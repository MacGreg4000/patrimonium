"""Tests du connecteur MCP : jetons de lecture et surface exposée.

L'essentiel de ces tests porte sur ce que le connecteur NE doit PAS pouvoir
faire — c'est la garantie vendue à l'utilisateur dans l'interface.
"""
from datetime import date
from unittest.mock import patch

import pytest

import auth as auth_utils
from models import ApiToken, AuditLog, Position, Purchase, Sale


def _create_token(client, label="Claude"):
    r = client.post("/api/tokens", json={"label": label})
    assert r.status_code == 201, r.text
    return r.json()["token"]


def _bearer(token):
    return {"Authorization": f"Bearer {token}"}


# ── Création et stockage ──────────────────────────────────

def test_token_is_stored_hashed_and_returned_once(auth_admin, db):
    client, _ = auth_admin
    raw = _create_token(client)
    assert raw.startswith("ptm_ro_")

    row = db.query(ApiToken).one()
    assert row.token_hash == auth_utils.hash_token(raw)
    assert row.token_hash != raw          # le jeton brut n'est jamais stocké
    assert row.scope == "read"

    # Il n'est plus jamais renvoyé ensuite
    listed = client.get("/api/tokens").json()
    assert "token" not in listed[0] and "token_hash" not in listed[0]


def test_regular_user_cannot_create_token(auth_user):
    assert auth_user.post("/api/tokens", json={"label": "x"}).status_code in (401, 403)


# ── Lecture autorisée ─────────────────────────────────────

# /api/mcp/historique est absent : il s'appuie sur date_trunc, propre à
# PostgreSQL, que la base SQLite des tests ne connaît pas. Sa protection par
# jeton est vérifiée séparément ci-dessous.
@pytest.mark.parametrize("path", [
    "/api/mcp/patrimoine", "/api/mcp/portefeuille", "/api/mcp/crypto",
    "/api/mcp/coffres", "/api/mcp/mouvements", "/api/mcp/actifs",
    "/api/mcp/reserves", "/api/mcp/transactions", "/api/mcp/positions-cloturees",
    "/api/mcp/actifs-vendus", "/api/mcp/inventaires", "/api/mcp/journal",
])
def test_read_endpoints_accept_a_valid_token(auth_admin, path):
    client, _ = auth_admin
    raw = _create_token(client)
    client.cookies.clear()                 # on n'utilise QUE le jeton
    assert client.get(path, headers=_bearer(raw)).status_code == 200


def test_token_usage_is_timestamped(auth_admin, db):
    client, _ = auth_admin
    raw = _create_token(client)
    assert db.query(ApiToken).one().last_used_at is None
    client.get("/api/mcp/coffres", headers=_bearer(raw))
    db.expire_all()
    assert db.query(ApiToken).one().last_used_at is not None


# ── Ce que le jeton ne doit PAS permettre ─────────────────

def test_token_is_rejected_without_bearer(auth_admin):
    client, _ = auth_admin
    _create_token(client)
    client.cookies.clear()
    assert client.get("/api/mcp/coffres").status_code == 401


def test_revoked_token_loses_access_immediately(auth_admin, db):
    client, _ = auth_admin
    raw = _create_token(client)
    token_id = db.query(ApiToken).one().id
    assert client.delete(f"/api/tokens/{token_id}").status_code == 200

    client.cookies.clear()
    assert client.get("/api/mcp/coffres", headers=_bearer(raw)).status_code == 401


def test_token_cannot_reach_the_password_vault(auth_admin):
    """Le coffre à mots de passe doit rester hors de portée du connecteur."""
    client, _ = auth_admin
    raw = _create_token(client)
    client.cookies.clear()

    # Le jeton ne vaut pas authentification sur les routes du coffre
    assert client.get("/api/password-files", headers=_bearer(raw)).status_code == 401

    # Et aucune route MCP n'expose de données de mots de passe : une URL
    # inconnue retombe sur la coquille HTML de l'application, pas sur du JSON.
    r = client.get("/api/mcp/passwords", headers=_bearer(raw))
    assert "text/html" in r.headers.get("content-type", "")


