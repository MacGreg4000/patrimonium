/* ═══════════════════════════════════════════════
   DASHBOARD — Vue d'ensemble du patrimoine (piste B)
   Lecture seule : /api/dashboard + compléments chargés en parallèle
   (historique titres, derniers mouvements, réserves, inventaires).
   ═══════════════════════════════════════════════ */
'use strict';

let _dashData = null;
let _dashPeriod = 'month';

const DASH_PERIODS = [['month', '1 M'], ['year', '1 A'], ['ytd', 'YTD'], ['max', 'Tout']];

async function loadDashboard() {
  try {
    _dashData = await apiGet('/api/dashboard');
    renderDashboard(_dashData);
    loadDashboardExtras();
  } catch (err) {
    showToast('Erreur dashboard: ' + err.message, 'error');
  }
}

function _pct(part, total) { return total > 0 ? part / total * 100 : 0; }

function renderDashboard(d) {
  const page = document.getElementById('page-dashboard');
  if (!page) return;

  const grandTotal = d.grand_total_eur;
  const port   = d.portfolio;
  const cash   = d.cash;
  const assets = d.assets;
  const res    = d.reserves;
  const cry    = d.crypto || { total_value_eur: 0, total_pnl_eur: 0, position_count: 0 };

  const prevTotal    = port.total_value_eur - port.day_change_eur;
  const dayChangePct = prevTotal > 0 ? port.day_change_eur / prevTotal * 100 : null;
  // Somme d'affichage : ce qui est mobilisable rapidement (titres + coffres + crypto)
  const liquid = port.total_value_eur + cash.total_eur + (cry.total_value_eur || 0);

  const firstName = (typeof _currentUser !== 'undefined' && _currentUser?.name) ? _currentUser.name.split(' ')[0] : '';
  const today = new Date().toLocaleDateString('fr-BE', { weekday: 'long', day: 'numeric', month: 'long' });

  const tile = (page, color, label, id, value, subHtml) => `
    <button type="button" class="db-tile" onclick="navigate('${page}')">
      <span class="db-tile-label"><span class="db-dot" style="background:var(${color})"></span>${label}</span>
      <span class="db-tile-value" id="${id}">${value}</span>
      <span class="db-tile-sub">${subHtml}</span>
    </button>`;

  page.innerHTML = `
    <div class="db-head">
      <div>
        <h1 class="db-title">${firstName ? 'Bonjour ' + escHtml(firstName) : 'Patrimoine'}</h1>
        <div class="db-subtitle">${escHtml(today.charAt(0).toUpperCase() + today.slice(1))} ·
          ${d.is_market_open ? '<span class="pos">marché ouvert</span>' : 'marché fermé'}</div>
      </div>
      <div class="db-actions">
        <button class="btn btn-secondary" id="exportExcelBtn" onclick="exportExcel()">Export Excel</button>
        <button class="btn btn-primary" onclick="navigate('coffres')">+ Opération coffre</button>
      </div>
    </div>

    <div class="db-row">
      <section class="card db-hero">
        <div class="db-hero-top">
          <div>
            <div class="db-label">Patrimoine total
              <span class="db-tip" data-tip="Somme : portefeuille boursier + liquidités coffres + actifs physiques + réserves libérables (montant non encore libéré)">ⓘ</span></div>
            <div class="db-hero-value" id="dHeroTotal">${fmtEur(grandTotal)}</div>
            <div class="db-hero-meta">
              <span class="db-chip ${port.day_change_eur >= 0 ? 'is-gain' : 'is-loss'}" id="dHeroDayChange">${pnlSign(port.day_change_eur)}${fmtEur(port.day_change_eur)} aujourd’hui</span>
              <span>dont ${fmtEur(liquid)} mobilisables (titres, coffres, crypto)</span>
            </div>
          </div>
          <div class="db-seg" role="group" aria-label="Période du graphique">
            ${DASH_PERIODS.map(([p, l]) => `<button type="button" class="db-seg-btn${p === _dashPeriod ? ' active' : ''}" data-period="${p}" onclick="setDashPeriod('${p}')">${l}</button>`).join('')}
          </div>
        </div>
        <div class="db-chart-cap"><span>Portefeuille titres</span><span>Investi : ${fmtEur(port.total_invested_eur)}</span></div>
        <div class="db-chart"><canvas id="dashHistory"></canvas></div>
        <div class="db-empty" id="dashHistoryEmpty" hidden>Pas encore d’historique pour cette période.</div>
      </section>

      <section class="card db-alloc">
        <div class="db-card-title">Répartition</div>
        <div class="db-donut">
          <canvas id="patrimoineDonut"></canvas>
          <div class="db-donut-center"><span>total</span><strong>${fmtEurShort(grandTotal)}</strong></div>
        </div>
        <div id="patrimoineDonutLegend" class="db-legend"></div>
      </section>
    </div>

    <div class="db-tiles">
      ${tile('portfolio', '--pocket-titres', 'Titres', 'dHeroPort', fmtEur(port.total_value_eur),
        `<span class="${pnlClass(port.total_pnl_eur)}" id="dHeroPnl">${pnlSign(port.total_pnl_eur)}${fmtEur(port.total_pnl_eur)}</span> · ${pnlSign(port.total_pnl_pct)}${fmtPct(port.total_pnl_pct)} depuis l’achat`)}
      ${cry.position_count > 0 ? tile('crypto', '--pocket-crypto', 'Crypto', 'dHeroCrypto', fmtEur(cry.total_value_eur),
        `<span class="${pnlClass(cry.total_pnl_eur)}">${pnlSign(cry.total_pnl_eur)}${fmtEur(cry.total_pnl_eur)}${cry.total_pnl_pct != null ? ' · ' + pnlSign(cry.total_pnl_pct) + fmtPct(cry.total_pnl_pct) : ''}</span>`) : ''}
      ${tile('coffres', '--pocket-coffres', 'Coffres', 'dHeroCash', fmtEur(cash.total_eur),
        `${cash.coffre_count} coffre${cash.coffre_count > 1 ? 's' : ''}`)}
      ${tile('assets', '--pocket-assets', 'Actifs physiques', 'dHeroAssets', fmtEur(assets.total_value_eur),
        `${assets.count} bien${assets.count > 1 ? 's' : ''}`)}
      ${tile('reserves', '--pocket-reserves', 'Réserves libérables', 'dHeroRes', fmtEur(res.total_releasable),
        `constitué ${fmtEur(res.total_amount)}`)}
    </div>

    <div class="db-row db-row-3">
      <section class="card">
        <div class="db-card-title">À surveiller</div>
        <div id="dashAlerts" class="db-list"><div class="db-muted">Chargement…</div></div>
      </section>
      <section class="card">
        <div class="db-card-title">Plus fortes variations
          <button type="button" class="db-link" onclick="navigate('portfolio')">Portefeuille →</button></div>
        <div class="db-list">${renderTopMovers(port)}</div>
        <div class="db-foot">% depuis l’achat, pas la variation du jour</div>
      </section>
      <section class="card">
        <div class="db-card-title">Derniers mouvements
          <button type="button" class="db-link" onclick="navigate('coffres')">Coffres →</button></div>
        <div id="dashMoves" class="db-list"><div class="db-muted">Chargement…</div></div>
      </section>
    </div>

    <section class="card">
      <div class="db-card-title">Flux mensuels des coffres
        ${collapseSwitch('dashFlows', 'dashFlowsBody', false)}</div>
      <div id="dashFlowsBody" class="${collapseBodyClass('dashFlows', false)}">
        <div style="height:220px"><canvas id="monthlyBarChart"></canvas></div>
      </div>
    </section>
  `;

  requestAnimationFrame(() => {
    renderPatrimoineDonut('patrimoineDonut', d);
    renderMonthlyBar('monthlyBarChart', d.monthly_flow.entries, d.monthly_flow.exits);
  });

  updateLiveBadge(d.is_market_open, d.last_updated);
}

