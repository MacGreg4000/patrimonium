/* ═══════════════════════════════════════════════
   BANK — GoCardless Bank Account Data page
   ═══════════════════════════════════════════════ */
'use strict';

// ── State ─────────────────────────────────────────────────

let _bankAccounts = [];
let _bankInstitutions = [];
let _bankStep = 1;  // 1 = select country/institution, 2 = link sent
let _bankConnectLink = null;
let _bankNewReqId = null;

// ── Icons ─────────────────────────────────────────────────

const BANK_ICON = `<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect x="3" y="10" width="18" height="11" rx="2"/><path d="M3 10l9-7 9 7"/><line x1="12" y1="10" x2="12" y2="21"/></svg>`;
const SYNC_ICON = `<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><path d="M3 12a9 9 0 019-9 9.75 9.75 0 016.74 2.74L21 8"/><path d="M21 3v5h-5M21 12a9 9 0 01-9 9 9.75 9.75 0 01-6.74-2.74L3 16"/></svg>`;
const TRASH_ICON = `<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polyline points="3 6 5 6 21 6"/><path d="M19 6l-1 14a2 2 0 01-2 2H8a2 2 0 01-2-2L5 6"/><path d="M10 11v6M14 11v6"/><path d="M9 6V4a1 1 0 011-1h4a1 1 0 011 1v2"/></svg>`;
const PLUG_ICON = `<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M18 6L6 18M6 6l12 12"/><path d="M12 2v4M12 18v4M4.93 4.93l2.83 2.83M16.24 16.24l2.83 2.83M2 12h4M18 12h4M4.93 19.07l2.83-2.83M16.24 7.76l2.83-2.83"/></svg>`;

// ── Main load function ────────────────────────────────────

async function loadBank() {
  const page = document.getElementById('page-bank');
  if (!page) return;
  page.innerHTML = '<div class="loading">Chargement des comptes bancaires…</div>';

  let configured = false;
  try {
    const status = await apiGet('/api/bank/status');
    configured = status.configured;
  } catch (_) {}

  if (!configured) {
    page.innerHTML = `
      <div class="section-header" style="margin-bottom:24px">
        <div>
          <h2 class="section-title">Comptes bancaires</h2>
          <p class="section-subtitle">Connexion via GoCardless Bank Account Data</p>
        </div>
      </div>
      <div class="card" style="text-align:center;padding:40px">
        <div style="font-size:32px;margin-bottom:16px;opacity:.4">${BANK_ICON}</div>
        <div style="font-size:15px;font-weight:500;margin-bottom:8px">GoCardless non configuré</div>
        <div style="font-size:13px;color:var(--text-secondary)">
          Définissez les variables d'environnement <code>GOCARDLESS_SECRET_ID</code>
          et <code>GOCARDLESS_SECRET_KEY</code> pour activer cette fonctionnalité.
        </div>
      </div>`;
    return;
  }

  try {
    _bankAccounts = await apiGet('/api/bank/accounts');
  } catch (err) {
    page.innerHTML = `<div class="error-state">Erreur : ${escHtml(err.message)}</div>`;
    return;
  }

  renderBankPage(_bankAccounts);
}

// ── Render ────────────────────────────────────────────────

