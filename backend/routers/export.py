"""Export router: génère un fichier HTML autonome chiffré pour clé USB."""
import base64 as b64_stdlib
import gzip
import json
import os
from datetime import datetime, timezone

from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import Response
from pydantic import BaseModel
from sqlalchemy.orm import Session

import encryption as enc
import market_data as md
from database import get_db
from dependencies import get_current_user, verify_csrf
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
        if pos.ticker == "MANUAL":
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
            "type": pos.asset_type,
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

    # Totaux
    total_portfolio      = sum(p["value_eur"] or 0 for p in portfolio_items)
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
            "total_cash_eur":       total_cash,
            "total_assets_eur":     total_assets,
            "total_reserves_eur":   total_releasable_res,
            "grand_total_eur":      total_portfolio + total_cash + total_assets + total_releasable_res,
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
<title>Patrimonium — Export patrimoine</title>
<style>
*{box-sizing:border-box;margin:0;padding:0}
:root{--bg:#0A0B0E;--bg2:#13141A;--bg3:#1C1E27;--border:#2A2D3A;--text:#E8EAF0;--text2:#8B90A0;--accent:#3B82F6;--green:#00D68F;--red:#FF4757;--yellow:#F59E0B;--purple:#a855f7;--teal:#14b8a6;--radius:10px;--font:'Segoe UI',system-ui,sans-serif}
body{background:var(--bg);color:var(--text);font-family:var(--font);min-height:100vh;display:flex;flex-direction:column}
h1,h2,h3{font-weight:600}
/* Lock screen */
#lockScreen{flex:1;display:flex;align-items:center;justify-content:center;padding:24px}
.lock-card{background:var(--bg2);border:1px solid var(--border);border-radius:16px;padding:40px;width:100%;max-width:420px;text-align:center}
.lock-icon{font-size:48px;margin-bottom:16px}
.lock-title{font-size:22px;font-weight:700;margin-bottom:6px}
.lock-sub{color:var(--text2);font-size:13px;margin-bottom:28px}
.lock-sub span{color:var(--text);font-weight:500}
.form-input{width:100%;background:var(--bg3);border:1px solid var(--border);border-radius:var(--radius);color:var(--text);padding:11px 14px;font-size:15px;outline:none;margin-bottom:12px;font-family:inherit}
.form-input:focus{border-color:var(--accent)}
.btn{display:inline-flex;align-items:center;justify-content:center;gap:6px;padding:11px 20px;border-radius:var(--radius);font-size:14px;font-weight:500;border:none;cursor:pointer;transition:.15s}
.btn-primary{background:var(--accent);color:#fff;width:100%}
.btn-primary:hover{filter:brightness(1.1)}
.err{color:var(--red);font-size:13px;margin-top:10px;min-height:20px}
/* App */
#app{display:none;flex-direction:column;min-height:100vh}
header{background:var(--bg2);border-bottom:1px solid var(--border);padding:0 24px;position:sticky;top:0;z-index:100}
.header-inner{display:flex;align-items:center;justify-content:space-between;height:56px;max-width:1200px;margin:0 auto}
.logo{font-size:18px;font-weight:700;display:flex;align-items:center;gap:8px}
.logo-icon{color:var(--accent)}
.badge-ro{background:rgba(255,71,87,.15);color:var(--red);border:1px solid rgba(255,71,87,.3);border-radius:20px;padding:3px 10px;font-size:11px;font-weight:600}
.export-date{color:var(--text2);font-size:12px}
main{flex:1;padding:24px;max-width:1200px;margin:0 auto;width:100%}
/* Tabs */
.tabs{display:flex;gap:4px;background:var(--bg2);border:1px solid var(--border);border-radius:var(--radius);padding:4px;margin-bottom:24px;flex-wrap:wrap}
.tab-btn{padding:8px 16px;border-radius:7px;border:none;background:transparent;color:var(--text2);font-size:13px;font-weight:500;cursor:pointer;transition:.15s;font-family:inherit}
.tab-btn.active{background:var(--bg3);color:var(--text)}
.tab-panel{display:none}.tab-panel.active{display:block}
/* Cards */
.summary-grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(200px,1fr));gap:16px;margin-bottom:28px}
.card{background:var(--bg2);border:1px solid var(--border);border-radius:var(--radius);padding:20px}
.card-label{font-size:11px;color:var(--text2);text-transform:uppercase;letter-spacing:.08em;margin-bottom:6px}
.card-value{font-size:24px;font-weight:700}
.blue{color:var(--accent)}.green{color:var(--green)}.yellow{color:var(--yellow)}.purple{color:var(--purple)}
/* Position cards */
.pos-card{background:var(--bg2);border:1px solid var(--border);border-radius:var(--radius);margin-bottom:10px;overflow:hidden;transition:border-color .15s}
.pos-card:hover{border-color:rgba(59,130,246,.4)}
.pos-header{padding:14px 16px;display:flex;align-items:center;justify-content:space-between;cursor:pointer;user-select:none}
.pos-left{flex:1}
.pos-name-row{display:flex;align-items:center;gap:8px;margin-bottom:3px;flex-wrap:wrap}
.pos-name{font-size:14px;font-weight:600}
.pos-ticker{font-size:11px;color:var(--text2)}
.pos-chevron{color:var(--text2);transition:transform .2s;font-size:11px;flex-shrink:0;margin-left:12px}
.asset-chevron{color:var(--text2);transition:transform .2s;font-size:11px;display:inline-block}
.asset-row.open .asset-chevron{transform:rotate(90deg)}
.pos-metrics{display:flex;gap:20px;padding:0 16px 14px;flex-wrap:wrap}
.metric{display:flex;flex-direction:column;min-width:70px}
.metric-lbl{font-size:10px;color:var(--text2);text-transform:uppercase;letter-spacing:.06em;margin-bottom:3px}
.metric-val{font-size:13px;font-weight:500}
.alloc-bar{height:3px;background:var(--border)}
.alloc-fill{height:100%;background:var(--accent)}
.card-detail{border-top:1px solid var(--border);padding:16px;display:none}
.detail-section{margin-bottom:16px}
.detail-section:last-child{margin-bottom:0}
/* Table */
.table-wrap{overflow-x:auto}
table{width:100%;border-collapse:collapse;font-size:13px}
thead tr{border-bottom:1px solid var(--border)}
th{padding:10px 12px;color:var(--text2);font-weight:500;font-size:11px;text-transform:uppercase;letter-spacing:.06em;white-space:nowrap}
th.left,td.left{text-align:left}
th:not(.left){text-align:right}
td{padding:10px 12px;border-bottom:1px solid var(--border);color:var(--text);white-space:nowrap}
td:not(.left){text-align:right}
tr:last-child td{border-bottom:none}
tr:hover td{background:var(--bg3)}
.pos{color:var(--green)}.neg{color:var(--red)}
/* Badges */
.badge{display:inline-flex;align-items:center;padding:2px 8px;border-radius:20px;font-size:11px;font-weight:500}
.badge-action{background:rgba(59,130,246,.15);color:var(--accent)}
.badge-etf{background:rgba(0,214,143,.15);color:var(--green)}
.badge-commodity{background:rgba(245,158,11,.15);color:var(--yellow)}
.badge-bond_manual{background:rgba(168,85,247,.15);color:var(--purple)}
.badge-bijou{background:rgba(168,85,247,.15);color:var(--purple)}
.badge-immo{background:rgba(59,130,246,.15);color:var(--accent)}
.badge-vehicule{background:rgba(20,184,166,.15);color:var(--teal)}
.badge-art{background:rgba(245,158,11,.15);color:var(--yellow)}
.badge-metal{background:rgba(209,162,68,.15);color:#c9a227}
.badge-autre{background:rgba(139,144,160,.15);color:var(--text2)}
/* Vehicle card */
.v-grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(150px,1fr));gap:10px;margin:12px 0}
.v-field{background:var(--bg3);border:1px solid var(--border);border-radius:8px;padding:8px 10px}
.v-label{font-size:10px;color:var(--text2);margin-bottom:2px}
.v-val{font-size:13px;font-weight:500}
/* Expand */
.expand-row{background:var(--bg2)}
.expand-content{padding:16px;font-size:12px;color:var(--text2)}
.section-title{font-size:11px;font-weight:600;text-transform:uppercase;letter-spacing:.08em;color:var(--text2);margin-bottom:10px}
/* Reserves */
.yr-block{margin-bottom:20px}
.yr-title{font-size:14px;font-weight:600;margin-bottom:10px;color:var(--text)}
/* Footer */
footer{padding:16px 24px;text-align:center;color:var(--text2);font-size:11px;border-top:1px solid var(--border)}
</style>
</head>
<body>

