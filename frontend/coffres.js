/* ═══════════════════════════════════════════════
   COFFRES — Cash management module
   ═══════════════════════════════════════════════ */
'use strict';

const DENOMS = [500, 200, 100, 50, 20, 10, 5];
let _coffresData = [];
let _selectedCoffreId = null;
let _caissMode = 'entry'; // entry | exit | inventory
let _editMovementId = null;

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
      <div class="page-title">${ICONS.landmark} Coffres & Liquidités</div>
      ${isAdmin() ? `<button class="btn btn-primary btn-sm" onclick="navigate('admin')">${ICONS.settings} Gérer les coffres</button>` : ''}
    </div>

    <!-- Total -->
    <div class="hero-grid" style="grid-template-columns:repeat(${_coffresData.length + 1},1fr);margin-bottom:20px">
      <div class="hero-card">
        <div class="card-label">${ICONS.coins} Total liquidités</div>
        <div class="hero-card-value gold">${fmtEur(totalCash)}</div>
        <div class="hero-card-sub">${_coffresData.length} coffre${_coffresData.length > 1 ? 's' : ''}</div>
      </div>
      ${_coffresData.map(c => `
      <div class="hero-card" style="cursor:pointer" onclick="selectCoffre(${c.id})">
        <div class="card-label">${ICONS.landmark} ${escHtml(c.name)}</div>
        <div class="hero-card-value ${_selectedCoffreId === c.id ? 'blue' : 'green'}">${fmtEur(c.balance)}</div>
        <div class="hero-card-sub" style="color:var(--text-muted)">Cliquer pour sélectionner</div>
      </div>`).join('')}
    </div>

    <!-- Caisse -->
    ${_coffresData.length === 0
      ? `<div class="card"><div class="empty-state"><div class="empty-icon">${ICONS.landmark}</div><div class="empty-text">Aucun coffre disponible</div>${isAdmin() ? `<div class="empty-sub">Créez un coffre depuis l'administration</div>` : ''}</div></div>`
      : renderCaisseInterface()}

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
    </div>

    <!-- Edit movement modal -->
    <div class="modal-overlay" id="editMovementModal">
      <div class="modal">
        <div class="modal-header">
          <span class="modal-title">Modifier le mouvement</span>
          <button class="modal-close" onclick="closeModal('editMovementModal')">✕</button>
        </div>
        <form onsubmit="submitEditMovement(event)" class="form-grid">
          <div class="form-group full"><label class="form-label">Montant (€)</label><input type="number" class="form-input" id="editMvtAmount" step="0.01" required/></div>
          <div class="form-group full"><label class="form-label">Note</label><textarea class="form-textarea" id="editMvtDesc" rows="2" placeholder="Optionnel"></textarea></div>
          <div class="form-actions">
            <button type="button" class="btn btn-secondary" onclick="closeModal('editMovementModal')">Annuler</button>
            <button type="submit" class="btn btn-primary">Enregistrer</button>
          </div>
        </form>
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
      <!-- Coffre selector row -->
      <div style="display:flex;align-items:center;gap:12px;margin-bottom:20px">
        <select class="form-select" style="width:auto" id="caisseSelect" onchange="selectCoffre(parseInt(this.value))">
          ${_coffresData.map(c => `<option value="${c.id}" ${c.id === coffre.id ? 'selected' : ''}>${escHtml(c.name)}</option>`).join('')}
        </select>
        <div style="font-family:var(--font-display);font-size:22px;color:var(--accent-gold)">${fmtEur(coffre.balance)}</div>
      </div>

      ${isAdmin() ? renderAdminCaisseSection(coffre) : `
        <div style="color:var(--text-secondary);font-size:13px;text-align:center;padding:24px">
          Accès en lecture seule — solde actuel : <strong style="color:var(--accent-gold)">${fmtEur(coffre.balance)}</strong>
        </div>`}
    </div>`;
}

function renderAdminCaisseSection(coffre) {
  const modeConfig = {
    entry:     { label: 'Entrée de fonds',     color: 'var(--accent-green)', btnClass: 'btn-caisse-entry',     icon: '↑' },
    exit:      { label: 'Sortie de fonds',      color: 'var(--accent-red)',  btnClass: 'btn-caisse-exit',      icon: '↓' },
    inventory: { label: 'Inventaire complet',   color: 'var(--accent-blue)', btnClass: 'btn-caisse-inventory', icon: '≡' },
  };
  const current = modeConfig[_caissMode];

  return `
    <!-- Mode selector — large, centred buttons -->
    <div style="display:flex;justify-content:center;gap:12px;margin-bottom:24px">
      ${Object.entries(modeConfig).map(([mode, cfg]) => `
        <button onclick="setCaisseMode('${mode}')"
          class="btn-caisse-mode ${_caissMode === mode ? 'active ' + cfg.btnClass : ''}"
          style="${_caissMode === mode ? `background:${cfg.color};border-color:${cfg.color};color:#fff` : `border-color:${cfg.color};color:${cfg.color}`}">
          <span style="font-size:18px;line-height:1">${cfg.icon}</span>
          <span>${mode === 'entry' ? 'Entrée' : mode === 'exit' ? 'Sortie' : 'Inventaire'}</span>
        </button>`).join('')}
    </div>

    <div style="font-size:12px;font-weight:500;color:${current.color};text-transform:uppercase;letter-spacing:.08em;margin-bottom:12px;text-align:center">${current.label}</div>

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
      <button type="submit" class="btn btn-primary" style="width:100%;justify-content:center;padding:13px">
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
    const [mvData, invData] = await Promise.all([
      apiGet(`/api/movements?limit=50${coffreId ? '&coffre_id=' + coffreId : ''}`),
      apiGet(`/api/inventories?limit=20${coffreId ? '&coffre_id=' + coffreId : ''}`),
    ]);

    const items = [
      ...(mvData.items || []).map(m => ({ ...m, kind: 'movement' })),
      ...(invData.items || []).map(i => ({ ...i, kind: 'inventory' })),
    ].sort((a, b) => new Date(b.created_at || b.date) - new Date(a.created_at || a.date)).slice(0, 50);

    const countEl = document.getElementById('historyCount');
    if (countEl) countEl.textContent = items.length;

    const body = document.getElementById('historyBody');
    if (!body) return;

    if (!items.length) {
      body.innerHTML = `<div class="empty-state"><div class="empty-icon">📋</div><div class="empty-text">Aucun mouvement</div></div>`;
      return;
    }

    const coffreMap = Object.fromEntries(_coffresData.map(c => [c.id, c.name]));
    const adminCols = isAdmin() ? '<th>Actions</th>' : '';

    body.innerHTML = `<table class="data-table">
      <thead><tr>
        <th class="left">Date</th><th class="left">Coffre</th><th class="left">Type</th>
        <th>Montant</th><th class="left">Note</th>${adminCols}
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
            ${isAdmin() ? `<td style="display:flex;gap:4px">
              <button class="btn btn-ghost btn-sm" onclick="openEditMovementModal(${item.id},${item.amount},${JSON.stringify(item.description||'')})">✏</button>
              <button class="btn btn-ghost danger btn-sm" onclick="deleteMovement(${item.id})">🗑</button>
            </td>` : ''}
          </tr>`;
        }
      }).join('')}</tbody></table>`;
  } catch (err) {
    showToast('Erreur historique: ' + err.message, 'error');
  }
}

function openEditMovementModal(id, amount, description) {
  _editMovementId = id;
  document.getElementById('editMvtAmount').value = amount;
  document.getElementById('editMvtDesc').value = description || '';
  openModal('editMovementModal');
}

async function submitEditMovement(e) {
  e.preventDefault();
  const amount = parseFloat(document.getElementById('editMvtAmount').value);
  const description = document.getElementById('editMvtDesc').value || null;
  try {
    await apiPut(`/api/movements/${_editMovementId}`, { amount, description });
    showToast('Mouvement modifié', 'success');
    closeModal('editMovementModal');
    await loadCoffres();
  } catch (err) { showToast(err.message, 'error'); }
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
