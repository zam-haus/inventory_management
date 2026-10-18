# Camera scanning

Every page has a QR scan button beside the logo in the navbar, also on narrow
screens; the home page (`/`) also offers **Scan QR code** next to the item and
location search. Scanning a label opens the link in its QR code, such as a location
page or a label ID. Only links to hosts this site serves are opened, matched like
Django's `ALLOWED_HOSTS` (plus the host the page was loaded from, the label ID hosts
and earlier domains on old labels; `inventory/link_scanner.py`); other codes are
shown as "not a link to this inventory". The scanner scripts are loaded on every
page by `templates/base.html` (`link_scanner.js` for these buttons).

Every location search field outside the admin (moving a location or unique item,
item locations, destinations when dissolving, a unique item's location) has a QR scan
button on its right (`inventory.widgets.LocationSelect`, `location_scan.js`): scanning a
location label or a label ID selects that location. The search itself also finds a
pasted or scanner-typed label URL or label ID (`views.filter_locations`). Fields with a
fixed location get no button.

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
