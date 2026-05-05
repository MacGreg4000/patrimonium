/* ═══════════════════════════════════════════════
   UTILS — Shared helpers across all modules
   ═══════════════════════════════════════════════ */
'use strict';

// ── Formatters ────────────────────────────────────────────

function fmtEur(v, decimals = 2) {
  if (v == null) return '—';
  return new Intl.NumberFormat('fr-BE', {
    style: 'currency', currency: 'EUR',
    minimumFractionDigits: decimals, maximumFractionDigits: decimals,
  }).format(v);
}

function fmtNum(v, decimals = 2) {
  if (v == null) return '—';
  return new Intl.NumberFormat('fr-BE', {
    minimumFractionDigits: decimals, maximumFractionDigits: decimals,
  }).format(v);
}

function fmtPct(v, decimals = 2) {
  if (v == null) return '—';
  return fmtNum(v, decimals) + '%';
}

function fmtDate(iso) {
  if (!iso) return '—';
  const d = new Date(iso.includes('T') ? iso : iso + 'T00:00:00');
  return d.toLocaleDateString('fr-BE', { day: '2-digit', month: '2-digit', year: 'numeric' });
}

function fmtDateTime(iso) {
  if (!iso) return '—';
  const d = new Date(iso);
  return d.toLocaleDateString('fr-BE', { day: '2-digit', month: '2-digit', year: 'numeric' })
    + ' ' + d.toLocaleTimeString('fr-BE', { hour: '2-digit', minute: '2-digit' });
}

function fmtSize(bytes) {
  if (!bytes) return '—';
  if (bytes >= 1048576) return (bytes / 1048576).toFixed(1) + ' MB';
  if (bytes >= 1024) return (bytes / 1024).toFixed(0) + ' KB';
  return bytes + ' B';
}

function fmtEurShort(v) {
  if (v == null) return '—';
  if (Math.abs(v) >= 1_000_000) return (v / 1_000_000).toFixed(1) + 'M €';
  if (Math.abs(v) >= 1_000) return (v / 1_000).toFixed(0) + 'k €';
  return v.toFixed(0) + ' €';
}

function escHtml(str) {
  if (str == null) return '';
  return String(str)
    .replace(/&/g, '&amp;').replace(/</g, '&lt;')
    .replace(/>/g, '&gt;').replace(/"/g, '&quot;');
}

function pnlClass(v) {
  if (v == null || v === 0) return 'neutral';
  return v > 0 ? 'pos' : 'neg';
}

function pnlSign(v) {
  return v != null && v > 0 ? '+' : '';
}

function todayISO() {
  return new Date().toISOString().split('T')[0];
}

// ── Number animation ──────────────────────────────────────

const _animTargets = new Map();

function animateNumber(el, target, formatter) {
  if (!el) return;
  const prev = _animTargets.get(el) ?? target;
  _animTargets.set(el, target);
  if (Math.abs(target - prev) < 0.01) { el.textContent = formatter(target); return; }
  const start = performance.now();
  const dur = 600;
  const from = prev;
  function step(now) {
    const t = Math.min((now - start) / dur, 1);
    const eased = 1 - Math.pow(1 - t, 3);
    el.textContent = formatter(from + (target - from) * eased);
    if (t < 1) requestAnimationFrame(step);
  }
  requestAnimationFrame(step);
}

// ── API ───────────────────────────────────────────────────

let _csrfToken = null;

async function apiFetch(url, options = {}, _retry = false) {
  const isFormData = options.body instanceof FormData;
  // Ne pas forcer Content-Type pour FormData — le navigateur le pose avec la boundary
  const headers = isFormData
    ? { ...options.headers }
    : { 'Content-Type': 'application/json', ...options.headers };
  if (_csrfToken && ['POST','PUT','DELETE','PATCH'].includes((options.method || 'GET').toUpperCase())) {
    headers['X-CSRF-Token'] = _csrfToken;
  }
  const res = await fetch(url, { ...options, headers, credentials: 'include' });

  // Access token expiré → refresh puis retry une fois
  if (res.status === 401 && !_retry) {
    const refreshed = await fetch('/api/auth/refresh', { method: 'POST', credentials: 'include' });
    if (!refreshed.ok) { showLogin(); throw new Error('Session expirée'); }
    return apiFetch(url, options, true);
  }

  // CSRF token expiré → refresh CSRF puis retry une fois
  if (res.status === 403 && !_retry) {
    const body = await res.json().catch(() => ({}));
    if (body.detail === 'Token CSRF invalide') {
      await refreshCsrf();
      return apiFetch(url, options, true);
    }
    throw new Error(body.detail || res.statusText);
  }

  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: res.statusText }));
    throw new Error(err.detail || res.statusText);
  }
  if (res.status === 204) return null;
  return res.json();
}

