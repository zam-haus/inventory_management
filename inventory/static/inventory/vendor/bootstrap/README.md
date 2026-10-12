# Bootstrap (vendored)

Served locally instead of from jsDelivr, so pages need no third party and keep
working behind the offline page's service worker. `BOOTSTRAP5` in
`imzam/settings.py` points django-bootstrap5 here.

| File | Source | Version |
|---|---|---|
| `bootstrap.min.css` | npm `bootstrap`, `dist/css/bootstrap.min.css` | 5.3.8 |
| `bootstrap.bundle.min.js` | npm `bootstrap`, `dist/js/bootstrap.bundle.min.js` | 5.3.8 |

The integrity hashes in `BOOTSTRAP5` must match the files; after an update, compute
them with `openssl dgst -sha384 -binary <file> | openssl base64 -A`.

License: MIT (`LICENSE`).
