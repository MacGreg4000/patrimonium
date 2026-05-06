"""Coffres router: safes, movements, inventories, cash balance."""
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy.orm import Session

from database import get_db
from dependencies import get_current_user, log_audit, require_admin_csrf
from models import Coffre, Inventory, InventoryDetail, Movement, MovementDetail, User

router = APIRouter(prefix="/api", tags=["coffres"])

DENOMINATIONS = [5, 10, 20, 50, 100, 200, 500]


# ── Schemas ───────────────────────────────────────────────

class BilletDetail(BaseModel):
    denomination: float
    quantity: int

class MovementCreate(BaseModel):
    coffre_id: int
    type: str         # ENTRY | EXIT
    amount: float
    description: Optional[str] = None
    details: list[BilletDetail] = []

class InventoryCreate(BaseModel):
    coffre_id: int
    total_amount: float
    notes: Optional[str] = None
    details: list[BilletDetail] = []

class MovementUpdate(BaseModel):
    amount: float
    description: Optional[str] = None


# ── Balance computation ───────────────────────────────────

def compute_balance(coffre_id: int, db: Session) -> float:
    """Compute current balance from last inventory + subsequent movements."""
    last_inv = (
        db.query(Inventory)
        .filter(Inventory.coffre_id == coffre_id, Inventory.deleted_at.is_(None))
        .order_by(Inventory.date.desc())
        .first()
    )
    if last_inv:
        base = last_inv.total_amount
        base_date = last_inv.date
    else:
        base = 0.0
        base_date = None

    q = db.query(Movement).filter(
        Movement.coffre_id == coffre_id,
        Movement.deleted_at.is_(None),
    )
    if base_date:
        q = q.filter(Movement.created_at > base_date)

    for m in q.all():
        if m.type == "ENTRY":
            base += m.amount
        else:
            base -= m.amount
    return base


# ── Coffres ───────────────────────────────────────────────

