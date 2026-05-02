"""Unit tests for auth.py (JWT, bcrypt, CSRF, TOTP)."""
import auth as auth_utils


def test_hash_and_verify_password():
    pw = "MyStr0ngP@ss!"
    hashed = auth_utils.hash_password(pw)
    assert auth_utils.verify_password(pw, hashed) is True


def test_wrong_password_fails():
    hashed = auth_utils.hash_password("correct")
    assert auth_utils.verify_password("wrong", hashed) is False


def test_create_and_decode_access_token():
    token = auth_utils.create_access_token(user_id=42, role="ADMIN")
    payload = auth_utils.decode_token(token)
    assert payload is not None
    assert payload["sub"] == "42"
    assert payload["role"] == "ADMIN"
    assert payload["type"] == "access"


def test_create_and_decode_refresh_token():
    token = auth_utils.create_refresh_token(user_id=7)
    payload = auth_utils.decode_token(token)
    assert payload is not None
    assert payload["sub"] == "7"
    assert payload["type"] == "refresh"


def test_decode_invalid_token_returns_none():
    assert auth_utils.decode_token("this.is.not.a.jwt") is None


def test_sign_and_verify_csrf_token():
    token = auth_utils.sign_csrf_token(user_id=1)
    assert auth_utils.verify_csrf_token(token, user_id=1) is True


def test_csrf_wrong_user_fails():
    token = auth_utils.sign_csrf_token(user_id=1)
    assert auth_utils.verify_csrf_token(token, user_id=99) is False


def test_csrf_invalid_token_fails():
    assert auth_utils.verify_csrf_token("garbage", user_id=1) is False
