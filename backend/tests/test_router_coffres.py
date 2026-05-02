"""Integration tests for /api/coffres, /api/movements, /api/inventories routes."""
import pytest


def test_list_coffres(auth_admin, coffre):
    client, _ = auth_admin
    resp = client.get("/api/coffres")
    assert resp.status_code == 200
    data = resp.json()
    assert isinstance(data, list)
    assert any(c["id"] == coffre.id for c in data)


def test_create_movement_entry(auth_admin, coffre):
    client, csrf = auth_admin
    resp = client.post("/api/movements", json={
        "coffre_id": coffre.id,
        "type": "ENTRY",
        "amount": 500.0,
        "description": "Dépôt test",
    }, headers={"X-CSRF-Token": csrf})
    assert resp.status_code == 201
    data = resp.json()
    assert data["amount"] == 500.0
    assert data["type"] == "ENTRY"


def test_update_movement(auth_admin, coffre):
    client, csrf = auth_admin
    mv_id = client.post("/api/movements", json={
        "coffre_id": coffre.id, "type": "ENTRY", "amount": 200.0,
    }, headers={"X-CSRF-Token": csrf}).json()["id"]

    resp = client.put(f"/api/movements/{mv_id}", json={
        "amount": 250.0, "description": "Modifié",
    }, headers={"X-CSRF-Token": csrf})
    assert resp.status_code == 200
    assert resp.json()["ok"] is True


def test_delete_movement(auth_admin, coffre):
    client, csrf = auth_admin
    mv_id = client.post("/api/movements", json={
        "coffre_id": coffre.id, "type": "ENTRY", "amount": 100.0,
    }, headers={"X-CSRF-Token": csrf}).json()["id"]

    resp = client.delete(f"/api/movements/{mv_id}",
                         headers={"X-CSRF-Token": csrf})
    assert resp.status_code == 200
    assert resp.json()["ok"] is True


def test_create_inventory(auth_admin, coffre):
    client, csrf = auth_admin
    resp = client.post("/api/inventories", json={
        "coffre_id": coffre.id,
        "total_amount": 1500.0,
        "notes": "Inventaire test",
        "details": [{"denomination": 50, "quantity": 20},
                    {"denomination": 100, "quantity": 10}],
    }, headers={"X-CSRF-Token": csrf})
    assert resp.status_code == 201
    data = resp.json()
    assert data["total_amount"] == 2000.0  # 50*20 + 100*10


def test_delete_inventory(auth_admin, coffre):
    client, csrf = auth_admin
    inv_id = client.post("/api/inventories", json={
        "coffre_id": coffre.id, "total_amount": 500.0,
    }, headers={"X-CSRF-Token": csrf}).json()["id"]

    resp = client.delete(f"/api/inventories/{inv_id}",
                         headers={"X-CSRF-Token": csrf})
    assert resp.status_code == 200
    assert resp.json()["ok"] is True


def test_invalid_movement_type(auth_admin, coffre):
    client, csrf = auth_admin
    resp = client.post("/api/movements", json={
        "coffre_id": coffre.id, "type": "INVALID", "amount": 100.0,
    }, headers={"X-CSRF-Token": csrf})
    assert resp.status_code == 400
