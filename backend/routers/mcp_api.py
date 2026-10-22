"""Surface de lecture exposée au connecteur MCP.

Routeur volontairement séparé des routes de l'application : ce qui est
accessible au connecteur est donc explicite et auditable d'un coup d'œil,
plutôt que dispersé dans les routeurs existants.

Garanties :
  - uniquement des routes GET, protégées par `require_read_token` qui refuse
    toute méthode mutante et n'accepte qu'un jeton de portée "read" ;
  - le coffre à mots de passe, les fichiers chiffrés et les combinaisons de
    coffres ne sont exposés par AUCUNE route de ce fichier ;
  - aucune écriture en base, hormis l'horodatage d'usage du jeton.
"""
from datetime import date
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from database import get_db
from dependencies import require_read_token
from exchanges import CASH_TICKERS
from models import User

router = APIRouter(prefix="/api/mcp", tags=["mcp"])

# Événements du journal jamais exposés : ils concernent le coffre à mots de
# passe (noms de fichiers) ou les combinaisons de coffres.
_HIDDEN_AUDIT_PREFIXES = ("PWFILE_", "COFFRE_COMBINATION_")


def _poche(pos) -> str:
    """Poche d'une position : la crypto et les liquidités d'exchange à part."""
    return "crypto" if pos.asset_type == "crypto" or pos.ticker in CASH_TICKERS else "titres"


def _page_args(page: int, limit: int, max_limit: int) -> tuple[int, int]:
    return max(1, page), max(1, min(limit, max_limit))


@router.get("/patrimoine")
def mcp_patrimoine(db: Session = Depends(get_db), user: User = Depends(require_read_token)):
    """Vue d'ensemble : total du patrimoine et répartition par poche."""
    from routers.dashboard import get_dashboard
    d = get_dashboard(db=db, user=user)
    return {
        "patrimoine_total_eur": d["grand_total_eur"],
        "portefeuille_titres": d["portfolio"],
        "crypto": d["crypto"],
        "liquidites_coffres": {
            "total_eur": d["cash"]["total_eur"],
            "coffres": d["cash"]["coffres"],
        },
        "actifs_physiques": d["assets"],
        "reserves": d["reserves"],
        "marche_ouvert": d["is_market_open"],
        "derniere_maj": d["last_updated"],
    }


@router.get("/portefeuille")
def mcp_portfolio(db: Session = Depends(get_db), user: User = Depends(require_read_token)):
    """Positions titres : quantité, PRU, valeur, plus/moins-value."""
    from routers.portfolio import get_portfolio_summary
    return get_portfolio_summary(db=db, user=user)


@router.get("/crypto")
def mcp_crypto(db: Session = Depends(get_db), user: User = Depends(require_read_token)):
    """Positions crypto et liquidités disponibles sur les exchanges."""
    from routers.crypto import get_summary
    data = get_summary(db=db, user=user)
    # Les comptes d'exchange sont volontairement réduits à leur nom : le
    # connecteur n'a aucun besoin de connaître leur état de synchronisation.
    return {
        "stats": data["stats"],
        "positions": data["positions"],
        "liquidites": data["cash"],
        "comptes": [a["label"] for a in data["accounts"]],
    }


@router.get("/coffres")
def mcp_coffres(db: Session = Depends(get_db), user: User = Depends(require_read_token)):
    """Soldes des coffres. Les combinaisons ne sont jamais renvoyées."""
    from models import Coffre
    from routers.coffres import compute_balance
    coffres = db.query(Coffre).filter(Coffre.is_active == True).all()  # noqa: E712
    items = [{"id": c.id, "nom": c.name, "description": c.description,
              "solde_eur": compute_balance(c.id, db)} for c in coffres]
    return {"total_eur": sum(i["solde_eur"] for i in items), "coffres": items}


