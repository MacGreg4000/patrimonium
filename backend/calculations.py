from typing import Optional
from models import Position


def calc_position_metrics(
    position: Position,
    current_price_eur: float,
    previous_close_eur: float,
    portfolio_total: float,
) -> dict:
    purchases     = position.purchases
    sales         = getattr(position, "sales", [])

    total_bought  = sum(p.quantity for p in purchases)
    total_sold    = sum(s.quantity for s in sales)
    net_quantity  = total_bought - total_sold

    total_invested  = sum(p.quantity * p.unit_price + p.fees for p in purchases)
    avg_cost        = total_invested / total_bought if total_bought > 0 else 0.0
    # Coût résiduel = PRU × parts encore détenues
    adjusted_invested = avg_cost * net_quantity

    realized_pnl   = sum(s.realized_pnl or 0.0 for s in sales)
    current_value  = net_quantity * current_price_eur
    unrealized_pnl = current_value - adjusted_invested
    total_pnl_eur  = unrealized_pnl + realized_pnl
    pnl_pct        = (total_pnl_eur / total_invested * 100) if total_invested > 0 else None
    day_change_eur = net_quantity * (current_price_eur - (previous_close_eur or current_price_eur))
    allocation_pct = (current_value / portfolio_total * 100) if portfolio_total > 0 else 0.0

    return {
        "total_quantity":  net_quantity,        # quantité nette après ventes
        "total_bought":    total_bought,
        "total_sold":      total_sold,
        "total_invested":  adjusted_invested,   # coût résiduel des parts encore détenues
        "average_cost":    avg_cost if total_bought > 0 else None,
        "current_value":   current_value,
        "pnl_eur":         total_pnl_eur,
        "unrealized_pnl":  unrealized_pnl,
        "realized_pnl":    realized_pnl,
        "pnl_pct":         pnl_pct,
        "day_change_eur":  day_change_eur,
        "allocation_pct":  allocation_pct,
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
