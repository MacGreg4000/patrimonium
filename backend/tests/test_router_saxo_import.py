"""Tests de l'import SaxoBank : lecture des ventes et déduplication.

Contexte : Saxo écrit les ventes avec une quantité NÉGATIVE (« Vente -800 @
17.09 EUR »). Le motif d'origine n'acceptait que des chiffres, si bien que
toutes les ventes du relevé étaient silencieusement ignorées.
"""
import datetime
from io import BytesIO

import openpyxl
import pytest

from models import Position, Purchase, Sale
from routers.saxo_import import _parse_event, _parse_sale_event

XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
ISIN = "IE00BMC38736"


def _row(day, op_id, event, amount, fees):
    """Une ligne au format du relevé Saxo (colonnes 0-indexées, 26 colonnes)."""
    row = [None] * 26
    row[1] = datetime.datetime.strptime(day, "%Y-%m-%d")
    row[4] = op_id
    row[9] = "Transaction"
    row[10] = event
    row[11] = amount
    row[15] = -fees
    row[21] = "iShares MSCI Global Semiconductors UCITS ETF"
    row[22] = "SEC0:xetr"
    row[23] = ISIN
    row[24] = "EUR"
    row[25] = "Etf"
    return row


def _xlsx(*rows):
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.append(["col"] * 26)          # en-tête ignoré par le parseur
    for r in rows:
        ws.append(r)
    buf = BytesIO()
    wb.save(buf)
    return buf.getvalue()


def _upload(client, *rows):
    return client.post("/api/saxo/import",
                       files={"file": ("releve.xlsx", _xlsx(*rows), XLSX)})


BUY = _row("2026-05-27", "100", "Achat 1000 @ 18.00 EUR", -18010.0, 10.0)
SELL = _row("2026-10-29", "200", "Vente -800 @ 17.00 EUR", 13595.0, 5.0)


# ── Lecture de l'événement ────────────────────────────────

def test_sale_with_negative_quantity_is_parsed():
    """Le cas réel du relevé : le signe moins ne doit pas faire échouer la lecture."""
    assert _parse_sale_event("Vente -800 @ 17.09 EUR") == (800.0, 17.09)


def test_sale_quantity_is_always_positive():
    assert _parse_sale_event("Vente -84 @ 8.52 EUR")[0] == 84.0
    assert _parse_sale_event("Vente 84 @ 8.52 EUR")[0] == 84.0     # forme sans signe


def test_purchase_is_not_mistaken_for_a_sale():
    assert _parse_sale_event("Achat 84 @ 8.68 EUR") is None
    assert _parse_event("Vente -84 @ 8.52 EUR") is None


# ── Import ────────────────────────────────────────────────

def test_partial_sale_is_recorded_and_position_stays_active(auth_admin, db):
    """Relevé trié du plus récent au plus ancien, comme Saxo l'exporte.

    Sans tri chronologique la vente serait traitée avant l'achat : PRU à zéro,
    P&L faux, et position archivée à tort alors qu'il reste 200 parts.
    """
    client, _ = auth_admin
    r = _upload(client, SELL, BUY)               # vente d'abord, comme dans le fichier
    assert r.status_code == 200, r.text
    assert r.json()["created_sales"] == 1

    pos = db.query(Position).filter(Position.isin == ISIN).one()
    assert pos.is_active is True                  # il reste 200 parts

    sale = db.query(Sale).filter(Sale.position_id == pos.id).one()
    assert sale.quantity == 800.0                 # positive, malgré le « -800 »
    # PRU = (1000×18 + 10) / 1000 = 18,01 → (17 − 18,01) × 800 − 5 = −813
    assert sale.realized_pnl == pytest.approx(-813.0)


def test_full_sale_archives_the_position(auth_admin, db):
    """Achat et vente soldant tout dans le même import (cas de la vente IUSN)."""
    client, _ = auth_admin
    full = _row("2026-10-29", "300", "Vente -1000 @ 17.00 EUR", 16995.0, 5.0)
    _upload(client, full, BUY)

    pos = db.query(Position).filter(Position.isin == ISIN).one()
    assert pos.is_active is False

    # Le P&L doit refléter le vrai PRU : si l'achat était invisible, le PRU vaudrait
    # zéro et l'intégralité du produit de la vente compterait comme du gain.
    # (17 − 18,01) × 1000 − 5 = −1015
    sale = db.query(Sale).filter(Sale.position_id == pos.id).one()
    assert sale.realized_pnl == pytest.approx(-1015.0)


def test_sale_import_is_idempotent(auth_admin, db):
    """Réimporter le même relevé ne doit pas doubler la vente."""
    client, _ = auth_admin
    _upload(client, SELL, BUY)
    again = _upload(client, SELL, BUY).json()

    assert again["created_sales"] == 0 and again["skipped_sales"] == 1
    assert db.query(Sale).count() == 1


def test_manually_entered_sale_is_not_duplicated(auth_admin, db):
    """Une vente saisie à la main (sans tag SAXO) ne doit pas être redoublée.

    C'est le cas de la vente IUSN de mai : l'import ne savait pas la lire, elle a
    donc été enregistrée à la main. Corriger le motif sans cette déduplication
    l'aurait créée une seconde fois au prochain import.
    """
    client, _ = auth_admin
    _upload(client, BUY)                          # achat seul, comme avant la correction
    pos = db.query(Position).filter(Position.isin == ISIN).one()
    db.add(Sale(position_id=pos.id, sale_date=datetime.date(2026, 10, 29),
                quantity=800.0, unit_price=17.0, fees=0.0,
                realized_pnl=-800.0, note=None))   # saisie manuelle : aucun tag
    db.commit()

    r = _upload(client, SELL, BUY).json()
    assert r["created_sales"] == 0 and r["skipped_sales"] == 1
    assert db.query(Sale).filter(Sale.position_id == pos.id).count() == 1


def test_identical_purchase_fills_with_different_ids_are_both_kept(auth_admin, db):
    """Deux exécutions identiques le même jour (IDs Saxo différents) sont légitimes.

    Verrouille la précaution prise autour du flush de la branche vente : un flush
    trop large rendrait la première exécution visible à la déduplication floue et
    ferait disparaître la seconde.
    """
    client, _ = auth_admin
    a = _row("2026-05-27", "501", "Achat 50 @ 18.00 EUR", -900.0, 1.0)
    b = _row("2026-05-27", "502", "Achat 50 @ 18.00 EUR", -900.0, 1.0)
    _upload(client, a, b, SELL)                   # une vente dans le fichier, en plus

    pos = db.query(Position).filter(Position.isin == ISIN).one()
    assert db.query(Purchase).filter(Purchase.position_id == pos.id).count() == 2


def test_two_distinct_sales_the_same_day_are_both_kept(auth_admin, db):
    """La déduplication floue ne doit pas écraser deux ventes réellement distinctes."""
    client, _ = auth_admin
    a = _row("2026-10-29", "401", "Vente -100 @ 17.00 EUR", 1695.0, 5.0)
    b = _row("2026-10-29", "402", "Vente -100 @ 17.50 EUR", 1745.0, 5.0)   # autre prix
    _upload(client, a, b, BUY)

    assert db.query(Sale).count() == 2
