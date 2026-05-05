"""Authentication helpers: JWT, bcrypt, TOTP."""
import hashlib
import io
import json
import os
import secrets
from datetime import datetime, timedelta, timezone
from typing import Optional

import bcrypt
import pyotp
import qrcode
from jose import JWTError, jwt

import encryption as enc

SECRET_KEY = os.getenv("SECRET_KEY", "change-this-in-production")
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 60
REFRESH_TOKEN_EXPIRE_DAYS = 7

# ── Passwords ─────────────────────────────────────────────

def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()

def verify_password(plain: str, hashed: str) -> bool:
    try:
        return bcrypt.checkpw(plain.encode(), hashed.encode())
    except Exception:
        return False

# ── JWT ───────────────────────────────────────────────────

def create_access_token(user_id: int, role: str) -> str:
    expire = datetime.now(timezone.utc) + timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    return jwt.encode(
        {"sub": str(user_id), "role": role, "exp": expire, "type": "access"},
        SECRET_KEY, algorithm=ALGORITHM,
    )

def create_refresh_token(user_id: int) -> str:
    expire = datetime.now(timezone.utc) + timedelta(days=REFRESH_TOKEN_EXPIRE_DAYS)
    return jwt.encode(
        {"sub": str(user_id), "exp": expire, "type": "refresh", "jti": secrets.token_hex(16)},
        SECRET_KEY, algorithm=ALGORITHM,
    )

def hash_token(token: str) -> str:
    """SHA-256 hex of a raw JWT — used as DB key for refresh token rotation."""
    return hashlib.sha256(token.encode()).hexdigest()

def refresh_token_expires_at() -> datetime:
    return datetime.now(timezone.utc) + timedelta(days=REFRESH_TOKEN_EXPIRE_DAYS)

def password_reset_expires_at() -> datetime:
    return datetime.now(timezone.utc) + timedelta(hours=1)

def decode_token(token: str) -> Optional[dict]:
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        return payload
    except JWTError:
        return None

# ── TOTP 2FA ──────────────────────────────────────────────

def generate_totp_secret() -> str:
    return pyotp.random_base32()

def get_totp_uri(secret: str, email: str) -> str:
    totp = pyotp.TOTP(secret)
    return totp.provisioning_uri(name=email, issuer_name="Patrimonium")

def generate_qr_png(uri: str) -> bytes:
    img = qrcode.make(uri)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()

def verify_totp(secret: str, code: str) -> bool:
    totp = pyotp.TOTP(secret)
    return totp.verify(code, valid_window=1)

def generate_backup_codes(n: int = 10) -> list[str]:
    return [secrets.token_hex(4).upper() for _ in range(n)]

def hash_backup_codes(codes: list[str]) -> str:
    hashed = [bcrypt.hashpw(c.encode(), bcrypt.gensalt()).decode() for c in codes]
    return json.dumps(hashed)

def verify_backup_code(code: str, hashed_json: str) -> tuple[bool, Optional[str]]:
    """Returns (matched, updated_hashed_json) — removes used code."""
    codes = json.loads(hashed_json)
    for i, h in enumerate(codes):
        try:
            matched = bcrypt.checkpw(code.upper().encode(), h.encode())
        except Exception:
            matched = False
        if matched:
            codes.pop(i)
            return True, json.dumps(codes)
    return False, None

# ── CSRF ──────────────────────────────────────────────────

def generate_csrf_token() -> str:
    return secrets.token_urlsafe(32)

def sign_csrf_token(user_id: int) -> str:
    expire = datetime.now(timezone.utc) + timedelta(hours=8)
    return jwt.encode(
        {"sub": str(user_id), "exp": expire, "type": "csrf"},
        SECRET_KEY, algorithm=ALGORITHM,
    )

def verify_csrf_token(token: str, user_id: int) -> bool:
    payload = decode_token(token)
    if not payload:
        return False
    return payload.get("type") == "csrf" and int(payload.get("sub", -1)) == user_id
