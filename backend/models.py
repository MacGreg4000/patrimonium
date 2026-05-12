"""SQLAlchemy models for Patrimonium."""
from datetime import datetime, timezone
from sqlalchemy import (
    Boolean, Column, Date, DateTime, Float, ForeignKey,
    Integer, LargeBinary, String, Text, UniqueConstraint,
)
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from database import Base


def utcnow():
    return datetime.now(timezone.utc)


# ── Users ─────────────────────────────────────────────────────────────────────

class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True)
    email = Column(String(255), unique=True, nullable=False, index=True)
    name = Column(String(100), nullable=False)
    hashed_password = Column(String(255), nullable=False)
    role = Column(String(20), nullable=False, default="USER")  # ADMIN | USER
    is_active = Column(Boolean, default=True)
    two_factor_enabled = Column(Boolean, default=False)
    two_factor_secret = Column(Text, nullable=True)      # AES-256-GCM encrypted
    two_factor_backup = Column(Text, nullable=True)      # JSON list of bcrypt hashes
    created_at = Column(DateTime(timezone=True), default=utcnow)
    updated_at = Column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)

    movements = relationship("Movement", back_populates="user")
    inventories = relationship("Inventory", back_populates="user")
    physical_assets = relationship("PhysicalAsset", back_populates="user")
    reserves = relationship("Reserve", back_populates="user")
    password_files = relationship("PasswordFile", back_populates="user")
    audit_logs = relationship("AuditLog", back_populates="user")


# ── Coffres ───────────────────────────────────────────────────────────────────

class Coffre(Base):
    __tablename__ = "coffres"

    id = Column(Integer, primary_key=True)
    name = Column(String(100), nullable=False)
    description = Column(Text, nullable=True)
    is_active = Column(Boolean, default=True)
    encrypted_combination = Column(LargeBinary, nullable=True)   # AES-256-GCM
    combination_hint = Column(String(200), nullable=True)        # indice mémo (non chiffré)
    created_at = Column(DateTime(timezone=True), default=utcnow)

    movements = relationship("Movement", back_populates="coffre")
    inventories = relationship("Inventory", back_populates="coffre")
    physical_assets = relationship("PhysicalAsset", back_populates="coffre")


class Movement(Base):
    __tablename__ = "movements"

    id = Column(Integer, primary_key=True)
    coffre_id = Column(Integer, ForeignKey("coffres.id"), nullable=False, index=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    type = Column(String(10), nullable=False)   # ENTRY | EXIT
    amount = Column(Float, nullable=False)
    description = Column(Text, nullable=True)
    deleted_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), default=utcnow, index=True)

    coffre = relationship("Coffre", back_populates="movements")
    user = relationship("User", back_populates="movements")
    details = relationship("MovementDetail", back_populates="movement", cascade="all, delete-orphan")


class MovementDetail(Base):
    __tablename__ = "movement_details"

    id = Column(Integer, primary_key=True)
    movement_id = Column(Integer, ForeignKey("movements.id", ondelete="CASCADE"), nullable=False)
    denomination = Column(Float, nullable=False)   # 5,10,20,50,100,200,500
    quantity = Column(Integer, nullable=False)

    movement = relationship("Movement", back_populates="details")


