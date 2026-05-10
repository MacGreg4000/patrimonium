/* ═══════════════════════════════════════════════
   APP — SPA router and main orchestrator
   ═══════════════════════════════════════════════ */
'use strict';

const PAGES = ['dashboard', 'portfolio', 'coffres', 'assets', 'reserves', 'passwords', 'admin'];
let _currentPage = 'dashboard';
let _refreshInterval = null;

// ── Navigation ────────────────────────────────────────────

function navigate(page) {
  if (!PAGES.includes(page)) page = 'dashboard';
  _currentPage = page;

  // Show/hide page divs
  PAGES.forEach(p => {
    const el = document.getElementById(`page-${p}`);
    if (el) el.classList.toggle('active', p === page);
  });

  // Update nav active state
  document.querySelectorAll('.nav-item[data-page]').forEach(btn => {
    btn.classList.toggle('active', btn.dataset.page === page);
  });

  // Close user dropdown if open
  const dd = document.getElementById('userDropdown');
  if (dd) dd.style.display = 'none';

  // Load page content
  switch (page) {
    case 'dashboard':  loadDashboard();  break;
    case 'portfolio':  loadPortfolio();  break;
    case 'coffres':    loadCoffres();    break;
    case 'assets':     loadAssets();     break;
    case 'reserves':   loadReserves();   break;
    case 'passwords':  loadPasswords();  break;
    case 'admin':      loadAdmin();      break;
  }
}

// ── App init (called after successful auth) ───────────────

function initApp() {
  injectPortfolioModals();
  navigate('dashboard');
  startAutoRefresh();
}

// ── Refresh logic ─────────────────────────────────────────

async function globalRefresh() {
  const btn = document.getElementById('globalRefreshBtn');
  if (btn) { btn.disabled = true; btn.style.opacity = '0.5'; }
  try {
    await navigate(_currentPage);
    if (_currentPage === 'dashboard' || _currentPage === 'portfolio') {
      try { await apiGet('/api/portfolio/refresh'); } catch (_) {}
    }
  } finally {
    if (btn) { btn.disabled = false; btn.style.opacity = ''; }
  }
}

function startAutoRefresh() {
  if (_refreshInterval) clearInterval(_refreshInterval);
  _refreshInterval = setInterval(async () => {
    try {
      const data = await apiGet('/api/portfolio/summary');
      updateLiveBadge(data.is_market_open, data.last_updated);
      if (_currentPage === 'dashboard') loadDashboard();
      else if (_currentPage === 'portfolio') loadPortfolio();
    } catch (_) {}
  }, 30_000);
}

function updateLiveBadge(isOpen, lastRefresh) {
  const badge = document.getElementById('liveBadge');
  const text = document.getElementById('liveText');
  const lastEl = document.getElementById('lastUpdate');

  if (badge) {
    badge.classList.toggle('live', !!isOpen);
    badge.classList.toggle('offline', !isOpen);
  }
  if (text) text.textContent = isOpen ? 'LIVE' : 'FERMÉ';
  // lastUpdate span removed from header
}

// ── Portfolio modals injection ────────────────────────────

