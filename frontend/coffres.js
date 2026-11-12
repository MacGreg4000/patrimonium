/* ═══════════════════════════════════════════════
   COFFRES — Cash management module
   ═══════════════════════════════════════════════
   La page est découpée en zones (cartes, contenu du coffre, opération,
   graphique, historique), chacune redessinée seule. Changer de coffre ou de
   mode ne recharge donc plus toute la page, et la saisie en cours est gardée.
   Les requêtes d'écriture (mouvements, inventaires, transferts) sont celles
   d'origine, avec les mêmes données.
*/
'use strict';

const DENOMS = [5, 10, 20, 50, 100, 200, 500];

const CAISSE_MODES = {
  entry:     { label: 'Entrée',     icon: '↑', color: 'var(--accent-green)' },
  exit:      { label: 'Sortie',     icon: '↓', color: 'var(--accent-red)' },
  transfer:  { label: 'Transfert',  icon: '⇄', color: 'var(--accent-gold)' },
  inventory: { label: 'Inventaire', icon: '≡', color: 'var(--accent-blue)' },
};

let _coffresData = [];
let _selectedCoffreId = null;
let _caissMode = 'entry'; // entry | exit | inventory | transfer
let _editMovementId = null;
let _breakdowns = {};     // coffre_id → breakdown data

// Saisie en cours, conservée d'un rendu à l'autre. Entrée et sortie partagent
// les mêmes billets (on peut changer d'avis sans tout ressaisir) ; l'inventaire,
// qui compte tout le coffre, a les siens.
const _billets = { flux: {}, inventaire: {} };
let _caisseNote = '';
let _transfer = { dest: '', amount: '' };
let _submitting = false;

// Historique : coffre sélectionné (paginé) ou tous les coffres (50 plus récents)
let _histScope = 'coffre';
let _histItems = [];
let _histPage = 1;
let _histTotal = 0;
let _histRequest = 0;

const _selectedCoffre = () => _coffresData.find(c => c.id === _selectedCoffreId) || null;
const _billetKey = () => (_caissMode === 'inventory' ? 'inventaire' : 'flux');

// ── Chargement ────────────────────────────────────────────

async function loadCoffres() {
  try {
    _coffresData = await apiGet('/api/coffres');
  } catch (err) {
    showToast('Erreur coffres: ' + err.message, 'error');
    return;
  }
  if (!_coffresData.some(c => c.id === _selectedCoffreId)) {
    const fav = _coffresData.find(c => c.is_favorite);
    _selectedCoffreId = fav ? fav.id : (_coffresData[0] ? _coffresData[0].id : null);
  }

  // Squelette dessiné une fois ; redessiné seulement s'il ne correspond plus
  // (premier coffre créé, ou dernier coffre supprimé, depuis l'administration).
  const hasZones = !!document.getElementById('cf-cards');
  if (!document.getElementById('cf-root') || hasZones !== (_coffresData.length > 0)) renderCoffresPage();
  if (!_coffresData.length) return;

  renderCoffreCards();
  renderCoffreOverview();
  renderCaisseInterface();
  await Promise.all([loadBreakdowns(), loadHistory(), loadBalanceChart(_selectedCoffreId)]);
}

async function loadBreakdowns() {
  await Promise.all(_coffresData.map(async c => {
    try {
      _breakdowns[c.id] = await apiGet(`/api/coffres/${c.id}/breakdown`);
    } catch (_) {}
  }));
  renderCoffreOverview();
}

// ── Squelette de la page (rendu une seule fois) ───────────

