/* Offline shell for the apps in this folder. */
var CACHE = 'apps-v3';
var PRECACHE = [
  "./index.html",
  "./daybook.html",
  "./coffer.html",
  "./kitchen.html",
  "./timesheet.html",
  "./daybook.webmanifest",
  "./coffer.webmanifest",
  "./kitchen.webmanifest",
  "./timesheet.webmanifest",
  "./icons/daybook-192.png",
  "./icons/daybook-512.png",
  "./icons/coffer-192.png",
  "./icons/coffer-512.png",
  "./icons/kitchen-192.png",
  "./icons/kitchen-512.png",
  "./icons/timesheet-192.png",
  "./icons/timesheet-512.png",
  "./icons/apps-192.png"
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
          return k === CACHE ? null : caches.delete(k);
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
