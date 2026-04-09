"""Authentication router: login, logout, refresh, 2FA, CSRF."""
import base64
import json
import os
from datetime import datetime, timezone

SECURE_COOKIES = os.getenv("SECURE_COOKIES", "false").lower() == "true"

from fastapi import APIRouter, Cookie, Depends, HTTPException, Request, Response, status
from pydantic import BaseModel, EmailStr
from slowapi import Limiter
from slowapi.util import get_remote_address
from sqlalchemy.orm import Session

import auth as auth_utils
import encryption as enc
from database import get_db
from dependencies import get_current_user
from models import AuditLog, User

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

    _set_cookies(response, access, refresh)
    _audit(db, user.id, "LOGIN", f"Connexion de {user.email}", request)

    return {"ok": True, "user": {"id": user.id, "name": user.name, "email": user.email, "role": user.role}}


@router.post("/logout")
def logout(response: Response, access_token: str = Cookie(default=None), db: Session = Depends(get_db)):
    response.delete_cookie("access_token")
    response.delete_cookie("refresh_token")
    return {"ok": True}


@router.post("/refresh")
def refresh(response: Response, refresh_token: str = Cookie(default=None), db: Session = Depends(get_db)):
    if not refresh_token:
        raise HTTPException(status_code=401, detail="Token manquant")
    payload = auth_utils.decode_token(refresh_token)
    if not payload or payload.get("type") != "refresh":
        raise HTTPException(status_code=401, detail="Token invalide")
    user = db.query(User).filter(User.id == int(payload["sub"]), User.is_active == True).first()  # noqa: E712
    if not user:
        raise HTTPException(status_code=401, detail="Utilisateur introuvable")
    access = auth_utils.create_access_token(user.id, user.role)
    new_refresh = auth_utils.create_refresh_token(user.id)
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


@router.post("/2fa/activate")
def activate_2fa(data: TwoFAVerifyRequest, request: Request, db: Session = Depends(get_db),
                 current_user: User = Depends(get_current_user)):
    # The secret was generated in setup — client sends it back with the code to confirm
    raise HTTPException(status_code=400, detail="Envoyez secret + code via /2fa/confirm")


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
    _audit(db, current_user.id, "2FA_ENABLED", "2FA activé", request)
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
    _audit(db, current_user.id, "2FA_DISABLED", "2FA désactivé", request)
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
    _audit(db, current_user.id, "2FA_BACKUP_REGEN", "Codes de secours régénérés", request)
    return {"backup_codes": raw_codes}


# ── Change password ───────────────────────────────────────

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
    db.commit()
    _audit(db, current_user.id, "PASSWORD_CHANGED", "Mot de passe modifié", request)
    return {"ok": True}


# ── Private helpers ───────────────────────────────────────

def _set_cookies(response: Response, access: str, refresh: str):
    response.set_cookie("access_token", access, httponly=True, samesite="strict",
                        secure=SECURE_COOKIES, max_age=3600)
    response.set_cookie("refresh_token", refresh, httponly=True, samesite="strict",
                        secure=SECURE_COOKIES, max_age=7 * 86400)


def _audit(db: Session, user_id: int, action: str, description: str, request: Request):
    log = AuditLog(
        user_id=user_id, action=action, description=description,
        ip_address=request.client.host if request.client else None,
        user_agent=request.headers.get("user-agent"),
    )
    db.add(log)
    db.commit()
