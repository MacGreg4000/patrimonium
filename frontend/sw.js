/* ═══════════════════════════════════════════════
   SERVICE WORKER — Patrimonium PWA
   Stratégie : cache-first pour assets statiques,
               network-first pour les appels API.
   ═══════════════════════════════════════════════ */
'use strict';

const CACHE_NAME = 'patrimonium-v1';

// Assets statiques à mettre en cache lors de l'installation
const STATIC_ASSETS = [
  '/',
  '/static/style.css',
  '/static/utils.js',
  '/static/charts.js',
  '/static/auth.js',
  '/static/dashboard.js',
  '/static/portfolio.js',
  '/static/coffres.js',
  '/static/assets.js',
  '/static/reserves.js',
  '/static/passwords.js',
  '/static/admin.js',
  '/static/app.js',
  '/static/manifest.json',
  '/static/icon-192.png',
  '/static/icon-512.png',
];

// ── Installation : précharge les assets statiques ─────────

self.addEventListener('install', event => {
  event.waitUntil(
    caches.open(CACHE_NAME).then(cache => cache.addAll(STATIC_ASSETS))
  );
  self.skipWaiting();
});

// ── Activation : supprime les anciens caches ──────────────

self.addEventListener('activate', event => {
  event.waitUntil(
    caches.keys().then(keys =>
      Promise.all(
        keys.filter(k => k !== CACHE_NAME).map(k => caches.delete(k))
      )
    )
  );
  self.clients.claim();
});

// ── Fetch : stratégie par type de requête ─────────────────

self.addEventListener('fetch', event => {
  const url = new URL(event.request.url);

  // Ignorer les requêtes non-GET et les extensions de navigateur
  if (event.request.method !== 'GET') return;
  if (!url.protocol.startsWith('http')) return;

  // API calls → network-first (données toujours fraîches)
  if (url.pathname.startsWith('/api/')) {
    event.respondWith(networkFirst(event.request));
    return;
  }

  // Assets statiques → cache-first
  if (url.pathname.startsWith('/static/') || url.pathname === '/') {
    event.respondWith(cacheFirst(event.request));
    return;
  }

  // Tout le reste (SPA routes) → retourne index.html depuis le cache
  event.respondWith(
    caches.match('/').then(cached => cached || fetch(event.request))
  );
});

// ── Stratégies ────────────────────────────────────────────

async function cacheFirst(request) {
  const cached = await caches.match(request);
  if (cached) return cached;
  try {
    const response = await fetch(request);
    if (response.ok) {
      const cache = await caches.open(CACHE_NAME);
      cache.put(request, response.clone());
    }
    return response;
  } catch {
    return new Response('Hors ligne — ressource non disponible.', {
      status: 503,
      headers: { 'Content-Type': 'text/plain; charset=utf-8' },
    });
  }
}

async function networkFirst(request) {
  try {
    const response = await fetch(request);
    return response;
  } catch {
    // En cas d'erreur réseau, on retourne une réponse JSON d'erreur
    return new Response(
      JSON.stringify({ detail: 'Hors ligne — données non disponibles.' }),
      { status: 503, headers: { 'Content-Type': 'application/json' } }
    );
  }
}
