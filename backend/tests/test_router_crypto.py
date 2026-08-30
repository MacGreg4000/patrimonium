"""Tests du router crypto : comptes d'exchange et synchronisation des trades."""
import datetime
from unittest.mock import patch

import pytest

import encryption
from models import ExchangeAccount, Position, Purchase, Sale


class FakeClient:
    """Client d'exchange factice — remplace Kraken/Bitvavo dans les tests."""

    trades: list = []

    def __init__(self, *_args, **_kwargs):
        pass

    def test_connection(self):
        return "2 actif(s) détecté(s)"

    def get_trades(self, extra_assets=None):
        return list(self.trades)


def _trade(ref, asset, side, qty, price, day, fee=0.0):
    return {
        "ref": ref, "asset": asset, "quote": "EUR", "side": side,
        "quantity": qty, "unit_price": price, "fee": fee,
        "date": datetime.date(2026, 1, day),
    }


@pytest.fixture
def fake_exchange():
    FakeClient.trades = []
    with patch("routers.crypto.get_client", lambda *a, **k: FakeClient()):
        yield FakeClient


def _create_account(client, exchange="kraken", label="Kraken test"):
    return client.post("/api/crypto/accounts", json={
        "exchange": exchange, "label": label,
        "api_key": "key", "api_secret": "c2VjcmV0",
    })


# ── Comptes ───────────────────────────────────────────────

def test_create_account_encrypts_keys(auth_admin, db, fake_exchange):
    client, _ = auth_admin
    r = _create_account(client)
    assert r.status_code == 201, r.text

    body = r.json()
    assert body["exchange"] == "kraken"
    # Les clés ne doivent jamais transiter dans la réponse
    assert "api_key" not in body and "api_secret" not in body

    acc = db.query(ExchangeAccount).filter(ExchangeAccount.id == body["id"]).first()
    assert acc.encrypted_api_key != "key"
    assert encryption.decrypt_str(acc.encrypted_api_key) == "key"
    assert encryption.decrypt_str(acc.encrypted_api_secret) == "c2VjcmV0"


def test_create_account_rejects_unknown_exchange(auth_admin, fake_exchange):
    client, _ = auth_admin
    r = client.post("/api/crypto/accounts", json={
        "exchange": "binance", "label": "X", "api_key": "k", "api_secret": "s",
    })
    assert r.status_code == 400
    assert "non supporté" in r.json()["detail"]


def test_regular_user_cannot_create_account(auth_user, fake_exchange):
    r = _create_account(auth_user)
    assert r.status_code in (401, 403)


# ── Synchronisation ───────────────────────────────────────

def test_sync_imports_buys_and_sells(auth_admin, db, fake_exchange):
    client, _ = auth_admin
    acc_id = _create_account(client).json()["id"]

    fake_exchange.trades = [
        _trade("t1", "BTC", "buy",  0.5, 40000.0, 10, fee=5.0),
        _trade("t2", "BTC", "buy",  0.5, 50000.0, 12),
        _trade("t3", "BTC", "sell", 0.4, 60000.0, 20),
    ]
    r = client.post(f"/api/crypto/accounts/{acc_id}/sync", json={})
    assert r.status_code == 200, r.text
    assert r.json()["created_purchases"] == 2
    assert r.json()["created_sales"] == 1

    pos = db.query(Position).filter(Position.asset_type == "crypto").one()
    assert pos.ticker == "BTC-EUR"          # format yfinance
    assert pos.display_name == "BTC · Kraken test"

    sale = db.query(Sale).filter(Sale.position_id == pos.id).one()
    # PRU = (0.5*40000 + 5 + 0.5*50000) / 1.0 = 45005
    assert sale.realized_pnl == pytest.approx((60000 - 45005) * 0.4)


