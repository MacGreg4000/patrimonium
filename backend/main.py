"""Patrimonium — unified wealth management dashboard."""
import logging
import os
from contextlib import asynccontextmanager
from pathlib import Path

# ── Security config ───────────────────────────────────────
_raw_origins = os.getenv("ALLOWED_ORIGINS", "")
ALLOWED_ORIGINS = [o.strip() for o in _raw_origins.split(",") if o.strip()] or [
    "http://localhost:8080",
    "http://localhost:8081",
    "http://127.0.0.1:8080",
    "http://127.0.0.1:8081",
]

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.util import get_remote_address

import auth as auth_utils
import market_data as md
import scheduler as sched
from database import SessionLocal, init_db
from models import Coffre, Position, User

limiter = Limiter(key_func=get_remote_address, default_limits=["200/minute"])

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s — %(message)s",
)
logger = logging.getLogger(__name__)

FRONTEND_DIR = Path(__file__).parent.parent / "frontend"

SEED_POSITIONS = [
    {"display_name": "TotalEnergies", "ticker": "TTE.PA", "asset_type": "action", "currency": "EUR"},
    {"display_name": "Orange", "ticker": "ORA.PA", "asset_type": "action", "currency": "EUR"},
    {"display_name": "Elia Group", "ticker": "ELI.BR", "asset_type": "action", "currency": "EUR"},
    {"display_name": "iShares MSCI World IWDA", "ticker": "IWDA.AS", "asset_type": "etf", "currency": "EUR"},
    {"display_name": "Amundi MSCI EM X9I1", "ticker": "X9I1.PA", "asset_type": "etf", "currency": "EUR"},
    {"display_name": "Or (Gold Futures)", "ticker": "GC=F", "asset_type": "commodity", "currency": "USD"},
    {"display_name": "Candriam Sustainable Bond Euro Corp", "ticker": "MANUAL",
     "asset_type": "bond_manual", "currency": "EUR", "manual_price": 75256.0},
]

SEED_COFFRES = [
    {"name": "Coffre principal", "description": "Coffre-fort physique principal"},
]


def seed(db):
    # First admin from env
    admin_email = os.getenv("FIRST_ADMIN_EMAIL", "")
    admin_pw = os.getenv("FIRST_ADMIN_PASSWORD", "")
    if admin_email and admin_pw and not db.query(User).first():
        user = User(
            email=admin_email.lower(), name="Administrateur",
            hashed_password=auth_utils.hash_password(admin_pw), role="ADMIN",
        )
        db.add(user)
        logger.info(f"Created first admin: {admin_email}")

    # Seed positions
    if db.query(Position).count() == 0:
        for p in SEED_POSITIONS:
            manual_price = p.pop("manual_price", None)
            pos = Position(**p)
            pos.manual_price = manual_price
            db.add(pos)
        logger.info("Seeded portfolio positions")

    # Seed coffres
    if db.query(Coffre).count() == 0:
        for c in SEED_COFFRES:
            db.add(Coffre(**c))
        logger.info("Seeded coffres")

    db.commit()


_INSECURE_SECRET_KEYS = {
    "change-this-in-production",
    "change-this-secret-key-in-production",
    "",
}

@asynccontextmanager
async def lifespan(app: FastAPI):
    # ── Startup security guards ───────────────────────────────
    secret_key = os.getenv("SECRET_KEY", "change-this-in-production")
    if secret_key in _INSECURE_SECRET_KEYS:
        raise RuntimeError(
            "SECRET_KEY is set to an insecure default value. "
            "Set a strong random SECRET_KEY in your .env file before starting."
        )

    enc_key = os.getenv("ENCRYPTION_KEY", "")
    if not enc_key:
        raise RuntimeError(
            "ENCRYPTION_KEY is not set. "
            "Set a valid Fernet key in your .env file before starting."
        )
    # Validate ENCRYPTION_KEY is well-formed (will raise if not)
    try:
        import encryption as _enc_check
        _enc_check.encrypt(b"test")
    except Exception as e:
        raise RuntimeError(f"ENCRYPTION_KEY is invalid: {e}") from e

    init_db()
    db = SessionLocal()
    try:
        seed(db)
    finally:
        db.close()

    # Initial market data fetch
    db2 = SessionLocal()
    try:
        positions = db2.query(Position).filter(Position.is_active == True).all()  # noqa: E712
        md.refresh_all_prices([p.ticker for p in positions])
    except Exception as e:
        logger.warning(f"Initial market fetch failed: {e}")
    finally:
        db2.close()

    sched.start_scheduler(SessionLocal)

    secure_cookies = os.getenv("SECURE_COOKIES", "false").lower() == "true"
    if not secure_cookies:
        logger.warning("SECURE_COOKIES is disabled — cookies will be sent over HTTP. Set SECURE_COOKIES=true in production.")

    yield
    sched.stop_scheduler()


app = FastAPI(title="Patrimonium", version="1.0.0", lifespan=lifespan, docs_url=None, redoc_url=None)
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
    allow_headers=["Content-Type", "X-CSRF-Token", "Authorization"],
)

# ── Security headers ──────────────────────────────────────
# 'unsafe-inline' (script) reste nécessaire tant que les handlers onclick
# inline et Chart.js (CDN jsdelivr) sont utilisés dans le frontend.
_CSP = (
    "default-src 'self'; "
    "script-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net; "
    "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; "
    "font-src 'self' https://fonts.gstatic.com; "
    "img-src 'self' data:; "
    "connect-src 'self'; "
    "object-src 'none'; "
    "base-uri 'self'; "
    "frame-ancestors 'none'"
)
_HSTS_ENABLED = os.getenv("SECURE_COOKIES", "false").lower() == "true"


@app.middleware("http")
async def security_headers(request: Request, call_next):
    response = await call_next(request)
    response.headers["Content-Security-Policy"] = _CSP
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    response.headers["Permissions-Policy"] = "geolocation=(), microphone=(), camera=()"
    if _HSTS_ENABLED:
        response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
    return response

# ── Register routers ──────────────────────────────────────
from routers import auth, admin, coffres, portfolio, physical_assets, reserves, password_files, dashboard, export, saxo_import, revolut_import

app.include_router(auth.router)
app.include_router(admin.router)
app.include_router(coffres.router)
app.include_router(portfolio.router)
app.include_router(physical_assets.router)
app.include_router(reserves.router)
app.include_router(password_files.router)
app.include_router(dashboard.router)
app.include_router(export.router)
app.include_router(saxo_import.router)
app.include_router(revolut_import.router)

# ── Health ────────────────────────────────────────────────

@app.get("/health")
def health():
    from datetime import datetime, timezone
    return {"status": "ok", "timestamp": datetime.now(timezone.utc).isoformat()}


# ── Static frontend ───────────────────────────────────────
if FRONTEND_DIR.exists():
    app.mount("/static", StaticFiles(directory=str(FRONTEND_DIR)), name="static")

    @app.get("/")
    def serve_index():
        return FileResponse(str(FRONTEND_DIR / "index.html"))

    @app.get("/{full_path:path}")
    def serve_spa(full_path: str):
        index = FRONTEND_DIR / "index.html"
        root = FRONTEND_DIR.resolve()
        try:
            fp = (FRONTEND_DIR / full_path).resolve()
        except (ValueError, OSError):
            return FileResponse(str(index))
        # N'autoriser que les fichiers strictement contenus dans FRONTEND_DIR
        if fp.is_file() and (fp == root or root in fp.parents):
            return FileResponse(str(fp))
        return FileResponse(str(index))
