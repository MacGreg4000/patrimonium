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


def get_client(exchange: str, api_key: str, api_secret: str):
    cls = CLIENTS.get(exchange)
    if cls is None:
        raise ValueError(f"Exchange non supporté : {exchange}")
    return cls(api_key, api_secret)
