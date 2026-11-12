/* ═══════════════════════════════════════════════
   CRYPTO — Positions + comptes d'exchange (Kraken, Bitvavo)
   Clés API en lecture seule, chiffrées AES-256 côté serveur.
   ═══════════════════════════════════════════════ */
'use strict';

let _cryptoData = { stats: {}, positions: [], accounts: [] };
let _cryptoShowDust = false;   // positions < 1 € (poussières) masquées par défaut

function toggleCryptoDust() { _cryptoShowDust = !_cryptoShowDust; renderCryptoPage(); }

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

  const dust = positions.filter(p => (p.current_value || 0) < 1);
  const shown = _cryptoShowDust ? positions : positions.filter(p => (p.current_value || 0) >= 1);
  const accN = stats.account_count || 0;

  page.innerHTML = `
    <div class="db-head">
      <div>
        <h1 class="db-title">Crypto</h1>
        <div class="db-subtitle">${accN} compte${accN > 1 ? 's' : ''} d’exchange · clés en lecture seule</div>
      </div>
      ${isAdmin() ? `
        <div class="db-actions">
          <button class="btn btn-secondary" onclick="openExchangeModal()">Ajouter un compte</button>
          <button class="btn btn-primary" onclick="syncAllExchanges(this)">${ICONS.refresh} Synchroniser</button>
        </div>` : ''}
    </div>

    <div class="pf-kpis cr-kpis">
      <div class="pf-kpi">
        <div class="db-label">Total sur les exchanges</div>
        <div class="pf-kpi-value">${fmtEur(stats.total_account_eur || 0)}</div>
        <div class="pf-kpi-sub">positions + liquidités</div>
      </div>
      <div class="pf-kpi">
        <div class="db-label">Valeur des positions</div>
        <div class="pf-kpi-value">${fmtEur(stats.total_value_eur || 0)}</div>
        <div class="pf-kpi-sub">investi ${fmtEur(stats.total_invested_eur || 0)}</div>
      </div>
      <div class="pf-kpi">
        <div class="db-label">Liquidités disponibles</div>
        <div class="pf-kpi-value">${fmtEur(stats.total_cash_eur || 0)}</div>
        <div class="pf-kpi-sub">non investi sur les exchanges</div>
      </div>
      <div class="pf-kpi">
        <div class="db-label">Plus-value latente</div>
        <div class="pf-kpi-value ${pnlClass(pnl)}">${pnlSign(pnl)}${fmtEur(pnl)}</div>
        <div class="pf-kpi-sub ${pnlClass(stats.total_pnl_pct)}">${stats.total_pnl_pct != null ? pnlSign(stats.total_pnl_pct) + fmtPct(stats.total_pnl_pct) : '—'}</div>
      </div>
    </div>

    ${positions.length ? `
      <section class="card pf-table-card">
        <div class="pf-toolbar">
          <div class="db-card-title" style="margin:0">Positions <span class="section-count">${positions.length - dust.length}</span></div>
        </div>
        <div class="table-wrap">
          <table class="data-table pf-table">
            <thead><tr>
              <th class="left">Actif</th>
              <th>Quantité</th>
              <th>PRU</th>
              <th>Cours</th>
              <th>Valeur</th>
              <th>Plus-value</th>
              <th>Poids</th>
              ${isAdmin() ? '<th><span class="sr-only">Actions</span></th>' : ''}
            </tr></thead>
            <tbody>${shown.map(renderCryptoRow).join('')}${renderCashRows(_cryptoData.cash)}</tbody>
          </table>
        </div>
        ${dust.length ? `<div class="cr-dust">${_cryptoShowDust
          ? `${dust.length} position${dust.length > 1 ? 's' : ''} résiduelle${dust.length > 1 ? 's' : ''} affichée${dust.length > 1 ? 's' : ''}`
          : `${dust.length} position${dust.length > 1 ? 's' : ''} résiduelle${dust.length > 1 ? 's' : ''} (moins de 1 €) masquée${dust.length > 1 ? 's' : ''}`}
          · <button type="button" class="db-link" onclick="toggleCryptoDust()">${_cryptoShowDust ? 'Masquer' : 'Afficher'}</button></div>` : ''}
      </section>` : `
      <div class="card" style="text-align:center;padding:48px 24px;margin-bottom:16px">
        <div style="font-size:15px;color:var(--text-secondary);margin-bottom:6px">Aucune position crypto</div>
        <div style="font-size:13px;color:var(--text-muted)">Ajoute un compte Kraken ou Bitvavo, puis lance une synchronisation.</div>
      </div>`}

    <section class="card">
      <div class="db-card-title">Comptes d’exchange</div>
      <div class="cr-note">
        <b>Clés en lecture seule uniquement.</b>
        Patrimonium ne passe aucun ordre et n'effectue aucun retrait — il lit seulement
        tes soldes et ton historique de trades. Crée tes clés API sans permission de
        trading ni de retrait : même compromises, elles ne permettraient pas de toucher à tes fonds.
      </div>
      ${accounts.length
        ? `<div class="cr-accounts">${accounts.map(renderExchangeCard).join('')}</div>`
        : `<div class="db-muted" style="text-align:center;padding:20px">Aucun compte configuré.</div>`}
    </section>

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
  const sym = (p.ticker || '').split(/[-./]/)[0].slice(0, 5);
  return `
    <tr class="position-row" style="cursor:default">
      <td class="left" data-label="">
        <div class="asset-name-cell">
          <span class="pf-badge cr-badge">${escHtml(sym)}</span>
          <div style="min-width:0">
            <div class="asset-name">${escHtml(p.display_name)}</div>
            <div class="asset-sub">${escHtml(p.ticker)}</div>
          </div>
        </div>
      </td>
      <td data-label="Quantité">${fmtNum(p.total_quantity, 6)}</td>
      <td data-label="PRU">${p.average_cost != null ? fmtEur(p.average_cost) : '—'}</td>
      <td data-label="Cours">${fmtEur(p.current_price || 0)}</td>
      <td data-label="Valeur"><strong>${fmtEur(p.current_value || 0)}</strong><div class="pf-sub">investi ${fmtEur(p.total_invested || 0)}</div></td>
      <td data-label="Plus-value">${p.pnl_pct != null ? `<span class="db-chip ${pnl >= 0 ? 'is-gain' : 'is-loss'}">${pnlSign(p.pnl_pct)}${fmtPct(p.pnl_pct)}</span>` : '—'}
        <div class="pf-sub ${pnlClass(pnl)}">${pnlSign(pnl)}${fmtEur(pnl)}</div></td>
      <td data-label="Poids">${fmtPct(p.allocation_pct || 0, 1)}</td>
      ${isAdmin() ? `<td class="pf-actions"><button type="button" class="pf-menu-btn" title="Archiver cette position"
        aria-label="Archiver ${escHtml(p.display_name)}" onclick="archiveCryptoPosition(${p.id})">${ICONS.trash || '🗑'}</button></td>` : ''}
    </tr>`;
}

// Lignes « liquidités » : un solde, pas une position — la plupart des colonnes
// (PRU, P&L, allocation) n'ont pas de sens ici.
function renderCashRows(cash) {
  return (cash || []).map(c => `
    <tr class="position-row" style="cursor:default">
      <td class="left" data-label="">
        <div class="asset-name-cell">
          <span class="pf-badge cr-cash">€</span>
          <div><div class="asset-name">${escHtml(c.display_name)}</div><div class="asset-sub">EUR disponible sur le compte</div></div>
        </div>
      </td>
      <td class="cr-na">—</td><td class="cr-na">—</td><td class="cr-na">—</td>
      <td data-label="Valeur"><strong>${fmtEur(c.balance_eur || 0)}</strong></td>
      <td class="cr-na">—</td><td class="cr-na">—</td>
      ${isAdmin() ? '<td></td>' : ''}
    </tr>`).join('');
}

async function archiveCryptoPosition(posId) {
  const pos = (_cryptoData.positions || []).find(p => p.id === posId);
  if (!pos) return;
  confirm('Archiver la position',
    `Archiver « ${pos.display_name} » ? Elle disparaîtra de la page Crypto, mais son `
    + `historique est conservé. Resynchroniser ne la fera pas revenir : seul un nouvel `
    + `achat sur cet actif la réactivera.`,
    async () => {
      try {
        await apiDelete(`/api/portfolio/positions/${posId}`);
        showToast('Position archivée', 'success');
        await loadCrypto();
      } catch (err) { showToast(err.message, 'error'); }
    });
}

function renderExchangeCard(a) {
  const sync = a.last_sync_at
    ? `Dernière sync : ${fmtDateTime(a.last_sync_at)}`
    : 'Jamais synchronisé';
  return `
    <div class="cr-account">
      <div style="min-width:0">
        <div style="font-weight:600;display:flex;align-items:center;gap:8px">
          ${escHtml(a.label)}
          <span class="badge badge-admin">${escHtml(a.exchange_label)}</span>
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
    <div class="cr-note is-info">
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
    if (r.cash_error) showToast(`Soldes illisibles : ${r.cash_error}`, 'error');
    if (r.reconciled_assets?.length)
      showToast(`Avoirs sans trade repris depuis les soldes : ${r.reconciled_assets.join(', ')} `
        + `— leur PRU est estimé au cours du jour`, 'info');
    if (r.assets_without_price?.length)
      showToast(`Cours introuvable pour ${r.assets_without_price.join(', ')} — valorisé à 0 €`, 'error');
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
    ok.filter(r => r.cash_error)
      .forEach(r => showToast(`${r.label} — liquidités : ${r.cash_error}`, 'error'));
    ko.forEach(r => showToast(`${r.label} : ${r.error}`, 'error'));
    await loadCrypto();
  } catch (err) {
    showToast(err.message, 'error');
  } finally {
    if (btn) { btn.disabled = false; btn.innerHTML = `${ICONS.refresh} Synchroniser`; }
  }
}

function deleteExchange(id) {
  const label = (_cryptoData.accounts || []).find(a => a.id === id)?.label || 'ce compte';
  confirm('Supprimer le compte',
    `Supprimer « ${label} » ? Les clés API sont effacées, mais les positions et `
    + `transactions déjà importées sont conservées.`,
    async () => {
      try {
        await apiDelete(`/api/crypto/accounts/${id}`);
        showToast('Compte supprimé', 'success');
        await loadCrypto();
      } catch (err) { showToast(err.message, 'error'); }
    });
}