@router.get("/mouvements")
def mcp_movements(coffre_id: Optional[int] = None, page: int = 1, limit: int = 50,
                  db: Session = Depends(get_db), user: User = Depends(require_read_token)):
    """Mouvements d'espèces (entrées, sorties, transferts), paginés, plus récents d'abord."""
    from routers.coffres import list_movements
    page, limit = _page_args(page, limit, 100)
    return list_movements(coffre_id=coffre_id, page=page, limit=limit, db=db, user=user)


@router.get("/inventaires")
def mcp_inventories(coffre_id: Optional[int] = None, page: int = 1, limit: int = 50,
                    db: Session = Depends(get_db), user: User = Depends(require_read_token)):
    """Inventaires (comptages) des coffres avec le détail des coupures."""
    from routers.coffres import list_inventories
    page, limit = _page_args(page, limit, 100)
    return list_inventories(coffre_id=coffre_id, page=page, limit=limit, db=db, user=user)


@router.get("/actifs")
def mcp_assets(db: Session = Depends(get_db), user: User = Depends(require_read_token)):
    """Actifs physiques non vendus : immobilier, véhicules, bijoux…"""
    from routers.physical_assets import list_assets
    return list_assets(search=None, category=None, coffre_id=None, sold=False,
                       db=db, user=user)


@router.get("/actifs-vendus")
def mcp_sold_assets(db: Session = Depends(get_db), user: User = Depends(require_read_token)):
    """Actifs physiques vendus : prix de vente, date et destination des fonds."""
    from routers.physical_assets import list_assets
    return list_assets(search=None, category=None, coffre_id=None, sold=True,
                       db=db, user=user)


@router.get("/transactions")
def mcp_transactions(position_id: Optional[int] = None, ticker: Optional[str] = None,
                     sens: Optional[str] = None, poche: Optional[str] = None,
                     date_debut: Optional[date] = None, date_fin: Optional[date] = None,
                     inclure_liquidites: bool = False,
                     page: int = 1, limit: int = 100,
                     db: Session = Depends(get_db), user: User = Depends(require_read_token)):
    """Historique complet des achats et ventes, titres et crypto, positions
    clôturées comprises. Plus récentes d'abord.

    sens ∈ {achat, vente} ; poche ∈ {titres, crypto} ; dates au format AAAA-MM-JJ.
    Les positions de liquidités (Saxo, exchanges) sont exclues par défaut : leurs
    « achats » sont des écritures techniques de suivi de solde, pas des opérations.
    """
    from models import Position, Purchase, Sale
    if sens not in (None, "achat", "vente"):
        raise HTTPException(status_code=422, detail="sens doit valoir achat ou vente")
    if poche not in (None, "titres", "crypto"):
        raise HTTPException(status_code=422, detail="poche doit valoir titres ou crypto")
    page, limit = _page_args(page, limit, 500)

    def _row(kind, tx_id, tx_date, pos, qty, price, fees, realized, note):
        gross = (qty or 0.0) * (price or 0.0)
        fees = fees or 0.0
        return {
            "id": tx_id, "sens": kind, "date": str(tx_date),
            "position_id": pos.id, "position": pos.display_name, "ticker": pos.ticker,
            "type_actif": pos.asset_type, "poche": _poche(pos),
            "position_active": bool(pos.is_active),
            "quantite": qty, "prix_unitaire": price, "frais": fees,
            "montant_brut": gross,
            # Achat : ce qui est sorti de la poche ; vente : ce qui y est rentré
            "montant_net": gross + fees if kind == "achat" else gross - fees,
            "plus_value_realisee": realized,
            "note": note,
        }

    rows = []
    if sens in (None, "achat"):
        for p, pos in db.query(Purchase, Position).join(Position, Purchase.position_id == Position.id):
            rows.append(_row("achat", p.id, p.purchase_date, pos, p.quantity,
                             p.unit_price, p.fees, None, p.note))
    if sens in (None, "vente"):
        for s, pos in db.query(Sale, Position).join(Position, Sale.position_id == Position.id):
            rows.append(_row("vente", s.id, s.sale_date, pos, s.quantity,
                             s.unit_price, s.fees, s.realized_pnl, s.note))

    if not inclure_liquidites:
        rows = [r for r in rows
                if r["type_actif"] != "cash" and r["ticker"] not in CASH_TICKERS]
    if position_id is not None:
        rows = [r for r in rows if r["position_id"] == position_id]
    if ticker:
        rows = [r for r in rows if r["ticker"].upper() == ticker.upper()]
    if poche:
        rows = [r for r in rows if r["poche"] == poche]
    if date_debut:
        rows = [r for r in rows if r["date"] >= date_debut.isoformat()]
    if date_fin:
        rows = [r for r in rows if r["date"] <= date_fin.isoformat()]

    rows.sort(key=lambda r: (r["date"], r["sens"], r["id"]), reverse=True)
    start = (page - 1) * limit
    return {"total": len(rows), "page": page, "limit": limit,
            "items": rows[start:start + limit]}


