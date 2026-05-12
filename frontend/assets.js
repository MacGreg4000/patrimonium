/* ═══════════════════════════════════════════════
   ASSETS — Physical assets module
   ═══════════════════════════════════════════════ */
'use strict';

let _assetsData = [];
let _soldAssetsData = [];
let _coffresList = [];

const SALE_DEST_LABELS = {
  portfolio: '📈 Investi en portefeuille boursier',
  bank:      '🏧 Versé sur compte bancaire',
  coffre:    '🔐 Déposé en coffre (espèces)',
  cash:      '💵 Reçu en espèces (hors coffre)',
  other:     '📦 Autre / Non précisé',
};

async function loadAssets() {
  try {
    [_assetsData, _soldAssetsData, _coffresList] = await Promise.all([
      apiGet('/api/assets'),
      apiGet('/api/assets?sold=true'),
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

    <!-- Historique des ventes -->
    ${renderSoldAssetsSection()}

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
    const locStr = a.category === 'immo' && a.location
      ? `🏠 ${escHtml(a.location)}`
      : a.coffre_id ? `🏦 ${escHtml(coffreMap[a.coffre_id] || 'Coffre')}` : '—';
    return `
      <tr onclick="toggleAssetExpand(${a.id})" id="asset-row-${a.id}">
        <td class="left" style="padding-left:24px">
          <div class="asset-name-cell">
            <div class="pos-icon ${a.category || 'autre'}">${ASSET_CAT_ICONS[a.category || 'autre'] ?? '📦'}</div>
            <div>
              <div class="asset-name">${escHtml(a.name)}</div>
              ${a.category === 'vehicule' && (a.vehicle_make || a.vehicle_model || a.vehicle_plate)
                ? `<div class="asset-sub" style="max-width:240px;overflow:hidden;text-overflow:ellipsis">${[a.vehicle_make, a.vehicle_model, a.vehicle_year, a.vehicle_plate ? '• ' + a.vehicle_plate : ''].filter(Boolean).join(' ')}</div>`
                : (a.description ? `<div class="asset-sub" style="max-width:200px;overflow:hidden;text-overflow:ellipsis">${escHtml(a.description)}</div>` : '')}
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
          <button class="btn btn-ghost btn-sell-asset" data-id="${a.id}" data-name="${escHtml(a.name)}" data-value="${a.estimated_value ?? 0}" title="Vendre / Archiver" style="color:var(--accent-gold)">🏷️</button>
          <button class="btn btn-ghost danger btn-del-asset" data-id="${a.id}" data-name="${escHtml(a.name)}">🗑</button>
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

  const DOC_TYPE_LABELS = {
    acte_notarie: '📜 Acte notarié', compromis: '🤝 Compromis', titre_propriete: '🏛 Titre de propriété',
    peb: '⚡ PEB', plan: '📐 Plan/cadastre',
    facture: '🧾 Facture d\'achat', facture_vente: '🧾 Facture de vente',
    carte_grise: '📋 Carte grise', assurance: '🛡 Assurance',
    controle_technique: '🔧 CT', certificat: '📜 Certificat', photo: '📷 Photo', autre: '📄 Autre',
  };

  const docsHtml = !(a.documents?.length) ? '<div style="color:var(--text-secondary);font-size:12px">Aucun document</div>' :
    `<div style="display:flex;flex-wrap:wrap;gap:8px">
    ${a.documents.map(d => `
      <div style="background:var(--bg-tertiary);border:1px solid var(--border);border-radius:var(--radius-sm);padding:8px 12px;display:flex;align-items:center;gap:8px">
        <span style="font-size:18px">📄</span>
        <div>
          <div style="font-size:12px;font-weight:500">${escHtml(d.filename)}</div>
          <div style="font-size:11px;color:var(--text-secondary)">${d.document_type ? (DOC_TYPE_LABELS[d.document_type] ?? d.document_type) + ' · ' : ''}${fmtSize(d.size_bytes)} · ${fmtDate(d.created_at)}</div>
        </div>
        <button class="btn btn-ghost btn-sm btn-download-doc" data-asset="${a.id}" data-doc="${d.id}" data-filename="${escHtml(d.filename)}">⬇</button>
        ${isAdmin() ? `<button class="btn btn-ghost danger btn-sm" onclick="deleteDocConfirm(${a.id},${d.id})">🗑</button>` : ''}
      </div>`).join('')}
    </div>`;

  // Immo info panel
  const immoHtml = a.category === 'immo' && a.location ? `
    <div style="margin-bottom:20px">
      <div style="font-size:11px;font-weight:500;color:var(--text-secondary);text-transform:uppercase;letter-spacing:.08em;margin-bottom:10px">🏠 Localisation du bien</div>
      <div style="background:var(--bg-tertiary);border:1px solid var(--border);border-radius:var(--radius-sm);padding:10px 14px;font-size:13px">${escHtml(a.location)}</div>
    </div>` : '';

  // Vehicle info panel
  const vehicleHtml = a.category === 'vehicule' ? `
    <div style="margin-bottom:20px">
      <div style="font-size:11px;font-weight:500;color:var(--text-secondary);text-transform:uppercase;letter-spacing:.08em;margin-bottom:10px">🚗 Fiche véhicule</div>
      <div style="display:grid;grid-template-columns:repeat(auto-fill,minmax(160px,1fr));gap:10px">
        ${_vField('Marque', a.vehicle_make)}
        ${_vField('Modèle', a.vehicle_model)}
        ${_vField('Année', a.vehicle_year)}
        ${_vField('Carburant', a.vehicle_fuel ? (a.vehicle_fuel.charAt(0).toUpperCase() + a.vehicle_fuel.slice(1)) : null)}
        ${_vField('Immatriculation', a.vehicle_plate)}
        ${_vField('Kilométrage', a.vehicle_km != null ? fmtNum(a.vehicle_km, 0) + ' km' : null)}
        ${a.vehicle_vin ? `<div style="grid-column:1/-1">${_vField('VIN / Châssis', a.vehicle_vin)}</div>` : ''}
      </div>
    </div>` : '';

  return `
    <div style="padding-bottom:4px">
      ${immoHtml}
      ${vehicleHtml}
      <div style="display:grid;grid-template-columns:1fr 1fr;gap:24px">
        <div>
          <div style="font-size:11px;font-weight:500;color:var(--text-secondary);text-transform:uppercase;letter-spacing:.08em;margin-bottom:10px">Événements</div>
          ${eventsHtml}
        </div>
        <div>
          <div style="font-size:11px;font-weight:500;color:var(--text-secondary);text-transform:uppercase;letter-spacing:.08em;margin-bottom:10px">Documents</div>
          ${docsHtml}
        </div>
      </div>
    </div>`;
}

function renderSoldAssetsSection() {
  if (!_soldAssetsData.length) return '';
  const totalSale = _soldAssetsData.reduce((s, a) => s + (a.sale_price || 0), 0);
  const coffreMap = Object.fromEntries(_coffresList.map(c => [c.id, c.name]));

  const rows = _soldAssetsData.map(a => {
    const soldDate = a.sold_at ? fmtDate(a.sold_at) : '—';
    const destLabel = SALE_DEST_LABELS[a.sale_destination] || (a.sale_destination || '—');
    return `
      <tr onclick="toggleAssetExpand('sold-${a.id}')" style="opacity:.85">
        <td class="left" style="padding-left:24px">
          <div class="asset-name-cell">
            <div class="pos-icon ${a.category || 'autre'}">${ASSET_CAT_ICONS[a.category || 'autre'] ?? '📦'}</div>
            <div>
              <div class="asset-name">${escHtml(a.name)}</div>
              ${a.description ? `<div class="asset-sub">${escHtml(a.description)}</div>` : ''}
            </div>
          </div>
        </td>
        <td class="left"><span class="badge badge-${a.category || 'autre'}">${ASSET_CAT_LABELS[a.category || 'autre'] ?? a.category}</span></td>
        <td class="left" style="color:var(--text-secondary);font-size:12px">${soldDate}</td>
        <td><strong style="color:var(--accent-green)">${a.sale_price != null ? fmtEur(a.sale_price) : '—'}</strong></td>
        <td class="left" style="font-size:12px;color:var(--text-secondary)">${escHtml(destLabel)}</td>
        <td style="color:var(--text-secondary)">${(a.documents || []).length}</td>
        ${isAdmin() ? `<td><div style="display:flex;justify-content:flex-end;gap:4px" onclick="event.stopPropagation()">
          <button class="btn btn-ghost primary" onclick="openUploadDocModal(${a.id})" title="Joindre document">📎</button>
        </div></td>` : ''}
      </tr>
      <tr class="expand-row"><td colspan="${isAdmin() ? 7 : 6}">
        <div class="expand-content" id="asset-expand-sold-${a.id}">${buildAssetDetails(a)}</div>
      </td></tr>`;
  }).join('');

  return `
    <div class="card" style="padding:0;overflow:hidden;margin-top:20px">
      <div class="section-header">
        <div class="section-title">🏷️ Historique des ventes <span class="section-count">${_soldAssetsData.length}</span></div>
        <div style="font-family:var(--font-display);font-size:14px;color:var(--accent-green)">${fmtEur(totalSale)}</div>
      </div>
      <div class="table-wrap">
        <table class="data-table">
          <thead><tr>
            <th class="left" style="padding-left:24px">Actif</th>
            <th class="left">Catégorie</th>
            <th class="left">Date de vente</th>
            <th>Prix de vente</th>
            <th class="left">Destination des fonds</th>
            <th>Documents</th>
            ${isAdmin() ? '<th>Actions</th>' : ''}
          </tr></thead>
          <tbody>${rows}</tbody>
        </table>
      </div>
    </div>`;
}

function _vField(label, value) {
  if (!value && value !== 0) return '';
  return `<div style="background:var(--bg-tertiary);border:1px solid var(--border);border-radius:var(--radius-sm);padding:8px 10px">
    <div style="font-size:10px;color:var(--text-secondary);margin-bottom:2px">${label}</div>
    <div style="font-size:13px;font-weight:500">${escHtml(String(value))}</div>
  </div>`;
}

function toggleAssetExpand(assetId) {
  // assetId peut être un nombre (actif actif) ou "sold-{id}" (actif vendu)
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
  const el = document.getElementById('assetModals');
  if (!el) return;
  const coffreOptions = _coffresList.map(c => `<option value="${c.id}">${escHtml(c.name)}</option>`).join('');
  el.innerHTML = `
    <!-- Add/Edit asset -->
    <div class="modal-overlay" id="assetModal">
      <div class="modal" style="max-width:640px">
        <div class="modal-header"><span class="modal-title" id="assetModalTitle">Ajouter un actif</span><button class="modal-close" onclick="closeModal('assetModal')">✕</button></div>
        <form onsubmit="submitAssetModal(event)" class="form-grid">
          <div class="form-group full"><label class="form-label">Nom</label><input type="text" class="form-input" id="assetName" required/></div>
          <div class="form-group"><label class="form-label">Catégorie</label>
            <select class="form-select" id="assetCategory" onchange="toggleCatFields(this.value)">
              ${Object.entries(ASSET_CAT_LABELS).map(([k, v]) => `<option value="${k}">${v}</option>`).join('')}
            </select>
          </div>
          <div class="form-group"><label class="form-label">Valeur estimée (€)</label><input type="number" class="form-input" id="assetValue" step="0.01" placeholder="0.00"/></div>
          <div class="form-group" id="assetCoffreRow"><label class="form-label">Coffre</label>
            <select class="form-select" id="assetCoffre"><option value="">—</option>${coffreOptions}</select>
          </div>
          <div class="form-group full"><label class="form-label">Description</label><textarea class="form-textarea" id="assetDesc" rows="2"></textarea></div>

          <!-- Champs immobilier (masqués par défaut) -->
          <div id="immoFields" style="display:none;grid-column:1/-1">
            <div style="font-size:11px;font-weight:600;color:var(--text-secondary);text-transform:uppercase;letter-spacing:.08em;margin:8px 0 12px;border-top:1px solid var(--border);padding-top:12px">🏠 Localisation du bien</div>
            <div class="form-group full"><label class="form-label">Adresse</label><input type="text" class="form-input" id="assetLocation" placeholder="ex: 12 rue de la Paix, 75001 Paris"/></div>
          </div>

          <!-- Champs véhicule (masqués par défaut) -->
          <div id="vehicleFields" style="display:none;grid-column:1/-1">
            <div style="font-size:11px;font-weight:600;color:var(--text-secondary);text-transform:uppercase;letter-spacing:.08em;margin:8px 0 12px;border-top:1px solid var(--border);padding-top:12px">🚗 Informations véhicule</div>
            <div class="form-grid" style="padding:0">
              <div class="form-group"><label class="form-label">Marque</label><input type="text" class="form-input" id="vMake" placeholder="ex: Volkswagen"/></div>
              <div class="form-group"><label class="form-label">Modèle</label><input type="text" class="form-input" id="vModel" placeholder="ex: Golf"/></div>
              <div class="form-group"><label class="form-label">Année</label><input type="number" class="form-input" id="vYear" placeholder="ex: 2021" min="1900" max="2100"/></div>
              <div class="form-group"><label class="form-label">Carburant</label>
                <select class="form-select" id="vFuel">
                  <option value="">—</option>
                  <option value="essence">Essence</option>
                  <option value="diesel">Diesel</option>
                  <option value="hybride">Hybride</option>
                  <option value="electrique">Électrique</option>
                  <option value="gpl">GPL</option>
                  <option value="autre">Autre</option>
                </select>
              </div>
              <div class="form-group"><label class="form-label">Immatriculation</label><input type="text" class="form-input" id="vPlate" placeholder="ex: 1-ABC-234" style="text-transform:uppercase"/></div>
              <div class="form-group"><label class="form-label">Kilométrage</label><input type="number" class="form-input" id="vKm" placeholder="ex: 45000" min="0"/></div>
              <div class="form-group full"><label class="form-label">Numéro VIN / Châssis</label><input type="text" class="form-input" id="vVin" placeholder="ex: VF1RFD00X56789012" style="text-transform:uppercase"/></div>
            </div>
          </div>

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
            <select class="form-select" id="docType"><option value="">—</option>
              <optgroup label="Immobilier">
                <option value="acte_notarie">Acte notarié</option>
                <option value="compromis">Compromis de vente</option>
                <option value="titre_propriete">Titre de propriété</option>
                <option value="peb">Certificat PEB</option>
                <option value="plan">Plan / cadastre</option>
              </optgroup>
              <optgroup label="Véhicule">
                <option value="carte_grise">Carte grise</option>
                <option value="controle_technique">Contrôle technique</option>
              </optgroup>
              <optgroup label="Général">
                <option value="facture">Facture d'achat</option>
                <option value="facture_vente">Facture de vente</option>
                <option value="assurance">Assurance</option>
                <option value="certificat">Certificat</option>
                <option value="photo">Photo</option>
                <option value="autre">Autre</option>
              </optgroup>
            </select>
          </div>
          <div class="form-group" style="margin-bottom:20px"><label class="form-label">Note</label><input type="text" class="form-input" id="docNotes"/></div>
          <input type="hidden" id="docAssetId"/>
          <div class="form-actions"><button type="button" class="btn btn-secondary" onclick="closeModal('uploadDocModal')">Annuler</button><button type="submit" class="btn btn-primary">Chiffrer et envoyer</button></div>
        </form>
      </div>
    </div>

    <!-- Sell asset modal -->
    <div class="modal-overlay" id="sellAssetModal">
      <div class="modal" style="max-width:520px">
        <div class="modal-header">
          <span class="modal-title" id="sellModalTitle">🏷️ Vendre l'actif</span>
          <button class="modal-close" onclick="closeModal('sellAssetModal')">✕</button>
        </div>
        <form onsubmit="submitSellModal(event)" class="form-grid">
          <div class="form-group"><label class="form-label">Prix de vente (€)</label>
            <input type="number" class="form-input" id="sellPrice" step="0.01" min="0" required placeholder="0.00"/>
          </div>
          <div class="form-group"><label class="form-label">Date de vente</label>
            <input type="date" class="form-input" id="sellDate" required/>
          </div>
          <div class="form-group full"><label class="form-label">Destination des fonds</label>
            <select class="form-select" id="sellDestination">
              <option value="">— Non précisé —</option>
              <option value="portfolio">📈 Investi en portefeuille boursier</option>
              <option value="bank">🏧 Versé sur compte bancaire</option>
              <option value="coffre">🔐 Déposé en coffre (espèces)</option>
              <option value="cash">💵 Reçu en espèces (hors coffre)</option>
              <option value="other">📦 Autre destination</option>
            </select>
          </div>
          <div class="form-group full"><label class="form-label">Note (optionnel)</label>
            <textarea class="form-textarea" id="sellNotes" rows="2" placeholder="Détails de la transaction…"></textarea>
          </div>
          <div style="grid-column:1/-1;font-size:12px;color:var(--text-muted);background:var(--bg-tertiary);border:1px solid var(--border);border-radius:var(--radius-sm);padding:10px 14px">
            ℹ️ L'actif sera archivé (non supprimé). Vous pourrez toujours y joindre des documents (facture de vente, etc.) depuis l'historique.
          </div>
          <input type="hidden" id="sellAssetId"/>
          <div class="form-actions">
            <button type="button" class="btn btn-secondary" onclick="closeModal('sellAssetModal')">Annuler</button>
            <button type="submit" class="btn btn-primary" style="background:var(--accent-gold);border-color:var(--accent-gold)">Confirmer la vente</button>
          </div>
        </form>
      </div>
    </div>`;
}

function toggleCatFields(cat) {
  const vf  = document.getElementById('vehicleFields');
  const imf = document.getElementById('immoFields');
  const coffreRow = document.getElementById('assetCoffreRow');
  if (vf)  vf.style.display  = cat === 'vehicule' ? 'block' : 'none';
  if (imf) imf.style.display = cat === 'immo'     ? 'block' : 'none';
  // Le coffre n'a pas de sens pour un bien immobilier
  if (coffreRow) coffreRow.style.display = cat === 'immo' ? 'none' : '';
}

// Legacy alias kept for any inline onchange still using it
function toggleVehicleFields(cat) { toggleCatFields(cat); }

function openAddAssetModal() {
  document.getElementById('assetModalTitle').textContent = 'Ajouter un actif';
  document.getElementById('assetModalBtn').textContent = 'Créer';
  document.getElementById('assetModalId').value = '';
  document.getElementById('assetName').value = '';
  document.getElementById('assetCategory').value = 'autre';
  document.getElementById('assetValue').value = '';
  document.getElementById('assetCoffre').value = '';
  document.getElementById('assetDesc').value = '';
  document.getElementById('assetLocation').value = '';
  _clearVehicleFields();
  toggleCatFields('autre');
  openModal('assetModal');
}

function _clearVehicleFields() {
  ['vMake','vModel','vYear','vFuel','vPlate','vKm','vVin'].forEach(id => {
    const el = document.getElementById(id);
    if (el) el.value = '';
  });
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
  document.getElementById('assetLocation').value = a.location ?? '';
  // Vehicle fields
  _clearVehicleFields();
  if (a.category === 'vehicule') {
    document.getElementById('vMake').value = a.vehicle_make ?? '';
    document.getElementById('vModel').value = a.vehicle_model ?? '';
    document.getElementById('vYear').value = a.vehicle_year ?? '';
    document.getElementById('vFuel').value = a.vehicle_fuel ?? '';
    document.getElementById('vPlate').value = a.vehicle_plate ?? '';
    document.getElementById('vKm').value = a.vehicle_km ?? '';
    document.getElementById('vVin').value = a.vehicle_vin ?? '';
  }
  toggleCatFields(a.category || 'autre');
  openModal('assetModal');
}

async function submitAssetModal(e) {
  e.preventDefault();
  const id = document.getElementById('assetModalId').value;
  const cat = document.getElementById('assetCategory').value;
  const body = {
    name: document.getElementById('assetName').value,
    category: cat,
    estimated_value: parseFloat(document.getElementById('assetValue').value) || null,
    coffre_id: parseInt(document.getElementById('assetCoffre').value) || null,
    description: document.getElementById('assetDesc').value || null,
    location: cat === 'immo' ? (document.getElementById('assetLocation').value || null) : null,
    // Vehicle fields (null if not vehicule category)
    vehicle_make: cat === 'vehicule' ? (document.getElementById('vMake').value || null) : null,
    vehicle_model: cat === 'vehicule' ? (document.getElementById('vModel').value || null) : null,
    vehicle_year: cat === 'vehicule' ? (parseInt(document.getElementById('vYear').value) || null) : null,
    vehicle_fuel: cat === 'vehicule' ? (document.getElementById('vFuel').value || null) : null,
    vehicle_plate: cat === 'vehicule' ? (document.getElementById('vPlate').value.toUpperCase() || null) : null,
    vehicle_km: cat === 'vehicule' ? (parseInt(document.getElementById('vKm').value) || null) : null,
    vehicle_vin: cat === 'vehicule' ? (document.getElementById('vVin').value.toUpperCase() || null) : null,
  };
  try {
    if (id) { await apiPut(`/api/assets/${id}`, body); showToast('Actif mis à jour', 'success'); }
    else { await apiPost('/api/assets', body); showToast('Actif créé', 'success'); }
    closeModal('assetModal');
    await loadAssets();
  } catch (err) { showToast(err.message, 'error'); }
}

// ── Sell asset ─────────────────────────────────────────────

function openSellAssetModal(assetId, name, estimatedValue) {
  document.getElementById('sellModalTitle').textContent = `🏷️ Vendre — ${name}`;
  document.getElementById('sellAssetId').value = assetId;
  document.getElementById('sellPrice').value = estimatedValue > 0 ? estimatedValue : '';
  document.getElementById('sellDate').value = todayISO();
  document.getElementById('sellDestination').value = '';
  document.getElementById('sellNotes').value = '';
  openModal('sellAssetModal');
}

async function submitSellModal(e) {
  e.preventDefault();
  const assetId = document.getElementById('sellAssetId').value;
  const body = {
    sale_price: parseFloat(document.getElementById('sellPrice').value),
    sold_at: document.getElementById('sellDate').value,
    sale_destination: document.getElementById('sellDestination').value || null,
    sale_notes: document.getElementById('sellNotes').value || null,
  };
  try {
    await apiPost(`/api/assets/${assetId}/sell`, body);
    showToast('Actif archivé comme vendu', 'success');
    closeModal('sellAssetModal');
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
  const btn = e.target.querySelector('[type=submit]');
  if (btn) { btn.disabled = true; btn.textContent = 'Envoi…'; }
  try {
    await apiFetch(`/api/assets/${assetId}/documents`, { method: 'POST', body: fd });
    showToast('Document chiffré et enregistré', 'success');
    closeModal('uploadDocModal');
    await loadAssets();
  } catch (err) {
    showToast(err.message, 'error');
  } finally {
    if (btn) { btn.disabled = false; btn.textContent = 'Chiffrer et envoyer'; }
  }
}

function deleteDocConfirm(assetId, docId) {
  confirm('Supprimer le document', 'Supprimer ce document ?', async () => {
    try { await apiDelete(`/api/assets/${assetId}/documents/${docId}`); showToast('Document supprimé', 'success'); await loadAssets(); }
    catch (err) { showToast(err.message, 'error'); }
  });
}

async function downloadDoc(assetId, docId, filename) {
  try {
    const res = await apiFetchRaw(`/api/assets/${assetId}/documents/${docId}/download`);
    if (!res.ok) { showToast('Erreur téléchargement', 'error'); return; }
    const blob = await res.blob();
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url; a.download = filename || 'document';
    document.body.appendChild(a); a.click();
    document.body.removeChild(a);
    setTimeout(() => URL.revokeObjectURL(url), 5000);
  } catch (err) { showToast(err.message, 'error'); }
}

// Délégation pour les boutons de téléchargement de documents
document.addEventListener('click', e => {
  const dlBtn = e.target.closest('.btn-download-doc');
  if (dlBtn) { downloadDoc(parseInt(dlBtn.dataset.asset), parseInt(dlBtn.dataset.doc), dlBtn.dataset.filename); return; }
  const delBtn = e.target.closest('.btn-del-asset');
  if (delBtn) { deleteAssetConfirm(parseInt(delBtn.dataset.id), delBtn.dataset.name); return; }
  const sellBtn = e.target.closest('.btn-sell-asset');
  if (sellBtn) openSellAssetModal(parseInt(sellBtn.dataset.id), sellBtn.dataset.name, parseFloat(sellBtn.dataset.value) || 0);
});
