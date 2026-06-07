"""Revolut Invest CSV import router."""
import re
from datetime import date, datetime, timezone
from io import StringIO

import pandas as pd
from fastapi import APIRouter, Depends, HTTPException, Request, UploadFile, File
from sqlalchemy.orm import Session

from database import get_db
from dependencies import get_current_user, log_audit, require_admin_csrf
from models import Position, Purchase, Sale, User

router = APIRouter(prefix="/api/revolut", tags=["revolut"])

# ── Mapping ticker Revolut → ticker yfinance ─────────────────────────────────
# Revolut utilise ses propres codes internes qui diffèrent souvent de yfinance.
# Ajouter ici tout nouveau ticker rencontré lors des imports.
_REVOLUT_TO_YFINANCE: dict[str, str] = {
    # Actions françaises (Euronext Paris)
    "AIL":   "AI.PA",      # Air Liquide
    "SGM":   "SGO.PA",     # Saint-Gobain
    "TOTB":  "TTE.PA",     # TotalEnergies
    "ACA":   "ACA.PA",     # Crédit Agricole
    "BNP":   "BNP.PA",     # BNP Paribas
    "SAN":   "SAN.PA",     # Sanofi
    "OR":    "OR.PA",      # L'Oréal
    "MC":    "MC.PA",      # LVMH
    "RMS":   "RMS.PA",     # Hermès
    "SU":    "SU.PA",      # Schneider Electric
    "ORA":   "ORA.PA",     # Orange
    "VIE":   "VIE.PA",     # Veolia
    "DG":    "DG.PA",      # Vinci
    "AI":    "AI.PA",      # Air Liquide (alias)
    "CAP":   "CAP.PA",     # Capgemini
    "SAF":   "SAF.PA",     # Safran
    "DSY":   "DSY.PA",     # Dassault Systèmes
    "HO":    "HO.PA",      # Thales
    "PUB":   "PUB.PA",     # Publicis
    "VK":    "VK.PA",      # Vallourec
    # Actions US
    "AAPL":  "AAPL",
    "MSFT":  "MSFT",
    "NVDA":  "NVDA",
    "GOOGL": "GOOGL",
    "AMZN":  "AMZN",
    "META":  "META",
    "TSLA":  "TSLA",
    # ETF (Euronext Amsterdam / XETRA)
    "EUNL":  "EUNL.AS",    # iShares Core MSCI World
    "IWDA":  "IWDA.AS",    # iShares MSCI World
    "CSPX":  "CSPX.AS",    # iShares Core S&P 500
    "VWCE":  "VWCE.DE",    # Vanguard FTSE All-World Acc
    "VUSA":  "VUSA.AS",    # Vanguard S&P 500
    "X9I1":  "X9I1.DE",    # Xtrackers MSCI World Swap
    "XDWD":  "XDWD.DE",    # Xtrackers MSCI World
    "MEUD":  "MEUD.PA",    # Amundi MSCI Europe
    "IMAE":  "IMAE.AS",    # iShares MSCI EM
    "IUSQ":  "IUSQ.DE",    # iShares MSCI World Quality
    "SWDA":  "SWDA.AS",    # iShares Core MSCI World (GBP)
    "LYPS":  "LYPS.DE",    # Lyxor S&P 500
    "PAEEM": "PAEEM.PA",   # Amundi MSCI Emerging Markets
    "PANX":  "PANX.PA",    # Amundi Nasdaq-100
}

# ETF connus pour le type d'actif (basé sur les valeurs ci-dessus)
_ETF_REVOLUT_TICKERS = {
    "EUNL", "IWDA", "CSPX", "VWCE", "VUSA", "MEUD", "X9I1", "IMAE",
    "IUSQ", "SWDA", "XDWD", "LYPS", "PAEEM", "PANX", "PRAE",
}


def _revolut_ticker_to_yfinance(revolut_ticker: str) -> str:
    """Convertit un ticker Revolut en ticker yfinance. Retourne le ticker brut si inconnu."""
    return _REVOLUT_TO_YFINANCE.get(revolut_ticker.upper(), revolut_ticker.upper())


def _guess_asset_type(revolut_ticker: str) -> str:
    return "etf" if revolut_ticker.upper() in _ETF_REVOLUT_TICKERS else "action"


def _parse_amount(val) -> float:
    """Extrait un float depuis une valeur type 'EUR 2200' ou '-400' ou 2200.0."""
    if val is None or (isinstance(val, float) and pd.isna(val)):
        return 0.0
    s = str(val).strip()
    # Supprimer le préfixe de devise (ex: "EUR ", "USD ")
    s = re.sub(r'^[A-Z]{3}\s*', '', s)
    try:
        return float(s.replace(',', '.'))
    except ValueError:
        return 0.0


