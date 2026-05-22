"""SaxoBank XLSX import router."""
import re
from datetime import date, datetime, timezone
from io import BytesIO
from typing import Optional

import openpyxl
from fastapi import APIRouter, Depends, HTTPException, Request, UploadFile, File
from sqlalchemy.orm import Session

from database import get_db
from dependencies import get_current_user, log_audit, require_admin_csrf
from models import Position, Purchase, Sale, User

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


def _parse_sale_event(event: str) -> Optional[tuple[float, float]]:
    """Extrait (quantité, prix_unitaire) depuis 'Vente 84 @ 8.52 EUR'."""
    if not event:
        return None
    m = re.match(r"Vente\s+([\d,\.]+)\s*@\s*([\d,\.]+)", event, re.IGNORECASE)
    if not m:
        return None
    qty   = float(m.group(1).replace(",", "."))
    price = float(m.group(2).replace(",", "."))
    return qty, price


def _parse_saxo_xlsx(content: bytes) -> tuple[list[dict], float]:
    """Parse le fichier XLSX SaxoBank.
    Retourne (transactions, cash_balance).
    Le cash_balance = Σ(Montant comptabilisé) sur toutes les lignes —
    valide uniquement si le fichier couvre l'historique complet du compte.
    """
    wb = openpyxl.load_workbook(BytesIO(content), data_only=True)
    ws = wb.active

    rows = list(ws.iter_rows(values_only=True))
    if not rows:
        raise ValueError("Fichier vide")

    # Colonnes (0-indexées) — basées sur le format SaxoBank exporté
    # 1=Date opération, 4=ID opération, 9=Type, 10=Événement,
    # 11=Montant comptabilisé, 15=Coût total(frais),
    # 21=Instrument, 22=Symbole, 23=ISIN, 24=Devise, 25=Type actif
    COL = {
        "date":        1,
        "op_id":       4,
        "tx_type":     9,
        "event":       10,
        "amount":      11,   # Montant comptabilisé (pour calcul cash)
        "fees":        15,
        "instrument":  21,
        "symbol":      22,
        "isin":        23,
        "currency":    24,
        "asset_type":  25,
    }

    # Solde cash = somme de tous les montants comptabilisés (valide si export complet)
    cash_balance = 0.0
    for row in rows[1:]:
        amt = row[COL["amount"]]
        if amt is not None:
            try:
                cash_balance += float(amt)
            except (ValueError, TypeError):
                pass

    transactions = []
    for row in rows[1:]:   # skip header
        tx_type = row[COL["tx_type"]]
        if tx_type != "Transaction":
            continue

        event = row[COL["event"]] or ""
        parsed      = _parse_event(event)
        sale_parsed = _parse_sale_event(event)
        if parsed is None and sale_parsed is None:
            continue   # Autre type d'opération — ignoré

        if parsed:
            qty, unit_price = parsed
        else:
            qty, unit_price = sale_parsed
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
            "is_sale":     sale_parsed is not None and parsed is None,
        })

    return transactions, cash_balance


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
        transactions, cash_balance = _parse_saxo_xlsx(content)
    except Exception as e:
        raise HTTPException(status_code=422, detail=f"Erreur de lecture du fichier: {e}")

    if not transactions:
        raise HTTPException(status_code=422, detail="Aucune transaction d'achat ou de vente trouvée dans ce fichier")

    created_positions = 0
    created_purchases = 0
    skipped_purchases = 0   # dédupliqués par ID SaxoBank
    fuzzy_duplicates  = 0   # dédupliqués par (date, qté, prix) — même transaction, ID différent
    created_sales     = 0
    skipped_sales     = 0

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

        op_id    = tx["op_id"]
        saxo_tag = f"[SAXO:{op_id}]" if op_id else None

        # ── Vente ─────────────────────────────────────────────
        if tx.get("is_sale"):
            qty_sold, sale_price = tx["quantity"], tx["unit_price"]

            # Déduplication par SAXO op_id
            if saxo_tag and db.query(Sale).filter(
                Sale.position_id == pos.id,
                Sale.note.like(f"%{saxo_tag}%"),
            ).first():
                skipped_sales += 1
                continue

            # Calcul du P&L réalisé sur base du PRU moyen
            all_purchases = db.query(Purchase).filter(Purchase.position_id == pos.id).all()
            total_b = sum(p.quantity for p in all_purchases)
            total_i = sum(p.quantity * p.unit_price + p.fees for p in all_purchases)
            avg_c   = total_i / total_b if total_b > 0 else 0.0
            rpnl    = (sale_price - avg_c) * qty_sold - tx["fees"]

            db.add(Sale(
                position_id=pos.id,
                sale_date=tx["date"],
                quantity=qty_sold,
                unit_price=sale_price,
                fees=tx["fees"],
                realized_pnl=rpnl,
                note=saxo_tag,
            ))
            created_sales += 1

            # Auto-archiver si la position est entièrement vendue
            prev_sales = db.query(Sale).filter(Sale.position_id == pos.id).all()
            net_qty = total_b - sum(s.quantity for s in prev_sales) - qty_sold
            if net_qty <= 0.0001:
                pos.is_active = False
            continue

        # ── Achat — Déduplication 1 : ID SaxoBank ────────────
        if saxo_tag:
            existing = db.query(Purchase).filter(
                Purchase.position_id == pos.id,
                Purchase.note.like(f"%{saxo_tag}%"),
            ).first()
            if existing:
                skipped_purchases += 1
                continue

        # --- Déduplication 2 : (date, quantité, prix unitaire) ---
        # SaxoBank peut exporter la même transaction avec des IDs différents
        # selon la période (ex : transaction pending → réglée).
        fuzzy_existing = db.query(Purchase).filter(
            Purchase.position_id == pos.id,
            Purchase.purchase_date == tx["date"],
            Purchase.quantity == tx["quantity"],
            Purchase.unit_price == tx["unit_price"],
        ).first()
        if fuzzy_existing:
            fuzzy_duplicates += 1
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

    # ── Mise à jour des liquidités SaxoBank ───────────────────
    # Le solde cash = Σ(Montant comptabilisé) sur l'historique complet
    SAXO_CASH_TICKER = "SAXO:EUR"
    cash_pos = db.query(Position).filter(Position.ticker == SAXO_CASH_TICKER).first()
    now_utc = datetime.now(timezone.utc)
    if cash_pos is None:
        cash_pos = Position(
            display_name="Liquidités SaxoBank",
            ticker=SAXO_CASH_TICKER,
            asset_type="cash",
            currency="EUR",
            manual_price=round(cash_balance, 2),
            manual_price_updated_at=now_utc,
        )
        db.add(cash_pos)
        db.flush()
        db.add(Purchase(
            position_id=cash_pos.id,
            purchase_date=date.today(),
            quantity=1.0,
            unit_price=round(cash_balance, 2),
            fees=0.0,
            note="[SAXO:CASH]",
        ))
    else:
        cash_pos.manual_price = round(cash_balance, 2)
        cash_pos.manual_price_updated_at = now_utc
        cash_pos.is_active = True   # réactiver si archivé
        vp = db.query(Purchase).filter(
            Purchase.position_id == cash_pos.id,
            Purchase.note == "[SAXO:CASH]",
        ).first()
        if vp:
            vp.unit_price = round(cash_balance, 2)
            vp.purchase_date = date.today()
        else:
            db.add(Purchase(
                position_id=cash_pos.id,
                purchase_date=date.today(),
                quantity=1.0,
                unit_price=round(cash_balance, 2),
                fees=0.0,
                note="[SAXO:CASH]",
            ))

    db.commit()
    log_audit(db, user.id, "SAXO_IMPORT",
              f"Import SaxoBank: {created_positions} positions, {created_purchases} achats, "
              f"{created_sales} ventes, {skipped_purchases} doublons (ID), "
              f"{fuzzy_duplicates} doublons (date/qté/prix), "
              f"liquidités: {cash_balance:.2f} EUR",
              request)

    return {
        "created_positions": created_positions,
        "created_purchases": created_purchases,
        "created_sales":     created_sales,
        "skipped_purchases": skipped_purchases,
        "skipped_sales":     skipped_sales,
        "fuzzy_duplicates":  fuzzy_duplicates,
        "total_transactions": len(transactions),
        "cash_balance_eur":  round(cash_balance, 2),
    }
