/**
 * BashFlow Cloud - Service Worker (sw.js)
 * Enables PWA installation while safely passing through /api/, /webhooks, and dynamic endpoints.
 */

const CACHE_NAME = 'bashflow-pwa-v1.0.0';

const PRECACHE_ASSETS = [
  '/',
  '/manifest.json',
  '/static/css/style.css?v=2.8.5',
  '/static/js/app.js',
  '/static/img/opsflow-icon.svg',
  '/static/img/icon-192.png',
  '/static/img/icon-512.png',
  '/static/img/icon-180.png',
  '/static/img/icon-maskable-192.png',
  '/static/img/icon-maskable-512.png',
  '/static/img/favicon-32.png',
  '/favicon.ico'
];

self.addEventListener('install', (event) => {
  event.waitUntil(
    caches.open(CACHE_NAME).then((cache) => {
      return Promise.allSettled(
        PRECACHE_ASSETS.map((url) =>
          cache.add(url).catch((err) => {
            console.warn('[PWA SW] Precache skip:', url, err);
          })
        )
      );
    }).then(() => self.skipWaiting())
  );
});

self.addEventListener('activate', (event) => {
  event.waitUntil(
    caches.keys().then((keys) => {
      return Promise.all(
        keys.map((key) => {
          if (key !== CACHE_NAME) {
            return caches.delete(key);
          }
        })
      );
    }).then(() => self.clients.claim())
  );
});

self.addEventListener('fetch', (event) => {
  const request = event.request;
  const url = new URL(request.url);

  // Bypass non-GET requests entirely
  if (request.method !== 'GET') {
    return;
  }

  // Network-only for API calls, webhooks, auth, and dynamic routes
  if (
    url.pathname.startsWith('/api/') ||
    url.pathname.startsWith('/webhooks') ||
    url.pathname.startsWith('/send-message') ||
    url.pathname.startsWith('/send') ||
    url.pathname.startsWith('/login') ||
    url.pathname.startsWith('/logout') ||
    url.pathname.startsWith('/auth') ||
    url.pathname.includes('/proxy') ||
    url.pathname.includes('/media')
  ) {
    event.respondWith(
      fetch(request).catch(() => {
        return new Response(
          JSON.stringify({ error: 'Offline: Network unavailable for live API dispatch.', offline: true }),
          { status: 503, headers: { 'Content-Type': 'application/json' } }
        );
      })
    );
    return;
  }

  // Navigation requests: Network-First with Cache Fallback
  if (request.mode === 'navigate' || request.destination === 'document') {
    event.respondWith(
      fetch(request)
        .then((networkResponse) => {
          if (networkResponse && networkResponse.status === 200) {
            const clone = networkResponse.clone();
            caches.open(CACHE_NAME).then((cache) => cache.put(request, clone));
          }
          return networkResponse;
        })
        .catch(async () => {
          const cached = await caches.match(request);
          if (cached) return cached;
          return caches.match('/');
        })
    );
    return;
  }

  // Static assets: Stale-While-Revalidate
  if (
    url.pathname.startsWith('/static/') ||
    url.hostname.includes('fonts.googleapis.com') ||
    url.hostname.includes('fonts.gstatic.com') ||
    request.destination === 'style' ||
    request.destination === 'script' ||
    request.destination === 'image' ||
    request.destination === 'font'
  ) {
    event.respondWith(
      caches.match(request).then((cachedResponse) => {
        const fetchPromise = fetch(request)
          .then((networkResponse) => {
            if (networkResponse && networkResponse.status === 200) {
              const clone = networkResponse.clone();
              caches.open(CACHE_NAME).then((cache) => cache.put(request, clone));
            }
            return networkResponse;
          })
          .catch(() => {});
        return cachedResponse || fetchPromise;
      })
    );
    return;
  }

  // Fallback: Cache first, then network
  event.respondWith(
    caches.match(request).then((cached) => cached || fetch(request))
  );
});
