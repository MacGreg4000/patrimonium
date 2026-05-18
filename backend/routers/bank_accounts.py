"""Bank accounts router — GoCardless Bank Account Data integration."""
import uuid
import logging
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session

from database import get_db
from dependencies import get_current_user, log_audit, require_admin_csrf
from models import BankAccount, BankRequisition
import services.gocardless as gc

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api", tags=["bank"])


# ── Schemas ───────────────────────────────────────────────────────────────────

class RequisitionCreate(BaseModel):
    institution_id: str
    institution_name: Optional[str] = None
    institution_logo: Optional[str] = None


# ── Helpers ───────────────────────────────────────────────────────────────────

def _fmt_account(a: BankAccount, req: BankRequisition) -> dict:
    return {
        "id": a.id,
        "account_id": a.account_id,
        "iban": a.iban,
        "name": a.name,
        "owner_name": a.owner_name,
        "balance": a.balance,
        "currency": a.currency,
        "last_synced_at": a.last_synced_at.isoformat() if a.last_synced_at else None,
        "institution_name": req.institution_name,
        "institution_logo": req.institution_logo,
        "requisition_status": req.status,
        "requisition_db_id": req.id,
    }


def _sync_account(a: BankAccount) -> None:
    """Fetch fresh balances from GoCardless and update the account in place."""
    try:
        balances = gc.get_account_balances(a.account_id)
        amount, currency = gc.pick_best_balance(balances)
        a.balance = amount
        a.currency = currency
        a.last_synced_at = datetime.now(timezone.utc)
    except Exception as exc:
        logger.warning("Failed to sync account %s: %s", a.account_id, exc)


# ── Endpoints ─────────────────────────────────────────────────────────────────

@router.get("/bank/status")
def bank_status():
    """Public — returns whether GoCardless is configured."""
    return {"configured": gc.is_configured()}


@router.get("/bank/institutions")
def list_institutions(
    country: str = "BE",
    user=Depends(get_current_user),
):
    """Return list of available banks for the given country from GoCardless."""
    if not gc.is_configured():
        raise HTTPException(status_code=503, detail="GoCardless non configuré")
    try:
        institutions = gc.get_institutions(country)
    except Exception as exc:
        logger.error("GoCardless get_institutions error: %s", exc)
        raise HTTPException(status_code=502, detail=f"Erreur GoCardless : {exc}")
    return institutions


