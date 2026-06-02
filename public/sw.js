// MotoBhai Service Worker v1
const CACHE_NAME = 'motobhai-v13';
const STATIC_ASSETS = [
  '/',
  '/index.html',
  '/manifest.json'
];

// Install: cache shell
self.addEventListener('install', (e) => {
  e.waitUntil(
    caches.open(CACHE_NAME).then(cache => cache.addAll(STATIC_ASSETS))
  );
  self.skipWaiting();
});

// Activate: clean old caches
self.addEventListener('activate', (e) => {
  e.waitUntil(
    caches.keys().then(keys =>
      Promise.all(keys.filter(k => k !== CACHE_NAME).map(k => caches.delete(k)))
    )
  );
  self.clients.claim();
});

// Fetch: network-first for API/dynamic, cache-first for static
self.addEventListener('fetch', (e) => {
  const url = new URL(e.request.url);

  // Skip non-GET
  if (e.request.method !== 'GET') return;

  // Allow caching of local origin, Iconify SVG API, and Google Fonts
  const isAllowedCrossOrigin = url.origin.includes('api.iconify.design') || 
                               url.origin.includes('fonts.googleapis.com') || 
                               url.origin.includes('fonts.gstatic.com');
  
  if (url.origin !== location.origin && !isAllowedCrossOrigin) return;

  e.respondWith(
    fetch(e.request)
      .then(response => {
        const clone = response.clone();
        caches.open(CACHE_NAME).then(cache => {
          cache.put(e.request, clone);
          // Limit cache size
          cache.keys().then(keys => {
            if (keys.length > 100) {
              cache.delete(keys[0]);
            }
          });
        });
        return response;
      })
      .catch(() => caches.match(e.request))
  );
});