function renderCoffresPage() {
  const page = document.getElementById('page-coffres');
  if (!page) return;

  const header = `
    <div class="cf-header db-head">
      <div>
        <h1 class="db-title">Coffres</h1>
        <div class="db-subtitle">${_coffresData.length} coffre${_coffresData.length > 1 ? 's' : ''} · billets, transferts et inventaires</div>
      </div>
      ${isAdmin() ? `<button class="btn btn-secondary" onclick="navigate('admin')">Gérer les coffres</button>` : ''}
    </div>`;

  if (!_coffresData.length) {
    page.innerHTML = `<div id="cf-root">${header}
      <div class="card"><div class="empty-state"><div class="empty-icon">${ICONS.landmark}</div>
        <div class="empty-text">Aucun coffre disponible</div>
        ${isAdmin() ? `<div class="empty-sub">Créez un coffre depuis l'administration</div>` : ''}
      </div></div></div>`;
    return;
  }

  page.innerHTML = `
    <div id="cf-root">
      ${header}

      <div id="cf-cards" class="cf-cards" aria-label="Choisir un coffre"></div>

      <div class="cf-layout">
        <section id="cf-overview" class="card cf-overview" aria-label="Contenu du coffre"></section>
        <section id="cf-op" class="card cf-op" aria-label="Nouvelle opération"></section>
      </div>

      <div class="card cf-block">
        <div class="cf-block-head">
          <div class="card-title" style="margin:0">Évolution du solde — <span id="balanceChartCoffreName"></span></div>
          <label class="cf-collapse">
            <span class="cf-collapse-label">Graphique</span>
            ${collapseSwitch('coffreBalance', 'coffreBalanceBody', false)}
          </label>
        </div>
        <div id="coffreBalanceBody" class="${collapseBodyClass('coffreBalance', false)}">
          <div style="height:220px"><canvas id="coffreBalanceChart"></canvas></div>
          <div id="coffreBalanceChartEmpty" style="display:none;text-align:center;padding:40px 0;color:var(--text-muted);font-size:13px">Aucun mouvement enregistré</div>
        </div>
      </div>

      <div class="card cf-block cf-history" id="coffresHistorySection">
        <div class="cf-block-head">
          <div class="section-title">Historique <span class="section-count" id="historyCount">—</span></div>
          <div class="cf-history-tools">
            <div class="cf-scope" role="group" aria-label="Portée de l'historique">
              <button type="button" data-scope="coffre" onclick="setHistScope('coffre')">Ce coffre</button>
              <button type="button" data-scope="all" onclick="setHistScope('all')">Tous</button>
            </div>
            <label class="cf-collapse">
              <span class="cf-collapse-label">Afficher</span>
              ${collapseSwitch('coffreHistory', 'historyBodyWrap', false)}
            </label>
          </div>
        </div>
        <div id="historyBodyWrap" class="${collapseBodyClass('coffreHistory', false)}">
          <div id="historyBody">
            <div class="empty-state"><div class="empty-icon">📋</div><div class="empty-text">Chargement…</div></div>
          </div>
        </div>
      </div>

      ${_coffreModalsHtml()}
    </div>`;
}

function _coffreModalsHtml() {
  return `
    <!-- Edit movement modal -->
    <div class="modal-overlay" id="editMovementModal">
      <div class="modal">
        <div class="modal-header">
          <span class="modal-title">Modifier le mouvement</span>
          <button class="modal-close" onclick="closeModal('editMovementModal')" aria-label="Fermer">✕</button>
        </div>
        <form onsubmit="submitEditMovement(event)" class="form-grid">
          <div class="form-group full"><label class="form-label" for="editMvtAmount">Montant (€)</label><input type="number" class="form-input" id="editMvtAmount" step="0.01" inputmode="decimal" required/></div>
          <div class="form-group full"><label class="form-label" for="editMvtDesc">Note</label><textarea class="form-textarea" id="editMvtDesc" rows="2" placeholder="Optionnel"></textarea></div>
          <div class="form-actions">
            <button type="button" class="btn btn-secondary" onclick="closeModal('editMovementModal')">Annuler</button>
            <button type="submit" class="btn btn-primary">Enregistrer</button>
          </div>
        </form>
      </div>
    </div>

    <!-- Modal code d'accès -->
    <div class="modal-overlay" id="combinationModal">
      <div class="modal" style="max-width:380px">
        <div class="modal-header">
          <span class="modal-title">Code d'accès du coffre</span>
          <button class="modal-close" onclick="closeModal('combinationModal')" aria-label="Fermer">✕</button>
        </div>
        <form onsubmit="submitSetCombination(event)" class="form-grid" style="grid-template-columns:1fr">
          <div class="form-group">
            <label class="form-label" for="combinationInput">Code / Combinaison</label>
            <input type="text" class="form-input" id="combinationInput" required
              placeholder="ex: A-23-B-07 ou 1234*" autocomplete="off"
              style="font-family:var(--font-display);font-size:18px;letter-spacing:.15em"/>
          </div>
          <div class="form-group">
            <label class="form-label" for="combinationHint">Indice mémo <span style="color:var(--text-muted)">(non chiffré, visible sans révéler)</span></label>
            <input type="text" class="form-input" id="combinationHint" placeholder="ex: Date anniversaire en chiffres"/>
          </div>
          <input type="hidden" id="combinationCoffreId"/>
          <div class="form-actions">
            <button type="button" class="btn btn-secondary" onclick="closeModal('combinationModal')">Annuler</button>
            <button type="submit" class="btn btn-primary">Enregistrer</button>
          </div>
        </form>
      </div>
    </div>`;
}

// ── Zone 1 : cartes (unique sélecteur de coffre) ──────────

function renderCoffreCards() {
  const el = document.getElementById('cf-cards');
  if (!el) return;
  const total = _coffresData.reduce((s, c) => s + c.balance, 0);
  const n = _coffresData.length;

  el.innerHTML = `
    <div class="cf-card cf-card-total">
      <div class="cf-card-label">Total liquidités</div>
      <div class="cf-card-value">${fmtEur(total)}</div>
      <div class="cf-card-sub">${n} coffre${n > 1 ? 's' : ''}</div>
    </div>
    ${_coffresData.map(c => {
      const selected = c.id === _selectedCoffreId;
      const star = isAdmin()
        ? `<button type="button" class="cf-star ${c.is_favorite ? 'is-on' : ''}"
             onclick="event.stopPropagation();toggleFavoriteCoffre(${c.id})"
             title="${c.is_favorite ? 'Retirer des favoris' : 'Définir comme favori'}"
             aria-label="${c.is_favorite ? 'Retirer des favoris' : 'Définir comme favori'}">⭐</button>`
        : (c.is_favorite ? '<span class="cf-star is-on" aria-label="Favori">⭐</span>' : '');
      return `
        <div class="cf-card ${selected ? 'is-selected' : ''}" role="button" tabindex="0"
             aria-pressed="${selected}" onclick="selectCoffre(${c.id})"
             onkeydown="if(event.key==='Enter'||event.key===' '){event.preventDefault();selectCoffre(${c.id})}">
          <div class="cf-card-top">
            <span class="cf-card-label">${escHtml(c.name)}</span>${star}
          </div>
          <div class="cf-card-value">${fmtEur(c.balance)}</div>
        </div>`;
    }).join('')}`;
}

function selectCoffre(coffreId) {
  if (coffreId === _selectedCoffreId) return;
  _selectedCoffreId = coffreId;
  // Le transfert vise un autre coffre : la destination choisie n'a plus de sens
  _transfer.dest = '';
  renderCoffreCards();
  renderCoffreOverview();
  renderCaisseInterface();
  loadBalanceChart(coffreId);
  if (_histScope === 'coffre') loadHistory();
  if (!_breakdowns[coffreId]) {
    apiGet(`/api/coffres/${coffreId}/breakdown`).then(data => {
      _breakdowns[coffreId] = data;
      renderCoffreOverview();
    }).catch(() => {});
  }
}

async function toggleFavoriteCoffre(coffreId) {
  try {
    await apiPut(`/api/coffres/${coffreId}/favorite`, {});
    const wasFav = _coffresData.find(c => c.id === coffreId)?.is_favorite;
    _coffresData.forEach(c => { c.is_favorite = false; });
    const target = _coffresData.find(c => c.id === coffreId);
    if (target) target.is_favorite = !wasFav;
    renderCoffreCards();
    showToast(target?.is_favorite ? `⭐ ${target.name} défini comme favori` : 'Favori retiré', 'success');
  } catch (err) {
    showToast('Erreur : ' + err.message, 'error');
  }
}

// ── Zone 2 : contenu du coffre (solde, billets, code) ─────

function renderCoffreOverview() {
  const el = document.getElementById('cf-overview');
  if (!el) return;
  const coffre = _selectedCoffre();
  if (!coffre) { el.innerHTML = ''; return; }
  const bd = _breakdowns[coffre.id];

  el.innerHTML = `
    <div class="cf-ov-name">${escHtml(coffre.name)}</div>
    <div class="cf-ov-balance">${fmtEur(coffre.balance)}</div>
    <div class="cf-ov-meta">${_inventoryAge(bd)}</div>

    <div class="cf-section-label">Composition en billets</div>
    ${_compositionHtml(bd, coffre.balance)}

    <div class="cf-section-label cf-code-head">
      <span>Code d'accès</span>
      ${isAdmin() ? `<button class="btn btn-ghost btn-sm" onclick="openSetCombinationModal(${coffre.id})">Modifier</button>` : ''}
    </div>
    <div class="cf-code" id="combinationDisplay-${coffre.id}">
      <div class="cf-code-value" id="combinationValue-${coffre.id}">●●●●●●</div>
      <button class="btn btn-secondary btn-sm" onclick="revealCombination(${coffre.id})"
              id="revealBtn-${coffre.id}" title="Révéler le code">Afficher</button>
      ${isAdmin() ? `<button class="btn btn-ghost danger btn-sm" onclick="deleteCombination(${coffre.id})"
              id="delComboBtn-${coffre.id}" style="display:none" title="Supprimer le code" aria-label="Supprimer le code">🗑</button>` : ''}
    </div>`;
}

function _inventoryAge(bd) {
  if (!bd) return '';
  if (!bd.last_inventory_date) return 'Aucun inventaire enregistré';
  const days = Math.floor((Date.now() - new Date(bd.last_inventory_date).getTime()) / 86_400_000);
  const when = days <= 0 ? "aujourd'hui" : days === 1 ? 'hier' : `il y a ${days} jours`;
  return `Dernier inventaire ${when} (${fmtDate(bd.last_inventory_date)})`;
}

function _compositionHtml(bd, balance) {
  if (!bd) return `<div class="cf-note">Chargement…</div>`;
  if (!bd.has_data) return `<div class="cf-note">Faites un inventaire pour voir la composition en billets.</div>`;
  if (!bd.breakdown.length) return `<div class="cf-note">Coffre vide.</div>`;

  const rows = bd.breakdown.map(b => `
    <div class="cf-comp-row">
      <span class="cf-comp-denom">${b.denomination} €</span>
      <span class="cf-comp-qty">× ${b.quantity}</span>
      <span class="cf-comp-bar"><span style="width:${Math.round(b.subtotal / bd.total * 100)}%"></span></span>
      <span class="cf-comp-sub">${fmtEur(b.subtotal)}</span>
    </div>`).join('');
  // Les mouvements saisis sans détail de billets ne figurent pas dans la
  // composition : on le signale plutôt que d'afficher deux totaux contradictoires.
  const gap = Math.abs(bd.total - balance) > 0.005
    ? `<div class="cf-note" style="margin-top:8px">Billets détaillés : ${fmtEur(bd.total)} sur ${fmtEur(balance)} de solde.</div>`
    : '';
  return `<div class="cf-comp">${rows}</div>${gap}`;
}

// ── Zone 3 : nouvelle opération ───────────────────────────

function renderCaisseInterface() {
  const el = document.getElementById('cf-op');
  if (!el) return;
  const coffre = _selectedCoffre();
  if (!coffre) { el.innerHTML = ''; return; }

  if (!isAdmin()) {
    el.innerHTML = `<div class="cf-note" style="text-align:center;padding:24px">
      Accès en lecture seule — solde actuel : <strong style="color:var(--accent-gold)">${fmtEur(coffre.balance)}</strong></div>`;
    return;
  }

  const mode = CAISSE_MODES[_caissMode];
  el.style.setProperty('--mode-color', mode.color);
  el.innerHTML = `
    <div class="cf-op-title">Nouvelle opération <span class="cf-op-target">· ${escHtml(coffre.name)}</span></div>
    <div class="cf-modes" role="tablist" aria-label="Type d'opération">
      ${Object.entries(CAISSE_MODES).map(([key, m]) => `
        <button type="button" role="tab" aria-selected="${key === _caissMode}"
          class="cf-mode ${key === _caissMode ? 'is-active' : ''}" style="--mode-color:${m.color}"
          onclick="setCaisseMode('${key}')">
          <span class="cf-mode-icon" aria-hidden="true">${m.icon}</span><span>${m.label}</span>
        </button>`).join('')}
    </div>

    <form onsubmit="submitCaisse(event)" id="caisseForm" novalidate>
      ${_caissMode === 'transfer' ? _transferFormHtml(coffre) : _billetsFormHtml()}
      <div class="form-group" style="margin-bottom:14px">
        <label class="form-label" for="caisseNote">Note (optionnel)</label>
        <textarea class="form-textarea" id="caisseNote" rows="2" oninput="_caisseNote = this.value"
          placeholder="${_caissMode === 'transfer' ? 'Motif du transfert…' : 'Commentaire…'}">${escHtml(_caisseNote)}</textarea>
      </div>
      <button type="submit" class="cf-submit" id="caisseSubmit"></button>
    </form>`;

  if (_caissMode === 'transfer') updateTransferPreview();
  else updateCaisseTotal();
}

function _billetsFormHtml() {
  const st = _billets[_billetKey()];
  const tiles = DENOMS.map(d => `
    <div class="cf-billet">
      <div class="cf-billet-denom">${d} €</div>
      <div class="cf-billet-ctrl">
        <button type="button" class="cf-step" onclick="stepBillet(${d},-1)" aria-label="Un billet de ${d} € en moins">−</button>
        <input type="number" class="cf-billet-input" id="billet_${d}" min="0" step="1"
          inputmode="numeric" placeholder="0" value="${st[d] || ''}"
          onfocus="this.select()" oninput="onBilletInput(${d}, this)" aria-label="Nombre de billets de ${d} €"/>
        <button type="button" class="cf-step" onclick="stepBillet(${d},1)" aria-label="Un billet de ${d} € en plus">+</button>
      </div>
      <div class="cf-billet-sub" id="sub_${d}"></div>
    </div>`).join('');

  return `
    <div class="cf-billets">${tiles}</div>
    <div class="cf-summary">
      <div class="cf-summary-row is-total">
        <span>${_caissMode === 'inventory' ? 'Total compté' : _caissMode === 'entry' ? 'Montant entrant' : 'Montant sortant'}</span>
        <strong id="caisseTotal">0,00 €</strong>
      </div>
      <div id="cf-after"></div>
    </div>`;
}

function _transferFormHtml(coffre) {
  const others = _coffresData.filter(c => c.id !== coffre.id);
  if (!others.length) {
    return `<div class="cf-note" style="margin-bottom:14px">Aucun autre coffre vers lequel transférer.</div>`;
  }
  return `
    <div class="form-group" style="margin-bottom:14px">
      <label class="form-label" for="transferDest">Vers le coffre</label>
      <select class="form-select" id="transferDest" onchange="_transfer.dest = this.value; updateTransferPreview()">
        <option value="">— Choisir un coffre —</option>
        ${others.map(c => `<option value="${c.id}" ${String(c.id) === _transfer.dest ? 'selected' : ''}>${escHtml(c.name)} (${fmtEur(c.balance)})</option>`).join('')}
      </select>
    </div>
    <div class="form-group" style="margin-bottom:14px">
      <label class="form-label" for="transferAmount">Montant à transférer (€)</label>
      <input type="number" class="form-input cf-amount" id="transferAmount" min="0.01" step="0.01"
        inputmode="decimal" placeholder="0,00" value="${escHtml(_transfer.amount)}"
        oninput="_transfer.amount = this.value; updateTransferPreview()"/>
      <div id="transferPreview" class="cf-note" style="margin-top:6px"></div>
    </div>`;
}

function setCaisseMode(mode) {
  if (mode === _caissMode) return;
  _caissMode = mode;
  renderCaisseInterface();
}

function onBilletInput(denom, input) {
  const qty = Math.max(0, parseInt(input.value, 10) || 0);
  _billets[_billetKey()][denom] = qty;
  updateCaisseTotal();
}

function stepBillet(denom, delta) {
  const st = _billets[_billetKey()];
  st[denom] = Math.max(0, (st[denom] || 0) + delta);
  const input = document.getElementById(`billet_${denom}`);
  if (input) input.value = st[denom] || '';
  updateCaisseTotal();
}

function _billetsTotal() {
  const st = _billets[_billetKey()];
  return DENOMS.reduce((s, d) => s + (st[d] || 0) * d, 0);
}

function updateCaisseTotal() {
  const st = _billets[_billetKey()];
  DENOMS.forEach(d => {
    const sub = document.getElementById(`sub_${d}`);
    if (sub) sub.textContent = st[d] ? fmtEur(st[d] * d) : '';
  });
  const total = _billetsTotal();
  const totalEl = document.getElementById('caisseTotal');
  if (totalEl) totalEl.textContent = fmtEur(total);

  // Aperçu d'affichage seulement : aucun calcul métier n'en dépend.
  const coffre = _selectedCoffre();
  const after = document.getElementById('cf-after');
  if (after && coffre) {
    if (_caissMode === 'inventory') {
      const diff = total - coffre.balance;
      after.innerHTML = `<div class="cf-summary-row"><span>Écart avec le solde enregistré (${fmtEur(coffre.balance)})</span>
        <strong class="${diff < 0 ? 'neg' : ''}">${diff > 0 ? '+' : ''}${fmtEur(diff)}</strong></div>`;
    } else {
      const rest = _caissMode === 'entry' ? coffre.balance + total : coffre.balance - total;
      after.innerHTML = `<div class="cf-summary-row"><span>Solde après</span>
        <strong class="${rest < 0 ? 'neg' : ''}">${fmtEur(rest)}</strong></div>
        ${rest < 0 ? `<div class="cf-warn">⚠ La sortie dépasse le solde du coffre (${fmtEur(coffre.balance)}).</div>` : ''}`;
    }
  }

  const btn = document.getElementById('caisseSubmit');
  if (btn) {
    const labels = { entry: "Valider l'entrée", exit: 'Valider la sortie', inventory: "Enregistrer l'inventaire" };
    btn.textContent = _submitting ? 'Enregistrement…'
      : total > 0 ? `${labels[_caissMode]} de ${fmtEur(total)}` : labels[_caissMode];
    // Un inventaire à 0 € est légitime (coffre vide) ; une entrée ou sortie vide, non.
    btn.disabled = _submitting || (_caissMode !== 'inventory' && total <= 0);
  }
}

function updateTransferPreview() {
  const amount = parseFloat(document.getElementById('transferAmount')?.value) || 0;
  const src = _selectedCoffre();
  const preview = document.getElementById('transferPreview');
  if (preview && src) {
    if (amount <= 0) preview.textContent = '';
    else {
      const remaining = src.balance - amount;
      preview.innerHTML = remaining < 0
        ? `<span style="color:var(--accent-red)">⚠ Solde insuffisant (${fmtEur(src.balance)} disponibles)</span>`
        : `Solde restant dans <strong>${escHtml(src.name)}</strong> : ${fmtEur(remaining)}`;
    }
  }
  const btn = document.getElementById('caisseSubmit');
  if (btn) {
    btn.textContent = _submitting ? 'Enregistrement…'
      : amount > 0 ? `Valider le transfert de ${fmtEur(amount)}` : 'Valider le transfert';
    btn.disabled = _submitting || amount <= 0 || !document.getElementById('transferDest')?.value;
  }
}

function _refreshSubmitButton() {
  if (_caissMode === 'transfer') updateTransferPreview();
  else updateCaisseTotal();
}

async function submitCaisse(e) {
  e.preventDefault();
  if (_submitting) return;   // évite un double enregistrement (double appui sur mobile)
  const coffre = _selectedCoffre();
  if (!coffre) return;
  const coffreId = coffre.id;
  const note = document.getElementById('caisseNote')?.value || null;

  if (_caissMode === 'transfer') {
    const destId = parseInt(document.getElementById('transferDest')?.value);
    const amount = parseFloat(document.getElementById('transferAmount')?.value);
    if (!destId) { showToast('Choisissez un coffre destination', 'error'); return; }
    if (!amount || amount <= 0) { showToast('Montant invalide', 'error'); return; }
    await _runCaisseWrite(async () => {
      await apiPost('/api/movements/transfer', {
        source_coffre_id: coffreId,
        destination_coffre_id: destId,
        amount,
        description: note,
      });
      const destName = _coffresData.find(c => c.id === destId)?.name || '';
      showToast(`⇄ ${fmtEur(amount)} transféré vers ${destName}`, 'success');
      _transfer = { dest: '', amount: '' };
    });
    return;
  }

  const key = _billetKey();
  const mode = _caissMode;
  const details = DENOMS.map(d => ({
    denomination: d,
    quantity: _billets[key][d] || 0,
  })).filter(d => d.quantity > 0);
  const total = details.reduce((s, d) => s + d.denomination * d.quantity, 0);

  const send = () => _runCaisseWrite(async () => {
    if (mode === 'inventory') {
      await apiPost('/api/inventories', { coffre_id: coffreId, total_amount: total, notes: note, details });
      showToast('Inventaire enregistré', 'success');
    } else {
      await apiPost('/api/movements', {
        coffre_id: coffreId, type: mode === 'entry' ? 'ENTRY' : 'EXIT',
        amount: total, description: note, details,
      });
      showToast(mode === 'entry' ? 'Entrée enregistrée' : 'Sortie enregistrée', 'success');
    }
    _billets[key] = {};
  });

  if (mode === 'exit' && total > coffre.balance + 0.005) {
    confirm('Sortie supérieure au solde',
      `La sortie de ${fmtEur(total)} dépasse le solde de ${coffre.name} (${fmtEur(coffre.balance)}). L'enregistrer quand même ?`,
      send);
    return;
  }
  await send();
}

