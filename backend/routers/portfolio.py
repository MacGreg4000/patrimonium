"""Stock portfolio router: positions, purchases, market data."""
from datetime import datetime, timezone
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy.orm import Session

import calculations
import market_data as md
from database import get_db
from dependencies import get_current_user, log_audit, require_admin_csrf
from models import Position, PortfolioSnapshot, Purchase, Sale, User

router = APIRouter(prefix="/api/portfolio", tags=["portfolio"])


# ── Schemas ───────────────────────────────────────────────

class PositionCreate(BaseModel):
    display_name: str
    ticker: str
    asset_type: str
    currency: str = "EUR"
    alert_gain_pct: Optional[float] = None
    alert_loss_pct: Optional[float] = None

class PositionUpdate(PositionCreate):
    is_active: Optional[bool] = None

class PurchaseCreate(BaseModel):
    purchase_date: str   # ISO date
    quantity: float
    unit_price: float
    fees: float = 0.0
    note: Optional[str] = None

class ManualPriceUpdate(BaseModel):
    price: float


# ── Helpers ───────────────────────────────────────────────

def _build_position(pos: Position, portfolio_total: float) -> dict:
    if pos.ticker == "MANUAL":
        price_eur = pos.manual_price or 0.0
        prev_eur = price_eur
        day_pct = 0.0
        raw_price = price_eur
    else:
        price_eur, prev_eur, day_pct = md.get_price_eur(pos.ticker, pos.currency)
        raw = md._price_cache.get(pos.ticker, {})
        raw_price = raw.get("price")

    metrics = calculations.calc_position_metrics(pos, price_eur or 0.0, prev_eur or 0.0, portfolio_total)
    return {
        "id": pos.id,
        "display_name": pos.display_name,
        "ticker": pos.ticker,
        "asset_type": pos.asset_type,
        "currency": pos.currency,
        "is_active": pos.is_active,
        "alert_gain_pct": pos.alert_gain_pct,
        "alert_loss_pct": pos.alert_loss_pct,
        "current_price": raw_price,
        "current_price_eur": price_eur,
        "day_change_pct": day_pct,
        "manual_price": pos.manual_price,
        "manual_price_updated_at": pos.manual_price_updated_at,
        **metrics,
        "purchases": [
            {"id": p.id, "position_id": p.position_id, "purchase_date": str(p.purchase_date),
             "quantity": p.quantity, "unit_price": p.unit_price, "fees": p.fees,
             "note": p.note, "created_at": p.created_at}
            for p in pos.purchases
        ],
        "sales": [
            {"id": s.id, "sale_date": str(s.sale_date), "quantity": s.quantity,
             "unit_price": s.unit_price, "fees": s.fees,
             "realized_pnl": s.realized_pnl, "note": s.note}
            for s in pos.sales
        ],
    }


def _all_positions_with_total(db: Session) -> tuple[list, float]:
    positions = db.query(Position).filter(Position.is_active == True).all()  # noqa: E712
    total = 0.0
    for pos in positions:
        if pos.ticker == "MANUAL":
            p = pos.manual_price or 0.0
        else:
            p, _, _ = md.get_price_eur(pos.ticker, pos.currency)
            p = p or 0.0
        m = calculations.calc_position_metrics(pos, p, p, 1.0)
        total += m["current_value"]
    return [_build_position(pos, total) for pos in positions], total


# ── Routes ────────────────────────────────────────────────