def _parse_revolut_csv(content: bytes) -> tuple[list[dict], float]:
    """
    Parse le CSV Revolut Invest.

    Format attendu (colonnes fixes) :
      Date, Ticker, Type, Quantity, Price per share, Total Amount, Currency, FX Rate

    Types gérés :
      BUY - MARKET  → achat
      SELL - MARKET → vente
      DIVIDEND      → dividende (ignoré — pas de transaction d'achat/vente)
      CASH TOP-UP   → dépôt (ignoré pour les positions, utilisé pour le solde cash)
      CASH WITHDRAWAL → retrait (idem)

    Retourne (transactions, solde_cash).
    Le solde cash = Σ TOP-UP − Σ WITHDRAWAL − Σ achats + Σ ventes + Σ dividendes
    """
    text = content.decode("utf-8-sig")  # gère éventuel BOM
    df = pd.read_csv(StringIO(text))

    # Normaliser les noms de colonnes
    df.columns = [c.strip() for c in df.columns]

    required = {"Date", "Ticker", "Type", "Quantity", "Price per share", "Total Amount", "Currency"}
    missing = required - set(df.columns)
    if missing:
        raise ValueError(f"Colonnes manquantes dans le fichier : {missing}")

    transactions = []
    cash_balance = 0.0

    for _, row in df.iterrows():
        tx_type   = str(row.get("Type", "")).strip()
        ticker    = str(row.get("Ticker", "")).strip()
        amount    = _parse_amount(row.get("Total Amount"))
        currency  = str(row.get("Currency", "EUR")).strip()

        # Statut du relevé : on ne filtre pas sur COMPLETED car Revolut
        # n'inclut que les opérations complètes dans ses exports CSV.

        # ── Flux de trésorerie (pas de position) ─────────────────────────
        if tx_type == "CASH TOP-UP":
            cash_balance += abs(amount)
            continue
        if tx_type == "CASH WITHDRAWAL":
            cash_balance -= abs(amount)
            continue
        if tx_type == "DIVIDEND":
            cash_balance += abs(amount)
            continue
        if not ticker or ticker == "nan":
            continue  # ligne sans ticker non gérée

        # ── Parsing de la date ────────────────────────────────────────────
        raw_date = str(row.get("Date", "")).strip()
        try:
            # Format ISO 8601 : 2026-01-16T04:07:36.468093Z
            tx_date = datetime.fromisoformat(raw_date.replace("Z", "+00:00")).date()
        except ValueError:
            try:
                tx_date = datetime.strptime(raw_date[:10], "%Y-%m-%d").date()
            except ValueError:
                continue  # date non parseable, on ignore

        qty        = float(str(row.get("Quantity", 0)).replace(",", ".") or 0)
        unit_price = _parse_amount(row.get("Price per share"))

        if qty <= 0 or unit_price <= 0:
            continue

        is_buy  = tx_type.startswith("BUY")
        is_sell = tx_type.startswith("SELL")
        if not is_buy and not is_sell:
            continue

        # Mettre à jour le solde cash
        if is_buy:
            cash_balance -= abs(amount)
        else:
            cash_balance += abs(amount)

        # Tag de déduplication : date ISO + ticker + quantité (pas d'ID dans Revolut)
        revolut_tag = f"[REVOLUT:{tx_date.isoformat()}:{ticker}:{qty}]"

        yf_ticker = _revolut_ticker_to_yfinance(ticker)
        transactions.append({
            "date":           tx_date,
            "revolut_ticker": ticker.upper(),    # ticker original Revolut (pour le tag)
            "ticker":         yf_ticker,         # ticker yfinance (pour les cours)
            "is_sale":        is_sell,
            "quantity":       round(qty, 8),
            "unit_price":     round(unit_price, 6),
            "fees":           0.0,
            "currency":       currency,
            "asset_type":     _guess_asset_type(ticker),
            "revolut_tag":    revolut_tag,
        })

    return transactions, round(cash_balance, 2)


