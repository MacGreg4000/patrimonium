"""SaxoBank XLSX import router."""
import re
from datetime import date
from io import BytesIO
from typing import Optional

import openpyxl
from fastapi import APIRouter, Depends, HTTPException, Request, UploadFile, File
from sqlalchemy.orm import Session

from database import get_db
from dependencies import get_current_user, log_audit, require_admin_csrf
from models import Position, Purchase, User

router = APIRouter(prefix="/api/saxo", tags=["saxo"])

# ── Exchange suffix mapping (SaxoBank MIC → yfinance suffix) ─────────────────

_EXCHANGE_MAP = {
    "xams": "AS",   # Euronext Amsterdam
    "xetr": "DE",   # Deutsche Börse / XETRA
    "xpar": "PA",   # Euronext Paris
    "xbru": "BR",   # Euronext Brussels
    "xlon": "L",    # London Stock Exchange
    "xist": "IS",   # Borsa Istanbul
    "xcse": "CO",   # Nasdaq Copenhagen
    "xhel": "HE",   # Nasdaq Helsinki
    "xsto": "ST",   # Nasdaq Stockholm
    "xosl": "OL",   # Oslo Stock Exchange
    "xlis": "LS",   # Euronext Lisbon
    "xmil": "MI",   # Borsa Italiana
    "xmad": "MC",   # Bolsa de Madrid
    "xswx": "SW",   # SIX Swiss Exchange
    "xnys": "",     # NYSE (no suffix)
    "xnas": "",     # NASDAQ (no suffix)
    "arcx": "",     # NYSE Arca (no suffix)
    "bats": "",     # CBOE/BATS (no suffix)
}

_ASSET_TYPE_MAP = {
    "etf":       "etf",
    "stock":     "action",
    "bond":      "bond_manual",
    "commodity": "commodity",
}


def _saxo_symbol_to_yfinance(symbol: str) -> str:
    """Convertit 'IWDA:xams' → 'IWDA.AS', 'AAPL:xnas' → 'AAPL'."""
    if not symbol or ":" not in symbol:
        return symbol.upper() if symbol else "MANUAL"
    ticker, exchange = symbol.split(":", 1)
    suffix = _EXCHANGE_MAP.get(exchange.lower())
    if suffix is None:
        # Exchange inconnu : on garde le ticker brut
        return ticker.upper()
    return f"{ticker.upper()}.{suffix}" if suffix else ticker.upper()


def _parse_event(event: str) -> Optional[tuple[float, float]]:
    """Extrait (quantité, prix_unitaire) depuis 'Achat 84 @ 8.68 EUR'."""
    if not event:
        return None
    m = re.match(r"Achat\s+([\d,\.]+)\s*@\s*([\d,\.]+)", event, re.IGNORECASE)
    if not m:
        return None
    qty   = float(m.group(1).replace(",", "."))
    price = float(m.group(2).replace(",", "."))
    return qty, price


