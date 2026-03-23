from typing import Optional
from models import Position


def calc_position_metrics(
    position: Position,
    current_price_eur: float,
    previous_close_eur: float,
    portfolio_total: float,
) -> dict:
    purchases = position.purchases
    total_quantity = sum(p.quantity for p in purchases)
    total_invested = sum(p.quantity * p.unit_price + p.fees for p in purchases)
    average_cost = total_invested / total_quantity if total_quantity > 0 else None
    current_value = total_quantity * current_price_eur
    pnl_eur = current_value - total_invested
    pnl_pct = (pnl_eur / total_invested * 100) if total_invested > 0 else None
    day_change_eur = total_quantity * (current_price_eur - (previous_close_eur or current_price_eur))
    allocation_pct = (current_value / portfolio_total * 100) if portfolio_total > 0 else 0.0
    return {
        "total_quantity": total_quantity,
        "total_invested": total_invested,
        "average_cost": average_cost,
        "current_value": current_value,
        "pnl_eur": pnl_eur,
        "pnl_pct": pnl_pct,
        "day_change_eur": day_change_eur,
        "allocation_pct": allocation_pct,
    }


def calc_portfolio_metrics(positions_data: list) -> dict:
    total_value = sum(p["current_value"] for p in positions_data)
    total_invested = sum(p["total_invested"] for p in positions_data)
    pnl_eur = total_value - total_invested
    pnl_pct = (pnl_eur / total_invested * 100) if total_invested > 0 else None
    day_change_eur = sum(p["day_change_eur"] for p in positions_data)
    prev_total = total_value - day_change_eur
    day_change_pct = (day_change_eur / prev_total * 100) if prev_total > 0 else None
    return {
        "total_value_eur": total_value,
        "total_invested_eur": total_invested,
        "total_pnl_eur": pnl_eur,
        "total_pnl_pct": pnl_pct,
        "day_change_eur": day_change_eur,
        "day_change_pct": day_change_pct,
    }
