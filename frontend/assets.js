/* ═══════════════════════════════════════════════
   ASSETS — Physical assets module
   ═══════════════════════════════════════════════ */
'use strict';

let _assetsData = [];
let _coffresList = [];

async function loadAssets() {
  try {
    [_assetsData, _coffresList] = await Promise.all([
      apiGet('/api/assets'),
      apiGet('/api/coffres'),
    ]);
    renderAssetsPage();
  } catch (err) {
    showToast('Erreur actifs: ' + err.message, 'error');
  }
}

function renderAssetsPage() {
  const page = document.getElementById('page-assets');
  if (!page) return;

  const totalValue = _assetsData.reduce((s, a) => s + (a.estimated_value || 0), 0);
  const byCategory = {};
  _assetsData.forEach(a => {
    const cat = a.category || 'autre';
    byCategory[cat] = (byCategory[cat] || 0) + (a.estimated_value || 0);
  });

  page.innerHTML = `
    <div style="display:flex;align-items:center;justify-content:space-between;margin-bottom:20px">
      <div class="page-title">💎 Actifs physiques</div>
      ${isAdmin() ? `<button class="btn btn-primary btn-sm" onclick="openAddAssetModal()">+ Actif</button>` : ''}
    </div>

    <!-- Summary cards -->
    <div class="hero-grid" style="margin-bottom:20px">
      <div class="hero-card">
        <div class="card-label">💎 Valeur totale</div>
        <div class="hero-card-value purple">${fmtEur(totalValue)}</div>
        <div class="hero-card-sub">${_assetsData.length} actif${_assetsData.length !== 1 ? 's' : ''}</div>
      </div>
      ${Object.entries(byCategory).map(([cat, val]) => `
      <div class="hero-card">
        <div class="card-label">${ASSET_CAT_ICONS[cat] ?? '📦'} ${ASSET_CAT_LABELS[cat] ?? cat}</div>
        <div class="hero-card-value">${fmtEur(val)}</div>
        <div class="hero-card-sub">${_assetsData.filter(a => (a.category || 'autre') === cat).length} actif${_assetsData.filter(a => (a.category || 'autre') === cat).length !== 1 ? 's' : ''}</div>
      </div>`).join('')}
    </div>

    <!-- Filter & list -->
    <div class="card" style="padding:0;overflow:hidden">
      <div class="section-header">
        <div class="section-title">Actifs <span class="section-count">${_assetsData.length}</span></div>
        <div style="display:flex;gap:8px">
          <input type="text" class="form-input" style="width:200px" placeholder="Rechercher…" oninput="filterAssets(this.value)" id="assetSearch"/>
          <select class="form-select" style="width:auto" onchange="filterAssetCat(this.value)">
            <option value="">Toutes catégories</option>
            ${Object.entries(ASSET_CAT_LABELS).map(([k, v]) => `<option value="${k}">${v}</option>`).join('')}
          </select>
        </div>
      </div>
      <div class="table-wrap">
        <table class="data-table">
          <thead><tr>
            <th class="left" style="padding-left:24px">Actif</th>
            <th class="left">Catégorie</th>
            <th class="left">Localisation</th>
            <th>Valeur estimée</th>
            <th>Documents</th>
            <th>Dernière évaluation</th>
            ${isAdmin() ? '<th>Actions</th>' : ''}
          </tr></thead>
          <tbody id="assetsBody">${renderAssetRows(_assetsData)}</tbody>
        </table>
      </div>
    </div>

    <!-- Modals injected via addAssetModals() -->
    <div id="assetModals"></div>`;

  addAssetModals();
}

