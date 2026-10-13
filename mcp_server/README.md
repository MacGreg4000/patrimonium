# Connecteur MCP Patrimonium — lecture seule

Permet d'interroger son patrimoine depuis Claude, sans ouvrir l'application.

## Ce que le connecteur peut et ne peut pas faire

Il ne peut **que lire**, et c'est garanti par construction, pas par convention :

- le jeton a une portée `read` et la dépendance qui le valide **refuse toute
  requête autre que GET** — même si une route mutante l'utilisait par erreur ;
- les outils exposés tapent uniquement sur `/api/mcp/*`, un routeur séparé qui
  ne contient aucune écriture ;
- le **coffre à mots de passe**, les fichiers chiffrés et les **combinaisons de
  coffres** ne sont exposés par aucun outil.

## Installation

1. Crée un jeton depuis **Admin → Connecteur MCP**. Il n'est affiché
   qu'une seule fois : seule son empreinte SHA-256 est conservée en base.

2. Installe les dépendances. Python **3.10 minimum** est requis par le paquet
   `mcp` (le `python3` fourni avec macOS est en 3.9 : utilise une version plus récente,
   par exemple celle de Homebrew) :

   ```bash
   /opt/homebrew/opt/python@3.12/bin/python3.12 -m venv .venv
   .venv/bin/pip install -r requirements.txt
   ```

3. Déclare le serveur auprès de Claude Code :

   ```bash
   claude mcp add patrimonium \
     --env PATRIMONIUM_URL=http://192.168.0.77:8080 \
     --env PATRIMONIUM_TOKEN=ptm_ro_xxxxx \
     -- /chemin/vers/mcp_server/.venv/bin/python /chemin/vers/mcp_server/patrimonium_mcp.py
   ```

## Outils disponibles

| Outil | Réponse |
|---|---|
| `patrimoine_total` | Total et répartition par poche |
| `portefeuille` | Positions titres, PRU, P&L |
| `crypto` | Positions crypto et liquidités des exchanges |
| `coffres` | Soldes des coffres (jamais les combinaisons) |
| `mouvements` | Entrées, sorties et transferts d'espèces |
| `actifs_physiques` | Immobilier, véhicules, bijoux… |
| `reserves` | Réserves de liquidation |
| `historique` | Évolution de la valeur du portefeuille |

## Révocation

Un jeton se révoque depuis **Admin → Connecteur MCP** : l'effet est immédiat,
le connecteur reçoit alors une erreur explicite.

## Sécurité du transport

Le jeton transite en clair si l'application est servie en HTTP. Sur un réseau
local de confiance c'est acceptable ; en dehors, passe l'application derrière
HTTPS avant d'exposer le connecteur.