async function _runCaisseWrite(write) {
  _submitting = true;
  _refreshSubmitButton();
  try {
    await write();
    _caisseNote = '';
    await loadCoffres();
  } catch (err) {
    showToast(err.message, 'error');
  } finally {
    _submitting = false;
    _refreshSubmitButton();
  }
}

// ── Zone 4 : graphique du solde ───────────────────────────

async function loadBalanceChart(coffreId) {
  const coffre = _coffresData.find(c => c.id === coffreId);
  const nameEl = document.getElementById('balanceChartCoffreName');
  if (nameEl && coffre) nameEl.textContent = coffre.name;
  if (!coffre) return;

  try {
    // Fetch full history (limit generous — cash movements are typically few)
    const data = await apiGet(`/api/coffres/${coffreId}/history?limit=500`);
    if (coffreId !== _selectedCoffreId) return;   // un autre coffre a été choisi entre-temps
    const items = (data.items || []).slice().reverse(); // oldest first

    const points = [];
    let balance = 0;

    for (const item of items) {
      const date = item.date || item.created_at;
      if (item.kind === 'inventory') {
        balance = item.total_amount;
      } else if (item.kind === 'movement') {
        balance += item.type === 'ENTRY' ? item.amount : -item.amount;
      }
      points.push({ date, balance });
    }

    const emptyEl = document.getElementById('coffreBalanceChartEmpty');
    const canvas  = document.getElementById('coffreBalanceChart');

    if (!points.length) {
      if (emptyEl) emptyEl.style.display = '';
      if (canvas)  canvas.style.display  = 'none';
      return;
    }

    if (emptyEl) emptyEl.style.display = 'none';
    if (canvas)  canvas.style.display  = '';

    renderCoffreBalanceLine('coffreBalanceChart', points);
  } catch (err) {
    console.warn('Balance chart:', err);
  }
}

