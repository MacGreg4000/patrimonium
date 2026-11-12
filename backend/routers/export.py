"""Export router: génère un fichier HTML autonome chiffré pour clé USB, et un export Excel."""
import base64 as b64_stdlib
import gzip
import json
import os
from datetime import date, datetime, timezone
from io import BytesIO

import openpyxl
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import Response
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter
from pydantic import BaseModel
from sqlalchemy.orm import Session

import encryption as enc
import market_data as md
from database import get_db
from dependencies import get_current_user, verify_csrf
from exchanges import CASH_TICKERS
from models import Coffre, Movement, PasswordFile, PhysicalAsset, Position, Reserve, Sale, User
from routers.coffres import compute_balance
from calculations import calc_position_metrics

router = APIRouter(prefix="/api/export", tags=["export"])

PBKDF2_ITERATIONS = 600_000


class ExportRequest(BaseModel):
    passphrase: str


# ── Encryption ────────────────────────────────────────────

def _derive_and_encrypt(data: bytes, passphrase: str) -> tuple[str, bytes]:
    """Dérive la clé et chiffre data. Retourne (blob_b64, raw_key_bytes)."""
    salt = os.urandom(32)
    kdf = PBKDF2HMAC(algorithm=hashes.SHA256(), length=32, salt=salt, iterations=PBKDF2_ITERATIONS)
    key = kdf.derive(passphrase.encode("utf-8"))
    nonce = os.urandom(12)
    ct = AESGCM(key).encrypt(nonce, data, None)
    return b64_stdlib.b64encode(salt + nonce + ct).decode(), key


def _encrypt_doc(data: bytes, key: bytes) -> str:
    """Chiffre un document avec une clé déjà dérivée. Retourne base64(nonce+ct)."""
    nonce = os.urandom(12)
    ct = AESGCM(key).encrypt(nonce, data, None)
    return b64_stdlib.b64encode(nonce + ct).decode()


# ── Data collection ───────────────────────────────────────

def _collect_data(db: Session, user: User) -> dict:
    # Portfolio — positions actives
    positions = db.query(Position).filter(Position.is_active == True).all()  # noqa: E712
    portfolio_items = []
    for pos in positions:
        if pos.ticker == "MANUAL" or pos.asset_type == "cash":
            price_eur = pos.manual_price or 0.0
            prev_eur = price_eur
        else:
            price_eur, prev_eur, _ = md.get_price_eur(pos.ticker, pos.currency)
            price_eur = price_eur or 0.0
            prev_eur = prev_eur or price_eur
        m = calc_position_metrics(pos, price_eur, prev_eur, 1.0)
        # Ignorer les positions sans achats (QTÉ nette = 0)
        if (m.get("total_quantity") or 0) <= 0 and (m.get("total_bought") or 0) == 0:
            continue
        portfolio_items.append({
            "name": pos.display_name,
            "ticker": pos.ticker,
            # Les liquidités d'exchange sont rattachées à la section Crypto
            "type": "crypto_cash" if pos.ticker in CASH_TICKERS else pos.asset_type,
            "currency": pos.currency,
            "current_price_eur": price_eur,
            "quantity": m.get("total_quantity"),
            "average_cost": m.get("average_cost"),
            "invested_eur": m.get("total_invested"),
            "value_eur": m.get("current_value"),
            "pnl_eur": m.get("pnl_eur"),
            "unrealized_pnl": m.get("unrealized_pnl"),
            "realized_pnl": m.get("realized_pnl"),
            "pnl_pct": m.get("pnl_pct"),
            "purchases": [
                {"date": str(p.purchase_date), "quantity": p.quantity,
                 "unit_price": p.unit_price, "fees": p.fees, "note": p.note}
                for p in pos.purchases
            ],
            "sales": [
                {"date": str(s.sale_date), "quantity": s.quantity,
                 "unit_price": s.unit_price, "fees": s.fees, "realized_pnl": s.realized_pnl}
                for s in pos.sales
            ],
        })

    # Positions archivées (clôturées)
    sold_positions = db.query(Position).filter(Position.is_active == False).all()  # noqa: E712
    sold_items = []
    for pos in sold_positions:
        if not pos.purchases:
            continue
        realized = sum(s.realized_pnl or 0.0 for s in pos.sales)
        total_invested_gross = sum(p.quantity * p.unit_price + p.fees for p in pos.purchases)
        last_sale = max((s.sale_date for s in pos.sales), default=None)
        sold_items.append({
            "name": pos.display_name,
            "ticker": pos.ticker,
            "type": pos.asset_type,
            "realized_pnl": realized,
            "total_invested": total_invested_gross,
            "last_sale_date": str(last_sale) if last_sale else "",
        })

    # Coffres
    coffres_data = []
    for c in db.query(Coffre).filter(Coffre.is_active == True).all():  # noqa: E712
        balance = compute_balance(c.id, db)
        combination = None
        if c.encrypted_combination:
            try:
                combination = enc.decrypt(c.encrypted_combination).decode("utf-8")
            except Exception:
                combination = None
        movements = (
            db.query(Movement)
            .filter(Movement.coffre_id == c.id, Movement.deleted_at == None)  # noqa: E711
            .order_by(Movement.created_at.desc())
            .limit(10)
            .all()
        )
        coffres_data.append({
            "id": c.id, "name": c.name, "balance": balance,
            "combination": combination,
            "combination_hint": c.combination_hint,
            "movements": [
                {"type": mv.type, "amount": mv.amount,
                 "description": mv.description, "date": str(mv.created_at)[:10]}
                for mv in movements
            ],
        })

    # Actifs physiques — filtré par user + non vendus uniquement
    assets_data = []
    for a in db.query(PhysicalAsset).filter(
        PhysicalAsset.user_id == user.id,
        PhysicalAsset.sold_at == None,  # noqa: E711
    ).all():
        assets_data.append({
            "name": a.name,
            "category": a.category,
            "description": a.description,
            "estimated_value": a.estimated_value,
            "location": getattr(a, "location", None),
            "coffre_id": a.coffre_id,
            "vehicle_make": a.vehicle_make,
            "vehicle_model": a.vehicle_model,
            "vehicle_year": a.vehicle_year,
            "vehicle_plate": a.vehicle_plate,
            "vehicle_vin": a.vehicle_vin,
            "vehicle_fuel": a.vehicle_fuel,
            "vehicle_km": a.vehicle_km,
            "events": [
                {"type": e.type, "date": str(e.date), "amount": e.amount, "notes": e.notes}
                for e in a.events
            ],
            "documents": [
                {"filename": d.filename, "document_type": d.document_type,
                 "notes": d.notes, "size_bytes": d.size_bytes, "mime_type": d.mime_type,
                 "created_at": str(d.created_at), "doc_key": f"d{d.id}"}
                for d in a.documents
            ],
        })

    # Coffre de fichiers (vault)
    vault_data = []
    for f in db.query(PasswordFile).filter(PasswordFile.user_id == user.id).all():
        vault_data.append({
            "filename": f.filename, "mime_type": f.mime_type,
            "size_bytes": f.size_bytes, "created_at": str(f.created_at),
            "doc_key": f"v{f.id}",
        })

    # Réserves
    reserves_data = []
    for r in db.query(Reserve).filter(Reserve.user_id == user.id).all():
        precompte = r.precompte_paye or 0.0
        released  = r.released or 0.0
        reserves_data.append({
            "year": r.year, "month": r.month, "amount": r.amount,
            "release_year": r.release_year, "released": released,
            "precompte_paye": precompte, "net_recu": released - precompte,
            "releasable": max(0.0, r.amount - released), "notes": r.notes,
        })

    # Totaux (cash SaxoBank et crypto séparés du portefeuille boursier)
    total_portfolio      = sum(p["value_eur"] or 0 for p in portfolio_items
                               if p["type"] not in ("cash", "crypto", "crypto_cash"))
    total_saxo_cash      = sum(p["value_eur"] or 0 for p in portfolio_items if p["type"] == "cash")
    total_crypto         = sum(p["value_eur"] or 0 for p in portfolio_items
                               if p["type"] in ("crypto", "crypto_cash"))
    total_cash           = sum(c["balance"] for c in coffres_data)
    total_assets         = sum((a["estimated_value"] or 0) for a in assets_data)
    total_releasable_res = sum(r["releasable"] for r in reserves_data)
    total_released_res   = sum(r["released"] for r in reserves_data)
    total_precompte_res  = sum(r["precompte_paye"] for r in reserves_data)
    total_amount_res     = sum(r["amount"] for r in reserves_data)

    return {
        "meta": {
            "exported_at": datetime.now(timezone.utc).isoformat(),
            "owner_name": user.name,
            "owner_email": user.email,
        },
        "summary": {
            "total_portfolio_eur":  total_portfolio,
            "total_saxo_cash_eur":  total_saxo_cash,
            "total_crypto_eur":     total_crypto,
            "total_cash_eur":       total_cash,
            "total_assets_eur":     total_assets,
            "total_reserves_eur":   total_releasable_res,
            "grand_total_eur":      (total_portfolio + total_saxo_cash + total_crypto
                                     + total_cash + total_assets + total_releasable_res),
            "reserves_stats": {
                "total_amount":     total_amount_res,
                "total_releasable": total_releasable_res,
                "total_released":   total_released_res,
                "total_precompte":  total_precompte_res,
                "total_net_recu":   total_released_res - total_precompte_res,
            },
        },
        "portfolio": portfolio_items,
        "sold_positions": sold_items,
        "coffres": coffres_data,
        "assets": assets_data,
        "vault": vault_data,
        "reserves": reserves_data,
    }


