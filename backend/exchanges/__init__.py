"""Clients d'exchanges crypto — LECTURE SEULE.

Ces clients n'exposent que la consultation des soldes et de l'historique des
trades. Aucune fonction d'ordre, de trading ou de retrait n'est implémentée :
les clés API configurées doivent être créées en lecture seule.
"""
from .kraken import KrakenClient
from .bitvavo import BitvavoClient

CLIENTS = {
    "kraken": KrakenClient,
    "bitvavo": BitvavoClient,
}

EXCHANGE_LABELS = {
    "kraken": "Kraken",
    "bitvavo": "Bitvavo",
}


def cash_ticker(exchange: str) -> str:
    """Ticker de la position « liquidités » d'un exchange (ex. BITVAVO:EUR).

    Même convention que SAXO:EUR / REVOLUT:EUR. Ces tickers ne sont jamais
    envoyés à yfinance : les positions portent asset_type="cash" et un
    manual_price.
    """
    return f"{exchange.upper()}:EUR"


# Tickers de liquidités rattachés à la page Crypto (et non au portefeuille titres)
CASH_TICKERS = {cash_ticker(e) for e in CLIENTS}


def get_client(exchange: str, api_key: str, api_secret: str):
    cls = CLIENTS.get(exchange)
    if cls is None:
        raise ValueError(f"Exchange non supporté : {exchange}")
    return cls(api_key, api_secret)