function renderAssetRows(assets, filter = '', catFilter = '') {
  let filtered = assets;
  if (filter) filtered = filtered.filter(a => a.name.toLowerCase().includes(filter.toLowerCase()) || (a.description || '').toLowerCase().includes(filter.toLowerCase()));
  if (catFilter) filtered = filtered.filter(a => (a.category || 'autre') === catFilter);

  if (!filtered.length) return `<tr><td colspan="${isAdmin() ? 7 : 6}"><div class="empty-state"><div class="empty-icon">💎</div><div class="empty-text">Aucun actif trouvé</div></div></td></tr>`;

  const coffreMap = Object.fromEntries(_coffresList.map(c => [c.id, c.name]));

  return filtered.map(a => {
    const lastVal = a.events?.filter(e => e.type === 'VALUATION').sort((x, y) => y.date.localeCompare(x.date))[0];
    const locStr = a.coffre_id ? `🏦 ${escHtml(coffreMap[a.coffre_id] || 'Coffre')}` : '—';
    return `
      <tr onclick="toggleAssetExpand(${a.id})" id="asset-row-${a.id}">
        <td class="left" style="padding-left:24px">
          <div class="asset-name-cell">
            <div class="pos-icon ${a.category || 'autre'}">${ASSET_CAT_ICONS[a.category || 'autre'] ?? '📦'}</div>
            <div>
              <div class="asset-name">${escHtml(a.name)}</div>
              ${a.description ? `<div class="asset-sub" style="max-width:200px;overflow:hidden;text-overflow:ellipsis">${escHtml(a.description)}</div>` : ''}
            </div>
          </div>
        </td>
        <td class="left"><span class="badge badge-${a.category || 'autre'}">${ASSET_CAT_LABELS[a.category || 'autre'] ?? a.category}</span></td>
        <td class="left">${locStr}</td>
        <td>${a.estimated_value != null ? `<strong>${fmtEur(a.estimated_value)}</strong>` : '—'}</td>
        <td style="color:var(--text-secondary)">${(a.documents || []).length}</td>
        <td style="color:var(--text-secondary)">${lastVal ? fmtDate(lastVal.date) : '—'}</td>
        ${isAdmin() ? `<td><div style="display:flex;justify-content:flex-end;gap:4px" onclick="event.stopPropagation()">
          <button class="btn btn-ghost primary" onclick="openAddEventModal(${a.id})" title="Ajouter événement">+ Év.</button>
          <button class="btn btn-ghost primary" onclick="openUploadDocModal(${a.id})" title="Joindre document">📎</button>
          <button class="btn btn-ghost" onclick="openEditAssetModal(${a.id})" title="Modifier">✏️</button>
          <button class="btn btn-ghost danger" onclick="deleteAssetConfirm(${a.id},'${escHtml(a.name).replace(/'/g,"\\'")}')">🗑</button>
        </div></td>` : ''}
      </tr>
      <tr class="expand-row"><td colspan="${isAdmin() ? 7 : 6}">
        <div class="expand-content" id="asset-expand-${a.id}">${buildAssetDetails(a)}</div>
      </td></tr>`;
  }).join('');
}

