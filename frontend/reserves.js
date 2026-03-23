/* ═══════════════════════════════════════════════
   RESERVES — Financial reserves module
   ═══════════════════════════════════════════════ */
'use strict';

let _reservesData = { stats: {}, items: [] };
let _reserveEditId = null;

async function loadReserves() {
  try {
    _reservesData = await apiGet('/api/reserves');
    renderReservesPage();
  } catch (err) {
    showToast('Erreur réserves: ' + err.message, 'error');
  }
}

function renderReservesPage() {
  const page = document.getElementById('page-reserves');
  if (!page) return;
  const { stats, items } = _reservesData;

  // Group by year
  const byYear = {};
  items.forEach(r => {
    if (!byYear[r.year]) byYear[r.year] = [];
    byYear[r.year].push(r);
  });
  const years = Object.keys(byYear).sort((a, b) => b - a);

  page.innerHTML = `
    <div style="display:flex;align-items:center;justify-content:space-between;margin-bottom:20px">
      <div class="page-title">🏦 Réserves financières</div>
      ${isAdmin() ? `<div style="display:flex;gap:8px">
        <button class="btn btn-secondary btn-sm" onclick="initializeReserves()">Initialiser 2013–2035</button>
        <button class="btn btn-primary btn-sm" onclick="openAddReserveModal()">+ Ajouter</button>
      </div>` : ''}
    </div>

    <!-- Stats -->
    <div class="grid-3" style="margin-bottom:20px">
      <div class="hero-card">
        <div class="card-label">💰 Total constitué</div>
        <div class="hero-card-value blue">${fmtEur(stats.total_amount || 0)}</div>
      </div>
      <div class="hero-card">
        <div class="card-label">✅ Total libéré</div>
        <div class="hero-card-value green">${fmtEur(stats.total_released || 0)}</div>
      </div>
      <div class="hero-card">
        <div class="card-label">⏳ Libérable</div>
        <div class="hero-card-value gold">${fmtEur(stats.total_releasable || 0)}</div>
      </div>
    </div>

    <!-- Table by year -->
    <div class="card" style="padding:0;overflow:hidden">
      <div class="table-wrap">
        <table class="data-table" id="reservesTable">
          <thead><tr>
            <th class="left" style="padding-left:24px">Période</th>
            <th>Montant constitué</th>
            <th>Année libération</th>
            <th>Libéré</th>
            <th>Libérable</th>
            <th class="left">Note</th>
            ${isAdmin() ? '<th>Actions</th>' : ''}
          </tr></thead>
          <tbody id="reservesBody">${renderReserveRows(years, byYear)}</tbody>
        </table>
      </div>
    </div>

    <!-- Add modal -->
    <div class="modal-overlay" id="reserveModal">
      <div class="modal">
        <div class="modal-header"><span class="modal-title" id="reserveModalTitle">Ajouter une réserve</span><button class="modal-close" onclick="closeModal('reserveModal')">✕</button></div>
        <form onsubmit="submitReserveModal(event)" class="form-grid">
          <div class="form-group"><label class="form-label">Année</label><input type="number" class="form-input" id="resYear" min="2000" max="2050" required/></div>
          <div class="form-group"><label class="form-label">Mois</label>
            <select class="form-select" id="resMonth">
              ${['Jan','Fév','Mar','Avr','Mai','Jun','Jul','Aoû','Sep','Oct','Nov','Déc'].map((m, i) => `<option value="${i+1}">${m}</option>`).join('')}
            </select>
          </div>
          <div class="form-group"><label class="form-label">Montant (€)</label><input type="number" class="form-input" id="resAmount" step="0.01" placeholder="0.00"/></div>
          <div class="form-group"><label class="form-label">Année libération</label><input type="number" class="form-input" id="resReleaseYear" min="2000" max="2060" placeholder="Optionnel"/></div>
          <div class="form-group"><label class="form-label">Libéré (€)</label><input type="number" class="form-input" id="resReleased" step="0.01" value="0"/></div>
          <div class="form-group full"><label class="form-label">Note</label><input type="text" class="form-input" id="resNotes" placeholder="Optionnel"/></div>
          <input type="hidden" id="resModalId"/>
          <div class="form-actions"><button type="button" class="btn btn-secondary" onclick="closeModal('reserveModal')">Annuler</button><button type="submit" class="btn btn-primary" id="resModalBtn">Créer</button></div>
        </form>
      </div>
    </div>`;
}

