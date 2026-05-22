/* ═══════════════════════════════════════════════
   PORTFOLIO — Stock portfolio module
   ═══════════════════════════════════════════════ */
'use strict';

let _portfolioData = null;
let _expandedPositions = new Set();

async function loadPortfolio() {
  try {
    _portfolioData = await apiGet('/api/portfolio/summary');
    renderPortfolioPage(_portfolioData);
  } catch (err) {
    showToast('Erreur portefeuille: ' + err.message, 'error');
  }
}

function renderPortfolioPage(data) {
  const page = document.getElementById('page-portfolio');
  if (!page) return;

  const positions = data.positions || [];
  const held    = positions.filter(p => p.total_quantity > 0);
  const watched = positions.filter(p => p.total_quantity === 0);

  page.innerHTML = `
    <div style="display:flex;align-items:center;justify-content:space-between;margin-bottom:20px">
      <div>
        <div class="page-title">📈 Portefeuille boursier</div>
      </div>
      <div style="display:flex;gap:8px">
        <button class="btn btn-secondary btn-sm" onclick="openSaxoImportModal()">📥 SaxoBank</button>
        ${isAdmin() ? `<button class="btn btn-primary btn-sm" onclick="openAddPositionModal()">+ Position</button>` : ''}
      </div>
    </div>

    <!-- Hero cards -->
    <div class="hero-grid" style="margin-bottom:20px">
      <div class="hero-card">
        <div class="card-label">💼 Valeur totale</div>
        <div class="hero-card-value gold">${fmtEur(data.total_value_eur)}</div>
        <div class="hero-card-sub">Investi: ${fmtEur(data.total_invested_eur)}</div>
      </div>
      <div class="hero-card">
        <div class="card-label">📊 P&L Total</div>
        <div class="hero-card-value ${pnlClass(data.total_pnl_eur)}">${pnlSign(data.total_pnl_eur)}${fmtEur(data.total_pnl_eur)}</div>
        <div class="hero-card-sub ${pnlClass(data.total_pnl_pct)}">${pnlSign(data.total_pnl_pct)}${fmtPct(data.total_pnl_pct)}</div>
      </div>
      <div class="hero-card">
        <div class="card-label">📅 Variation jour</div>
        <div class="hero-card-value ${pnlClass(data.day_change_eur)}">${pnlSign(data.day_change_eur)}${fmtEur(data.day_change_eur)}</div>
        <div class="hero-card-sub ${pnlClass(data.day_change_pct)}">${pnlSign(data.day_change_pct)}${fmtPct(data.day_change_pct)}</div>
      </div>
      <div class="hero-card">
        <div class="card-label">📦 Positions</div>
        <div class="hero-card-value blue">${held.length}</div>
        <div class="hero-card-sub">${watched.length > 0 ? `${watched.length} suivi${watched.length > 1 ? 's' : ''} · ` : ''}${data.is_market_open ? '<span style="color:var(--accent-green)">● Marché ouvert</span>' : '<span style="color:var(--text-muted)">● Marché fermé</span>'}</div>
      </div>
    </div>

    <!-- Charts -->
    <div class="grid-chart" style="margin-bottom:20px">
      <div class="card">
        <div class="card-title">Allocation</div>
        <div style="height:220px;display:flex;align-items:center;justify-content:center"><canvas id="portDonut"></canvas></div>
        <div class="donut-legend" id="portDonutLegend"></div>
      </div>
      <div class="card">
        <div class="card-title">Évolution 30 jours</div>
        <div style="height:220px"><canvas id="portLine"></canvas></div>
      </div>
    </div>

    <!-- Held positions table -->
    <div class="card" style="padding:0;overflow:hidden;margin-bottom:20px">
      <div class="section-header">
        <div class="section-title">Positions détenues <span class="section-count">${held.length}</span></div>
      </div>
      <div class="table-wrap">
        <table class="data-table">
          <thead><tr>
            <th class="left" style="padding-left:24px">Actif</th>
            <th>Cours</th><th>Var. j.</th><th>Qté</th><th>PRU</th>
            <th>Investi</th><th>Valeur</th><th>P&L €</th><th>P&L %</th>
            <th>Alloc.</th><th>⚡</th><th>Actions</th>
          </tr></thead>
          <tbody id="positionsBody">${renderHeldRows(held)}</tbody>
        </table>
      </div>
    </div>

    <!-- Watched positions table -->
    <div class="card" style="padding:0;overflow:hidden">
      <div class="section-header">
        <div class="section-title">Suivis <span class="section-count">${watched.length}</span></div>
        ${isAdmin() ? `<button class="btn btn-ghost btn-sm" style="margin-right:12px" onclick="openAddPositionModal()">+ Ajouter</button>` : ''}
      </div>
      <div class="table-wrap">
        <table class="data-table">
          <thead><tr>
            <th class="left" style="padding-left:24px">Actif</th>
            <th>Cours</th><th>Var. j.</th><th>⚡</th><th>Actions</th>
          </tr></thead>
          <tbody id="watchedBody">${renderWatchedRows(watched)}</tbody>
        </table>
      </div>
    </div>`;

  // Charts (only held positions that have value)
  requestAnimationFrame(() => {
    const visiblePos = held.filter(p => p.current_value > 0);
    renderDonut('portDonut', visiblePos.map(p => p.display_name), visiblePos.map(p => p.current_value), 'portDonutLegend');
    loadPortfolioHistory();
  });

  // Re-expand
  _expandedPositions.forEach(id => {
    const el = document.getElementById(`expand-${id}`);
    if (el) el.classList.add('open');
  });
}

