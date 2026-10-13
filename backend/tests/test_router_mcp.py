"""Tests du connecteur MCP : jetons de lecture et surface exposée.

L'essentiel de ces tests porte sur ce que le connecteur NE doit PAS pouvoir
faire — c'est la garantie vendue à l'utilisateur dans l'interface.
"""
import pytest

import auth as auth_utils
from models import ApiToken


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
    "/api/mcp/reserves",
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
