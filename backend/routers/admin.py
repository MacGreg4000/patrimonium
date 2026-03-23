"""Admin router: user & coffre management."""
from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, EmailStr
from sqlalchemy.orm import Session

import auth as auth_utils
from database import get_db
from dependencies import require_admin
from models import AuditLog, Coffre, Movement, User

router = APIRouter(prefix="/api/admin", tags=["admin"])


# ── Schemas ───────────────────────────────────────────────

class UserCreate(BaseModel):
    email: EmailStr
    name: str
    password: str
    role: str = "USER"

class UserUpdate(BaseModel):
    name: str | None = None
    role: str | None = None
    is_active: bool | None = None

class CoffreCreate(BaseModel):
    name: str
    description: str | None = None

class CoffreUpdate(BaseModel):
    name: str | None = None
    description: str | None = None
    is_active: bool | None = None


# ── Users ─────────────────────────────────────────────────

@router.get("/users")
def list_users(db: Session = Depends(get_db), admin: User = Depends(require_admin)):
    users = db.query(User).order_by(User.created_at).all()
    return [
        {"id": u.id, "email": u.email, "name": u.name, "role": u.role,
         "is_active": u.is_active, "two_factor_enabled": u.two_factor_enabled,
         "created_at": u.created_at}
        for u in users
    ]


@router.post("/users", status_code=201)
def create_user(data: UserCreate, request: Request, db: Session = Depends(get_db),
                admin: User = Depends(require_admin)):
    if db.query(User).filter(User.email == data.email.lower()).first():
        raise HTTPException(status_code=400, detail="Email déjà utilisé")
    if data.role not in ("ADMIN", "USER"):
        raise HTTPException(status_code=400, detail="Rôle invalide")
    user = User(
        email=data.email.lower(),
        name=data.name,
        hashed_password=auth_utils.hash_password(data.password),
        role=data.role,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    _audit(db, admin.id, "USER_CREATED", f"Utilisateur créé: {user.email}", request)
    return {"id": user.id, "email": user.email, "name": user.name, "role": user.role}


@router.put("/users/{user_id}")
def update_user(user_id: int, data: UserUpdate, request: Request,
                db: Session = Depends(get_db), admin: User = Depends(require_admin)):
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="Utilisateur introuvable")
    if user_id == admin.id and data.role == "USER":
        raise HTTPException(status_code=400, detail="Impossible de se retirer les droits admin")
    if data.name is not None:
        user.name = data.name
    if data.role is not None:
        user.role = data.role
    if data.is_active is not None:
        user.is_active = data.is_active
    db.commit()
    _audit(db, admin.id, "USER_UPDATED", f"Utilisateur modifié: {user.email}", request)
    return {"ok": True}


@router.delete("/users/{user_id}")
def delete_user(user_id: int, request: Request, db: Session = Depends(get_db),
                admin: User = Depends(require_admin)):
    if user_id == admin.id:
        raise HTTPException(status_code=400, detail="Impossible de supprimer son propre compte")
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="Utilisateur introuvable")
    email = user.email
    db.delete(user)
    db.commit()
    _audit(db, admin.id, "USER_DELETED", f"Utilisateur supprimé: {email}", request)
    return {"ok": True}


@router.post("/users/{user_id}/reset-password")
def reset_password(user_id: int, body: dict, request: Request,
                   db: Session = Depends(get_db), admin: User = Depends(require_admin)):
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="Utilisateur introuvable")
    new_pw = body.get("password", "")
    if len(new_pw) < 8:
        raise HTTPException(status_code=400, detail="Mot de passe trop court")
    user.hashed_password = auth_utils.hash_password(new_pw)
    db.commit()
    _audit(db, admin.id, "PASSWORD_RESET", f"Mot de passe réinitialisé pour: {user.email}", request)
    return {"ok": True}


# ── Coffres ───────────────────────────────────────────────

@router.get("/coffres")
def list_coffres(db: Session = Depends(get_db), admin: User = Depends(require_admin)):
    coffres = db.query(Coffre).order_by(Coffre.created_at).all()
    return [
        {"id": c.id, "name": c.name, "description": c.description,
         "is_active": c.is_active, "created_at": c.created_at}
        for c in coffres
    ]


@router.post("/coffres", status_code=201)
def create_coffre(data: CoffreCreate, request: Request, db: Session = Depends(get_db),
                  admin: User = Depends(require_admin)):
    coffre = Coffre(name=data.name, description=data.description)
    db.add(coffre)
    db.commit()
    db.refresh(coffre)
    _audit(db, admin.id, "COFFRE_CREATED", f"Coffre créé: {coffre.name}", request)
    return {"id": coffre.id, "name": coffre.name}


@router.put("/coffres/{coffre_id}")
def update_coffre(coffre_id: int, data: CoffreUpdate, request: Request,
                  db: Session = Depends(get_db), admin: User = Depends(require_admin)):
    coffre = db.query(Coffre).filter(Coffre.id == coffre_id).first()
    if not coffre:
        raise HTTPException(status_code=404, detail="Coffre introuvable")
    if data.name is not None:
        coffre.name = data.name
    if data.description is not None:
        coffre.description = data.description
    if data.is_active is not None:
        coffre.is_active = data.is_active
    db.commit()
    _audit(db, admin.id, "COFFRE_UPDATED", f"Coffre modifié: {coffre.name}", request)
    return {"ok": True}


@router.delete("/coffres/{coffre_id}")
def delete_coffre(coffre_id: int, request: Request, db: Session = Depends(get_db),
                  admin: User = Depends(require_admin)):
    coffre = db.query(Coffre).filter(Coffre.id == coffre_id).first()
    if not coffre:
        raise HTTPException(status_code=404, detail="Coffre introuvable")
    # Only delete if balance is 0
    from routers.coffres import compute_balance
    bal = compute_balance(coffre_id, db)
    if abs(bal) > 0.01:
        raise HTTPException(status_code=400, detail=f"Solde non nul ({bal:.2f} €) — videz le coffre avant suppression")
    db.delete(coffre)
    db.commit()
    _audit(db, admin.id, "COFFRE_DELETED", f"Coffre supprimé: {coffre.name}", request)
    return {"ok": True}


# ── Audit logs ────────────────────────────────────────────

@router.get("/logs")
def get_logs(limit: int = 100, offset: int = 0,
             db: Session = Depends(get_db), admin: User = Depends(require_admin)):
    logs = (
        db.query(AuditLog)
        .order_by(AuditLog.created_at.desc())
        .offset(offset).limit(min(limit, 500))
        .all()
    )
    return [
        {"id": l.id, "user_id": l.user_id, "action": l.action,
         "description": l.description, "ip_address": l.ip_address,
         "created_at": l.created_at}
        for l in logs
    ]


# ── Private helpers ───────────────────────────────────────

def _audit(db: Session, user_id: int, action: str, description: str, request: Request):
    log = AuditLog(
        user_id=user_id, action=action, description=description,
        ip_address=request.client.host if request.client else None,
        user_agent=request.headers.get("user-agent"),
    )
    db.add(log)
    db.commit()