async function loadPortfolioHistory() {
  try {
    const history = await apiGet('/api/portfolio/history');
    renderPortfolioLine('portLine', history);
  } catch (_) {}
}

// ── Held positions (with purchases) ──────────────────────

function renderHeldRows(positions) {
  if (!positions.length) return `<tr><td colspan="12"><div class="empty-state"><div class="empty-icon">📊</div><div class="empty-text">Aucune position détenue</div>${isAdmin() ? `<button class="btn btn-primary btn-sm" style="margin-top:12px" onclick="openAddPositionModal()">+ Ajouter une position</button>` : ''}</div></td></tr>`;
  return positions.map(pos => buildPositionRow(pos)).join('');
}

function buildPositionRow(pos) {
  const isCash = pos.asset_type === 'cash';
  const hasPrice = pos.current_price_eur != null || pos.manual_price != null;
  const priceStr = isCash ? '—' : (hasPrice ? fmtNum(pos.current_price_eur ?? pos.manual_price) + ' €' : '—');
  const dayStr = (pos.asset_type === 'bond_manual' || isCash) ? '—' : (pos.day_change_pct != null
    ? `<span class="${pnlClass(pos.day_change_eur)}">${pnlSign(pos.day_change_eur)}${fmtPct(pos.day_change_pct)}</span>` : '—');
  const pnlEurStr = isCash ? '—' : `<span class="${pnlClass(pos.pnl_eur)}">${pnlSign(pos.pnl_eur)}${fmtEur(pos.pnl_eur)}</span>`;
  const pnlPctStr = (isCash || pos.pnl_pct == null) ? '—'
    : `<span class="${pnlClass(pos.pnl_pct)}">${pnlSign(pos.pnl_pct)}${fmtPct(pos.pnl_pct)}</span>`;
  const alertDot = (pos.alert_gain_pct || pos.alert_loss_pct)
    ? `<span class="alert-dot" title="+${pos.alert_gain_pct ?? '—'}% / -${pos.alert_loss_pct ?? '—'}%"></span>` : '—';
  const adminActions = isAdmin() ? `
    ${pos.asset_type === 'bond_manual' ? `<button class="btn btn-ghost primary" onclick="openManualPriceModal(${pos.id})">📝</button>` : ''}
    ${!isCash ? `<button class="btn btn-ghost" onclick="openAlertModal(${pos.id})" title="Alertes">⚡</button>` : ''}
    ${!isCash ? `<button class="btn btn-ghost primary" onclick="openAddPurchaseModal(${pos.id})">+ Achat</button>` : ''}
    <button class="btn btn-ghost" onclick="openEditPositionModal(${pos.id})" title="Modifier">✏️</button>
    <button class="btn btn-ghost danger" onclick="archivePosition(${pos.id},'${escHtml(pos.display_name).replace(/'/g,"\\'")}')">🗑</button>` : '';

  return `
    <tr class="position-row" onclick="togglePositionExpand(${pos.id})" id="pos-row-${pos.id}">
      <td class="left" style="padding-left:24px">
        <div class="asset-name-cell">
          <div class="pos-icon ${pos.asset_type}">${ASSET_TYPE_ICONS[pos.asset_type] ?? '?'}</div>
          <div>
            <div class="asset-name">${escHtml(pos.display_name)} <span style="color:var(--text-muted);font-size:10px">${_expandedPositions.has(pos.id) ? '▴' : '▾'}</span></div>
            <div class="asset-sub">${escHtml(pos.ticker)} <span class="badge badge-${pos.asset_type}" style="margin-left:4px">${ASSET_TYPE_LABELS[pos.asset_type] ?? pos.asset_type}</span>${pos.currency !== 'EUR' ? ` <span style="font-size:10px;color:var(--text-muted)">${pos.currency}</span>` : ''}</div>
          </div>
        </div>
      </td>
      <td>${priceStr}</td>
      <td>${dayStr}</td>
      <td>${isCash ? '—' : fmtNum(pos.total_quantity, 4)}</td>
      <td>${isCash ? '—' : (pos.average_cost != null ? fmtNum(pos.average_cost) + ' €' : '—')}</td>
      <td>${isCash ? '—' : fmtEur(pos.total_invested)}</td>
      <td><strong>${fmtEur(pos.current_value)}</strong></td>
      <td>${pnlEurStr}</td>
      <td>${pnlPctStr}</td>
      <td style="font-family:var(--font-display);font-size:12px">${(pos.allocation_pct ?? 0).toFixed(1)}%</td>
      <td>${alertDot}</td>
      <td><div style="display:flex;justify-content:flex-end;gap:4px" onclick="event.stopPropagation()">${adminActions}</div></td>
    </tr>
    <tr class="expand-row">
      <td colspan="12">
        <div class="expand-content ${_expandedPositions.has(pos.id) ? 'open' : ''}" id="expand-${pos.id}">
          ${buildDCAContent(pos)}
        </div>
      </td>
    </tr>`;
}

