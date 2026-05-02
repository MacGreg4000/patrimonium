import logging
import threading
import time
from datetime import datetime, timezone
from typing import Dict, Optional, Tuple
from zoneinfo import ZoneInfo

import yfinance as yf

logger = logging.getLogger(__name__)
BRUSSELS_TZ = ZoneInfo("Europe/Brussels")

_price_cache: Dict[str, dict] = {}
_eurusd_cache: Optional[Tuple[float, float]] = None
_last_refresh: Optional[datetime] = None
CACHE_TTL = 300  # secondes

# Verrous par ticker pour éviter les fetches parallèles
_locks: Dict[str, threading.Lock] = {}
_locks_meta = threading.Lock()


def _ticker_lock(ticker: str) -> threading.Lock:
    with _locks_meta:
        if ticker not in _locks:
            _locks[ticker] = threading.Lock()
        return _locks[ticker]


def is_market_open() -> bool:
    now = datetime.now(BRUSSELS_TZ)
    if now.weekday() >= 5:
        return False
    open_ = now.replace(hour=9, minute=0, second=0, microsecond=0)
    close = now.replace(hour=17, minute=30, second=0, microsecond=0)
    return open_ <= now <= close


def get_eurusd_rate() -> float:
    global _eurusd_cache
    now = time.time()
    if _eurusd_cache and (now - _eurusd_cache[1]) < CACHE_TTL:
        return _eurusd_cache[0]

    with _ticker_lock("EURUSD"):
        if _eurusd_cache and (now - _eurusd_cache[1]) < CACHE_TTL:
            return _eurusd_cache[0]
        try:
            rate = float(yf.Ticker("EURUSD=X").fast_info.last_price)
            if rate > 0:
                _eurusd_cache = (rate, time.time())
                return rate
        except Exception as e:
            logger.warning(f"EUR/USD fetch failed: {e}")
    return _eurusd_cache[0] if _eurusd_cache else 1.10


def fetch_price(ticker: str) -> Optional[dict]:
    now = time.time()
    cached = _price_cache.get(ticker)
    if cached and (now - cached.get("fetched_at", 0)) < CACHE_TTL:
        return cached

    with _ticker_lock(ticker):
        cached = _price_cache.get(ticker)
        now = time.time()
        if cached and (now - cached.get("fetched_at", 0)) < CACHE_TTL:
            return cached
        try:
            info = yf.Ticker(ticker).fast_info
            price = float(info.last_price)
            prev = float(info.previous_close) if info.previous_close else price
            data = {
                "price": price,
                "prev_close": prev,
                "day_change_pct": ((price - prev) / prev * 100) if prev else 0.0,
                "fetched_at": time.time(),
            }
            _price_cache[ticker] = data
            logger.info(f"Fetched {ticker}: {price:.4f}")
            return data
        except Exception as e:
            logger.warning(f"Fetch failed for {ticker}: {e}")
            return _price_cache.get(ticker)


def get_price_eur(ticker: str, currency: str) -> Tuple[Optional[float], Optional[float], Optional[float]]:
    if ticker == "MANUAL":
        return None, None, None
    data = fetch_price(ticker)
    if not data:
        return None, None, None
    price = data["price"]
    prev = data["prev_close"]
    day_pct = data["day_change_pct"]
    if currency == "USD":
        rate = get_eurusd_rate()
        return price / rate, prev / rate, day_pct
    return price, prev, day_pct


def refresh_all_prices(tickers: list) -> None:
    global _last_refresh
    for t in tickers:
        if t in _price_cache:
            _price_cache[t]["fetched_at"] = 0
    global _eurusd_cache
    _eurusd_cache = None

    get_eurusd_rate()
    for t in set(t for t in tickers if t != "MANUAL"):
        fetch_price(t)
        time.sleep(1)

    _last_refresh = datetime.now(timezone.utc)


def get_last_refresh() -> Optional[datetime]:
    return _last_refresh