# ── HTML template ─────────────────────────────────────────
# Utilise des marqueurs __XXXX__ pour éviter l'enfer des {{ }} dans les f-strings.

_HTML_TEMPLATE = r'''<!DOCTYPE html>
<html lang="fr">
<head>
<meta charset="UTF-8"/>
<meta name="viewport" content="width=device-width,initial-scale=1"/>
<meta name="color-scheme" content="light"/>
<title>Relevé de patrimoine</title>
<style>
*{box-sizing:border-box;margin:0;padding:0}
:root{
  --bg:#F4F5F7;--sf:#FFFFFF;--sf2:#F6F7F9;--ln:#E3E6EB;--ln2:#EEF0F3;
  --tx:#0E1726;--tx2:#4A5568;--tx3:#667085;
  --ac:#1D3B6F;--acInk:#FFFFFF;--acSoft:#EEF2F9;
  --gain:#0F7B4E;--gainBg:#E7F5EE;--loss:#B42318;--lossBg:#FDECEA;--warn:#B54708;--warnBg:#FEF4E6;
  --p-titres:#2F6FDE;--p-crypto:#D9622B;--p-coffres:#0F8A66;--p-biens:#6D5BD0;--p-reserves:#C08A2B;--p-cash:#0E7490;
  --sh:0 1px 2px rgba(16,24,40,.05),0 4px 16px rgba(16,24,40,.05);
  --font:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,'Helvetica Neue',Arial,sans-serif;
}
html{-webkit-text-size-adjust:100%;color-scheme:light}
body{background:var(--bg);color:var(--tx);font-family:var(--font);font-size:15px;line-height:1.55;font-feature-settings:'tnum' 1;min-height:100vh}
button{font-family:inherit}
a{color:var(--ac)}
.hidden{display:none !important}
.muted{color:var(--tx3)}
.pos{color:var(--gain)}.neg{color:var(--loss)}

/* ── Écran d'ouverture ── */
#lockScreen{min-height:100vh;display:flex;align-items:center;justify-content:center;padding:24px 16px}
.lock{background:var(--sf);border-radius:20px;box-shadow:var(--sh);padding:36px 32px;width:100%;max-width:460px}
.lock-logo{width:52px;height:52px;border-radius:14px;background:var(--ac);color:var(--acInk);display:flex;align-items:center;justify-content:center;margin-bottom:20px}
.lock h1{font-size:26px;letter-spacing:-.02em;line-height:1.2}
.lock .date{color:var(--tx3);margin-top:4px;font-size:14px}
.lock p.intro{margin:18px 0 22px;color:var(--tx2)}
label.lbl{display:block;font-size:14px;font-weight:600;margin-bottom:6px}
.pw-wrap{display:flex;gap:8px}
.input{flex:1;min-width:0;height:52px;border-radius:12px;border:1px solid var(--ln);background:var(--sf2);color:var(--tx);padding:0 14px;font-size:17px;font-family:inherit}
.input:focus{outline:2px solid var(--ac);outline-offset:1px;border-color:transparent}
.btn{display:inline-flex;align-items:center;justify-content:center;gap:8px;min-height:44px;padding:0 16px;border-radius:12px;border:1px solid var(--ln);background:var(--sf);color:var(--tx);font-size:15px;font-weight:600;cursor:pointer;text-decoration:none}
.btn:hover{border-color:var(--ac)}
.btn:disabled{opacity:.6;cursor:wait}
.btn-primary{background:var(--ac);border-color:var(--ac);color:var(--acInk)}
.btn-wide{width:100%;min-height:52px;font-size:17px;margin-top:14px}
.hint{font-size:13px;color:var(--tx3);margin-top:8px}
.msg{margin-top:14px;padding:12px 14px;border-radius:12px;font-size:14px}
.msg.err{background:var(--lossBg);color:var(--loss)}
.msg.info{background:var(--acSoft);color:var(--tx2)}
.faq{margin-top:24px;border-top:1px solid var(--ln2);padding-top:8px}
details.q{border-bottom:1px solid var(--ln2)}
details.q summary{cursor:pointer;padding:12px 0;font-weight:600;font-size:14px;list-style:none;display:flex;justify-content:space-between;gap:12px}
details.q summary::after{content:'+';color:var(--tx3);font-weight:400;font-size:18px;line-height:1}
details.q[open] summary::after{content:'−'}
details.q summary::-webkit-details-marker{display:none}
details.q div{padding:0 0 14px;color:var(--tx2);font-size:14px}

/* ── Relevé ── */
#app{min-height:100vh}
.top{background:var(--sf);border-bottom:1px solid var(--ln);position:sticky;top:0;z-index:10}
.top-in{max-width:1080px;margin:0 auto;padding:14px 20px;display:flex;align-items:center;gap:12px;flex-wrap:wrap}
.top-title{flex:1;min-width:200px}
.top-title strong{display:block;font-size:17px}
.top-title span{font-size:13px;color:var(--tx3)}
.top-actions{display:flex;gap:8px}
nav.chips{max-width:1080px;margin:0 auto;padding:0 20px 12px;display:flex;gap:6px;overflow-x:auto;scrollbar-width:none}
nav.chips::-webkit-scrollbar{display:none}
.chip{flex:0 0 auto;min-height:40px;padding:0 14px;border-radius:999px;border:1px solid var(--ln);background:var(--sf);color:var(--tx2);font-size:14px;font-weight:600;cursor:pointer}
.chip.active{background:var(--ac);border-color:var(--ac);color:var(--acInk)}
main{max-width:1080px;margin:0 auto;padding:24px 20px 64px}
section.page{display:none}
section.page.active{display:block}
h2.ttl{font-size:26px;letter-spacing:-.02em;line-height:1.25}
p.lead{color:var(--tx2);margin:6px 0 20px;max-width:720px}
.card{background:var(--sf);border-radius:16px;box-shadow:var(--sh);padding:20px;margin-bottom:14px}
.card h3{font-size:16px;margin-bottom:10px}
.note{background:var(--warnBg);color:var(--tx2);border-radius:12px;padding:12px 14px;font-size:14px;margin-bottom:18px}
.note b{color:var(--warn)}
.note.blue{background:var(--acSoft)}
.note.blue b{color:var(--tx)}

.hero{display:flex;flex-wrap:wrap;gap:20px;align-items:center}
.hero-total{flex:1 1 260px}
.hero-total .lbl2{font-size:14px;color:var(--tx2)}
.hero-total .big{font-size:38px;font-weight:700;letter-spacing:-.02em;line-height:1.15;margin-top:4px}
.bar{display:flex;height:14px;border-radius:7px;overflow:hidden;gap:2px;margin-top:16px}
.bar span{min-width:4px}

.grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(250px,1fr));gap:14px}
.cat{display:flex;flex-direction:column;gap:6px;text-align:left;background:var(--sf);border:2px solid transparent;border-radius:16px;box-shadow:var(--sh);padding:18px;cursor:pointer;color:inherit;font:inherit}
.cat:hover{border-color:var(--ac)}
.cat .name{display:flex;align-items:center;gap:8px;font-weight:700}
.dot{width:10px;height:10px;border-radius:3px;flex-shrink:0}
.cat .val{font-size:24px;font-weight:700}
.cat .what{font-size:13px;color:var(--tx3)}
.cat .go{font-size:14px;font-weight:600;color:var(--ac);margin-top:auto}

ol.steps{list-style:none;counter-reset:s;display:grid;gap:12px}
ol.steps li{counter-increment:s;display:flex;gap:12px;color:var(--tx2)}
ol.steps li::before{content:counter(s);flex-shrink:0;width:28px;height:28px;border-radius:50%;background:var(--acSoft);color:var(--ac);font-weight:700;display:flex;align-items:center;justify-content:center;font-size:14px}
ol.steps b{color:var(--tx)}

.kpis{display:grid;grid-template-columns:repeat(auto-fit,minmax(180px,1fr));gap:12px;margin-bottom:18px}
.kpi{background:var(--sf);border-radius:14px;box-shadow:var(--sh);padding:14px 16px}
.kpi .k{font-size:13px;color:var(--tx2)}
.kpi .v{font-size:22px;font-weight:700;margin-top:4px}
.kpi .s{font-size:12px;color:var(--tx3);margin-top:2px}

.item{background:var(--sf);border-radius:16px;box-shadow:var(--sh);margin-bottom:12px;overflow:hidden}
.item-head{display:flex;align-items:flex-start;gap:14px;padding:16px 18px}
.badge{width:42px;height:42px;border-radius:12px;flex-shrink:0;display:flex;align-items:center;justify-content:center;font-size:11px;font-weight:700;background:var(--acSoft);color:var(--ac)}
.item-main{flex:1;min-width:0}
.item-name{font-weight:700;font-size:16px}
.item-sub{font-size:13px;color:var(--tx3);margin-top:2px}
.item-val{text-align:right;flex-shrink:0}
.item-val .v{font-size:18px;font-weight:700;white-space:nowrap}
.pill{display:inline-block;padding:2px 9px;border-radius:999px;font-size:12px;font-weight:700;margin-top:4px;white-space:nowrap}
.pill.pos{background:var(--gainBg)}.pill.neg{background:var(--lossBg)}
.pill.muted{background:var(--sf2);color:var(--tx2)}
.facts{display:grid;grid-template-columns:repeat(auto-fill,minmax(150px,1fr));gap:10px;padding:0 18px 16px}
.fact{background:var(--sf2);border-radius:10px;padding:8px 12px}
.fact .k{font-size:12px;color:var(--tx3)}
.fact .v{font-size:14px;font-weight:600;word-break:break-word}
details.more{border-top:1px solid var(--ln2)}
details.more>summary{cursor:pointer;padding:12px 18px;font-size:14px;font-weight:600;color:var(--ac);list-style:none}
details.more>summary::-webkit-details-marker{display:none}
details.more>summary::before{content:'▸ '}
details.more[open]>summary::before{content:'▾ '}
details.more .in{padding:0 18px 16px}
.tbl-wrap{overflow-x:auto}
table{width:100%;border-collapse:collapse;font-size:14px}
th{text-align:left;font-size:12px;color:var(--tx3);font-weight:600;padding:8px 10px;border-bottom:1px solid var(--ln);white-space:nowrap}
td{padding:9px 10px;border-bottom:1px solid var(--ln2);white-space:nowrap}
td.r,th.r{text-align:right}
td.wrap{white-space:normal}
.docs{display:grid;gap:8px}
.doc{display:flex;align-items:center;gap:12px;background:var(--sf2);border-radius:12px;padding:10px 12px}
.doc .ext{width:38px;height:38px;border-radius:10px;background:var(--sf);display:flex;align-items:center;justify-content:center;font-size:10px;font-weight:700;color:var(--tx2);flex-shrink:0}
.doc .info{flex:1;min-width:0}
.doc .fn{font-weight:600;font-size:14px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.doc .meta{font-size:12px;color:var(--tx3)}
.code{font-family:ui-monospace,Menlo,Consolas,monospace;font-size:22px;letter-spacing:.25em;font-weight:700}
.group-title{font-size:13px;font-weight:700;color:var(--tx3);text-transform:uppercase;letter-spacing:.06em;margin:22px 0 10px}
dl.lex{display:grid;gap:2px}
dl.lex dt{font-weight:700;margin-top:12px}
dl.lex dd{color:var(--tx2)}
footer{max-width:1080px;margin:0 auto;padding:0 20px 40px;color:var(--tx3);font-size:13px}

@media (max-width:600px){
  .lock{padding:28px 20px}
  .top-actions .lbl-long{display:none}
  .top-in{padding:10px 16px;gap:8px;flex-wrap:nowrap}
  .top-title{min-width:0}
  .top-title strong{font-size:15px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
  .top-title span{font-size:12px}
  .top-actions .btn{min-height:40px;padding:0 12px;font-size:14px}
  nav.chips{padding:0 16px 10px}
  main{padding:18px 16px 56px}
  .kpis{grid-template-columns:repeat(2,minmax(0,1fr))}
  .kpi .v{font-size:18px}
  .hero-total .big{font-size:30px}
  h2.ttl{font-size:22px}
  .item-head{flex-wrap:wrap}
  .item-val{text-align:left;width:100%;padding-left:56px}
}
@media print{
  body{background:#fff;color:#000;font-size:12px}
  .top,nav.chips,.no-print,details.more>summary::before{display:none !important}
  section.page{display:block !important;page-break-before:always}
  section.page:first-child{page-break-before:auto}
  details.more{border:none}
  details.more>.in{display:block !important}
  .card,.item,.kpi,.cat{box-shadow:none;border:1px solid #ccc}
  main{padding:0}
}
</style>
</head>
<body>

<!-- ══ Écran d'ouverture ══ -->
<div id="lockScreen">
  <div class="lock">
    <div class="lock-logo" aria-hidden="true">
      <svg width="26" height="26" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"><rect x="4" y="10" width="16" height="11" rx="2"/><path d="M8 10V7a4 4 0 0 1 8 0v3"/></svg>
    </div>
    <h1>Relevé de patrimoine</h1>
    <div class="date">Établi le <span id="exportDateDisplay"></span></div>
    <p class="intro">Ce fichier rassemble, à la date indiquée, l’ensemble du patrimoine : placements, comptes, coffres, biens, documents importants.
      Il est protégé par une <b>phrase secrète</b> choisie par la personne qui l’a créé.</p>

    <div id="browserWarn" class="msg err hidden">Ce navigateur ne peut pas ouvrir ce fichier. Ouvrez-le avec une version récente de Chrome, Edge, Firefox ou Safari (sur ordinateur, tablette ou téléphone).</div>

    <form id="unlockForm" autocomplete="off">
      <label class="lbl" for="passInput">Phrase secrète</label>
      <div class="pw-wrap">
        <input type="password" class="input" id="passInput" autocomplete="current-password" autocapitalize="off" autocorrect="off" spellcheck="false" aria-describedby="passHint"/>
        <button type="button" class="btn" id="togglePass" aria-label="Afficher la phrase secrète" aria-pressed="false">Afficher</button>
      </div>
      <div class="hint" id="passHint">Respectez les majuscules, les accents et les espaces.</div>
      <button type="submit" class="btn btn-primary btn-wide" id="unlockBtn">Ouvrir le relevé</button>
      <div id="errMsg" class="msg hidden" role="alert"></div>
    </form>

    <div class="faq">
      <details class="q"><summary>Où trouver la phrase secrète ?</summary>
        <div>Elle a été choisie au moment de la création de ce fichier et doit être conservée à part (sur papier, chez un notaire, dans un coffre…).
        Sans elle, le contenu ne peut pas être lu : c’est volontaire, pour protéger ces informations si la clé USB est perdue.</div></details>
      <details class="q"><summary>Mes informations sont-elles envoyées sur Internet ?</summary>
        <div>Non. Tout se passe sur cet appareil : le fichier fonctionne même sans connexion. Rien n’est envoyé nulle part.</div></details>
      <details class="q"><summary>Le fichier ne s’ouvre pas</summary>
        <div>Vérifiez la phrase secrète (majuscules, touche « Verr. Maj. », espaces en trop). Si le message persiste, essayez un autre navigateur récent
        ou un ordinateur. Copiez de préférence le fichier depuis la clé USB vers l’ordinateur avant de l’ouvrir.</div></details>
    </div>
  </div>
</div>

<!-- ══ Relevé ══ -->
<div id="app" class="hidden">
  <div class="top">
    <div class="top-in">
      <div class="top-title"><strong id="hdrTitle">Relevé de patrimoine</strong><span id="hdrDate"></span></div>
      <div class="top-actions no-print">
        <button class="btn" onclick="window.print()" title="Imprimer ou enregistrer en PDF">Imprimer<span class="lbl-long">&nbsp;/ PDF</span></button>
        <button class="btn" onclick="location.reload()" title="Refermer le relevé">Fermer</button>
      </div>
    </div>
    <nav class="chips" id="nav" aria-label="Sections du relevé"></nav>
  </div>
  <main id="pages"></main>
  <footer id="footerInfo"></footer>
</div>

<script>
// Déclarations globales — les valeurs sont injectées dans le 2e bloc <script>
var BLOB, DOC_BLOBS, ITERATIONS;
var _cryptoKey = null;
var _docs = [];      // registre des documents téléchargeables (évite de mettre noms et clés dans les attributs)
var _codes = [];     // registre des codes de coffre

function b64ToBytes(b64) {
  var bin = atob(b64);
  var bytes = new Uint8Array(bin.length);
  for (var i = 0; i < bin.length; i++) bytes[i] = bin.charCodeAt(i);
  return bytes;
}

// ── Ouverture (déchiffrement inchangé : PBKDF2-SHA256 → AES-256-GCM → gzip) ──
async function unlock() {
  var pass = document.getElementById('passInput').value;
  var btn = document.getElementById('unlockBtn');
  if (!pass) { showMsg('err', 'Saisissez la phrase secrète.'); return; }
  btn.disabled = true; btn.textContent = 'Ouverture en cours…';
  showMsg('info', 'Vérification de la phrase secrète, cela peut prendre quelques secondes.');
  try {
    var blob = b64ToBytes(BLOB);
    var salt = blob.slice(0, 32);
    var nonce = blob.slice(32, 44);
    var ct = blob.slice(44);
    var keyMat = await crypto.subtle.importKey('raw', new TextEncoder().encode(pass), 'PBKDF2', false, ['deriveKey']);
    var key = await crypto.subtle.deriveKey(
      { name: 'PBKDF2', salt: salt, iterations: ITERATIONS, hash: 'SHA-256' },
      keyMat, { name: 'AES-GCM', length: 256 }, false, ['decrypt']
    );
    var plain = await crypto.subtle.decrypt({name:'AES-GCM', iv:nonce}, key, ct);
    var ds = new DecompressionStream('gzip');
    var writer = ds.writable.getWriter();
    writer.write(new Uint8Array(plain));
    writer.close();
    var decompressed = await new Response(ds.readable).arrayBuffer();
    var data = JSON.parse(new TextDecoder().decode(decompressed));
    _cryptoKey = key;
    document.getElementById('passInput').value = '';
    document.getElementById('lockScreen').classList.add('hidden');
    document.getElementById('app').classList.remove('hidden');
    renderAll(data);
    window.scrollTo(0, 0);
  } catch (e) {
    showMsg('err', 'Cette phrase secrète ne permet pas d’ouvrir le relevé. Vérifiez les majuscules, les accents et les espaces, puis réessayez.');
    btn.disabled = false; btn.textContent = 'Ouvrir le relevé';
    document.getElementById('passInput').focus();
  }
}

function showMsg(kind, text) {
  var el = document.getElementById('errMsg');
  el.className = 'msg ' + kind;
  el.textContent = text;
}

async function downloadDoc(btn, idx) {
  var d = _docs[idx];
  if (!_cryptoKey || !d) return;
  var label = btn.textContent;
  btn.disabled = true; btn.textContent = 'Préparation…';
  try {
    var raw = b64ToBytes(DOC_BLOBS[d.key]);
    var plain = await crypto.subtle.decrypt({name:'AES-GCM', iv:raw.slice(0, 12)}, _cryptoKey, raw.slice(12));
    var url = URL.createObjectURL(new Blob([plain], {type: d.mime || 'application/octet-stream'}));
    var a = document.createElement('a');
    a.href = url; a.download = d.name;
    document.body.appendChild(a); a.click(); document.body.removeChild(a);
    setTimeout(function(){ URL.revokeObjectURL(url); }, 2000);
    btn.textContent = 'Téléchargé ✓';
    setTimeout(function(){ btn.disabled = false; btn.textContent = label; }, 2500);
  } catch (e) {
    btn.disabled = false; btn.textContent = label;
    alert('Ce document n’a pas pu être ouvert.');
  }
}

function toggleCode(btn, idx) {
  var el = document.getElementById('code-' + idx);
  var shown = el.dataset.shown === '1';
  el.textContent = shown ? '••••••' : _codes[idx];
  el.dataset.shown = shown ? '0' : '1';
  btn.textContent = shown ? 'Afficher le code' : 'Masquer le code';
}

// ── Mise en forme ──
function eur(v, d) {
  if (v == null) return '—';
  d = (d == null) ? 2 : d;
  return new Intl.NumberFormat('fr-BE', {style:'currency', currency:'EUR', minimumFractionDigits:d, maximumFractionDigits:d}).format(v);
}
function eur0(v) { return eur(v, 0); }
function num(v, d) { if (v == null) return '—'; return new Intl.NumberFormat('fr-BE', {maximumFractionDigits: d == null ? 0 : d}).format(v); }
function pct(v) { return v == null ? '—' : (v >= 0 ? '+' : '−') + Math.abs(v).toFixed(1).replace('.', ',') + ' %'; }
function signed(v) { return v == null ? '—' : (v >= 0 ? '+' : '−') + eur(Math.abs(v)); }
function cls(v) { return v == null ? '' : v >= 0 ? 'pos' : 'neg'; }
function esc(s) {
  if (s == null) return '';
  return String(s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;').replace(/'/g,'&#39;');
}
function fmtDate(iso, long) {
  if (!iso) return '—';
  var d = new Date(String(iso).indexOf('T') > -1 ? iso : iso + 'T00:00:00');
  if (isNaN(d)) return esc(iso);
  return d.toLocaleDateString('fr-BE', long ? {day:'numeric', month:'long', year:'numeric'} : {day:'2-digit', month:'2-digit', year:'numeric'});
}
function fmtSize(b) { if (!b) return '—'; if (b >= 1048576) return (b/1048576).toFixed(1).replace('.', ',') + ' Mo'; if (b >= 1024) return Math.round(b/1024) + ' Ko'; return b + ' octets'; }
function ext(name) { var p = String(name || '').split('.'); return p.length > 1 ? p.pop().toUpperCase().slice(0, 4) : 'FICH'; }
function fact(k, v) { return v == null || v === '' ? '' : '<div class="fact"><div class="k">' + k + '</div><div class="v">' + v + '</div></div>'; }

function docButton(d) {
  var idx = _docs.push({key: d.doc_key, name: d.filename, mime: d.mime_type}) - 1;
  return '<div class="doc"><span class="ext">' + esc(ext(d.filename)) + '</span>'
    + '<div class="info"><div class="fn">' + esc(d.filename) + '</div>'
    + '<div class="meta">' + [DOC_LABELS[d.document_type] || '', fmtSize(d.size_bytes), d.created_at ? 'ajouté le ' + fmtDate(d.created_at) : ''].filter(Boolean).join(' · ')
    + (d.notes ? '<br/>' + esc(d.notes) : '') + '</div></div>'
    + '<button class="btn no-print" onclick="downloadDoc(this,' + idx + ')">Télécharger</button></div>';
}

var CAT_LABELS = {immo:'Immobilier', vehicule:'Véhicules', bijou:'Bijoux et montres', metal:'Métaux précieux', art:'Œuvres d’art', autre:'Autres biens'};
var TYPE_LABELS = {action:'Action', etf:'Fonds indiciel (ETF)', commodity:'Matière première', bond_manual:'Obligation', crypto:'Cryptomonnaie', cash:'Liquidités', crypto_cash:'Liquidités'};
var DOC_LABELS = {facture:'Facture', carte_grise:'Certificat d’immatriculation', assurance:'Assurance', controle_technique:'Contrôle technique', certificat:'Certificat', photo:'Photo', acte_notarie:'Acte notarié', compromis:'Compromis', autre:'Document'};
var EVENT_LABELS = {VALUATION:'Réévaluation', PURCHASE:'Achat', MAINTENANCE:'Entretien', REPAIR:'Réparation'};

// ── Structure du relevé ──
var SECTIONS = [];
function addSection(id, label, html) { SECTIONS.push({id: id, label: label, html: html}); }

function showSection(id) {
  document.querySelectorAll('section.page').forEach(function(s){ s.classList.toggle('active', s.id === 'sec-' + id); });
  document.querySelectorAll('.chip').forEach(function(c){ c.classList.toggle('active', c.dataset.id === id); });
  window.scrollTo(0, 0);
}

function renderAll(data) {
  var meta = data.meta || {};
  var at = fmtDate(meta.exported_at, true);
  document.getElementById('hdrTitle').textContent = 'Relevé de patrimoine' + (meta.owner_name ? ' de ' + meta.owner_name : '');
  document.getElementById('hdrDate').textContent = 'Situation au ' + at;
  document.getElementById('footerInfo').textContent = 'Relevé établi le ' + at + (meta.owner_name ? ' par ' + meta.owner_name : '')
    + (meta.owner_email ? ' (' + meta.owner_email + ')' : '') + ' avec l’application Patrimonium.';

  var port = (data.portfolio || []);
  var titres = port.filter(function(p){ return p.type !== 'crypto' && p.type !== 'crypto_cash'; });
  var crypto = port.filter(function(p){ return p.type === 'crypto' || p.type === 'crypto_cash'; });

  addSection('home', 'Accueil', renderHome(data, at));
  if (titres.length || (data.sold_positions || []).some(function(p){ return p.type !== 'crypto'; }))
    addSection('titres', 'Placements en bourse', renderPositions(titres, (data.sold_positions || []).filter(function(p){ return p.type !== 'crypto'; }), 'titres', at));
  if (crypto.length) addSection('crypto', 'Cryptomonnaies', renderPositions(crypto, (data.sold_positions || []).filter(function(p){ return p.type === 'crypto'; }), 'crypto', at));
  if ((data.coffres || []).length) addSection('coffres', 'Coffres', renderCoffres(data));
  if ((data.assets || []).length) addSection('biens', 'Biens', renderAssets(data));
  if ((data.reserves || []).length) addSection('reserves', 'Réserves', renderReserves(data));
  if ((data.vault || []).length) addSection('fichiers', 'Fichiers protégés', renderVault(data));
  addSection('lexique', 'Lexique', renderLexique());

  document.getElementById('nav').innerHTML = SECTIONS.map(function(s){
    return '<button class="chip" data-id="' + s.id + '" onclick="showSection(\'' + s.id + '\')">' + s.label + '</button>';
  }).join('');
  document.getElementById('pages').innerHTML = SECTIONS.map(function(s){
    return '<section class="page" id="sec-' + s.id + '">' + s.html + '</section>';
  }).join('');
  showSection('home');
}

// ── Accueil ──
function renderHome(data, at) {
  var s = data.summary || {};
  var cats = [
    {id:'titres',   label:'Placements en bourse', color:'var(--p-titres)',   value:(s.total_portfolio_eur || 0),
      what:'Parts de fonds et actions détenues sur un compte-titres.'},
    {id:'titres',   label:'Argent sur le compte-titres', color:'var(--p-cash)', value:(s.total_saxo_cash_eur || 0),
      what:'Liquidités non placées, disponibles sur le compte de courtage.'},
    {id:'crypto',   label:'Cryptomonnaies', color:'var(--p-crypto)', value:(s.total_crypto_eur || 0),
      what:'Bitcoin et autres, détenus sur des plateformes en ligne.'},
    {id:'coffres',  label:'Argent liquide en coffre', color:'var(--p-coffres)', value:(s.total_cash_eur || 0),
      what:'Billets rangés dans des coffres, avec leur code d’accès.'},
    {id:'biens',    label:'Biens', color:'var(--p-biens)', value:(s.total_assets_eur || 0),
      what:'Immobilier, véhicules, bijoux, métaux précieux (valeurs estimées).'},
    {id:'reserves', label:'Réserves de la société', color:'var(--p-reserves)', value:(s.total_reserves_eur || 0),
      what:'Montants mis de côté dans la société, versables plus tard.'},
  ].filter(function(c){ return c.value > 0; });
  var total = s.grand_total_eur || 0;
  var bar = cats.map(function(c){ return '<span style="flex:' + c.value + ' 0 0;background:' + c.color + '" title="' + esc(c.label) + '"></span>'; }).join('');
  var tiles = cats.map(function(c){
    return '<button class="cat" onclick="showSection(\'' + c.id + '\')">'
      + '<span class="name"><span class="dot" style="background:' + c.color + '"></span>' + c.label + '</span>'
      + '<span class="val">' + eur0(c.value) + '</span>'
      + '<span class="what">' + c.what + (total > 0 ? ' · ' + (c.value / total * 100).toFixed(1).replace('.', ',') + ' % du total' : '') + '</span>'
      + '<span class="go no-print">Voir le détail →</span></button>';
  }).join('');
  var hasDocs = (data.vault || []).length || (data.assets || []).some(function(a){ return (a.documents || []).length; });
  var hasCodes = (data.coffres || []).some(function(c){ return c.combination || c.combination_hint; });

  return '<h2 class="ttl">Vue d’ensemble</h2>'
    + '<p class="lead">Voici la situation du patrimoine au <b>' + at + '</b>. Touchez une catégorie pour en voir le détail ; '
    + 'le <a href="#" onclick="showSection(\'lexique\');return false">lexique</a> explique les termes techniques.</p>'
    + '<div class="note"><b>À savoir :</b> les montants sont ceux du ' + at + '. Les placements en bourse et les cryptomonnaies changent de valeur chaque jour ; '
    + 'les biens sont des estimations. Pour connaître la valeur actuelle, il faut consulter les comptes concernés.</div>'
    + '<div class="card"><div class="hero"><div class="hero-total"><div class="lbl2">Valeur totale estimée</div>'
    + '<div class="big">' + eur0(total) + '</div></div></div>'
    + (bar ? '<div class="bar" aria-hidden="true">' + bar + '</div>' : '') + '</div>'
    + '<div class="grid" style="margin-bottom:18px">' + tiles + '</div>'
    + '<div class="card"><h3>Par où commencer ?</h3><ol class="steps">'
    + '<li><span>Parcourez les <b>catégories</b> ci-dessus : chacune explique ce qu’elle contient et où se trouvent les avoirs.</span></li>'
    + (hasCodes ? '<li><span>La section <b>Coffres</b> indique le montant présent dans chaque coffre et permet d’afficher son <b>code d’accès</b>.</span></li>' : '')
    + (hasDocs ? '<li><span>Les <b>documents</b> (actes, factures, certificats…) peuvent être téléchargés depuis la fiche de chaque bien ou la section Fichiers protégés. Une fois téléchargés, ils ne sont plus protégés : conservez-les en lieu sûr.</span></li>' : '')
    + '<li><span>Le bouton <b>Imprimer / PDF</b> en haut permet d’obtenir une version papier complète, par exemple pour un notaire ou un comptable.</span></li>'
    + '</ol></div>';
}

// ── Placements (titres ou crypto) ──
function renderPositions(list, sold, kind, at) {
  var held = list.filter(function(p){ return p.type !== 'cash' && p.type !== 'crypto_cash'; });
  var cash = list.filter(function(p){ return p.type === 'cash' || p.type === 'crypto_cash'; });
  var val = held.reduce(function(s,p){ return s + (p.value_eur || 0); }, 0);
  var inv = held.reduce(function(s,p){ return s + (p.invested_eur || 0); }, 0);
  var pnl = held.reduce(function(s,p){ return s + (p.pnl_eur || 0); }, 0);
  var cashTot = cash.reduce(function(s,p){ return s + (p.value_eur || 0); }, 0);
  held.sort(function(a,b){ return (b.value_eur || 0) - (a.value_eur || 0); });

  var intro = kind === 'crypto'
    ? 'Cryptomonnaies (comme le bitcoin) détenues sur des plateformes en ligne. Pour y accéder, il faut se connecter au compte de chaque plateforme (le nom figure sous chaque ligne).'
    : 'Placements détenus sur un ou plusieurs comptes-titres (courtier en ligne ou banque). Chaque ligne indique combien de parts sont détenues, ce qu’elles ont coûté et ce qu’elles valaient au ' + at + '.';

  var cards = held.map(function(p){
    var purchases = (p.purchases || []).map(function(a){
      return '<tr><td>' + fmtDate(a.date) + '</td><td class="r">' + num(a.quantity, 6) + '</td><td class="r">' + eur(a.unit_price) + '</td><td class="r">' + eur(a.fees) + '</td><td class="wrap">' + esc(a.note || '') + '</td></tr>';
    }).join('');
    var sales = (p.sales || []).map(function(s){
      return '<tr><td>' + fmtDate(s.date) + '</td><td class="r">' + num(s.quantity, 6) + '</td><td class="r">' + eur(s.unit_price) + '</td><td class="r">' + eur(s.fees) + '</td><td class="r ' + cls(s.realized_pnl) + '">' + signed(s.realized_pnl) + '</td></tr>';
    }).join('');
    var hist = (purchases ? '<div class="group-title" style="margin-top:4px">Achats</div><div class="tbl-wrap"><table><thead><tr><th>Date</th><th class="r">Quantité</th><th class="r">Prix par part</th><th class="r">Frais</th><th>Note</th></tr></thead><tbody>' + purchases + '</tbody></table></div>' : '')
      + (sales ? '<div class="group-title">Ventes</div><div class="tbl-wrap"><table><thead><tr><th>Date</th><th class="r">Quantité</th><th class="r">Prix par part</th><th class="r">Frais</th><th class="r">Gain réalisé</th></tr></thead><tbody>' + sales + '</tbody></table></div>' : '');
    return '<div class="item"><div class="item-head">'
      + '<span class="badge">' + esc(String(p.ticker || '').split(/[.\-]/)[0].slice(0, 5)) + '</span>'
      + '<div class="item-main"><div class="item-name">' + esc(p.name) + '</div>'
      + '<div class="item-sub">' + (TYPE_LABELS[p.type] || esc(p.type)) + ' · code ' + esc(p.ticker) + '</div></div>'
      + '<div class="item-val"><div class="v">' + eur0(p.value_eur) + '</div>'
      + (p.pnl_eur != null ? '<span class="pill ' + cls(p.pnl_eur) + '">' + signed(p.pnl_eur) + ' (' + pct(p.pnl_pct) + ')</span>' : '') + '</div></div>'
      + '<div class="facts">' + fact('Nombre de parts', num(p.quantity, 6)) + fact('Prix d’achat moyen', eur(p.average_cost))
      + fact('Montant investi', eur(p.invested_eur)) + fact('Cours au ' + at, eur(p.current_price_eur)) + '</div>'
      + (hist ? '<details class="more"><summary>Historique des achats et ventes</summary><div class="in">' + hist + '</div></details>' : '')
      + '</div>';
  }).join('');

  var cashBlock = cash.length ? '<div class="group-title">Argent disponible</div>' + cash.map(function(c){
    return '<div class="item"><div class="item-head"><span class="badge">€</span><div class="item-main"><div class="item-name">' + esc(c.name) + '</div>'
      + '<div class="item-sub">Liquidités non placées sur le compte</div></div><div class="item-val"><div class="v">' + eur(c.value_eur) + '</div></div></div></div>';
  }).join('') : '';

  var soldBlock = sold.length ? '<details class="more card" style="padding:0"><summary>Placements vendus entièrement (' + sold.length + ')</summary><div class="in"><div class="tbl-wrap"><table>'
    + '<thead><tr><th>Placement</th><th>Dernière vente</th><th class="r">Montant investi</th><th class="r">Gain ou perte</th></tr></thead><tbody>'
    + sold.map(function(p){ return '<tr><td class="wrap"><b>' + esc(p.name) + '</b><br/><span class="muted">' + esc(p.ticker) + '</span></td><td>' + fmtDate(p.last_sale_date) + '</td><td class="r">' + eur(p.total_invested) + '</td><td class="r ' + cls(p.realized_pnl) + '">' + signed(p.realized_pnl) + '</td></tr>'; }).join('')
    + '</tbody></table></div><p class="hint">Ces placements ne sont plus détenus ; ils sont listés pour mémoire.</p></div></details>' : '';

  return '<h2 class="ttl">' + (kind === 'crypto' ? 'Cryptomonnaies' : 'Placements en bourse') + '</h2>'
    + '<p class="lead">' + intro + '</p>'
    + '<div class="kpis">'
    + '<div class="kpi"><div class="k">Valeur au ' + at + '</div><div class="v">' + eur0(val) + '</div><div class="s">' + held.length + ' ligne' + (held.length > 1 ? 's' : '') + '</div></div>'
    + '<div class="kpi"><div class="k">Montant investi</div><div class="v">' + eur0(inv) + '</div><div class="s">ce que ces placements ont coûté</div></div>'
    + '<div class="kpi"><div class="k">Gain ou perte</div><div class="v ' + cls(pnl) + '">' + signed(pnl) + '</div><div class="s">valeur − montant investi</div></div>'
    + (cash.length ? '<div class="kpi"><div class="k">Argent disponible</div><div class="v">' + eur0(cashTot) + '</div><div class="s">non placé</div></div>' : '')
    + '</div>' + cards + cashBlock + soldBlock;
}

// ── Coffres ──
function renderCoffres(data) {
  var coffres = data.coffres || [];
  var total = coffres.reduce(function(s,c){ return s + (c.balance || 0); }, 0);
  var cards = coffres.map(function(c){
    var code = '';
    if (c.combination || c.combination_hint) {
      var idx = c.combination ? _codes.push(c.combination) - 1 : -1;
      code = '<div style="padding:0 18px 16px"><div class="fact" style="display:flex;align-items:center;gap:12px;flex-wrap:wrap">'
        + '<div style="flex:1;min-width:140px"><div class="k">Code d’accès</div>'
        + (idx > -1 ? '<div class="code" id="code-' + idx + '">••••••</div>' : '<div class="v">Pas de code enregistré</div>')
        + (c.combination_hint ? '<div class="k" style="margin-top:4px">Indice : ' + esc(c.combination_hint) + '</div>' : '') + '</div>'
        + (idx > -1 ? '<button class="btn no-print" onclick="toggleCode(this,' + idx + ')">Afficher le code</button>' : '') + '</div></div>';
    }
    var movs = (c.movements || []).map(function(m){
      var inMove = m.type === 'ENTRY';
      return '<tr><td>' + fmtDate(m.date) + '</td><td>' + (inMove ? 'Dépôt' : 'Retrait') + '</td><td class="r ' + (inMove ? 'pos' : 'neg') + '">' + (inMove ? '+' : '−') + eur(Math.abs(m.amount)) + '</td><td class="wrap">' + esc(m.description || '') + '</td></tr>';
    }).join('');
    return '<div class="item"><div class="item-head"><span class="badge" style="color:var(--p-coffres)">€</span>'
      + '<div class="item-main"><div class="item-name">' + esc(c.name) + '</div><div class="item-sub">Argent liquide (billets)</div></div>'
      + '<div class="item-val"><div class="v">' + eur(c.balance) + '</div></div></div>' + code
      + (movs ? '<details class="more"><summary>Derniers dépôts et retraits</summary><div class="in"><div class="tbl-wrap"><table><thead><tr><th>Date</th><th>Opération</th><th class="r">Montant</th><th>Note</th></tr></thead><tbody>' + movs + '</tbody></table></div></div></details>' : '')
      + '</div>';
  }).join('');
  var anyCode = coffres.some(function(c){ return c.combination; });
  return '<h2 class="ttl">Coffres</h2>'
    + '<p class="lead">Argent liquide conservé dans des coffres. Le montant indiqué est celui enregistré au moment du relevé ; il est conseillé de recompter sur place.</p>'
    + (anyCode ? '<div class="note blue no-print"><b>Codes d’accès :</b> ils sont masqués par défaut. Appuyez sur « Afficher le code » quand vous êtes seul devant l’écran.</div>' : '')
    + '<div class="kpis"><div class="kpi"><div class="k">Total en coffres</div><div class="v">' + eur0(total) + '</div><div class="s">' + coffres.length + ' coffre' + (coffres.length > 1 ? 's' : '') + '</div></div></div>'
    + cards;
}

// ── Biens ──
function renderAssets(data) {
  var coffreMap = {};
  (data.coffres || []).forEach(function(c){ coffreMap[c.id] = c.name; });
  var assets = (data.assets || []).slice().sort(function(a,b){ return (b.estimated_value || 0) - (a.estimated_value || 0); });
  var total = assets.reduce(function(s,a){ return s + (a.estimated_value || 0); }, 0);
  var order = ['immo', 'vehicule', 'bijou', 'metal', 'art', 'autre'];
  var groups = {};
  assets.forEach(function(a){ var k = a.category || 'autre'; (groups[k] = groups[k] || []).push(a); });

  var html = '';
  order.concat(Object.keys(groups).filter(function(k){ return order.indexOf(k) < 0; })).forEach(function(k){
    var g = groups[k]; if (!g) return;
    var sub = g.reduce(function(s,a){ return s + (a.estimated_value || 0); }, 0);
    html += '<div class="group-title">' + (CAT_LABELS[k] || esc(k)) + ' · ' + eur0(sub) + '</div>';
    g.forEach(function(a){
      var where = a.location ? esc(a.location) : (a.coffre_id ? 'Dans le coffre « ' + esc(coffreMap[a.coffre_id] || '?') + ' »' : '');
      var facts = a.category === 'vehicule'
        ? fact('Marque', esc(a.vehicle_make)) + fact('Modèle', esc(a.vehicle_model)) + fact('Année', a.vehicle_year) + fact('Carburant', esc(a.vehicle_fuel))
          + fact('Kilométrage', a.vehicle_km != null ? num(a.vehicle_km) + ' km' : null) + fact('Immatriculation', esc(a.vehicle_plate)) + fact('Numéro de châssis (VIN)', esc(a.vehicle_vin))
        : '';
      var events = (a.events || []).map(function(e){
        return '<tr><td>' + fmtDate(e.date) + '</td><td>' + (EVENT_LABELS[e.type] || esc(e.type)) + '</td><td class="r">' + eur(e.amount) + '</td><td class="wrap">' + esc(e.notes || '') + '</td></tr>';
      }).join('');
      var docs = (a.documents || []).map(docButton).join('');
      var more = (events ? '<div class="group-title" style="margin-top:4px">Historique</div><div class="tbl-wrap"><table><thead><tr><th>Date</th><th>Événement</th><th class="r">Montant</th><th>Note</th></tr></thead><tbody>' + events + '</tbody></table></div>' : '')
        + (docs ? '<div class="group-title">Documents</div><div class="docs">' + docs + '</div>' : '');
      html += '<div class="item"><div class="item-head"><span class="badge" style="color:var(--p-biens)">' + esc((CAT_LABELS[k] || k).slice(0, 4).toUpperCase()) + '</span>'
        + '<div class="item-main"><div class="item-name">' + esc(a.name) + '</div>'
        + '<div class="item-sub">' + [where, a.description ? esc(a.description) : ''].filter(Boolean).join(' · ') + '</div></div>'
        + '<div class="item-val"><div class="v">' + (a.estimated_value != null ? eur0(a.estimated_value) : '—') + '</div>'
        + (docs ? '<span class="pill muted">' + a.documents.length + ' document' + (a.documents.length > 1 ? 's' : '') + '</span>' : '') + '</div></div>'
        + (facts ? '<div class="facts">' + facts + '</div>' : '')
        + (more ? '<details class="more"><summary>' + (docs ? 'Documents et historique' : 'Historique') + '</summary><div class="in">' + more + '</div></details>' : '')
        + '</div>';
    });
  });
  return '<h2 class="ttl">Biens</h2>'
    + '<p class="lead">Biens matériels : immobilier, véhicules, bijoux, métaux précieux… Les valeurs sont des <b>estimations</b> ; une expertise peut être nécessaire en cas de vente ou de succession.</p>'
    + '<div class="kpis"><div class="kpi"><div class="k">Valeur estimée totale</div><div class="v">' + eur0(total) + '</div><div class="s">' + assets.length + ' bien' + (assets.length > 1 ? 's' : '') + '</div></div></div>'
    + html;
}

// ── Réserves ──
function renderReserves(data) {
  var rs = (data.summary && data.summary.reserves_stats) || {};
  var byYear = {};
  (data.reserves || []).forEach(function(r){
    var y = byYear[r.year] = byYear[r.year] || {amount:0, released:0, precompte:0, net:0, left:0, release_year:r.release_year, notes:r.notes};
    y.amount += r.amount || 0; y.released += r.released || 0; y.precompte += r.precompte_paye || 0;
    y.net += r.net_recu || 0; y.left += r.releasable || 0;
  });
  var now = new Date().getFullYear();
  var rows = Object.keys(byYear).sort(function(a,b){ return b - a; }).map(function(yr){
    var y = byYear[yr];
    var st = y.left <= 0.01 ? '<span class="pill pos">Versée</span>'
      : (y.release_year && y.release_year <= now ? '<span class="pill" style="background:var(--warnBg);color:var(--warn)">Versable</span>'
      : '<span class="pill muted">À partir de ' + (y.release_year || '?') + '</span>');
    return '<tr><td><b>' + yr + '</b></td><td class="r">' + eur(y.amount) + '</td><td class="r">' + eur(y.released) + '</td><td class="r">' + eur(y.left) + '</td><td>' + st + '</td><td class="wrap">' + esc(y.notes || '') + '</td></tr>';
  }).join('');
  return '<h2 class="ttl">Réserves de la société</h2>'
    + '<p class="lead">Bénéfices mis de côté dans la société (réserves de liquidation). Ils peuvent être versés plus tard à l’actionnaire ; '
    + 'l’année « à partir de » indique quand ce versement devient possible dans les conditions prévues. Le comptable de la société peut confirmer les montants et la marche à suivre.</p>'
    + '<div class="kpis">'
    + '<div class="kpi"><div class="k">Encore à verser</div><div class="v">' + eur0(rs.total_releasable || 0) + '</div></div>'
    + '<div class="kpi"><div class="k">Déjà versé (brut)</div><div class="v">' + eur0(rs.total_released || 0) + '</div><div class="s">net reçu ' + eur0(rs.total_net_recu || 0) + ' après précompte</div></div>'
    + '<div class="kpi"><div class="k">Total mis en réserve</div><div class="v">' + eur0(rs.total_amount || 0) + '</div></div>'
    + '</div>'
    + '<div class="card" style="padding:8px 10px"><div class="tbl-wrap"><table><thead><tr><th>Année</th><th class="r">Mis en réserve</th><th class="r">Déjà versé</th><th class="r">Reste</th><th>Statut</th><th>Note</th></tr></thead><tbody>' + rows + '</tbody></table></div></div>';
}

// ── Fichiers protégés ──
function renderVault(data) {
  var files = data.vault || [];
  return '<h2 class="ttl">Fichiers protégés</h2>'
    + '<p class="lead">Fichiers importants conservés de façon sécurisée (par exemple la liste des mots de passe et des comptes en ligne).</p>'
    + '<div class="note"><b>Attention :</b> un fichier téléchargé n’est plus protégé. Ouvrez-le sur un appareil de confiance et supprimez-le après usage.</div>'
    + '<div class="card"><div class="docs">' + files.map(docButton).join('') + '</div></div>';
}

// ── Lexique ──
function renderLexique() {
  var L = [
    ['Compte-titres', 'Compte ouvert chez une banque ou un courtier en ligne, sur lequel sont détenus des placements en bourse.'],
    ['Action', 'Part d’une entreprise cotée en bourse.'],
    ['Fonds indiciel (ETF)', 'Placement qui regroupe des centaines d’actions d’un coup (par exemple « MSCI World » = grandes entreprises du monde entier).'],
    ['Nombre de parts', 'Combien d’unités d’un placement sont détenues.'],
    ['Prix d’achat moyen', 'Prix payé en moyenne pour une part, frais compris. Aussi appelé « PRU » (prix de revient unitaire).'],
    ['Montant investi', 'Ce que les parts encore détenues ont coûté au total.'],
    ['Gain ou perte', 'Différence entre la valeur au jour du relevé et le montant investi. Positive en vert, négative en rouge.'],
    ['Cours', 'Prix d’une part en bourse à une date donnée.'],
    ['Cryptomonnaie', 'Monnaie numérique (bitcoin, ether…) détenue sur une plateforme en ligne comme Kraken ou Bitvavo.'],
    ['Réserve de liquidation', 'Bénéfice d’une société mis de côté, qui peut être versé plus tard à l’actionnaire avec une fiscalité particulière.'],
    ['Précompte mobilier', 'Impôt retenu à la source lors du versement d’un dividende ou d’une réserve.'],
    ['Liquidités', 'Argent disponible immédiatement, non placé.'],
  ];
  return '<h2 class="ttl">Lexique</h2><p class="lead">Les termes utilisés dans ce relevé, expliqués simplement.</p>'
    + '<div class="card"><dl class="lex">' + L.map(function(x){ return '<dt>' + x[0] + '</dt><dd>' + x[1] + '</dd>'; }).join('') + '</dl></div>';
}

// ── Écran d'ouverture : interactions ──
document.getElementById('unlockForm').addEventListener('submit', function(e){ e.preventDefault(); unlock(); });
document.getElementById('togglePass').addEventListener('click', function(){
  var inp = document.getElementById('passInput');
  var show = inp.type === 'password';
  inp.type = show ? 'text' : 'password';
  this.textContent = show ? 'Masquer' : 'Afficher';
  this.setAttribute('aria-pressed', show ? 'true' : 'false');
  inp.focus();
});
if (!(window.crypto && crypto.subtle && window.DecompressionStream && window.TextEncoder)) {
  document.getElementById('browserWarn').classList.remove('hidden');
  document.getElementById('unlockBtn').disabled = true;
}
</script>
<!-- Bloc 2 : injection des données — séparé pour éviter les erreurs de parsing Safari -->
<script>
BLOB = "__BLOB__";
DOC_BLOBS = __DOC_BLOBS__;
ITERATIONS = __ITERATIONS__;
(function(){
  var raw = "__EXPORTED_AT__";
  var d = new Date(raw + 'T00:00:00');
  document.getElementById('exportDateDisplay').textContent = isNaN(d) ? raw
    : d.toLocaleDateString('fr-BE', {day:'numeric', month:'long', year:'numeric'});
})();
document.getElementById('passInput').focus();
</script>
</body>
</html>'''