function renderReserveRows(years, byYear) {
  if (!years.length) return `<tr><td colspan="${isAdmin() ? 7 : 6}"><div class="empty-state"><div class="empty-icon">🏦</div><div class="empty-text">Aucune réserve</div>${isAdmin() ? `<button class="btn btn-primary btn-sm" style="margin-top:12px" onclick="initializeReserves()">Initialiser 2013–2035</button>` : ''}</div></td></tr>`;

  return years.map(year => {
    const rows = byYear[year];
    const yearTotal = rows.reduce((s, r) => s + (r.amount || 0), 0);
    const yearReleased = rows.reduce((s, r) => s + (r.released || 0), 0);
    const nonZero = rows.filter(r => r.amount > 0 || r.released > 0 || r.notes);

    const monthRows = nonZero.map(r => `
      <tr class="no-cursor" id="reserve-row-${r.id}">
        <td class="left" style="padding-left:24px;color:var(--text-secondary)">${r.month_label}</td>
        <td>${isAdmin()
          ? `<input type="number" class="reserves-inline-input" value="${r.amount}" step="0.01" onchange="updateReserveInline(${r.id},'amount',this.value)" style="width:100px"/>`
          : fmtEur(r.amount)}</td>
        <td>${isAdmin()
          ? `<input type="number" class="reserves-inline-input" value="${r.release_year ?? ''}" placeholder="—" onchange="updateReserveInline(${r.id},'release_year',this.value)" style="width:70px"/>`
          : (r.release_year ?? '—')}</td>
        <td>${isAdmin()
          ? `<input type="number" class="reserves-inline-input" value="${r.released}" step="0.01" onchange="updateReserveInline(${r.id},'released',this.value)" style="width:100px"/>`
          : fmtEur(r.released)}</td>
        <td class="${r.releasable > 0 ? 'pos' : 'neutral'}">${fmtEur(r.releasable)}</td>
        <td class="left">${isAdmin()
          ? `<input type="text" class="reserves-inline-input" value="${escHtml(r.notes || '')}" placeholder="—" onchange="updateReserveInline(${r.id},'notes',this.value)" style="width:150px"/>`
          : escHtml(r.notes || '—')}</td>
        ${isAdmin() ? `<td><button class="btn btn-ghost danger btn-sm" onclick="deleteReserveConfirm(${r.id})">🗑</button></td>` : ''}
      </tr>`).join('');

    return `
      <tr class="no-cursor" style="background:var(--bg-tertiary)">
        <td class="left" colspan="${isAdmin() ? 7 : 6}" style="padding:8px 24px;font-size:11px;font-weight:600;letter-spacing:.08em;text-transform:uppercase;color:var(--text-secondary)">
          ${year} — Total: <span style="color:var(--accent-blue)">${fmtEur(yearTotal)}</span> · Libéré: <span style="color:var(--accent-green)">${fmtEur(yearReleased)}</span>
        </td>
      </tr>
      ${monthRows}`;
  }).join('');
}

async function updateReserveInline(id, field, value) {
  try {
    const body = { [field]: field === 'notes' ? (value || null) : (parseFloat(value) || null) };
    await apiPut(`/api/reserves/${id}`, body);
    // Silently refresh stats
    const data = await apiGet('/api/reserves');
    _reservesData = data;
  } catch (err) {
    showToast('Erreur: ' + err.message, 'error');
  }
}

function openAddReserveModal() {
  document.getElementById('reserveModalTitle').textContent = 'Ajouter une réserve';
  document.getElementById('resModalBtn').textContent = 'Créer';
  document.getElementById('resModalId').value = '';
  document.getElementById('resYear').value = new Date().getFullYear();
  document.getElementById('resMonth').value = new Date().getMonth() + 1;
  document.getElementById('resAmount').value = '';
  document.getElementById('resReleaseYear').value = '';
  document.getElementById('resReleased').value = '0';
  document.getElementById('resNotes').value = '';
  openModal('reserveModal');
}

async function submitReserveModal(e) {
  e.preventDefault();
  const id = document.getElementById('resModalId').value;
  const body = {
    year: parseInt(document.getElementById('resYear').value),
    month: parseInt(document.getElementById('resMonth').value),
    amount: parseFloat(document.getElementById('resAmount').value) || 0,
    release_year: parseInt(document.getElementById('resReleaseYear').value) || null,
    released: parseFloat(document.getElementById('resReleased').value) || 0,
    notes: document.getElementById('resNotes').value || null,
  };
  try {
    if (id) { await apiPut(`/api/reserves/${id}`, body); showToast('Réserve mise à jour', 'success'); }
    else { await apiPost('/api/reserves', body); showToast('Réserve créée', 'success'); }
    closeModal('reserveModal');
    await loadReserves();
  } catch (err) { showToast(err.message, 'error'); }
}

function deleteReserveConfirm(id) {
  confirm('Supprimer la réserve', 'Supprimer cette réserve ?', async () => {
    try { await apiDelete(`/api/reserves/${id}`); showToast('Réserve supprimée', 'success'); await loadReserves(); }
    catch (err) { showToast(err.message, 'error'); }
  });
}

async function initializeReserves() {
  try {
    const r = await apiPost('/api/reserves/initialize', {});
    showToast(`${r.created} réserves créées (2013–2035)`, 'success');
    await loadReserves();
  } catch (err) { showToast(err.message, 'error'); }
}
