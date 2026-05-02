"""Integration tests for /api/auth/* routes."""
import pytest
from unittest.mock import patch


def test_login_success(client, admin_user):
    resp = client.post(
        "/api/auth/login",
        json={"email": "admin@test.com", "password": "AdminPass123!"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["ok"] is True
    assert data["user"]["email"] == "admin@test.com"
    assert data["user"]["role"] == "ADMIN"
    # Cookies must be set
    assert "access_token" in client.cookies
    assert "refresh_token" in client.cookies


def test_login_wrong_password(client, admin_user):
    resp = client.post(
        "/api/auth/login",
        json={"email": "admin@test.com", "password": "WrongPass!"},
    )
    assert resp.status_code == 401


def test_login_unknown_email(client):
    resp = client.post(
        "/api/auth/login",
        json={"email": "nobody@test.com", "password": "Whatever!"},
    )
    assert resp.status_code == 401


def test_logout_clears_cookies(client, admin_user):
    client.post("/api/auth/login",
                json={"email": "admin@test.com", "password": "AdminPass123!"})
    assert "access_token" in client.cookies

    resp = client.post("/api/auth/logout")
    assert resp.status_code == 200
    assert client.cookies.get("access_token") in (None, "")


def test_csrf_endpoint_requires_auth(client):
    resp = client.get("/api/auth/csrf")
    assert resp.status_code == 401


def test_csrf_endpoint_returns_token(client, admin_user):
    client.post("/api/auth/login",
                json={"email": "admin@test.com", "password": "AdminPass123!"})
    resp = client.get("/api/auth/csrf")
    assert resp.status_code == 200
    assert "csrf_token" in resp.json()
    assert len(resp.json()["csrf_token"]) > 10


def test_me_returns_current_user(client, admin_user):
    client.post("/api/auth/login",
                json={"email": "admin@test.com", "password": "AdminPass123!"})
    resp = client.get("/api/auth/me")
    assert resp.status_code == 200
    data = resp.json()
    assert data["email"] == "admin@test.com"
    assert data["role"] == "ADMIN"


def test_change_password_success(client, admin_user):
    client.post("/api/auth/login",
                json={"email": "admin@test.com", "password": "AdminPass123!"})
    csrf = client.get("/api/auth/csrf").json()["csrf_token"]
    resp = client.post(
        "/api/auth/change-password",
        json={"old_password": "AdminPass123!", "new_password": "NewPass456!"},
        headers={"X-CSRF-Token": csrf},
    )
    assert resp.status_code == 200
    assert resp.json()["ok"] is True


def test_change_password_wrong_old(client, admin_user):
    client.post("/api/auth/login",
                json={"email": "admin@test.com", "password": "AdminPass123!"})
    csrf = client.get("/api/auth/csrf").json()["csrf_token"]
    resp = client.post(
        "/api/auth/change-password",
        json={"old_password": "WrongOld!", "new_password": "NewPass456!"},
        headers={"X-CSRF-Token": csrf},
    )
    assert resp.status_code == 401


def test_refresh_token_renews_access(client, admin_user):
    client.post("/api/auth/login",
                json={"email": "admin@test.com", "password": "AdminPass123!"})

    resp = client.post("/api/auth/refresh")
    assert resp.status_code == 200
    # A new access_token cookie must be set after refresh
    assert client.cookies.get("access_token") is not None


def test_refresh_token_replay_rejected(client, admin_user):
    """Using the same refresh token twice must be rejected."""
    client.post("/api/auth/login",
                json={"email": "admin@test.com", "password": "AdminPass123!"})
    old_refresh = client.cookies.get("refresh_token")

    # First use — OK
    assert client.post("/api/auth/refresh").status_code == 200

    # Replay the old token manually
    client.cookies.set("refresh_token", old_refresh)
    resp = client.post("/api/auth/refresh")
    assert resp.status_code == 401


def test_forgot_password_unknown_email(client):
    """Unknown email returns 200 (no enumeration)."""
    resp = client.post("/api/auth/forgot-password",
                       json={"email": "nobody@example.com"})
    assert resp.status_code == 200
    assert resp.json()["ok"] is True


def test_forgot_and_reset_password(client, admin_user, db):
    """Full reset flow: request token → use it → login with new password."""
    with patch("mailer.send_password_reset"):
        resp = client.post("/api/auth/forgot-password",
                           json={"email": "admin@test.com"})
    assert resp.status_code == 200

    # Retrieve the raw token from DB (test only)
    from models import PasswordResetToken
    import hashlib
    rt = db.query(PasswordResetToken).filter(
        PasswordResetToken.user_id == admin_user.id,
        PasswordResetToken.used == False,  # noqa: E712
    ).first()
    assert rt is not None

    # We need the raw token — stored as hash, so reconstruct via brute force not
    # possible. Instead, grab it by patching the mailer to capture the token.
    captured = {}
    def _capture(email, token):
        captured["token"] = token

    with patch("mailer.send_password_reset", side_effect=_capture):
        client.post("/api/auth/forgot-password",
                    json={"email": "admin@test.com"})

    raw_token = captured["token"]
    resp = client.post("/api/auth/reset-password",
                       json={"token": raw_token, "new_password": "NewResetPass99!"})
    assert resp.status_code == 200
    assert resp.json()["ok"] is True

    # Login with new password must succeed
    resp = client.post("/api/auth/login",
                       json={"email": "admin@test.com", "password": "NewResetPass99!"})
    assert resp.status_code == 200


def test_reset_password_token_single_use(client, admin_user):
    """A reset token can only be used once."""
    captured = {}
    def _capture(email, token):
        captured["token"] = token

    with patch("mailer.send_password_reset", side_effect=_capture):
        client.post("/api/auth/forgot-password",
                    json={"email": "admin@test.com"})

    token = captured["token"]
    client.post("/api/auth/reset-password",
                json={"token": token, "new_password": "FirstReset99!"})
    resp = client.post("/api/auth/reset-password",
                       json={"token": token, "new_password": "SecondReset99!"})
    assert resp.status_code == 400
