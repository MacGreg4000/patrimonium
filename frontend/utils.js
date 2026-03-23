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

async function apiFetch(url, options = {}) {
  const headers = { 'Content-Type': 'application/json', ...options.headers };
  if (_csrfToken && ['POST','PUT','DELETE','PATCH'].includes((options.method || 'GET').toUpperCase())) {
    headers['X-CSRF-Token'] = _csrfToken;
  }
  const res = await fetch(url, { ...options, headers, credentials: 'include' });
  if (res.status === 401) {
    // Try token refresh
    const refreshed = await fetch('/api/auth/refresh', { method: 'POST', credentials: 'include' });
    if (!refreshed.ok) { showLogin(); throw new Error('Session expirée'); }
    return apiFetch(url, options);
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

// ── Asset type / category helpers ─────────────────────────

const ASSET_TYPE_LABELS = { action: 'Action', etf: 'ETF', commodity: 'Or', bond_manual: 'Obligation' };
const ASSET_TYPE_ICONS  = { action: 'A', etf: 'E', commodity: '✦', bond_manual: 'B' };
const ASSET_CAT_LABELS  = { bijou: 'Bijou', immo: 'Immobilier', vehicule: 'Véhicule', art: 'Art', autre: 'Autre' };
const ASSET_CAT_ICONS   = { bijou: '💎', immo: '🏠', vehicule: '🚗', art: '🎨', autre: '📦' };

const CHART_COLORS = [
  '#3B82F6','#00D68F','#F59E0B','#FF4757',
  '#a855f7','#06b6d4','#f97316','#84cc16','#ec4899','#14b8a6',
];
