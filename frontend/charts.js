/* ═══════════════════════════════════════════════
   CHARTS — Reusable Chart.js instances
   ═══════════════════════════════════════════════ */
'use strict';

Chart.defaults.color = '#6B7280';
Chart.defaults.font.family = "'DM Mono', monospace";
Chart.defaults.font.size = 11;

const _charts = {};

function destroyChart(id) {
  if (_charts[id]) { _charts[id].destroy(); delete _charts[id]; }
}

// ── Donut ─────────────────────────────────────────────────

function renderDonut(canvasId, labels, data, legendId) {
  destroyChart(canvasId);
  const canvas = document.getElementById(canvasId);
  if (!canvas) return;
  const colors = labels.map((_, i) => CHART_COLORS[i % CHART_COLORS.length]);
  _charts[canvasId] = new Chart(canvas, {
    type: 'doughnut',
    data: { labels, datasets: [{ data, backgroundColor: colors, borderColor: '#111318', borderWidth: 3, hoverOffset: 6 }] },
    options: {
      responsive: true, maintainAspectRatio: false, cutout: '72%',
      plugins: {
        legend: { display: false },
        tooltip: { ...tooltipStyle(), callbacks: {
          label(ctx) {
            const tot = ctx.dataset.data.reduce((a, b) => a + b, 0);
            const pct = tot > 0 ? (ctx.parsed / tot * 100).toFixed(1) : 0;
            return `  ${fmtEur(ctx.parsed)}  (${pct}%)`;
          }
        }},
      },
    },
  });

  if (legendId) {
    const total = data.reduce((a, b) => a + b, 0);
    const legend = document.getElementById(legendId);
    if (legend) legend.innerHTML = labels.map((l, i) => `
      <div class="legend-item">
        <div class="legend-dot" style="background:${colors[i]}"></div>
        <span class="legend-name">${escHtml(l)}</span>
        <span class="legend-pct">${total > 0 ? (data[i] / total * 100).toFixed(1) : 0}%</span>
      </div>`).join('');
  }
}

// ── Line (portfolio history) ───────────────────────────────

function renderPortfolioLine(canvasId, history) {
  destroyChart(canvasId);
  const canvas = document.getElementById(canvasId);
  if (!canvas || !history?.length) return;

  const labels   = history.map(h => fmtDate(h.timestamp));
  const values   = history.map(h => h.total_value_eur);
  const invested = history.map(h => h.total_invested_eur);

  const ctx = canvas.getContext('2d');
  const grad = ctx.createLinearGradient(0, 0, 0, 260);
  grad.addColorStop(0, 'rgba(59,130,246,.25)');
  grad.addColorStop(1, 'rgba(59,130,246,0)');

  _charts[canvasId] = new Chart(canvas, {
    type: 'line',
    data: { labels, datasets: [
      { label: 'Valeur', data: values, borderColor: '#3B82F6', backgroundColor: grad, borderWidth: 2,
        pointRadius: 0, pointHoverRadius: 5, fill: true, tension: 0.4 },
      { label: 'Investi', data: invested, borderColor: '#1E2330', backgroundColor: 'transparent',
        borderWidth: 1.5, borderDash: [4, 4], pointRadius: 0, fill: false, tension: 0.4 },
    ]},
    options: {
      responsive: true, maintainAspectRatio: false,
      interaction: { mode: 'index', intersect: false },
      plugins: {
        legend: { display: false },
        tooltip: { ...tooltipStyle(), callbacks: { label: ctx => `  ${ctx.dataset.label}: ${fmtEur(ctx.parsed.y)}` }},
      },
      scales: {
        x: { grid: { color: '#1E2330' }, ticks: { maxTicksLimit: 8, color: '#3D4452' }},
        y: { position: 'right', grid: { color: '#1E2330' }, ticks: { color: '#3D4452', callback: fmtEurShort }},
      },
    },
  });
}

// ── Investissement vs gains réels ─────────────────────────
// Zone d'investissement : ligne + aire bleue remplie en dessous.
// Par-dessus, la valeur du portefeuille : VERTE tant qu'elle est au-dessus
// de l'investi, ROUGE dès qu'elle croise et passe en dessous (perte).
function renderInvestGainChart(canvasId, history) {
  destroyChart(canvasId);
  const canvas = document.getElementById(canvasId);
  if (!canvas || !history?.length) return;

  const labels   = history.map(h => fmtDate(h.timestamp));
  const invested = history.map(h => h.total_invested_eur);
  const value    = history.map(h => h.total_value_eur != null
    ? h.total_value_eur
    : (h.total_invested_eur + (h.total_pnl_eur || 0)));

  const ctx = canvas.getContext('2d');
  const gradInvest = ctx.createLinearGradient(0, 0, 0, 260);
  gradInvest.addColorStop(0, 'rgba(79,142,247,.30)');
  gradInvest.addColorStop(1, 'rgba(79,142,247,0)');

  // Couleur du trait de valeur, segment par segment : vert si ≥ investi, sinon rouge
  const segColor = c => {
    const i = c.p1DataIndex;
    return value[i] >= invested[i] ? '#10D98A' : '#F5465D';
  };

  _charts[canvasId] = new Chart(canvas, {
    type: 'line',
    data: { labels, datasets: [
      // Zone d'investissement (dessinée en premier = en dessous)
      { label: 'Montants investis', data: invested,
        borderColor: '#4F8EF7', backgroundColor: gradInvest, borderWidth: 2,
        pointRadius: 0, pointHoverRadius: 4, fill: true, tension: 0.35 },
      // Valeur du portefeuille (au-dessus), colorée vert/rouge par segment
      { label: 'Valeur du portefeuille', data: value,
        borderColor: '#10D98A', backgroundColor: 'transparent', borderWidth: 2.5,
        pointRadius: 0, pointHoverRadius: 5, fill: false, tension: 0.35,
        segment: { borderColor: segColor } },
    ]},
    options: {
      responsive: true, maintainAspectRatio: false,
      interaction: { mode: 'index', intersect: false },
      plugins: {
        legend: { display: true, labels: { color: '#7D97BA', font: { size: 11 }, boxWidth: 16, padding: 14, usePointStyle: true }},
        tooltip: { ...tooltipStyle(), callbacks: {
          label: ctx => `  ${ctx.dataset.label}: ${fmtEur(ctx.parsed.y)}`,
          afterBody: items => {
            const i = items[0].dataIndex;
            const gain = value[i] - invested[i];
            const sign = gain >= 0 ? '+' : '';
            return `\n  Gain/perte: ${sign}${fmtEur(gain)}`;
          },
        }},
      },
      scales: {
        x: { grid: { color: '#1E2330' }, ticks: { maxTicksLimit: 8, color: '#3D4452', font: { size: 10 } }},
        y: { position: 'right', grid: { color: '#1E2330' },
             ticks: { color: '#3D4452', callback: fmtEurShort, font: { size: 10 } }},
      },
    },
  });
}

