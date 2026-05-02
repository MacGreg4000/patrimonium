"""Integration tests for /api/admin/* routes."""
import pytest

NEW_USER = {
    "email": "newuser@test.com",
    "name": "New User",
    "password": "NewPass123!",
    "role": "USER",
}


def test_list_users(auth_admin, admin_user):
    client, _ = auth_admin
    resp = client.get("/api/admin/users")
    assert resp.status_code == 200
    data = resp.json()
    assert isinstance(data, list)
    assert any(u["email"] == "admin@test.com" for u in data)


def test_create_user(auth_admin):
    client, csrf = auth_admin
    resp = client.post("/api/admin/users", json=NEW_USER,
                       headers={"X-CSRF-Token": csrf})
    assert resp.status_code == 201
    data = resp.json()
    assert data["email"] == "newuser@test.com"
    assert data["role"] == "USER"


def test_create_user_duplicate_email(auth_admin):
    client, csrf = auth_admin
    client.post("/api/admin/users", json=NEW_USER,
                headers={"X-CSRF-Token": csrf})
    resp = client.post("/api/admin/users", json=NEW_USER,
                       headers={"X-CSRF-Token": csrf})
    assert resp.status_code == 400


def test_update_user(auth_admin):
    client, csrf = auth_admin
    user_id = client.post("/api/admin/users", json=NEW_USER,
                          headers={"X-CSRF-Token": csrf}).json()["id"]

    resp = client.put(f"/api/admin/users/{user_id}",
                      json={"name": "Updated Name"},
                      headers={"X-CSRF-Token": csrf})
    assert resp.status_code == 200
    assert resp.json()["ok"] is True


def test_delete_user(auth_admin):
    client, csrf = auth_admin
    user_id = client.post("/api/admin/users", json=NEW_USER,
                          headers={"X-CSRF-Token": csrf}).json()["id"]

    resp = client.delete(f"/api/admin/users/{user_id}",
                         headers={"X-CSRF-Token": csrf})
    assert resp.status_code == 200
    assert resp.json()["ok"] is True

    # Deleted user should not appear in list
    users = client.get("/api/admin/users").json()
    assert all(u["id"] != user_id for u in users)


def test_admin_cannot_delete_own_account(auth_admin, admin_user):
    client, csrf = auth_admin
    resp = client.delete(f"/api/admin/users/{admin_user.id}",
                         headers={"X-CSRF-Token": csrf})
    assert resp.status_code == 400


def test_create_coffre(auth_admin):
    client, csrf = auth_admin
    resp = client.post("/api/admin/coffres",
                       json={"name": "Coffre Admin Test"},
                       headers={"X-CSRF-Token": csrf})
    assert resp.status_code == 201
    assert resp.json()["name"] == "Coffre Admin Test"


def test_list_admin_requires_admin(auth_user):
    resp = auth_user.get("/api/admin/users")
    assert resp.status_code == 403
