/* ═══════════════════════════════════════════════
   DASHBOARD — Unified patrimoine overview
   ═══════════════════════════════════════════════ */
'use strict';

let _dashData = null;

async function loadDashboard() {
  try {
    _dashData = await apiGet('/api/dashboard');
    renderDashboard(_dashData);
  } catch (err) {
    showToast('Erreur dashboard: ' + err.message, 'error');
  }
}

function renderDashboard(d) {
  const page = document.getElementById('page-dashboard');
  if (!page) return;

  const grandTotal = d.grand_total_eur;
  const port = d.portfolio;
  const cash = d.cash;
  const assets = d.assets;
  const res = d.reserves;

  // Allocation percentages
  const portPct  = grandTotal > 0 ? port.total_value_eur    / grandTotal * 100 : 0;
  const cashPct  = grandTotal > 0 ? cash.total_eur           / grandTotal * 100 : 0;
  const assetPct = grandTotal > 0 ? assets.total_value_eur   / grandTotal * 100 : 0;
  const resPct   = grandTotal > 0 ? res.total_releasable     / grandTotal * 100 : 0;

  page.innerHTML = `
    <!-- Hero row -->
    <div class="hero-grid">
      <div class="hero-card">
        <div class="card-label">${ICONS.pieChart} Patrimoine total</div>
        <div class="hero-card-value gold" id="dHeroTotal">${fmtEur(grandTotal)}</div>
        <div class="hero-card-sub">${d.is_market_open ? '<span style="color:var(--accent-green)">● Marché ouvert</span>' : '<span style="color:var(--text-muted)">● Marché fermé</span>'}</div>
      </div>
      <div class="hero-card">
        <div class="card-label">${ICONS.trendingUp} Portefeuille boursier</div>
        <div class="hero-card-value blue" id="dHeroPort">${fmtEur(port.total_value_eur)}</div>
        <div class="hero-card-sub ${pnlClass(port.total_pnl_eur)}">${pnlSign(port.total_pnl_eur)}${fmtEur(port.total_pnl_eur)} (${pnlSign(port.total_pnl_pct)}${fmtPct(port.total_pnl_pct)})</div>
      </div>
      <div class="hero-card">
        <div class="card-label">${ICONS.landmark} Liquidités coffres</div>
        <div class="hero-card-value green" id="dHeroCash">${fmtEur(cash.total_eur)}</div>
        <div class="hero-card-sub">${cash.coffre_count} coffre${cash.coffre_count > 1 ? 's' : ''}</div>
      </div>
      <div class="hero-card">
        <div class="card-label">${ICONS.gem} Actifs physiques</div>
        <div class="hero-card-value purple" id="dHeroAssets">${fmtEur(assets.total_value_eur)}</div>
        <div class="hero-card-sub">${assets.count} actif${assets.count > 1 ? 's' : ''}</div>
      </div>
      <div class="hero-card">
        <div class="card-label">${ICONS.wallet} Réserves libérables</div>
        <div class="hero-card-value gold" id="dHeroRes">${fmtEur(res.total_releasable)}</div>
        <div class="hero-card-sub" style="color:var(--text-muted)">constitué ${fmtEur(res.total_amount)}</div>
      </div>
    </div>

    <!-- Charts row -->
    <div class="grid-chart" style="margin-bottom:24px">
      <div class="card">
        <div class="card-title">Répartition du patrimoine</div>
        <div style="height:220px;display:flex;align-items:center;justify-content:center">
          <canvas id="patrimoineDonut"></canvas>
        </div>
        <div class="donut-legend" id="patrimoineDonutLegend"></div>
      </div>
      <div class="card">
        <div class="card-title">Flux de trésorerie mensuels (coffres)</div>
        <div style="height:220px"><canvas id="monthlyBarChart"></canvas></div>
      </div>
    </div>

    <!-- Detail row -->
    <div class="grid-3" style="margin-bottom:24px">

      <!-- Portfolio top movers -->
      <div class="card card-sm">
        <div class="card-title">Top movers <span style="font-size:11px;color:var(--text-secondary);font-weight:400">portefeuille</span></div>
        ${renderTopMovers(port)}
      </div>

      <!-- Coffres balances -->
      <div class="card card-sm">
        <div class="card-title">Soldes des coffres</div>
        ${renderCoffreBalances(cash.coffres)}
      </div>

      <!-- Réserves summary -->
      <div class="card card-sm">
        <div class="card-title">Réserves financières</div>
        ${renderReservesWidget(res)}
      </div>
    </div>

    <!-- Patrimoine allocation bar -->
    <div class="card card-sm">
      <div class="card-title">Allocation globale du patrimoine</div>
      <div style="display:grid;gap:10px">
        ${renderAllocBar('Portefeuille boursier', portPct,  '#3B82F6', port.total_value_eur)}
        ${renderAllocBar('Liquidités coffres',   cashPct,  '#00D68F', cash.total_eur)}
        ${renderAllocBar('Actifs physiques',     assetPct, '#a855f7', assets.total_value_eur)}
        ${renderAllocBar('Réserves libérables',  resPct,   '#F59E0B', res.total_releasable)}
      </div>
    </div>
  `;

  // Render charts after DOM is ready
  requestAnimationFrame(() => {
    renderPatrimoineDonut('patrimoineDonut', d);
    renderMonthlyBar('monthlyBarChart', d.monthly_flow.entries, d.monthly_flow.exits);
  });

  // Update header
  updateLiveBadge(d.is_market_open, d.last_updated);
}