// ── Watched positions (no purchases) ─────────────────────

function renderWatchedRows(positions) {
  if (!positions.length) return `<tr><td colspan="5"><div class="empty-state"><div class="empty-icon">👁</div><div class="empty-text">Aucun titre suivi</div>${isAdmin() ? `<button class="btn btn-primary btn-sm" style="margin-top:12px" onclick="openAddPositionModal()">+ Ajouter un suivi</button>` : ''}</div></td></tr>`;
  return positions.map(pos => buildWatchedRow(pos)).join('');
}

function buildWatchedRow(pos) {
  const hasPrice = pos.current_price_eur != null || pos.manual_price != null;
  const priceStr = hasPrice ? fmtNum(pos.current_price_eur ?? pos.manual_price) + ' €' : '—';
  const dayStr = pos.day_change_pct != null
    ? `<span class="${pnlClass(pos.day_change_pct)}">${pnlSign(pos.day_change_pct)}${fmtPct(pos.day_change_pct)}</span>` : '—';
  const alertDot = (pos.alert_gain_pct || pos.alert_loss_pct)
    ? `<span class="alert-dot" title="+${pos.alert_gain_pct ?? '—'}% / -${pos.alert_loss_pct ?? '—'}%"></span>` : '—';
  const adminActions = isAdmin() ? `
    <button class="btn btn-ghost" onclick="openAlertModal(${pos.id})" title="Alertes">⚡</button>
    <button class="btn btn-ghost primary" onclick="openAddPurchaseModal(${pos.id})" title="Acheter">💰 Acheter</button>
    <button class="btn btn-ghost" onclick="openEditPositionModal(${pos.id})" title="Modifier">✏️</button>
    <button class="btn btn-ghost danger" onclick="archivePosition(${pos.id},'${escHtml(pos.display_name).replace(/'/g,"\\'")}')">🗑</button>` : '';

  return `
    <tr id="pos-row-${pos.id}">
      <td class="left" style="padding-left:24px">
        <div class="asset-name-cell">
          <div class="pos-icon ${pos.asset_type}">${ASSET_TYPE_ICONS[pos.asset_type] ?? '?'}</div>
          <div>
            <div class="asset-name">${escHtml(pos.display_name)}</div>
            <div class="asset-sub">${escHtml(pos.ticker)} <span class="badge badge-${pos.asset_type}" style="margin-left:4px">${ASSET_TYPE_LABELS[pos.asset_type] ?? pos.asset_type}</span>${pos.currency !== 'EUR' ? ` <span style="font-size:10px;color:var(--text-muted)">${pos.currency}</span>` : ''}</div>
          </div>
        </div>
      </td>
      <td>${priceStr}</td>
      <td>${dayStr}</td>
      <td>${alertDot}</td>
      <td><div style="display:flex;justify-content:flex-end;gap:4px">${adminActions}</div></td>
    </tr>`;
}

