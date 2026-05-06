"""Export router: génère un fichier HTML autonome chiffré pour clé USB."""
import base64 as b64_stdlib
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
from models import Coffre, PasswordFile, PhysicalAsset, Position, Reserve, User
from routers.coffres import compute_balance
from calculations import calc_position_metrics

router = APIRouter(prefix="/api/export", tags=["export"])

PBKDF2_ITERATIONS = 600_000


class ExportRequest(BaseModel):
    passphrase: str


# ── Encryption ────────────────────────────────────────────

def _encrypt_blob(data: bytes, passphrase: str) -> str:
    salt = os.urandom(32)
    kdf = PBKDF2HMAC(algorithm=hashes.SHA256(), length=32, salt=salt, iterations=PBKDF2_ITERATIONS)
    key = kdf.derive(passphrase.encode("utf-8"))
    nonce = os.urandom(12)
    ciphertext = AESGCM(key).encrypt(nonce, data, None)
    return b64_stdlib.b64encode(salt + nonce + ciphertext).decode()


# ── Data collection ───────────────────────────────────────

def _collect_data(db: Session, user: User) -> dict:
    # Portfolio
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
        purchases = [
            {
                "date": str(p.purchase_date),
                "quantity": p.quantity,
                "unit_price": p.unit_price,
                "fees": p.fees,
                "note": p.note,
            }
            for p in pos.purchases
        ]
        portfolio_items.append({
            "name": pos.display_name,
            "ticker": pos.ticker,
            "type": pos.asset_type,
            "currency": pos.currency,
            "current_price_eur": price_eur,
            "quantity": m.get("total_quantity"),
            "invested_eur": m.get("total_invested"),
            "value_eur": m.get("current_value"),
            "pnl_eur": m.get("pnl_eur"),
            "pnl_pct": m.get("pnl_pct"),
            "purchases": purchases,
        })

    # Coffres
    coffres_data = []
    for c in db.query(Coffre).filter(Coffre.is_active == True).all():  # noqa: E712
        balance = compute_balance(c.id, db)
        coffres_data.append({"id": c.id, "name": c.name, "balance": balance})

    # Actifs physiques
    assets_data = []
    for a in db.query(PhysicalAsset).all():
        assets_data.append({
            "name": a.name,
            "category": a.category,
            "description": a.description,
            "estimated_value": a.estimated_value,
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
                {
                    "filename": d.filename,
                    "document_type": d.document_type,
                    "notes": d.notes,
                    "size_bytes": d.size_bytes,
                    "mime_type": d.mime_type,
                    "created_at": str(d.created_at),
                    # Contenu déchiffré en base64 pour téléchargement offline
                    "data_b64": b64_stdlib.b64encode(enc.decrypt(d.encrypted_data)).decode(),
                }
                for d in a.documents
            ],
        })

    # Coffre de fichiers (vault)
    vault_data = []
    for f in db.query(PasswordFile).filter(PasswordFile.user_id == user.id).all():
        vault_data.append({
            "filename": f.filename,
            "mime_type": f.mime_type,
            "size_bytes": f.size_bytes,
            "created_at": str(f.created_at),
            "data_b64": b64_stdlib.b64encode(enc.decrypt(f.encrypted_data)).decode(),
        })

    # Réserves
    reserves_data = []
    for r in db.query(Reserve).filter(Reserve.user_id == user.id).all():
        reserves_data.append({
            "year": r.year, "month": r.month, "amount": r.amount,
            "release_year": r.release_year, "released": r.released, "notes": r.notes,
        })

    # Totaux
    total_portfolio = sum(p["value_eur"] or 0 for p in portfolio_items)
    total_cash = sum(c["balance"] for c in coffres_data)
    total_assets = sum((a["estimated_value"] or 0) for a in assets_data)

    return {
        "meta": {
            "exported_at": datetime.now(timezone.utc).isoformat(),
            "owner_name": user.name,
            "owner_email": user.email,
        },
        "summary": {
            "total_portfolio_eur": total_portfolio,
            "total_cash_eur": total_cash,
            "total_assets_eur": total_assets,
            "grand_total_eur": total_portfolio + total_cash + total_assets,
        },
        "portfolio": portfolio_items,
        "coffres": coffres_data,
        "assets": assets_data,
        "vault": vault_data,
        "reserves": reserves_data,
    }


