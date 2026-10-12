# Camera scanning

The home page (`/`) has a search field with buttons for the item and the
location search, and **📷 Scan QR code**: scanning a label opens the link in
its QR code, such as a location page or a ZAM ID. Only links to hosts this site
serves are opened, matched like Django's `ALLOWED_HOSTS` (plus the host the page
was loaded from); other codes are shown as "not a link to this inventory".

The "Move locations here" page scans the QR codes of location labels, and the
item form scans EAN-13/EAN-8 product barcodes; every scanned code is added to
the respective text field. Browsers with a native `BarcodeDetector` for those
formats use it; all others use the vendored ZXing WebAssembly ponyfill in
`inventory/static/inventory/vendor/barcode-detector/` (about 1 MB, loaded on
first use and served from this site). The camera requires HTTPS (or
`localhost`). When scanning is impossible, the scan buttons stay visible but
disabled and say why (no JavaScript, no camera, no HTTPS), also for guests: these
are not permission reasons. Hardware and
keyboard-app scanners keep working by typing into the same fields.