function buildDCAContent(pos) {
  const prm = pos.average_cost != null ? fmtNum(pos.average_cost) + ' €' : '—';
  const purchases = pos.purchases || [];
  const addBtn = isAdmin() ? `<button class="btn btn-secondary btn-sm" onclick="openAddPurchaseModal(${pos.id})">+ Ajouter un achat</button>` : '';
  const tableRows = !purchases.length
    ? `<tr><td colspan="6" class="empty-state" style="padding:16px;text-align:center">Aucun achat — ${isAdmin() ? `<a href="#" onclick="event.preventDefault();openAddPurchaseModal(${pos.id})">Ajouter</a>` : 'pas d\'achat'}</td></tr>`
    : purchases.map(p => `
        <tr>
          <td class="left">${fmtDate(p.purchase_date)}</td>
          <td>${fmtNum(p.quantity, 4)}</td>
          <td>${fmtNum(p.unit_price)} €</td>
          <td>${fmtNum(p.fees)} €</td>
          <td class="left" style="font-family:var(--font-body);color:var(--text-secondary);max-width:200px;overflow:hidden;text-overflow:ellipsis">${escHtml(p.note || '—')}</td>
          <td>${isAdmin() ? `<div style="display:flex;justify-content:flex-end;gap:4px">
            <button class="btn btn-ghost" onclick="openEditPurchaseModal(${pos.id},${p.id})">✏️</button>
            <button class="btn btn-ghost danger" onclick="deletePurchaseConfirm(${pos.id},${p.id})">🗑</button>
          </div>` : ''}</td>
        </tr>`).join('');

  // Section ventes
  const sales = pos.sales || [];
  const salesSection = sales.length ? `
    <div style="margin-top:16px;border-top:1px solid var(--border);padding-top:12px">
      <div style="font-size:11px;font-weight:500;color:var(--text-secondary);text-transform:uppercase;letter-spacing:.08em;margin-bottom:8px">Ventes</div>
      <table class="data-table" style="font-size:12px">
        <thead><tr><th class="left">Date</th><th>Qté vendue</th><th>Prix vente</th><th>Frais</th><th>P&amp;L réalisé</th></tr></thead>
        <tbody>${sales.map(s => `
          <tr>
            <td class="left">${fmtDate(s.sale_date)}</td>
            <td>${fmtNum(s.quantity, 4)}</td>
            <td>${fmtNum(s.unit_price)} €</td>
            <td>${fmtNum(s.fees)} €</td>
            <td class="${s.realized_pnl >= 0 ? 'positive' : 'negative'}">${s.realized_pnl != null ? (s.realized_pnl >= 0 ? '+' : '') + fmtNum(s.realized_pnl) + ' €' : '—'}</td>
          </tr>`).join('')}
        </tbody>
      </table>
    </div>` : '';

  return `
    <div style="display:flex;align-items:center;justify-content:space-between;margin-bottom:12px">
      <span style="font-size:11px;font-weight:500;color:var(--text-secondary);text-transform:uppercase;letter-spacing:.08em">Achats DCA — ${escHtml(pos.display_name)}</span>
      <span style="font-family:var(--font-display);font-size:12px;color:var(--text-secondary)">PRU: <span style="color:var(--accent-gold)">${prm}</span> · Qté: <span style="color:var(--text-primary)">${fmtNum(pos.total_quantity, 4)}</span></span>
    </div>
    <table class="data-table" style="font-size:12px">
      <thead><tr><th class="left">Date</th><th>Qté</th><th>Prix</th><th>Frais</th><th class="left">Note</th><th>Actions</th></tr></thead>
      <tbody>${tableRows}</tbody>
    </table>
    <div style="margin-top:10px">${addBtn}</div>
    ${salesSection}`;
}

