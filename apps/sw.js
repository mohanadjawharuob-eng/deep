/* Tombstone.
   Replaces the old folder-wide worker, which claimed /deep/apps/ and stopped the
   apps from installing separately. It clears only the caches that worker made
   and then removes itself; each app now ships its own worker in its own
   directory. */
self.addEventListener('install', function () { self.skipWaiting(); });

self.addEventListener('activate', function (e) {
  e.waitUntil(
    caches.keys()
      .then(function (keys) {
        return Promise.all(keys.map(function (k) {
          return k.indexOf('apps-') === 0 ? caches.delete(k) : null;
        }));
      })
      .then(function () { return self.registration.unregister(); })
      .then(function () { return self.clients.claim(); })
  );
});

// Never answer from cache while winding down.
self.addEventListener('fetch', function () {});