// ── Compléments (chargés après le rendu, chacun peut échouer sans bloquer) ──
async function loadDashboardExtras() {
  const d = _dashData;
  const [hist, moves, reserves, inventories] = await Promise.allSettled([
    apiGet('/api/portfolio/history?period=' + encodeURIComponent(_dashPeriod)),
    apiGet('/api/movements?limit=5'),
    apiGet('/api/reserves'),
    apiGet('/api/inventories'),
  ]);
  if (hist.status === 'fulfilled') _renderDashHistory(hist.value);
  const coffres = d?.cash?.coffres || [];
  const names = Object.fromEntries(coffres.map(c => [c.id, c.name]));
  const movesEl = document.getElementById('dashMoves');
  if (movesEl) movesEl.innerHTML = moves.status === 'fulfilled'
    ? renderDashMoves(moves.value.items || [], names)
    : '<div class="db-muted">Mouvements indisponibles</div>';
  const alertsEl = document.getElementById('dashAlerts');
  if (alertsEl) alertsEl.innerHTML = renderDashAlerts(d,
    reserves.status === 'fulfilled' ? reserves.value : null,
    inventories.status === 'fulfilled' ? inventories.value : null);
}

function _renderDashHistory(history) {
  const empty = document.getElementById('dashHistoryEmpty');
  const has = Array.isArray(history) && history.length > 1;
  if (empty) empty.hidden = has;
  const box = document.getElementById('dashHistory')?.parentElement;
  if (box) box.hidden = !has;
  if (has) renderPortfolioLine('dashHistory', history);
  else destroyChart('dashHistory');
}

