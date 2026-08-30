"""Crypto router : comptes d'exchange (Kraken, Bitvavo) et positions crypto.

Les clés API sont chiffrées en AES-256-GCM et utilisées uniquement en lecture.
Aucun ordre, trade ou retrait n'est possible depuis cette application.
"""
import logging
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy.orm import Session

import calculations
import encryption
import market_data as md
from database import get_db
from dependencies import get_current_user, log_audit, require_admin_csrf
from exchanges import CASH_TICKERS, EXCHANGE_LABELS, cash_ticker, get_client
from models import ExchangeAccount, Position, Purchase, Sale, User

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/crypto", tags=["crypto"])

FIAT = {"EUR", "USD", "GBP", "CHF", "CAD", "JPY", "AUD"}


class CashSyncError(RuntimeError):
    """Le solde de liquidités n'a pas pu être lu — à remonter à l'utilisateur."""


class AccountCreate(BaseModel):
    exchange: str          # kraken | bitvavo
    label: str
    api_key: str
    api_secret: str


# ── Comptes d'exchange ────────────────────────────────────────

@router.get("/accounts")
def list_accounts(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    accounts = (db.query(ExchangeAccount)
                  .filter(ExchangeAccount.user_id == user.id)
                  .order_by(ExchangeAccount.created_at).all())
    return [_fmt_account(a) for a in accounts]


@router.post("/accounts", status_code=201)
def create_account(data: AccountCreate, request: Request,
                   db: Session = Depends(get_db), user: User = Depends(require_admin_csrf)):
    exchange = data.exchange.lower().strip()
    if exchange not in EXCHANGE_LABELS:
        raise HTTPException(status_code=400, detail=f"Exchange non supporté : {exchange}")
    if not data.api_key.strip() or not data.api_secret.strip():
        raise HTTPException(status_code=400, detail="Clé API et secret sont requis")

    # Vérifie les clés avant de les enregistrer
    try:
        client = get_client(exchange, data.api_key.strip(), data.api_secret.strip())
        status = client.test_connection()
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Connexion échouée — {e}") from e

    acc = ExchangeAccount(
        user_id=user.id,
        exchange=exchange,
        label=data.label.strip() or EXCHANGE_LABELS[exchange],
        encrypted_api_key=encryption.encrypt_str(data.api_key.strip()),
        encrypted_api_secret=encryption.encrypt_str(data.api_secret.strip()),
        last_sync_status=f"Connexion vérifiée — {status}",
    )
    db.add(acc)
    db.commit()
    db.refresh(acc)
    log_audit(db, user.id, "EXCHANGE_ACCOUNT_CREATED",
              f"Compte {EXCHANGE_LABELS[exchange]} ajouté : {acc.label}", request)
    return _fmt_account(acc)


@router.delete("/accounts/{account_id}")
def delete_account(account_id: int, request: Request,
                   db: Session = Depends(get_db), user: User = Depends(require_admin_csrf)):
    acc = _get_account(account_id, db, user)
    label = acc.label
    db.delete(acc)
    db.commit()
    log_audit(db, user.id, "EXCHANGE_ACCOUNT_DELETED", f"Compte supprimé : {label}", request)
    return {"ok": True}


# ── Synchronisation ───────────────────────────────────────────

@router.post("/accounts/{account_id}/sync")
def sync_account(account_id: int, request: Request,
                 db: Session = Depends(get_db), user: User = Depends(require_admin_csrf)):
    acc = _get_account(account_id, db, user)
    result = _sync(acc, db)
    db.commit()
    log_audit(db, user.id, "EXCHANGE_SYNCED",
              f"{acc.label} : {result['created_purchases']} achat(s), "
              f"{result['created_sales']} vente(s)", request)
    return result


@router.post("/sync-all")
def sync_all(request: Request,
             db: Session = Depends(get_db), user: User = Depends(require_admin_csrf)):
    accounts = (db.query(ExchangeAccount)
                  .filter(ExchangeAccount.user_id == user.id,
                          ExchangeAccount.is_active == True).all())  # noqa: E712
    results = []
    for acc in accounts:
        try:
            results.append(_sync(acc, db))
        except HTTPException as e:
            results.append({"account_id": acc.id, "label": acc.label, "error": e.detail})
    db.commit()
    log_audit(db, user.id, "EXCHANGE_SYNCED_ALL", f"{len(accounts)} compte(s) synchronisé(s)", request)
    return {"results": results}


def _sync(acc: ExchangeAccount, db: Session) -> dict:
    """Importe l'historique des trades d'un compte dans Positions/Purchases/Sales."""
    try:
        client = get_client(
            acc.exchange,
            encryption.decrypt_str(acc.encrypted_api_key),
            encryption.decrypt_str(acc.encrypted_api_secret),
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Clés illisibles — {e}") from e

    try:
        if acc.exchange == "bitvavo":
            known = {p.ticker.split("-")[0] for p in _account_positions(acc, db)}
            trades = client.get_trades(extra_assets=known)
        else:
            trades = client.get_trades()
    except Exception as e:
        acc.last_sync_at = datetime.now(timezone.utc)
        acc.last_sync_status = f"Échec : {e}"
        db.commit()
        raise HTTPException(status_code=400, detail=f"Synchronisation échouée — {e}") from e

    prefix = acc.exchange.upper()
    created_purchases = created_sales = skipped = 0
    unsupported: set[str] = set()

    for t in sorted(trades, key=lambda x: x["date"]):
        if t["asset"] in FIAT or t["quantity"] <= 0:
            continue
        if t.get("quote") not in ("EUR", None):
            unsupported.add(f"{t['asset']}/{t['quote']}")
            continue

        tag = f"[{prefix}:{acc.id}:{t['ref']}]"
        pos = _get_or_create_position(acc, t["asset"], db)

        if t["side"] == "sell":
            if db.query(Sale).filter(Sale.position_id == pos.id,
                                     Sale.note.like(f"%{tag}%")).first():
                skipped += 1
                continue
            purchases = db.query(Purchase).filter(Purchase.position_id == pos.id).all()
            total_b = sum(p.quantity for p in purchases)
            total_i = sum(p.quantity * p.unit_price + (p.fees or 0) for p in purchases)
            avg_cost = total_i / total_b if total_b > 0 else 0.0
            db.add(Sale(
                position_id=pos.id, sale_date=t["date"], quantity=t["quantity"],
                unit_price=t["unit_price"], fees=t["fee"],
                realized_pnl=(t["unit_price"] - avg_cost) * t["quantity"] - t["fee"],
                note=tag,
            ))
            created_sales += 1
            sold = sum(s.quantity for s in db.query(Sale)
                       .filter(Sale.position_id == pos.id).all()) + t["quantity"]
            if total_b - sold <= 1e-9:
                pos.is_active = False
        else:
            if db.query(Purchase).filter(Purchase.position_id == pos.id,
                                         Purchase.note.like(f"%{tag}%")).first():
                skipped += 1
                continue
            db.add(Purchase(
                position_id=pos.id, purchase_date=t["date"], quantity=t["quantity"],
                unit_price=t["unit_price"], fees=t["fee"], note=tag,
            ))
            created_purchases += 1
            pos.is_active = True
        db.flush()

    try:
        cash_balance, cash_error = _sync_cash(acc, client, db), None
    except CashSyncError as e:
        cash_balance, cash_error = None, str(e)

    status = (f"{created_purchases} achat(s), {created_sales} vente(s), "
              f"{skipped} déjà connu(s)")
    if cash_error:
        status += f" — liquidités : {cash_error}"
    elif cash_balance is not None:
        status += f", {cash_balance:.2f} € de liquidités"

    acc.last_sync_at = datetime.now(timezone.utc)
    acc.last_sync_status = status[:200]
    return {
        "account_id": acc.id, "label": acc.label,
        "created_purchases": created_purchases,
        "created_sales": created_sales,
        "skipped": skipped,
        "cash_balance_eur": cash_balance,
        "cash_error": cash_error,
        "unsupported_pairs": sorted(unsupported),
    }



def _sync_cash(acc: ExchangeAccount, client, db: Session) -> Optional[float]:
    """Enregistre le solde EUR disponible sur l'exchange comme position cash.

    Sans cela, seul le capital investi remonterait : l'argent non investi qui
    dort sur le compte disparaîtrait du patrimoine.
    """
    try:
        balances = client.get_balances()
    except Exception as e:
        logger.warning(f"{acc.label} : soldes non récupérés ({e})")
        raise CashSyncError(str(e)) from e

    # Trace ce que l'exchange a réellement renvoyé : un 0 « normal » et une clé
    # API sans droit de lecture des fonds sont sinon indiscernables.
    logger.info(f"{acc.label} : soldes lus = {sorted(balances)}")
    if "EUR" not in balances:
        raise CashSyncError(
            "aucun solde EUR renvoyé par l'exchange — vérifie que la clé API a bien "
            f"le droit de lecture des fonds (actifs vus : {', '.join(sorted(balances)) or 'aucun'})"
        )

    balance = round(float(balances["EUR"] or 0.0), 2)
    ticker = cash_ticker(acc.exchange)
    display_name = f"Liquidités · {acc.label}"
    pos = db.query(Position).filter(
        Position.ticker == ticker,
        Position.display_name == display_name,
    ).first()
    today = datetime.now(timezone.utc).date()
    tag = f"[{acc.exchange.upper()}:{acc.id}:CASH]"

    if pos is None:
        # Ne pas créer de ligne « Liquidités » à 0 € : elle encombrerait le tableau
        if balance <= 0:
            return balance
        pos = Position(display_name=display_name, ticker=ticker, asset_type="cash",
                       currency="EUR", manual_price=balance,
                       manual_price_updated_at=datetime.now(timezone.utc))
        db.add(pos)
        db.flush()
    else:
        pos.manual_price = balance
        pos.manual_price_updated_at = datetime.now(timezone.utc)
        pos.is_active = True

    # Une seule ligne d'achat, réécrite à chaque synchro (quantité 1 × solde)
    line = db.query(Purchase).filter(Purchase.position_id == pos.id,
                                     Purchase.note == tag).first()
    if line is None:
        db.add(Purchase(position_id=pos.id, purchase_date=today, quantity=1.0,
                        unit_price=balance, fees=0.0, note=tag))
    else:
        line.unit_price = balance
        line.purchase_date = today
    return balance


def _account_positions(acc: ExchangeAccount, db: Session) -> list[Position]:
    """Positions déjà importées pour ce compte.

    On filtre sur le tag d'import ([KRAKEN:<id>:<ref>]), pas sur le libellé du
    compte : celui-ci est saisi par l'utilisateur et pourrait contenir des
    jokers SQL ou être le suffixe d'un autre libellé.
    """
    tag_prefix = f"[{acc.exchange.upper()}:{acc.id}:"
    return (db.query(Position)
              .join(Purchase, Purchase.position_id == Position.id)
              .filter(Position.asset_type == "crypto",
                      Purchase.note.startswith(tag_prefix))
              .distinct().all())


def _get_or_create_position(acc: ExchangeAccount, asset: str, db: Session) -> Position:
    """Une position par (actif, compte) — le PRU reste séparé par exchange."""
    display_name = f"{asset} · {acc.label}"
    pos = db.query(Position).filter(
        Position.display_name == display_name,
        Position.asset_type == "crypto",
    ).first()
    if pos is None:
        pos = Position(
            display_name=display_name,
            ticker=f"{asset}-EUR",       # format yfinance (BTC-EUR, ETH-EUR…)
            asset_type="crypto",
            currency="EUR",
        )
        db.add(pos)
        db.flush()
    return pos


# ── Vue d'ensemble ────────────────────────────────────────────

@router.get("/summary")
def get_summary(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    positions = db.query(Position).filter(
        Position.asset_type == "crypto",
        Position.is_active == True,  # noqa: E712
    ).all()

    items = []
    for pos in positions:
        price, prev, _ = md.get_price_eur(pos.ticker, pos.currency)
        price = price or 0.0
        m = calculations.calc_position_metrics(pos, price, prev or price, 1.0)
        if (m.get("total_bought") or 0) <= 0:
            continue
        items.append({
            **m,
            "id": pos.id,
            "display_name": pos.display_name,
            "ticker": pos.ticker,
            "asset": pos.ticker.split("-")[0],
            "current_price": price,
        })

    total_value = sum(i["current_value"] for i in items)
    total_invested = sum(i["total_invested"] for i in items)
    total_pnl = sum(i["pnl_eur"] for i in items)
    for i in items:
        i["allocation_pct"] = (i["current_value"] / total_value * 100) if total_value > 0 else 0.0

    # Liquidités disponibles sur les exchanges (argent non investi)
    cash_positions = db.query(Position).filter(
        Position.ticker.in_(CASH_TICKERS),
        Position.is_active == True,  # noqa: E712
    ).all()
    cash_items = [{"id": p.id, "display_name": p.display_name,
                   "balance_eur": p.manual_price or 0.0,
                   "updated_at": p.manual_price_updated_at}
                  for p in cash_positions]
    total_cash = sum(c["balance_eur"] for c in cash_items)

    accounts = (db.query(ExchangeAccount)
                  .filter(ExchangeAccount.user_id == user.id).all())
    return {
        "stats": {
            "total_value_eur": total_value,
            "total_invested_eur": total_invested,
            "total_pnl_eur": total_pnl,
            "total_pnl_pct": (total_pnl / total_invested * 100) if total_invested > 0 else None,
            "total_cash_eur": total_cash,
            "total_account_eur": total_value + total_cash,   # capital total sur les exchanges
            "position_count": len(items),
            "account_count": len(accounts),
        },
        "positions": sorted(items, key=lambda i: i["current_value"], reverse=True),
        "cash": sorted(cash_items, key=lambda c: c["balance_eur"], reverse=True),
        "accounts": [_fmt_account(a) for a in accounts],
    }


# ── Helpers ───────────────────────────────────────────────────

def _get_account(account_id: int, db: Session, user: User) -> ExchangeAccount:
    acc = db.query(ExchangeAccount).filter(
        ExchangeAccount.id == account_id,
        ExchangeAccount.user_id == user.id,
    ).first()
    if not acc:
        raise HTTPException(status_code=404, detail="Compte introuvable")
    return acc


def _fmt_account(a: ExchangeAccount) -> dict:
    """Ne renvoie JAMAIS les clés API, même chiffrées."""
    return {
        "id": a.id,
        "exchange": a.exchange,
        "exchange_label": EXCHANGE_LABELS.get(a.exchange, a.exchange),
        "label": a.label,
        "is_active": a.is_active,
        "last_sync_at": a.last_sync_at,
        "last_sync_status": a.last_sync_status,
    }