def test_history_route_requires_a_token(auth_admin):
    """Vérifié à part : la route s'appuie sur du SQL propre à PostgreSQL."""
    client, _ = auth_admin
    _create_token(client)
    client.cookies.clear()
    assert client.get("/api/mcp/historique").status_code == 401


def test_token_does_not_authenticate_application_routes(auth_admin):
    """Un jeton MCP ne doit pas servir de passe-partout sur le reste de l'API."""
    client, _ = auth_admin
    raw = _create_token(client)
    client.cookies.clear()
    for path in ("/api/dashboard", "/api/portfolio/summary", "/api/admin/users"):
        assert client.get(path, headers=_bearer(raw)).status_code == 401, path


def test_token_cannot_mutate_anything(auth_admin):
    """Garantie centrale : toute méthode mutante est refusée."""
    client, _ = auth_admin
    raw = _create_token(client)
    client.cookies.clear()
    h = _bearer(raw)
    assert client.post("/api/mcp/coffres", headers=h, json={}).status_code in (404, 405)
    assert client.delete("/api/mcp/coffres", headers=h).status_code in (404, 405)
    assert client.post("/api/coffres/movements", headers=h, json={}).status_code in (401, 403, 404, 405)


def test_coffre_combinations_are_never_exposed(auth_admin, db):
    """Les combinaisons de coffres ne doivent apparaître dans aucune réponse MCP."""
    from models import Coffre
    import encryption
    coffre = db.query(Coffre).first()
    if coffre is None:
        coffre = Coffre(name="Test", is_active=True)
        db.add(coffre)
    coffre.encrypted_combination = encryption.encrypt(b"1234-SECRET")
    coffre.combination_hint = "indice"
    db.commit()

    client, _ = auth_admin
    raw = _create_token(client)
    client.cookies.clear()
    body = client.get("/api/mcp/coffres", headers=_bearer(raw)).text
    assert "SECRET" not in body
    assert "combination" not in body.lower()


# ── Accès complet en lecture : détail des opérations ──────

def _position(db, name, ticker, asset_type, active=True):
    pos = Position(display_name=name, ticker=ticker, asset_type=asset_type,
                   currency="EUR", is_active=active)
    db.add(pos)
    db.flush()
    return pos


def _seed_operations(db):
    """Une position titres active, une crypto avec vente, une position clôturée."""
    etf = _position(db, "ETF Monde", "IWDA.AS", "etf")
    btc = _position(db, "BTC · Kraken", "BTC-EUR", "crypto")
    old = _position(db, "Ancienne action", "OLD.PA", "action", active=False)
    db.add_all([
        Purchase(position_id=etf.id, purchase_date=date(2026, 1, 10),
                 quantity=10, unit_price=100.0, fees=2.0),
        Purchase(position_id=btc.id, purchase_date=date(2026, 2, 1),
                 quantity=1, unit_price=50000.0, fees=10.0),
        Sale(position_id=btc.id, sale_date=date(2026, 3, 1),
             quantity=0.5, unit_price=60000.0, fees=5.0, realized_pnl=4990.0),
        Purchase(position_id=old.id, purchase_date=date(2025, 5, 1),
                 quantity=4, unit_price=25.0, fees=0.0),
        Sale(position_id=old.id, sale_date=date(2025, 9, 1),
             quantity=4, unit_price=30.0, fees=1.0, realized_pnl=19.0),
    ])
    db.commit()
    return etf, btc, old


def test_transactions_cover_stocks_crypto_and_closed_positions(auth_admin, db):
    _seed_operations(db)
    client, _ = auth_admin
    raw = _create_token(client)
    client.cookies.clear()
    h = _bearer(raw)

    body = client.get("/api/mcp/transactions", headers=h).json()
    assert body["total"] == 5
    # Plus récentes d'abord
    assert [i["date"] for i in body["items"]][:2] == ["2026-03-01", "2026-02-01"]
    assert {i["poche"] for i in body["items"]} == {"titres", "crypto"}
    # La position clôturée est bien incluse
    assert any(not i["position_active"] for i in body["items"])

    vente_btc = client.get("/api/mcp/transactions", headers=h,
                           params={"poche": "crypto", "sens": "vente"}).json()["items"]
    assert len(vente_btc) == 1
    assert vente_btc[0]["montant_net"] == 0.5 * 60000.0 - 5.0
    assert vente_btc[0]["plus_value_realisee"] == 4990.0

    periode = client.get("/api/mcp/transactions", headers=h,
                         params={"date_debut": "2026-01-01", "date_fin": "2026-01-31"}).json()
    assert [i["ticker"] for i in periode["items"]] == ["IWDA.AS"]
    assert periode["items"][0]["montant_net"] == 10 * 100.0 + 2.0