def _build_html(main_blob: str, doc_blobs_json: str, exported_at: str, iterations: int) -> str:
    return (_HTML_TEMPLATE
            .replace("__BLOB__", main_blob)
            .replace("__DOC_BLOBS__", doc_blobs_json)
            .replace("__EXPORTED_AT__", exported_at)
            .replace("__ITERATIONS__", str(iterations)))


# ── Endpoint ──────────────────────────────────────────────

@router.post("")
def generate_export(
    body: ExportRequest,
    db: Session = Depends(get_db),
    user: User = Depends(verify_csrf),
):
    if not body.passphrase or len(body.passphrase) < 6:
        raise HTTPException(status_code=400, detail="Passphrase trop courte (6 caractères minimum)")

    data = _collect_data(db, user)
    json_bytes = gzip.compress(
        json.dumps(data, ensure_ascii=False, default=str).encode("utf-8"),
        compresslevel=6,
    )
    main_blob, key = _derive_and_encrypt(json_bytes, body.passphrase)

    # Chiffrer chaque document séparément
    doc_blobs: dict[str, str] = {}
    for asset in db.query(PhysicalAsset).filter(
        PhysicalAsset.user_id == user.id,
        PhysicalAsset.sold_at == None,  # noqa: E711
    ).all():
        for doc in asset.documents:
            doc_blobs[f"d{doc.id}"] = _encrypt_doc(enc.decrypt(doc.encrypted_data), key)
    for vf in db.query(PasswordFile).filter(PasswordFile.user_id == user.id).all():
        doc_blobs[f"v{vf.id}"] = _encrypt_doc(enc.decrypt(vf.encrypted_data), key)

    doc_blobs_json = json.dumps(doc_blobs)
    exported_at = data["meta"]["exported_at"][:10]  # YYYY-MM-DD
    html = _build_html(main_blob, doc_blobs_json, exported_at, PBKDF2_ITERATIONS)

    filename = f"patrimonium-export-{exported_at}.html"
    return Response(
        content=html.encode("utf-8"),
        media_type="text/html",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


# ── Excel export ──────────────────────────────────────────

_XL_HEADER_FILL = PatternFill("solid", fgColor="1E3A5F")
_XL_HEADER_FONT = Font(bold=True, color="FFFFFF", size=10)
_EUR_FMT  = '#,##0.00 "€"'
_PCT_FMT  = r'0.00\%'
_DATE_FMT = "DD/MM/YYYY"


def _xl_write_headers(ws, headers: list[str]) -> None:
    ws.append(headers)
    for cell in ws[1]:
        cell.font = _XL_HEADER_FONT
        cell.fill = _XL_HEADER_FILL
        cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
    ws.row_dimensions[1].height = 20


def _xl_autowidth(ws) -> None:
    for col_cells in ws.columns:
        max_len = max(
            len(str(c.value)) if c.value is not None else 0
            for c in col_cells
        )
        ws.column_dimensions[get_column_letter(col_cells[0].column)].width = min(max_len + 4, 45)


def _xl_fmt_col(ws, col_idx: int, fmt: str, start_row: int = 2) -> None:
    for row in ws.iter_rows(min_row=start_row, min_col=col_idx, max_col=col_idx):
        for cell in row:
            cell.number_format = fmt


def _parse_date(s) -> date | None:
    if not s:
        return None
    try:
        return date.fromisoformat(str(s)[:10])
    except (ValueError, TypeError):
        return None


@router.get("/patrimoine-excel")
def export_patrimoine_excel(
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Génère un fichier .xlsx structuré avec les données patrimoniales."""
    data = _collect_data(db, user)
    today_str  = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    today_date = date.fromisoformat(today_str)

    portfolio_items = data["portfolio"]
    # Exclure les liquidités SaxoBank (type='cash') et le crypto du total "bourse"
    stock_items     = [p for p in portfolio_items
                       if p.get("type") not in ("cash", "crypto", "crypto_cash")]
    crypto_items    = [p for p in portfolio_items if p.get("type") == "crypto"]
    crypto_cash     = [p for p in portfolio_items if p.get("type") == "crypto_cash"]
    saxo_cash_items = [p for p in portfolio_items if p.get("type") == "cash"]
    total_portfolio = sum(p.get("value_eur") or 0.0 for p in stock_items)
    total_crypto_xl = (sum(p.get("value_eur") or 0.0 for p in crypto_items)
                       + sum(p.get("value_eur") or 0.0 for p in crypto_cash))
    total_saxo_cash_xl = sum(p.get("value_eur") or 0.0 for p in saxo_cash_items)

    wb = openpyxl.Workbook()
    wb.remove(wb.active)

    # ── Feuille 1 : Portefeuille Boursier ──────────────────
    ws1 = wb.create_sheet("Portefeuille Boursier")
    _xl_write_headers(ws1, [
        "Ticker", "Nom", "Quantité", "PRU (€)", "Cours actuel (€)",
        "Valeur totale (€)", "P&L (€)", "P&L (%)", "Allocation (%)",
    ])
    for p in stock_items:
        qty = p.get("quantity") or 0.0
        if qty <= 0:
            continue
        alloc = (p.get("value_eur") or 0.0) / total_portfolio * 100.0 if total_portfolio > 0 else 0.0
        ws1.append([
            p.get("ticker") or "",
            p.get("name") or "",
            qty,
            p.get("average_cost") or 0.0,
            p.get("current_price_eur") or 0.0,
            p.get("value_eur") or 0.0,
            p.get("pnl_eur") or 0.0,
            p.get("pnl_pct") or 0.0,
            alloc,
        ])
    _xl_fmt_col(ws1, 4, _EUR_FMT)
    _xl_fmt_col(ws1, 5, _EUR_FMT)
    _xl_fmt_col(ws1, 6, _EUR_FMT)
    _xl_fmt_col(ws1, 7, _EUR_FMT)
    _xl_fmt_col(ws1, 8, _PCT_FMT)
    _xl_fmt_col(ws1, 9, _PCT_FMT)
    _xl_autowidth(ws1)

    # ── Feuille Crypto (uniquement si des positions existent) ──
    if crypto_items or crypto_cash:
        wsc = wb.create_sheet("Crypto")
        _xl_write_headers(wsc, [
            "Actif", "Compte", "Quantité", "PRU (€)", "Cours actuel (€)",
            "Valeur totale (€)", "P&L (€)", "P&L (%)", "Allocation (%)",
        ])
        for p in crypto_items:
            qty = p.get("quantity") or 0.0
            if qty <= 0:
                continue
            alloc = (p.get("value_eur") or 0.0) / total_crypto_xl * 100.0 if total_crypto_xl > 0 else 0.0
            # display_name = "BTC · Kraken principal"
            name_parts = (p.get("name") or "").split("·")
            wsc.append([
                name_parts[0].strip() or (p.get("ticker") or ""),
                name_parts[1].strip() if len(name_parts) > 1 else "",
                qty,
                p.get("average_cost") or 0.0,
                p.get("current_price_eur") or 0.0,
                p.get("value_eur") or 0.0,
                p.get("pnl_eur") or 0.0,
                p.get("pnl_pct") or 0.0,
                alloc,
            ])
        # Liquidités disponibles sur les exchanges (argent non investi)
        for c in crypto_cash:
            bal = c.get("value_eur") or 0.0
            alloc = bal / total_crypto_xl * 100.0 if total_crypto_xl > 0 else 0.0
            name_parts = (c.get("name") or "").split("·")
            wsc.append([
                "Liquidités (EUR)",
                name_parts[1].strip() if len(name_parts) > 1 else "",
                "", "", "", bal, "", "", alloc,
            ])
        for col in (4, 5, 6, 7):
            _xl_fmt_col(wsc, col, _EUR_FMT)
        _xl_fmt_col(wsc, 8, _PCT_FMT)
        _xl_fmt_col(wsc, 9, _PCT_FMT)
        _xl_autowidth(wsc)

    # ── Feuille 2 : Actifs Physiques ────────────────────────
    ws2 = wb.create_sheet("Actifs Physiques")
    _xl_write_headers(ws2, [
        "Catégorie", "Nom", "Localisation", "Valeur estimée (€)",
        "Dernière évaluation", "Notes",
    ])
    for a in data["assets"]:
        val_dates = [e["date"] for e in a.get("events", []) if e.get("type") == "VALUATION"]
        last_val  = _parse_date(max(val_dates)) if val_dates else None
        ws2.append([
            a.get("category") or "",
            a.get("name") or "",
            a.get("location") or "",
            a.get("estimated_value") or 0.0,
            last_val,
            a.get("description") or "",
        ])
    _xl_fmt_col(ws2, 4, _EUR_FMT)
    _xl_fmt_col(ws2, 5, _DATE_FMT)
    _xl_autowidth(ws2)

    # ── Feuille 3 : Réserves SRL ────────────────────────────
    ws3 = wb.create_sheet("Réserves SRL")
    _xl_write_headers(ws3, [
        "Année", "Montant constitué (€)", "Libéré brut (€)",
        "Précompte payé (€)", "Net reçu (€)", "Encore libérable (€)", "Statut",
    ])
    for r in sorted(data["reserves"], key=lambda x: (x.get("year", 0), x.get("month", 0))):
        released   = r.get("released") or 0.0
        releasable = r.get("releasable") or 0.0
        amount     = r.get("amount") or 0.0
        if released == 0:
            status = "Non libéré"
        elif releasable == 0:
            status = "Libéré"
        else:
            status = "Partiel"
        ws3.append([
            r.get("year") or "",
            amount,
            released,
            r.get("precompte_paye") or 0.0,
            r.get("net_recu") or 0.0,
            releasable,
            status,
        ])
    for col in [2, 3, 4, 5, 6]:
        _xl_fmt_col(ws3, col, _EUR_FMT)
    _xl_autowidth(ws3)

    # ── Feuille 4 : Liquidités ──────────────────────────────
    ws4 = wb.create_sheet("Liquidités")
    _xl_write_headers(ws4, ["Coffre/Compte", "Montant (€)", "Devise", "Date mise à jour"])
    for c in data["coffres"]:
        moves     = c.get("movements", [])
        last_date = _parse_date(moves[0]["date"]) if moves else today_date
        ws4.append([
            c.get("name") or "",
            c.get("balance") or 0.0,
            "EUR",
            last_date,
        ])
    _xl_fmt_col(ws4, 2, _EUR_FMT)
    _xl_fmt_col(ws4, 4, _DATE_FMT)
    _xl_autowidth(ws4)

    # ── Feuille 5 : Synthèse ────────────────────────────────
    ws5 = wb.create_sheet("Synthèse")
    _xl_write_headers(ws5, [
        "Date export", "Patrimoine total (€)", "Total immobilier (€)", "Total bourse (€)",
        "Total crypto (€)", "Liq. SaxoBank (€)", "Total réserves SRL (€)", "Liq. coffres (€)",
        "Total métaux (€)", "Total véhicules (€)",
    ])
    assets         = data["assets"]
    total_immo     = sum((a.get("estimated_value") or 0.0) for a in assets if a.get("category") == "immo")
    total_metal    = sum((a.get("estimated_value") or 0.0) for a in assets if a.get("category") == "metal")
    total_vehicule = sum((a.get("estimated_value") or 0.0) for a in assets if a.get("category") == "vehicule")
    total_cash_xl  = sum(c.get("balance") or 0.0 for c in data["coffres"])
    total_res      = sum(r.get("releasable") or 0.0 for r in data["reserves"])
    total_phys     = sum((a.get("estimated_value") or 0.0) for a in assets)
    grand_total    = (total_portfolio + total_crypto_xl + total_saxo_cash_xl
                      + total_cash_xl + total_phys + total_res)

    ws5.append([
        today_date,
        grand_total,
        total_immo,
        total_portfolio,
        total_crypto_xl,
        total_saxo_cash_xl,
        total_res,
        total_cash_xl,
        total_metal,
        total_vehicule,
    ])
    _xl_fmt_col(ws5, 1, _DATE_FMT)
    for col in range(2, 11):
        _xl_fmt_col(ws5, col, _EUR_FMT)
    _xl_autowidth(ws5)

    # ── Sérialisation ───────────────────────────────────────
    buf = BytesIO()
    wb.save(buf)
    buf.seek(0)

    filename = f"patrimoine_{today_str}.xlsx"
    return Response(
        content=buf.getvalue(),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
