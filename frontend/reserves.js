/* ═══════════════════════════════════════════════
   RESERVES — Réserves de liquidation / dividendes
   ═══════════════════════════════════════════════ */
'use strict';

let _reservesData = { stats: {}, items: [] };
let _liberateId    = null;

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

  // Aggregate by year (sum all month entries for the same year)
  const byYear = {};
  items.forEach(r => {
    if (!byYear[r.year]) {
      byYear[r.year] = {
        id: r.id, year: r.year,
        amount: 0, released: 0, precompte_paye: 0,
        net_recu: 0, releasable: 0,
        release_year: r.release_year, notes: r.notes,
      };
    }
    const y = byYear[r.year];
    y.amount        += r.amount        || 0;
    y.released      += r.released      || 0;
    y.precompte_paye+= r.precompte_paye|| 0;
    y.net_recu      += r.net_recu      || 0;
    y.releasable     = Math.max(0, y.amount - y.released);
  });
  const years = Object.keys(byYear).sort((a, b) => b - a);

  page.innerHTML = `
    <div style="display:flex;align-items:center;justify-content:space-between;margin-bottom:20px">
      <div class="page-title">${ICONS.wallet} Réserves de liquidation</div>
      ${isAdmin() ? `<button class="btn btn-primary btn-sm" onclick="openAddReserveModal()">+ Ajouter une année</button>` : ''}
    </div>

    <!-- 4 hero KPIs -->
    <div class="hero-grid" style="margin-bottom:20px">
      <div class="hero-card">
        <div class="card-label">${ICONS.coins} Total constitué</div>
        <div class="hero-card-value blue">${fmtEur(stats.total_amount || 0)}</div>
      </div>
      <div class="hero-card">
        <div class="card-label">${ICONS.wallet} Encore libérable</div>
        <div class="hero-card-value gold">${fmtEur(stats.total_releasable || 0)}</div>
      </div>
      <div class="hero-card">
        <div class="card-label">${ICONS.chartUp} Libéré (brut)</div>
        <div class="hero-card-value green">${fmtEur(stats.total_released || 0)}</div>
      </div>
      <div class="hero-card">
        <div class="card-label">${ICONS.coins} Net reçu total</div>
        <div class="hero-card-value green">${fmtEur(stats.total_net_recu || 0)}</div>
        <div style="font-size:11px;color:var(--text-muted);margin-top:2px">après précompte ${fmtEur(stats.total_precompte || 0)}</div>
      </div>
    </div>

    <!-- Table by year -->
    <div class="card" style="padding:0;overflow:hidden">
      <div class="table-wrap">
        <table class="data-table" id="reservesTable">
          <thead><tr>
            <th class="left" style="padding-left:24px">Année</th>
            <th>Montant constitué</th>
            <th>Libéré (brut)</th>
            <th>Précompte payé</th>
            <th>Net reçu</th>
            <th class="${isAdmin() ? '' : 'right'}">Encore libérable</th>
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
          <div class="form-group">
            <label class="form-label">Année</label>
            <input type="number" class="form-input" id="resYear" min="2000" max="2060" required/>
          </div>
          <div class="form-group">
            <label class="form-label">Montant constitué (€)</label>
            <input type="number" class="form-input" id="resAmount" step="0.01" placeholder="0.00"/>
          </div>
          <div class="form-group">
            <label class="form-label">Année de libération prévue</label>
            <input type="number" class="form-input" id="resReleaseYear" min="2000" max="2060" placeholder="Optionnel"/>
          </div>
          <div class="form-group full">
            <label class="form-label">Note</label>
            <input type="text" class="form-input" id="resNotes" placeholder="Optionnel"/>
          </div>
          <input type="hidden" id="resModalId"/>
          <div class="form-actions">
            <button type="button" class="btn btn-secondary" onclick="closeModal('reserveModal')">Annuler</button>
            <button type="submit" class="btn btn-primary" id="resModalBtn">Créer</button>
          </div>
        </form>
      </div>
    </div>

    <!-- Liberation modal -->
    <div class="modal-overlay" id="liberateModal">
      <div class="modal" style="max-width:400px">
        <div class="modal-header">
          <span class="modal-title">💶 Libérer une réserve</span>
          <button class="modal-close" onclick="closeModal('liberateModal')">✕</button>
        </div>
        <div id="liberateInfo" style="background:rgba(59,130,246,.08);border:1px solid rgba(59,130,246,.25);border-radius:10px;padding:12px 16px;margin-bottom:18px;font-size:13px;color:var(--text-secondary)"></div>
        <form onsubmit="submitLiberate(event)" class="form-grid">
          <div class="form-group">
            <label class="form-label">Montant brut libéré (€)</label>
            <input type="number" class="form-input" id="liberateMontant" step="0.01" min="0.01" required placeholder="0.00" oninput="updateLiberateNet()"/>
          </div>
          <div class="form-group">
            <label class="form-label">Précompte mobilier payé (€)</label>
            <input type="number" class="form-input" id="liberatePrecompte" step="0.01" min="0" value="0" oninput="updateLiberateNet()"/>
          </div>
          <div class="form-group full">
            <div style="display:flex;justify-content:space-between;align-items:center;padding:10px 14px;background:rgba(74,222,128,.08);border:1px solid rgba(74,222,128,.25);border-radius:8px;font-size:14px">
              <span style="color:var(--text-secondary)">Net reçu :</span>
              <span id="liberateNetDisplay" style="font-weight:700;color:var(--accent-green)">0,00 €</span>
            </div>
          </div>
          <div class="form-actions">
            <button type="button" class="btn btn-secondary" onclick="closeModal('liberateModal')">Annuler</button>
            <button type="submit" class="btn btn-primary">Enregistrer</button>
          </div>
        </form>
      </div>
    </div>`;
}

