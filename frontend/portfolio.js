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
  _simInitialized = false;   // le DOM du simulateur est recréé à chaque rendu

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
        <button class="btn btn-secondary btn-sm" onclick="openRevolutImportModal()">📥 Revolut</button>
        ${isAdmin() ? `<button class="btn btn-primary btn-sm" onclick="openAddPositionModal()">+ Position</button>` : ''}
      </div>
    </div>

    <!-- Hero cards -->
    <div class="hero-grid" style="margin-bottom:20px">
      <div class="hero-card">
        <div class="card-label">💼 Valeur totale <span data-tip="Valeur de marché actuelle de toutes les positions (ETF, actions, liquidités SaxoBank)" style="opacity:.6;font-size:11px">ⓘ</span></div>
        <div class="hero-card-value gold">${fmtEur(data.total_value_eur)}</div>
        <div class="hero-card-sub" data-tip="Capital engagé résiduel : coût des parts encore détenues, hors liquidités">Investi: ${fmtEur(data.total_invested_eur)}</div>
      </div>
      <div class="hero-card">
        <div class="card-label">📊 P&L Total <span data-tip="Gain/perte total depuis l'achat sur toutes les positions actives (unrealized + realized sur ventes partielles), hors liquidités" style="opacity:.6;font-size:11px">ⓘ</span></div>
        <div class="hero-card-value ${pnlClass(data.total_pnl_eur)}">${pnlSign(data.total_pnl_eur)}${fmtEur(data.total_pnl_eur)}</div>
        <div class="hero-card-sub ${pnlClass(data.total_pnl_pct)}">${pnlSign(data.total_pnl_pct)}${fmtPct(data.total_pnl_pct)}</div>
      </div>
      <div class="hero-card">
        <div class="card-label">📅 Variation jour <span data-tip="Variation de valeur depuis la clôture d'hier, sur les positions cotées en bourse" style="opacity:.6;font-size:11px">ⓘ</span></div>
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

    <!-- Investissement & gains réels -->
    <div class="card" style="margin-bottom:20px">
      <div class="card-title" style="display:flex;align-items:center;justify-content:space-between;gap:12px;flex-wrap:wrap">
        <span>💰 Investissement & gains réels
          <span style="font-size:11px;color:var(--text-secondary);font-weight:400;margin-left:6px">— capital investi et valeur du portefeuille dans le temps</span>
        </span>
        <div id="igPeriodSel" class="seg-ctrl">
          <button class="seg-btn" onclick="setInvestGainPeriod('day',this)">Jour</button>
          <button class="seg-btn" onclick="setInvestGainPeriod('week',this)">Sem.</button>
          <button class="seg-btn active" onclick="setInvestGainPeriod('month',this)">Mois</button>
          <button class="seg-btn" onclick="setInvestGainPeriod('ytd',this)">YTD</button>
          <button class="seg-btn" onclick="setInvestGainPeriod('year',this)">1 an</button>
          <button class="seg-btn" onclick="setInvestGainPeriod('max',this)">Max</button>
        </div>
      </div>
      <div style="height:260px"><canvas id="investGainLine"></canvas></div>
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
            <th data-tip="Dernier cours coté">Cours</th>
            <th data-tip="Variation du cours depuis la clôture d'hier">Var. j.</th>
            <th data-tip="Nombre de parts détenues (achats − ventes)">Qté</th>
            <th data-tip="Prix de Revient Unitaire : coût moyen pondéré par part, frais inclus">PRU</th>
            <th data-tip="Capital engagé résiduel : coût des parts encore détenues (PRU × quantité)">Investi</th>
            <th data-tip="Valeur de marché actuelle (cours × quantité)">Valeur</th>
            <th data-tip="Gain/perte en € depuis l'achat (unrealized + realized sur ventes partielles)">P&L €</th>
            <th data-tip="Gain/perte % depuis l'achat, calculé sur le capital total investi dans cette position">P&L %</th>
            <th data-tip="Part de cet actif dans la valeur totale du portefeuille (hors liquidités)">Alloc.</th>
            <th>⚡</th><th>Actions</th>
          </tr></thead>
          <tbody id="positionsBody">${renderHeldRows(held)}</tbody>
        </table>
      </div>
    </div>

    <!-- Watched positions table -->
    <div class="card" style="padding:0;overflow:hidden;margin-bottom:20px">
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
    </div>

    <!-- ── Simulateur de rendement ── -->
    <div class="card" style="margin-bottom:20px">
      <div class="card-title" style="margin-bottom:16px;display:flex;align-items:center;justify-content:space-between;gap:12px">
        <span>📈 Simulateur de rendement
          <span style="font-size:11px;color:var(--text-secondary);font-weight:400;margin-left:6px">— projection basée sur le CAGR historique (yfinance)</span>
        </span>
        <label class="ui-switch" title="Plier / déplier le simulateur">
          <input type="checkbox" id="simToggle" onchange="_toggleSimulator(this.checked)">
          <span class="ui-switch-track"></span>
          <span class="ui-switch-thumb"></span>
        </label>
      </div>
      <div id="simBody" class="collapsible" style="display:grid;grid-template-columns:240px 1fr;gap:28px;align-items:start">

        <!-- Panneau gauche -->
        <div style="display:flex;flex-direction:column;gap:12px">
          <div>
            <div style="font-size:11px;font-weight:600;color:var(--text-secondary);text-transform:uppercase;letter-spacing:.06em;margin-bottom:6px">Actifs à simuler</div>
            <div id="simAssetList" style="border:1px solid var(--border);border-radius:6px;padding:6px 8px;max-height:180px;overflow-y:auto">
              ${positions.filter(p => p.asset_type !== 'cash' && p.ticker && p.ticker !== 'MANUAL').map(p => {
                const typeLabel = (typeof ASSET_TYPE_LABELS !== 'undefined' && ASSET_TYPE_LABELS[p.asset_type]) || p.asset_type;
                const checked = p.total_quantity > 0 ? 'checked' : '';
                return `<label style="display:flex;align-items:center;gap:8px;padding:5px 2px;cursor:pointer;font-size:13px">
                  <input type="checkbox" value="${escHtml(p.ticker)}" ${checked}
                    data-name="${escHtml(p.display_name)}"
                    data-type="${escHtml(p.asset_type)}"
                    data-invested="${p.total_invested || 0}"
                    onchange="_onSimAssetChange()"
                    style="accent-color:var(--accent);flex-shrink:0">
                  <span style="flex:1;min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap">${escHtml(p.display_name)}</span>
                  <span style="font-size:10px;color:var(--text-secondary);flex-shrink:0">${escHtml(typeLabel)}</span>
                </label>`;
              }).join('')}
            </div>
          </div>
          <div>
            <label class="form-label">Capital initial (€)</label>
            <input id="simCapital" type="number" class="form-input" min="0" step="100" value="0" oninput="_updateSim()">
          </div>
          <div>
            <label class="form-label">DCA mensuel (€) <span style="color:var(--text-secondary);font-weight:400">— optionnel</span></label>
            <input id="simDCA" type="number" class="form-input" min="0" step="50" value="0" oninput="_updateSim()">
          </div>
          <div>
            <label class="form-label">Durée : <strong id="simYearsLabel">20</strong> ans</label>
            <input id="simYears" type="range" min="1" max="40" value="20"
              style="width:100%;accent-color:var(--accent);margin-top:4px"
              oninput="document.getElementById('simYearsLabel').textContent=this.value;_updateSim()">
            <div style="display:flex;justify-content:space-between;font-size:10px;color:var(--text-secondary)"><span>1</span><span>40 ans</span></div>
          </div>
          <div>
            <label class="form-label">Taux annuel (%) <span id="simRateInfo" style="color:var(--text-secondary);font-weight:400;font-size:11px"></span></label>
            <input id="simRate" type="number" class="form-input" min="-20" max="50" step="0.1" value="8" oninput="_updateSim()">
            <div id="simRateWarn" style="display:none;margin-top:4px;font-size:11px;color:#F59E0B;line-height:1.4">
              ⚠ Taux basé sur les 10 dernières années (performance exceptionnelle). Moyenne historique long terme MSCI World : 7–9 %/an.
            </div>
          </div>
          <div id="simDivGroup" style="display:none">
            <label class="form-label">Rendement dividende (%/an)</label>
            <input id="simDiv" type="number" class="form-input" min="0" max="20" step="0.1" value="0" oninput="_updateSim()">
          </div>
          <div id="simDataInfo" style="font-size:11px;color:var(--text-secondary);line-height:1.4"></div>
        </div>

        <!-- Panneau droit -->
        <div>
          <div id="simKpis" style="display:grid;grid-template-columns:repeat(3,1fr);gap:10px;margin-bottom:16px">
            <div style="background:var(--bg-tertiary);border-radius:6px;padding:12px;color:var(--text-secondary);font-size:12px;grid-column:1/-1;text-align:center">
              Chargement des données historiques…
            </div>
          </div>
          <div style="height:220px;margin-bottom:16px"><canvas id="simChart"></canvas></div>
          <div id="simTable"></div>
        </div>
      </div>
    </div>`;

  // Initialisation après rendu DOM
  requestAnimationFrame(() => {
    const visiblePos = held.filter(p => p.current_value > 0);
    renderDonut('portDonut', visiblePos.map(p => p.display_name), visiblePos.map(p => p.current_value), 'portDonutLegend');
    loadPortfolioHistory();
    _restoreSimToggle();   // applique l'état plié/déplié mémorisé (+ init si déplié)
  });

  // Re-expand
  _expandedPositions.forEach(id => {
    const el = document.getElementById(`expand-${id}`);
    if (el) el.classList.add('open');
  });
}

function refreshPortfolioValues(data) {
  // Mise à jour légère des KPI heroes sans re-rendre toute la page
  // Appelée par l'auto-refresh toutes les 30s pour ne pas écraser le simulateur
  _portfolioData = data;
  const q = id => document.querySelector(`#page-portfolio ${id}`);

  const vEl = q('.hero-card-value.gold');
  if (vEl) vEl.textContent = fmtEur(data.total_value_eur);

  // Mettre à jour le tbody des positions détenues et suivies
  const held    = (data.positions || []).filter(p => p.total_quantity > 0);
  const watched = (data.positions || []).filter(p => p.total_quantity === 0);
  const pb = document.getElementById('positionsBody');
  const wb = document.getElementById('watchedBody');
  if (pb) pb.innerHTML = renderHeldRows(held);
  if (wb) wb.innerHTML = renderWatchedRows(watched);

  // Re-expand les lignes qui étaient ouvertes
  _expandedPositions.forEach(id => {
    const el = document.getElementById(`expand-${id}`);
    if (el) el.classList.add('open');
  });
}