@router.get("/positions-cloturees")
def mcp_closed_positions(db: Session = Depends(get_db), user: User = Depends(require_read_token)):
    """Positions archivées (titres et crypto) avec leur bilan réalisé."""
    from models import Position
    items = []
    for pos in db.query(Position).filter(Position.is_active == False).all():  # noqa: E712
        if not pos.purchases and not pos.sales:
            continue
        buy_dates = [p.purchase_date for p in pos.purchases]
        sell_dates = [s.sale_date for s in pos.sales]
        items.append({
            "position_id": pos.id, "position": pos.display_name, "ticker": pos.ticker,
            "type_actif": pos.asset_type, "poche": _poche(pos),
            "investi_brut": sum(p.quantity * p.unit_price + (p.fees or 0.0) for p in pos.purchases),
            "produit_ventes_net": sum(s.quantity * s.unit_price - (s.fees or 0.0) for s in pos.sales),
            "plus_value_realisee": sum(s.realized_pnl or 0.0 for s in pos.sales),
            "nb_achats": len(pos.purchases), "nb_ventes": len(pos.sales),
            "premier_achat": str(min(buy_dates)) if buy_dates else None,
            "derniere_vente": str(max(sell_dates)) if sell_dates else None,
        })
    items.sort(key=lambda i: i["derniere_vente"] or "", reverse=True)
    return {"total_plus_value_realisee": sum(i["plus_value_realisee"] for i in items),
            "positions": items}


@router.get("/journal")
def mcp_audit_log(action: Optional[str] = None, page: int = 1, limit: int = 100,
                  db: Session = Depends(get_db), user: User = Depends(require_read_token)):
    """Journal d'audit (qui a fait quoi, quand). Les événements liés au coffre à
    mots de passe et aux combinaisons de coffres en sont retirés."""
    from models import AuditLog
    page, limit = _page_args(page, limit, 500)
    q = db.query(AuditLog)
    for prefix in _HIDDEN_AUDIT_PREFIXES:
        q = q.filter(~AuditLog.action.startswith(prefix, autoescape=True))
    if action:
        q = q.filter(AuditLog.action == action.upper())
    total = q.count()
    logs = (q.order_by(AuditLog.created_at.desc())
             .offset((page - 1) * limit).limit(limit).all())
    return {"total": total, "page": page, "limit": limit, "items": [
        {"id": l.id, "date": l.created_at, "action": l.action,
         "description": l.description, "user_id": l.user_id, "ip": l.ip_address}
        for l in logs
    ]}


@router.get("/reserves")
def mcp_reserves(db: Session = Depends(get_db), user: User = Depends(require_read_token)):
    """Réserves de liquidation : constitué, libéré, encore libérable."""
    from routers.reserves import list_reserves
    return list_reserves(db=db, user=user)


@router.get("/historique")
def mcp_history(period: str = "month",
                db: Session = Depends(get_db), user: User = Depends(require_read_token)):
    """Historique de la valeur du portefeuille (day, week, month, ytd, year, max)."""
    from routers.portfolio import get_history
    return get_history(period=period, db=db, user=user)