const apiGet    = url       => apiFetch(url);
const apiPost   = (url, b)  => apiFetch(url, { method: 'POST',   body: JSON.stringify(b) });
const apiPut    = (url, b)  => apiFetch(url, { method: 'PUT',    body: JSON.stringify(b) });
const apiDelete = url       => apiFetch(url, { method: 'DELETE' });

async function refreshCsrf() {
  try {
    const { csrf_token } = await apiGet('/api/auth/csrf');
    _csrfToken = csrf_token;
  } catch (_) {}
}

// ── Toast ─────────────────────────────────────────────────

function showToast(message, type = 'info') {
  const container = document.getElementById('toastContainer');
  const t = document.createElement('div');
  t.className = `toast ${type}`;
  const icons = { success: '✓', error: '✕', info: 'ℹ' };
  t.innerHTML = `<span class="toast-icon">${icons[type] ?? 'ℹ'}</span>
    <span class="toast-msg">${escHtml(message)}</span>
    <button class="toast-close" onclick="this.closest('.toast').remove()">✕</button>`;
  container.appendChild(t);
  setTimeout(() => t.remove(), 4500);
}

// ── Modal helpers ─────────────────────────────────────────

function openModal(id) {
  const el = document.getElementById(id);
  if (el) { el.classList.add('open'); document.body.style.overflow = 'hidden'; }
}

function closeModal(id) {
  const el = document.getElementById(id);
  if (el) { el.classList.remove('open'); document.body.style.overflow = ''; }
}

document.addEventListener('click', e => {
  if (e.target.classList.contains('modal-overlay')) {
    e.target.classList.remove('open');
    document.body.style.overflow = '';
  }
});

document.addEventListener('keydown', e => {
  if (e.key === 'Escape') {
    document.querySelectorAll('.modal-overlay.open').forEach(el => {
      el.classList.remove('open'); document.body.style.overflow = '';
    });
  }
});

// ── Tabs ──────────────────────────────────────────────────

function switchTab(groupId, tabId) {
  const group = document.getElementById(groupId);
  if (!group) {
    // fallback: use parent modal
    document.querySelectorAll(`.tab-panel[id^="tab-"]`).forEach(p => p.classList.remove('active'));
    document.querySelectorAll(`.tab-btn`).forEach(b => b.classList.remove('active'));
    const panel = document.getElementById(`tab-${tabId}`);
    if (panel) {
      panel.classList.add('active');
      panel.closest('.modal')?.querySelectorAll('.tab-btn').forEach(b => {
        b.classList.toggle('active', b.textContent.toLowerCase().includes(tabId));
      });
    }
    return;
  }
  group.querySelectorAll('.tab-panel').forEach(p => p.classList.remove('active'));
  group.querySelectorAll('.tab-btn').forEach(b => b.classList.remove('active'));
  const panel = group.querySelector(`#tab-${tabId}`);
  if (panel) panel.classList.add('active');
  // activate button
  group.querySelectorAll('.tab-btn').forEach(b => {
    if (b.getAttribute('onclick')?.includes(tabId)) b.classList.add('active');
  });
}

// ── Confirm dialog ────────────────────────────────────────

function confirm(title, message, onConfirm) {
  document.getElementById('confirmTitle').textContent = title;
  document.getElementById('confirmMessage').textContent = message;
  const btn = document.getElementById('confirmBtn');
  btn.onclick = () => { closeModal('confirmModal'); onConfirm(); };
  openModal('confirmModal');
}

// ── SVG icon library (Lucide-style, stroke-based) ─────────