function buildAssetDetails(a) {
  const eventsHtml = !(a.events?.length) ? '<div style="color:var(--text-secondary);font-size:12px">Aucun événement</div>' :
    `<table class="data-table" style="font-size:12px"><thead><tr><th class="left">Date</th><th class="left">Type</th><th>Montant</th><th class="left">Note</th>${isAdmin() ? '<th></th>' : ''}</tr></thead><tbody>
    ${a.events.map(ev => `<tr class="no-cursor">
      <td class="left">${fmtDate(ev.date)}</td>
      <td class="left"><span class="badge badge-${ev.type.toLowerCase()}">${ev.type}</span></td>
      <td>${ev.amount != null ? fmtEur(ev.amount) : '—'}</td>
      <td class="left" style="font-family:var(--font-body);color:var(--text-secondary)">${escHtml(ev.notes || '—')}</td>
      ${isAdmin() ? `<td><button class="btn btn-ghost danger btn-sm" onclick="deleteEventConfirm(${a.id},${ev.id})">🗑</button></td>` : ''}
    </tr>`).join('')}
    </tbody></table>`;

  const docsHtml = !(a.documents?.length) ? '<div style="color:var(--text-secondary);font-size:12px">Aucun document</div>' :
    `<div style="display:flex;flex-wrap:wrap;gap:8px">
    ${a.documents.map(d => `
      <div style="background:var(--bg-tertiary);border:1px solid var(--border);border-radius:var(--radius-sm);padding:8px 12px;display:flex;align-items:center;gap:8px">
        <span style="font-size:18px">📄</span>
        <div>
          <div style="font-size:12px;font-weight:500">${escHtml(d.filename)}</div>
          <div style="font-size:11px;color:var(--text-secondary)">${fmtSize(d.size_bytes)} · ${fmtDate(d.created_at)}</div>
        </div>
        <a href="/api/assets/${a.id}/documents/${d.id}/download" class="btn btn-ghost btn-sm" download>⬇</a>
        ${isAdmin() ? `<button class="btn btn-ghost danger btn-sm" onclick="deleteDocConfirm(${a.id},${d.id})">🗑</button>` : ''}
      </div>`).join('')}
    </div>`;

  return `
    <div style="display:grid;grid-template-columns:1fr 1fr;gap:24px;padding-bottom:4px">
      <div>
        <div style="font-size:11px;font-weight:500;color:var(--text-secondary);text-transform:uppercase;letter-spacing:.08em;margin-bottom:10px">Événements</div>
        ${eventsHtml}
      </div>
      <div>
        <div style="font-size:11px;font-weight:500;color:var(--text-secondary);text-transform:uppercase;letter-spacing:.08em;margin-bottom:10px">Documents</div>
        ${docsHtml}
      </div>
    </div>`;
}

function toggleAssetExpand(assetId) {
  const el = document.getElementById(`asset-expand-${assetId}`);
  if (el) el.classList.toggle('open');
}

function filterAssets(q) {
  document.getElementById('assetsBody').innerHTML = renderAssetRows(_assetsData, q);
}

function filterAssetCat(cat) {
  const q = document.getElementById('assetSearch')?.value || '';
  document.getElementById('assetsBody').innerHTML = renderAssetRows(_assetsData, q, cat);
}

// ── Asset CRUD modals ──────────────────────────────────────

