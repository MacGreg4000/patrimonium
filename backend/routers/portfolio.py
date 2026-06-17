"""Stock portfolio router: positions, purchases, market data."""
from datetime import datetime, timedelta, timezone
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy import func
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
    if pos.ticker == "MANUAL" or pos.asset_type == "cash":
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
        if pos.ticker == "MANUAL" or pos.asset_type == "cash":
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
    # Les liquidités (cash) ne sont pas du capital "investi" → exclure du calcul P&L
    # mais conserver leur valeur dans total_value_eur
    stock_positions = [p for p in positions if p.get("asset_type") != "cash"]
    metrics = calculations.calc_portfolio_metrics([
        {"current_value": p["current_value"], "total_invested": p["total_invested"],
         "day_change_eur": p["day_change_eur"]}
        for p in stock_positions
    ])
    metrics["total_value_eur"] = total   # inclut les liquidités
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


# period → (fenêtre temporelle, granularité du bucket pour sous-échantillonnage)
# Bucket None = données brutes (la fenêtre est assez courte pour rester légère).
_HISTORY_PERIODS = {
    "day":   (timedelta(days=1),    None),
    "week":  (timedelta(days=7),    "hour"),
    "month": (timedelta(days=30),   "day"),
    "year":  (timedelta(days=365),  "day"),
    "max":   (None,                 "day"),
    # "ytd" est traité à part (depuis le 1ᵉʳ janvier de l'année courante)
}


@router.get("/history")
def get_history(period: str = "month",
                db: Session = Depends(get_db),
                user: User = Depends(get_current_user)):
    """Historique des snapshots de portefeuille pour une période donnée.

    period ∈ {day, week, month, ytd, year, max}. Les périodes longues sont
    sous-échantillonnées (dernier snapshot par heure/jour) pour rester légères.
    """
    now = datetime.now(timezone.utc)

    if period == "ytd":
        cutoff, bucket = datetime(now.year, 1, 1, tzinfo=timezone.utc), "day"
    else:
        window, bucket = _HISTORY_PERIODS.get(period, _HISTORY_PERIODS["month"])
        cutoff = (now - window) if window else None

    q = db.query(PortfolioSnapshot)
    if cutoff is not None:
        q = q.filter(PortfolioSnapshot.timestamp >= cutoff)

    if bucket:
        # DISTINCT ON (bucket) : conserve le dernier snapshot de chaque bucket
        trunc = func.date_trunc(bucket, PortfolioSnapshot.timestamp)
        snaps = (q.distinct(trunc)
                  .order_by(trunc.desc(), PortfolioSnapshot.timestamp.desc())
                  .limit(800).all())
    else:
        snaps = (q.order_by(PortfolioSnapshot.timestamp.desc())
                  .limit(800).all())

    snaps = sorted(snaps, key=lambda s: s.timestamp)
    return [{"timestamp": s.timestamp, "total_value_eur": s.total_value_eur,
             "total_invested_eur": s.total_invested_eur, "total_pnl_eur": s.total_pnl_eur}
            for s in snaps]


# ── Simulator rates ────────────────────────────────────────

_sim_rate_cache: dict = {}   # {ticker: {"data": {...}, "ts": float}}
_SIM_CACHE_TTL  = 6 * 3600  # 6 h

@router.get("/simulate-rates")
def get_simulate_rates(tickers: str,
                       db: Session = Depends(get_db),
                       user: User = Depends(get_current_user)):
    """Retourne le CAGR 10 ans et le rendement dividende pour une liste de tickers.
    Le calcul de simulation est entièrement côté client — cet endpoint fournit
    uniquement les paramètres historiques (appel yfinance mis en cache 6 h).
    """
    import yfinance as yf
    import pandas as pd

    now    = datetime.now(timezone.utc).timestamp()
    result = {}

    for ticker in [t.strip() for t in tickers.split(",") if t.strip()]:
        cached = _sim_rate_cache.get(ticker)
        if cached and (now - cached["ts"]) < _SIM_CACHE_TTL:
            result[ticker] = cached["data"]
            continue

        try:
            yf_t = yf.Ticker(ticker)
            hist = yf_t.history(period="10y", auto_adjust=True)

            if len(hist) < 50:
                data: dict = {"cagr": None, "dividend_yield": 0.0, "years_of_data": 0}
            else:
                years = len(hist) / 252   # jours ouvrés → années
                cagr  = (hist["Close"].iloc[-1] / hist["Close"].iloc[0]) ** (1 / years) - 1

                # Rendement dividende : moyenne annuelle des 3 dernières années
                divs      = yf_t.dividends
                div_yield = 0.0
                if len(divs) > 0:
                    cutoff  = divs.index[-1] - pd.DateOffset(years=3)
                    recent  = divs[divs.index > cutoff]
                    if len(recent) > 0:
                        annual_div = recent.sum() / 3
                        cur_price  = float(hist["Close"].iloc[-1])
                        div_yield  = annual_div / cur_price if cur_price > 0 else 0.0

                data = {
                    "cagr":           round(cagr * 100, 2),
                    "dividend_yield": round(div_yield * 100, 2),
                    "years_of_data":  round(years, 1),
                }

            _sim_rate_cache[ticker] = {"data": data, "ts": now}
            result[ticker] = data

        except Exception:
            result[ticker] = {"cagr": None, "dividend_yield": 0.0, "years_of_data": 0}

    return result
