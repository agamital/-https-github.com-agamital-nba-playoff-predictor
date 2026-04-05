const CACHE_NAME = 'nba-predictor-v1';
const API_CACHE  = 'nba-api-v1';

// App shell files to cache on install
const SHELL = [
  '/',
  '/index.html',
];

// ── Install: cache app shell ────────────────────────────────────────────────
self.addEventListener('install', event => {
  event.waitUntil(
    caches.open(CACHE_NAME)
      .then(cache => cache.addAll(SHELL))
      .then(() => self.skipWaiting())
  );
});

// ── Activate: remove old caches ─────────────────────────────────────────────
self.addEventListener('activate', event => {
  event.waitUntil(
    caches.keys().then(keys =>
      Promise.all(
        keys
          .filter(k => k !== CACHE_NAME && k !== API_CACHE)
          .map(k => caches.delete(k))
      )
    ).then(() => self.clients.claim())
  );
});

// ── App Badge API ────────────────────────────────────────────────────────────
// The page posts { type:'SET_BADGE', count } whenever the missing-picks count
// changes.  Setting the badge from the service worker context makes it persist
// on the home-screen icon even when the app is closed / backgrounded.
self.addEventListener('message', event => {
  if (event.data?.type !== 'SET_BADGE') return;
  const n = Number(event.data.count) || 0;
  if (n > 0) {
    navigator.setAppBadge?.(n).catch(() => {});
  } else {
    navigator.clearAppBadge?.().catch(() => {});
  }
});

// Clear badge when the user taps any notification and opens the app.
self.addEventListener('notificationclick', event => {
  event.notification.close();
  navigator.clearAppBadge?.().catch(() => {});
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