// ── Zone 5 : historique ───────────────────────────────────

function setHistScope(scope) {
  if (scope === _histScope) return;
  _histScope = scope;
  loadHistory();
}

async function loadHistory(append = false) {
  const body = document.getElementById('historyBody');
  if (!body) return;
  const request = ++_histRequest;   // ignore les réponses arrivées dans le désordre

  document.querySelectorAll('.cf-scope [data-scope]').forEach(b => {
    b.classList.toggle('is-active', b.dataset.scope === _histScope);
    b.setAttribute('aria-pressed', b.dataset.scope === _histScope);
  });

  try {
    if (_histScope === 'coffre' && _selectedCoffreId) {
      // Historique complet du coffre, page par page (endpoint existant)
      const page = append ? _histPage + 1 : 1;
      const data = await apiGet(`/api/coffres/${_selectedCoffreId}/history?page=${page}&limit=50`);
      if (request !== _histRequest) return;
      _histItems = append ? _histItems.concat(data.items || []) : (data.items || []);
      _histPage = page;
      _histTotal = data.total || 0;
    } else {
      const [mvData, invData] = await Promise.all([
        apiGet('/api/movements?limit=50'),
        apiGet('/api/inventories?limit=20'),
      ]);
      if (request !== _histRequest) return;
      _histItems = [
        ...(mvData.items || []).map(m => ({ ...m, kind: 'movement' })),
        ...(invData.items || []).map(i => ({ ...i, kind: 'inventory' })),
      ].sort((a, b) => new Date(b.created_at || b.date) - new Date(a.created_at || a.date)).slice(0, 50);
      _histPage = 1;
      _histTotal = (mvData.total || 0) + (invData.total || 0);
    }
    renderHistory();
  } catch (err) {
    showToast('Erreur historique: ' + err.message, 'error');
  }
}

