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

// ── Shared tooltip style ──────────────────────────────────

function tooltipStyle() {
  return {
    backgroundColor: '#1A1D25', borderColor: '#1E2330', borderWidth: 1,
    titleColor: '#F0F2F5', bodyColor: '#6B7280', padding: 10,
  };
}