class Inventory(Base):
    __tablename__ = "inventories"

    id = Column(Integer, primary_key=True)
    coffre_id = Column(Integer, ForeignKey("coffres.id"), nullable=False, index=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    total_amount = Column(Float, nullable=False)
    notes = Column(Text, nullable=True)
    date = Column(DateTime(timezone=True), default=utcnow, index=True)
    deleted_at = Column(DateTime(timezone=True), nullable=True)

    coffre = relationship("Coffre", back_populates="inventories")
    user = relationship("User", back_populates="inventories")
    details = relationship("InventoryDetail", back_populates="inventory", cascade="all, delete-orphan")


class InventoryDetail(Base):
    __tablename__ = "inventory_details"

    id = Column(Integer, primary_key=True)
    inventory_id = Column(Integer, ForeignKey("inventories.id", ondelete="CASCADE"), nullable=False)
    denomination = Column(Float, nullable=False)
    quantity = Column(Integer, nullable=False)

    inventory = relationship("Inventory", back_populates="details")


# ── Stock Portfolio ───────────────────────────────────────────────────────────

class Position(Base):
    __tablename__ = "positions"

    id = Column(Integer, primary_key=True)
    display_name = Column(String(100), nullable=False)
    ticker = Column(String(20), nullable=False)        # "MANUAL" for manual positions
    isin = Column(String(20), nullable=True, index=True)  # ISIN pour sync SaxoBank
    asset_type = Column(String(20), nullable=False)    # action|etf|commodity|bond_manual
    currency = Column(String(3), nullable=False, default="EUR")
    is_active = Column(Boolean, default=True)
    alert_gain_pct = Column(Float, nullable=True)
    alert_loss_pct = Column(Float, nullable=True)
    manual_price = Column(Float, nullable=True)
    manual_price_updated_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), default=utcnow)

    purchases = relationship("Purchase", back_populates="position", cascade="all, delete-orphan")


class Purchase(Base):
    __tablename__ = "purchases"

    id = Column(Integer, primary_key=True)
    position_id = Column(Integer, ForeignKey("positions.id"), nullable=False)
    purchase_date = Column(Date, nullable=False)
    quantity = Column(Float, nullable=False)
    unit_price = Column(Float, nullable=False)
    fees = Column(Float, default=0.0)
    note = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), default=utcnow)

    position = relationship("Position", back_populates="purchases")


class PortfolioSnapshot(Base):
    __tablename__ = "portfolio_snapshots"

    id = Column(Integer, primary_key=True)
    timestamp = Column(DateTime(timezone=True), default=utcnow, index=True)
    total_value_eur = Column(Float, nullable=False)
    total_invested_eur = Column(Float, nullable=False)
    total_pnl_eur = Column(Float, nullable=False)


# ── Physical Assets ───────────────────────────────────────────────────────────

class PhysicalAsset(Base):
    __tablename__ = "physical_assets"

    id = Column(Integer, primary_key=True)
    name = Column(String(150), nullable=False)
    category = Column(String(50), nullable=True)   # bijou|immo|vehicule|art|metal|autre
    description = Column(Text, nullable=True)
    estimated_value = Column(Float, nullable=True)
    coffre_id = Column(Integer, ForeignKey("coffres.id"), nullable=True)
    location = Column(String(300), nullable=True)  # adresse libre (ex: immo)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    created_at = Column(DateTime(timezone=True), default=utcnow)
    updated_at = Column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)

    # ── Vente (archivage) ───────────────────────────────────
    sold_at = Column(DateTime(timezone=True), nullable=True)           # null = non vendu
    sale_price = Column(Float, nullable=True)
    sale_destination = Column(String(50), nullable=True)               # portfolio|bank|coffre|cash|other
    sale_notes = Column(String(500), nullable=True)

    # ── Véhicule (renseignés uniquement si category == 'vehicule') ──
    vehicle_make = Column(String(100), nullable=True)    # Marque (ex: BMW)
    vehicle_model = Column(String(100), nullable=True)   # Modèle (ex: Série 3)
    vehicle_year = Column(Integer, nullable=True)        # Année (ex: 2021)
    vehicle_plate = Column(String(30), nullable=True)    # Immatriculation
    vehicle_vin = Column(String(50), nullable=True)      # Numéro de châssis VIN
    vehicle_fuel = Column(String(30), nullable=True)     # Carburant (essence|diesel|hybride|électrique)
    vehicle_km = Column(Integer, nullable=True)          # Kilométrage actuel

    coffre = relationship("Coffre", back_populates="physical_assets")
    user = relationship("User", back_populates="physical_assets")
    events = relationship("AssetEvent", back_populates="asset", cascade="all, delete-orphan")
    documents = relationship("AssetDocument", back_populates="asset", cascade="all, delete-orphan")


