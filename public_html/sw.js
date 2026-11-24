/* Simko SI service worker.
   Deliberately small: it only (1) keeps an offline screen and the app icons in a cache and
   (2) shows that screen when a page navigation fails because the device is offline, and
   (3) shows routine and test alerts sent by Web Push (payload encrypted by the server, RFC 8291).
   It never caches /api/*, POSTs, media ranges or app JS/CSS, so deploys are never served stale. */
var VERSION = 'simko-sw-20261123-2';
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

self.addEventListener('push', function (event) {
  var msg = {};
  try { msg = event.data ? event.data.json() : {}; } catch (e) { msg = { body: event.data ? event.data.text() : '' }; }
  var title = msg.title || 'Simko SI';
  var opts = { body: msg.body || 'You have a new note from Simko SI.', icon: msg.icon || '/assets/icons/icon-192.png', badge: '/assets/icons/icon-192.png', tag: msg.tag || 'simko', data: { url: msg.url || '/' } };
  event.waitUntil(self.registration.showNotification(title, opts).then(function () {
    return self.clients.matchAll({ type: 'window', includeUncontrolled: true });
  }).then(function (list) {
    list.forEach(function (c) { c.postMessage({ type: 'simko-push', title: title, body: opts.body, tag: opts.tag }); });
  }));
});

self.addEventListener('notificationclick', function (event) {
  event.notification.close();
  var url = (event.notification.data && event.notification.data.url) || '/';
  event.waitUntil(self.clients.matchAll({ type: 'window', includeUncontrolled: true }).then(function (list) {
    for (var i = 0; i < list.length; i++) { if ('focus' in list[i]) return list[i].focus(); }
    return self.clients.openWindow(url);
  }));
});