function renderHistory() {
  const body = document.getElementById('historyBody');
  if (!body) return;
  const items = _histItems;

  // Afficher le vrai total, pas seulement le nombre de lignes chargées.
  const countEl = document.getElementById('historyCount');
  if (countEl) countEl.textContent = _histTotal > items.length ? `${items.length} sur ${_histTotal}` : items.length;

  if (!items.length) {
    body.innerHTML = `<div class="empty-state"><div class="empty-icon">📋</div><div class="empty-text">Aucun mouvement</div></div>`;
    return;
  }

  const showCoffre = _histScope === 'all';
  const coffreMap = Object.fromEntries(_coffresData.map(c => [c.id, c.name]));
  const admin = isAdmin();
  const cols = 4 + (showCoffre ? 1 : 0) + (admin ? 1 : 0);

  const rows = items.map(item => {
    const rowId = `hist-${item.kind}-${item.id}`;
    const hasDetails = (item.details || []).length > 0;
    const isInv = item.kind === 'inventory';
    const toggle = hasDetails
      ? `<button type="button" class="btn btn-ghost btn-sm btn-toggle-hist" data-row="${rowId}" title="Voir les billets" aria-label="Voir le détail des billets">≡</button>`
      : '';

    let badge, amount, note;
    if (isInv) {
      badge = `<span class="badge badge-inventory">Inventaire</span>`;
      amount = `<td class="pos cf-td-amount">${fmtEur(item.total_amount)}</td>`;
      note = item.notes;
    } else {
      badge = item.transfer_ref
        ? `<span class="badge" style="background:rgba(249,168,37,.15);color:var(--accent-gold);border:1px solid rgba(249,168,37,.3)">⇄ Transfert</span>`
        : `<span class="badge badge-${item.type.toLowerCase()}">${item.type === 'ENTRY' ? 'Entrée' : 'Sortie'}</span>`;
      amount = `<td class="${item.type === 'ENTRY' ? 'pos' : 'neg'} cf-td-amount">${item.type === 'EXIT' ? '-' : '+'}${fmtEur(item.amount)}</td>`;
      note = item.description;
    }

    const actions = !admin ? '' : `<td class="cf-td-actions"><div class="cf-hist-actions">${toggle}${isInv
      ? `<button type="button" class="btn btn-ghost danger btn-sm btn-del-inv" data-id="${item.id}" title="Supprimer l'inventaire" aria-label="Supprimer l'inventaire">🗑</button>`
      : `<button type="button" class="btn btn-ghost btn-sm btn-edit-mvt" data-id="${item.id}" data-amount="${item.amount}" data-desc="${escHtml(item.description || '')}" title="Modifier" aria-label="Modifier le mouvement">✏</button>
         <button type="button" class="btn btn-ghost danger btn-sm btn-del-mvt" data-id="${item.id}" title="Supprimer" aria-label="Supprimer le mouvement">🗑</button>`
    }</div></td>`;

    return `
      <tr class="no-cursor cf-row" ${hasDetails ? `data-row="${rowId}" style="cursor:pointer"` : ''}>
        <td class="left cf-td-date">${fmtDateTime(item.created_at || item.date)}</td>
        ${showCoffre ? `<td class="left cf-td-coffre">${escHtml(coffreMap[item.coffre_id] || `#${item.coffre_id}`)}</td>` : ''}
        <td class="left cf-td-type">${badge}</td>
        ${amount}
        <td class="left cf-td-note">${escHtml(note || '—')}</td>
        ${actions}
      </tr>
      ${hasDetails ? `<tr id="${rowId}" class="expand-row" style="display:none"><td colspan="${cols}"><div class="expand-content open">${_renderBilletDetails(item.details)}</div></td></tr>` : ''}`;
  }).join('');

  const more = _histScope === 'coffre' && items.length < _histTotal
    ? `<div class="cf-hist-more"><button type="button" class="btn btn-secondary btn-sm btn-hist-more">Afficher plus (${_histTotal - items.length} restant${_histTotal - items.length > 1 ? 's' : ''})</button></div>`
    : _histScope === 'all' && _histTotal > items.length
      ? `<div class="cf-note cf-hist-hint">Les ${items.length} opérations les plus récentes. Choisissez « Ce coffre » pour tout parcourir.</div>`
      : '';

  body.innerHTML = `
    <table class="data-table cf-hist-table ${showCoffre ? 'with-coffre' : ''}">
      <thead><tr>
        <th class="left">Date</th>${showCoffre ? '<th class="left">Coffre</th>' : ''}
        <th class="left">Type</th><th>Montant</th><th class="left">Note</th>${admin ? '<th>Actions</th>' : ''}
      </tr></thead>
      <tbody>${rows}</tbody>
    </table>${more}`;

  // Délégation d'événements — évite tout inline JS avec données utilisateur.
  // Posée UNE fois par élément : un écouteur ajouté à chaque rendu s'empilerait.
  if (!body.dataset.delegated) {
    body.dataset.delegated = '1';
    body.addEventListener('click', _onHistoryClick);
  }
}

