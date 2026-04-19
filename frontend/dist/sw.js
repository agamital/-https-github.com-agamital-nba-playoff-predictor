const CACHE_NAME = 'nba-predictor-v1';
const API_CACHE  = 'nba-api-v1';
const DB_NAME    = 'nba-sw-db';
const DB_STORE   = 'badge';
const BADGE_KEY  = 'count';

// App shell files to cache on install
const SHELL = [
  '/',
  '/index.html',
];

// ── IndexedDB helpers ────────────────────────────────────────────────────────
// Tiny promise-based wrapper — no library needed in SW context.

function openDB() {
  return new Promise((resolve, reject) => {
    const req = indexedDB.open(DB_NAME, 1);
    req.onupgradeneeded = e => e.target.result.createObjectStore(DB_STORE);
    req.onsuccess = e => resolve(e.target.result);
    req.onerror   = e => reject(e.target.error);
  });
}

function saveBadgeCount(count) {
  return openDB().then(db => new Promise((resolve, reject) => {
    const tx  = db.transaction(DB_STORE, 'readwrite');
    const req = tx.objectStore(DB_STORE).put(count, BADGE_KEY);
    req.onsuccess = () => resolve();
    req.onerror   = e => reject(e.target.error);
  }));
}

function loadBadgeCount() {
  return openDB().then(db => new Promise((resolve, reject) => {
    const tx  = db.transaction(DB_STORE, 'readonly');
    const req = tx.objectStore(DB_STORE).get(BADGE_KEY);
    req.onsuccess = e => resolve(e.target.result ?? 0);
    req.onerror   = e => reject(e.target.error);
  }));
}

// ── Apply badge using SW-context API ─────────────────────────────────────────
function applyBadge(count) {
  if (count > 0) {
    (self.registration.setAppBadge?.(count) ?? navigator.setAppBadge?.(count))?.catch(() => {});
  } else {
    (self.registration.clearAppBadge?.() ?? navigator.clearAppBadge?.())?.catch(() => {});
  }
}

// ── Install: cache app shell ────────────────────────────────────────────────
self.addEventListener('install', event => {
  event.waitUntil(
    caches.open(CACHE_NAME)
      .then(cache => cache.addAll(SHELL))
      .then(() => self.skipWaiting())
  );
});

// ── Activate: remove old caches, restore persisted badge ───────────────────
self.addEventListener('activate', event => {
  event.waitUntil(
    caches.keys().then(keys =>
      Promise.all(
        keys
          .filter(k => k !== CACHE_NAME && k !== API_CACHE)
          .map(k => caches.delete(k))
      )
    )
    .then(() => self.clients.claim())
    .then(() => loadBadgeCount())
    .then(count => { if (count > 0) applyBadge(count); })
    .catch(() => {})
  );
});

// ── Message: SYNC_BADGE from App.jsx ─────────────────────────────────────────
// App.jsx posts { type: 'SYNC_BADGE', count } via navigator.serviceWorker.ready.
// The SW applies the badge using self.registration.setAppBadge() (persists on the
// home-screen icon even when the app is closed) and saves the count to IndexedDB
// so it can be restored after a browser restart / ColorOS badge clear.
self.addEventListener('message', event => {
  if (event.data?.type !== 'SYNC_BADGE') return;
  const count = Number(event.data.count) || 0;
  applyBadge(count);
  saveBadgeCount(count).catch(() => {});
});

// Clear badge when the user taps any notification and opens the app.
self.addEventListener('notificationclick', event => {
  event.notification.close();
  applyBadge(0);
  saveBadgeCount(0).catch(() => {});
  event.waitUntil(
    clients.matchAll({ type: 'window', includeUncontrolled: true }).then(list => {
      const existing = list.find(c => c.url.startsWith(self.location.origin));
      if (existing) return existing.focus();
      return clients.openWindow('/');
    })
  );
});

// ── Fetch strategy ───────────────────────────────────────────────────────────
self.addEventListener('fetch', event => {
  const { request } = event;
  const url = new URL(request.url);

  // API requests: network-first, fall back to cache
  if (url.pathname.startsWith('/api/')) {
    event.respondWith(
      fetch(request)
        .then(response => {
          if (response.ok) {
            const clone = response.clone();
            caches.open(API_CACHE).then(cache => cache.put(request, clone));
          }
          return response;
        })
        .catch(() => caches.match(request))
    );
    return;
  }

  // Navigation requests: network-first, fall back to /index.html (SPA)
  if (request.mode === 'navigate') {
    event.respondWith(
      fetch(request).catch(() => caches.match('/index.html'))
    );
    return;
  }

  // Static assets: cache-first
  event.respondWith(
    caches.match(request).then(cached => cached || fetch(request))
  );
});