def test_transactions_reject_unknown_filter_values(auth_admin):
    client, _ = auth_admin
    raw = _create_token(client)
    client.cookies.clear()
    r = client.get("/api/mcp/transactions", headers=_bearer(raw), params={"sens": "don"})
    assert r.status_code == 422


def test_closed_positions_report_realized_pnl(auth_admin, db):
    _seed_operations(db)
    client, _ = auth_admin
    raw = _create_token(client)
    client.cookies.clear()
    body = client.get("/api/mcp/positions-cloturees", headers=_bearer(raw)).json()
    assert [p["ticker"] for p in body["positions"]] == ["OLD.PA"]
    p = body["positions"][0]
    assert p["investi_brut"] == 100.0
    assert p["produit_ventes_net"] == 119.0
    assert p["derniere_vente"] == "2025-09-01"
    assert body["total_plus_value_realisee"] == 19.0


def test_journal_hides_password_vault_and_combination_events(auth_admin, db, admin_user):
    db.add_all([
        AuditLog(user_id=admin_user.id, action="PWFILE_UPLOADED",
                 description="Fichier 'banque-secret.csv' chargé"),
        AuditLog(user_id=admin_user.id, action="COFFRE_COMBINATION_SET",
                 description="Code du coffre modifié"),
        AuditLog(user_id=admin_user.id, action="PURCHASE_CREATED",
                 description="Achat IWDA"),
    ])
    db.commit()
    client, _ = auth_admin
    raw = _create_token(client)
    client.cookies.clear()

    r = client.get("/api/mcp/journal", headers=_bearer(raw))
    actions = {i["action"] for i in r.json()["items"]}
    assert "PURCHASE_CREATED" in actions
    assert not any(a.startswith(("PWFILE_", "COFFRE_COMBINATION_")) for a in actions)
    assert "banque-secret" not in r.text

    # Même en le demandant explicitement, l'événement reste invisible
    r = client.get("/api/mcp/journal", headers=_bearer(raw), params={"action": "PWFILE_UPLOADED"})
    assert r.json()["total"] == 0


def test_movements_are_paginated(auth_admin):
    client, _ = auth_admin
    raw = _create_token(client)
    client.cookies.clear()
    body = client.get("/api/mcp/mouvements", headers=_bearer(raw),
                      params={"page": 2, "limit": 500}).json()
    assert body["page"] == 2
    assert body["limit"] == 100            # plafonné


# ── Non-régression : vue d'ensemble du patrimoine ─────────

def test_overview_top_movers_exclude_crypto_and_allocation_is_a_percentage(auth_admin, db):
    """Les top movers titres ne doivent pas contenir de crypto, l'allocation doit
    être une part en % et la variation du jour ne doit compter que les titres."""
    etf, btc, _ = _seed_operations(db)
    client, _ = auth_admin
    raw = _create_token(client)
    client.cookies.clear()

    # Cours 120, clôture veille 110 : tout le monde est en gain
    with patch("market_data.get_price_eur", return_value=(120.0, 110.0, 9.1)):
        body = client.get("/api/mcp/patrimoine", headers=_bearer(raw)).json()

    titres = body["portefeuille_titres"]
    movers = titres["top_gainers"] + titres["top_losers"]
    assert movers, "au moins l'ETF doit apparaître"
    assert all(m["asset_type"] != "crypto" for m in movers)
    etf_row = next(m for m in movers if m["ticker"] == "IWDA.AS")
    assert etf_row["allocation_pct"] == pytest.approx(100.0)   # seule position titres
    # 10 parts × (120 − 110) : la crypto n'entre pas dans la variation des titres
    assert titres["day_change_eur"] == pytest.approx(100.0)