function _onHistoryClick(e) {
  // Un clic sur un bouton ne doit jamais déplier la ligne qui le contient.
  const btn = e.target.closest('button');
  if (btn) {
    if (btn.classList.contains('btn-toggle-hist')) {
      toggleHistRow(btn.dataset.row);
    } else if (btn.classList.contains('btn-edit-mvt')) {
      openEditMovementModal(parseInt(btn.dataset.id), parseFloat(btn.dataset.amount), btn.dataset.desc);
    } else if (btn.classList.contains('btn-del-mvt')) {
      deleteMovement(parseInt(btn.dataset.id));
    } else if (btn.classList.contains('btn-del-inv')) {
      deleteInventory(parseInt(btn.dataset.id));
    } else if (btn.classList.contains('btn-hist-more')) {
      btn.disabled = true;
      loadHistory(true);
    }
    return;
  }
  const row = e.target.closest('tr[data-row]');
  if (row) toggleHistRow(row.dataset.row);
}

function _renderBilletDetails(details) {
  if (!details.length) return '';
  const total = details.reduce((s, d) => s + d.denomination * d.quantity, 0);
  const rows = details
    .slice().sort((a, b) => b.denomination - a.denomination)
    .map(d => `
      <div style="display:flex;align-items:center;gap:12px;padding:4px 0">
        <span style="font-family:var(--font-display);font-size:13px;min-width:50px;color:var(--text-secondary)">${d.denomination} €</span>
        <span style="color:var(--text-muted);font-size:12px">×</span>
        <span style="font-family:var(--font-display);font-size:14px;font-weight:600;min-width:30px">${d.quantity}</span>
        <span style="color:var(--text-muted);font-size:12px">=</span>
        <span style="font-family:var(--font-display);font-size:13px;color:var(--accent-gold)">${fmtEur(d.denomination * d.quantity)}</span>
      </div>`).join('');
  return `
    <div style="padding:8px 16px">
      <div style="font-size:11px;font-weight:600;color:var(--text-secondary);text-transform:uppercase;letter-spacing:.08em;margin-bottom:8px">Détail des billets</div>
      ${rows}
      <div style="border-top:1px solid var(--border);margin-top:8px;padding-top:8px;display:flex;justify-content:flex-end">
        <span style="font-family:var(--font-display);font-size:13px;font-weight:600;color:var(--accent-gold)">${fmtEur(total)}</span>
      </div>
    </div>`;
}