class AssetEvent(Base):
    __tablename__ = "asset_events"

    id = Column(Integer, primary_key=True)
    asset_id = Column(Integer, ForeignKey("physical_assets.id", ondelete="CASCADE"), nullable=False)
    type = Column(String(20), nullable=False)   # PURCHASE|SALE|VALUATION
    amount = Column(Float, nullable=True)
    date = Column(Date, nullable=False)
    notes = Column(Text, nullable=True)

    asset = relationship("PhysicalAsset", back_populates="events")


class AssetDocument(Base):
    __tablename__ = "asset_documents"

    id = Column(Integer, primary_key=True)
    asset_id = Column(Integer, ForeignKey("physical_assets.id", ondelete="CASCADE"), nullable=False)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    filename = Column(String(255), nullable=False)
    mime_type = Column(String(100), nullable=False)
    size_bytes = Column(Integer, nullable=False)
    sha256 = Column(String(64), nullable=True)
    encrypted_data = Column(LargeBinary, nullable=False)
    document_type = Column(String(50), nullable=True)
    notes = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), default=utcnow)

    asset = relationship("PhysicalAsset", back_populates="documents")


# ── Reserves ──────────────────────────────────────────────────────────────────

class Reserve(Base):
    __tablename__ = "reserves"
    __table_args__ = (UniqueConstraint("user_id", "year", "month", name="uq_reserve_user_year_month"),)

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    year = Column(Integer, nullable=False)
    month = Column(Integer, nullable=False)
    amount = Column(Float, default=0.0)
    release_year = Column(Integer, nullable=True)
    released = Column(Float, default=0.0)
    precompte_paye = Column(Float, default=0.0)   # précompte mobilier payé à la libération
    notes = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), default=utcnow)
    updated_at = Column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)

    user = relationship("User", back_populates="reserves")


# ── Password Files ────────────────────────────────────────────────────────────

class PasswordFile(Base):
    __tablename__ = "password_files"

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    filename = Column(String(255), nullable=False)
    mime_type = Column(String(100), nullable=False)
    size_bytes = Column(Integer, nullable=False)
    sha256 = Column(String(64), nullable=True)
    encrypted_data = Column(LargeBinary, nullable=False)
    created_at = Column(DateTime(timezone=True), default=utcnow)

    user = relationship("User", back_populates="password_files")


# ── Refresh Tokens ───────────────────────────────────────────────────────────

class RefreshToken(Base):
    __tablename__ = "refresh_tokens"

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    token_hash = Column(String(64), nullable=False, unique=True, index=True)  # SHA-256 hex
    expires_at = Column(DateTime(timezone=True), nullable=False)
    revoked = Column(Boolean, default=False, nullable=False)
    created_at = Column(DateTime(timezone=True), default=utcnow)

    user = relationship("User")


# ── Password Reset Tokens ────────────────────────────────────────────────────

class PasswordResetToken(Base):
    __tablename__ = "password_reset_tokens"

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    token_hash = Column(String(64), nullable=False, unique=True, index=True)  # SHA-256 hex
    expires_at = Column(DateTime(timezone=True), nullable=False)
    used = Column(Boolean, default=False, nullable=False)
    created_at = Column(DateTime(timezone=True), default=utcnow)

    user = relationship("User")


# ── Audit Logs ────────────────────────────────────────────────────────────────

class AuditLog(Base):
    __tablename__ = "audit_logs"

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    action = Column(String(100), nullable=False, index=True)
    description = Column(Text, nullable=True)
    metadata_ = Column("metadata", Text, nullable=True)   # JSON string
    ip_address = Column(String(45), nullable=True)
    user_agent = Column(String(500), nullable=True)
    created_at = Column(DateTime(timezone=True), default=utcnow, index=True)

    user = relationship("User", back_populates="audit_logs")
