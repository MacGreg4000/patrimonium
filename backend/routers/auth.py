"""Authentication router: login, logout, refresh, 2FA, CSRF."""
import base64
import json
import os
import secrets
from datetime import datetime, timezone

SECURE_COOKIES = os.getenv("SECURE_COOKIES", "false").lower() == "true"

from fastapi import APIRouter, Cookie, Depends, HTTPException, Request, Response, status
from pydantic import BaseModel, EmailStr
from slowapi import Limiter
from slowapi.util import get_remote_address
from sqlalchemy.orm import Session

import auth as auth_utils
import encryption as enc
import mailer
from database import get_db
from dependencies import get_current_user, log_audit
from models import PasswordResetToken, RefreshToken, User

router = APIRouter(prefix="/api/auth", tags=["auth"])
limiter = Limiter(key_func=get_remote_address)

# ── Schemas ───────────────────────────────────────────────

class LoginRequest(BaseModel):
    email: EmailStr
    password: str
    totp_code: str = ""

class TwoFASetupResponse(BaseModel):
    secret: str
    qr_png_b64: str
    uri: str

class TwoFAVerifyRequest(BaseModel):
    code: str

class TwoFADisableRequest(BaseModel):
    password: str
    code: str

# ── Login / Logout ────────────────────────────────────────

@router.post("/login")
@limiter.limit("10/minute")
def login(data: LoginRequest, request: Request, response: Response, db: Session = Depends(get_db)):
    user = db.query(User).filter(User.email == data.email.lower(), User.is_active == True).first()  # noqa: E712
    if not user or not auth_utils.verify_password(data.password, user.hashed_password):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Email ou mot de passe incorrect")

    if user.two_factor_enabled:
        if not data.totp_code:
            # Tell frontend 2FA is required
            return {"requires_2fa": True}
        secret = enc.decrypt_str(user.two_factor_secret)
        # Try TOTP first
        if not auth_utils.verify_totp(secret, data.totp_code):
            # Try backup codes
            if user.two_factor_backup:
                ok, updated = auth_utils.verify_backup_code(data.totp_code, user.two_factor_backup)
                if ok:
                    user.two_factor_backup = updated
                    db.commit()
                else:
                    raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Code 2FA invalide")
            else:
                raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Code 2FA invalide")

    access = auth_utils.create_access_token(user.id, user.role)
    refresh = auth_utils.create_refresh_token(user.id)

    db.add(RefreshToken(
        user_id=user.id,
        token_hash=auth_utils.hash_token(refresh),
        expires_at=auth_utils.refresh_token_expires_at(),
    ))
    db.commit()

    _set_cookies(response, access, refresh)
    log_audit(db, user.id, "LOGIN", f"Connexion de {user.email}", request)

    return {"ok": True, "user": {"id": user.id, "name": user.name, "email": user.email, "role": user.role}}


@router.post("/logout")
def logout(response: Response, refresh_token: str = Cookie(default=None), db: Session = Depends(get_db)):
    if refresh_token:
        token_hash = auth_utils.hash_token(refresh_token)
        rt = db.query(RefreshToken).filter(RefreshToken.token_hash == token_hash).first()
        if rt:
            rt.revoked = True
            db.commit()
    response.delete_cookie("access_token")
    response.delete_cookie("refresh_token")
    return {"ok": True}


@router.post("/refresh")
@limiter.limit("30/minute")
def refresh(request: Request, response: Response, refresh_token: str = Cookie(default=None), db: Session = Depends(get_db)):
    if not refresh_token:
        raise HTTPException(status_code=401, detail="Token manquant")
    payload = auth_utils.decode_token(refresh_token)
    if not payload or payload.get("type") != "refresh":
        raise HTTPException(status_code=401, detail="Token invalide")

    token_hash = auth_utils.hash_token(refresh_token)
    rt = db.query(RefreshToken).filter(RefreshToken.token_hash == token_hash).first()
    if not rt or rt.revoked:
        raise HTTPException(status_code=401, detail="Token révoqué ou inconnu")

    user = db.query(User).filter(User.id == int(payload["sub"]), User.is_active == True).first()  # noqa: E712
    if not user:
        raise HTTPException(status_code=401, detail="Utilisateur introuvable")

    # Rotate: revoke old, issue new
    rt.revoked = True
    access = auth_utils.create_access_token(user.id, user.role)
    new_refresh = auth_utils.create_refresh_token(user.id)
    db.add(RefreshToken(
        user_id=user.id,
        token_hash=auth_utils.hash_token(new_refresh),
        expires_at=auth_utils.refresh_token_expires_at(),
    ))
    db.commit()

    _set_cookies(response, access, new_refresh)
    return {"ok": True}


