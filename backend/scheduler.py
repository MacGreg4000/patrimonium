import logging
import os
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger

import market_data as md
from alerts import check_alerts

logger = logging.getLogger(__name__)
MARKET_MIN = int(os.getenv("MARKET_REFRESH_MINUTES", "5"))
OFFMARKET_MIN = int(os.getenv("OFFMARKET_REFRESH_MINUTES", "30"))

scheduler = AsyncIOScheduler(timezone="Europe/Brussels")
_SessionLocal = None


def init_scheduler(session_local):
    global _SessionLocal
    _SessionLocal = session_local


async def refresh_job():
    if not _SessionLocal:
        return
    db = _SessionLocal()
    try:
        from models import Position, PortfolioSnapshot
        import calculations
        positions = db.query(Position).filter(Position.is_active == True).all()  # noqa: E712
        md.refresh_all_prices([p.ticker for p in positions if p.ticker != "MANUAL" and p.asset_type != "cash"])

        pos_data = []
        for pos in positions:
            if pos.ticker == "MANUAL" or pos.asset_type == "cash":
                price = pos.manual_price or 0.0
                prev = price
            else:
                price, prev, _ = md.get_price_eur(pos.ticker, pos.currency)
                price = price or 0.0
                prev = prev or price
            m = calculations.calc_position_metrics(pos, price, prev, 1.0)
            pos_data.append({**m, "id": pos.id, "display_name": pos.display_name,
                              "alert_gain_pct": pos.alert_gain_pct, "alert_loss_pct": pos.alert_loss_pct})

        portfolio = calculations.calc_portfolio_metrics(pos_data)
        if portfolio["total_value_eur"] == 0 and not pos_data:
            return
        snap = PortfolioSnapshot(
            total_value_eur=portfolio["total_value_eur"],
            total_invested_eur=portfolio["total_invested_eur"],
            total_pnl_eur=portfolio["total_pnl_eur"],
        )
        db.add(snap)
        db.commit()
        await check_alerts(pos_data)
        _reschedule()
    except Exception as e:
        logger.error(f"Refresh job error: {e}", exc_info=True)
        db.rollback()
    finally:
        db.close()


def _reschedule():
    minutes = MARKET_MIN if md.is_market_open() else OFFMARKET_MIN
    if scheduler.get_job("refresh"):
        scheduler.reschedule_job("refresh", trigger=IntervalTrigger(minutes=minutes))


def start_scheduler(session_local):
    init_scheduler(session_local)
    scheduler.add_job(refresh_job, trigger=IntervalTrigger(minutes=MARKET_MIN),
                      id="refresh", replace_existing=True)
    scheduler.start()
    logger.info("Scheduler started")


def stop_scheduler():
    if scheduler.running:
        scheduler.shutdown()