async function setDashPeriod(period) {
  _dashPeriod = period;
  document.querySelectorAll('.db-seg-btn').forEach(b => b.classList.toggle('active', b.dataset.period === period));
  try { _renderDashHistory(await apiGet('/api/portfolio/history?period=' + encodeURIComponent(period))); }
  catch (_) {}
}

// Mise à jour légère : chiffres seulement, sans recréer le DOM ni les graphiques
function refreshDashboardValues(d) {
  const $ = id => document.getElementById(id);
  if (!$('dHeroTotal')) return;
  $('dHeroTotal').textContent  = fmtEur(d.grand_total_eur);
  $('dHeroPort').textContent   = fmtEur(d.portfolio.total_value_eur);
  $('dHeroCash').textContent   = fmtEur(d.cash.total_eur);
  $('dHeroAssets').textContent = fmtEur(d.assets.total_value_eur);
  if ($('dHeroRes'))    $('dHeroRes').textContent    = fmtEur(d.reserves.total_releasable);
  if ($('dHeroCrypto')) $('dHeroCrypto').textContent = fmtEur(d.crypto?.total_value_eur || 0);
  if ($('dHeroDayChange')) {
    $('dHeroDayChange').textContent = pnlSign(d.portfolio.day_change_eur) + fmtEur(d.portfolio.day_change_eur) + ' aujourd’hui';
    $('dHeroDayChange').className = 'db-chip ' + (d.portfolio.day_change_eur >= 0 ? 'is-gain' : 'is-loss');
  }
  if ($('dHeroPnl')) $('dHeroPnl').textContent = pnlSign(d.portfolio.total_pnl_eur) + fmtEur(d.portfolio.total_pnl_eur);
  updateLiveBadge(d.is_market_open, d.last_updated);
}