// Mise à jour légère : chiffres seulement, sans recréer le DOM ni les graphiques
function refreshDashboardValues(d) {
  const $ = id => document.getElementById(id);
  if (!$('dHeroTotal')) return; // page pas encore rendue, on ignore
  $('dHeroTotal').textContent  = fmtEur(d.grand_total_eur);
  $('dHeroPort').textContent   = fmtEur(d.portfolio.total_value_eur);
  $('dHeroCash').textContent   = fmtEur(d.cash.total_eur);
  $('dHeroAssets').textContent = fmtEur(d.assets.total_value_eur);
  if ($('dHeroRes')) $('dHeroRes').textContent = fmtEur(d.reserves.total_releasable);
  updateLiveBadge(d.is_market_open, d.last_updated);
}

function renderTopMovers(port) {
  const gainers = (port.top_gainers || []).filter(p => (p.pnl_pct || 0) !== 0);
  const losers  = (port.top_losers  || []).filter(p => (p.pnl_pct || 0) !== 0);
  if (!gainers.length && !losers.length) {
    return `<div class="empty-state" style="padding:20px"><div class="empty-icon">📊</div><div class="empty-text">Aucun achat enregistré</div></div>`;
  }
  const rows = [...gainers, ...losers].slice(0, 5).map(p => `
    <div style="display:flex;align-items:center;justify-content:space-between;gap:8px;padding:6px 0;border-bottom:1px solid var(--border)">
      <div style="font-size:13px;font-weight:500;min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap">${escHtml(p.display_name)}</div>
      <div class="${pnlClass(p.pnl_pct)}" style="font-family:var(--font-display);font-size:12px;flex-shrink:0">${pnlSign(p.pnl_pct)}${fmtPct(p.pnl_pct)}</div>
    </div>`).join('');
  return `<div>${rows}</div>`;
}

function renderCoffreBalances(coffres) {
  if (!coffres?.length) {
    return `<div class="empty-state" style="padding:20px"><div class="empty-icon">🏦</div><div class="empty-text">Aucun coffre</div></div>`;
  }
  return coffres.map(c => `
    <div style="display:flex;align-items:center;justify-content:space-between;padding:7px 0;border-bottom:1px solid var(--border)">
      <div style="font-size:13px">${escHtml(c.name)}</div>
      <div style="font-family:var(--font-display);font-size:13px;color:var(--accent-gold)">${fmtEur(c.balance)}</div>
    </div>`).join('');
}

function renderReservesWidget(res) {
  return `
    <div style="display:grid;gap:10px">
      <div style="display:flex;justify-content:space-between;padding:7px 0;border-bottom:1px solid var(--border)">
        <span style="color:var(--text-secondary);font-size:13px">Total constitué</span>
        <span style="font-family:var(--font-display);font-size:13px;color:var(--accent-blue)">${fmtEur(res.total_amount)}</span>
      </div>
      <div style="display:flex;justify-content:space-between;padding:7px 0;border-bottom:1px solid var(--border)">
        <span style="color:var(--text-secondary);font-size:13px">Libéré</span>
        <span style="font-family:var(--font-display);font-size:13px;color:var(--accent-green)">${fmtEur(res.total_released)}</span>
      </div>
      <div style="display:flex;justify-content:space-between;padding:7px 0">
        <span style="color:var(--text-secondary);font-size:13px">Libérable</span>
        <span style="font-family:var(--font-display);font-size:13px;color:var(--accent-gold)">${fmtEur(res.total_releasable)}</span>
      </div>
    </div>`;
}

function renderAllocBar(label, pct, color, value) {
  return `
    <div>
      <div style="display:flex;justify-content:space-between;margin-bottom:4px">
        <span style="font-size:12px;color:var(--text-secondary)">${escHtml(label)}</span>
        <span style="font-family:var(--font-display);font-size:12px">${fmtEur(value)} — <span style="color:${color}">${pct.toFixed(1)}%</span></span>
      </div>
      <div class="patrimoine-bar">
        <div class="patrimoine-fill" style="width:${pct.toFixed(1)}%;background:${color}"></div>
      </div>
    </div>`;
}