function renderBankPage(accounts) {
  const page = document.getElementById('page-bank');
  if (!page) return;

  const admin = isAdmin();

  // ── Hero KPIs ─────────────────────────────────────────

  // Group by currency
  const byCurrency = {};
  for (const acc of accounts) {
    if (acc.balance == null) continue;
    const cur = acc.currency || 'EUR';
    byCurrency[cur] = (byCurrency[cur] || 0) + acc.balance;
  }

  let heroHtml = '';
  if (Object.keys(byCurrency).length === 0) {
    heroHtml = `
      <div class="hero-card">
        <div class="hero-card-label">Total</div>
        <div class="hero-card-value">—</div>
      </div>`;
  } else if (Object.keys(byCurrency).length === 1 && byCurrency['EUR'] != null) {
    heroHtml = `
      <div class="hero-card">
        <div class="hero-card-label">Total bancaire</div>
        <div class="hero-card-value">${fmtEur(byCurrency['EUR'])}</div>
      </div>`;
  } else {
    for (const [cur, total] of Object.entries(byCurrency)) {
      heroHtml += `
        <div class="hero-card">
          <div class="hero-card-label">Total ${escHtml(cur)}</div>
          <div class="hero-card-value">${fmtNum(total, 2)} ${escHtml(cur)}</div>
        </div>`;
    }
  }

  heroHtml += `
    <div class="hero-card">
      <div class="hero-card-label">Comptes connectés</div>
      <div class="hero-card-value">${accounts.length}</div>
    </div>`;

  // ── Group accounts by institution ─────────────────────

  const byInstitution = {};
  for (const acc of accounts) {
    const key = acc.institution_name || acc.requisition_db_id || 'unknown';
    if (!byInstitution[key]) {
      byInstitution[key] = {
        name: acc.institution_name || 'Banque inconnue',
        logo: acc.institution_logo,
        requisition_db_id: acc.requisition_db_id,
        requisition_status: acc.requisition_status,
        accounts: [],
      };
    }
    byInstitution[key].accounts.push(acc);
  }

  let institutionsHtml = '';
  if (accounts.length === 0) {
    institutionsHtml = `
      <div class="card" style="text-align:center;padding:40px">
        <div style="font-size:32px;margin-bottom:16px;opacity:.4">${BANK_ICON}</div>
        <div style="font-size:15px;font-weight:500;margin-bottom:8px">Aucun compte connecté</div>
        <div style="font-size:13px;color:var(--text-secondary)">
          ${admin ? 'Cliquez sur "Connecter une banque" pour commencer.' : 'Aucun compte bancaire n\'est encore connecté.'}
        </div>
      </div>`;
  } else {
    for (const [, inst] of Object.entries(byInstitution)) {
      const logoHtml = inst.logo
        ? `<img src="${escHtml(inst.logo)}" alt="${escHtml(inst.name)}" style="width:28px;height:28px;object-fit:contain;border-radius:4px"/>`
        : `<span style="opacity:.5">${BANK_ICON}</span>`;

      const statusBadge = inst.requisition_status === 'LN'
        ? '<span class="badge badge-success" style="font-size:10px">Lié</span>'
        : inst.requisition_status === 'EX'
          ? '<span class="badge badge-warning" style="font-size:10px">Expiré</span>'
          : inst.requisition_status === 'RJ'
            ? '<span class="badge badge-danger" style="font-size:10px">Rejeté</span>'
            : `<span class="badge" style="font-size:10px">${escHtml(inst.requisition_status)}</span>`;

      const deleteBtn = admin
        ? `<button class="btn btn-danger btn-sm" onclick="deleteBankRequisition(${inst.requisition_db_id}, '${escHtml(inst.name)}')" title="Supprimer la connexion">${TRASH_ICON}</button>`
        : '';

      const rows = inst.accounts.map(acc => `
        <tr>
          <td style="padding:10px 16px;color:var(--text-secondary);font-size:12px;font-family:monospace">${escHtml(acc.iban || '—')}</td>
          <td style="padding:10px 16px">${escHtml(acc.name || acc.owner_name || '—')}</td>
          <td style="padding:10px 16px;text-align:right;font-weight:600">${acc.balance != null ? fmtNum(acc.balance, 2) + ' ' + escHtml(acc.currency || 'EUR') : '—'}</td>
          <td style="padding:10px 16px;color:var(--text-secondary);font-size:12px">${fmtDateTime(acc.last_synced_at)}</td>
          <td style="padding:10px 16px;text-align:right">
            ${admin ? `<button class="btn btn-secondary btn-sm" onclick="syncBankAccount(${acc.id})" title="Synchroniser">${SYNC_ICON}</button>` : ''}
          </td>
        </tr>`).join('');

      institutionsHtml += `
        <div class="card" style="margin-bottom:16px;padding:0;overflow:hidden">
          <div style="display:flex;align-items:center;justify-content:space-between;padding:16px 20px;border-bottom:1px solid var(--border)">
            <div style="display:flex;align-items:center;gap:12px">
              ${logoHtml}
              <div>
                <div style="font-weight:600;font-size:15px">${escHtml(inst.name)}</div>
                <div style="font-size:12px;color:var(--text-secondary);margin-top:2px">${statusBadge} · ${inst.accounts.length} compte${inst.accounts.length > 1 ? 's' : ''}</div>
              </div>
            </div>
            <div style="display:flex;align-items:center;gap:8px">
              ${deleteBtn}
            </div>
          </div>
          <div style="overflow-x:auto">
            <table class="data-table" style="margin:0">
              <thead>
                <tr>
                  <th style="padding:8px 16px">IBAN</th>
                  <th style="padding:8px 16px">Nom du compte</th>
                  <th style="padding:8px 16px;text-align:right">Solde</th>
                  <th style="padding:8px 16px">Dernière synchro</th>
                  <th style="padding:8px 16px"></th>
                </tr>
              </thead>
              <tbody>${rows}</tbody>
            </table>
          </div>
        </div>`;
    }
  }

  // ── Action buttons ────────────────────────────────────

  const actionBtns = admin ? `
    <div style="display:flex;gap:8px">
      ${accounts.length > 0 ? `<button class="btn btn-secondary" onclick="syncAllBankAccounts()">${SYNC_ICON} Tout synchroniser</button>` : ''}
      <button class="btn btn-primary" onclick="openBankConnectModal()">${PLUG_ICON} Connecter une banque</button>
    </div>` : '';

  page.innerHTML = `
    <div class="section-header" style="margin-bottom:24px">
      <div>
        <h2 class="section-title">Comptes bancaires</h2>
        <p class="section-subtitle">Soldes en temps réel via GoCardless Bank Account Data</p>
      </div>
      ${actionBtns}
    </div>

    <div class="hero-grid" style="margin-bottom:24px">
      ${heroHtml}
    </div>

    ${institutionsHtml}`;
}

