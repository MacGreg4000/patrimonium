"""Unified patrimoine dashboard router."""
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

import calculations
import market_data as md
from database import get_db
from dependencies import get_current_user
from models import AssetDocument, Coffre, Inventory, Movement, PasswordFile, PhysicalAsset, Position, Reserve, User

router = APIRouter(prefix="/api/dashboard", tags=["dashboard"])


@router.get("")
def get_dashboard(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    """
    Returns unified patrimoine summary:
    - Total portfolio boursier
    - Total liquidités coffres
    - Total actifs physiques
    - Total réserves
    - Grand total patrimoine
    """

    # ── 1. Portfolio boursier ──────────────────────────────
    positions = db.query(Position).filter(Position.is_active == True).all()  # noqa: E712
    total_portfolio_value = 0.0
    total_portfolio_invested = 0.0
    total_portfolio_pnl = 0.0
    day_change_eur = 0.0

    pos_data = []
    for pos in positions:
        if pos.ticker == "MANUAL":
            price_eur = pos.manual_price or 0.0
            prev_eur = price_eur
        else:
            price_eur, prev_eur, _ = md.get_price_eur(pos.ticker, pos.currency)
            price_eur = price_eur or 0.0
            prev_eur = prev_eur or price_eur
        m = calculations.calc_position_metrics(pos, price_eur, prev_eur, 1.0)
        m["display_name"] = pos.display_name
        m["ticker"] = pos.ticker
        pos_data.append(m)
        total_portfolio_value += m["current_value"]
        total_portfolio_invested += m["total_invested"]
        day_change_eur += m["day_change_eur"]

    total_portfolio_pnl = total_portfolio_value - total_portfolio_invested
    total_portfolio_pnl_pct = (
        total_portfolio_pnl / total_portfolio_invested * 100
        if total_portfolio_invested > 0 else None
    )

    # ── 2. Liquidités coffres ──────────────────────────────
    from routers.coffres import compute_balance
    coffres = db.query(Coffre).filter(Coffre.is_active == True).all()  # noqa: E712
    coffre_balances = [
        {"id": c.id, "name": c.name, "balance": compute_balance(c.id, db)}
        for c in coffres
    ]
    total_cash = sum(c["balance"] for c in coffre_balances)

    # ── 3. Actifs physiques ────────────────────────────────
    assets = db.query(PhysicalAsset).all()
    total_assets_value = sum((a.estimated_value or 0.0) for a in assets)
    asset_count = len(assets)

    # Category breakdown
    cat_totals: dict = {}
    for a in assets:
        cat = a.category or "autre"
        cat_totals[cat] = cat_totals.get(cat, 0.0) + (a.estimated_value or 0.0)

    # ── 4. Réserves ───────────────────────────────────────
    reserves = db.query(Reserve).filter(Reserve.user_id == user.id).all()
    total_reserves   = sum(r.amount for r in reserves)
    total_released   = sum(r.released or 0.0 for r in reserves)
    total_precompte  = sum(r.precompte_paye or 0.0 for r in reserves)
    total_releasable = sum(max(0.0, r.amount - (r.released or 0.0)) for r in reserves)

    # ── 5. Grand total patrimoine ─────────────────────────
    # Les réserves sont incluses en valeur brute (= non encore libérées)
    grand_total = total_portfolio_value + total_cash + total_assets_value + total_releasable

    # ── 6. Monthly cash flow (last 6 months) ─────────────
    from sqlalchemy import func, extract
    from datetime import datetime, timezone, timedelta
    six_months_ago = datetime.now(timezone.utc) - timedelta(days=180)

    monthly_entries = {}
    monthly_exits = {}
    mvs = (db.query(Movement)
           .filter(Movement.deleted_at.is_(None), Movement.created_at >= six_months_ago)
           .all())
    for m in mvs:
        key = m.created_at.strftime("%Y-%m")
        if m.type == "ENTRY":
            monthly_entries[key] = monthly_entries.get(key, 0.0) + m.amount
        else:
            monthly_exits[key] = monthly_exits.get(key, 0.0) + m.amount

    # ── 7. Fichiers chiffrés ──────────────────────────────
    password_file_count = db.query(PasswordFile).filter(PasswordFile.user_id == user.id).count()
    asset_doc_count     = db.query(AssetDocument).count()

    # ── 8. Portfolio top movers ───────────────────────────
    movers = sorted(pos_data, key=lambda x: x.get("pnl_pct") or 0, reverse=True)
    top_gainers = movers[:3]
    top_losers = sorted(pos_data, key=lambda x: x.get("pnl_pct") or 0)[:3]

    return {
        # Global
        "grand_total_eur": grand_total,
        "is_market_open": md.is_market_open(),
        "last_updated": md.get_last_refresh(),

        # Portfolio boursier
        "portfolio": {
            "total_value_eur": total_portfolio_value,
            "total_invested_eur": total_portfolio_invested,
            "total_pnl_eur": total_portfolio_pnl,
            "total_pnl_pct": total_portfolio_pnl_pct,
            "day_change_eur": day_change_eur,
            "position_count": len(positions),
            "top_gainers": top_gainers[:3],
            "top_losers": [l for l in top_losers if (l.get("pnl_pct") or 0) < 0][:3],
        },

        # Liquidités
        "cash": {
            "total_eur": total_cash,
            "coffres": coffre_balances,
            "coffre_count": len(coffres),
        },

        # Actifs physiques
        "assets": {
            "total_value_eur": total_assets_value,
            "count": asset_count,
            "by_category": cat_totals,
        },

        # Réserves de liquidation / dividendes société
        "reserves": {
            "total_amount":     total_reserves,
            "total_released":   total_released,
            "total_precompte":  total_precompte,
            "total_releasable": total_releasable,
            "total_net_recu":   total_released - total_precompte,
        },

        # Fichiers
        "files": {
            "password_count": password_file_count,
            "asset_doc_count": asset_doc_count,
            "total_count": password_file_count + asset_doc_count,
        },

        # Cash flow chart data
        "monthly_flow": {
            "entries": monthly_entries,
            "exits": monthly_exits,
        },
    }