function toggleHistRow(id) {
  const row = document.getElementById(id);
  if (!row) return;
  row.style.display = row.style.display === 'none' ? '' : 'none';
}

// ── Modification / suppression (requêtes d'origine) ───────

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

// ── Code d'accès du coffre ────────────────────────────────

let _revealTimer = null;

async function revealCombination(coffreId) {
  const valEl = document.getElementById(`combinationValue-${coffreId}`);
  const btnEl = document.getElementById(`revealBtn-${coffreId}`);
  const delEl = document.getElementById(`delComboBtn-${coffreId}`);
  if (!valEl) return;

  // Si déjà révélé → masquer
  if (btnEl && btnEl.dataset.revealed === '1') {
    valEl.textContent = '●●●●●●';
    valEl.style.color = 'var(--text-muted)';
    valEl.style.letterSpacing = '.3em';
    btnEl.dataset.revealed = '0';
    btnEl.title = 'Révéler le code';
    btnEl.textContent = 'Afficher';
    if (_revealTimer) clearTimeout(_revealTimer);
    return;
  }

  try {
    const data = await apiGet(`/api/coffres/${coffreId}/combination`);
    valEl.textContent = data.combination;
    valEl.style.color = 'var(--accent-gold)';
    valEl.style.letterSpacing = '.1em';
    if (btnEl) { btnEl.dataset.revealed = '1'; btnEl.title = 'Masquer le code'; btnEl.textContent = '🙈 Masquer'; }
    if (delEl) delEl.style.display = '';
    // Masquer automatiquement après 30s
    if (_revealTimer) clearTimeout(_revealTimer);
    _revealTimer = setTimeout(() => revealCombination(coffreId), 30_000);
  } catch (err) {
    if (err.message.includes('404') || err.message.includes('Aucun')) {
      valEl.textContent = 'Aucun code enregistré';
      valEl.style.color = 'var(--text-muted)';
      valEl.style.fontSize = '13px';
      valEl.style.letterSpacing = 'normal';
    } else {
      showToast(err.message, 'error');
    }
  }
}

function openSetCombinationModal(coffreId) {
  document.getElementById('combinationCoffreId').value = coffreId;
  document.getElementById('combinationInput').value = '';
  document.getElementById('combinationHint').value = '';
  openModal('combinationModal');
  setTimeout(() => document.getElementById('combinationInput').focus(), 100);
}

async function submitSetCombination(e) {
  e.preventDefault();
  const coffreId = document.getElementById('combinationCoffreId').value;
  const combination = document.getElementById('combinationInput').value.trim();
  const hint = document.getElementById('combinationHint').value.trim();
  if (!combination) return;
  try {
    await apiPut(`/api/coffres/${coffreId}/combination`, { combination, hint: hint || null });
    showToast('Code enregistré', 'success');
    closeModal('combinationModal');
    await loadCoffres();
  } catch (err) { showToast(err.message, 'error'); }
}

function deleteCombination(coffreId) {
  confirm('Supprimer le code', 'Supprimer le code d\'accès de ce coffre ?', async () => {
    try {
      await apiDelete(`/api/coffres/${coffreId}/combination`);
      showToast('Code supprimé', 'success');
      await loadCoffres();
    } catch (err) { showToast(err.message, 'error'); }
  });
}