# ── CSRF ──────────────────────────────────────────────────

@router.get("/csrf")
def get_csrf(current_user: User = Depends(get_current_user)):
    return {"csrf_token": auth_utils.sign_csrf_token(current_user.id)}


# ── Current user ──────────────────────────────────────────

@router.get("/me")
def me(current_user: User = Depends(get_current_user)):
    return {
        "id": current_user.id,
        "name": current_user.name,
        "email": current_user.email,
        "role": current_user.role,
        "two_factor_enabled": current_user.two_factor_enabled,
    }


# ── 2FA ───────────────────────────────────────────────────

@router.get("/2fa/setup", response_model=TwoFASetupResponse)
def setup_2fa(current_user: User = Depends(get_current_user)):
    if current_user.two_factor_enabled:
        raise HTTPException(status_code=400, detail="2FA déjà activé")
    secret = auth_utils.generate_totp_secret()
    uri = auth_utils.get_totp_uri(secret, current_user.email)
    png = auth_utils.generate_qr_png(uri)
    return {
        "secret": secret,
        "qr_png_b64": base64.b64encode(png).decode(),
        "uri": uri,
    }


@router.post("/2fa/confirm")
def confirm_2fa(body: dict, request: Request, db: Session = Depends(get_db),
                current_user: User = Depends(get_current_user)):
    """Confirm 2FA setup by verifying a TOTP code against the new secret."""
    secret = body.get("secret", "")
    code = body.get("code", "")
    if not secret or not code:
        raise HTTPException(status_code=400, detail="Secret et code requis")
    if not auth_utils.verify_totp(secret, code):
        raise HTTPException(status_code=400, detail="Code invalide")
    # Encrypt and save
    raw_codes = auth_utils.generate_backup_codes()
    current_user.two_factor_secret = enc.encrypt_str(secret)
    current_user.two_factor_backup = auth_utils.hash_backup_codes(raw_codes)
    current_user.two_factor_enabled = True
    db.commit()
    log_audit(db, current_user.id, "2FA_ENABLED", "2FA activé", request)
    return {"ok": True, "backup_codes": raw_codes}


@router.post("/2fa/disable")
def disable_2fa(data: TwoFADisableRequest, request: Request, db: Session = Depends(get_db),
                current_user: User = Depends(get_current_user)):
    if not auth_utils.verify_password(data.password, current_user.hashed_password):
        raise HTTPException(status_code=401, detail="Mot de passe incorrect")
    if not current_user.two_factor_enabled:
        raise HTTPException(status_code=400, detail="2FA non activé")
    secret = enc.decrypt_str(current_user.two_factor_secret)
    if not auth_utils.verify_totp(secret, data.code):
        raise HTTPException(status_code=401, detail="Code 2FA invalide")
    current_user.two_factor_enabled = False
    current_user.two_factor_secret = None
    current_user.two_factor_backup = None
    db.commit()
    log_audit(db, current_user.id, "2FA_DISABLED", "2FA désactivé", request)
    return {"ok": True}


@router.get("/2fa/backup-codes")
def get_backup_codes(current_user: User = Depends(get_current_user)):
    if not current_user.two_factor_enabled or not current_user.two_factor_backup:
        raise HTTPException(status_code=400, detail="2FA non activé")
    codes = json.loads(current_user.two_factor_backup)
    return {"remaining": len(codes)}


@router.post("/2fa/regenerate-backup")
def regenerate_backup(request: Request, db: Session = Depends(get_db),
                      current_user: User = Depends(get_current_user)):
    if not current_user.two_factor_enabled:
        raise HTTPException(status_code=400, detail="2FA non activé")
    raw_codes = auth_utils.generate_backup_codes()
    current_user.two_factor_backup = auth_utils.hash_backup_codes(raw_codes)
    db.commit()
    log_audit(db, current_user.id, "2FA_BACKUP_REGEN", "Codes de secours régénérés", request)
    return {"backup_codes": raw_codes}


