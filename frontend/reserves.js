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

  // Calendrier : montant encore libérable par année de libération (affichage uniquement)
  const sched = {};
  Object.values(byYear).forEach(y => {
    if (y.releasable > 0.01 && y.release_year) sched[y.release_year] = (sched[y.release_year] || 0) + y.releasable;
  });
  const schedYears = Object.keys(sched).sort((a, b) => a - b);
  const schedMax = Math.max(1, ...Object.values(sched));
  const thisYear = new Date().getFullYear();
  const releasedPct = stats.total_amount > 0 ? (stats.total_released || 0) / stats.total_amount * 100 : 0;

  page.innerHTML = `
    <div class="db-head">
      <div>
        <h1 class="db-title">Réserves de liquidation</h1>
        <div class="db-subtitle">${years.length} année${years.length > 1 ? 's' : ''} constituée${years.length > 1 ? 's' : ''} · ${fmtPct(releasedPct, 0)} déjà libéré</div>
      </div>
      ${isAdmin() ? `<div class="db-actions"><button class="btn btn-primary" onclick="openAddReserveModal()">+ Ajouter une année</button></div>` : ''}
    </div>

    <div class="pf-kpis cr-kpis">
      <div class="pf-kpi"><div class="db-label">Total constitué</div><div class="pf-kpi-value">${fmtEur(stats.total_amount || 0)}</div></div>
      <div class="pf-kpi"><div class="db-label">Encore libérable</div><div class="pf-kpi-value">${fmtEur(stats.total_releasable || 0)}</div></div>
      <div class="pf-kpi"><div class="db-label">Libéré (brut)</div><div class="pf-kpi-value">${fmtEur(stats.total_released || 0)}</div></div>
      <div class="pf-kpi"><div class="db-label">Net reçu</div><div class="pf-kpi-value pos">${fmtEur(stats.total_net_recu || 0)}</div>
        <div class="pf-kpi-sub">après précompte ${fmtEur(stats.total_precompte || 0)}</div></div>
    </div>

    ${schedYears.length ? `
    <section class="card" style="margin-bottom:16px">
      <div class="db-card-title">Calendrier de libération</div>
      <div class="db-subtitle" style="margin:-8px 0 14px">Montant encore libérable, par année de libération prévue</div>
      <div class="rs-sched">
        ${schedYears.map(y => `
          <div class="rs-col">
            <span class="rs-val">${fmtEurShort(sched[y])}</span>
            <div class="rs-bar${+y <= thisYear ? ' is-due' : ''}" style="height:${Math.max(4, Math.round(sched[y] / schedMax * 140))}px"></div>
            <span class="rs-year">${y}</span>
          </div>`).join('')}
      </div>
    </section>` : ''}

    <section class="card pf-table-card">
      <div class="table-wrap">
        <table class="data-table pf-table" id="reservesTable">
          <thead><tr>
            <th class="left">Année</th>
            <th>Constitué</th>
            <th>Libéré (brut)</th>
            <th>Précompte</th>
            <th>Net reçu</th>
            <th>Encore libérable</th>
            <th class="left">Note</th>
            ${isAdmin() ? '<th><span class="sr-only">Actions</span></th>' : ''}
          </tr></thead>
          <tbody id="reservesBody">${renderReserveRows(years, byYear, items)}</tbody>
        </table>
      </div>
    </section>

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
          <span class="modal-title">Libérer une réserve</span>
          <button class="modal-close" onclick="closeModal('liberateModal')">✕</button>
        </div>
        <div id="liberateInfo" class="cr-note is-info" style="margin-bottom:18px"></div>
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
            <div style="display:flex;justify-content:space-between;align-items:center;padding:10px 14px;background:var(--accent-green-dim);border-radius:10px;font-size:14px">
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

    const thisYear = new Date().getFullYear();
    const status = row.releasable <= 0.01 ? ['Libéré', 'is-gain']
      : (row.release_year && row.release_year <= thisYear) ? ['Libérable', 'is-warn']
      : ['En attente', 'is-muted'];
    return `
      <tr class="no-cursor position-row" id="reserve-row-${dbId}">
        <td class="left" data-label="">
          <div class="rs-year-cell"><strong>${year}</strong>
            <span class="db-chip ${status[1]}">${status[0]}</span></div>
          ${row.release_year ? `<div class="pf-sub">libération ${row.release_year}</div>` : ''}
        </td>
        <td data-label="Constitué">
          ${isAdmin()
            ? `<span class="editable-cell" onclick="startEditCell(this, ${dbId}, 'amount', ${row.amount})">${fmtEur(row.amount)}</span>`
            : fmtEur(row.amount)}
        </td>
        <td data-label="Libéré (brut)">${fmtEur(row.released)}</td>
        <td data-label="Précompte" style="color:var(--text-muted)">${fmtEur(row.precompte_paye)}</td>
        <td data-label="Net reçu" class="${row.net_recu > 0 ? 'pos' : 'neutral'}">${fmtEur(row.net_recu)}</td>
        <td data-label="Encore libérable"><strong>${fmtEur(row.releasable)}</strong></td>
        <td class="left" data-label="Note">
          ${isAdmin()
            ? `<span class="editable-cell" onclick="startEditCellText(this, ${dbId}, 'notes', ${JSON.stringify(row.notes || '')})">${escHtml(row.notes || '—')}</span>`
            : escHtml(row.notes || '—')}
        </td>
        ${isAdmin() ? `
        <td class="pf-actions rs-actions">
          ${row.releasable > 0.01 ? `<button class="btn btn-secondary btn-sm" onclick="openLiberateModal(${dbId}, ${year}, ${row.releasable})">Libérer</button>` : ''}
          <button type="button" class="pf-menu-btn row-menu-btn" aria-haspopup="menu" aria-label="Autres actions ${year}"
            onclick="openRowMenu(this, [['Supprimer', () => deleteReserveConfirm(${dbId}), true]])">⋯</button>
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
