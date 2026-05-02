"""Integration tests verifying CSRF protection is enforced on all mutations."""
import pytest
from models import Position, Coffre


# ── Helpers ───────────────────────────────────────────────

def _login_admin(client, admin_user):
    client.post("/api/auth/login",
                json={"email": "admin@test.com", "password": "AdminPass123!"})


def _get_csrf(client) -> str:
    return client.get("/api/auth/csrf").json()["csrf_token"]


NEW_POSITION = {
    "display_name": "Test Corp",
    "ticker": "TST.PA",
    "asset_type": "action",
    "currency": "EUR",
}


# ── POST mutations ────────────────────────────────────────

def test_create_position_without_csrf_returns_403(client, admin_user):
    _login_admin(client, admin_user)
    resp = client.post("/api/portfolio/positions", json=NEW_POSITION)
    assert resp.status_code == 403


def test_create_position_with_csrf_succeeds(client, admin_user):
    _login_admin(client, admin_user)
    csrf = _get_csrf(client)
    resp = client.post("/api/portfolio/positions", json=NEW_POSITION,
                       headers={"X-CSRF-Token": csrf})
    assert resp.status_code == 201


def test_create_movement_without_csrf_returns_403(client, admin_user, coffre):
    _login_admin(client, admin_user)
    resp = client.post("/api/movements", json={
        "coffre_id": coffre.id, "type": "ENTRY", "amount": 100.0,
    })
    assert resp.status_code == 403


def test_create_admin_coffre_without_csrf_returns_403(client, admin_user):
    _login_admin(client, admin_user)
    resp = client.post("/api/admin/coffres", json={"name": "Nouveau coffre"})
    assert resp.status_code == 403


# ── PUT / DELETE mutations ────────────────────────────────

def test_update_position_without_csrf_returns_403(client, admin_user, db):
    _login_admin(client, admin_user)
    csrf = _get_csrf(client)
    # Create a position first (with CSRF)
    pos_resp = client.post("/api/portfolio/positions", json=NEW_POSITION,
                           headers={"X-CSRF-Token": csrf})
    pos_id = pos_resp.json()["id"]
    # Attempt update without CSRF
    client.headers.pop("X-CSRF-Token", None)
    resp = client.put(f"/api/portfolio/positions/{pos_id}", json={**NEW_POSITION, "display_name": "Changed"})
    assert resp.status_code == 403


def test_delete_position_without_csrf_returns_403(client, admin_user, db):
    _login_admin(client, admin_user)
    csrf = _get_csrf(client)
    pos_resp = client.post("/api/portfolio/positions", json=NEW_POSITION,
                           headers={"X-CSRF-Token": csrf})
    pos_id = pos_resp.json()["id"]
    # Attempt delete without CSRF
    no_csrf_client_headers = {k: v for k, v in client.headers.items() if k != "x-csrf-token"}
    resp = client.delete(f"/api/portfolio/positions/{pos_id}",
                         headers={**no_csrf_client_headers, "X-CSRF-Token": ""})
    assert resp.status_code == 403


# ── GET routes must NOT require CSRF ─────────────────────

def test_list_positions_without_csrf_returns_200(client, admin_user):
    _login_admin(client, admin_user)
    resp = client.get("/api/portfolio/positions")
    assert resp.status_code == 200


def test_list_coffres_without_csrf_returns_200(client, admin_user):
    _login_admin(client, admin_user)
    resp = client.get("/api/coffres")
    assert resp.status_code == 200


# ── USER role must be blocked on mutations ────────────────

def test_create_position_as_user_returns_403(client, regular_user):
    client.post("/api/auth/login",
                json={"email": "user@test.com", "password": "UserPass123!"})
    csrf = _get_csrf(client)
    resp = client.post("/api/portfolio/positions", json=NEW_POSITION,
                       headers={"X-CSRF-Token": csrf})
    assert resp.status_code == 403
