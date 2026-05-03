/* ═══════════════════════════════════════════════
   RESERVES — Financial reserves module
   ═══════════════════════════════════════════════ */
'use strict';

let _reservesData = { stats: {}, items: [] };

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

  // Aggregate by year (sum amounts when multiple month entries exist)
  const byYear = {};
  items.forEach(r => {
    if (!byYear[r.year]) {
      byYear[r.year] = { id: r.id, year: r.year, amount: 0, released: 0, releasable: 0, release_year: r.release_year, notes: r.notes };
    }
    byYear[r.year].amount    += r.amount  || 0;
    byYear[r.year].released  += r.released || 0;
    byYear[r.year].releasable = Math.max(0, byYear[r.year].amount - byYear[r.year].released);
    // For single-entry years, keep release_year / notes from that entry
  });
  const years = Object.keys(byYear).sort((a, b) => b - a);

  page.innerHTML = `
    <div style="display:flex;align-items:center;justify-content:space-between;margin-bottom:20px">
      <div class="page-title">${ICONS.wallet} Réserves financières</div>
      ${isAdmin() ? `<button class="btn btn-primary btn-sm" onclick="openAddReserveModal()">+ Ajouter une année</button>` : ''}
    </div>

    <!-- Stats -->
    <div class="grid-3" style="margin-bottom:20px">
      <div class="hero-card">
        <div class="card-label">${ICONS.coins} Total constitué</div>
        <div class="hero-card-value blue">${fmtEur(stats.total_amount || 0)}</div>
      </div>
      <div class="hero-card">
        <div class="card-label">${ICONS.chartUp} Total libéré</div>
        <div class="hero-card-value green">${fmtEur(stats.total_released || 0)}</div>
      </div>
      <div class="hero-card">
        <div class="card-label">${ICONS.wallet} Libérable</div>
        <div class="hero-card-value gold">${fmtEur(stats.total_releasable || 0)}</div>
      </div>
    </div>

    <!-- Table by year -->
    <div class="card" style="padding:0;overflow:hidden">
      <div class="table-wrap">
        <table class="data-table" id="reservesTable">
          <thead><tr>
            <th class="left" style="padding-left:24px">Année</th>
            <th>Montant constitué</th>
            <th>Année libération</th>
            <th>Libéré</th>
            <th class="${isAdmin() ? '' : 'right'}">Libérable</th>
            <th class="left">Note</th>
            ${isAdmin() ? '<th>Actions</th>' : ''}
          </tr></thead>
          <tbody id="reservesBody">${renderReserveRows(years, byYear, items)}</tbody>
        </table>
      </div>
    </div>

    <!-- Add/Edit modal -->
    <div class="modal-overlay" id="reserveModal">
      <div class="modal">
        <div class="modal-header">
          <span class="modal-title" id="reserveModalTitle">Ajouter une réserve</span>
          <button class="modal-close" onclick="closeModal('reserveModal')">✕</button>
        </div>
        <form onsubmit="submitReserveModal(event)" class="form-grid">
          <div class="form-group"><label class="form-label">Année</label><input type="number" class="form-input" id="resYear" min="2000" max="2060" required/></div>
          <div class="form-group"><label class="form-label">Montant constitué (€)</label><input type="number" class="form-input" id="resAmount" step="0.01" placeholder="0.00"/></div>
          <div class="form-group"><label class="form-label">Année de libération</label><input type="number" class="form-input" id="resReleaseYear" min="2000" max="2060" placeholder="Optionnel"/></div>
          <div class="form-group"><label class="form-label">Déjà libéré (€)</label><input type="number" class="form-input" id="resReleased" step="0.01" value="0"/></div>
          <div class="form-group full"><label class="form-label">Note</label><input type="text" class="form-input" id="resNotes" placeholder="Optionnel"/></div>
          <input type="hidden" id="resModalId"/>
          <div class="form-actions">
            <button type="button" class="btn btn-secondary" onclick="closeModal('reserveModal')">Annuler</button>
            <button type="submit" class="btn btn-primary" id="resModalBtn">Créer</button>
          </div>
        </form>
      </div>
    </div>`;
}

