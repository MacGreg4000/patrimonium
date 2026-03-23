/* ═══════════════════════════════════════════════
   COFFRES — Cash management module
   ═══════════════════════════════════════════════ */
'use strict';

const DENOMS = [500, 200, 100, 50, 20, 10, 5];
let _coffresData = [];
let _selectedCoffreId = null;
let _caissMode = 'entry'; // entry | exit | inventory

async function loadCoffres() {
  try {
    _coffresData = await apiGet('/api/coffres');
    renderCoffresPage();
  } catch (err) {
    showToast('Erreur coffres: ' + err.message, 'error');
  }
}

function renderCoffresPage() {
  const page = document.getElementById('page-coffres');
  if (!page) return;

  const totalCash = _coffresData.reduce((s, c) => s + c.balance, 0);

  page.innerHTML = `
    <div style="display:flex;align-items:center;justify-content:space-between;margin-bottom:20px">
      <div class="page-title">🏦 Coffres & Liquidités</div>
      ${isAdmin() ? `<button class="btn btn-primary btn-sm" onclick="navigate('admin')">⚙ Gérer les coffres</button>` : ''}
    </div>

    <!-- Total -->
    <div class="hero-grid" style="grid-template-columns:repeat(${_coffresData.length + 1},1fr);margin-bottom:20px">
      <div class="hero-card">
        <div class="card-label">💰 Total liquidités</div>
        <div class="hero-card-value gold">${fmtEur(totalCash)}</div>
        <div class="hero-card-sub">${_coffresData.length} coffre${_coffresData.length > 1 ? 's' : ''}</div>
      </div>
      ${_coffresData.map(c => `
      <div class="hero-card" style="cursor:pointer" onclick="selectCoffre(${c.id})">
        <div class="card-label">🏦 ${escHtml(c.name)}</div>
        <div class="hero-card-value ${_selectedCoffreId === c.id ? 'blue' : 'green'}">${fmtEur(c.balance)}</div>
        <div class="hero-card-sub" style="color:var(--text-muted)">Cliquer pour sélectionner</div>
      </div>`).join('')}
    </div>

    <!-- Caisse -->
    ${_coffresData.length === 0 ? `<div class="card"><div class="empty-state"><div class="empty-icon">🏦</div><div class="empty-text">Aucun coffre disponible</div>${isAdmin() ? `<div class="empty-sub">Créez un coffre depuis l'administration</div>` : ''}</div></div>` : renderCaisseInterface()}

    <!-- History -->
    <div class="card" style="padding:0;overflow:hidden;margin-top:20px" id="coffresHistorySection">
      <div class="section-header">
        <div class="section-title">Historique <span class="section-count" id="historyCount">—</span></div>
        <div style="display:flex;gap:8px">
          <select class="form-select" style="width:auto;padding:6px 10px" id="histCoffreFilter" onchange="loadHistory()">
            <option value="">Tous les coffres</option>
            ${_coffresData.map(c => `<option value="${c.id}">${escHtml(c.name)}</option>`).join('')}
          </select>
        </div>
      </div>
      <div id="historyBody" style="padding:0">
        <div class="empty-state"><div class="empty-icon">📋</div><div class="empty-text">Chargement…</div></div>
      </div>
    </div>`;

  if (_coffresData.length > 0) {
    if (!_selectedCoffreId) _selectedCoffreId = _coffresData[0].id;
    loadHistory();
  }
}

function renderCaisseInterface() {
  if (!_coffresData.length) return '';
  const coffre = _coffresData.find(c => c.id === _selectedCoffreId) || _coffresData[0];

  return `
    <div class="card">
      <div style="display:flex;align-items:center;justify-content:space-between;margin-bottom:16px">
        <div style="display:flex;align-items:center;gap:10px">
          <select class="form-select" style="width:auto" id="caisseSelect" onchange="selectCoffre(parseInt(this.value))">
            ${_coffresData.map(c => `<option value="${c.id}" ${c.id === coffre.id ? 'selected' : ''}>${escHtml(c.name)}</option>`).join('')}
          </select>
          <div style="font-family:var(--font-display);font-size:24px;color:var(--accent-gold)">${fmtEur(coffre.balance)}</div>
        </div>
        ${isAdmin() ? `<div class="tabs" style="margin-bottom:0;flex:none">
          <button class="tab-btn ${_caissMode === 'entry' ? 'active' : ''}" onclick="setCaisseMode('entry')">Entrée</button>
          <button class="tab-btn ${_caissMode === 'exit' ? 'active' : ''}" onclick="setCaisseMode('exit')">Sortie</button>
          <button class="tab-btn ${_caissMode === 'inventory' ? 'active' : ''}" onclick="setCaisseMode('inventory')">Inventaire</button>
        </div>` : `<span class="badge badge-inventory">Lecture seule</span>`}
      </div>

      ${isAdmin() ? renderBilletForm(coffre) : `<div style="color:var(--text-secondary);font-size:13px;text-align:center;padding:24px">Accès en lecture seule — solde actuel: <strong style="color:var(--accent-gold)">${fmtEur(coffre.balance)}</strong></div>`}
    </div>`;
}