@router.post("/import")
@require_admin_csrf
async def import_revolut(
    request: Request,
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Importe un relevé de transactions Revolut Invest (.csv)."""
    if not file.filename or not file.filename.lower().endswith(".csv"):
        raise HTTPException(status_code=400, detail="Fichier .csv requis")

    content = await file.read()
    if len(content) > 10 * 1024 * 1024:
        raise HTTPException(status_code=400, detail="Fichier trop volumineux (max 10 MB)")

    try:
        transactions, cash_balance = _parse_revolut_csv(content)
    except Exception as e:
        raise HTTPException(status_code=422, detail=f"Erreur de lecture du fichier : {e}")

    if not transactions:
        raise HTTPException(
            status_code=422,
            detail="Aucune transaction BUY/SELL trouvée dans ce fichier"
        )

    created_positions = 0
    created_purchases = 0
    skipped_purchases = 0
    created_sales     = 0
    skipped_sales     = 0
    fuzzy_duplicates  = 0
    unknown_tickers   = {
        tx["revolut_ticker"] for tx in transactions
        if tx["revolut_ticker"] not in _REVOLUT_TO_YFINANCE
    }

    for tx in transactions:
        ticker = tx["ticker"]

        # ── Trouver ou créer la Position ──────────────────────────────────
        pos = db.query(Position).filter(Position.ticker == ticker).first()
        if pos is None:
            pos = Position(
                display_name=ticker,   # sera enrichi par yfinance au premier refresh
                ticker=ticker,
                asset_type=tx["asset_type"],
                currency=tx["currency"],
            )
            db.add(pos)
            db.flush()
            created_positions += 1

        revolut_tag = tx["revolut_tag"]

        # ── Vente ─────────────────────────────────────────────────────────
        if tx["is_sale"]:
            # Déduplication par tag
            if db.query(Sale).filter(
                Sale.position_id == pos.id,
                Sale.note.like(f"%{revolut_tag}%"),
            ).first():
                skipped_sales += 1
                continue

            # P&L réalisé basé sur le PRU moyen
            all_purchases = db.query(Purchase).filter(Purchase.position_id == pos.id).all()
            total_b = sum(p.quantity for p in all_purchases)
            total_i = sum(p.quantity * p.unit_price + p.fees for p in all_purchases)
            avg_c   = total_i / total_b if total_b > 0 else 0.0
            rpnl    = (tx["unit_price"] - avg_c) * tx["quantity"] - tx["fees"]

            db.add(Sale(
                position_id=pos.id,
                sale_date=tx["date"],
                quantity=tx["quantity"],
                unit_price=tx["unit_price"],
                fees=tx["fees"],
                realized_pnl=rpnl,
                note=revolut_tag,
            ))
            created_sales += 1

            # Auto-archiver si la position est entièrement vendue
            all_purchases_q = db.query(Purchase).filter(Purchase.position_id == pos.id).all()
            prev_sales      = db.query(Sale).filter(Sale.position_id == pos.id).all()
            net_qty = (
                sum(p.quantity for p in all_purchases_q)
                - sum(s.quantity for s in prev_sales)
                - tx["quantity"]
            )
            if net_qty <= 0.0001:
                pos.is_active = False
            continue

        # ── Achat — déduplication par tag ────────────────────────────────
        if db.query(Purchase).filter(
            Purchase.position_id == pos.id,
            Purchase.note.like(f"%{revolut_tag}%"),
        ).first():
            skipped_purchases += 1
            continue

        # Déduplication fuzzy : (date, qté, prix)
        if db.query(Purchase).filter(
            Purchase.position_id == pos.id,
            Purchase.purchase_date == tx["date"],
            Purchase.quantity == tx["quantity"],
            Purchase.unit_price == tx["unit_price"],
        ).first():
            fuzzy_duplicates += 1
            continue

        db.add(Purchase(
            position_id=pos.id,
            purchase_date=tx["date"],
            quantity=tx["quantity"],
            unit_price=tx["unit_price"],
            fees=tx["fees"],
            note=revolut_tag,
        ))
        created_purchases += 1

    # ── Mise à jour des liquidités Revolut ───────────────────────────────
    REVOLUT_CASH_TICKER = "REVOLUT:EUR"
    cash_pos = db.query(Position).filter(Position.ticker == REVOLUT_CASH_TICKER).first()
    now_utc  = datetime.now(timezone.utc)

    if cash_pos is None:
        cash_pos = Position(
            display_name="Liquidités Revolut",
            ticker=REVOLUT_CASH_TICKER,
            asset_type="cash",
            currency="EUR",
            manual_price=max(0.0, round(cash_balance, 2)),
            manual_price_updated_at=now_utc,
        )
        db.add(cash_pos)
        db.flush()
        db.add(Purchase(
            position_id=cash_pos.id,
            purchase_date=date.today(),
            quantity=1.0,
            unit_price=max(0.0, round(cash_balance, 2)),
            fees=0.0,
            note="[REVOLUT:CASH]",
        ))
    else:
        cash_pos.manual_price = max(0.0, round(cash_balance, 2))
        cash_pos.manual_price_updated_at = now_utc
        cash_pos.is_active = True
        vp = db.query(Purchase).filter(
            Purchase.position_id == cash_pos.id,
            Purchase.note == "[REVOLUT:CASH]",
        ).first()
        if vp:
            vp.unit_price    = max(0.0, round(cash_balance, 2))
            vp.purchase_date = date.today()
        else:
            db.add(Purchase(
                position_id=cash_pos.id,
                purchase_date=date.today(),
                quantity=1.0,
                unit_price=max(0.0, round(cash_balance, 2)),
                fees=0.0,
                note="[REVOLUT:CASH]",
            ))

    db.commit()

    log_audit(
        db, user.id, "REVOLUT_IMPORT",
        f"Import Revolut: {created_positions} positions, {created_purchases} achats, "
        f"{created_sales} ventes, {skipped_purchases + skipped_sales} doublons, "
        f"{fuzzy_duplicates} doublons fuzzy, liquidités: {cash_balance:.2f} EUR",
        request,
    )

    return {
        "created_positions":  created_positions,
        "created_purchases":  created_purchases,
        "created_sales":      created_sales,
        "skipped_purchases":  skipped_purchases,
        "skipped_sales":      skipped_sales,
        "fuzzy_duplicates":   fuzzy_duplicates,
        "total_transactions": len(transactions),
        "cash_balance_eur":   round(cash_balance, 2),
        "unknown_tickers":    sorted(unknown_tickers),   # tickers sans mapping yfinance
    }
