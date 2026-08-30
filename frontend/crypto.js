/* ═══════════════════════════════════════════════
   CRYPTO — Positions + comptes d'exchange (Kraken, Bitvavo)
   Clés API en lecture seule, chiffrées AES-256 côté serveur.
   ═══════════════════════════════════════════════ */
'use strict';

let _cryptoData = { stats: {}, positions: [], accounts: [] };

const EXCHANGE_HELP = {
  kraken: {
    name: 'Kraken',
    url: 'https://pro.kraken.com/app/settings/api',
    steps: [
      'Connecte-toi à Kraken → Paramètres → API → « Create API key »',
      'Coche uniquement <b>Query Funds</b> et <b>Query Ledger Entries &amp; Trades</b>',
      'Ne coche <b>aucune</b> permission de trading ni de retrait',
      'Copie la clé (API Key) et le secret (Private Key) ci-dessous',
    ],
  },
  bitvavo: {
    name: 'Bitvavo',
    url: 'https://account.bitvavo.com/user/api',
    steps: [
      'Connecte-toi à Bitvavo → Paramètres → API → « Nouvelle clé API »',
      'Coche uniquement <b>View</b> (lecture)',
      'Ne coche <b>ni</b> Trade <b>ni</b> Withdraw',
      'Copie la clé et le secret ci-dessous',
    ],
  },
};

async function loadCrypto() {
  try {
    _cryptoData = await apiGet('/api/crypto/summary');
    renderCryptoPage();
  } catch (err) {
    showToast('Erreur crypto: ' + err.message, 'error');
  }
}

function renderCryptoPage() {
  const page = document.getElementById('page-crypto');
  if (!page) return;
  const { stats, positions, accounts } = _cryptoData;
  const pnl = stats.total_pnl_eur || 0;
  const pnlCls = pnl >= 0 ? 'green' : 'red';

  page.innerHTML = `
    <div style="display:flex;align-items:center;justify-content:space-between;margin-bottom:20px;gap:12px;flex-wrap:wrap">
      <div class="page-title">${ICONS.bitcoin} Crypto</div>
      ${isAdmin() ? `
        <div style="display:flex;gap:8px;flex-wrap:wrap">
          <button class="btn btn-secondary btn-sm" onclick="openExchangeModal()">${ICONS.key} Ajouter un compte</button>
          <button class="btn btn-primary btn-sm" onclick="syncAllExchanges(this)">${ICONS.refresh} Synchroniser</button>
        </div>` : ''}
    </div>

    <!-- KPIs -->
    <div class="hero-grid" style="margin-bottom:20px">
      <div class="hero-card">
        <div class="card-label">${ICONS.bitcoin} Valeur crypto</div>
        <div class="hero-card-value blue">${fmtEur(stats.total_value_eur || 0)}</div>
        <div class="hero-card-sub">${stats.position_count || 0} position${(stats.position_count || 0) > 1 ? 's' : ''}</div>
      </div>
      <div class="hero-card">
        <div class="card-label">${ICONS.coins} Capital investi</div>
        <div class="hero-card-value gold">${fmtEur(stats.total_invested_eur || 0)}</div>
        <div class="hero-card-sub">coût des parts détenues</div>
      </div>
      <div class="hero-card">
        <div class="card-label">${ICONS.chartUp} Plus/moins-value</div>
        <div class="hero-card-value ${pnlCls}">${pnl >= 0 ? '+' : ''}${fmtEur(pnl)}</div>
        <div class="hero-card-sub">${stats.total_pnl_pct != null ? fmtPct(stats.total_pnl_pct) : '—'}</div>
      </div>
      <div class="hero-card">
        <div class="card-label">${ICONS.key} Comptes connectés</div>
        <div class="hero-card-value">${stats.account_count || 0}</div>
        <div class="hero-card-sub">Kraken · Bitvavo</div>
      </div>
    </div>

    ${positions.length ? `
      <div class="card" style="padding:0;overflow:hidden;margin-bottom:20px">
        <div class="table-wrap">
          <table class="data-table">
            <thead><tr>
              <th class="left" style="padding-left:24px">Actif</th>
              <th>Cours</th>
              <th>Qté</th>
              <th>PRU</th>
              <th>Investi</th>
              <th>Valeur</th>
              <th>P&amp;L €</th>
              <th>P&amp;L %</th>
              <th>Alloc.</th>
            </tr></thead>
            <tbody>${positions.map(renderCryptoRow).join('')}</tbody>
          </table>
        </div>
      </div>` : `
      <div class="card" style="text-align:center;padding:48px 24px;margin-bottom:20px">
        <div style="font-size:15px;color:var(--text-secondary);margin-bottom:6px">Aucune position crypto</div>
        <div style="font-size:13px;color:var(--text-muted)">
          Ajoute un compte Kraken ou Bitvavo, puis lance une synchronisation.
        </div>
      </div>`}

    <!-- Comptes d'exchange -->
    <div class="card">
      <div style="display:flex;align-items:center;justify-content:space-between;margin-bottom:14px">
        <div class="card-title">${ICONS.key} Comptes d'exchange</div>
      </div>
      <div style="background:rgba(249,168,37,.08);border:1px solid rgba(249,168,37,.25);border-radius:10px;padding:12px 16px;margin-bottom:16px;font-size:13px;color:var(--text-secondary);line-height:1.55">
        <b style="color:var(--accent-gold)">Clés en lecture seule uniquement.</b>
        Patrimonium ne passe aucun ordre et n'effectue aucun retrait — il lit seulement
        tes soldes et ton historique de trades. Crée tes clés API sans permission de
        trading ni de retrait : même compromises, elles ne permettraient pas de toucher à tes fonds.
      </div>
      ${accounts.length
        ? `<div style="display:flex;flex-direction:column;gap:10px">${accounts.map(renderExchangeCard).join('')}</div>`
        : `<div style="font-size:13px;color:var(--text-muted);text-align:center;padding:20px">Aucun compte configuré.</div>`}
    </div>

    <!-- Modal ajout de compte -->
    <div class="modal-overlay" id="exchangeModal">
      <div class="modal" style="max-width:520px">
        <div class="modal-header">
          <span class="modal-title">${ICONS.key} Ajouter un compte d'exchange</span>
          <button class="modal-close" onclick="closeModal('exchangeModal')">✕</button>
        </div>
        <form onsubmit="submitExchange(event)" class="form-grid">
          <div class="form-group full">
            <label class="form-label">Exchange</label>
            <select class="form-input" id="exExchange" onchange="updateExchangeHelp()">
              <option value="kraken">Kraken</option>
              <option value="bitvavo">Bitvavo</option>
            </select>
          </div>
          <div class="form-group full" id="exHelp"></div>
          <div class="form-group full">
            <label class="form-label">Nom du compte</label>
            <input type="text" class="form-input" id="exLabel" placeholder="Kraken principal" required/>
          </div>
          <div class="form-group full">
            <label class="form-label">Clé API</label>
            <input type="text" class="form-input" id="exKey" autocomplete="off" spellcheck="false" required/>
          </div>
          <div class="form-group full">
            <label class="form-label">Secret API</label>
            <input type="password" class="form-input" id="exSecret" autocomplete="new-password" spellcheck="false" required/>
            <div style="font-size:11px;color:var(--text-muted);margin-top:4px">
              Chiffré en AES-256-GCM avant enregistrement — jamais réaffiché ensuite.
            </div>
          </div>
          <div class="form-actions">
            <button type="button" class="btn btn-secondary" onclick="closeModal('exchangeModal')">Annuler</button>
            <button type="submit" class="btn btn-primary" id="exSubmitBtn">Vérifier et ajouter</button>
          </div>
        </form>
      </div>
    </div>
  `;
  updateExchangeHelp();
}

