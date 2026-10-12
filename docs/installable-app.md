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
* **No third parties:** Bootstrap is served from
  `inventory/static/inventory/vendor/bootstrap/` instead of a CDN.

Installing requires HTTPS (or `localhost` during development).