function renderBilletForm(coffre) {
  const modeLabel = { inventory: 'Inventaire complet', entry: 'Entrée de fonds', exit: 'Sortie de fonds' };
  const modeColor = { inventory: 'var(--accent-blue)', entry: 'var(--accent-green)', exit: 'var(--accent-red)' };

  return `
    <div style="margin-bottom:12px">
      <span style="font-size:12px;font-weight:500;color:${modeColor[_caissMode]};text-transform:uppercase;letter-spacing:.08em">${modeLabel[_caissMode]}</span>
    </div>
    <form onsubmit="submitCaisse(event)" id="caisseForm">
      <div class="billet-grid">
        ${DENOMS.map(d => `
          <div class="billet-item">
            <div class="billet-denom">${d} €</div>
            <input type="number" class="billet-qty-input" id="billet_${d}" min="0" value="0"
              oninput="updateCaisseTotal()" placeholder="0"/>
            <div class="billet-subtotal" id="sub_${d}">0 €</div>
          </div>`).join('')}
      </div>
      <div style="display:flex;align-items:center;justify-content:space-between;padding:16px 0;border-top:1px solid var(--border);border-bottom:1px solid var(--border);margin-bottom:16px">
        <span style="font-size:13px;color:var(--text-secondary)">${_caissMode === 'inventory' ? 'Total compté' : _caissMode === 'entry' ? 'Montant entrant' : 'Montant sortant'}</span>
        <div class="cash-total" id="caisseTotal">0,00 €</div>
      </div>
      <div class="form-group" style="margin-bottom:16px">
        <label class="form-label">Note (optionnel)</label>
        <textarea class="form-textarea" id="caisseNote" rows="2" placeholder="Commentaire…"></textarea>
      </div>
      <button type="submit" class="btn btn-primary" style="width:100%;justify-content:center">
        ${_caissMode === 'inventory' ? 'Enregistrer l\'inventaire' : _caissMode === 'entry' ? 'Valider l\'entrée' : 'Valider la sortie'}
      </button>
    </form>`;
}

function updateCaisseTotal() {
  let total = 0;
  DENOMS.forEach(d => {
    const qty = parseInt(document.getElementById(`billet_${d}`)?.value || 0) || 0;
    const sub = qty * d;
    total += sub;
    const subEl = document.getElementById(`sub_${d}`);
    if (subEl) subEl.textContent = sub > 0 ? fmtEur(sub) : '0 €';
  });
  const el = document.getElementById('caisseTotal');
  if (el) el.textContent = fmtEur(total);
}

function setCaisseMode(mode) {
  _caissMode = mode;
  renderCoffresPage();
}

function selectCoffre(coffreId) {
  _selectedCoffreId = coffreId;
  renderCoffresPage();
}

async function submitCaisse(e) {
  e.preventDefault();
  const details = DENOMS.map(d => ({
    denomination: d,
    quantity: parseInt(document.getElementById(`billet_${d}`)?.value || 0) || 0,
  })).filter(d => d.quantity > 0);

  const total = details.reduce((s, d) => s + d.denomination * d.quantity, 0);
  const note = document.getElementById('caisseNote')?.value || null;
  const coffreId = _selectedCoffreId;

  try {
    if (_caissMode === 'inventory') {
      await apiPost('/api/inventories', { coffre_id: coffreId, total_amount: total, notes: note, details });
      showToast('Inventaire enregistré', 'success');
    } else {
      await apiPost('/api/movements', {
        coffre_id: coffreId, type: _caissMode === 'entry' ? 'ENTRY' : 'EXIT',
        amount: total, description: note, details,
      });
      showToast(_caissMode === 'entry' ? 'Entrée enregistrée' : 'Sortie enregistrée', 'success');
    }
    await loadCoffres();
  } catch (err) {
    showToast(err.message, 'error');
  }
}