function renderCryptoRow(p) {
  const pnl = p.pnl_eur || 0;
  const cls = pnl >= 0 ? 'pos' : 'neg';
  return `
    <tr>
      <td class="left" style="padding-left:24px">
        <div style="display:flex;align-items:center;gap:10px">
          <div class="pos-icon" style="background:rgba(247,147,26,.14);color:#F7931A">${ICONS.bitcoinSm}</div>
          <div>
            <div style="font-weight:600">${escHtml(p.display_name)}</div>
            <div style="font-size:11px;color:var(--text-muted);font-family:var(--font-mono)">${escHtml(p.ticker)}</div>
          </div>
        </div>
      </td>
      <td>${fmtEur(p.current_price || 0)}</td>
      <td>${fmtNum(p.total_quantity, 6)}</td>
      <td>${p.average_cost != null ? fmtEur(p.average_cost) : '—'}</td>
      <td>${fmtEur(p.total_invested || 0)}</td>
      <td style="font-weight:700">${fmtEur(p.current_value || 0)}</td>
      <td class="${cls}">${pnl >= 0 ? '+' : ''}${fmtEur(pnl)}</td>
      <td class="${cls}">${p.pnl_pct != null ? fmtPct(p.pnl_pct) : '—'}</td>
      <td>${(p.allocation_pct || 0).toFixed(1)}%</td>
    </tr>`;
}