<div id="lockScreen">
  <div class="lock-card">
    <div class="lock-icon">🔐</div>
    <div class="lock-title">Patrimonium</div>
    <div class="lock-sub">Export patrimoine du <span id="exportDateDisplay"></span><br/>Entrez la passphrase pour accéder aux données.</div>
    <input type="password" class="form-input" id="passInput" placeholder="Passphrase…" autocomplete="current-password"/>
    <button class="btn btn-primary" onclick="unlock()">Déverrouiller</button>
    <div class="err" id="errMsg"></div>
  </div>
</div>

<div id="app">
  <header>
    <div class="header-inner">
      <div class="logo"><span class="logo-icon">◈</span> Patrimonium</div>
      <div style="display:flex;align-items:center;gap:12px">
        <span class="export-date" id="headerDate"></span>
        <span class="badge-ro">LECTURE SEULE</span>
      </div>
    </div>
  </header>
  <main>
    <div class="tabs" id="mainTabs">
      <button class="tab-btn active" onclick="showTab('summary',this)">📊 Résumé</button>
      <button class="tab-btn" onclick="showTab('portfolio',this)">📈 Portefeuille</button>
      <button class="tab-btn" onclick="showTab('coffres',this)">🏦 Coffres</button>
      <button class="tab-btn" onclick="showTab('assets',this)">💎 Actifs physiques</button>
      <button class="tab-btn" onclick="showTab('reserves',this)">📅 Réserves</button>
      <button class="tab-btn" onclick="showTab('vault',this)">🔐 Fichiers</button>
    </div>
    <div class="tab-panel active" id="tab-summary"></div>
    <div class="tab-panel" id="tab-portfolio"></div>
    <div class="tab-panel" id="tab-coffres"></div>
    <div class="tab-panel" id="tab-assets"></div>
    <div class="tab-panel" id="tab-reserves"></div>
    <div class="tab-panel" id="tab-vault"></div>
  </main>
  <footer id="footerInfo"></footer>
</div>

<script>
// Déclarations globales — les valeurs sont injectées dans le 2e bloc <script>
var BLOB, DOC_BLOBS, ITERATIONS;
var _cryptoKey = null;

function b64ToBytes(b64) {
  const bin = atob(b64);
  const bytes = new Uint8Array(bin.length);
  for (let i = 0; i < bin.length; i++) bytes[i] = bin.charCodeAt(i);
  return bytes;
}

async function downloadFile(docKey, filename, mimeType) {
  if (!_cryptoKey) return;
  const btn = event.currentTarget;
  btn.disabled = true; btn.textContent = '⏳';
  try {
    const raw = b64ToBytes(DOC_BLOBS[docKey]);
    const nonce = raw.slice(0, 12);
    const ct = raw.slice(12);
    const plain = await crypto.subtle.decrypt({name:'AES-GCM',iv:nonce}, _cryptoKey, ct);
    const blob = new Blob([plain], {type: mimeType || 'application/octet-stream'});
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url; a.download = filename;
    document.body.appendChild(a); a.click();
    document.body.removeChild(a);
    setTimeout(() => URL.revokeObjectURL(url), 2000);
    btn.textContent = '✓';
    setTimeout(() => { btn.disabled = false; btn.textContent = '⬇ Télécharger'; }, 2000);
  } catch(e) {
    btn.disabled = false; btn.textContent = '⬇ Télécharger';
    alert('Erreur de déchiffrement du document.');
  }
}