def test_sync_is_idempotent(auth_admin, db, fake_exchange):
    """Re-synchroniser ne doit pas dupliquer les transactions déjà importées."""
    client, _ = auth_admin
    acc_id = _create_account(client).json()["id"]
    fake_exchange.trades = [_trade("t1", "ETH", "buy", 2.0, 2000.0, 5)]

    first = client.post(f"/api/crypto/accounts/{acc_id}/sync", json={}).json()
    assert first["created_purchases"] == 1 and first["skipped"] == 0

    second = client.post(f"/api/crypto/accounts/{acc_id}/sync", json={}).json()
    assert second["created_purchases"] == 0 and second["skipped"] == 1

    assert db.query(Purchase).count() == 1


def test_sync_archives_fully_sold_position(auth_admin, db, fake_exchange):
    client, _ = auth_admin
    acc_id = _create_account(client).json()["id"]
    fake_exchange.trades = [
        _trade("b1", "SOL", "buy",  10.0, 100.0, 3),
        _trade("s1", "SOL", "sell", 10.0, 150.0, 8),
    ]
    client.post(f"/api/crypto/accounts/{acc_id}/sync", json={})

    pos = db.query(Position).filter(Position.asset_type == "crypto").one()
    assert pos.is_active is False


def test_sync_skips_non_eur_pairs(auth_admin, db, fake_exchange):
    client, _ = auth_admin
    acc_id = _create_account(client).json()["id"]
    usd = _trade("u1", "BTC", "buy", 1.0, 40000.0, 4)
    usd["quote"] = "USD"
    fake_exchange.trades = [usd]

    r = client.post(f"/api/crypto/accounts/{acc_id}/sync", json={}).json()
    assert r["created_purchases"] == 0
    assert r["unsupported_pairs"] == ["BTC/USD"]


def test_separate_positions_per_account(auth_admin, db, fake_exchange):
    """Le même actif sur deux exchanges garde deux PRU distincts."""
    client, _ = auth_admin
    kraken = _create_account(client, "kraken", "Kraken test").json()["id"]
    bitvavo = _create_account(client, "bitvavo", "Bitvavo test").json()["id"]

    fake_exchange.trades = [_trade("k1", "BTC", "buy", 1.0, 30000.0, 2)]
    client.post(f"/api/crypto/accounts/{kraken}/sync", json={})
    fake_exchange.trades = [_trade("b1", "BTC", "buy", 1.0, 60000.0, 2)]
    client.post(f"/api/crypto/accounts/{bitvavo}/sync", json={})

    names = {p.display_name for p in db.query(Position)
             .filter(Position.asset_type == "crypto").all()}
    assert names == {"BTC · Kraken test", "BTC · Bitvavo test"}


# ── Vue d'ensemble ────────────────────────────────────────

def test_summary_excludes_crypto_from_portfolio(auth_admin, db, fake_exchange):
    """Le crypto a sa propre page : il ne doit pas polluer /api/portfolio/summary."""
    client, _ = auth_admin
    acc_id = _create_account(client).json()["id"]
    fake_exchange.trades = [_trade("t1", "BTC", "buy", 1.0, 30000.0, 2)]
    client.post(f"/api/crypto/accounts/{acc_id}/sync", json={})

    with patch("market_data.get_price_eur", return_value=(50000.0, 49000.0, 2.0)):
        crypto = client.get("/api/crypto/summary").json()
        portfolio = client.get("/api/portfolio/summary").json()

    assert crypto["stats"]["position_count"] == 1
    assert crypto["stats"]["total_value_eur"] == pytest.approx(50000.0)
    assert all(p["asset_type"] != "crypto" for p in portfolio["positions"])


def test_delete_account_keeps_positions(auth_admin, db, fake_exchange):
    client, _ = auth_admin
    acc_id = _create_account(client).json()["id"]
    fake_exchange.trades = [_trade("t1", "BTC", "buy", 1.0, 30000.0, 2)]
    client.post(f"/api/crypto/accounts/{acc_id}/sync", json={})

    assert client.delete(f"/api/crypto/accounts/{acc_id}").status_code == 200
    assert db.query(ExchangeAccount).count() == 0
    assert db.query(Position).filter(Position.asset_type == "crypto").count() == 1
