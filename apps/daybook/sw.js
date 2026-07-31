/* Offline shell for Daybook. Scope: /deep/apps/daybook/ */
var CACHE = 'daybook-v1';
var PRECACHE = [
  "./",
  "../icons/daybook-192.png",
  "../icons/daybook-512.png",
  "../icons/daybook-512-maskable.png",
  "./manifest.webmanifest"
];

self.addEventListener('install', function (e) {
  e.waitUntil(
    caches.open(CACHE)
      // addAll is all-or-nothing; cache individually so one bad entry
      // can't stop the whole app from installing
      .then(function (c) { return Promise.all(PRECACHE.map(function (u) {
        return c.add(u).catch(function () {});
      })); })
      .then(function () { return self.skipWaiting(); })
  );
});

self.addEventListener('activate', function (e) {
  e.waitUntil(
    caches.keys()
      .then(function (keys) {
        return Promise.all(keys.map(function (k) {
          // Only tidy up this app's own older caches. The sibling apps share
          // an origin, so a blanket delete would wipe their offline copies.
          if (k === CACHE) return null;
          return k.indexOf('daybook-') === 0 ? caches.delete(k) : null;
        }));
      })
      .then(function () { return self.clients.claim(); })
  );
});

// Cache first: these apps never change between deploys and must open offline.
// A background refresh keeps the copy current for next time.
self.addEventListener('fetch', function (e) {
  var req = e.request;
  if (req.method !== 'GET') return;
  var url = new URL(req.url);
  if (url.origin !== self.location.origin) return;

  e.respondWith(
    caches.match(req).then(function (hit) {
      var net = fetch(req).then(function (res) {
        if (res && res.ok) {
          var copy = res.clone();
          caches.open(CACHE).then(function (c) { c.put(req, copy); });
        }
        return res;
      }).catch(function () { return hit; });
      return hit || net;
    })
  );
});
