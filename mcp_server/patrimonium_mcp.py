"""Serveur MCP Patrimonium — LECTURE SEULE.

Expose le patrimoine (portefeuille, crypto, coffres, actifs, réserves) à un
client MCP comme Claude. Le serveur ne fait que des GET sur l'API Patrimonium,
authentifiés par un jeton de portée "read" : il ne peut rien modifier, et le
coffre à mots de passe n'est atteignable par aucun de ses outils.

Configuration (variables d'environnement) :
    PATRIMONIUM_URL    ex. http://192.168.0.77:8080
    PATRIMONIUM_TOKEN  jeton créé depuis la page Admin (commence par ptm_ro_)

Lancement : python patrimonium_mcp.py
"""
import os
import sys

import httpx
from mcp.server.fastmcp import FastMCP

BASE_URL = os.getenv("PATRIMONIUM_URL", "").rstrip("/")
TOKEN = os.getenv("PATRIMONIUM_TOKEN", "")
TIMEOUT = 30.0

if not BASE_URL or not TOKEN:
    print("PATRIMONIUM_URL et PATRIMONIUM_TOKEN doivent être définis.", file=sys.stderr)
    sys.exit(1)

mcp = FastMCP("patrimonium")


def _get(path: str, **params) -> dict | list:
    """Appelle l'API en lecture. Seul GET est utilisé — le jeton refuse le reste."""
    r = httpx.get(
        f"{BASE_URL}/api/mcp{path}",
        headers={"Authorization": f"Bearer {TOKEN}"},
        params={k: v for k, v in params.items() if v is not None},
        timeout=TIMEOUT,
    )
    if r.status_code == 401:
        raise RuntimeError("Jeton refusé — il a peut-être été révoqué depuis la page Admin.")
    r.raise_for_status()
    return r.json()


@mcp.tool()
def patrimoine_total() -> dict:
    """Vue d'ensemble du patrimoine : total et répartition par poche.

    Donne le patrimoine total en euros et sa ventilation entre portefeuille
    titres, crypto, liquidités en coffre, actifs physiques et réserves.
    À utiliser pour toute question globale (« combien je vaux », « ma
    répartition », « part de la crypto dans mon patrimoine »).
    """
    return _get("/patrimoine")


@mcp.tool()
def portefeuille() -> dict:
    """Positions du portefeuille titres : actions, ETF, obligations, liquidités.

    Pour chaque position : quantité, prix de revient unitaire, cours actuel,
    montant investi, valeur, plus/moins-value en euros et en pourcentage.
    Ne contient pas la crypto, qui a son propre outil.
    """
    return _get("/portefeuille")


@mcp.tool()
def crypto() -> dict:
    """Positions crypto et liquidités disponibles sur les exchanges.

    Une ligne par couple actif/compte (le BTC de Kraken et celui de Bitvavo
    sont distincts, avec des PRU séparés). Inclut les euros non investis qui
    dorment sur chaque exchange.
    """
    return _get("/crypto")


@mcp.tool()
def coffres() -> dict:
    """Soldes des coffres-forts physiques.

    Renvoie le solde de chaque coffre et le total. Les combinaisons ne sont
    jamais accessibles par ce connecteur.
    """
    return _get("/coffres")


@mcp.tool()
def mouvements(coffre_id: int | None = None, limit: int = 50) -> dict:
    """Derniers mouvements d'espèces : entrées, sorties et transferts.

    Args:
        coffre_id: limite à un coffre précis ; tous les coffres si omis.
        limit: nombre de mouvements à renvoyer (200 au maximum).
    """
    return _get("/mouvements", coffre_id=coffre_id, limit=limit)


@mcp.tool()
def actifs_physiques() -> list:
    """Actifs physiques non vendus : immobilier, véhicules, bijoux, métaux…

    Pour chacun : catégorie, valeur estimée, emplacement et coffre de rattachement.
    """
    return _get("/actifs")


@mcp.tool()
def reserves() -> dict:
    """Réserves de liquidation de la société.

    Montant constitué par année, déjà libéré, précompte mobilier payé et
    solde encore libérable.
    """
    return _get("/reserves")


@mcp.tool()
def historique(periode: str = "month") -> list:
    """Évolution de la valeur du portefeuille dans le temps.

    Args:
        periode: day, week, month, ytd, year ou max.

    Chaque point donne la valeur, le capital investi et la plus/moins-value
    à cette date. Utile pour les questions de tendance ou de performance.
    """
    if periode not in {"day", "week", "month", "ytd", "year", "max"}:
        raise ValueError("periode doit valoir day, week, month, ytd, year ou max")
    return _get("/historique", period=periode)


if __name__ == "__main__":
    mcp.run()
