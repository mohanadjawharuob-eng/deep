# Coffer, in `deep`

This is a **mirror**. Coffer is developed in
[`mohanadjawharuob-eng/Apps`](https://github.com/mohanadjawharuob-eng/Apps)
under `coffer/`, and copied here so the app served from `/deep/apps/coffer/`
stays current for anyone who installed it from this path.

Fix things there, then copy `index.html` across. **Two files are deliberately
not copied:**

- **`manifest.webmanifest`** — its `id` is `/deep/apps/coffer/`, not
  `/Apps/coffer/`. The `id` is what the browser uses to decide whether an
  installed app is the same app; changing it turns an update into a second
  Coffer sitting beside the first.
- **`sw.js`** — its cache is `coffer-vN`, while the Apps copy uses
  `pwa-coffer-vN`. Both repos publish to one GitHub Pages origin, and each
  worker's `activate` deletes every cache carrying its own prefix. The two
  prefixes are kept apart so that neither install can wipe the other's offline
  copy. Bump `coffer-vN` here when you copy a new `index.html` in, or the
  phone keeps serving the old one.

## One origin, one set of data

`…github.io/deep/` and `…github.io/Apps/` are the **same origin**, so both
copies read and write the same `localStorage` key, `coffer.v2`. That is
deliberate — it is why moving the apps out of `deep/apps/` carried every
user's data across untouched — but it has a sharp edge:

> **Never leave an old build of Coffer runnable on this site.** An older
> `load()` does not know about the fields added since, and drops every one of
> them the next time it saves. A stale copy in a folder next door is a way to
> lose grants, allowances, splits, cross-currency transfers and pocket
> currencies by opening the wrong bookmark.

The version this replaced is kept in history, not in a folder. It is the state
of `apps/coffer/` at commit **`369149d`** ("Give each app its own scope so all
four can be installed"), and there is a local tag `coffer-deep-v1` on it:

```
git show 369149d:apps/coffer/index.html > /tmp/coffer-old.html   # read it
git checkout 369149d -- apps/coffer                              # restore it
```

The tag is local only — the credentials these sessions push with accept
branches and refuse tags — so the commit above is the durable reference. To
publish the label yourself: `git push origin coffer-deep-v1`.