// ── Bar (monthly cash flow) ───────────────────────────────

function renderMonthlyBar(canvasId, entries, exits) {
  destroyChart(canvasId);
  const canvas = document.getElementById(canvasId);
  if (!canvas) return;

  // Merge and sort keys
  const keys = [...new Set([...Object.keys(entries), ...Object.keys(exits)])].sort();
  const labels = keys.map(k => {
    const [y, m] = k.split('-');
    return `${m}/${y.slice(2)}`;
  });

  _charts[canvasId] = new Chart(canvas, {
    type: 'bar',
    data: { labels, datasets: [
      { label: 'Entrées', data: keys.map(k => entries[k] || 0), backgroundColor: 'rgba(0,214,143,.5)', borderColor: '#00D68F', borderWidth: 1 },
      { label: 'Sorties', data: keys.map(k => -(exits[k] || 0)), backgroundColor: 'rgba(255,71,87,.5)', borderColor: '#FF4757', borderWidth: 1 },
    ]},
    options: {
      responsive: true, maintainAspectRatio: false,
      plugins: {
        legend: { display: true, labels: { color: '#6B7280', boxWidth: 10, padding: 12 }},
        tooltip: { ...tooltipStyle(), callbacks: { label: ctx => `  ${ctx.dataset.label}: ${fmtEur(Math.abs(ctx.parsed.y))}` }},
      },
      scales: {
        x: { grid: { color: '#1E2330' }, ticks: { color: '#3D4452' }, stacked: false },
        y: { grid: { color: '#1E2330' }, ticks: { color: '#3D4452', callback: fmtEurShort }},
      },
    },
  });
}

// ── Patrimoine donut (dashboard grand total) ───────────────

function renderPatrimoineDonut(canvasId, data) {
  const { portfolio, cash, assets, reserves } = data;
  const labels = ['Portefeuille', 'Liquidités', 'Actifs physiques', 'Réserves'];
  const values = [
    portfolio.total_value_eur,
    cash.total_eur,
    assets.total_value_eur,
    reserves?.total_releasable || 0,
  ];
  renderDonut(canvasId, labels, values, canvasId + 'Legend');
}

// ── Coffre balance over time ──────────────────────────────

function renderCoffreBalanceLine(canvasId, points) {
  destroyChart(canvasId);
  const canvas = document.getElementById(canvasId);
  if (!canvas) return;

  if (!points.length) {
    const ctx = canvas.getContext('2d');
    ctx.clearRect(0, 0, canvas.width, canvas.height);
    return;
  }

  const labels = points.map(p => fmtDate(p.date));
  const values = points.map(p => p.balance);

  const ctx = canvas.getContext('2d');
  const grad = ctx.createLinearGradient(0, 0, 0, 220);
  grad.addColorStop(0, 'rgba(245,158,11,.28)');
  grad.addColorStop(1, 'rgba(245,158,11,0)');

  _charts[canvasId] = new Chart(canvas, {
    type: 'line',
    data: {
      labels,
      datasets: [{
        label: 'Solde',
        data: values,
        borderColor: '#F59E0B',
        backgroundColor: grad,
        borderWidth: 2,
        pointRadius: points.length <= 30 ? 4 : 0,
        pointHoverRadius: 6,
        pointBackgroundColor: '#F59E0B',
        fill: true,
        stepped: true,
      }],
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      interaction: { mode: 'index', intersect: false },
      plugins: {
        legend: { display: false },
        tooltip: {
          ...tooltipStyle(),
          callbacks: {
            title: ctx => ctx[0].label,
            label: ctx => `  Solde : ${fmtEur(ctx.parsed.y)}`,
          },
        },
      },
      scales: {
        x: { grid: { color: '#1E2330' }, ticks: { color: '#3D4452', maxTicksLimit: 10 }},
        y: {
          position: 'right',
          grid: { color: '#1E2330' },
          ticks: { color: '#3D4452', callback: fmtEurShort },
          min: 0,
        },
      },
    },
  });
}

// ── Shared tooltip style ──────────────────────────────────

function tooltipStyle() {
  return {
    backgroundColor: '#1A1D25', borderColor: '#1E2330', borderWidth: 1,
    titleColor: '#F0F2F5', bodyColor: '#6B7280', padding: 10,
  };
}