async function unlock() {
  const pass = document.getElementById('passInput').value;
  const errEl = document.getElementById('errMsg');
  if (!pass) { errEl.textContent = 'Entrez la passphrase.'; return; }
  errEl.textContent = 'Déchiffrement…';
  try {
    const blob = b64ToBytes(BLOB);
    const salt = blob.slice(0, 32);
    const nonce = blob.slice(32, 44);
    const ct = blob.slice(44);
    const keyMat = await crypto.subtle.importKey('raw', new TextEncoder().encode(pass), 'PBKDF2', false, ['deriveKey']);
    const key = await crypto.subtle.deriveKey(
      { name: 'PBKDF2', salt, iterations: ITERATIONS, hash: 'SHA-256' },
      keyMat, { name: 'AES-GCM', length: 256 }, false, ['decrypt']
    );
    const plain = await crypto.subtle.decrypt({name:'AES-GCM',iv:nonce}, key, ct);
    const ds = new DecompressionStream('gzip');
    const writer = ds.writable.getWriter();
    writer.write(new Uint8Array(plain));
    writer.close();
    const decompressed = await new Response(ds.readable).arrayBuffer();
    const data = JSON.parse(new TextDecoder().decode(decompressed));
    _cryptoKey = key;
    document.getElementById('lockScreen').style.display = 'none';
    document.getElementById('app').style.display = 'flex';
    renderAll(data);
  } catch(e) {
    errEl.textContent = 'Passphrase incorrecte ou fichier corrompu.';
  }
}

function showTab(id, btn) {
  document.querySelectorAll('.tab-panel').forEach(p => p.classList.remove('active'));
  document.querySelectorAll('.tab-btn').forEach(b => b.classList.remove('active'));
  document.getElementById('tab-' + id).classList.add('active');
  if (btn) btn.classList.add('active');
}