function renderReserveRows(years, byYear, allItems) {
  const cols = isAdmin() ? 7 : 6;
  if (!years.length) {
    return `<tr><td colspan="${cols}"><div class="empty-state">
      <div class="empty-icon">${ICONS.wallet}</div>
      <div class="empty-text">Aucune réserve enregistrée</div>
      ${isAdmin() ? `<button class="btn btn-primary btn-sm" style="margin-top:12px" onclick="openAddReserveModal()">+ Ajouter une année</button>` : ''}
    </div></td></tr>`;
  }

  return years.map(year => {
    const row = byYear[year];
    // Find the canonical DB id for this year (first matching item)
    const dbItem = allItems.find(r => r.year === parseInt(year));
    const dbId = dbItem ? dbItem.id : null;

    return `
      <tr class="no-cursor" id="reserve-row-${dbId}">
        <td class="left" style="padding-left:24px;font-weight:600">${year}</td>
        <td>
          ${isAdmin()
            ? `<span class="editable-cell" onclick="startEditCell(this, ${dbId}, 'amount', ${row.amount})">${fmtEur(row.amount)}</span>`
            : fmtEur(row.amount)}
        </td>
        <td>
          ${isAdmin()
            ? `<span class="editable-cell" onclick="startEditCellRaw(this, ${dbId}, 'release_year', ${row.release_year ?? ''})">${row.release_year ?? '—'}</span>`
            : (row.release_year ?? '—')}
        </td>
        <td>
          ${isAdmin()
            ? `<span class="editable-cell" onclick="startEditCell(this, ${dbId}, 'released', ${row.released})">${fmtEur(row.released)}</span>`
            : fmtEur(row.released)}
        </td>
        <td class="${row.releasable > 0 ? 'pos' : 'neutral'}">${fmtEur(row.releasable)}</td>
        <td class="left">
          ${isAdmin()
            ? `<span class="editable-cell" onclick="startEditCellText(this, ${dbId}, 'notes', ${JSON.stringify(row.notes || '')})">${escHtml(row.notes || '—')}</span>`
            : escHtml(row.notes || '—')}
        </td>
        ${isAdmin() ? `<td><button class="btn btn-ghost danger btn-sm" onclick="deleteReserveConfirm(${dbId})">🗑</button></td>` : ''}
      </tr>`;
  }).join('');
}

// ── Inline cell editing ───────────────────────────────────

function startEditCell(span, id, field, currentVal) {
  const input = document.createElement('input');
  input.type = 'number';
  input.step = '0.01';
  input.value = currentVal;
  input.className = 'reserves-inline-input';
  input.style.cssText = 'width:110px';
  input.onblur = () => saveEditCell(input, span, id, field);
  input.onkeydown = e => { if (e.key === 'Enter') input.blur(); if (e.key === 'Escape') { span.style.display = ''; input.remove(); } };
  span.style.display = 'none';
  span.parentNode.insertBefore(input, span);
  input.focus();
  input.select();
}

function startEditCellRaw(span, id, field, currentVal) {
  const input = document.createElement('input');
  input.type = 'number';
  input.value = currentVal;
  input.className = 'reserves-inline-input';
  input.style.cssText = 'width:70px';
  input.placeholder = '—';
  input.onblur = () => saveEditCellRaw(input, span, id, field);
  input.onkeydown = e => { if (e.key === 'Enter') input.blur(); if (e.key === 'Escape') { span.style.display = ''; input.remove(); } };
  span.style.display = 'none';
  span.parentNode.insertBefore(input, span);
  input.focus();
  input.select();
}

function startEditCellText(span, id, field, currentVal) {
  const input = document.createElement('input');
  input.type = 'text';
  input.value = currentVal;
  input.className = 'reserves-inline-input';
  input.style.cssText = 'width:160px';
  input.onblur = () => saveEditCellText(input, span, id, field);
  input.onkeydown = e => { if (e.key === 'Enter') input.blur(); if (e.key === 'Escape') { span.style.display = ''; input.remove(); } };
  span.style.display = 'none';
  span.parentNode.insertBefore(input, span);
  input.focus();
  input.select();
}

async function saveEditCell(input, span, id, field) {
  const val = parseFloat(input.value) || 0;
  input.remove();
  span.style.display = '';
  span.textContent = fmtEur(val);
  try {
    await apiPut(`/api/reserves/${id}`, { [field]: val });
    await loadReserves();
  } catch (err) { showToast('Erreur: ' + err.message, 'error'); }
}

async function saveEditCellRaw(input, span, id, field) {
  const val = parseInt(input.value) || null;
  input.remove();
  span.style.display = '';
  span.textContent = val ?? '—';
  try {
    await apiPut(`/api/reserves/${id}`, { [field]: val });
    await loadReserves();
  } catch (err) { showToast('Erreur: ' + err.message, 'error'); }
}

async function saveEditCellText(input, span, id, field) {
  const val = input.value || null;
  input.remove();
  span.style.display = '';
  span.textContent = val || '—';
  try {
    await apiPut(`/api/reserves/${id}`, { [field]: val });
    await loadReserves();
  } catch (err) { showToast('Erreur: ' + err.message, 'error'); }
}

// ── Add/Edit modal ────────────────────────────────────────

function openAddReserveModal() {
  document.getElementById('reserveModalTitle').textContent = 'Ajouter une réserve';
  document.getElementById('resModalBtn').textContent = 'Créer';
  document.getElementById('resModalId').value = '';
  document.getElementById('resYear').value = new Date().getFullYear();
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
    month: 1,
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
    try {
      await apiDelete(`/api/reserves/${id}`);
      showToast('Réserve supprimée', 'success');
      await loadReserves();
    } catch (err) { showToast(err.message, 'error'); }
  });
}
