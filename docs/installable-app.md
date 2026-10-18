# Installable app

The inventory can be installed as an app (Progressive Web App): Chrome and Edge
offer *Install* in the address bar or menu, Android *Add to home screen*, iOS
Safari *Share → Add to Home Screen*. It then opens in its own window without
the browser's address bar.

* **Manifest:** `/manifest.webmanifest` (`inventory/pwa.py`) names the app, sets
  `/` as start page and points to the icons (see [Logo and icons](branding/README.md)).
  On a dev system (`DEBUG` on) it is called *ZAM-Inventar (dev)* and uses the
  magenta icons, so both can be installed side by side.
* **Offline page:** when a page cannot be loaded at all, a small page says there
  is no connection, offers *Try again* and reloads by itself once the device is
  back online. It is self-contained (inline styles and logo), at `/offline/`.
* **Service worker:** `/sw.js` exists only to show the offline page. It caches
  that page and nothing else; every page still comes from the network, so
  nobody sees outdated stock or another user's internal details. Form
  submissions and other requests are not touched. The cache name follows the
  offline page's content, so browsers update it when the page changes.
* **Portrait only:** the manifest sets `"orientation": "portrait"`, so the
  installed app does not rotate on Android. iOS ignores this for web apps and
  offers no way to lock it; there the app still rotates. Installed apps pick up
  manifest changes only after a while or after being reinstalled.
* **Status bar on iOS:** iOS ignores `theme-color` for installed apps, and from iOS 27
  also `apple-mobile-web-app-status-bar-style`; it paints the status bar itself, with a
  blurred, grey edge towards the page. Workarounds (translucent status bar, fixed or
  sticky elements at the top edge, dark strips) did not help, so there are none: we
  wait for iOS to fix it. The navbar is light (`bg-light`, also `theme-color` and the
  manifest), which suits the dark status bar icons iOS draws.
* **Pull to refresh:** installed apps have no pull-to-refresh of their own; pulling down
  at the top of a page reloads it, with an indicator below the navbar
  (`inventory/static/inventory/pull_refresh.js` and `.css`). Browsers keep theirs.
* **Updates reach the app at once:** static URLs carry a version from the file's content
  (`/static/…/actions.css?v=…`, `inventory/static_versions.py`), so browsers and the
  installed app load a changed stylesheet or script right away instead of a cached copy
  (Safari kept old ones for a long time).
* **No third parties:** Bootstrap is served from
  `inventory/static/inventory/vendor/bootstrap/` instead of a CDN.

Installing requires HTTPS (or `localhost` during development).