@router.get("/summary")
def get_portfolio_summary(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    positions, total = _all_positions_with_total(db)
    metrics = calculations.calc_portfolio_metrics([
        {"current_value": p["current_value"], "total_invested": p["total_invested"],
         "day_change_eur": p["day_change_eur"]}
        for p in positions
    ])
    return {
        **metrics,
        "positions": positions,
        "last_updated": md.get_last_refresh(),
        "is_market_open": md.is_market_open(),
    }


@router.get("/positions")
def list_positions(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    positions, _ = _all_positions_with_total(db)
    return positions


@router.post("/positions", status_code=201)
def create_position(data: PositionCreate, request: Request,
                    db: Session = Depends(get_db), user: User = Depends(require_admin_csrf)):
    pos = Position(**data.model_dump())
    db.add(pos)
    db.commit()
    db.refresh(pos)
    log_audit(db, user.id, "POSITION_CREATED", f"Position créée: {pos.display_name} ({pos.ticker})", request)
    return _build_position(pos, 0.0)


@router.put("/positions/{pos_id}")
def update_position(pos_id: int, data: PositionUpdate, request: Request,
                    db: Session = Depends(get_db), user: User = Depends(require_admin_csrf)):
    pos = db.query(Position).filter(Position.id == pos_id).first()
    if not pos:
        raise HTTPException(status_code=404, detail="Position introuvable")
    for k, v in data.model_dump(exclude_none=True).items():
        setattr(pos, k, v)
    db.commit()
    log_audit(db, user.id, "POSITION_UPDATED", f"Position modifiée: {pos.display_name} ({pos.ticker})", request)
    return _build_position(pos, 0.0)


@router.delete("/positions/{pos_id}")
def archive_position(pos_id: int, request: Request,
                     db: Session = Depends(get_db), user: User = Depends(require_admin_csrf)):
    pos = db.query(Position).filter(Position.id == pos_id).first()
    if not pos:
        raise HTTPException(status_code=404, detail="Position introuvable")
    pos.is_active = False
    db.commit()
    log_audit(db, user.id, "POSITION_ARCHIVED", f"Position archivée: {pos.display_name} ({pos.ticker})", request)
    return {"ok": True}


# ── Purchases ─────────────────────────────────────────────

@router.get("/positions/{pos_id}/purchases")
def list_purchases(pos_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    pos = db.query(Position).filter(Position.id == pos_id).first()
    if not pos:
        raise HTTPException(status_code=404, detail="Position introuvable")
    return pos.purchases


@router.post("/positions/{pos_id}/purchases", status_code=201)
def add_purchase(pos_id: int, data: PurchaseCreate, request: Request,
                 db: Session = Depends(get_db), user: User = Depends(require_admin_csrf)):
    pos = db.query(Position).filter(Position.id == pos_id).first()
    if not pos:
        raise HTTPException(status_code=404, detail="Position introuvable")
    from datetime import date
    purchase = Purchase(
        position_id=pos_id,
        purchase_date=date.fromisoformat(data.purchase_date),
        quantity=data.quantity, unit_price=data.unit_price,
        fees=data.fees, note=data.note,
    )
    db.add(purchase)
    db.commit()
    db.refresh(purchase)
    log_audit(db, user.id, "PURCHASE_CREATED",
              f"Achat {data.quantity} x {pos.ticker} à {data.unit_price}", request)
    return {
        "id": purchase.id, "position_id": purchase.position_id,
        "purchase_date": str(purchase.purchase_date),
        "quantity": purchase.quantity, "unit_price": purchase.unit_price,
        "fees": purchase.fees, "note": purchase.note,
    }


@router.put("/positions/{pos_id}/purchases/{pid}")
def update_purchase(pos_id: int, pid: int, data: PurchaseCreate, request: Request,
                    db: Session = Depends(get_db), user: User = Depends(require_admin_csrf)):
    p = db.query(Purchase).filter(Purchase.id == pid, Purchase.position_id == pos_id).first()
    if not p:
        raise HTTPException(status_code=404, detail="Achat introuvable")
    pos = db.query(Position).filter(Position.id == pos_id).first()
    from datetime import date
    p.purchase_date = date.fromisoformat(data.purchase_date)
    p.quantity = data.quantity
    p.unit_price = data.unit_price
    p.fees = data.fees
    p.note = data.note
    db.commit()
    log_audit(db, user.id, "PURCHASE_UPDATED",
              f"Achat #{pid} modifié sur {pos.ticker if pos else pos_id}", request)
    return {
        "id": p.id, "position_id": p.position_id,
        "purchase_date": str(p.purchase_date),
        "quantity": p.quantity, "unit_price": p.unit_price,
        "fees": p.fees, "note": p.note,
    }


@router.delete("/positions/{pos_id}/purchases/{pid}")
def delete_purchase(pos_id: int, pid: int, request: Request,
                    db: Session = Depends(get_db), user: User = Depends(require_admin_csrf)):
    p = db.query(Purchase).filter(Purchase.id == pid, Purchase.position_id == pos_id).first()
    if not p:
        raise HTTPException(status_code=404, detail="Achat introuvable")
    pos = db.query(Position).filter(Position.id == pos_id).first()
    db.delete(p)
    db.commit()
    log_audit(db, user.id, "PURCHASE_DELETED",
              f"Achat #{pid} supprimé sur {pos.ticker if pos else pos_id}", request)
    return {"ok": True}


@router.post("/positions/{pos_id}/manual-price")
def set_manual_price(pos_id: int, data: ManualPriceUpdate, request: Request,
                     db: Session = Depends(get_db), user: User = Depends(require_admin_csrf)):
    pos = db.query(Position).filter(Position.id == pos_id).first()
    if not pos or pos.ticker != "MANUAL":
        raise HTTPException(status_code=404, detail="Position introuvable ou non-manuelle")
    pos.manual_price = data.price
    pos.manual_price_updated_at = datetime.now(timezone.utc)
    db.commit()
    log_audit(db, user.id, "MANUAL_PRICE_SET",
              f"Prix manuel {data.price} fixé sur {pos.display_name}", request)
    return {"ok": True, "price": data.price}


# ── Refresh & history ─────────────────────────────────────

@router.get("/refresh")
def force_refresh(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    positions = db.query(Position).filter(Position.is_active == True).all()  # noqa: E712
    md.refresh_all_prices([p.ticker for p in positions])
    return {"ok": True, "refreshed_at": md.get_last_refresh()}


@router.get("/history")
def get_history(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    snaps = (db.query(PortfolioSnapshot)
             .order_by(PortfolioSnapshot.timestamp.desc())
             .limit(300).all())
    return [{"timestamp": s.timestamp, "total_value_eur": s.total_value_eur,
             "total_invested_eur": s.total_invested_eur, "total_pnl_eur": s.total_pnl_eur}
            for s in reversed(snaps)]
