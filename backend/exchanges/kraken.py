"""Client Kraken — lecture seule (soldes + historique des trades).

Docs : https://docs.kraken.com/rest/
Authentification : API-Key + API-Sign (HMAC-SHA512).
"""
import base64
import hashlib
import hmac
import logging
import time
import urllib.parse
from datetime import datetime, timezone

import httpx

logger = logging.getLogger(__name__)

BASE_URL = "https://api.kraken.com"
TIMEOUT = 20.0

# Kraken utilise des codes historiques préfixés X (crypto) / Z (fiat)
_ASSET_ALIASES = {
    "XXBT": "BTC", "XBT": "BTC",
    "XETH": "ETH", "XETC": "ETC",
    "XLTC": "LTC", "XXRP": "XRP",
    "XXDG": "DOGE", "XDG": "DOGE",
    "XXLM": "XLM", "XZEC": "ZEC",
    "XXMR": "XMR", "XREP": "REP",
    "ZEUR": "EUR", "ZUSD": "USD", "ZGBP": "GBP", "ZCAD": "CAD", "ZJPY": "JPY",
}

FIAT = {"EUR", "USD", "GBP", "CHF", "CAD", "JPY", "AUD"}


def normalize_asset(code: str) -> str:
    """Convertit un code Kraken en symbole standard (XXBT → BTC, ETH2.S → ETH)."""
    code = (code or "").upper()
    # Suffixes de staking : ETH2.S, DOT.S, ADA.M …
    for suffix in (".S", ".M", ".F", ".B"):
        if code.endswith(suffix):
            code = code[: -len(suffix)]
    if code == "ETH2":
        code = "ETH"
    return _ASSET_ALIASES.get(code, code)


class KrakenClient:
    """Accès en lecture seule au compte Kraken."""

    def __init__(self, api_key: str, api_secret: str):
        self._key = api_key
        self._secret = api_secret
        self._pairs_cache: dict | None = None

    # ── Signature ────────────────────────────────────────────
    def _sign(self, urlpath: str, data: dict) -> str:
        postdata = urllib.parse.urlencode(data)
        encoded = (str(data["nonce"]) + postdata).encode()
        message = urlpath.encode() + hashlib.sha256(encoded).digest()
        try:
            secret = base64.b64decode(self._secret)
        except Exception as e:
            raise ValueError("Clé secrète Kraken invalide (base64 attendu)") from e
        sig = hmac.new(secret, message, hashlib.sha512)
        return base64.b64encode(sig.digest()).decode()

    def _private(self, method: str, data: dict | None = None) -> dict:
        urlpath = f"/0/private/{method}"
        payload = dict(data or {})
        payload["nonce"] = str(int(time.time() * 1000))
        headers = {
            "API-Key": self._key,
            "API-Sign": self._sign(urlpath, payload),
            "Content-Type": "application/x-www-form-urlencoded",
        }
        r = httpx.post(BASE_URL + urlpath, data=payload, headers=headers, timeout=TIMEOUT)
        r.raise_for_status()
        body = r.json()
        if body.get("error"):
            raise RuntimeError("Kraken : " + "; ".join(body["error"]))
        return body.get("result") or {}

    def _asset_pairs(self) -> dict:
        """Mapping pair → (base, quote), via l'endpoint public AssetPairs."""
        if self._pairs_cache is None:
            r = httpx.get(f"{BASE_URL}/0/public/AssetPairs", timeout=TIMEOUT)
            r.raise_for_status()
            result = r.json().get("result") or {}
            self._pairs_cache = {
                name: (normalize_asset(p.get("base", "")), normalize_asset(p.get("quote", "")))
                for name, p in result.items()
            }
        return self._pairs_cache

    # ── API publique du client ───────────────────────────────
    def test_connection(self) -> str:
        """Vérifie que les clés fonctionnent. Retourne un message lisible."""
        balances = self.get_balances()
        return f"{len(balances)} actif(s) détecté(s)"

    def get_balances(self) -> dict[str, float]:
        """Soldes non nuls, agrégés par symbole normalisé."""
        raw = self._private("Balance")
        out: dict[str, float] = {}
        for code, amount in raw.items():
            qty = float(amount or 0)
            if qty <= 0:
                continue
            sym = normalize_asset(code)
            out[sym] = out.get(sym, 0.0) + qty
        return out

    def get_trades(self) -> list[dict]:
        """Historique complet des trades (pagination par offset de 50)."""
        pairs = self._asset_pairs()
        trades: list[dict] = []
        offset = 0
        while True:
            result = self._private("TradesHistory", {"ofs": offset})
            batch = result.get("trades") or {}
            if not batch:
                break
            for txid, t in batch.items():
                pair = t.get("pair", "")
                base, quote = pairs.get(pair, (normalize_asset(pair), "EUR"))
                if base in FIAT:
                    continue  # conversion fiat/fiat, hors périmètre
                trades.append({
                    "ref": txid,
                    "date": datetime.fromtimestamp(float(t["time"]), tz=timezone.utc).date(),
                    "asset": base,
                    "quote": quote,
                    "side": "buy" if t.get("type") == "buy" else "sell",
                    "quantity": float(t.get("vol") or 0),
                    "unit_price": float(t.get("price") or 0),
                    "fee": float(t.get("fee") or 0),
                })
            offset += len(batch)
            total = int(result.get("count") or 0)
            if offset >= total:
                break
            time.sleep(1)  # respecte le rate-limit Kraken
        return trades
