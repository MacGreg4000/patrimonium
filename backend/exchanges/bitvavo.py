"""Client Bitvavo — lecture seule (soldes + historique des trades).

Docs : https://docs.bitvavo.com/
Authentification : HMAC-SHA256 sur (timestamp + méthode + chemin + body).
"""
import hashlib
import hmac
import logging
import time
from datetime import datetime, timezone

import httpx

logger = logging.getLogger(__name__)

BASE_URL = "https://api.bitvavo.com"
PREFIX = "/v2"
TIMEOUT = 20.0
ACCESS_WINDOW = 10000

FIAT = {"EUR", "USD", "GBP"}


class BitvavoClient:
    """Accès en lecture seule au compte Bitvavo."""

    def __init__(self, api_key: str, api_secret: str):
        self._key = api_key
        self._secret = api_secret

    # ── Signature ────────────────────────────────────────────
    def _headers(self, method: str, endpoint: str, body: str = "") -> dict:
        ts = str(int(time.time() * 1000))
        message = ts + method.upper() + PREFIX + endpoint + body
        sig = hmac.new(self._secret.encode(), message.encode(), hashlib.sha256).hexdigest()
        return {
            "Bitvavo-Access-Key": self._key,
            "Bitvavo-Access-Signature": sig,
            "Bitvavo-Access-Timestamp": ts,
            "Bitvavo-Access-Window": str(ACCESS_WINDOW),
            "Content-Type": "application/json",
        }

    def _get(self, endpoint: str) -> list | dict:
        r = httpx.get(BASE_URL + PREFIX + endpoint,
                      headers=self._headers("GET", endpoint), timeout=TIMEOUT)
        if r.status_code >= 400:
            try:
                msg = r.json().get("error") or r.text
            except Exception:
                msg = r.text
            raise RuntimeError(f"Bitvavo : {msg}")
        return r.json()

    # ── API publique du client ───────────────────────────────
    def test_connection(self) -> str:
        balances = self.get_balances()
        return f"{len(balances)} actif(s) détecté(s)"

    def get_balances(self) -> dict[str, float]:
        """Soldes non nuls (disponible + engagé dans des ordres)."""
        out: dict[str, float] = {}
        for b in self._get("/balance") or []:
            qty = float(b.get("available") or 0) + float(b.get("inOrder") or 0)
            if qty > 0:
                out[(b.get("symbol") or "").upper()] = qty
        return out

    def get_trades(self, extra_assets: set[str] | None = None) -> list[dict]:
        """Historique des trades pour les marchés <ASSET>-EUR.

        Bitvavo n'expose pas d'endpoint global : on interroge marché par marché.
        Les marchés sont déduits des soldes actuels, complétés par `extra_assets`
        (actifs déjà connus en base) pour couvrir les positions entièrement vendues.
        """
        assets = {a for a in self.get_balances() if a not in FIAT}
        assets |= {a.upper() for a in (extra_assets or set()) if a.upper() not in FIAT}

        trades: list[dict] = []
        for asset in sorted(assets):
            market = f"{asset}-EUR"
            try:
                rows = self._get(f"/trades?market={market}&limit=1000") or []
            except RuntimeError as e:
                logger.warning(f"Bitvavo : marché {market} ignoré ({e})")
                continue
            for t in rows:
                ts = float(t.get("timestamp") or 0) / 1000
                trades.append({
                    "ref": str(t.get("id") or ""),
                    "date": datetime.fromtimestamp(ts, tz=timezone.utc).date(),
                    "asset": asset,
                    "quote": "EUR",
                    "side": "buy" if t.get("side") == "buy" else "sell",
                    "quantity": float(t.get("amount") or 0),
                    "unit_price": float(t.get("price") or 0),
                    "fee": abs(float(t.get("fee") or 0)),
                })
            time.sleep(0.2)  # respecte le rate-limit Bitvavo
        return trades
