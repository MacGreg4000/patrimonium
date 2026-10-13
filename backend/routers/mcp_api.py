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
from typing import Optional

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from database import get_db
from dependencies import require_read_token
from models import User

router = APIRouter(prefix="/api/mcp", tags=["mcp"])


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
def mcp_movements(coffre_id: Optional[int] = None, limit: int = 50,
                  db: Session = Depends(get_db), user: User = Depends(require_read_token)):
    """Derniers mouvements d'espèces (entrées, sorties, transferts)."""
    from routers.coffres import list_movements
    return list_movements(coffre_id=coffre_id, page=1, limit=min(limit, 200),
                          db=db, user=user)


@router.get("/actifs")
def mcp_assets(db: Session = Depends(get_db), user: User = Depends(require_read_token)):
    """Actifs physiques non vendus : immobilier, véhicules, bijoux…"""
    from routers.physical_assets import list_assets
    return list_assets(db=db, user=user)


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