function addAssetModals() {
  // Modals are defined in index.html + extra ones injected here
  const el = document.getElementById('assetModals');
  if (!el) return;
  const coffreOptions = _coffresList.map(c => `<option value="${c.id}">${escHtml(c.name)}</option>`).join('');
  el.innerHTML = `
    <!-- Add/Edit asset -->
    <div class="modal-overlay" id="assetModal">
      <div class="modal">
        <div class="modal-header"><span class="modal-title" id="assetModalTitle">Ajouter un actif</span><button class="modal-close" onclick="closeModal('assetModal')">✕</button></div>
        <form onsubmit="submitAssetModal(event)" class="form-grid">
          <div class="form-group full"><label class="form-label">Nom</label><input type="text" class="form-input" id="assetName" required/></div>
          <div class="form-group"><label class="form-label">Catégorie</label>
            <select class="form-select" id="assetCategory">
              ${Object.entries(ASSET_CAT_LABELS).map(([k, v]) => `<option value="${k}">${v}</option>`).join('')}
            </select>
          </div>
          <div class="form-group"><label class="form-label">Valeur estimée (€)</label><input type="number" class="form-input" id="assetValue" step="0.01" placeholder="0.00"/></div>
          <div class="form-group"><label class="form-label">Coffre (localisation)</label>
            <select class="form-select" id="assetCoffre"><option value="">—</option>${coffreOptions}</select>
          </div>
          <div class="form-group full"><label class="form-label">Description</label><textarea class="form-textarea" id="assetDesc" rows="2"></textarea></div>
          <input type="hidden" id="assetModalId"/>
          <div class="form-actions"><button type="button" class="btn btn-secondary" onclick="closeModal('assetModal')">Annuler</button><button type="submit" class="btn btn-primary" id="assetModalBtn">Créer</button></div>
        </form>
      </div>
    </div>
    <!-- Add event -->
    <div class="modal-overlay" id="assetEventModal">
      <div class="modal">
        <div class="modal-header"><span class="modal-title" id="assetEventTitle">Ajouter un événement</span><button class="modal-close" onclick="closeModal('assetEventModal')">✕</button></div>
        <form onsubmit="submitEventModal(event)" class="form-grid">
          <div class="form-group"><label class="form-label">Type</label>
            <select class="form-select" id="eventType">
              <option value="PURCHASE">Achat</option><option value="SALE">Vente</option><option value="VALUATION">Évaluation</option>
            </select>
          </div>
          <div class="form-group"><label class="form-label">Date</label><input type="date" class="form-input" id="eventDate" required/></div>
          <div class="form-group"><label class="form-label">Montant (€)</label><input type="number" class="form-input" id="eventAmount" step="0.01" placeholder="0.00"/></div>
          <div class="form-group full"><label class="form-label">Note</label><textarea class="form-textarea" id="eventNotes" rows="2"></textarea></div>
          <input type="hidden" id="eventAssetId"/>
          <div class="form-actions"><button type="button" class="btn btn-secondary" onclick="closeModal('assetEventModal')">Annuler</button><button type="submit" class="btn btn-primary">Ajouter</button></div>
        </form>
      </div>
    </div>
    <!-- Upload doc -->
    <div class="modal-overlay" id="uploadDocModal">
      <div class="modal">
        <div class="modal-header"><span class="modal-title">Joindre un document</span><button class="modal-close" onclick="closeModal('uploadDocModal')">✕</button></div>
        <form onsubmit="submitUploadDoc(event)" id="uploadDocForm">
          <div class="form-group" style="margin-bottom:14px"><label class="form-label">Fichier (max 20 MB)</label><input type="file" class="form-input" id="docFile" required/></div>
          <div class="form-group" style="margin-bottom:14px"><label class="form-label">Type de document</label>
            <select class="form-select" id="docType"><option value="">—</option><option value="facture">Facture</option><option value="assurance">Assurance</option><option value="certificat">Certificat</option><option value="photo">Photo</option><option value="autre">Autre</option></select>
          </div>
          <div class="form-group" style="margin-bottom:20px"><label class="form-label">Note</label><input type="text" class="form-input" id="docNotes"/></div>
          <input type="hidden" id="docAssetId"/>
          <div class="form-actions"><button type="button" class="btn btn-secondary" onclick="closeModal('uploadDocModal')">Annuler</button><button type="submit" class="btn btn-primary">Chiffrer et envoyer</button></div>
        </form>
      </div>
    </div>`;
}

function openAddAssetModal() {
  document.getElementById('assetModalTitle').textContent = 'Ajouter un actif';
  document.getElementById('assetModalBtn').textContent = 'Créer';
  document.getElementById('assetModalId').value = '';
  document.getElementById('assetName').value = '';
  document.getElementById('assetCategory').value = 'autre';
  document.getElementById('assetValue').value = '';
  document.getElementById('assetCoffre').value = '';
  document.getElementById('assetDesc').value = '';
  openModal('assetModal');
}

function openEditAssetModal(assetId) {
  const a = _assetsData.find(x => x.id === assetId);
  if (!a) return;
  document.getElementById('assetModalTitle').textContent = 'Modifier l\'actif';
  document.getElementById('assetModalBtn').textContent = 'Enregistrer';
  document.getElementById('assetModalId').value = assetId;
  document.getElementById('assetName').value = a.name;
  document.getElementById('assetCategory').value = a.category || 'autre';
  document.getElementById('assetValue').value = a.estimated_value ?? '';
  document.getElementById('assetCoffre').value = a.coffre_id ?? '';
  document.getElementById('assetDesc').value = a.description ?? '';
  openModal('assetModal');
}