const ICONS = {
  // Navigation
  dashboard: `<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect x="3" y="3" width="7" height="7" rx="1"/><rect x="14" y="3" width="7" height="7" rx="1"/><rect x="14" y="14" width="7" height="7" rx="1"/><rect x="3" y="14" width="7" height="7" rx="1"/></svg>`,
  trendingUp: `<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polyline points="22 7 13.5 15.5 8.5 10.5 2 17"/><polyline points="16 7 22 7 22 13"/></svg>`,
  landmark:   `<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><line x1="3" y1="22" x2="21" y2="22"/><line x1="6" y1="18" x2="6" y2="11"/><line x1="10" y1="18" x2="10" y2="11"/><line x1="14" y1="18" x2="14" y2="11"/><line x1="18" y1="18" x2="18" y2="11"/><polygon points="12 2 20 7 4 7"/></svg>`,
  gem:        `<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polygon points="6 3 18 3 22 9 12 22 2 9"/><line x1="2" y1="9" x2="22" y2="9"/><line x1="12" y1="3" x2="6" y2="9"/><line x1="12" y1="3" x2="18" y2="9"/></svg>`,
  wallet:     `<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M21 12V7H5a2 2 0 010-4h14v4"/><path d="M3 5v14a2 2 0 002 2h16v-5"/><path d="M18 12a2 2 0 000 4h4v-4z"/></svg>`,
  shield:     `<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z"/></svg>`,
  settings:   `<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><line x1="21" y1="4" x2="14" y2="4"/><line x1="10" y1="4" x2="3" y2="4"/><line x1="21" y1="12" x2="12" y2="12"/><line x1="8" y1="12" x2="3" y2="12"/><line x1="21" y1="20" x2="16" y2="20"/><line x1="12" y1="20" x2="3" y2="20"/><line x1="14" y1="2" x2="14" y2="6"/><line x1="8" y1="10" x2="8" y2="14"/><line x1="16" y1="18" x2="16" y2="22"/></svg>`,
  user:       `<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M20 21v-2a4 4 0 00-4-4H8a4 4 0 00-4 4v2"/><circle cx="12" cy="7" r="4"/></svg>`,
  download:   `<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M21 15v4a2 2 0 01-2 2H5a2 2 0 01-2-2v-4"/><polyline points="7 10 12 15 17 10"/><line x1="12" y1="15" x2="12" y2="3"/></svg>`,
  logout:     `<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M9 21H5a2 2 0 01-2-2V5a2 2 0 012-2h4"/><polyline points="16 17 21 12 16 7"/><line x1="21" y1="12" x2="9" y2="12"/></svg>`,
  // Asset types (pos-icon, 15px)
  chartUp:    `<svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><polyline points="22 7 13.5 15.5 8.5 10.5 2 17"/><polyline points="16 7 22 7 22 13"/></svg>`,
  layers:     `<svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><polygon points="12 2 2 7 12 12 22 7 12 2"/><polyline points="2 17 12 22 22 17"/><polyline points="2 12 12 17 22 12"/></svg>`,
  coins:      `<svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><line x1="12" y1="1" x2="12" y2="23"/><path d="M17 5H9.5a3.5 3.5 0 000 7h5a3.5 3.5 0 010 7H6"/></svg>`,
  bank:       `<svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><line x1="3" y1="22" x2="21" y2="22"/><line x1="6" y1="18" x2="6" y2="11"/><line x1="10" y1="18" x2="10" y2="11"/><line x1="14" y1="18" x2="14" y2="11"/><line x1="18" y1="18" x2="18" y2="11"/><polygon points="12 2 20 7 4 7"/></svg>`,
  gemSm:      `<svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><polygon points="6 3 18 3 22 9 12 22 2 9"/><line x1="2" y1="9" x2="22" y2="9"/><line x1="12" y1="3" x2="6" y2="9"/><line x1="12" y1="3" x2="18" y2="9"/></svg>`,
  home:       `<svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><path d="M3 9l9-7 9 7v11a2 2 0 01-2 2H5a2 2 0 01-2-2z"/><polyline points="9 22 9 12 15 12 15 22"/></svg>`,
  car:        `<svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><path d="M5 17H3v-5l2-5h14l2 5v5h-2"/><circle cx="7.5" cy="17.5" r="2"/><circle cx="16.5" cy="17.5" r="2"/></svg>`,
  frame:      `<svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><rect x="3" y="3" width="18" height="18" rx="2"/><path d="M3 9h18M9 21V9"/></svg>`,
  box:        `<svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><path d="M21 16V8a2 2 0 00-1-1.73l-7-4a2 2 0 00-2 0l-7 4A2 2 0 003 8v8a2 2 0 001 1.73l7 4a2 2 0 002 0l7-4A2 2 0 0021 16z"/><polyline points="3.27 6.96 12 12.01 20.73 6.96"/><line x1="12" y1="22.08" x2="12" y2="12"/></svg>`,
  // Dashboard card icons (12px)
  pieChart:   `<svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M21.21 15.89A10 10 0 118 2.83"/><path d="M22 12A10 10 0 0012 2v10z"/></svg>`,
};

// ── Asset type / category helpers ─────────────────────────

const ASSET_TYPE_LABELS = { action: 'Action', etf: 'ETF', commodity: 'Or', bond_manual: 'Obligation' };
const ASSET_TYPE_ICONS  = { action: ICONS.chartUp, etf: ICONS.layers, commodity: ICONS.coins, bond_manual: ICONS.bank };
const ASSET_CAT_LABELS  = { bijou: 'Bijou', immo: 'Immobilier', vehicule: 'Véhicule', art: 'Art', metal: 'Métaux précieux', autre: 'Autre' };
const ASSET_CAT_ICONS   = { bijou: ICONS.gemSm, immo: ICONS.home, vehicule: ICONS.car, art: ICONS.frame, metal: ICONS.coins, autre: ICONS.box };

const CHART_COLORS = [
  '#3B82F6','#00D68F','#F59E0B','#FF4757',
  '#a855f7','#06b6d4','#f97316','#84cc16','#ec4899','#14b8a6',
];
