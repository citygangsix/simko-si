/* Simko SI service worker.
   Deliberately small: it only (1) keeps an offline screen and the app icons in a cache and
   (2) shows that screen when a page navigation fails because the device is offline.
   It never caches /api/*, POSTs, media ranges or app JS/CSS, so deploys are never served stale. */
var VERSION = 'simko-sw-20261123-1';
var PRECACHE = ['/offline.html', '/assets/icons/icon-192.png', '/manifest.webmanifest'];

self.addEventListener('install', function (event) {
  event.waitUntil(caches.open(VERSION).then(function (c) { return c.addAll(PRECACHE); }).then(function () { return self.skipWaiting(); }));
});

self.addEventListener('activate', function (event) {
  event.waitUntil(caches.keys().then(function (keys) {
    return Promise.all(keys.filter(function (k) { return k.indexOf('simko-sw-') === 0 && k !== VERSION; }).map(function (k) { return caches.delete(k); }));
  }).then(function () { return self.clients.claim(); }));
});

self.addEventListener('fetch', function (event) {
  var req = event.request;
  if (req.method !== 'GET') return;
  var url = new URL(req.url);
  if (url.origin !== self.location.origin) return;
  if (url.pathname.indexOf('/api/') === 0) return;
  if (req.mode === 'navigate') {
    event.respondWith(fetch(req).catch(function () {
      return caches.match('/offline.html').then(function (r) { return r || Response.error(); });
    }));
    return;
  }
  if (PRECACHE.indexOf(url.pathname) !== -1) {
    event.respondWith(fetch(req).catch(function () { return caches.match(url.pathname); }));
  }
});
