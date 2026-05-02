"""Integration tests for /api/portfolio/* routes."""
import pytest

NEW_POSITION = {
    "display_name": "LVMH",
    "ticker": "MC.PA",
    "asset_type": "action",
    "currency": "EUR",
}

NEW_PURCHASE = {
    "purchase_date": "2024-01-15",
    "quantity": 5.0,
    "unit_price": 750.0,
    "fees": 1.99,
}


def test_get_portfolio_summary(auth_admin):
    client, _ = auth_admin
    resp = client.get("/api/portfolio/summary")
    assert resp.status_code == 200
    data = resp.json()
    assert "positions" in data
    assert "last_updated" in data


def test_list_positions(auth_admin):
    client, _ = auth_admin
    resp = client.get("/api/portfolio/positions")
    assert resp.status_code == 200
    assert isinstance(resp.json(), list)


def test_create_position(auth_admin):
    client, csrf = auth_admin
    resp = client.post("/api/portfolio/positions", json=NEW_POSITION,
                       headers={"X-CSRF-Token": csrf})
    assert resp.status_code == 201
    data = resp.json()
    assert data["ticker"] == "MC.PA"
    assert data["display_name"] == "LVMH"
    assert data["is_active"] is True


def test_update_position(auth_admin):
    client, csrf = auth_admin
    pos_id = client.post("/api/portfolio/positions", json=NEW_POSITION,
                         headers={"X-CSRF-Token": csrf}).json()["id"]

    resp = client.put(f"/api/portfolio/positions/{pos_id}",
                      json={**NEW_POSITION, "display_name": "LVMH Updated"},
                      headers={"X-CSRF-Token": csrf})
    assert resp.status_code == 200
    assert resp.json()["display_name"] == "LVMH Updated"


def test_archive_position(auth_admin):
    client, csrf = auth_admin
    pos_id = client.post("/api/portfolio/positions", json=NEW_POSITION,
                         headers={"X-CSRF-Token": csrf}).json()["id"]

    resp = client.delete(f"/api/portfolio/positions/{pos_id}",
                         headers={"X-CSRF-Token": csrf})
    assert resp.status_code == 200
    assert resp.json()["ok"] is True

    # Archived position should not appear in active list
    positions = client.get("/api/portfolio/positions").json()
    assert all(p["id"] != pos_id for p in positions)


def test_add_purchase(auth_admin):
    client, csrf = auth_admin
    pos_id = client.post("/api/portfolio/positions", json=NEW_POSITION,
                         headers={"X-CSRF-Token": csrf}).json()["id"]

    resp = client.post(f"/api/portfolio/positions/{pos_id}/purchases",
                       json=NEW_PURCHASE, headers={"X-CSRF-Token": csrf})
    assert resp.status_code == 201
    data = resp.json()
    assert data["quantity"] == 5.0
    assert data["unit_price"] == 750.0


def test_update_purchase(auth_admin):
    client, csrf = auth_admin
    pos_id = client.post("/api/portfolio/positions", json=NEW_POSITION,
                         headers={"X-CSRF-Token": csrf}).json()["id"]
    pid = client.post(f"/api/portfolio/positions/{pos_id}/purchases",
                      json=NEW_PURCHASE, headers={"X-CSRF-Token": csrf}).json()["id"]

    resp = client.put(f"/api/portfolio/positions/{pos_id}/purchases/{pid}",
                      json={**NEW_PURCHASE, "quantity": 10.0},
                      headers={"X-CSRF-Token": csrf})
    assert resp.status_code == 200
    assert resp.json()["quantity"] == 10.0


def test_delete_purchase(auth_admin):
    client, csrf = auth_admin
    pos_id = client.post("/api/portfolio/positions", json=NEW_POSITION,
                         headers={"X-CSRF-Token": csrf}).json()["id"]
    pid = client.post(f"/api/portfolio/positions/{pos_id}/purchases",
                      json=NEW_PURCHASE, headers={"X-CSRF-Token": csrf}).json()["id"]

    resp = client.delete(f"/api/portfolio/positions/{pos_id}/purchases/{pid}",
                         headers={"X-CSRF-Token": csrf})
    assert resp.status_code == 200
    assert resp.json()["ok"] is True
