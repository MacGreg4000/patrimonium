"""FastAPI dependency injection helpers."""
from fastapi import Cookie, Depends, HTTPException, Request, status
from sqlalchemy.orm import Session

import auth as auth_utils
from database import get_db
from models import User


def get_current_user(
    access_token: str = Cookie(default=None),
    db: Session = Depends(get_db),
) -> User:
    if not access_token:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Non authentifié")
    payload = auth_utils.decode_token(access_token)
    if not payload or payload.get("type") != "access":
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Token invalide")
    user = db.query(User).filter(User.id == int(payload["sub"]), User.is_active == True).first()  # noqa: E712
    if not user:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Utilisateur introuvable")
    return user


def require_admin(current_user: User = Depends(get_current_user)) -> User:
    if current_user.role != "ADMIN":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Accès administrateur requis")
    return current_user


def verify_csrf(request: Request, current_user: User = Depends(get_current_user)) -> User:
    """Check X-CSRF-Token header on mutating requests."""
    csrf_token = request.headers.get("X-CSRF-Token", "")
    if not auth_utils.verify_csrf_token(csrf_token, current_user.id):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Token CSRF invalide")
    return current_user


def audit(action: str, description: str = "", metadata: dict = None):
    """Helper to create an audit log entry (use inside routes)."""
    import json
    from models import AuditLog
    def _audit(
        request: Request,
        db: Session = Depends(get_db),
        current_user: User = Depends(get_current_user),
    ):
        log = AuditLog(
            user_id=current_user.id,
            action=action,
            description=description,
            metadata_=json.dumps(metadata) if metadata else None,
            ip_address=request.client.host if request.client else None,
            user_agent=request.headers.get("user-agent"),
        )
        db.add(log)
        db.commit()
    return _audit
