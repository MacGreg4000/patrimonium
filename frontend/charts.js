/* ═══════════════════════════════════════════════
   CHARTS — Reusable Chart.js instances
   ═══════════════════════════════════════════════ */
'use strict';

Chart.defaults.font.family = "'Plus Jakarta Sans', -apple-system, system-ui, sans-serif";
Chart.defaults.font.size = 11;

// Couleurs lues dans les variables CSS du thème courant (clair / sombre).
function cssVar(name) {
  return getComputedStyle(document.documentElement).getPropertyValue(name).trim();
}
function withAlpha(color, a) {
  const m = /^#([0-9a-f]{6})$/i.exec(color);
  if (!m) return color;
  const n = parseInt(m[1], 16);
  return `rgba(${n >> 16},${(n >> 8) & 255},${n & 255},${a})`;
}
function themeColors() {
  return {
    text: cssVar('--text-muted'), grid: cssVar('--border'), surface: cssVar('--bg-secondary'),
    accent: cssVar('--accent-blue'), gain: cssVar('--accent-green'), loss: cssVar('--accent-red'),
    gold: cssVar('--pocket-reserves'), title: cssVar('--text-primary'), body: cssVar('--text-secondary'),
    line: cssVar('--border-light'),
  };
}
function applyChartDefaults() { Chart.defaults.color = themeColors().text; }
applyChartDefaults();

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
    data: { labels, datasets: [{ data, backgroundColor: colors, borderColor: themeColors().surface, borderWidth: 3, hoverOffset: 6 }] },
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
  const C = themeColors();
  grad.addColorStop(0, withAlpha(C.accent, .18));
  grad.addColorStop(1, withAlpha(C.accent, 0));

  _charts[canvasId] = new Chart(canvas, {
    type: 'line',
    data: { labels, datasets: [
      { label: 'Valeur', data: values, borderColor: C.accent, backgroundColor: grad, borderWidth: 2,
        pointRadius: 0, pointHoverRadius: 5, fill: true, tension: 0.4 },
      { label: 'Investi', data: invested, borderColor: C.text, backgroundColor: 'transparent',
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
        x: { grid: { color: C.grid }, ticks: { maxTicksLimit: 8, color: C.text }},
        y: { position: 'right', grid: { color: C.grid }, ticks: { color: C.text, callback: fmtEurShort }},
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
  const C = themeColors();
  gradInvest.addColorStop(0, withAlpha(C.accent, .18));
  gradInvest.addColorStop(1, withAlpha(C.accent, 0));

  // Couleur du trait de valeur, segment par segment : vert si ≥ investi, sinon rouge
  const segColor = c => {
    const i = c.p1DataIndex;
    return value[i] >= invested[i] ? C.gain : C.loss;
  };

  _charts[canvasId] = new Chart(canvas, {
    type: 'line',
    data: { labels, datasets: [
      // Zone d'investissement (dessinée en premier = en dessous)
      { label: 'Montants investis', data: invested,
        borderColor: C.accent, backgroundColor: gradInvest, borderWidth: 2,
        pointRadius: 0, pointHoverRadius: 4, fill: true, tension: 0.35 },
      // Valeur du portefeuille (au-dessus), colorée vert/rouge par segment
      { label: 'Valeur du portefeuille', data: value,
        borderColor: C.gain, backgroundColor: 'transparent', borderWidth: 2.5,
        pointRadius: 0, pointHoverRadius: 5, fill: false, tension: 0.35,
        segment: { borderColor: segColor } },
    ]},
    options: {
      responsive: true, maintainAspectRatio: false,
      interaction: { mode: 'index', intersect: false },
      plugins: {
        legend: { display: true, labels: { color: C.body, font: { size: 11 }, boxWidth: 16, padding: 14, usePointStyle: true }},
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
        x: { grid: { color: C.grid }, ticks: { maxTicksLimit: 8, color: C.text, font: { size: 10 } }},
        y: { position: 'right', grid: { color: C.grid },
             ticks: { color: C.text, callback: fmtEurShort, font: { size: 10 } }},
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

  const C = themeColors();
  _charts[canvasId] = new Chart(canvas, {
    type: 'bar',
    data: { labels, datasets: [
      { label: 'Entrées', data: keys.map(k => entries[k] || 0), backgroundColor: withAlpha(C.gain, .55), borderColor: C.gain, borderWidth: 1 },
      { label: 'Sorties', data: keys.map(k => -(exits[k] || 0)), backgroundColor: withAlpha(C.loss, .55), borderColor: C.loss, borderWidth: 1 },
    ]},
    options: {
      responsive: true, maintainAspectRatio: false,
      plugins: {
        legend: { display: true, labels: { color: C.body, boxWidth: 10, padding: 12 }},
        tooltip: { ...tooltipStyle(), callbacks: { label: ctx => `  ${ctx.dataset.label}: ${fmtEur(Math.abs(ctx.parsed.y))}` }},
      },
      scales: {
        x: { grid: { color: C.grid }, ticks: { color: C.text }, stacked: false },
        y: { grid: { color: C.grid }, ticks: { color: C.text, callback: fmtEurShort }},
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
  const C = themeColors();
  grad.addColorStop(0, withAlpha(C.gold, .22));
  grad.addColorStop(1, withAlpha(C.gold, 0));

  _charts[canvasId] = new Chart(canvas, {
    type: 'line',
    data: {
      labels,
      datasets: [{
        label: 'Solde',
        data: values,
        borderColor: C.gold,
        backgroundColor: grad,
        borderWidth: 2,
        pointRadius: points.length <= 30 ? 4 : 0,
        pointHoverRadius: 6,
        pointBackgroundColor: C.gold,
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
        x: { grid: { color: C.grid }, ticks: { color: C.text, maxTicksLimit: 10 }},
        y: {
          position: 'right',
          grid: { color: C.grid },
          ticks: { color: C.text, callback: fmtEurShort },
          min: 0,
        },
      },
    },
  });
}

// ── Shared tooltip style ──────────────────────────────────

function tooltipStyle() {
  const C = themeColors();
  return {
    backgroundColor: C.surface, borderColor: C.line, borderWidth: 1,
    titleColor: C.title, bodyColor: C.body, padding: 10, cornerRadius: 10,
  };
}
