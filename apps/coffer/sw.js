/* Offline shell for Coffer. Scope: /deep/apps/coffer/ */
var CACHE = 'coffer-v2';
var PRECACHE = [
  "./",
  "../icons/coffer-192.png",
  "../icons/coffer-512.png",
  "../icons/coffer-512-maskable.png",
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
          /* Only this copy's own older caches. The sibling apps share an
             origin, so a blanket delete would wipe their offline copies — and
             so does the same app served from the Apps repo, which uses the
             'pwa-coffer-' prefix precisely so the two never delete each
             other's. Keep this prefix bare. */
          if (k === CACHE) return null;
          return k.indexOf('coffer-') === 0 ? caches.delete(k) : null;
        }));
      })
      .then(function () { return self.clients.claim(); })
  );
});

self.addEventListener('fetch', function (e) {
  var req = e.request;
  if (req.method !== 'GET') return;
  var url = new URL(req.url);

  if (url.origin !== self.location.origin) return;

  // The app itself is network-first: cache-first on the HTML meant a shipped
  // change could sit unseen behind a stale copy for days, which is exactly
  // what happened. Online you always get the current app; offline you get the
  // last good one. Everything else stays cache-first, because it is small,
  // unchanging and wanted instantly.
  var isDoc = req.mode === 'navigate' ||
              (req.headers.get('accept') || '').indexOf('text/html') > -1;

  if (isDoc) {
    e.respondWith(
      fetch(req).then(function (res) {
        if (res && res.ok) {
          var copy = res.clone();
          caches.open(CACHE).then(function (c) { c.put(req, copy); });
        }
        return res;
      }).catch(function () {
        return caches.match(req).then(function (hit) {
          return hit || caches.match('./');
        });
      })
    );
    return;
  }

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