function renderExchangeCard(a) {
  const sync = a.last_sync_at
    ? `Dernière sync : ${fmtDateTime(a.last_sync_at)}`
    : 'Jamais synchronisé';
  return `
    <div style="display:flex;align-items:center;justify-content:space-between;gap:12px;flex-wrap:wrap;
                padding:14px 16px;background:var(--bg-tertiary);border:1px solid var(--border);border-radius:10px">
      <div style="min-width:0">
        <div style="font-weight:600;display:flex;align-items:center;gap:8px">
          ${escHtml(a.label)}
          <span class="badge" style="background:rgba(79,142,247,.15);color:var(--accent-blue)">${escHtml(a.exchange_label)}</span>
        </div>
        <div style="font-size:12px;color:var(--text-muted);margin-top:3px">${escHtml(sync)}</div>
        ${a.last_sync_status ? `<div style="font-size:11px;color:var(--text-muted);margin-top:2px">${escHtml(a.last_sync_status)}</div>` : ''}
      </div>
      ${isAdmin() ? `
        <div style="display:flex;gap:8px;flex-shrink:0">
          <button class="btn btn-secondary btn-sm" onclick="syncExchange(${a.id}, this)">Synchroniser</button>
          <button class="btn btn-danger btn-sm" onclick="deleteExchange(${a.id})">Supprimer</button>
        </div>` : ''}
    </div>`;
}

function updateExchangeHelp() {
  const sel = document.getElementById('exExchange');
  const box = document.getElementById('exHelp');
  if (!sel || !box) return;
  const h = EXCHANGE_HELP[sel.value];
  box.innerHTML = `
    <div style="background:rgba(59,130,246,.08);border:1px solid rgba(59,130,246,.25);
                border-radius:10px;padding:12px 16px;font-size:12.5px;color:var(--text-secondary);line-height:1.6">
      <div style="margin-bottom:6px">
        <b>Créer une clé ${h.name} en lecture seule</b> —
        <a href="${h.url}" target="_blank" rel="noopener noreferrer" style="color:var(--accent-blue)">ouvrir ${h.name} ↗</a>
      </div>
      <ol style="margin:0;padding-left:18px">${h.steps.map(s => `<li>${s}</li>`).join('')}</ol>
    </div>`;
}

function openExchangeModal() {
  ['exLabel', 'exKey', 'exSecret'].forEach(id => {
    const el = document.getElementById(id);
    if (el) el.value = '';
  });
  updateExchangeHelp();
  openModal('exchangeModal');
}

async function submitExchange(e) {
  e.preventDefault();
  const btn = document.getElementById('exSubmitBtn');
  const original = btn.textContent;
  btn.disabled = true;
  btn.textContent = 'Vérification…';
  try {
    await apiPost('/api/crypto/accounts', {
      exchange:   document.getElementById('exExchange').value,
      label:      document.getElementById('exLabel').value.trim(),
      api_key:    document.getElementById('exKey').value.trim(),
      api_secret: document.getElementById('exSecret').value.trim(),
    });
    closeModal('exchangeModal');
    showToast('Compte ajouté — clés vérifiées', 'success');
    await loadCrypto();
  } catch (err) {
    showToast(err.message, 'error');
  } finally {
    btn.disabled = false;
    btn.textContent = original;
  }
}

async function syncExchange(id, btn) {
  const original = btn ? btn.textContent : '';
  if (btn) { btn.disabled = true; btn.textContent = 'Sync…'; }
  try {
    const r = await apiPost(`/api/crypto/accounts/${id}/sync`, {});
    showToast(`${r.created_purchases} achat(s), ${r.created_sales} vente(s) importé(s)`, 'success');
    if (r.unsupported_pairs?.length)
      showToast(`Paires non EUR ignorées : ${r.unsupported_pairs.join(', ')}`, 'info');
    await loadCrypto();
  } catch (err) {
    showToast(err.message, 'error');
    if (btn) { btn.disabled = false; btn.textContent = original; }
  }
}

async function syncAllExchanges(btn) {
  if (!_cryptoData.accounts?.length) {
    showToast('Ajoute d\'abord un compte d\'exchange', 'info');
    return;
  }
  const original = btn ? btn.textContent : '';
  if (btn) { btn.disabled = true; btn.textContent = 'Synchronisation…'; }
  try {
    const { results } = await apiPost('/api/crypto/sync-all', {});
    const ok = results.filter(r => !r.error);
    const ko = results.filter(r => r.error);
    const p = ok.reduce((s, r) => s + r.created_purchases, 0);
    const s = ok.reduce((acc, r) => acc + r.created_sales, 0);
    showToast(`${p} achat(s), ${s} vente(s) importé(s)`, 'success');
    ko.forEach(r => showToast(`${r.label} : ${r.error}`, 'error'));
    await loadCrypto();
  } catch (err) {
    showToast(err.message, 'error');
  } finally {
    if (btn) { btn.disabled = false; btn.innerHTML = `${ICONS.refresh} Synchroniser`; }
  }
}

async function deleteExchange(id) {
  const label = (_cryptoData.accounts || []).find(a => a.id === id)?.label || 'ce compte';
  if (!confirm(`Supprimer le compte « ${label} » ?\n\nLes positions et transactions déjà importées sont conservées.`))
    return;
  try {
    await apiDelete(`/api/crypto/accounts/${id}`);
    showToast('Compte supprimé', 'success');
    await loadCrypto();
  } catch (err) {
    showToast(err.message, 'error');
  }
}
