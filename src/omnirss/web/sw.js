/**
 * OmniRSS Service Worker (sw.js)
 * Provides static asset caching and offline resilience.
 */

const CACHE_NAME = "omnirss-static-v1";
const STATIC_ASSETS = [
  "/",
  "/index.html",
  "/css/tokens.css",
  "/css/layout.css",
  "/css/tree.css",
  "/css/list.css",
  "/css/reader.css",
  "/css/modals.css",
  "/js/app.js",
  "/js/state.js",
  "/js/api_client.js",
  "/js/i18n.js",
  "/js/keybindings.js",
  "/js/components/tree_view.js",
  "/js/components/list_view.js",
  "/js/components/reader_view.js",
  "/js/components/column_picker.js",
  "/js/components/modals.js",
  "/manifest.webmanifest"
];

self.addEventListener("install", (e) => {
  e.waitUntil(
    caches.open(CACHE_NAME).then((cache) => {
      return cache.addAll(STATIC_ASSETS);
    })
  );
  self.skipWaiting();
});

self.addEventListener("activate", (e) => {
  e.waitUntil(
    caches.keys().then((keys) => {
      return Promise.all(
        keys.filter((k) => k !== CACHE_NAME).map((k) => caches.delete(k))
      );
    })
  );
  self.clients.claim();
});

self.addEventListener("fetch", (e) => {
  // Only cache GET requests and non-API requests
  if (e.request.method !== "GET" || e.request.url.includes("/api/")) {
    return;
  }

  e.respondWith(
    caches.match(e.request).then((cached) => {
      return cached || fetch(e.request);
    })
  );
});