function injectPortfolioModals() {
  if (document.getElementById('positionModal')) return; // already injected

  const html = `
    <!-- Position modal -->
    <div class="modal-overlay" id="positionModal">
      <div class="modal">
        <div class="modal-header">
          <span class="modal-title" id="posModalTitle">Ajouter une position</span>
          <button class="modal-close" onclick="closeModal('positionModal')">✕</button>
        </div>
        <form onsubmit="submitPositionModal(event)" class="form-grid">
          <div class="form-group full">
            <label class="form-label">Nom affiché</label>
            <input type="text" class="form-input" id="posName" required placeholder="ex: TotalEnergies"/>
          </div>
          <div class="form-group">
            <label class="form-label">Ticker Yahoo Finance</label>
            <input type="text" class="form-input" id="posTicker" required placeholder="ex: TTE.PA"/>
          </div>
          <div class="form-group">
            <label class="form-label">Type</label>
            <select class="form-select" id="posType">
              <option value="action">Action</option>
              <option value="etf">ETF</option>
              <option value="obligation">Obligation</option>
              <option value="crypto">Crypto</option>
              <option value="matiere_premiere">Matière première</option>
              <option value="autre">Autre</option>
            </select>
          </div>
          <div class="form-group">
            <label class="form-label">Devise</label>
            <select class="form-select" id="posCurrency">
              <option value="EUR">EUR</option>
              <option value="USD">USD</option>
              <option value="GBP">GBP</option>
              <option value="CHF">CHF</option>
            </select>
          </div>
          <div class="form-group">
            <label class="form-label">Alerte gain (%)</label>
            <input type="number" class="form-input" id="posAlertGain" step="0.1" placeholder="Optionnel"/>
          </div>
          <div class="form-group">
            <label class="form-label">Alerte perte (%)</label>
            <input type="number" class="form-input" id="posAlertLoss" step="0.1" placeholder="Optionnel"/>
          </div>
          <div class="form-actions">
            <button type="button" class="btn btn-secondary" onclick="closeModal('positionModal')">Annuler</button>
            <button type="submit" class="btn btn-primary" id="posModalBtn">Créer</button>
          </div>
        </form>
      </div>
    </div>

    <!-- Purchase modal -->
    <div class="modal-overlay" id="purchaseModal">
      <div class="modal" style="max-width:420px">
        <div class="modal-header">
          <span class="modal-title" id="purchaseModalTitle">Ajouter un achat</span>
          <button class="modal-close" onclick="closeModal('purchaseModal')">✕</button>
        </div>
        <form onsubmit="submitPurchaseModal(event)" class="form-grid">
          <div class="form-group">
            <label class="form-label">Date</label>
            <input type="date" class="form-input" id="purchaseDate" required/>
          </div>
          <div class="form-group">
            <label class="form-label">Quantité</label>
            <input type="number" class="form-input" id="purchaseQty" step="0.0001" required placeholder="0"/>
          </div>
          <div class="form-group">
            <label class="form-label">Prix unitaire (€)</label>
            <input type="number" class="form-input" id="purchasePrice" step="0.0001" required placeholder="0.00"/>
          </div>
          <div class="form-group">
            <label class="form-label">Frais (€)</label>
            <input type="number" class="form-input" id="purchaseFees" step="0.01" value="0"/>
          </div>
          <div class="form-group full">
            <label class="form-label">Note</label>
            <input type="text" class="form-input" id="purchaseNote" placeholder="Optionnel"/>
          </div>
          <div class="form-actions">
            <button type="button" class="btn btn-secondary" onclick="closeModal('purchaseModal')">Annuler</button>
            <button type="submit" class="btn btn-primary" id="purchaseModalBtn">Enregistrer</button>
          </div>
        </form>
      </div>
    </div>

    <!-- Manual price modal -->
    <div class="modal-overlay" id="manualPriceModal">
      <div class="modal" style="max-width:360px">
        <div class="modal-header">
          <span class="modal-title" id="manualPriceTitle">Cours manuel</span>
          <button class="modal-close" onclick="closeModal('manualPriceModal')">✕</button>
        </div>
        <form onsubmit="submitManualPrice(event)">
          <div class="form-group" style="margin-bottom:20px">
            <label class="form-label">Valeur (€)</label>
            <input type="number" class="form-input" id="manualPriceValue" step="0.0001" required placeholder="0.00"/>
          </div>
          <input type="hidden" id="manualPricePosId"/>
          <div class="form-actions">
            <button type="button" class="btn btn-secondary" onclick="closeModal('manualPriceModal')">Annuler</button>
            <button type="submit" class="btn btn-primary">Mettre à jour</button>
          </div>
        </form>
      </div>
    </div>

    <!-- Alert modal -->
    <div class="modal-overlay" id="alertModal">
      <div class="modal" style="max-width:360px">
        <div class="modal-header">
          <span class="modal-title" id="alertModalTitle">Alertes</span>
          <button class="modal-close" onclick="closeModal('alertModal')">✕</button>
        </div>
        <form onsubmit="submitAlertModal(event)" class="form-grid" style="grid-template-columns:1fr 1fr">
          <div class="form-group">
            <label class="form-label" style="color:var(--accent-green)">Gain (%)</label>
            <input type="number" class="form-input" id="alertGain" step="0.1" placeholder="ex: 10"/>
          </div>
          <div class="form-group">
            <label class="form-label" style="color:var(--accent-red)">Perte (%)</label>
            <input type="number" class="form-input" id="alertLoss" step="0.1" placeholder="ex: 5"/>
          </div>
          <input type="hidden" id="alertPosId"/>
          <div class="form-actions" style="grid-column:1/-1">
            <button type="button" class="btn btn-secondary" onclick="closeModal('alertModal')">Annuler</button>
            <button type="submit" class="btn btn-primary">Enregistrer</button>
          </div>
        </form>
      </div>
    </div>

    <!-- SaxoBank import modal -->
    <div class="modal-overlay" id="saxoImportModal">
      <div class="modal" style="max-width:460px">
        <div class="modal-header">
          <span class="modal-title">📥 Importer depuis SaxoBank</span>
          <button class="modal-close" onclick="closeModal('saxoImportModal')">✕</button>
        </div>
        <div style="background:rgba(59,130,246,.08);border:1px solid rgba(59,130,246,.25);border-radius:10px;padding:14px 16px;margin-bottom:20px">
          <div style="font-size:11px;font-weight:600;text-transform:uppercase;letter-spacing:.06em;color:var(--accent-blue);margin-bottom:10px">📋 Où trouver le fichier ?</div>
          <div style="display:flex;flex-direction:column;gap:6px">
            <div style="display:flex;align-items:center;gap:10px;font-size:13px">
              <span style="background:var(--accent-blue);color:#fff;border-radius:50%;width:20px;height:20px;display:flex;align-items:center;justify-content:center;font-size:11px;font-weight:700;flex-shrink:0">1</span>
              <span style="color:var(--text-secondary)">SaxoBank → <strong style="color:var(--text-primary)">Menu</strong></span>
            </div>
            <div style="display:flex;align-items:center;gap:10px;font-size:13px">
              <span style="background:var(--accent-blue);color:#fff;border-radius:50%;width:20px;height:20px;display:flex;align-items:center;justify-content:center;font-size:11px;font-weight:700;flex-shrink:0">2</span>
              <span style="color:var(--text-secondary)"><strong style="color:var(--text-primary)">Relevés</strong> → Relevé des transactions</span>
            </div>
            <div style="display:flex;align-items:center;gap:10px;font-size:13px">
              <span style="background:var(--accent-blue);color:#fff;border-radius:50%;width:20px;height:20px;display:flex;align-items:center;justify-content:center;font-size:11px;font-weight:700;flex-shrink:0">3</span>
              <span style="color:var(--text-secondary)">Choisir la période → <strong style="color:var(--text-primary)">Télécharger .xlsx</strong></span>
            </div>
          </div>
          <div style="margin-top:10px;padding-top:10px;border-top:1px solid rgba(59,130,246,.2);font-size:11px;color:var(--text-muted)">
            ✓ Les achats déjà importés ne seront jamais dupliqués — tu peux importer la même période plusieurs fois.
          </div>
        </div>
        <form id="saxoImportForm" onsubmit="submitSaxoImport(event)">
          <div class="form-group" style="margin-bottom:20px">
            <label class="form-label">Fichier .xlsx SaxoBank</label>
            <input type="file" class="form-input" id="saxoImportFile" required accept=".xlsx"/>
          </div>
          <div id="saxoImportResult" style="display:none;margin-bottom:16px;padding:12px;border-radius:8px;font-size:13px"></div>
          <div class="form-actions">
            <button type="button" class="btn btn-secondary" onclick="closeModal('saxoImportModal')">Fermer</button>
            <button type="submit" class="btn btn-primary" id="saxoImportBtn">📥 Importer</button>
          </div>
        </form>
      </div>
    </div>`;

  const container = document.createElement('div');
  container.id = 'portfolioModals';
  container.innerHTML = html;
  document.body.appendChild(container);
}

