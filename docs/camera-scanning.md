# Camera scanning

Every page has a QR scan button beside the logo in the navbar, also on narrow
screens; the home page (`/`, the [search](search.md)) also has one beside its search
field. Scanning a label opens the link in its QR code, such as a location
page or a label ID. Only links to hosts this site serves are opened, matched like
Django's `ALLOWED_HOSTS` (plus the host the page was loaded from, the label ID hosts
and earlier domains on old labels; `inventory/link_scanner.py`); other QR codes are
shown as "not a link to this inventory". A product barcode (EAN-13, EAN-8) is searched
for, which finds the items with that barcode. The scanner scripts are loaded on every
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

The scanner dialog (`barcode_scanner.js`) works the same everywhere:

* Only codes wholly inside the drawn box are read: each frame is cut to the box before
  the detector sees it, so a code beside the one aimed at is not picked up (and the
  detector has fewer pixels to search).
* Each scan sounds and vibrates: a short high beep for a code taken, two lower beeps for
  a code scanned already (e.g. a location already in the "Move locations here" list), a
  low buzz for a code that cannot be used (a QR code that is not a link to this
  inventory). The box flashes green, grey or red. A page's `onDetect` says which:
  `false` for scanned already, `'error'` for unusable.
* The list below the camera keeps the codes taken (the last five); a failed scan shows
  above them, struck through, until the next scan.
* Where the camera has a light the browser can switch (most phones in Chrome), a
  flashlight button in the corner of the picture turns it on and off; it goes off with the
  camera.
