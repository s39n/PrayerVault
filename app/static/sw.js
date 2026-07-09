"use strict";
// PrayerVault service worker: network-first for the app shell so updates land
// immediately, cache fallback so the shell still opens offline. API calls are
// never intercepted — prayer data always comes from the server.

const CACHE = "prayervault-v3";
const SHELL = [
  "/",
  "/app.js",
  "/manifest.webmanifest",
  "/icon.svg",
  "/veil-left.svg",
  "/veil-right.svg",
  "/icon-192.png",
  "/icon-512.png",
];

self.addEventListener("install", (e) => {
  e.waitUntil(caches.open(CACHE).then((c) => c.addAll(SHELL)));
  self.skipWaiting();
});

self.addEventListener("activate", (e) => {
  e.waitUntil(
    caches.keys()
      .then((keys) => Promise.all(keys.filter((k) => k !== CACHE).map((k) => caches.delete(k))))
      .then(() => self.clients.claim())
  );
});

self.addEventListener("fetch", (e) => {
  const url = new URL(e.request.url);
  if (e.request.method !== "GET" || url.origin !== self.location.origin) return;
  if (url.pathname.startsWith("/api/")) return; // live data only

  e.respondWith(
    fetch(e.request)
      .then((resp) => {
        if (resp.ok) {
          const copy = resp.clone();
          caches.open(CACHE).then((c) => c.put(e.request, copy));
        }
        return resp;
      })
      .catch(() =>
        caches.match(e.request).then((hit) => hit || (e.request.mode === "navigate" ? caches.match("/") : Response.error()))
      )
  );
});