# ── Change password ───────────────────────────────────────

def _revoke_all_refresh_tokens(db: Session, user_id: int) -> None:
    """Révoque toutes les sessions actives d'un utilisateur (refresh tokens)."""
    db.query(RefreshToken).filter(
        RefreshToken.user_id == user_id,
        RefreshToken.revoked == False,  # noqa: E712
    ).update({"revoked": True})


@router.post("/change-password")
def change_password(body: dict, request: Request, db: Session = Depends(get_db),
                    current_user: User = Depends(get_current_user)):
    old_pw = body.get("old_password", "")
    new_pw = body.get("new_password", "")
    if not auth_utils.verify_password(old_pw, current_user.hashed_password):
        raise HTTPException(status_code=401, detail="Mot de passe actuel incorrect")
    if len(new_pw) < 8:
        raise HTTPException(status_code=400, detail="Mot de passe trop court (8 caractères minimum)")
    current_user.hashed_password = auth_utils.hash_password(new_pw)
    _revoke_all_refresh_tokens(db, current_user.id)
    db.commit()
    log_audit(db, current_user.id, "PASSWORD_CHANGED", "Mot de passe modifié", request)
    return {"ok": True}


# ── Password reset ────────────────────────────────────────

class ForgotPasswordRequest(BaseModel):
    email: EmailStr

class ResetPasswordRequest(BaseModel):
    token: str
    new_password: str


@router.post("/forgot-password")
@limiter.limit("5/minute")
def forgot_password(data: ForgotPasswordRequest, request: Request, db: Session = Depends(get_db)):
    user = db.query(User).filter(User.email == data.email.lower(), User.is_active == True).first()  # noqa: E712
    # Always return 200 to avoid email enumeration
    if not user:
        return {"ok": True}

    raw_token = secrets.token_urlsafe(32)
    token_hash = auth_utils.hash_token(raw_token)
    expires_at = auth_utils.password_reset_expires_at()

    # Invalidate any existing unused tokens for this user
    db.query(PasswordResetToken).filter(
        PasswordResetToken.user_id == user.id,
        PasswordResetToken.used == False,  # noqa: E712
    ).update({"used": True})

    db.add(PasswordResetToken(user_id=user.id, token_hash=token_hash, expires_at=expires_at))
    db.commit()

    try:
        mailer.send_password_reset(user.email, raw_token)
    except Exception:
        pass  # Don't leak SMTP errors to the client

    log_audit(db, user.id, "PASSWORD_RESET_REQUESTED", f"Demande de reset pour {user.email}", request)
    return {"ok": True}


@router.post("/reset-password")
@limiter.limit("5/minute")
def reset_password(data: ResetPasswordRequest, request: Request, db: Session = Depends(get_db)):
    if len(data.new_password) < 8:
        raise HTTPException(status_code=400, detail="Mot de passe trop court (8 caractères minimum)")

    token_hash = auth_utils.hash_token(data.token)
    rt = db.query(PasswordResetToken).filter(
        PasswordResetToken.token_hash == token_hash,
        PasswordResetToken.used == False,  # noqa: E712
    ).first()

    if not rt or rt.expires_at.replace(tzinfo=timezone.utc) < datetime.now(timezone.utc):
        raise HTTPException(status_code=400, detail="Token invalide ou expiré")

    user = db.query(User).filter(User.id == rt.user_id, User.is_active == True).first()  # noqa: E712
    if not user:
        raise HTTPException(status_code=400, detail="Utilisateur introuvable")

    user.hashed_password = auth_utils.hash_password(data.new_password)
    rt.used = True
    _revoke_all_refresh_tokens(db, user.id)
    db.commit()

    log_audit(db, user.id, "PASSWORD_RESET_DONE", f"Mot de passe réinitialisé pour {user.email}", request)
    return {"ok": True}


def _set_cookies(response: Response, access: str, refresh: str):
    response.set_cookie("access_token", access, httponly=True, samesite="strict",
                        secure=SECURE_COOKIES, max_age=3600)
    response.set_cookie("refresh_token", refresh, httponly=True, samesite="strict",
                        secure=SECURE_COOKIES, max_age=7 * 86400)