function togglePositionExpand(posId) {
  const el = document.getElementById(`expand-${posId}`);
  if (!el) return;
  if (_expandedPositions.has(posId)) {
    _expandedPositions.delete(posId);
    el.classList.remove('open');
  } else {
    _expandedPositions.add(posId);
    el.classList.add('open');
  }
}

// ── Position modals ───────────────────────────────────────

function openAddPositionModal() {
  _posModalMode = 'add';
  _posModalId = null;
  setInner('posModalTitle', 'Ajouter une position');
  setInner('posModalBtn', 'Créer');
  setVal('posName', ''); setVal('posTicker', ''); setVal('posType', 'action');
  setVal('posCurrency', 'EUR'); setVal('posAlertGain', ''); setVal('posAlertLoss', '');
  openModal('positionModal');
}

function openEditPositionModal(posId) {
  const pos = _portfolioData?.positions?.find(p => p.id === posId);
  if (!pos) return;
  _posModalMode = 'edit';
  _posModalId = posId;
  setInner('posModalTitle', 'Modifier la position');
  setInner('posModalBtn', 'Enregistrer');
  setVal('posName', pos.display_name); setVal('posTicker', pos.ticker);
  setVal('posType', pos.asset_type); setVal('posCurrency', pos.currency);
  setVal('posAlertGain', pos.alert_gain_pct ?? ''); setVal('posAlertLoss', pos.alert_loss_pct ?? '');
  openModal('positionModal');
}

async function submitPositionModal(e) {
  e.preventDefault();
  const body = {
    display_name: getVal('posName'), ticker: getVal('posTicker').toUpperCase(),
    asset_type: getVal('posType'), currency: getVal('posCurrency'),
    alert_gain_pct: floatOrNull(getVal('posAlertGain')),
    alert_loss_pct: floatOrNull(getVal('posAlertLoss')),
  };
  try {
    if (_posModalMode === 'edit') {
      await apiPut(`/api/portfolio/positions/${_posModalId}`, body);
      showToast('Position mise à jour', 'success');
    } else {
      await apiPost('/api/portfolio/positions', body);
      showToast('Position créée', 'success');
    }
    closeModal('positionModal');
    await loadPortfolio();
  } catch (err) { showToast(err.message, 'error'); }
}

