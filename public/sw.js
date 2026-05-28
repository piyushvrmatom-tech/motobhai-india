/* Moto Bhai India — Service Worker v1
 *
 * Strategy:
 *   - Cache-first for the app shell (HTML/CSS/JS/icons) — so the planner
 *     opens instantly above Rohtang where there is no signal.
 *   - Network-first for /api/* — riders see fresh data when they have signal,
 *     and the cached last itinerary survives offline.
 *   - The most recent itinerary is stashed in IndexedDB by app.js as well;
 *     the SW only caches the API response shape.
 *
 * Versioning: bump SW_VERSION on every shell change. Old caches are pruned
 * on `activate`.
 */
const SW_VERSION = "v1.0.0";
const SHELL_CACHE = `mb-shell-${SW_VERSION}`;
const API_CACHE = `mb-api-${SW_VERSION}`;

const SHELL_ASSETS = [
  "/",
  "/index.html",
  "/share.html",
  "/manifest.json",
  "/icon.svg",
  "/assets/css/app.css",
  "/assets/js/app.js",
  "/assets/js/api.js",
  // Fonts are loaded from Google; we let the browser handle their cache.
];

const API_HOSTS = ["motobhai-api.onrender.com"];

self.addEventListener("install", (event) => {
  event.waitUntil(
    caches
      .open(SHELL_CACHE)
      .then((cache) => cache.addAll(SHELL_ASSETS))
      .then(() => self.skipWaiting())
      .catch((err) => console.warn("[sw] shell precache partial:", err))
  );
});

self.addEventListener("activate", (event) => {
  event.waitUntil(
    caches.keys().then((keys) =>
      Promise.all(
        keys
          .filter((k) => k.startsWith("mb-") && k !== SHELL_CACHE && k !== API_CACHE)
          .map((k) => caches.delete(k))
      )
    ).then(() => self.clients.claim())
  );
});

self.addEventListener("fetch", (event) => {
  const req = event.request;
  if (req.method !== "GET") return;

  const url = new URL(req.url);

  // ─── API: network-first, fall back to cached last response ─────────
  if (API_HOSTS.includes(url.hostname)) {
    // Only cache safe reads — never POSTs, never /api/log
    if (url.pathname.startsWith("/api/share/") || url.pathname === "/api/motorcycles") {
      event.respondWith(networkFirst(req, API_CACHE));
    }
    return; // POST /api/plan etc → no caching, default network behaviour
  }

  // ─── Same-origin: cache-first ──────────────────────────────────────
  if (url.origin === self.location.origin) {
    event.respondWith(cacheFirst(req, SHELL_CACHE));
  }
});

async function cacheFirst(req, cacheName) {
  const cache = await caches.open(cacheName);
  const cached = await cache.match(req);
  if (cached) {
    // Refresh in background.
    fetch(req).then((res) => {
      if (res && res.ok) cache.put(req, res.clone());
    }).catch(() => {});
    return cached;
  }
  try {
    const res = await fetch(req);
    if (res && res.ok) cache.put(req, res.clone());
    return res;
  } catch (err) {
    // Last resort: return the cached index for navigation requests.
    if (req.mode === "navigate") {
      const fallback = await cache.match("/index.html");
      if (fallback) return fallback;
    }
    throw err;
  }
}

async function networkFirst(req, cacheName) {
  const cache = await caches.open(cacheName);
  try {
    const res = await fetch(req);
    if (res && res.ok) cache.put(req, res.clone());
    return res;
  } catch (err) {
    const cached = await cache.match(req);
    if (cached) return cached;
    throw err;
  }
}

// Allow app.js to trigger an immediate update.
self.addEventListener("message", (event) => {
  if (event.data === "SKIP_WAITING") self.skipWaiting();
});
