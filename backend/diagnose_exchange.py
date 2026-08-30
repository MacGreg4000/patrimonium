"""Diagnostic : affiche ce que l'API d'un exchange renvoie réellement.

Usage (dans le conteneur) :
    python diagnose_exchange.py

Lit les clés déjà enregistrées (chiffrées) et affiche la réponse brute de
l'endpoint des soldes. Aucun secret n'est imprimé.
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import encryption                     # noqa: E402
from database import SessionLocal     # noqa: E402
from exchanges import get_client      # noqa: E402
from models import ExchangeAccount    # noqa: E402


def main():
    db = SessionLocal()
    try:
        accounts = db.query(ExchangeAccount).all()
        if not accounts:
            print("Aucun compte d'exchange enregistré.")
            return

        for acc in accounts:
            print(f"\n{'=' * 60}\n{acc.label}  ({acc.exchange})\n{'=' * 60}")
            client = get_client(
                acc.exchange,
                encryption.decrypt_str(acc.encrypted_api_key),
                encryption.decrypt_str(acc.encrypted_api_secret),
            )

            # 1. Réponse brute de l'endpoint des soldes
            try:
                if acc.exchange == "bitvavo":
                    raw = client._get("/balance")
                else:
                    raw = client._private("Balance")
                print("\n--- Réponse brute de l'endpoint soldes ---")
                print(json.dumps(raw, indent=2, ensure_ascii=False)[:3000])
            except Exception as e:
                print(f"\n!! Échec de l'appel soldes : {type(e).__name__}: {e}")
                print("   → la clé API n'a probablement pas le droit de lecture des fonds")
                continue

            # 2. Ce que Patrimonium en retient
            try:
                parsed = client.get_balances()
                print("\n--- Soldes retenus par Patrimonium ---")
                for sym, qty in sorted(parsed.items()):
                    print(f"   {sym:8} {qty}")
                print(f"\n   EUR présent ? {'OUI' if 'EUR' in parsed else 'NON'}")
                if "EUR" in parsed:
                    print(f"   Solde EUR    : {parsed['EUR']}")
            except Exception as e:
                print(f"!! Parsing échoué : {type(e).__name__}: {e}")
    finally:
        db.close()


if __name__ == "__main__":
    main()