// ── Formatters ──────────────────────────────────────────────────────────
function fmtSize(b) {
  if (!b) return '—';
  if (b>=1048576) return (b/1048576).toFixed(1)+' MB';
  if (b>=1024) return (b/1024).toFixed(0)+' KB';
  return b+' B';
}
function eur(v, d) {
  d = (d == null) ? 2 : d;
  if (v == null) return '—';
  return new Intl.NumberFormat('fr-BE', {style:'currency',currency:'EUR',minimumFractionDigits:d,maximumFractionDigits:d}).format(v);
}
function num(v, d) {
  d = (d == null) ? 0 : d;
  if (v == null) return '—';
  return new Intl.NumberFormat('fr-BE', {minimumFractionDigits:d,maximumFractionDigits:d}).format(v);
}
function pct(v) { return v == null ? '—' : (v >= 0 ? '+' : '') + v.toFixed(2) + '%'; }
function cls(v) { return v == null ? '' : v >= 0 ? 'pos' : 'neg'; }
function esc(s) {
  if (!s) return '';
  return String(s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;');
}
function fmtDate(iso) {
  if (!iso) return '—';
  const d = new Date(iso.includes('T') ? iso : iso + 'T00:00:00');
  return d.toLocaleDateString('fr-BE', {day:'2-digit',month:'2-digit',year:'numeric'});
}

const CAT_LABELS = {bijou:'Bijou',immo:'Immobilier',vehicule:'Véhicule',art:'Art',metal:'Métaux précieux',autre:'Autre'};
const CAT_ICONS  = {bijou:'💎',immo:'🏠',vehicule:'🚗',art:'🎨',metal:'🪙',autre:'📦'};
const TYPE_LABELS = {action:'Action',etf:'ETF',commodity:'Or',bond_manual:'Obligation'};

// ── Donut SVG (pur JS, sans dépendance) ─────────────────────────────────
function buildDonut(segs, size) {
  size = size || 200;
  const total = segs.reduce(function(s,x){ return s + (x.value||0); }, 0);
  if (!total) return '';
  const r = 75, cx = 100, cy = 100, sw = 26;
  let angle = -Math.PI / 2;
  let paths = '';
  for (let i = 0; i < segs.length; i++) {
    const seg = segs[i];
    if (!(seg.value > 0)) continue;
    let ratio = seg.value / total;
    if (ratio >= 1) ratio = 0.9999;
    const sweep = ratio * Math.PI * 2;
    const x1 = (cx + r * Math.cos(angle)).toFixed(2);
    const y1 = (cy + r * Math.sin(angle)).toFixed(2);
    angle += sweep;
    const x2 = (cx + r * Math.cos(angle)).toFixed(2);
    const y2 = (cy + r * Math.sin(angle)).toFixed(2);
    const large = sweep > Math.PI ? 1 : 0;
    paths += '<path d="M' + x1 + ',' + y1 + ' A' + r + ',' + r + ',0,' + large + ',1,' + x2 + ',' + y2
           + '" stroke="' + seg.color + '" stroke-width="' + sw + '" fill="none" stroke-linecap="butt"/>';
  }
  return '<svg width="' + size + '" height="' + size + '" viewBox="0 0 200 200">'
       + '<circle cx="100" cy="100" r="' + r + '" fill="none" stroke="#2A2D3A" stroke-width="' + sw + '"/>'
       + paths + '</svg>';
}

// ── Render all ───────────────────────────────────────────────────────────
function renderAll(data) {
  document.getElementById('headerDate').textContent = 'Export du ' + fmtDate(data.meta.exported_at);
  document.getElementById('footerInfo').textContent =
    'Propriétaire : ' + data.meta.owner_name + ' (' + data.meta.owner_email + ')'
    + ' · Export du ' + fmtDate(data.meta.exported_at) + ' · Patrimonium';
  renderSummary(data);
  renderPortfolio(data);
  renderCoffres(data);
  renderAssets(data);
  renderReserves(data);
  renderVault(data);
}

// ── Summary ──────────────────────────────────────────────────────────────
function renderSummary(data) {
  const s = data.summary;
  const segs = [
    {label:'Portefeuille', value: s.total_portfolio_eur || 0, color:'#3B82F6'},
    {label:'Liquidités',   value: s.total_cash_eur      || 0, color:'#F59E0B'},
    {label:'Actifs phys.', value: s.total_assets_eur    || 0, color:'#a855f7'},
    {label:'Réserves',     value: s.total_reserves_eur  || 0, color:'#14b8a6'},
  ].filter(function(x){ return x.value > 0; });

  const donut = buildDonut(segs, 200);
  let legend = '';
  for (let i = 0; i < segs.length; i++) {
    const seg = segs[i];
    const pctVal = s.grand_total_eur > 0 ? (seg.value / s.grand_total_eur * 100).toFixed(1) : '0';
    legend += '<div style="display:flex;align-items:center;gap:10px;margin-bottom:10px">'
            + '<div style="width:12px;height:12px;border-radius:3px;background:' + seg.color + ';flex-shrink:0"></div>'
            + '<div><div style="font-size:13px;font-weight:500">' + esc(seg.label) + '</div>'
            + '<div style="font-size:12px;color:var(--text2)">' + eur(seg.value) + ' · ' + pctVal + '%</div></div>'
            + '</div>';
  }

  const topPositions = (data.portfolio || []).slice().sort(function(a,b){ return (b.pnl_pct||0)-(a.pnl_pct||0); }).slice(0,5);
  let topRows = '';
  for (let i = 0; i < topPositions.length; i++) {
    const p = topPositions[i];
    topRows += '<div style="display:flex;justify-content:space-between;align-items:center;padding:7px 0;border-bottom:1px solid var(--border)">'
             + '<span style="font-size:13px">' + esc(p.name) + '</span>'
             + '<span class="' + cls(p.pnl_pct) + '" style="font-size:13px;font-weight:600">' + pct(p.pnl_pct) + '</span>'
             + '</div>';
  }

  let coffreRows = '';
  const coffres = data.coffres || [];
  for (let i = 0; i < coffres.length; i++) {
    const c = coffres[i];
    coffreRows += '<div style="display:flex;justify-content:space-between;align-items:center;padding:7px 0;border-bottom:1px solid var(--border)">'
               + '<span style="font-size:13px">' + esc(c.name) + '</span>'
               + '<span style="font-size:13px;font-weight:600">' + eur(c.balance) + '</span>'
               + '</div>';
  }

  document.getElementById('tab-summary').innerHTML =
    '<div style="display:flex;gap:20px;align-items:flex-start;flex-wrap:wrap;margin-bottom:24px">'
    + '<div class="card" style="flex:0 0 auto;padding:24px;display:flex;flex-direction:column;align-items:center">'
    + donut
    + '<div style="margin-top:14px;text-align:center">'
    + '<div style="font-size:24px;font-weight:700;color:var(--accent)">' + eur(s.grand_total_eur) + '</div>'
    + '<div style="font-size:11px;color:var(--text2);margin-top:3px;text-transform:uppercase;letter-spacing:.06em">Patrimoine total</div>'
    + '</div></div>'
    + '<div class="card" style="flex:1;min-width:220px">'
    + '<div class="card-label" style="margin-bottom:14px">Répartition</div>'
    + legend
    + '</div></div>'
    + '<div style="display:grid;grid-template-columns:1fr 1fr;gap:16px">'
    + '<div class="card"><div class="card-label" style="margin-bottom:14px">📈 Top positions</div>' + topRows + '</div>'
    + '<div class="card"><div class="card-label" style="margin-bottom:14px">🏦 Soldes coffres</div>' + coffreRows + '</div>'
    + '</div>';
}

// ── Portfolio ────────────────────────────────────────────────────────────
function toggleCard(card) {
  const d = card.querySelector('.card-detail');
  const ch = card.querySelector('.pos-chevron');
  if (!d) return;
  const open = d.style.display === 'block';
  d.style.display = open ? 'none' : 'block';
  if (ch) ch.style.transform = open ? '' : 'rotate(90deg)';
}

function renderPortfolio(data) {
  const portfolio = data.portfolio || [];
  const sold = data.sold_positions || [];
  const total_val = portfolio.reduce(function(s,p){ return s+(p.value_eur||0); }, 0);
  const total_inv = portfolio.reduce(function(s,p){ return s+(p.invested_eur||0); }, 0);
  const total_pnl = portfolio.reduce(function(s,p){ return s+(p.pnl_eur||0); }, 0);
  const total_rpnl = portfolio.reduce(function(s,p){ return s+(p.realized_pnl||0); }, 0);

  let cards = '';
  for (let i = 0; i < portfolio.length; i++) {
    const p = portfolio[i];
    const alloc = total_val > 0 ? ((p.value_eur||0) / total_val * 100) : 0;

    // Purchases table
    let purchasesTable = '';
    if ((p.purchases||[]).length) {
      let rows = '';
      for (let j = 0; j < p.purchases.length; j++) {
        const a = p.purchases[j];
        rows += '<tr><td class="left">' + fmtDate(a.date) + '</td>'
              + '<td>' + num(a.quantity, 4) + '</td>'
              + '<td>' + eur(a.unit_price) + '</td>'
              + '<td>' + eur(a.fees) + '</td>'
              + '<td class="left" style="color:var(--text2)">' + esc(a.note || '—') + '</td></tr>';
      }
      purchasesTable = '<div class="detail-section">'
        + '<div class="section-title">Historique d\'achats</div>'
        + '<div class="table-wrap"><table>'
        + '<thead><tr><th class="left">Date</th><th>Qté</th><th>Prix unit.</th><th>Frais</th><th class="left">Note</th></tr></thead>'
        + '<tbody>' + rows + '</tbody></table></div></div>';
    }

    // Sales table
    let salesTable = '';
    if ((p.sales||[]).length) {
      let rows = '';
      for (let j = 0; j < p.sales.length; j++) {
        const s = p.sales[j];
        rows += '<tr><td class="left">' + fmtDate(s.date) + '</td>'
              + '<td>' + num(s.quantity, 4) + '</td>'
              + '<td>' + eur(s.unit_price) + '</td>'
              + '<td>' + eur(s.fees) + '</td>'
              + '<td class="' + cls(s.realized_pnl) + '">' + eur(s.realized_pnl) + '</td></tr>';
      }
      let pnlLine = '';
      if (p.realized_pnl != null) {
        pnlLine = '<div style="margin-top:8px;font-size:12px;color:var(--text2)">'
                + 'P&amp;L réalisé : <strong class="' + cls(p.realized_pnl) + '">' + eur(p.realized_pnl) + '</strong>'
                + (p.unrealized_pnl != null ? ' &nbsp;·&nbsp; Non réalisé : <strong class="' + cls(p.unrealized_pnl) + '">' + eur(p.unrealized_pnl) + '</strong>' : '')
                + '</div>';
      }
      salesTable = '<div class="detail-section">'
        + '<div class="section-title">Ventes</div>'
        + '<div class="table-wrap"><table>'
        + '<thead><tr><th class="left">Date</th><th>Qté vendue</th><th>Prix vente</th><th>Frais</th><th>P&amp;L réalisé</th></tr></thead>'
        + '<tbody>' + rows + '</tbody></table></div>'
        + pnlLine + '</div>';
    }

    cards += '<div class="pos-card" onclick="toggleCard(this)">'
           + '<div class="pos-header">'
           + '<div class="pos-left">'
           + '<div class="pos-name-row"><span class="pos-name">' + esc(p.name) + '</span>'
           + '<span class="badge badge-' + (p.type||'action') + '">' + (TYPE_LABELS[p.type]||p.type) + '</span></div>'
           + '<div class="pos-ticker">' + esc(p.ticker) + '</div>'
           + '</div>'
           + '<span class="pos-chevron">▶</span>'
           + '</div>'
           + '<div class="pos-metrics">'
           + '<div class="metric"><span class="metric-lbl">QTÉ</span><span class="metric-val">' + num(p.quantity,4) + '</span></div>'
           + '<div class="metric"><span class="metric-lbl">PRU</span><span class="metric-val">' + eur(p.average_cost) + '</span></div>'
           + '<div class="metric"><span class="metric-lbl">Investi</span><span class="metric-val">' + eur(p.invested_eur) + '</span></div>'
           + '<div class="metric"><span class="metric-lbl">Valeur</span><span class="metric-val"><strong>' + eur(p.value_eur) + '</strong></span></div>'
           + '<div class="metric"><span class="metric-lbl">P&amp;L €</span><span class="metric-val ' + cls(p.pnl_eur) + '">' + eur(p.pnl_eur) + '</span></div>'
           + '<div class="metric"><span class="metric-lbl">P&amp;L %</span><span class="metric-val ' + cls(p.pnl_pct) + '">' + pct(p.pnl_pct) + '</span></div>'
           + '<div class="metric"><span class="metric-lbl">Alloc.</span><span class="metric-val" style="color:var(--text2)">' + alloc.toFixed(1) + '%</span></div>'
           + '</div>'
           + '<div class="alloc-bar"><div class="alloc-fill" style="width:' + alloc.toFixed(2) + '%"></div></div>'
           + '<div class="card-detail">' + purchasesTable + salesTable + '</div>'
           + '</div>';
  }

  // Sold positions section
  let soldSection = '';
  if (sold.length) {
    let soldRows = '';
    for (let i = 0; i < sold.length; i++) {
      const p = sold[i];
      soldRows += '<tr>'
               + '<td class="left"><strong>' + esc(p.name) + '</strong><br/><span style="color:var(--text2);font-size:11px">' + esc(p.ticker) + '</span></td>'
               + '<td class="left"><span class="badge badge-' + (p.type||'action') + '">' + (TYPE_LABELS[p.type]||p.type) + '</span></td>'
               + '<td class="left">' + fmtDate(p.last_sale_date) + '</td>'
               + '<td>' + eur(p.total_invested) + '</td>'
               + '<td class="' + cls(p.realized_pnl) + '"><strong>' + eur(p.realized_pnl) + '</strong></td>'
               + '</tr>';
    }
    soldSection = '<div class="card" style="margin-top:16px;padding:0;overflow:hidden">'
      + '<div onclick="var p=document.getElementById(\'soldPanel\');var ch=this.querySelector(\'.schev\');var open=p.style.display===\'block\';p.style.display=open?\'none\':\'block\';ch.style.transform=open?\'\':\'rotate(90deg)\'"'
      + ' style="padding:14px 16px;cursor:pointer;display:flex;align-items:center;justify-content:space-between;user-select:none">'
      + '<span style="font-size:13px;font-weight:500;color:var(--text2)">Positions clôturées (' + sold.length + ')</span>'
      + '<span class="schev" style="color:var(--text2);transition:transform .2s;font-size:11px">▶</span>'
      + '</div>'
      + '<div id="soldPanel" style="display:none;border-top:1px solid var(--border)">'
      + '<div class="table-wrap"><table>'
      + '<thead><tr><th class="left">Actif</th><th class="left">Type</th><th class="left">Dernière vente</th><th>Investi total</th><th>P&amp;L réalisé</th></tr></thead>'
      + '<tbody>' + soldRows + '</tbody></table></div>'
      + '</div></div>';
  }

  let kpis = '<div class="summary-grid" style="margin-bottom:20px">'
    + '<div class="card"><div class="card-label">Valeur totale</div><div class="card-value green">' + eur(total_val) + '</div></div>'
    + '<div class="card"><div class="card-label">Investi (résiduel)</div><div class="card-value">' + eur(total_inv) + '</div></div>'
    + '<div class="card"><div class="card-label">P&amp;L total</div><div class="card-value ' + cls(total_pnl) + '">' + eur(total_pnl) + '</div></div>'
    + (total_rpnl ? '<div class="card"><div class="card-label">P&amp;L réalisé</div><div class="card-value ' + cls(total_rpnl) + '">' + eur(total_rpnl) + '</div></div>' : '')
    + '</div>';

  document.getElementById('tab-portfolio').innerHTML = kpis + cards + soldSection;
}

// ── Coffres ──────────────────────────────────────────────────────────────
function toggleCombo(id, code) {
  const el = document.getElementById('combo-' + id);
  const btn = document.getElementById('combobtn-' + id);
  if (!el || !btn) return;
  if (el.dataset.revealed === '1') {
    el.textContent = '●●●●●●';
    el.style.color = 'var(--text2)';
    el.dataset.revealed = '0';
    btn.textContent = 'Révéler';
  } else {
    el.textContent = code;
    el.style.color = 'var(--yellow)';
    el.dataset.revealed = '1';
    btn.textContent = 'Masquer';
  }
}

function renderCoffres(data) {
  const total = (data.coffres || []).reduce(function(s,c){ return s+c.balance; }, 0);
  let cards = '';
  const coffres = data.coffres || [];

  for (let i = 0; i < coffres.length; i++) {
    const c = coffres[i];
    // Combination section
    let comboBlock = '';
    if (c.combination || c.combination_hint) {
      comboBlock = '<div style="margin-top:14px;border-top:1px solid var(--border);padding-top:12px">'
        + '<div style="font-size:10px;color:var(--text2);text-transform:uppercase;letter-spacing:.08em;margin-bottom:8px">🔑 Code d\'accès</div>'
        + (c.combination_hint ? '<div style="font-size:11px;color:var(--text2);margin-bottom:6px">Indice : ' + esc(c.combination_hint) + '</div>' : '')
        + (c.combination
          ? '<div style="display:flex;align-items:center;gap:10px">'
            + '<div style="font-family:monospace;font-size:16px;letter-spacing:.2em;color:var(--text2)" id="combo-' + c.id + '">●●●●●●</div>'
            + '<button onclick="toggleCombo(\'' + c.id + '\',\'' + esc(c.combination) + '\')" '
            + 'style="background:var(--bg3);border:1px solid var(--border);border-radius:6px;padding:4px 10px;font-size:11px;color:var(--text2);cursor:pointer" '
            + 'id="combobtn-' + c.id + '">Révéler</button></div>'
          : '<div style="font-size:12px;color:var(--text2);font-style:italic">Indice uniquement</div>')
        + '</div>';
    }

    // Movements section
    let movBlock = '';
    const movs = c.movements || [];
    if (movs.length) {
      let movRows = '';
      for (let j = 0; j < movs.length; j++) {
        const mv = movs[j];
        const isEntry = mv.type === 'ENTRY';
        movRows += '<tr>'
                 + '<td class="left">' + fmtDate(mv.date) + '</td>'
                 + '<td class="left"><span style="color:' + (isEntry ? 'var(--green)' : 'var(--red)') + ';font-weight:500">'
                 + (isEntry ? 'ENTRÉE' : 'SORTIE') + '</span></td>'
                 + '<td class="' + (isEntry ? 'pos' : 'neg') + '">' + eur(mv.amount) + '</td>'
                 + '<td class="left" style="color:var(--text2)">' + esc(mv.description || '—') + '</td>'
                 + '</tr>';
      }
      movBlock = '<div style="margin-top:16px;border-top:1px solid var(--border);padding-top:14px">'
               + '<div class="section-title">Derniers mouvements</div>'
               + '<div class="table-wrap"><table style="font-size:12px">'
               + '<thead><tr><th class="left">Date</th><th class="left">Type</th><th>Montant</th><th class="left">Description</th></tr></thead>'
               + '<tbody>' + movRows + '</tbody></table></div></div>';
    } else {
      movBlock = '<div style="margin-top:14px;font-size:12px;color:var(--text2)">Aucun mouvement récent.</div>';
    }

    cards += '<div class="card">'
           + '<div class="card-label">🏦 ' + esc(c.name) + '</div>'
           + '<div class="card-value yellow">' + eur(c.balance) + '</div>'
           + comboBlock
           + movBlock
           + '</div>';
  }

  document.getElementById('tab-coffres').innerHTML =
    '<div class="summary-grid" style="margin-bottom:24px">'
    + '<div class="card"><div class="card-label">Total liquidités</div><div class="card-value yellow">' + eur(total) + '</div></div>'
    + '</div>'
    + '<div style="display:grid;grid-template-columns:repeat(auto-fill,minmax(340px,1fr));gap:16px">' + cards + '</div>'
    + '<div class="card" style="margin-top:16px;padding:14px 16px">'
    + '<p style="color:var(--text2);font-size:13px">Les soldes et codes affichés correspondent à l\'état au moment de l\'export.</p>'
    + '</div>';
}

// ── Assets ───────────────────────────────────────────────────────────────
function renderAssets(data) {
  const coffreMap = {};
  (data.coffres||[]).forEach(function(c){ coffreMap[c.id] = c.name; });
  const total = (data.assets||[]).reduce(function(s,a){ return s+(a.estimated_value||0); }, 0);
  const DOC_LABELS = {facture:'🧾 Facture',carte_grise:'📋 Carte grise',assurance:'🛡 Assurance',controle_technique:'🔧 CT',certificat:'📜 Certificat',photo:'📷 Photo',autre:'📄 Autre'};

  let rows = '';
  const assets = data.assets || [];
  for (let i = 0; i < assets.length; i++) {
    const a = assets[i];
    const vInfo = a.category==='vehicule' && (a.vehicle_make||a.vehicle_model)
      ? [a.vehicle_make,a.vehicle_model,a.vehicle_year].filter(Boolean).join(' ') : '';

    let vehicleBlock = '';
    if (a.category==='vehicule') {
      vehicleBlock = '<div class="v-grid">'
        + (a.vehicle_make?'<div class="v-field"><div class="v-label">Marque</div><div class="v-val">'+esc(a.vehicle_make)+'</div></div>':'')
        + (a.vehicle_model?'<div class="v-field"><div class="v-label">Modèle</div><div class="v-val">'+esc(a.vehicle_model)+'</div></div>':'')
        + (a.vehicle_year?'<div class="v-field"><div class="v-label">Année</div><div class="v-val">'+a.vehicle_year+'</div></div>':'')
        + (a.vehicle_fuel?'<div class="v-field"><div class="v-label">Carburant</div><div class="v-val">'+esc(a.vehicle_fuel)+'</div></div>':'')
        + (a.vehicle_plate?'<div class="v-field"><div class="v-label">Immatriculation</div><div class="v-val">'+esc(a.vehicle_plate)+'</div></div>':'')
        + (a.vehicle_km!=null?'<div class="v-field"><div class="v-label">Kilométrage</div><div class="v-val">'+num(a.vehicle_km)+' km</div></div>':'')
        + (a.vehicle_vin?'<div class="v-field" style="grid-column:1/-1"><div class="v-label">VIN</div><div class="v-val">'+esc(a.vehicle_vin)+'</div></div>':'')
        + '</div>';
    }

    let docsBlock = '';
    if ((a.documents||[]).length) {
      let docCards = '';
      for (let j = 0; j < a.documents.length; j++) {
        const d = a.documents[j];
        docCards += '<div style="background:var(--bg3);border:1px solid var(--border);border-radius:8px;padding:10px 12px;display:flex;align-items:center;gap:10px;min-width:200px">'
                  + '<span style="font-size:20px">📄</span>'
                  + '<div style="flex:1;min-width:0">'
                  + '<div style="font-size:12px;font-weight:600;white-space:nowrap;overflow:hidden;text-overflow:ellipsis">' + esc(d.filename) + '</div>'
                  + '<div style="font-size:11px;color:var(--text2);margin-top:2px">' + (DOC_LABELS[d.document_type]||d.document_type||'—') + ' · ' + fmtSize(d.size_bytes) + ' · ' + fmtDate(d.created_at) + '</div>'
                  + (d.notes?'<div style="font-size:11px;color:var(--text2);font-style:italic">'+esc(d.notes)+'</div>':'')
                  + '</div>'
                  + '<button onclick="downloadFile(\''+esc(d.doc_key)+'\',\''+esc(d.filename)+'\',\''+esc(d.mime_type)+'\')" '
                  + 'style="background:var(--accent);color:#fff;border:none;border-radius:6px;padding:6px 10px;font-size:12px;cursor:pointer;white-space:nowrap;flex-shrink:0">⬇ Télécharger</button>'
                  + '</div>';
      }
      docsBlock = '<div style="margin-top:10px"><div class="section-title">Documents (' + a.documents.length + ')</div>'
               + '<div style="display:flex;flex-wrap:wrap;gap:8px">' + docCards + '</div></div>';
    }

    let eventsBlock = '';
    if ((a.events||[]).length) {
      let evRows = '';
      for (let j = 0; j < a.events.length; j++) {
        const e = a.events[j];
        evRows += '<tr><td class="left">'+fmtDate(e.date)+'</td><td class="left">'+e.type+'</td><td>'+eur(e.amount)+'</td><td class="left" style="color:var(--text2)">'+esc(e.notes||'—')+'</td></tr>';
      }
      eventsBlock = '<div style="margin-top:10px"><div class="section-title">Événements</div>'
                 + '<table style="font-size:12px"><thead><tr><th class="left">Date</th><th class="left">Type</th><th>Montant</th><th class="left">Note</th></tr></thead>'
                 + '<tbody>' + evRows + '</tbody></table></div>';
    }

    const locStr = a.location || (a.coffre_id ? (coffreMap[a.coffre_id]||'Coffre') : '—');

    rows += '<tr class="asset-row" onclick="toggleAssetRow(this)" style="cursor:pointer">'
          + '<td class="left"><strong>' + (CAT_ICONS[a.category]||'📦') + ' ' + esc(a.name) + '</strong>'
          + (vInfo?'<br/><span style="color:var(--text2);font-size:11px">'+esc(vInfo)+'</span>':'') + '</td>'
          + '<td class="left"><span class="badge badge-'+(a.category||'autre')+'">'+(CAT_LABELS[a.category||'autre']||a.category)+'</span></td>'
          + '<td class="left" style="color:var(--text2)">' + esc(locStr) + '</td>'
          + '<td><strong>' + eur(a.estimated_value) + '</strong></td>'
          + '<td style="color:var(--text2)">' + (a.documents||[]).length + '</td>'
          + '<td style="width:28px;text-align:center"><span class="asset-chevron">▶</span></td>'
          + '</tr>'
          + '<tr class="expand-row" style="display:table-row"><td colspan="6">'
          + '<div class="expand-content" style="max-height:0;overflow:hidden;transition:.3s">'
          + vehicleBlock + eventsBlock + docsBlock + '</div></td></tr>';
  }

  document.getElementById('tab-assets').innerHTML =
    '<div class="summary-grid" style="margin-bottom:24px">'
    + '<div class="card"><div class="card-label">Valeur totale</div><div class="card-value purple">' + eur(total) + '</div></div>'
    + '</div>'
    + '<div class="card" style="padding:0"><div class="table-wrap"><table>'
    + '<thead><tr><th class="left">Actif</th><th class="left">Catégorie</th><th class="left">Localisation</th><th>Valeur estimée</th><th>Docs</th><th></th></tr></thead>'
    + '<tbody>' + rows + '</tbody></table></div></div>';

  document.querySelectorAll('#tab-assets .expand-content').forEach(function(el) {
    const observer = new MutationObserver(function() {
      el.style.maxHeight = el.classList.contains('open') ? el.scrollHeight + 'px' : '0';
    });
    observer.observe(el, {attributes:true,attributeFilter:['class']});
  });
}

function toggleAssetRow(tr) {
  tr.classList.toggle('open');
  var ec = tr.nextElementSibling.querySelector('.expand-content');
  if (ec) ec.classList.toggle('open');
}

// ── Reserves ─────────────────────────────────────────────────────────────
function renderReserves(data) {
  const reserves = data.reserves || [];
  const rs = (data.summary && data.summary.reserves_stats) || {};
  const yearsSet = {};
  reserves.forEach(function(r){ yearsSet[r.year]=true; });
  const years = Object.keys(yearsSet).map(Number).sort(function(a,b){return b-a;});

  const byYear = {};
  reserves.forEach(function(r) {
    if (!byYear[r.year]) byYear[r.year] = {amount:0,released:0,precompte_paye:0,net_recu:0,releasable:0,notes:r.notes};
    const y = byYear[r.year];
    y.amount         += r.amount         || 0;
    y.released       += r.released       || 0;
    y.precompte_paye += r.precompte_paye || 0;
    y.net_recu       += r.net_recu       || 0;
    y.releasable     += r.releasable     || 0;
  });

  let rows = '';
  for (let i = 0; i < years.length; i++) {
    const yr = years[i];
    const y = byYear[yr];
    rows += '<tr>'
          + '<td class="left" style="font-weight:600">' + yr + '</td>'
          + '<td>' + eur(y.amount) + '</td>'
          + '<td>' + eur(y.released) + '</td>'
          + '<td style="color:var(--text2)">' + eur(y.precompte_paye) + '</td>'
          + '<td class="' + (y.net_recu>0?'pos':'') + '">' + eur(y.net_recu) + '</td>'
          + '<td class="' + (y.releasable>0?'pos':'') + '">' + eur(y.releasable) + '</td>'
          + '<td class="left" style="color:var(--text2)">' + esc(y.notes||'—') + '</td>'
          + '</tr>';
  }

  document.getElementById('tab-reserves').innerHTML =
    '<div class="summary-grid" style="margin-bottom:24px">'
    + '<div class="card"><div class="card-label">Total constitué</div><div class="card-value blue">' + eur(rs.total_amount||0) + '</div></div>'
    + '<div class="card"><div class="card-label">Encore libérable</div><div class="card-value yellow">' + eur(rs.total_releasable||0) + '</div></div>'
    + '<div class="card"><div class="card-label">Libéré (brut)</div><div class="card-value green">' + eur(rs.total_released||0) + '</div></div>'
    + '<div class="card"><div class="card-label">Net reçu total</div><div class="card-value green">' + eur(rs.total_net_recu||0) + '</div>'
    + '<div style="font-size:11px;color:var(--text2);margin-top:2px">après précompte ' + eur(rs.total_precompte||0) + '</div></div>'
    + '</div>'
    + '<div class="card" style="padding:0"><div class="table-wrap"><table>'
    + '<thead><tr><th class="left">Année</th><th>Montant constitué</th><th>Libéré (brut)</th><th>Précompte payé</th><th>Net reçu</th><th>Encore libérable</th><th class="left">Note</th></tr></thead>'
    + '<tbody>' + (rows || '<tr><td colspan="7" style="text-align:center;padding:24px;color:var(--text2)">Aucune réserve</td></tr>') + '</tbody>'
    + '</table></div></div>';
}

// ── Vault ─────────────────────────────────────────────────────────────────
function renderVault(data) {
  const files = data.vault || [];
  const EXT_ICONS = {pdf:'📕',jpg:'🖼',jpeg:'🖼',png:'🖼',webp:'🖼',csv:'📊',json:'📋',zip:'🗜',txt:'📝',doc:'📄',docx:'📄',xls:'📊',xlsx:'📊'};
  function getIcon(f) { const ext = f.split('.').pop().toLowerCase(); return EXT_ICONS[ext] || '📄'; }

  if (!files.length) {
    document.getElementById('tab-vault').innerHTML =
      '<div class="card" style="padding:40px;text-align:center">'
      + '<div style="font-size:40px;margin-bottom:12px">🔐</div>'
      + '<div style="color:var(--text2);font-size:14px">Aucun fichier dans le coffre au moment de l\'export.</div>'
      + '</div>';
    return;
  }

  let cards = '';
  for (let i = 0; i < files.length; i++) {
    const f = files[i];
    cards += '<div class="card" style="display:flex;align-items:center;gap:16px;padding:16px">'
           + '<span style="font-size:32px;flex-shrink:0">' + getIcon(f.filename) + '</span>'
           + '<div style="flex:1;min-width:0">'
           + '<div style="font-size:14px;font-weight:600;margin-bottom:4px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis">' + esc(f.filename) + '</div>'
           + '<div style="font-size:12px;color:var(--text2)">' + fmtSize(f.size_bytes) + ' · Ajouté le ' + fmtDate(f.created_at) + '</div>'
           + '</div>'
           + '<button onclick="downloadFile(\'' + esc(f.doc_key) + '\',\'' + esc(f.filename) + '\',\'' + esc(f.mime_type) + '\')" '
           + 'style="background:var(--accent);color:#fff;border:none;border-radius:8px;padding:10px 16px;font-size:13px;font-weight:500;cursor:pointer;flex-shrink:0;display:flex;align-items:center;gap:6px">'
           + '⬇ Télécharger</button></div>';
  }

  document.getElementById('tab-vault').innerHTML =
    '<div class="summary-grid" style="margin-bottom:24px">'
    + '<div class="card"><div class="card-label">🔐 Fichiers chiffrés</div>'
    + '<div class="card-value">' + files.length + '</div>'
    + '<div style="font-size:12px;color:var(--text2);margin-top:4px">Total : ' + fmtSize(files.reduce(function(s,f){return s+f.size_bytes;},0)) + '</div></div>'
    + '</div>'
    + '<div style="display:flex;flex-direction:column;gap:10px">' + cards + '</div>';
}
</script>
<!-- Bloc 2 : injection des données — séparé pour éviter les erreurs de parsing Safari -->
<script>
BLOB = "__BLOB__";
DOC_BLOBS = __DOC_BLOBS__;
ITERATIONS = __ITERATIONS__;
document.getElementById('exportDateDisplay').textContent = "__EXPORTED_AT__";
document.getElementById('passInput').addEventListener('keydown', function(e) {
  if (e.key === 'Enter') unlock();
});
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