// ── Sync actions ──────────────────────────────────────────

async function syncBankAccount(accountId) {
  try {
    const updated = await apiPost(`/api/bank/sync/${accountId}`, {});
    // Update local state
    const idx = _bankAccounts.findIndex(a => a.id === accountId);
    if (idx !== -1) _bankAccounts[idx] = updated;
    renderBankPage(_bankAccounts);
    showToast('Compte synchronisé.', 'success');
  } catch (err) {
    showToast('Erreur de synchronisation : ' + err.message, 'error');
  }
}

async function syncAllBankAccounts() {
  try {
    _bankAccounts = await apiPost('/api/bank/sync', {});
    renderBankPage(_bankAccounts);
    showToast('Tous les comptes synchronisés.', 'success');
  } catch (err) {
    showToast('Erreur de synchronisation : ' + err.message, 'error');
  }
}

// ── Delete requisition ────────────────────────────────────

function deleteBankRequisition(reqDbId, institutionName) {
  const confirmEl = document.getElementById('confirmTitle');
  const messageEl = document.getElementById('confirmMessage');
  const confirmBtn = document.getElementById('confirmBtn');

  if (confirmEl) confirmEl.textContent = 'Supprimer la connexion bancaire';
  if (messageEl) messageEl.textContent = `Supprimer la connexion avec ${institutionName} ? Tous les comptes associés seront supprimés de Patrimonium.`;
  if (confirmBtn) {
    confirmBtn.onclick = async () => {
      closeModal('confirmModal');
      try {
        await apiDelete(`/api/bank/requisitions/${reqDbId}`);
        showToast('Connexion supprimée.', 'success');
        await loadBank();
      } catch (err) {
        showToast('Erreur : ' + err.message, 'error');
      }
    };
  }
  openModal('confirmModal');
}

// ── Connect bank modal ────────────────────────────────────

function openBankConnectModal() {
  _bankStep = 1;
  _bankConnectLink = null;
  _bankNewReqId = null;
  _renderBankModalStep1();
  openModal('bankConnectModal');
}

function _renderBankModalStep1() {
  const body = document.getElementById('bankModalBody');
  if (!body) return;

  body.innerHTML = `
    <div class="form-group" style="margin-bottom:16px">
      <label class="form-label">Pays</label>
      <select class="form-input" id="bankCountrySelect" onchange="loadBankInstitutions()">
        <option value="BE">🇧🇪 Belgique</option>
        <option value="FR">🇫🇷 France</option>
        <option value="LU">🇱🇺 Luxembourg</option>
      </select>
    </div>
    <div class="form-group" style="margin-bottom:20px">
      <label class="form-label">Banque</label>
      <div id="bankInstitutionContainer">
        <div style="color:var(--text-secondary);font-size:13px">Chargement des banques…</div>
      </div>
    </div>
    <div class="form-actions" style="border-top:1px solid var(--border);padding-top:16px;margin-top:8px">
      <button class="btn btn-secondary" onclick="closeModal('bankConnectModal')">Annuler</button>
      <button class="btn btn-primary" id="bankConnectBtn" onclick="startBankConnection()" disabled>Connecter</button>
    </div>`;

  loadBankInstitutions();
}