async function submitAssetModal(e) {
  e.preventDefault();
  const id = document.getElementById('assetModalId').value;
  const body = {
    name: document.getElementById('assetName').value,
    category: document.getElementById('assetCategory').value,
    estimated_value: parseFloat(document.getElementById('assetValue').value) || null,
    coffre_id: parseInt(document.getElementById('assetCoffre').value) || null,
    description: document.getElementById('assetDesc').value || null,
  };
  try {
    if (id) { await apiPut(`/api/assets/${id}`, body); showToast('Actif mis à jour', 'success'); }
    else { await apiPost('/api/assets', body); showToast('Actif créé', 'success'); }
    closeModal('assetModal');
    await loadAssets();
  } catch (err) { showToast(err.message, 'error'); }
}

function deleteAssetConfirm(id, name) {
  confirm('Supprimer l\'actif', `Supprimer "${name}" et tous ses documents ?`, async () => {
    try { await apiDelete(`/api/assets/${id}`); showToast('Actif supprimé', 'success'); await loadAssets(); }
    catch (err) { showToast(err.message, 'error'); }
  });
}

// ── Events ─────────────────────────────────────────────────

function openAddEventModal(assetId) {
  document.getElementById('eventAssetId').value = assetId;
  document.getElementById('eventDate').value = todayISO();
  document.getElementById('eventType').value = 'VALUATION';
  document.getElementById('eventAmount').value = '';
  document.getElementById('eventNotes').value = '';
  openModal('assetEventModal');
}

async function submitEventModal(e) {
  e.preventDefault();
  const assetId = document.getElementById('eventAssetId').value;
  const body = {
    type: document.getElementById('eventType').value,
    date: document.getElementById('eventDate').value,
    amount: parseFloat(document.getElementById('eventAmount').value) || null,
    notes: document.getElementById('eventNotes').value || null,
  };
  try {
    await apiPost(`/api/assets/${assetId}/events`, body);
    showToast('Événement ajouté', 'success');
    closeModal('assetEventModal');
    await loadAssets();
  } catch (err) { showToast(err.message, 'error'); }
}

function deleteEventConfirm(assetId, eventId) {
  confirm('Supprimer l\'événement', 'Supprimer cet événement ?', async () => {
    try { await apiDelete(`/api/assets/${assetId}/events/${eventId}`); showToast('Événement supprimé', 'success'); await loadAssets(); }
    catch (err) { showToast(err.message, 'error'); }
  });
}

// ── Documents ─────────────────────────────────────────────

function openUploadDocModal(assetId) {
  document.getElementById('docAssetId').value = assetId;
  document.getElementById('uploadDocForm').reset();
  openModal('uploadDocModal');
}

async function submitUploadDoc(e) {
  e.preventDefault();
  const assetId = document.getElementById('docAssetId').value;
  const file = document.getElementById('docFile').files[0];
  if (!file) return;
  const fd = new FormData();
  fd.append('file', file);
  fd.append('document_type', document.getElementById('docType').value);
  fd.append('notes', document.getElementById('docNotes').value);
  try {
    const res = await fetch(`/api/assets/${assetId}/documents`, { method: 'POST', body: fd, credentials: 'include', headers: { 'X-CSRF-Token': _csrfToken || '' } });
    if (!res.ok) { const e = await res.json(); throw new Error(e.detail); }
    showToast('Document chiffré et enregistré', 'success');
    closeModal('uploadDocModal');
    await loadAssets();
  } catch (err) { showToast(err.message, 'error'); }
}

function deleteDocConfirm(assetId, docId) {
  confirm('Supprimer le document', 'Supprimer ce document ?', async () => {
    try { await apiDelete(`/api/assets/${assetId}/documents/${docId}`); showToast('Document supprimé', 'success'); await loadAssets(); }
    catch (err) { showToast(err.message, 'error'); }
  });
}
