"""Gestion des jetons d'API en lecture seule (connecteur MCP)."""
import secrets

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy.orm import Session

import auth as auth_utils
from database import get_db
from dependencies import get_current_user, log_audit, require_admin_csrf
from models import ApiToken, User

router = APIRouter(prefix="/api/tokens", tags=["tokens"])

TOKEN_PREFIX = "ptm_ro_"      # ro = read-only, identifiable d'un coup d'œil


class TokenCreate(BaseModel):
    label: str


@router.get("")
def list_tokens(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    tokens = (db.query(ApiToken)
                .filter(ApiToken.user_id == user.id, ApiToken.revoked == False)  # noqa: E712
                .order_by(ApiToken.created_at.desc()).all())
    return [_fmt(t) for t in tokens]


@router.post("", status_code=201)
def create_token(data: TokenCreate, request: Request,
                 db: Session = Depends(get_db), user: User = Depends(require_admin_csrf)):
    """Crée un jeton de lecture. Le jeton brut n'est affiché qu'une seule fois."""
    label = data.label.strip()
    if not label:
        raise HTTPException(status_code=400, detail="Un nom est requis")

    raw = TOKEN_PREFIX + secrets.token_urlsafe(32)
    token = ApiToken(
        user_id=user.id,
        label=label,
        token_hash=auth_utils.hash_token(raw),   # seul le SHA-256 est conservé
        scope="read",
    )
    db.add(token)
    db.commit()
    db.refresh(token)
    log_audit(db, user.id, "API_TOKEN_CREATED", f"Jeton de lecture créé : {label}", request)
    # `token` n'est renvoyé qu'ici : il est irrécupérable ensuite.
    return {**_fmt(token), "token": raw}


@router.delete("/{token_id}")
def revoke_token(token_id: int, request: Request,
                 db: Session = Depends(get_db), user: User = Depends(require_admin_csrf)):
    token = db.query(ApiToken).filter(ApiToken.id == token_id,
                                      ApiToken.user_id == user.id).first()
    if not token:
        raise HTTPException(status_code=404, detail="Jeton introuvable")
    token.revoked = True
    db.commit()
    log_audit(db, user.id, "API_TOKEN_REVOKED", f"Jeton révoqué : {token.label}", request)
    return {"ok": True}


def _fmt(t: ApiToken) -> dict:
    """Ne renvoie jamais le jeton, ni même son empreinte."""
    return {
        "id": t.id,
        "label": t.label,
        "scope": t.scope,
        "created_at": t.created_at,
        "last_used_at": t.last_used_at,
    }
