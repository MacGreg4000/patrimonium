"""Shared pytest fixtures for Patrimonium backend tests."""
import base64
import os
import secrets

# ── Set test env vars BEFORE any app import ───────────────
os.environ["DATABASE_URL"] = "sqlite:///./test_patrimonium.db"
os.environ["SECRET_KEY"] = "test-secret-key-for-testing-purposes-only"
os.environ["ENCRYPTION_KEY"] = base64.urlsafe_b64encode(secrets.token_bytes(32)).decode()
os.environ["SECURE_COOKIES"] = "false"
os.environ["FIRST_ADMIN_EMAIL"] = ""   # skip auto-seeding
os.environ["FIRST_ADMIN_PASSWORD"] = ""

import pytest
from unittest.mock import MagicMock, patch
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from database import Base, get_db
from models import Coffre, User
import auth as auth_utils

# ── Test database (SQLite) ────────────────────────────────

TEST_DB_URL = "sqlite:///./test_patrimonium.db"
test_engine = create_engine(TEST_DB_URL, connect_args={"check_same_thread": False})
TestSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=test_engine)


@pytest.fixture(autouse=True)
def _disable_rate_limiting():
    """Disable slowapi rate limiting for all tests."""
    def _noop_check(self, request, *args, **kwargs):
        request.state.view_rate_limit = None

    with patch("slowapi.extension.Limiter._check_request_limit", _noop_check):
        yield


@pytest.fixture(scope="session", autouse=True)
def _setup_db():
    """Create all tables once per test session, drop them at the end."""
    Base.metadata.create_all(bind=test_engine)
    yield
    Base.metadata.drop_all(bind=test_engine)
    if os.path.exists("test_patrimonium.db"):
        os.remove("test_patrimonium.db")


@pytest.fixture
def db(_setup_db):
    """Transactional test session — rolls back after each test."""
    connection = test_engine.connect()
    transaction = connection.begin()
    session = TestSessionLocal(bind=connection)
    yield session
    session.close()
    transaction.rollback()
    connection.close()


# ── App & TestClient ──────────────────────────────────────

@pytest.fixture
def client(db):
    """TestClient with get_db overridden to use the test session."""
    # Patch external calls so tests don't hit yfinance or start background jobs
    with (
        patch("market_data.refresh_all_prices"),
        patch("scheduler.start_scheduler"),
        patch("scheduler.stop_scheduler"),
    ):
        from main import app

        def _override_get_db():
            yield db

        app.dependency_overrides[get_db] = _override_get_db
        with TestClient(app, raise_server_exceptions=True) as c:
            yield c
        app.dependency_overrides.clear()


# ── User fixtures ─────────────────────────────────────────

@pytest.fixture
def admin_user(db) -> User:
    user = User(
        email="admin@test.com",
        name="Admin Test",
        hashed_password=auth_utils.hash_password("AdminPass123!"),
        role="ADMIN",
        is_active=True,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


@pytest.fixture
def regular_user(db) -> User:
    user = User(
        email="user@test.com",
        name="User Test",
        hashed_password=auth_utils.hash_password("UserPass123!"),
        role="USER",
        is_active=True,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


# ── Authenticated client fixtures ─────────────────────────

@pytest.fixture
def auth_admin(client, admin_user):
    """Authenticated TestClient (ADMIN) with CSRF token set in headers.

    Returns (client, csrf_token).
    """
    resp = client.post(
        "/api/auth/login",
        json={"email": "admin@test.com", "password": "AdminPass123!"},
    )
    assert resp.status_code == 200, resp.text

    csrf_resp = client.get("/api/auth/csrf")
    assert csrf_resp.status_code == 200
    csrf_token = csrf_resp.json()["csrf_token"]
    client.headers.update({"X-CSRF-Token": csrf_token})
    return client, csrf_token


@pytest.fixture
def auth_user(client, regular_user):
    """Authenticated TestClient (USER, read-only)."""
    resp = client.post(
        "/api/auth/login",
        json={"email": "user@test.com", "password": "UserPass123!"},
    )
    assert resp.status_code == 200, resp.text
    return client


# ── Data fixtures ─────────────────────────────────────────

@pytest.fixture
def coffre(db, admin_user) -> Coffre:
    c = Coffre(name="Coffre Test", description="Coffre pour tests")
    db.add(c)
    db.commit()
    db.refresh(c)
    return c
