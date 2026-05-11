"""Reserves router: réserves de liquidation / dividendes société."""
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy.orm import Session

from database import get_db
from dependencies import get_current_user, log_audit, require_admin_csrf
from models import Reserve, User

router = APIRouter(prefix="/api/reserves", tags=["reserves"])

MONTHS_FR = ["Jan", "Fév", "Mar", "Avr", "Mai", "Jun",
             "Jul", "Aoû", "Sep", "Oct", "Nov", "Déc"]


class ReserveCreate(BaseModel):
    year: int
    month: int = 1
    amount: float = 0.0
    release_year: Optional[int] = None
    released: float = 0.0
    precompte_paye: float = 0.0
    notes: Optional[str] = None

class ReserveUpdate(BaseModel):
    amount: Optional[float] = None
    release_year: Optional[int] = None
    released: Optional[float] = None
    precompte_paye: Optional[float] = None
    notes: Optional[str] = None

class ReserveLiberate(BaseModel):
    montant: float          # montant brut libéré
    precompte: float = 0.0  # précompte mobilier exact payé


@router.get("")
def list_reserves(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    reserves = (
        db.query(Reserve)
        .filter(Reserve.user_id == user.id)
        .order_by(Reserve.year.desc(), Reserve.month.desc())
        .all()
    )
    total_amount    = sum(r.amount for r in reserves)
    total_released  = sum(r.released for r in reserves)
    total_precompte = sum(r.precompte_paye for r in reserves)
    total_releasable = sum(r.amount - r.released for r in reserves if r.amount > r.released)
    return {
        "stats": {
            "total_amount":     total_amount,
            "total_released":   total_released,
            "total_precompte":  total_precompte,
            "total_releasable": total_releasable,
            "total_net_recu":   total_released - total_precompte,
        },
        "items": [_fmt(r) for r in reserves],
    }


@router.post("", status_code=201)
def create_reserve(data: ReserveCreate, request: Request,
                   db: Session = Depends(get_db), user: User = Depends(require_admin_csrf)):
    existing = db.query(Reserve).filter(
        Reserve.user_id == user.id, Reserve.year == data.year, Reserve.month == data.month
    ).first()
    if existing:
        raise HTTPException(status_code=400, detail="Réserve déjà existante pour cette période")
    r = Reserve(user_id=user.id, **data.model_dump())
    db.add(r)
    db.commit()
    db.refresh(r)
    log_audit(db, user.id, "RESERVE_CREATED",
              f"Réserve créée: {data.year} — {data.amount}€", request)
    return _fmt(r)


@router.post("/{reserve_id}/liberate")
def liberate_reserve(reserve_id: int, data: ReserveLiberate, request: Request,
                     db: Session = Depends(get_db), user: User = Depends(require_admin_csrf)):
    """Enregistre une libération partielle ou totale avec le précompte exact payé."""
    r = db.query(Reserve).filter(Reserve.id == reserve_id, Reserve.user_id == user.id).first()
    if not r:
        raise HTTPException(status_code=404, detail="Réserve introuvable")
    releasable = max(0.0, r.amount - r.released)
    if data.montant <= 0:
        raise HTTPException(status_code=400, detail="Le montant doit être positif")
    if data.montant > releasable + 0.01:
        raise HTTPException(status_code=400,
                            detail=f"Montant supérieur au solde libérable ({releasable:.2f} €)")
    r.released       += data.montant
    r.precompte_paye += data.precompte
    db.commit()
    log_audit(db, user.id, "RESERVE_LIBERATED",
              f"Réserve {r.year} : {data.montant}€ libérés, précompte {data.precompte}€", request)
    return _fmt(r)


@router.post("/initialize")
def initialize_reserves(request: Request,
                        db: Session = Depends(get_db), user: User = Depends(require_admin_csrf)):
    """Auto-create empty rows for 2013–2035 if they don't exist."""
    created = 0
    for year in range(2013, 2036):
        for month in range(1, 13):
            exists = db.query(Reserve).filter(
                Reserve.user_id == user.id, Reserve.year == year, Reserve.month == month
            ).first()
            if not exists:
                db.add(Reserve(user_id=user.id, year=year, month=month))
                created += 1
    db.commit()
    log_audit(db, user.id, "RESERVES_INITIALIZED",
              f"{created} réserves initialisées (2013–2035)", request)
    return {"created": created}


@router.put("/{reserve_id}")
def update_reserve(reserve_id: int, data: ReserveUpdate, request: Request,
                   db: Session = Depends(get_db), user: User = Depends(require_admin_csrf)):
    r = db.query(Reserve).filter(Reserve.id == reserve_id, Reserve.user_id == user.id).first()
    if not r:
        raise HTTPException(status_code=404, detail="Réserve introuvable")
    for k, v in data.model_dump(exclude_none=True).items():
        setattr(r, k, v)
    db.commit()
    log_audit(db, user.id, "RESERVE_UPDATED",
              f"Réserve modifiée: {r.year}", request)
    return _fmt(r)


@router.delete("/{reserve_id}")
def delete_reserve(reserve_id: int, request: Request,
                   db: Session = Depends(get_db), user: User = Depends(require_admin_csrf)):
    r = db.query(Reserve).filter(Reserve.id == reserve_id, Reserve.user_id == user.id).first()
    if not r:
        raise HTTPException(status_code=404, detail="Réserve introuvable")
    db.delete(r)
    db.commit()
    log_audit(db, user.id, "RESERVE_DELETED", f"Réserve supprimée: {r.year}", request)
    return {"ok": True}


def _fmt(r: Reserve) -> dict:
    return {
        "id": r.id, "year": r.year, "month": r.month,
        "month_label": MONTHS_FR[r.month - 1],
        "amount": r.amount, "release_year": r.release_year,
        "released": r.released, "precompte_paye": r.precompte_paye or 0.0,
        "net_recu": (r.released or 0.0) - (r.precompte_paye or 0.0),
        "releasable": max(0.0, r.amount - (r.released or 0.0)),
        "notes": r.notes, "updated_at": r.updated_at,
    }
