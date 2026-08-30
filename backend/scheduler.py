import asyncio
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


def _refresh_and_snapshot() -> list:
    """Rafraîchit les cours et enregistre un snapshot. Retourne les positions.

    Bloquant (réseau yfinance + pauses anti-rate-limit) : à exécuter dans un
    thread, jamais directement sur la boucle asyncio.
    """
    db = _SessionLocal()
    try:
        from models import Position, PortfolioSnapshot
        import calculations
        # Le crypto est exclu des snapshots : le graphique « Investissement & gains
        # réels » vit sur la page Portefeuille, qui n'affiche pas le crypto. L'inclure
        # ici ferait bondir la courbe à la première synchro sans contrepartie visible.
        from exchanges import CASH_TICKERS
        positions = db.query(Position).filter(
            Position.is_active == True,          # noqa: E712
            Position.asset_type != "crypto",
            Position.ticker.notin_(CASH_TICKERS),
        ).all()
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
            return pos_data
        snap = PortfolioSnapshot(
            total_value_eur=portfolio["total_value_eur"],
            total_invested_eur=portfolio["total_invested_eur"],
            total_pnl_eur=portfolio["total_pnl_eur"],
        )
        db.add(snap)
        db.commit()
        return pos_data
    except Exception as e:
        logger.error(f"Refresh job error: {e}", exc_info=True)
        db.rollback()
        return []
    finally:
        db.close()


async def refresh_job():
    """Job planifié : délègue le travail bloquant à un thread.

    Sans cela, les appels réseau et les pauses anti-rate-limit gèleraient la
    boucle asyncio — donc toute l'API — pendant plusieurs secondes à chaque cycle.
    """
    if not _SessionLocal:
        return
    try:
        pos_data = await asyncio.to_thread(_refresh_and_snapshot)
        if pos_data:
            await check_alerts(pos_data)
        _reschedule()
    except Exception as e:
        logger.error(f"Refresh job error: {e}", exc_info=True)


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