@router.get("/bank/accounts")
def list_bank_accounts(
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
    """Return all bank accounts from DB with institution info."""
    requisitions = db.query(BankRequisition).all()
    result = []
    for req in requisitions:
        for acc in req.accounts:
            if acc.is_active:
                result.append(_fmt_account(acc, req))
    return result


@router.post("/bank/requisitions", status_code=201)
def create_requisition(
    body: RequisitionCreate,
    request: Request,
    db: Session = Depends(get_db),
    user=Depends(require_admin_csrf),
):
    """Create a GoCardless requisition and persist it in DB.

    Returns ``{id: <db_id>, link: <authorization_url>}``.
    """
    if not gc.is_configured():
        raise HTTPException(status_code=503, detail="GoCardless non configuré")

    redirect_url = str(request.base_url).rstrip("/") + "/api/bank/callback"
    reference = str(uuid.uuid4())[:8]

    try:
        data = gc.create_requisition(
            institution_id=body.institution_id,
            redirect_url=redirect_url,
            reference=reference,
        )
    except Exception as exc:
        logger.error("GoCardless create_requisition error: %s", exc)
        raise HTTPException(status_code=502, detail=f"Erreur GoCardless : {exc}")

    req = BankRequisition(
        requisition_id=data["id"],
        institution_id=body.institution_id,
        institution_name=body.institution_name,
        institution_logo=body.institution_logo,
        status="CR",
    )
    db.add(req)
    db.commit()
    db.refresh(req)

    log_audit(
        db, user.id, "BANK_REQUISITION_CREATED",
        f"Réquisition GoCardless créée pour {body.institution_name or body.institution_id}",
        request,
    )

    return {"id": req.id, "link": data.get("link", "")}


@router.get("/bank/callback", response_class=HTMLResponse)
def bank_callback(
    ref: Optional[str] = None,
    error: Optional[str] = None,
    details: Optional[str] = None,
    db: Session = Depends(get_db),
):
    """GoCardless redirect callback. Fetches requisition status and links accounts."""

    success = False
    message = "Connexion bancaire traitée."

    if error:
        message = f"Erreur GoCardless : {error}. {details or ''}"
    elif ref:
        # ref is the GoCardless reference (not the requisition UUID)
        # We need to find the requisition by reference — but GoCardless sends
        # the requisition_id in the `ref` query parameter in some flows.
        # Try to look up by requisition_id first.
        req = db.query(BankRequisition).filter(
            BankRequisition.requisition_id == ref
        ).first()

        if req is None:
            message = "Réquisition introuvable."
        else:
            try:
                gc_data = gc.get_requisition(req.requisition_id)
                gc_status = gc_data.get("status", "CR")
                req.status = gc_status
                db.commit()

                if gc_status == "LN":
                    account_ids = gc_data.get("accounts", [])
                    for account_id in account_ids:
                        existing = db.query(BankAccount).filter(
                            BankAccount.account_id == account_id
                        ).first()
                        if existing:
                            # Re-activate if needed
                            existing.is_active = True
                            _sync_account(existing)
                            db.commit()
                            continue

                        try:
                            details_data = gc.get_account_details(account_id)
                            balances = gc.get_account_balances(account_id)
                            amount, currency = gc.pick_best_balance(balances)
                        except Exception as exc:
                            logger.warning("Failed to fetch account %s: %s", account_id, exc)
                            details_data = {}
                            amount, currency = 0.0, "EUR"

                        acc = BankAccount(
                            requisition_id=req.id,
                            account_id=account_id,
                            iban=details_data.get("iban"),
                            name=details_data.get("name") or details_data.get("product"),
                            owner_name=details_data.get("ownerName"),
                            balance=amount,
                            currency=currency,
                            last_synced_at=datetime.now(timezone.utc),
                            is_active=True,
                        )
                        db.add(acc)

                    db.commit()
                    success = True
                    message = "Comptes bancaires connectés avec succès."
                else:
                    message = f"Statut de la réquisition : {gc_status}. Veuillez réessayer."
            except Exception as exc:
                logger.error("Callback processing error: %s", exc)
                message = f"Erreur lors du traitement : {exc}"
    else:
        message = "Paramètres de callback manquants."

    status_icon = "✓" if success else "⚠"
    status_color = "#22c55e" if success else "#f59e0b"

    html = f"""<!DOCTYPE html>
<html lang="fr">
<head>
  <meta charset="UTF-8"/>
  <meta name="viewport" content="width=device-width,initial-scale=1"/>
  <title>Patrimonium — Connexion bancaire</title>
  <style>
    body {{
      background: #05080F;
      color: #e2e8f0;
      font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
      display: flex;
      align-items: center;
      justify-content: center;
      min-height: 100vh;
      margin: 0;
    }}
    .card {{
      background: #0d1117;
      border: 1px solid #1e2535;
      border-radius: 12px;
      padding: 40px 48px;
      text-align: center;
      max-width: 420px;
    }}
    .icon {{ font-size: 48px; margin-bottom: 16px; color: {status_color}; }}
    h1 {{ font-size: 20px; font-weight: 600; margin: 0 0 12px; }}
    p {{ font-size: 14px; color: #94a3b8; margin: 0 0 24px; }}
    .redirect {{ font-size: 12px; color: #475569; }}
  </style>
</head>
<body>
  <div class="card">
    <div class="icon">{status_icon}</div>
    <h1>Connexion bancaire</h1>
    <p>{message}</p>
    <div class="redirect">Redirection vers Patrimonium dans <span id="cnt">3</span>s…</div>
  </div>
  <script>
    let n = 3;
    const el = document.getElementById('cnt');
    const iv = setInterval(() => {{
      n--;
      if (el) el.textContent = n;
      if (n <= 0) {{ clearInterval(iv); window.location.href = '/'; }}
    }}, 1000);
  </script>
</body>
</html>"""

    return HTMLResponse(content=html)


@router.post("/bank/sync")
def sync_all_accounts(
    request: Request,
    db: Session = Depends(get_db),
    user=Depends(require_admin_csrf),
):
    """Sync balances for all active bank accounts."""
    if not gc.is_configured():
        raise HTTPException(status_code=503, detail="GoCardless non configuré")

    accounts = db.query(BankAccount).filter(BankAccount.is_active == True).all()  # noqa: E712
    for acc in accounts:
        _sync_account(acc)
    db.commit()

    log_audit(db, user.id, "BANK_SYNC_ALL", "Synchronisation de tous les comptes bancaires", request)

    result = []
    for acc in accounts:
        req = acc.requisition
        result.append(_fmt_account(acc, req))
    return result


@router.post("/bank/sync/{account_id}")
def sync_single_account(
    account_id: int,
    request: Request,
    db: Session = Depends(get_db),
    user=Depends(require_admin_csrf),
):
    """Sync balance for a single bank account (by DB id)."""
    if not gc.is_configured():
        raise HTTPException(status_code=503, detail="GoCardless non configuré")

    acc = db.query(BankAccount).filter(BankAccount.id == account_id).first()
    if not acc:
        raise HTTPException(status_code=404, detail="Compte introuvable")

    _sync_account(acc)
    db.commit()

    log_audit(
        db, user.id, "BANK_SYNC_ACCOUNT",
        f"Synchronisation du compte {acc.iban or acc.account_id}",
        request,
    )
    return _fmt_account(acc, acc.requisition)


@router.delete("/bank/requisitions/{requisition_db_id}", status_code=204)
def delete_requisition_endpoint(
    requisition_db_id: int,
    request: Request,
    db: Session = Depends(get_db),
    user=Depends(require_admin_csrf),
):
    """Delete a requisition from GoCardless and from DB (cascade deletes accounts)."""
    req = db.query(BankRequisition).filter(BankRequisition.id == requisition_db_id).first()
    if not req:
        raise HTTPException(status_code=404, detail="Réquisition introuvable")

    try:
        gc.delete_requisition(req.requisition_id)
    except Exception as exc:
        logger.warning("GoCardless delete_requisition error (continuing): %s", exc)

    institution_name = req.institution_name or req.institution_id
    db.delete(req)
    db.commit()

    log_audit(
        db, user.id, "BANK_REQUISITION_DELETED",
        f"Réquisition GoCardless supprimée pour {institution_name}",
        request,
    )