let _investGainPeriod = 'month';

async function loadPortfolioHistory() {
  try {
    const history = await apiGet('/api/portfolio/history?period=month');
    renderPortfolioLine('portLine', history);          // « Évolution 30 jours »
    renderInvestGainChart('investGainLine', history);  // période par défaut : mois
  } catch (_) {}
}

// Sélecteur d'échelle de temps du graphique investissement/gains
async function setInvestGainPeriod(period, btn) {
  _investGainPeriod = period;
  document.querySelectorAll('#igPeriodSel .seg-btn')
    .forEach(b => b.classList.toggle('active', b === btn));
  try {
    const history = await apiGet('/api/portfolio/history?period=' + encodeURIComponent(period));
    renderInvestGainChart('investGainLine', history);
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

// ── Revolut import ────────────────────────────────────────

function openRevolutImportModal() {
  document.getElementById('revolutImportForm').reset();
  const res = document.getElementById('revolutImportResult');
  res.style.display = 'none';
  res.textContent = '';
  document.getElementById('revolutImportBtn').disabled = false;
  document.getElementById('revolutImportBtn').textContent = '📥 Importer';
  openModal('revolutImportModal');
}

async function submitRevolutImport(e) {
  e.preventDefault();
  const file = document.getElementById('revolutImportFile').files[0];
  if (!file) return;
  const btn = document.getElementById('revolutImportBtn');
  btn.disabled = true;
  btn.textContent = '⏳ Import en cours…';
  const res = document.getElementById('revolutImportResult');
  res.style.display = 'none';

  const fd = new FormData();
  fd.append('file', file);
  try {
    const data = await apiFetch('/api/revolut/import', { method: 'POST', body: fd });
    const { created_positions, created_purchases, created_sales, skipped_purchases, skipped_sales, fuzzy_duplicates, cash_balance_eur, unknown_tickers } = data;
    const skipped = skipped_purchases + skipped_sales + fuzzy_duplicates;
    const unknownWarn = unknown_tickers?.length
      ? `<div style="margin-top:8px;padding:8px;background:rgba(245,158,11,.1);border:1px solid rgba(245,158,11,.3);border-radius:6px;color:#F59E0B;font-size:12px">
          ⚠ Tickers sans mapping yfinance (cours non mis à jour) : <strong>${unknown_tickers.join(', ')}</strong><br/>
          <span style="color:var(--text-secondary)">Contacte le support pour les ajouter au mapping.</span>
         </div>` : '';
    res.style.display = 'block';
    res.style.background = 'rgba(0,214,143,0.08)';
    res.style.border = '1px solid rgba(0,214,143,0.3)';
    res.style.color = 'var(--accent-green)';
    res.innerHTML = `✅ Import terminé<br/>
      <span style="color:var(--text-secondary)">
        ${created_positions} position${created_positions !== 1 ? 's' : ''} créée${created_positions !== 1 ? 's' : ''} ·
        ${created_purchases} achat${created_purchases !== 1 ? 's' : ''} ·
        ${created_sales} vente${created_sales !== 1 ? 's' : ''} ·
        ${skipped} doublon${skipped !== 1 ? 's' : ''} ignoré${skipped !== 1 ? 's' : ''}
        ${cash_balance_eur != null ? ` · 💶 Liquidités : ${fmtEur(cash_balance_eur)}` : ''}
      </span>${unknownWarn}`;
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

// ── Simulateur de rendement ───────────────────────────────

let _simRates     = {};   // {ticker: {cagr, dividend_yield, years_of_data}}
let _simChartInst = null;

// Pli/dépli du simulateur — état persistant (plié par défaut)
// Init paresseux : les données yfinance ne sont chargées qu'au premier dépli.
let _simInitialized = false;

function _restoreSimToggle() {
  const expanded = localStorage.getItem('simExpanded') === 'true';
  const toggle = document.getElementById('simToggle');
  const body   = document.getElementById('simBody');
  if (toggle) toggle.checked = expanded;
  if (body)   body.classList.toggle('collapsed', !expanded);
  if (expanded && !_simInitialized) { _simInitialized = true; _initSimulator(); }
}

function _toggleSimulator(expanded) {
  const body = document.getElementById('simBody');
  if (body) body.classList.toggle('collapsed', !expanded);
  localStorage.setItem('simExpanded', expanded ? 'true' : 'false');
  if (expanded && !_simInitialized) { _simInitialized = true; _initSimulator(); }
}

async function _initSimulator() {
  // Déclenche _onSimAssetChange pour les cases pré-cochées (positions détenues)
  const checked = [...document.querySelectorAll('#simAssetList input:checked')];
  if (checked.length) await _onSimAssetChange();
}

async function _onSimAssetChange() {
  const checked = [...document.querySelectorAll('#simAssetList input:checked')];
  if (!checked.length) {
    document.getElementById('simKpis').innerHTML = `<div style="background:var(--bg2);border:1px solid var(--border);border-radius:6px;padding:14px;color:var(--text-secondary);font-size:12px;text-align:center;grid-column:1/-1">Sélectionnez un ou plusieurs actifs pour lancer la simulation</div>`;
    document.getElementById('simTable').innerHTML = '';
    document.getElementById('simDataInfo').textContent = '';
    if (_simChartInst) { _simChartInst.destroy(); _simChartInst = null; }
    return;
  }

  // Recalculer le capital initial en fonction des actifs sélectionnés
  const capInput = document.getElementById('simCapital');
  const totalInvested = checked.reduce((s, cb) => s + parseFloat(cb.dataset.invested || 0), 0);
  if (totalInvested > 0)
    capInput.value = Math.round(totalInvested);

  // Récupérer les taux manquants via l'API
  const missing = checked.map(cb => cb.value).filter(t => !_simRates[t]);
  if (missing.length) {
    document.getElementById('simDataInfo').textContent = '⏳ Chargement des données historiques yfinance…';
    try {
      const rates = await apiGet('/api/portfolio/simulate-rates?tickers=' + encodeURIComponent(missing.join(',')));
      Object.assign(_simRates, rates);
    } catch (_) {}
  }

  // Calcul du taux blendé (pondéré par capital investi)
  const totalW = checked.reduce((s, cb) => s + Math.max(1, parseFloat(cb.dataset.invested || 1)), 0);
  let blendedCagr = 0, blendedDiv = 0, infos = [], hasDiv = false;

  for (const cb of checked) {
    const w = Math.max(1, parseFloat(cb.dataset.invested || 1)) / totalW;
    const r = _simRates[cb.value] || {};
    if (r.cagr != null)           blendedCagr += r.cagr * w;
    if ((r.dividend_yield || 0) > 0) { blendedDiv += r.dividend_yield * w; hasDiv = true; }
    if (r.years_of_data)          infos.push(`${cb.value} (${r.years_of_data}a)`);
  }

  document.getElementById('simRate').value = blendedCagr.toFixed(1);
  document.getElementById('simRateInfo').textContent = blendedCagr ? `— CAGR historique` : '';
  document.getElementById('simDiv').value  = blendedDiv.toFixed(1);
  document.getElementById('simDivGroup').style.display = hasDiv ? '' : 'none';
  document.getElementById('simDataInfo').textContent   = infos.length ? `Données: ${infos.join(' · ')}` : '';

  _updateSim();
}

function _runSimulation() {
  const capital = parseFloat(document.getElementById('simCapital').value) || 0;
  const dca     = parseFloat(document.getElementById('simDCA').value)     || 0;
  const years   = parseInt(document.getElementById('simYears').value)     || 20;
  const rate    = parseFloat(document.getElementById('simRate').value)    || 0;
  const divY    = parseFloat(document.getElementById('simDiv')?.value)    || 0;

  // Pour les actions : séparer rendement prix et dividende
  const priceReturnAnnual = Math.max(0, rate - divY) / 100;
  const monthlyPriceRate  = Math.pow(1 + priceReturnAnnual, 1/12) - 1;
  const monthlyDivRate    = divY / 100 / 12;
  const monthlyTotalRate  = Math.pow(1 + rate / 100, 1/12) - 1;

  let value = capital, invested = capital, cumDivs = 0;
  const rows = [];

  for (let y = 1; y <= years; y++) {
    let yearDiv = 0;
    for (let m = 0; m < 12; m++) {
      value   += dca;
      invested += dca;
      if (divY > 0) {
        yearDiv += value * monthlyDivRate;      // dividende perçu en cash
        value    = value * (1 + monthlyPriceRate);
      } else {
        value    = value * (1 + monthlyTotalRate); // ETF accumulant
      }
    }
    cumDivs += yearDiv;
    rows.push({
      year:    y,
      invested: Math.round(invested),
      value:    Math.round(value),
      gain:     Math.round(value - invested),
      gainPct:  invested > 0 ? (value - invested) / invested * 100 : 0,
      yearDiv:  Math.round(yearDiv),
      cumDivs:  Math.round(cumDivs),
    });
  }
  return rows;
}

function _updateSim() {
  const checked = [...document.querySelectorAll('#simAssetList input:checked')];
  if (!checked.length) return;

  const rows  = _runSimulation();
  const last  = rows[rows.length - 1];
  const hasDivs = (parseFloat(document.getElementById('simDiv')?.value) || 0) > 0;
  const rate  = parseFloat(document.getElementById('simRate')?.value) || 0;
  const warn  = document.getElementById('simRateWarn');
  if (warn) warn.style.display = rate > 10 ? '' : 'none';

  // KPI cards
  const kpis = [
    { label: 'Valeur finale',   value: fmtEur(last.value),    color: 'var(--accent-green)' },
    { label: 'Total investi',   value: fmtEur(last.invested),  color: 'var(--text-primary)' },
    { label: hasDivs ? 'Gain capital' : 'Gain total',
      value: fmtEur(last.gain), color: last.gain >= 0 ? 'var(--accent-green)' : 'var(--accent-red)' },
  ];
  if (hasDivs) kpis.push({ label: 'Dividendes cumulés', value: fmtEur(last.cumDivs), color: '#F59E0B' });

  document.getElementById('simKpis').style.gridTemplateColumns = `repeat(${kpis.length},1fr)`;
  document.getElementById('simKpis').innerHTML = kpis.map(k => `
    <div style="background:var(--bg2);border:1px solid var(--border);border-radius:6px;padding:12px">
      <div style="font-size:10px;color:var(--text-secondary);text-transform:uppercase;letter-spacing:.06em;margin-bottom:4px">${k.label}</div>
      <div style="font-size:17px;font-weight:700;color:${k.color};font-family:var(--font-display)">${k.value}</div>
    </div>`).join('');

  // Graphique
  _renderSimChart(rows, hasDivs);

  // Tableau
  document.getElementById('simTable').innerHTML = `
    <div style="max-height:220px;overflow-y:auto">
    <table class="data-table" style="font-size:11px">
      <thead><tr>
        <th class="left" style="position:sticky;top:0;background:var(--bg-surface,var(--bg))">Année</th>
        <th style="position:sticky;top:0;background:var(--bg-surface,var(--bg))">Investi</th>
        <th style="position:sticky;top:0;background:var(--bg-surface,var(--bg))">Valeur</th>
        <th style="position:sticky;top:0;background:var(--bg-surface,var(--bg))">Gain €</th>
        <th style="position:sticky;top:0;background:var(--bg-surface,var(--bg))">Gain %</th>
        ${hasDivs ? '<th style="position:sticky;top:0;background:var(--bg-surface,var(--bg))">Div./an</th><th style="position:sticky;top:0;background:var(--bg-surface,var(--bg))">Div. cumulés</th>' : ''}
      </tr></thead>
      <tbody>
        ${rows.map(r => `<tr>
          <td class="left" style="color:var(--text-secondary)">${r.year}</td>
          <td>${fmtEur(r.invested)}</td>
          <td style="font-weight:600">${fmtEur(r.value)}</td>
          <td class="${r.gain >= 0 ? 'pos' : 'neg'}">${r.gain >= 0 ? '+' : ''}${fmtEur(r.gain)}</td>
          <td class="${r.gain >= 0 ? 'pos' : 'neg'}">${r.gain >= 0 ? '+' : ''}${fmtPct(r.gainPct)}</td>
          ${hasDivs ? `<td style="color:#F59E0B">${fmtEur(r.yearDiv)}</td><td>${fmtEur(r.cumDivs)}</td>` : ''}
        </tr>`).join('')}
      </tbody>
    </table>
    </div>`;
}

function _renderSimChart(rows, hasDivs) {
  if (_simChartInst) { _simChartInst.destroy(); _simChartInst = null; }
  const canvas = document.getElementById('simChart');
  if (!canvas) return;

  const ctx       = canvas.getContext('2d');
  const gradGreen = ctx.createLinearGradient(0, 0, 0, 200);
  gradGreen.addColorStop(0, 'rgba(0,214,143,.22)');
  gradGreen.addColorStop(1, 'rgba(0,214,143,0)');

  const datasets = [
    { label: 'Valeur projetée', data: rows.map(r => r.value),
      borderColor: '#00D68F', backgroundColor: gradGreen, borderWidth: 2,
      pointRadius: 0, pointHoverRadius: 4, fill: true, tension: 0.4 },
    { label: 'Capital investi', data: rows.map(r => r.invested),
      borderColor: '#3B82F6', backgroundColor: 'transparent', borderWidth: 1.5,
      borderDash: [5, 4], pointRadius: 0, fill: false, tension: 0 },
  ];

  if (hasDivs) {
    const gradOrange = ctx.createLinearGradient(0, 0, 0, 200);
    gradOrange.addColorStop(0, 'rgba(245,158,11,.18)');
    gradOrange.addColorStop(1, 'rgba(245,158,11,0)');
    datasets.push({
      label: 'Dividendes cumulés', data: rows.map(r => r.cumDivs),
      borderColor: '#F59E0B', backgroundColor: gradOrange, borderWidth: 1.5,
      pointRadius: 0, fill: true, tension: 0.4,
    });
  }

  _simChartInst = new Chart(canvas, {
    type: 'line',
    data: { labels: rows.map(r => `An ${r.year}`), datasets },
    options: {
      responsive: true, maintainAspectRatio: false,
      interaction: { mode: 'index', intersect: false },
      plugins: {
        legend: { display: true, labels: { color: '#6B7280', font: { size: 11 }, boxWidth: 18, padding: 12 } },
        tooltip: {
          backgroundColor: '#1A1F2E', titleColor: '#E8ECF0', bodyColor: '#9BA3AF',
          borderColor: '#1E2330', borderWidth: 1, padding: 10,
          callbacks: { label: ctx => `  ${ctx.dataset.label}: ${fmtEur(ctx.parsed.y)}` },
        },
      },
      scales: {
        x: { grid: { color: '#1E2330' }, ticks: { maxTicksLimit: 10, color: '#3D4452', font: { size: 10 } }},
        y: { position: 'right', grid: { color: '#1E2330' },
             ticks: { color: '#3D4452', callback: v => fmtEurShort(v), font: { size: 10 } }},
      },
    },
  });
}