async function loadHistory() {
  const coffreId = document.getElementById('histCoffreFilter')?.value || '';
  try {
    let url = `/api/movements?limit=50${coffreId ? '&coffre_id=' + coffreId : ''}`;
    const mvData = await apiGet(url);
    let url2 = `/api/inventories?limit=20${coffreId ? '&coffre_id=' + coffreId : ''}`;
    const invData = await apiGet(url2);

    const items = [
      ...(mvData.items || []).map(m => ({ ...m, kind: 'movement' })),
      ...(invData.items || []).map(i => ({ ...i, kind: 'inventory' })),
    ].sort((a, b) => {
      const da = new Date(a.created_at || a.date);
      const db_ = new Date(b.created_at || b.date);
      return db_ - da;
    }).slice(0, 50);

    const countEl = document.getElementById('historyCount');
    if (countEl) countEl.textContent = items.length;

    const body = document.getElementById('historyBody');
    if (!body) return;

    if (!items.length) {
      body.innerHTML = `<div class="empty-state"><div class="empty-icon">📋</div><div class="empty-text">Aucun mouvement</div></div>`;
      return;
    }

    const coffreMap = Object.fromEntries(_coffresData.map(c => [c.id, c.name]));

    body.innerHTML = `<table class="data-table">
      <thead><tr>
        <th class="left">Date</th><th class="left">Coffre</th><th class="left">Type</th>
        <th>Montant</th><th class="left">Note</th>
        ${isAdmin() ? '<th>Actions</th>' : ''}
      </tr></thead>
      <tbody>${items.map(item => {
        const date = fmtDateTime(item.created_at || item.date);
        const coffreName = coffreMap[item.coffre_id] || `#${item.coffre_id}`;
        if (item.kind === 'inventory') {
          return `<tr class="no-cursor">
            <td class="left">${date}</td>
            <td class="left">${escHtml(coffreName)}</td>
            <td class="left"><span class="badge badge-inventory">Inventaire</span></td>
            <td class="pos">${fmtEur(item.total_amount)}</td>
            <td class="left" style="color:var(--text-secondary)">${escHtml(item.notes || '—')}</td>
            ${isAdmin() ? `<td><button class="btn btn-ghost danger btn-sm" onclick="deleteInventory(${item.id})">🗑</button></td>` : ''}
          </tr>`;
        } else {
          return `<tr class="no-cursor">
            <td class="left">${date}</td>
            <td class="left">${escHtml(coffreName)}</td>
            <td class="left"><span class="badge badge-${item.type.toLowerCase()}">${item.type === 'ENTRY' ? 'Entrée' : 'Sortie'}</span></td>
            <td class="${item.type === 'ENTRY' ? 'pos' : 'neg'}">${item.type === 'EXIT' ? '-' : '+'}${fmtEur(item.amount)}</td>
            <td class="left" style="color:var(--text-secondary)">${escHtml(item.description || '—')}</td>
            ${isAdmin() ? `<td><button class="btn btn-ghost danger btn-sm" onclick="deleteMovement(${item.id})">🗑</button></td>` : ''}
          </tr>`;
        }
      }).join('')}</tbody></table>`;
  } catch (err) {
    showToast('Erreur historique: ' + err.message, 'error');
  }
}

async function deleteMovement(id) {
  confirm('Supprimer le mouvement', 'Supprimer ce mouvement de l\'historique ?', async () => {
    try {
      await apiDelete(`/api/movements/${id}`);
      showToast('Mouvement supprimé', 'success');
      await loadCoffres();
    } catch (err) { showToast(err.message, 'error'); }
  });
}

async function deleteInventory(id) {
  confirm('Supprimer l\'inventaire', 'Supprimer cet inventaire ?', async () => {
    try {
      await apiDelete(`/api/inventories/${id}`);
      showToast('Inventaire supprimé', 'success');
      await loadCoffres();
    } catch (err) { showToast(err.message, 'error'); }
  });
}