def _parse_saxo_xlsx(content: bytes) -> list[dict]:
    """Parse le fichier XLSX SaxoBank et retourne les transactions d'achat."""
    wb = openpyxl.load_workbook(BytesIO(content), data_only=True)
    ws = wb.active

    rows = list(ws.iter_rows(values_only=True))
    if not rows:
        raise ValueError("Fichier vide")

    # Colonnes (0-indexées) — basées sur le format SaxoBank exporté
    # 1=Date opération, 4=ID opération, 9=Type, 10=Événement,
    # 15=Coût total(frais), 21=Instrument, 22=Symbole, 23=ISIN, 24=Devise, 25=Type actif
    COL = {
        "date":        1,
        "op_id":       4,
        "tx_type":     9,
        "event":       10,
        "fees":        15,
        "instrument":  21,
        "symbol":      22,
        "isin":        23,
        "currency":    24,
        "asset_type":  25,
    }

    transactions = []
    for row in rows[1:]:   # skip header
        tx_type = row[COL["tx_type"]]
        if tx_type != "Transaction":
            continue

        event = row[COL["event"]] or ""
        parsed = _parse_event(event)
        if parsed is None:
            continue   # Vente ou autre — ignoré pour l'instant

        qty, unit_price = parsed
        raw_date = row[COL["date"]]
        if hasattr(raw_date, "date"):
            op_date = raw_date.date()
        elif isinstance(raw_date, str):
            op_date = date.fromisoformat(raw_date[:10])
        else:
            continue

        isin        = row[COL["isin"]] or ""
        symbol      = row[COL["symbol"]] or ""
        instrument  = row[COL["instrument"]] or "Instrument inconnu"
        currency    = row[COL["currency"]] or "EUR"
        asset_type  = (row[COL["asset_type"]] or "").lower()
        fees_raw    = row[COL["fees"]]
        fees        = abs(float(fees_raw)) if fees_raw else 0.0
        op_id       = str(row[COL["op_id"]] or "")

        transactions.append({
            "date":        op_date,
            "op_id":       op_id,
            "instrument":  instrument,
            "symbol":      symbol,
            "isin":        isin,
            "currency":    currency,
            "asset_type":  _ASSET_TYPE_MAP.get(asset_type, "action"),
            "quantity":    qty,
            "unit_price":  unit_price,
            "fees":        fees,
        })

    return transactions


# ── Endpoint ──────────────────────────────────────────────

@router.post("/import")
async def import_saxo(
    request: Request,
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Importe un relevé de transactions SaxoBank (.xlsx)."""
    if not file.filename or not file.filename.lower().endswith(".xlsx"):
        raise HTTPException(status_code=400, detail="Fichier .xlsx requis")

    content = await file.read()
    if len(content) > 10 * 1024 * 1024:
        raise HTTPException(status_code=400, detail="Fichier trop volumineux (max 10 MB)")

    try:
        transactions = _parse_saxo_xlsx(content)
    except Exception as e:
        raise HTTPException(status_code=422, detail=f"Erreur de lecture du fichier: {e}")

    if not transactions:
        raise HTTPException(status_code=422, detail="Aucune transaction d'achat trouvée dans ce fichier")

    created_positions = 0
    created_purchases = 0
    skipped_purchases = 0

    for tx in transactions:
        isin = tx["isin"]
        ticker = _saxo_symbol_to_yfinance(tx["symbol"]) if tx["symbol"] else "MANUAL"

        # --- Trouver ou créer la Position ---
        pos = None
        if isin:
            pos = db.query(Position).filter(Position.isin == isin).first()
        if pos is None and ticker and ticker != "MANUAL":
            pos = db.query(Position).filter(Position.ticker == ticker).first()

        if pos is None:
            pos = Position(
                display_name=tx["instrument"],
                ticker=ticker,
                isin=isin or None,
                asset_type=tx["asset_type"],
                currency=tx["currency"],
            )
            db.add(pos)
            db.flush()   # obtenir pos.id sans commit
            created_positions += 1
        elif isin and not pos.isin:
            # Enrichir une position existante avec l'ISIN
            pos.isin = isin

        # --- Vérifier si cet achat est déjà importé (via note SAXO) ---
        op_id = tx["op_id"]
        saxo_tag = f"[SAXO:{op_id}]" if op_id else None
        if saxo_tag:
            existing = db.query(Purchase).filter(
                Purchase.position_id == pos.id,
                Purchase.note.like(f"%{saxo_tag}%"),
            ).first()
            if existing:
                skipped_purchases += 1
                continue

        purchase = Purchase(
            position_id=pos.id,
            purchase_date=tx["date"],
            quantity=tx["quantity"],
            unit_price=tx["unit_price"],
            fees=tx["fees"],
            note=saxo_tag,
        )
        db.add(purchase)
        created_purchases += 1

    db.commit()
    log_audit(db, user.id, "SAXO_IMPORT",
              f"Import SaxoBank: {created_positions} positions, {created_purchases} achats, {skipped_purchases} doublons ignorés",
              request)

    return {
        "created_positions": created_positions,
        "created_purchases": created_purchases,
        "skipped_purchases": skipped_purchases,
        "total_transactions": len(transactions),
    }