@router.get("/coffres")
def list_coffres(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    coffres = db.query(Coffre).filter(Coffre.is_active == True).order_by(Coffre.name).all()  # noqa: E712
    return [
        {"id": c.id, "name": c.name, "description": c.description,
         "balance": compute_balance(c.id, db)}
        for c in coffres
    ]


@router.get("/coffres/{coffre_id}/balance")
def get_balance(coffre_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    coffre = db.query(Coffre).filter(Coffre.id == coffre_id).first()
    if not coffre:
        raise HTTPException(status_code=404, detail="Coffre introuvable")
    return {"coffre_id": coffre_id, "balance": compute_balance(coffre_id, db)}


# ── Movements ─────────────────────────────────────────────

@router.get("/movements")
def list_movements(
    coffre_id: Optional[int] = None,
    page: int = 1, limit: int = 50,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    q = db.query(Movement).filter(Movement.deleted_at.is_(None))
    if coffre_id:
        q = q.filter(Movement.coffre_id == coffre_id)
    total = q.count()
    items = q.order_by(Movement.created_at.desc()).offset((page - 1) * limit).limit(min(limit, 100)).all()
    return {"total": total, "page": page, "limit": limit,
            "items": [_fmt_movement(m) for m in items]}


@router.post("/movements", status_code=201)
def create_movement(data: MovementCreate, request: Request,
                    db: Session = Depends(get_db), user: User = Depends(require_admin_csrf)):
    if data.type not in ("ENTRY", "EXIT"):
        raise HTTPException(status_code=400, detail="Type invalide")
    coffre = db.query(Coffre).filter(Coffre.id == data.coffre_id, Coffre.is_active == True).first()  # noqa: E712
    if not coffre:
        raise HTTPException(status_code=404, detail="Coffre introuvable")
    mv = Movement(coffre_id=data.coffre_id, user_id=user.id,
                  type=data.type, amount=data.amount, description=data.description)
    db.add(mv)
    db.flush()
    for d in data.details:
        if d.denomination in DENOMINATIONS and d.quantity > 0:
            db.add(MovementDetail(movement_id=mv.id, denomination=d.denomination, quantity=d.quantity))
    db.commit()
    db.refresh(mv)
    log_audit(db, user.id, "MOVEMENT_CREATED",
              f"{data.type} {data.amount}€ — coffre '{coffre.name}'", request)
    return _fmt_movement(mv)


@router.put("/movements/{movement_id}")
def update_movement(movement_id: int, data: MovementUpdate, request: Request,
                    db: Session = Depends(get_db), user: User = Depends(require_admin_csrf)):
    mv = db.query(Movement).filter(Movement.id == movement_id, Movement.deleted_at.is_(None)).first()
    if not mv:
        raise HTTPException(status_code=404, detail="Mouvement introuvable")
    mv.amount = data.amount
    mv.description = data.description
    db.commit()
    log_audit(db, user.id, "MOVEMENT_UPDATED", f"Mouvement #{movement_id} modifié", request)
    return {"ok": True}


@router.delete("/movements/{movement_id}")
def delete_movement(movement_id: int, request: Request,
                    db: Session = Depends(get_db), user: User = Depends(require_admin_csrf)):
    mv = db.query(Movement).filter(Movement.id == movement_id, Movement.deleted_at.is_(None)).first()
    if not mv:
        raise HTTPException(status_code=404, detail="Mouvement introuvable")
    from datetime import datetime, timezone
    mv.deleted_at = datetime.now(timezone.utc)
    db.commit()
    log_audit(db, user.id, "MOVEMENT_DELETED", f"Mouvement #{movement_id} supprimé", request)
    return {"ok": True}


# ── Inventories ───────────────────────────────────────────

@router.get("/inventories")
def list_inventories(
    coffre_id: Optional[int] = None,
    page: int = 1, limit: int = 50,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    q = db.query(Inventory).filter(Inventory.deleted_at.is_(None))
    if coffre_id:
        q = q.filter(Inventory.coffre_id == coffre_id)
    total = q.count()
    items = q.order_by(Inventory.date.desc()).offset((page - 1) * limit).limit(min(limit, 100)).all()
    return {"total": total, "page": page, "limit": limit,
            "items": [_fmt_inventory(i) for i in items]}


@router.post("/inventories", status_code=201)
def create_inventory(data: InventoryCreate, request: Request,
                     db: Session = Depends(get_db), user: User = Depends(require_admin_csrf)):
    coffre = db.query(Coffre).filter(Coffre.id == data.coffre_id, Coffre.is_active == True).first()  # noqa: E712
    if not coffre:
        raise HTTPException(status_code=404, detail="Coffre introuvable")
    total = sum(d.denomination * d.quantity for d in data.details) if data.details else data.total_amount
    inv = Inventory(coffre_id=data.coffre_id, user_id=user.id,
                    total_amount=total, notes=data.notes)
    db.add(inv)
    db.flush()
    for d in data.details:
        if d.denomination in DENOMINATIONS and d.quantity >= 0:
            db.add(InventoryDetail(inventory_id=inv.id, denomination=d.denomination, quantity=d.quantity))
    db.commit()
    db.refresh(inv)
    log_audit(db, user.id, "INVENTORY_CREATED",
              f"Inventaire {total}€ — coffre '{coffre.name}'", request)
    return _fmt_inventory(inv)


@router.delete("/inventories/{inventory_id}")
def delete_inventory(inventory_id: int, request: Request,
                     db: Session = Depends(get_db), user: User = Depends(require_admin_csrf)):
    inv = db.query(Inventory).filter(Inventory.id == inventory_id, Inventory.deleted_at.is_(None)).first()
    if not inv:
        raise HTTPException(status_code=404, detail="Inventaire introuvable")
    from datetime import datetime, timezone
    inv.deleted_at = datetime.now(timezone.utc)
    db.commit()
    log_audit(db, user.id, "INVENTORY_DELETED", f"Inventaire #{inventory_id} supprimé", request)
    return {"ok": True}


# ── Denomination breakdown ────────────────────────────────

@router.get("/coffres/{coffre_id}/breakdown")
def get_breakdown(coffre_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    """Current denomination breakdown: last inventory + movements since."""
    coffre = db.query(Coffre).filter(Coffre.id == coffre_id).first()
    if not coffre:
        raise HTTPException(status_code=404, detail="Coffre introuvable")

    last_inv = (
        db.query(Inventory)
        .filter(Inventory.coffre_id == coffre_id, Inventory.deleted_at.is_(None))
        .order_by(Inventory.date.desc())
        .first()
    )

    counts: dict[float, int] = {float(d): 0 for d in DENOMINATIONS}
    base_date = None

    if last_inv:
        base_date = last_inv.date
        for d in last_inv.details:
            if d.denomination in counts:
                counts[d.denomination] = d.quantity

    q = db.query(Movement).filter(
        Movement.coffre_id == coffre_id,
        Movement.deleted_at.is_(None),
    )
    if base_date:
        q = q.filter(Movement.created_at > base_date)

    for mv in q.order_by(Movement.created_at).all():
        sign = 1 if mv.type == "ENTRY" else -1
        for d in mv.details:
            if d.denomination in counts:
                counts[d.denomination] += sign * d.quantity

    breakdown = [
        {"denomination": int(d), "quantity": counts[d], "subtotal": d * counts[d]}
        for d in sorted(counts.keys(), reverse=True)
        if counts[d] > 0
    ]

    return {
        "coffre_id": coffre_id,
        "has_data": last_inv is not None,
        "last_inventory_date": last_inv.date if last_inv else None,
        "breakdown": breakdown,
        "total": sum(b["subtotal"] for b in breakdown),
    }


# ── History (unified movements + inventories) ─────────────

@router.get("/coffres/{coffre_id}/history")
def get_history(coffre_id: int, page: int = 1, limit: int = 50,
                db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    coffre = db.query(Coffre).filter(Coffre.id == coffre_id).first()
    if not coffre:
        raise HTTPException(status_code=404, detail="Coffre introuvable")

    # Charger tous les enregistrements puis paginer sur le résultat fusionné
    mvs = (db.query(Movement)
           .filter(Movement.coffre_id == coffre_id, Movement.deleted_at.is_(None))
           .order_by(Movement.created_at.desc()).all())

    invs = (db.query(Inventory)
            .filter(Inventory.coffre_id == coffre_id, Inventory.deleted_at.is_(None))
            .order_by(Inventory.date.desc()).all())

    items = (
        [{"kind": "movement", **_fmt_movement(m)} for m in mvs]
        + [{"kind": "inventory", **_fmt_inventory(i)} for i in invs]
    )
    items.sort(key=lambda x: x.get("created_at") or x.get("date") or "", reverse=True)

    total = len(items)
    offset = (page - 1) * limit
    return {"total": total, "page": page, "limit": limit, "items": items[offset:offset + limit]}


# ── Formatters ────────────────────────────────────────────

def _fmt_movement(m: Movement) -> dict:
    return {
        "id": m.id, "coffre_id": m.coffre_id, "user_id": m.user_id,
        "type": m.type, "amount": m.amount, "description": m.description,
        "created_at": m.created_at,
        "details": [{"denomination": d.denomination, "quantity": d.quantity} for d in m.details],
    }


def _fmt_inventory(i: Inventory) -> dict:
    return {
        "id": i.id, "coffre_id": i.coffre_id, "user_id": i.user_id,
        "total_amount": i.total_amount, "notes": i.notes, "date": i.date,
        "details": [{"denomination": d.denomination, "quantity": d.quantity} for d in i.details],
    }