async function loadBankInstitutions() {
  const country = document.getElementById('bankCountrySelect')?.value || 'BE';
  const container = document.getElementById('bankInstitutionContainer');
  if (!container) return;

  container.innerHTML = '<div style="color:var(--text-secondary);font-size:13px">Chargement…</div>';

  try {
    _bankInstitutions = await apiGet(`/api/bank/institutions?country=${country}`);
  } catch (err) {
    container.innerHTML = `<div style="color:var(--accent-red);font-size:13px">Erreur : ${escHtml(err.message)}</div>`;
    return;
  }

  const options = _bankInstitutions
    .map(inst => `<option value="${escHtml(inst.id)}" data-logo="${escHtml(inst.logo || '')}">${escHtml(inst.name)}</option>`)
    .join('');

  container.innerHTML = `<select class="form-input" id="bankInstitutionSelect" onchange="onBankInstitutionChange()">
    <option value="">— Sélectionner une banque —</option>
    ${options}
  </select>`;

  const connectBtn = document.getElementById('bankConnectBtn');
  if (connectBtn) connectBtn.disabled = true;
}

function onBankInstitutionChange() {
  const select = document.getElementById('bankInstitutionSelect');
  const connectBtn = document.getElementById('bankConnectBtn');
  if (connectBtn) connectBtn.disabled = !select?.value;
}

async function startBankConnection() {
  const institutionSelect = document.getElementById('bankInstitutionSelect');
  const connectBtn = document.getElementById('bankConnectBtn');
  if (!institutionSelect?.value) return;

  const instId = institutionSelect.value;
  const instOption = institutionSelect.options[institutionSelect.selectedIndex];
  const instName = instOption?.text || instId;
  const instLogo = instOption?.dataset?.logo || null;

  if (connectBtn) { connectBtn.disabled = true; connectBtn.textContent = 'Connexion…'; }

  try {
    const data = await apiPost('/api/bank/requisitions', {
      institution_id: instId,
      institution_name: instName,
      institution_logo: instLogo || undefined,
    });
    _bankConnectLink = data.link;
    _bankNewReqId = data.id;
    _renderBankModalStep2(instName, data.link);
  } catch (err) {
    showToast('Erreur : ' + err.message, 'error');
    if (connectBtn) { connectBtn.disabled = false; connectBtn.textContent = 'Connecter'; }
  }
}

function _renderBankModalStep2(institutionName, link) {
  const body = document.getElementById('bankModalBody');
  if (!body) return;

  body.innerHTML = `
    <div style="text-align:center;padding:8px 0 16px">
      <div style="font-size:32px;margin-bottom:12px">🏦</div>
      <div style="font-weight:600;font-size:15px;margin-bottom:8px">Autorisez l'accès dans l'onglet ouvert</div>
      <div style="font-size:13px;color:var(--text-secondary);margin-bottom:20px">
        Un onglet GoCardless a été ouvert pour <strong>${escHtml(institutionName)}</strong>.
        Connectez-vous à votre banque et autorisez l'accès en lecture.
      </div>
      <a href="${escHtml(link)}" target="_blank" class="btn btn-secondary" style="display:inline-flex;margin-bottom:20px">
        Ouvrir le lien GoCardless ↗
      </a>
      <div style="border-top:1px solid var(--border);padding-top:16px">
        <div style="font-size:13px;color:var(--text-secondary);margin-bottom:12px">
          Une fois l'autorisation accordée, cliquez sur le bouton ci-dessous pour vérifier la connexion.
        </div>
        <button class="btn btn-primary" onclick="verifyBankConnection()" id="verifyBankBtn">
          Vérifier la connexion
        </button>
      </div>
    </div>
    <div class="form-actions" style="border-top:1px solid var(--border);padding-top:12px;margin-top:8px">
      <button class="btn btn-secondary" onclick="closeModal('bankConnectModal')">Fermer</button>
    </div>`;

  // Open link automatically
  window.open(link, '_blank');
}

async function verifyBankConnection() {
  const btn = document.getElementById('verifyBankBtn');
  if (btn) { btn.disabled = true; btn.textContent = 'Vérification…'; }

  try {
    const accounts = await apiGet('/api/bank/accounts');
    const newAccounts = accounts.filter(a =>
      !_bankAccounts.some(prev => prev.id === a.id)
    );

    if (newAccounts.length > 0) {
      _bankAccounts = accounts;
      closeModal('bankConnectModal');
      renderBankPage(_bankAccounts);
      showToast(`${newAccounts.length} compte(s) connecté(s) avec succès.`, 'success');
    } else {
      showToast('Aucun nouveau compte détecté. Vérifiez que vous avez bien autorisé l\'accès dans la fenêtre GoCardless.', 'info');
      if (btn) { btn.disabled = false; btn.textContent = 'Réessayer'; }
    }
  } catch (err) {
    showToast('Erreur : ' + err.message, 'error');
    if (btn) { btn.disabled = false; btn.textContent = 'Réessayer'; }
  }
}