function renderReserveRows(years, byYear, allItems) {
  const cols = isAdmin() ? 8 : 7;
  if (!years.length) {
    return `<tr><td colspan="${cols}"><div class="empty-state">
      <div class="empty-icon">${ICONS.wallet}</div>
      <div class="empty-text">Aucune réserve enregistrée</div>
      ${isAdmin() ? `<button class="btn btn-primary btn-sm" style="margin-top:12px" onclick="openAddReserveModal()">+ Ajouter une année</button>` : ''}
    </div></td></tr>`;
  }

  return years.map(year => {
    const row = byYear[year];
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
        <td>${fmtEur(row.released)}</td>
        <td style="color:var(--text-muted)">${fmtEur(row.precompte_paye)}</td>
        <td class="${row.net_recu > 0 ? 'pos' : 'neutral'}">${fmtEur(row.net_recu)}</td>
        <td class="${row.releasable > 0 ? 'gold' : 'neutral'}">${fmtEur(row.releasable)}</td>
        <td class="left">
          ${isAdmin()
            ? `<span class="editable-cell" onclick="startEditCellText(this, ${dbId}, 'notes', ${JSON.stringify(row.notes || '')})">${escHtml(row.notes || '—')}</span>`
            : escHtml(row.notes || '—')}
        </td>
        ${isAdmin() ? `
        <td style="white-space:nowrap">
          ${row.releasable > 0.01 ? `<button class="btn btn-primary btn-sm" style="margin-right:4px" onclick="openLiberateModal(${dbId}, ${year}, ${row.releasable})">💶 Libérer</button>` : ''}
          <button class="btn btn-ghost danger btn-sm" onclick="deleteReserveConfirm(${dbId})">🗑</button>
        </td>` : ''}
      </tr>`;
  }).join('');
}

// ── Liberation modal ──────────────────────────────────────

function openLiberateModal(id, year, solde) {
  _liberateId = id;
  document.getElementById('liberateInfo').innerHTML =
    `<strong>Réserve ${year}</strong> — Solde libérable : <strong>${fmtEur(solde)}</strong>`;
  document.getElementById('liberateMontant').value = '';
  document.getElementById('liberatePrecompte').value = '0';
  document.getElementById('liberateNetDisplay').textContent = '0,00 €';
  openModal('liberateModal');
  setTimeout(() => document.getElementById('liberateMontant').focus(), 100);
}

function updateLiberateNet() {
  const montant   = parseFloat(document.getElementById('liberateMontant').value)    || 0;
  const precompte = parseFloat(document.getElementById('liberatePrecompte').value)  || 0;
  const net = montant - precompte;
  const el = document.getElementById('liberateNetDisplay');
  el.textContent = fmtEur(net);
  el.style.color = net >= 0 ? 'var(--accent-green)' : 'var(--accent-red)';
}

async function submitLiberate(e) {
  e.preventDefault();
  const montant   = parseFloat(document.getElementById('liberateMontant').value)   || 0;
  const precompte = parseFloat(document.getElementById('liberatePrecompte').value) || 0;
  if (montant <= 0) { showToast('Le montant doit être positif', 'error'); return; }
  try {
    await apiPost(`/api/reserves/${_liberateId}/liberate`, { montant, precompte });
    showToast('Libération enregistrée', 'success');
    closeModal('liberateModal');
    await loadReserves();
  } catch (err) { showToast(err.message, 'error'); }
}

// ── Inline cell editing ───────────────────────────────────

function startEditCell(span, id, field, currentVal) {
  const input = document.createElement('input');
  input.type = 'number';
  input.step = '0.01';
  input.value = currentVal;
  input.className = 'reserves-inline-input';
  input.style.cssText = 'width:120px';
  input.onblur = () => saveEditCell(input, span, id, field);
  input.onkeydown = e => {
    if (e.key === 'Enter') input.blur();
    if (e.key === 'Escape') { span.style.display = ''; input.remove(); }
  };
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
  input.onkeydown = e => {
    if (e.key === 'Enter') input.blur();
    if (e.key === 'Escape') { span.style.display = ''; input.remove(); }
  };
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
  document.getElementById('resNotes').value = '';
  openModal('reserveModal');
}

async function submitReserveModal(e) {
  e.preventDefault();
  const id = document.getElementById('resModalId').value;
  const body = {
    year:         parseInt(document.getElementById('resYear').value),
    month:        1,
    amount:       parseFloat(document.getElementById('resAmount').value) || 0,
    release_year: parseInt(document.getElementById('resReleaseYear').value) || null,
    notes:        document.getElementById('resNotes').value || null,
  };
  try {
    if (id) {
      await apiPut(`/api/reserves/${id}`, body);
      showToast('Réserve mise à jour', 'success');
    } else {
      await apiPost('/api/reserves', body);
      showToast('Réserve créée', 'success');
    }
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
