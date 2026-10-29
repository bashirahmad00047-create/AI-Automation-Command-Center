/**
 * BashFlow Cloud - Progressive Web App (PWA) Service Worker
 * Version: 1.0.0
 * 
 * Provides offline shell caching, stale-while-revalidate for static assets,
 * network-only guarantees for APIs/auth/webhooks, and rapid background updates.
 */

const CACHE_NAME = 'bashflow-pwa-v1.0.0';

// Core static assets required for the offline application shell
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

// Install Event: Precache app shell and immediately activate
self.addEventListener('install', (event) => {
  event.waitUntil(
    caches.open(CACHE_NAME).then((cache) => {
      // Use addAll with graceful failure for individual non-critical files
      return Promise.allSettled(
        PRECACHE_ASSETS.map((url) =>
          cache.add(url).catch((err) => {
            console.warn('[PWA SW] Precache failed for:', url, err);
          })
        )
      );
    }).then(() => {
      return self.skipWaiting();
    })
  );
});

// Activate Event: Clear obsolete caches and claim clients immediately
self.addEventListener('activate', (event) => {
  event.waitUntil(
    caches.keys().then((cacheNames) => {
      return Promise.all(
        cacheNames.map((name) => {
          if (name !== CACHE_NAME) {
            console.log('[PWA SW] Removing obsolete cache:', name);
            return caches.delete(name);
          }
        })
      );
    }).then(() => {
      return self.clients.claim();
    })
  );
});

// Fetch Event: Intelligent routing based on request destination and URL
self.addEventListener('fetch', (event) => {
  const request = event.request;
  const url = new URL(request.url);

  // 1. Non-GET requests (POST, PUT, DELETE) must ALWAYS bypass cache and hit network
  if (request.method !== 'GET') {
    return;
  }

  // 2. Dynamic APIs, Webhooks, Auth, and Bridge endpoints must NEVER be cached
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
    // Network-only for live dynamic data
    event.respondWith(
      fetch(request).catch(() => {
        return new Response(
          JSON.stringify({
            error: 'Offline: Network unavailable for live API dispatch.',
            offline: true
          }),
          {
            status: 503,
            headers: { 'Content-Type': 'application/json' }
          }
        );
      })
    );
    return;
  }

  // 3. Navigation requests (HTML documents like / or /dashboard): Network-First with Cache Fallback
  if (request.mode === 'navigate' || request.destination === 'document') {
    event.respondWith(
      fetch(request)
        .then((networkResponse) => {
          if (networkResponse && networkResponse.status === 200) {
            const responseClone = networkResponse.clone();
            caches.open(CACHE_NAME).then((cache) => {
              cache.put(request, responseClone);
            });
          }
          return networkResponse;
        })
        .catch(async () => {
          // If network is offline, retrieve from cache or serve shell
          const cachedResponse = await caches.match(request);
          if (cachedResponse) return cachedResponse;
          return caches.match('/');
        })
    );
    return;
  }

  // 4. Static assets (CSS, JS, Fonts, Images): Stale-While-Revalidate
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
              const responseClone = networkResponse.clone();
              caches.open(CACHE_NAME).then((cache) => {
                cache.put(request, responseClone);
              });
            }
            return networkResponse;
          })
          .catch(() => {
            // Network failed, nothing to do if already cached
          });

        // Return cached version immediately if present, otherwise await network
        return cachedResponse || fetchPromise;
      })
    );
    return;
  }

  // Default: Network with cache fallback
  event.respondWith(
    caches.match(request).then((cached) => {
      return cached || fetch(request);
    })
  );
});