# ── HTML template ─────────────────────────────────────────

def _build_html(encrypted_blob: str, exported_at: str, iterations: int) -> str:
    return f"""<!DOCTYPE html>
<html lang="fr">
<head>
<meta charset="UTF-8"/>
<meta name="viewport" content="width=device-width,initial-scale=1"/>
<title>Patrimonium — Export patrimoine</title>
<style>
*{{box-sizing:border-box;margin:0;padding:0}}
:root{{--bg:#0A0B0E;--bg2:#13141A;--bg3:#1C1E27;--border:#2A2D3A;--text:#E8EAF0;--text2:#8B90A0;--accent:#3B82F6;--green:#00D68F;--red:#FF4757;--yellow:#F59E0B;--purple:#a855f7;--teal:#14b8a6;--radius:10px;--font:'Segoe UI',system-ui,sans-serif}}
body{{background:var(--bg);color:var(--text);font-family:var(--font);min-height:100vh;display:flex;flex-direction:column}}
h1,h2,h3{{font-weight:600}}
/* Lock screen */
#lockScreen{{flex:1;display:flex;align-items:center;justify-content:center;padding:24px}}
.lock-card{{background:var(--bg2);border:1px solid var(--border);border-radius:16px;padding:40px;width:100%;max-width:420px;text-align:center}}
.lock-icon{{font-size:48px;margin-bottom:16px}}
.lock-title{{font-size:22px;font-weight:700;margin-bottom:6px}}
.lock-sub{{color:var(--text2);font-size:13px;margin-bottom:28px}}
.lock-sub span{{color:var(--text);font-weight:500}}
.form-input{{width:100%;background:var(--bg3);border:1px solid var(--border);border-radius:var(--radius);color:var(--text);padding:11px 14px;font-size:15px;outline:none;margin-bottom:12px;font-family:inherit}}
.form-input:focus{{border-color:var(--accent)}}
.btn{{display:inline-flex;align-items:center;justify-content:center;gap:6px;padding:11px 20px;border-radius:var(--radius);font-size:14px;font-weight:500;border:none;cursor:pointer;transition:.15s}}
.btn-primary{{background:var(--accent);color:#fff;width:100%}}
.btn-primary:hover{{filter:brightness(1.1)}}
.err{{color:var(--red);font-size:13px;margin-top:10px;min-height:20px}}
/* App */
#app{{display:none;flex-direction:column;min-height:100vh}}
header{{background:var(--bg2);border-bottom:1px solid var(--border);padding:0 24px;position:sticky;top:0;z-index:100}}
.header-inner{{display:flex;align-items:center;justify-content:space-between;height:56px;max-width:1200px;margin:0 auto}}
.logo{{font-size:18px;font-weight:700;display:flex;align-items:center;gap:8px}}
.logo-icon{{color:var(--accent)}}
.badge-ro{{background:rgba(255,71,87,.15);color:var(--red);border:1px solid rgba(255,71,87,.3);border-radius:20px;padding:3px 10px;font-size:11px;font-weight:600}}
.export-date{{color:var(--text2);font-size:12px}}
main{{flex:1;padding:24px;max-width:1200px;margin:0 auto;width:100%}}
/* Tabs */
.tabs{{display:flex;gap:4px;background:var(--bg2);border:1px solid var(--border);border-radius:var(--radius);padding:4px;margin-bottom:24px;flex-wrap:wrap}}
.tab-btn{{padding:8px 16px;border-radius:7px;border:none;background:transparent;color:var(--text2);font-size:13px;font-weight:500;cursor:pointer;transition:.15s;font-family:inherit}}
.tab-btn.active{{background:var(--bg3);color:var(--text)}}
.tab-panel{{display:none}}.tab-panel.active{{display:block}}
/* Cards */
.summary-grid{{display:grid;grid-template-columns:repeat(auto-fill,minmax(200px,1fr));gap:16px;margin-bottom:28px}}
.card{{background:var(--bg2);border:1px solid var(--border);border-radius:var(--radius);padding:20px}}
.card-label{{font-size:11px;color:var(--text2);text-transform:uppercase;letter-spacing:.08em;margin-bottom:6px}}
.card-value{{font-size:24px;font-weight:700}}
.blue{{color:var(--accent)}}.green{{color:var(--green)}}.yellow{{color:var(--yellow)}}.purple{{color:var(--purple)}}
/* Table */
.table-wrap{{overflow-x:auto}}
table{{width:100%;border-collapse:collapse;font-size:13px}}
thead tr{{border-bottom:1px solid var(--border)}}
th{{padding:10px 12px;color:var(--text2);font-weight:500;font-size:11px;text-transform:uppercase;letter-spacing:.06em;white-space:nowrap}}
th.left,td.left{{text-align:left}}
th:not(.left){{text-align:right}}
td{{padding:10px 12px;border-bottom:1px solid var(--border);color:var(--text);white-space:nowrap}}
td:not(.left){{text-align:right}}
tr:last-child td{{border-bottom:none}}
tr:hover td{{background:var(--bg3)}}
.pos{{color:var(--green)}}.neg{{color:var(--red)}}
/* Badges */
.badge{{display:inline-flex;align-items:center;padding:2px 8px;border-radius:20px;font-size:11px;font-weight:500}}
.badge-action{{background:rgba(59,130,246,.15);color:var(--accent)}}
.badge-etf{{background:rgba(0,214,143,.15);color:var(--green)}}
.badge-commodity{{background:rgba(245,158,11,.15);color:var(--yellow)}}
.badge-bond_manual{{background:rgba(168,85,247,.15);color:var(--purple)}}
.badge-bijou{{background:rgba(168,85,247,.15);color:var(--purple)}}
.badge-immo{{background:rgba(59,130,246,.15);color:var(--accent)}}
.badge-vehicule{{background:rgba(20,184,166,.15);color:var(--teal)}}
.badge-art{{background:rgba(245,158,11,.15);color:var(--yellow)}}
.badge-metal{{background:rgba(209,162,68,.15);color:#c9a227}}
.badge-autre{{background:rgba(139,144,160,.15);color:var(--text2)}}
/* Vehicle card */
.v-grid{{display:grid;grid-template-columns:repeat(auto-fill,minmax(150px,1fr));gap:10px;margin:12px 0}}
.v-field{{background:var(--bg3);border:1px solid var(--border);border-radius:8px;padding:8px 10px}}
.v-label{{font-size:10px;color:var(--text2);margin-bottom:2px}}
.v-val{{font-size:13px;font-weight:500}}
/* Expand */
.expand-row{{background:var(--bg2)}}
.expand-content{{padding:16px;font-size:12px;color:var(--text2)}}
.section-title{{font-size:11px;font-weight:600;text-transform:uppercase;letter-spacing:.08em;color:var(--text2);margin-bottom:10px}}
/* Reserves */
.yr-block{{margin-bottom:20px}}
.yr-title{{font-size:14px;font-weight:600;margin-bottom:10px;color:var(--text)}}
/* Footer */
footer{{padding:16px 24px;text-align:center;color:var(--text2);font-size:11px;border-top:1px solid var(--border)}}
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
const BLOB = "{encrypted_blob}";
const ITERATIONS = {iterations};

function b64ToBytes(b64) {{
  const bin = atob(b64);
  const bytes = new Uint8Array(bin.length);
  for (let i = 0; i < bin.length; i++) bytes[i] = bin.charCodeAt(i);
  return bytes;
}}

function downloadFile(filename, mimeType, b64data) {{
  const bytes = b64ToBytes(b64data);
  const blob = new Blob([bytes], {{ type: mimeType || 'application/octet-stream' }});
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url; a.download = filename;
  document.body.appendChild(a); a.click();
  document.body.removeChild(a);
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}}

document.getElementById('exportDateDisplay').textContent = "{exported_at}";
document.getElementById('passInput').addEventListener('keydown', e => {{ if (e.key === 'Enter') unlock(); }});

async function unlock() {{
  const pass = document.getElementById('passInput').value;
  const errEl = document.getElementById('errMsg');
  if (!pass) {{ errEl.textContent = 'Entrez la passphrase.'; return; }}
  errEl.textContent = 'Déchiffrement…';
  try {{
    const blob = b64ToBytes(BLOB);
    const salt = blob.slice(0, 32);
    const nonce = blob.slice(32, 44);
    const ct = blob.slice(44);
    const keyMat = await crypto.subtle.importKey('raw', new TextEncoder().encode(pass), 'PBKDF2', false, ['deriveKey']);
    const key = await crypto.subtle.deriveKey(
      {{ name: 'PBKDF2', salt, iterations: ITERATIONS, hash: 'SHA-256' }},
      keyMat, {{ name: 'AES-GCM', length: 256 }}, false, ['decrypt']
    );
    const plain = await crypto.subtle.decrypt({{ name: 'AES-GCM', iv: nonce }}, key, ct);
    const data = JSON.parse(new TextDecoder().decode(plain));
    document.getElementById('lockScreen').style.display = 'none';
    document.getElementById('app').style.display = 'flex';
    renderAll(data);
  }} catch(e) {{
    errEl.textContent = 'Passphrase incorrecte ou fichier corrompu.';
  }}
}}

function showTab(id, btn) {{
  document.querySelectorAll('.tab-panel').forEach(p => p.classList.remove('active'));
  document.querySelectorAll('.tab-btn').forEach(b => b.classList.remove('active'));
  document.getElementById('tab-' + id).classList.add('active');
  if (btn) btn.classList.add('active');
}}

function fmtSize(b) {{
  if (!b) return '—';
  if (b>=1048576) return (b/1048576).toFixed(1)+' MB';
  if (b>=1024) return (b/1024).toFixed(0)+' KB';
  return b+' B';
}}

function eur(v, d=2) {{
  if (v == null) return '—';
  return new Intl.NumberFormat('fr-BE', {{style:'currency',currency:'EUR',minimumFractionDigits:d,maximumFractionDigits:d}}).format(v);
}}
function num(v, d=0) {{
  if (v == null) return '—';
  return new Intl.NumberFormat('fr-BE', {{minimumFractionDigits:d,maximumFractionDigits:d}}).format(v);
}}
function pct(v) {{ return v == null ? '—' : (v >= 0 ? '+' : '') + v.toFixed(2) + '%'; }}
function cls(v) {{ return v == null ? '' : v >= 0 ? 'pos' : 'neg'; }}
function esc(s) {{ if (!s) return ''; return String(s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;'); }}
function fmtDate(iso) {{
  if (!iso) return '—';
  const d = new Date(iso.includes('T') ? iso : iso + 'T00:00:00');
  return d.toLocaleDateString('fr-BE', {{day:'2-digit',month:'2-digit',year:'numeric'}});
}}

const CAT_LABELS = {{bijou:'Bijou',immo:'Immobilier',vehicule:'Véhicule',art:'Art',metal:'Métaux précieux',autre:'Autre'}};
const CAT_ICONS  = {{bijou:'💎',immo:'🏠',vehicule:'🚗',art:'🎨',metal:'🪙',autre:'📦'}};
const TYPE_LABELS = {{action:'Action',etf:'ETF',commodity:'Or',bond_manual:'Obligation'}};

function renderAll(data) {{
  document.getElementById('headerDate').textContent = 'Export du ' + fmtDate(data.meta.exported_at);
  document.getElementById('footerInfo').textContent =
    'Propriétaire : ' + data.meta.owner_name + ' (' + data.meta.owner_email + ') · Export du ' + fmtDate(data.meta.exported_at) + ' · Patrimonium';

  renderSummary(data);
  renderPortfolio(data);
  renderCoffres(data);
  renderAssets(data);
  renderReserves(data);
  renderVault(data);
}}

function renderSummary(data) {{
  const s = data.summary;
  const coffreMap = Object.fromEntries((data.coffres||[]).map(c => [c.id, c.name]));
  document.getElementById('tab-summary').innerHTML = `
    <div class="summary-grid">
      <div class="card"><div class="card-label">Patrimoine total</div><div class="card-value blue">${{eur(s.grand_total_eur)}}</div></div>
      <div class="card"><div class="card-label">📈 Portefeuille</div><div class="card-value green">${{eur(s.total_portfolio_eur)}}</div></div>
      <div class="card"><div class="card-label">🏦 Liquidités</div><div class="card-value yellow">${{eur(s.total_cash_eur)}}</div></div>
      <div class="card"><div class="card-label">💎 Actifs physiques</div><div class="card-value purple">${{eur(s.total_assets_eur)}}</div></div>
    </div>
    <div style="display:grid;grid-template-columns:1fr 1fr;gap:16px">
      <div class="card">
        <div class="card-label" style="margin-bottom:14px">📈 Top positions</div>
        ${{(data.portfolio||[]).sort((a,b)=>(b.pnl_pct||0)-(a.pnl_pct||0)).slice(0,5).map(p=>`
        <div style="display:flex;justify-content:space-between;align-items:center;padding:6px 0;border-bottom:1px solid var(--border)">
          <span style="font-size:13px">${{esc(p.name)}}</span>
          <span class="${{cls(p.pnl_pct)}}" style="font-size:13px;font-weight:500">${{pct(p.pnl_pct)}}</span>
        </div>`).join('')}}
      </div>
      <div class="card">
        <div class="card-label" style="margin-bottom:14px">🏦 Soldes coffres</div>
        ${{(data.coffres||[]).map(c=>`
        <div style="display:flex;justify-content:space-between;align-items:center;padding:6px 0;border-bottom:1px solid var(--border)">
          <span style="font-size:13px">${{esc(c.name)}}</span>
          <span style="font-size:13px;font-weight:500">${{eur(c.balance)}}</span>
        </div>`).join('')}}
      </div>
    </div>`;
}}

function renderPortfolio(data) {{
  const rows = (data.portfolio||[]).map(p => `
    <tr>
      <td class="left"><strong>${{esc(p.name)}}</strong><br/><span style="color:var(--text2);font-size:11px">${{esc(p.ticker)}}</span></td>
      <td class="left"><span class="badge badge-${{p.type}}">${{TYPE_LABELS[p.type]||p.type}}</span></td>
      <td>${{num(p.quantity,4)}}</td>
      <td>${{eur(p.current_price_eur)}}</td>
      <td>${{eur(p.invested_eur)}}</td>
      <td><strong>${{eur(p.value_eur)}}</strong></td>
      <td class="${{cls(p.pnl_eur)}}">${{eur(p.pnl_eur)}}</td>
      <td class="${{cls(p.pnl_pct)}}">${{pct(p.pnl_pct)}}</td>
    </tr>
    <tr class="expand-row"><td colspan="8"><div class="expand-content">
      <div class="section-title">Historique d'achats</div>
      <table><thead><tr><th class="left">Date</th><th>Qté</th><th>Prix unit.</th><th>Frais</th><th class="left">Note</th></tr></thead><tbody>
        ${{(p.purchases||[]).map(a=>`<tr><td class="left">${{fmtDate(a.date)}}</td><td>${{num(a.quantity,4)}}</td><td>${{eur(a.unit_price)}}</td><td>${{eur(a.fees)}}</td><td class="left" style="color:var(--text2)">${{esc(a.note||'—')}}</td></tr>`).join('')}}
      </tbody></table>
    </div></td></tr>`).join('');

  const total_val = (data.portfolio||[]).reduce((s,p)=>s+(p.value_eur||0),0);
  const total_inv = (data.portfolio||[]).reduce((s,p)=>s+(p.invested_eur||0),0);
  const total_pnl = total_val - total_inv;

  document.getElementById('tab-portfolio').innerHTML = `
    <div class="summary-grid" style="margin-bottom:24px">
      <div class="card"><div class="card-label">Valeur totale</div><div class="card-value green">${{eur(total_val)}}</div></div>
      <div class="card"><div class="card-label">Investi</div><div class="card-value">${{eur(total_inv)}}</div></div>
      <div class="card"><div class="card-label">P&L total</div><div class="card-value ${{cls(total_pnl)}}">${{eur(total_pnl)}}</div></div>
    </div>
    <div class="card" style="padding:0"><div class="table-wrap"><table>
      <thead><tr><th class="left">Valeur</th><th class="left">Type</th><th>Quantité</th><th>Prix actuel</th><th>Investi</th><th>Valeur</th><th>P&L €</th><th>P&L %</th></tr></thead>
      <tbody>${{rows}}</tbody>
    </table></div></div>`;
}}

function renderCoffres(data) {{
  const total = (data.coffres||[]).reduce((s,c)=>s+c.balance,0);
  const cards = (data.coffres||[]).map(c=>`
    <div class="card"><div class="card-label">🏦 ${{esc(c.name)}}</div><div class="card-value yellow">${{eur(c.balance)}}</div></div>`).join('');
  document.getElementById('tab-coffres').innerHTML = `
    <div class="summary-grid" style="margin-bottom:24px">
      <div class="card"><div class="card-label">Total liquidités</div><div class="card-value yellow">${{eur(total)}}</div></div>
      ${{cards}}
    </div>
    <div class="card" style="padding:16px">
      <p style="color:var(--text2);font-size:13px">Les soldes affichés correspondent à l'état au moment de l'export.</p>
    </div>`;
}}

function renderAssets(data) {{
  const coffreMap = Object.fromEntries((data.coffres||[]).map(c=>[c.id,c.name]));
  const total = (data.assets||[]).reduce((s,a)=>s+(a.estimated_value||0),0);
  const rows = (data.assets||[]).map(a => {{
    const vInfo = a.category==='vehicule' && (a.vehicle_make||a.vehicle_model)
      ? [a.vehicle_make,a.vehicle_model,a.vehicle_year].filter(Boolean).join(' ')
      : '';
    const vehicleBlock = a.category==='vehicule' ? `
      <div class="v-grid">
        ${{a.vehicle_make?`<div class="v-field"><div class="v-label">Marque</div><div class="v-val">${{esc(a.vehicle_make)}}</div></div>`:''}}
        ${{a.vehicle_model?`<div class="v-field"><div class="v-label">Modèle</div><div class="v-val">${{esc(a.vehicle_model)}}</div></div>`:''}}
        ${{a.vehicle_year?`<div class="v-field"><div class="v-label">Année</div><div class="v-val">${{a.vehicle_year}}</div></div>`:''}}
        ${{a.vehicle_fuel?`<div class="v-field"><div class="v-label">Carburant</div><div class="v-val">${{esc(a.vehicle_fuel)}}</div></div>`:''}}
        ${{a.vehicle_plate?`<div class="v-field"><div class="v-label">Immatriculation</div><div class="v-val">${{esc(a.vehicle_plate)}}</div></div>`:''}}
        ${{a.vehicle_km!=null?`<div class="v-field"><div class="v-label">Kilométrage</div><div class="v-val">${{num(a.vehicle_km)}} km</div></div>`:''}}
        ${{a.vehicle_vin?`<div class="v-field" style="grid-column:1/-1"><div class="v-label">VIN</div><div class="v-val">${{esc(a.vehicle_vin)}}</div></div>`:''}}
      </div>` : '';
    const DOC_LABELS = {{facture:'🧾 Facture',carte_grise:'📋 Carte grise',assurance:'🛡 Assurance',controle_technique:'🔧 CT',certificat:'📜 Certificat',photo:'📷 Photo',autre:'📄 Autre'}};
    const docsBlock = (a.documents||[]).length ? `
      <div style="margin-top:10px">
        <div class="section-title">Documents (${{a.documents.length}})</div>
        <div style="display:flex;flex-wrap:wrap;gap:8px">
          ${{a.documents.map((d,i)=>`
            <div style="background:var(--bg3);border:1px solid var(--border);border-radius:8px;padding:10px 12px;display:flex;align-items:center;gap:10px;min-width:200px">
              <span style="font-size:20px">📄</span>
              <div style="flex:1;min-width:0">
                <div style="font-size:12px;font-weight:600;white-space:nowrap;overflow:hidden;text-overflow:ellipsis">${{esc(d.filename)}}</div>
                <div style="font-size:11px;color:var(--text2);margin-top:2px">${{DOC_LABELS[d.document_type]||d.document_type||'—'}} · ${{fmtSize(d.size_bytes)}} · ${{fmtDate(d.created_at)}}</div>
                ${{d.notes?`<div style="font-size:11px;color:var(--text2);font-style:italic">${{esc(d.notes)}}</div>`:''}}
              </div>
              <button onclick="downloadFile('${{esc(d.filename)}}','${{d.mime_type}}','${{d.data_b64}}')"
                style="background:var(--accent);color:#fff;border:none;border-radius:6px;padding:6px 10px;font-size:12px;cursor:pointer;white-space:nowrap;flex-shrink:0">
                ⬇ Télécharger
              </button>
            </div>`).join('')}}
        </div>
      </div>` : '';
    const eventsBlock = (a.events||[]).length ? `<div style="margin-top:10px"><div class="section-title">Événements</div><table style="font-size:12px"><thead><tr><th class="left">Date</th><th class="left">Type</th><th>Montant</th><th class="left">Note</th></tr></thead><tbody>${{a.events.map(e=>`<tr><td class="left">${{fmtDate(e.date)}}</td><td class="left">${{e.type}}</td><td>${{eur(e.amount)}}</td><td class="left" style="color:var(--text2)">${{esc(e.notes||'—')}}</td></tr>`).join('')}}</tbody></table></div>` : '';
    return `
      <tr onclick="this.nextElementSibling.querySelector('.expand-content').classList.toggle('open')" style="cursor:pointer">
        <td class="left"><strong>${{CAT_ICONS[a.category]||'📦'}} ${{esc(a.name)}}</strong>${{vInfo?`<br/><span style="color:var(--text2);font-size:11px">${{esc(vInfo)}}</span>`:''}}</td>
        <td class="left"><span class="badge badge-${{a.category||'autre'}}">${{CAT_LABELS[a.category||'autre']}}</span></td>
        <td class="left" style="color:var(--text2)">${{a.coffre_id?(coffreMap[a.coffre_id]||'Coffre'):'—'}}</td>
        <td><strong>${{eur(a.estimated_value)}}</strong></td>
        <td style="color:var(--text2)">${{(a.documents||[]).length}}</td>
      </tr>
      <tr class="expand-row" style="display:table-row"><td colspan="5">
        <div class="expand-content" style="max-height:0;overflow:hidden;transition:.3s">${{vehicleBlock}}${{eventsBlock}}${{docsBlock}}</div>
      </td></tr>`;
  }}).join('');

  document.getElementById('tab-assets').innerHTML = `
    <div class="summary-grid" style="margin-bottom:24px">
      <div class="card"><div class="card-label">Valeur totale</div><div class="card-value purple">${{eur(total)}}</div></div>
    </div>
    <div class="card" style="padding:0"><div class="table-wrap"><table>
      <thead><tr><th class="left">Actif</th><th class="left">Catégorie</th><th class="left">Localisation</th><th>Valeur estimée</th><th>Docs</th></tr></thead>
      <tbody>${{rows}}</tbody>
    </table></div></div>`;

  // Toggle expand on click
  document.querySelectorAll('#tab-assets .expand-content').forEach(el => {{
    const observer = new MutationObserver(() => {{
      el.style.maxHeight = el.classList.contains('open') ? el.scrollHeight + 'px' : '0';
    }});
    observer.observe(el, {{attributes:true,attributeFilter:['class']}});
  }});
}}

function renderReserves(data) {{
  const reserves = data.reserves || [];
  const years = [...new Set(reserves.map(r=>r.year))].sort((a,b)=>b-a);
  const MONTHS = ['Janv','Févr','Mars','Avr','Mai','Juin','Juil','Août','Sept','Oct','Nov','Déc'];
  const totalAmt = reserves.reduce((s,r)=>s+r.amount,0);
  const totalRel = reserves.reduce((s,r)=>s+r.released,0);

  const blocks = years.map(yr => {{
    const yReserves = reserves.filter(r=>r.year===yr).sort((a,b)=>a.month-b.month);
    const rows = yReserves.map(r=>`
      <tr><td class="left">${{MONTHS[r.month-1]}}</td><td>${{eur(r.amount)}}</td>
      <td style="color:var(--text2)">${{r.release_year||'—'}}</td>
      <td>${{eur(r.released)}}</td>
      <td class="pos">${{eur(Math.max(0,r.amount-r.released))}}</td>
      <td class="left" style="color:var(--text2)">${{esc(r.notes||'—')}}</td></tr>`).join('');
    return `<div class="yr-block">
      <div class="yr-title">${{yr}}</div>
      <div class="table-wrap"><table>
        <thead><tr><th class="left">Mois</th><th>Montant</th><th>Année libér.</th><th>Libéré</th><th>Libérable</th><th class="left">Note</th></tr></thead>
        <tbody>${{rows}}</tbody>
      </table></div></div>`;
  }}).join('');

  document.getElementById('tab-reserves').innerHTML = `
    <div class="summary-grid" style="margin-bottom:24px">
      <div class="card"><div class="card-label">Total constitué</div><div class="card-value">${{eur(totalAmt)}}</div></div>
      <div class="card"><div class="card-label">Total libéré</div><div class="card-value">${{eur(totalRel)}}</div></div>
      <div class="card"><div class="card-label">Libérable</div><div class="card-value green">${{eur(Math.max(0,totalAmt-totalRel))}}</div></div>
    </div>
    ${{blocks}}`;
}}

function renderVault(data) {{
  const files = data.vault || [];
  const EXT_ICONS = {{pdf:'📕',jpg:'🖼',jpeg:'🖼',png:'🖼',webp:'🖼',csv:'📊',json:'📋',zip:'🗜',txt:'📝',doc:'📄',docx:'📄',xls:'📊',xlsx:'📊'}};
  const getIcon = f => {{ const ext = f.split('.').pop().toLowerCase(); return EXT_ICONS[ext] || '📄'; }};

  if (!files.length) {{
    document.getElementById('tab-vault').innerHTML = `
      <div class="card" style="padding:40px;text-align:center">
        <div style="font-size:40px;margin-bottom:12px">🔐</div>
        <div style="color:var(--text2);font-size:14px">Aucun fichier dans le coffre au moment de l'export.</div>
      </div>`;
    return;
  }}

  const cards = files.map((f,i) => `
    <div class="card" style="display:flex;align-items:center;gap:16px;padding:16px">
      <span style="font-size:32px;flex-shrink:0">${{getIcon(f.filename)}}</span>
      <div style="flex:1;min-width:0">
        <div style="font-size:14px;font-weight:600;margin-bottom:4px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis">${{esc(f.filename)}}</div>
        <div style="font-size:12px;color:var(--text2)">${{fmtSize(f.size_bytes)}} · Ajouté le ${{fmtDate(f.created_at)}}</div>
      </div>
      <button onclick="downloadFile('${{esc(f.filename)}}','${{f.mime_type}}','${{f.data_b64}}')"
        style="background:var(--accent);color:#fff;border:none;border-radius:8px;padding:10px 16px;font-size:13px;font-weight:500;cursor:pointer;flex-shrink:0;display:flex;align-items:center;gap:6px">
        ⬇ Télécharger
      </button>
    </div>`).join('');

  document.getElementById('tab-vault').innerHTML = `
    <div class="summary-grid" style="margin-bottom:24px">
      <div class="card">
        <div class="card-label">🔐 Fichiers chiffrés</div>
        <div class="card-value">${{files.length}}</div>
        <div style="font-size:12px;color:var(--text2);margin-top:4px">Total : ${{fmtSize(files.reduce((s,f)=>s+f.size_bytes,0))}}</div>
      </div>
    </div>
    <div style="display:flex;flex-direction:column;gap:10px">${{cards}}</div>`;
}}
</script>
</body>
</html>"""


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
    json_bytes = json.dumps(data, ensure_ascii=False, default=str).encode("utf-8")
    blob = _encrypt_blob(json_bytes, body.passphrase)

    exported_at = data["meta"]["exported_at"][:10]  # YYYY-MM-DD
    html = _build_html(blob, exported_at, PBKDF2_ITERATIONS)

    filename = f"patrimonium-export-{exported_at}.html"
    return Response(
        content=html.encode("utf-8"),
        media_type="text/html",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