function renderTopMovers(port) {
  const list = [...(port.top_gainers || []), ...(port.top_losers || [])].filter(p => (p.pnl_pct || 0) !== 0);
  if (!list.length) return '<div class="db-muted">Aucun achat enregistré</div>';
  return list.map(p => `
    <div class="db-item">
      <span class="db-badge">${escHtml((p.ticker || '').split('.')[0].slice(0, 5))}</span>
      <div class="db-item-main">
        <div class="db-item-title">${escHtml(p.display_name)}</div>
        <div class="db-item-sub">${fmtEur(p.current_value || 0)}</div>
      </div>
      <span class="db-chip ${p.pnl_pct >= 0 ? 'is-gain' : 'is-loss'}">${pnlSign(p.pnl_pct)}${fmtPct(p.pnl_pct)}</span>
    </div>`).join('');
}

function renderDashMoves(items, names) {
  if (!items.length) return '<div class="db-muted">Aucun mouvement</div>';
  return items.map(m => {
    const inMove = m.type === 'ENTRY';
    const date = new Date(m.created_at).toLocaleDateString('fr-BE', { day: 'numeric', month: 'short' });
    const label = m.description || (m.transfer_ref ? 'Transfert' : inMove ? 'Dépôt' : 'Retrait');
    return `
      <div class="db-item">
        <span class="db-icon ${inMove ? 'is-gain' : 'is-loss'}" aria-hidden="true">${inMove ? '↓' : '↑'}</span>
        <div class="db-item-main">
          <div class="db-item-title">${escHtml(label)}</div>
          <div class="db-item-sub">${escHtml(date)} · ${escHtml(names[m.coffre_id] || 'Coffre')}</div>
        </div>
        <span class="db-amount ${inMove ? 'pos' : 'neg'}">${inMove ? '+' : '−'}${fmtEur(Math.abs(m.amount))}</span>
      </div>`;
  }).join('');
}

// Rappels calculés à partir des données déjà présentes (aucune règle métier nouvelle)
function renderDashAlerts(d, reserves, inventories) {
  const alerts = [];
  const year = new Date().getFullYear();

  // Réserves arrivant à libération cette année (ou en retard) et pas encore libérées
  const resItems = reserves?.items || [];
  const due = resItems.filter(r => r.release_year && r.release_year <= year && r.releasable > 0);
  if (due.length) {
    const total = due.reduce((s, r) => s + r.releasable, 0);
    alerts.push(['accent', `Réserve${due.length > 1 ? 's' : ''} libérable${due.length > 1 ? 's' : ''} : ${due.map(r => r.year).join(', ')}`,
      `${fmtEur(total)} · échéance ${due[0].release_year}`, 'reserves', 'Voir']);
  }

  // Coffres avec solde dont le dernier inventaire date de plus de 90 jours (ou jamais)
  const invList = Array.isArray(inventories) ? inventories : (inventories?.items || []);
  for (const c of (d.cash?.coffres || []).filter(c => c.balance > 0)) {
    const last = invList.filter(i => i.coffre_id === c.id).map(i => new Date(i.date)).sort((a, b) => b - a)[0];
    const days = last ? Math.floor((Date.now() - last) / 86400000) : null;
    if (days === null || days > 90)
      alerts.push(['warn', `Inventaire · ${c.name}`, days === null ? 'Jamais compté' : `Dernier comptage il y a ${days} jours`, 'coffres', 'Compter']);
  }

  // Positions en perte de plus de 10 % depuis l'achat
  for (const p of (d.portfolio?.top_losers || []).filter(p => p.pnl_pct <= -10))
    alerts.push(['loss', `${p.display_name} sous son prix de revient`, `${fmtPct(p.pnl_pct)} depuis l’achat`, 'portfolio', 'Détail']);

  if (!alerts.length) return '<div class="db-muted">Rien à signaler.</div>';
  return alerts.map(([tone, title, sub, page, cta]) => `
    <div class="db-alert">
      <span class="db-alert-dot is-${tone}"></span>
      <div class="db-item-main"><div class="db-item-title">${escHtml(title)}</div><div class="db-item-sub">${escHtml(sub)}</div></div>
      <button type="button" class="db-link" onclick="navigate('${page}')">${cta}</button>
    </div>`).join('');
}
