import logging
import os
import httpx

logger = logging.getLogger(__name__)
NTFY_URL = os.getenv("NTFY_URL", "")
NTFY_ENABLED = os.getenv("NTFY_ENABLED", "false").lower() == "true"
_sent: dict = {}


async def send_ntfy(title: str, message: str, priority: str = "default", tags: str = "chart_with_upwards_trend"):
    if not NTFY_ENABLED or not NTFY_URL:
        return
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            await client.post(NTFY_URL, content=message,
                              headers={"Title": title, "Priority": priority, "Tags": tags})
    except Exception as e:
        logger.warning(f"ntfy failed: {e}")


async def check_alerts(positions_data: list):
    for pos in positions_data:
        pid = pos["id"]
        pnl_pct = pos.get("pnl_pct")
        if pnl_pct is None:
            continue
        gain_thr = pos.get("alert_gain_pct")
        loss_thr = pos.get("alert_loss_pct")
        name = pos.get("display_name", "Position")
        prev = _sent.get(pid)
        if gain_thr and pnl_pct >= gain_thr and prev != "gain":
            await send_ntfy(f"📈 {name} +{pnl_pct:.1f}%",
                            f"Seuil de gain atteint ({gain_thr:.1f}%)\nValeur: {pos.get('current_value',0):.2f}€",
                            priority="high", tags="chart_with_upwards_trend,moneybag")
            _sent[pid] = "gain"
        elif loss_thr and pnl_pct <= -abs(loss_thr) and prev != "loss":
            await send_ntfy(f"📉 {name} {pnl_pct:.1f}%",
                            f"Seuil de perte atteint (-{loss_thr:.1f}%)\nValeur: {pos.get('current_value',0):.2f}€",
                            priority="urgent", tags="chart_with_downwards_trend,warning")
            _sent[pid] = "loss"
        else:
            if prev and (
                (prev == "gain" and (not gain_thr or pnl_pct < gain_thr)) or
                (prev == "loss" and (not loss_thr or pnl_pct > -abs(loss_thr)))
            ):
                _sent[pid] = None