// ── Export USB ────────────────────────────────────────────

function openExportModal() {
  const dd = document.getElementById('userDropdown');
  if (dd) dd.style.display = 'none';
  document.getElementById('exportPassphrase').value = '';
  document.getElementById('exportPassphrase2').value = '';
  openModal('exportModal');
}

async function submitExport(e) {
  e.preventDefault();
  const pass = document.getElementById('exportPassphrase').value;
  const pass2 = document.getElementById('exportPassphrase2').value;
  if (pass !== pass2) { showToast('Les passphrases ne correspondent pas', 'error'); return; }
  if (pass.length < 6) { showToast('Passphrase trop courte (6 caractères minimum)', 'error'); return; }

  const btn = document.getElementById('exportBtn');
  btn.disabled = true;
  btn.textContent = '⏳ Génération en cours…';

  try {
    const res = await apiFetchRaw('/api/export', {
      method: 'POST',
      body: JSON.stringify({ passphrase: pass }),
      headers: { 'Content-Type': 'application/json' },
    });
    if (!res.ok) {
      let detail = 'Erreur serveur';
      try { const e = await res.json(); detail = e.detail || detail; } catch {}
      throw new Error(detail);
    }

    const blob = await res.blob();
    const today = new Date().toISOString().slice(0, 10);
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = `patrimonium-export-${today}.html`;
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    URL.revokeObjectURL(url);

    showToast('Export téléchargé avec succès', 'success');
    closeModal('exportModal');
  } catch (err) {
    showToast('Erreur export : ' + err.message, 'error');
  } finally {
    btn.disabled = false;
    btn.textContent = '⬇ Générer et télécharger';
  }
}

// ── Bootstrap ─────────────────────────────────────────────

document.addEventListener('DOMContentLoaded', () => {
  bootAuth();
});