async function archivePosition(posId, name) {
  confirm('Archiver la position', `Archiver "${name}" ?`, async () => {
    try {
      await apiDelete(`/api/portfolio/positions/${posId}`);
      showToast('Position archivée', 'success');
      await loadPortfolio();
    } catch (err) { showToast(err.message, 'error'); }
  });
}

// ── Purchase modals ───────────────────────────────────────

let _purchaseModalPosId = null;
let _purchaseModalId = null;

function openAddPurchaseModal(posId) {
  _purchaseModalPosId = posId;
  _purchaseModalId = null;
  setInner('purchaseModalTitle', 'Ajouter un achat');
  setInner('purchaseModalBtn', 'Enregistrer');
  setVal('purchaseDate', todayISO()); setVal('purchaseQty', '');
  setVal('purchasePrice', ''); setVal('purchaseFees', '0'); setVal('purchaseNote', '');
  openModal('purchaseModal');
}

async function openEditPurchaseModal(posId, purchaseId) {
  const pos = _portfolioData?.positions?.find(p => p.id === posId);
  const purchase = pos?.purchases?.find(p => p.id === purchaseId);
  if (!purchase) return;
  _purchaseModalPosId = posId;
  _purchaseModalId = purchaseId;
  setInner('purchaseModalTitle', 'Modifier l\'achat');
  setInner('purchaseModalBtn', 'Enregistrer');
  setVal('purchaseDate', purchase.purchase_date);
  setVal('purchaseQty', purchase.quantity);
  setVal('purchasePrice', purchase.unit_price);
  setVal('purchaseFees', purchase.fees);
  setVal('purchaseNote', purchase.note || '');
  openModal('purchaseModal');
}

async function submitPurchaseModal(e) {
  e.preventDefault();
  const body = {
    purchase_date: getVal('purchaseDate'), quantity: parseFloat(getVal('purchaseQty')),
    unit_price: parseFloat(getVal('purchasePrice')), fees: parseFloat(getVal('purchaseFees') || 0),
    note: getVal('purchaseNote') || null,
  };
  try {
    if (_purchaseModalId) {
      await apiPut(`/api/portfolio/positions/${_purchaseModalPosId}/purchases/${_purchaseModalId}`, body);
      showToast('Achat modifié', 'success');
    } else {
      await apiPost(`/api/portfolio/positions/${_purchaseModalPosId}/purchases`, body);
      showToast('Achat enregistré', 'success');
    }
    closeModal('purchaseModal');
    await loadPortfolio();
  } catch (err) { showToast(err.message, 'error'); }
}

function deletePurchaseConfirm(posId, purchaseId) {
  confirm('Supprimer l\'achat', 'Supprimer cet achat ?', async () => {
    try {
      await apiDelete(`/api/portfolio/positions/${posId}/purchases/${purchaseId}`);
      showToast('Achat supprimé', 'success');
      await loadPortfolio();
    } catch (err) { showToast(err.message, 'error'); }
  });
}

// ── Manual price ──────────────────────────────────────────

function openManualPriceModal(posId) {
  const pos = _portfolioData?.positions?.find(p => p.id === posId);
  if (!pos) return;
  setInner('manualPriceTitle', `Cours manuel — ${pos.display_name}`);
  setVal('manualPriceValue', pos.manual_price ?? '');
  document.getElementById('manualPricePosId').value = posId;
  openModal('manualPriceModal');
}

async function submitManualPrice(e) {
  e.preventDefault();
  const posId = document.getElementById('manualPricePosId').value;
  try {
    await apiPost(`/api/portfolio/positions/${posId}/manual-price`, { price: parseFloat(getVal('manualPriceValue')) });
    showToast('Cours mis à jour', 'success');
    closeModal('manualPriceModal');
    await loadPortfolio();
  } catch (err) { showToast(err.message, 'error'); }
}

// ── Alert modal ───────────────────────────────────────────

