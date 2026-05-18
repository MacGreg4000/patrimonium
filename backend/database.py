import logging
import os

from sqlalchemy import create_engine, text
from sqlalchemy.orm import DeclarativeBase, sessionmaker

logger = logging.getLogger(__name__)

DATABASE_URL = os.getenv(
    "DATABASE_URL",
    "postgresql+psycopg2://patrimonium:changeme@localhost:5432/patrimonium",
)

engine = create_engine(DATABASE_URL, pool_pre_ping=True, pool_size=10, max_overflow=20)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


class Base(DeclarativeBase):
    pass


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


# ── Migrations ────────────────────────────────────────────
# Chaque entrée est (description, sql).
# Toutes les instructions doivent être idempotentes (IF NOT EXISTS).
# Ne jamais supprimer de colonnes ou de données ici.
_MIGRATIONS: list[tuple[str, str]] = [
    ("pgcrypto extension",
     "CREATE EXTENSION IF NOT EXISTS pgcrypto"),
    ("positions.isin column",
     "ALTER TABLE positions ADD COLUMN IF NOT EXISTS isin VARCHAR(20)"),
    ("positions.isin index",
     "CREATE INDEX IF NOT EXISTS ix_positions_isin ON positions (isin)"),
    ("physical_assets.location column",
     "ALTER TABLE physical_assets ADD COLUMN IF NOT EXISTS location VARCHAR(300)"),
    ("reserves.precompte_paye column",
     "ALTER TABLE reserves ADD COLUMN IF NOT EXISTS precompte_paye FLOAT DEFAULT 0.0"),
    ("coffres.encrypted_combination column",
     "ALTER TABLE coffres ADD COLUMN IF NOT EXISTS encrypted_combination BYTEA"),
    ("coffres.combination_hint column",
     "ALTER TABLE coffres ADD COLUMN IF NOT EXISTS combination_hint VARCHAR(200)"),
    ("physical_assets.sold_at column",
     "ALTER TABLE physical_assets ADD COLUMN IF NOT EXISTS sold_at TIMESTAMPTZ"),
    ("physical_assets.sale_price column",
     "ALTER TABLE physical_assets ADD COLUMN IF NOT EXISTS sale_price FLOAT"),
    ("physical_assets.sale_destination column",
     "ALTER TABLE physical_assets ADD COLUMN IF NOT EXISTS sale_destination VARCHAR(50)"),
    ("physical_assets.sale_notes column",
     "ALTER TABLE physical_assets ADD COLUMN IF NOT EXISTS sale_notes VARCHAR(500)"),
    ("coffres.is_favorite column",
     "ALTER TABLE coffres ADD COLUMN IF NOT EXISTS is_favorite BOOLEAN DEFAULT FALSE"),
]


def run_migrations() -> None:
    """Applique les migrations DDL avant que l'ORM ne charge les modèles.
    Chaque migration est exécutée dans sa propre transaction pour éviter
    qu'une erreur bloque les suivantes."""
    for description, sql in _MIGRATIONS:
        try:
            with engine.begin() as conn:   # auto-commit à la sortie du bloc
                conn.execute(text(sql))
            logger.debug("Migration OK : %s", description)
        except Exception as exc:
            # Loggué mais non-bloquant (ex: extension déjà présente)
            logger.warning("Migration ignorée (%s) : %s", description, exc)


def init_db() -> None:
    """Migrations d'abord, création des tables ensuite."""
    run_migrations()           # DDL incrémental sur les tables existantes
    import models  # noqa: F401  (enregistre les classes auprès de Base)
    Base.metadata.create_all(bind=engine)  # crée les nouvelles tables
