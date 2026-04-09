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


@asynccontextmanager
async def lifespan(app: FastAPI):
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

# ── Register routers ──────────────────────────────────────
from routers import auth, admin, coffres, portfolio, physical_assets, reserves, password_files, dashboard, export

app.include_router(auth.router)
app.include_router(admin.router)
app.include_router(coffres.router)
app.include_router(portfolio.router)
app.include_router(physical_assets.router)
app.include_router(reserves.router)
app.include_router(password_files.router)
app.include_router(dashboard.router)
app.include_router(export.router)

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
        fp = FRONTEND_DIR / full_path
        if fp.exists() and fp.is_file():
            return FileResponse(str(fp))
        return FileResponse(str(FRONTEND_DIR / "index.html"))