function openAlertModal(posId) {
  const pos = _portfolioData?.positions?.find(p => p.id === posId);
  if (!pos) return;
  setInner('alertModalTitle', `Alertes — ${pos.display_name}`);
  document.getElementById('alertPosId').value = posId;
  setVal('alertGain', pos.alert_gain_pct ?? '');
  setVal('alertLoss', pos.alert_loss_pct ?? '');
  openModal('alertModal');
}

async function submitAlertModal(e) {
  e.preventDefault();
  const posId = document.getElementById('alertPosId').value;
  const pos = _portfolioData?.positions?.find(p => p.id == posId);
  if (!pos) return;
  try {
    await apiPut(`/api/portfolio/positions/${posId}`, {
      ...pos,
      alert_gain_pct: floatOrNull(getVal('alertGain')),
      alert_loss_pct: floatOrNull(getVal('alertLoss')),
    });
    showToast('Alertes enregistrées', 'success');
    closeModal('alertModal');
    await loadPortfolio();
  } catch (err) { showToast(err.message, 'error'); }
}

// ── SaxoBank import ───────────────────────────────────────

function openSaxoImportModal() {
  document.getElementById('saxoImportForm').reset();
  const res = document.getElementById('saxoImportResult');
  res.style.display = 'none';
  res.textContent = '';
  document.getElementById('saxoImportBtn').disabled = false;
  document.getElementById('saxoImportBtn').textContent = '📥 Importer';
  openModal('saxoImportModal');
}

async function submitSaxoImport(e) {
  e.preventDefault();
  const file = document.getElementById('saxoImportFile').files[0];
  if (!file) return;
  const btn = document.getElementById('saxoImportBtn');
  btn.disabled = true;
  btn.textContent = '⏳ Import en cours…';
  const res = document.getElementById('saxoImportResult');
  res.style.display = 'none';

  const fd = new FormData();
  fd.append('file', file);
  try {
    const data = await apiFetch('/api/saxo/import', { method: 'POST', body: fd });
    const { created_positions, created_purchases, skipped_purchases, total_transactions, cash_balance_eur } = data;
    res.style.display = 'block';
    res.style.background = 'rgba(0,214,143,0.08)';
    res.style.border = '1px solid rgba(0,214,143,0.3)';
    res.style.color = 'var(--accent-green)';
    res.innerHTML = `✅ Import terminé<br/>
      <span style="color:var(--text-secondary)">
        ${created_positions} position${created_positions !== 1 ? 's' : ''} créée${created_positions !== 1 ? 's' : ''} ·
        ${created_purchases} achat${created_purchases !== 1 ? 's' : ''} importé${created_purchases !== 1 ? 's' : ''} ·
        ${skipped_purchases} doublon${skipped_purchases !== 1 ? 's' : ''} ignoré${skipped_purchases !== 1 ? 's' : ''}
        ${cash_balance_eur != null ? ` · 💶 Liquidités : ${fmtEur(cash_balance_eur)}` : ''}
      </span>`;
    btn.textContent = '✓ Terminé';
    await loadPortfolio();
  } catch (err) {
    res.style.display = 'block';
    res.style.background = 'rgba(255,71,87,0.08)';
    res.style.border = '1px solid rgba(255,71,87,0.3)';
    res.style.color = 'var(--accent-red)';
    res.textContent = '❌ ' + err.message;
    btn.disabled = false;
    btn.textContent = '📥 Importer';
  }
}

// ── Helpers ───────────────────────────────────────────────

let _posModalMode = 'add';
let _posModalId = null;

function getVal(id) { return document.getElementById(id)?.value ?? ''; }
function setVal(id, v) { const el = document.getElementById(id); if (el) el.value = v; }
function setInner(id, v) { const el = document.getElementById(id); if (el) el.textContent = v; }
function floatOrNull(v) { const f = parseFloat(v); return isNaN(f) ? null : f; }
