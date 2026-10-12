# Camera scanning

The "Move locations here" page scans the QR codes of location labels, and the
item form scans EAN-13/EAN-8 product barcodes; every scanned code is added to
the respective text field. Browsers with a native `BarcodeDetector` for those
formats use it; all others use the vendored ZXing WebAssembly ponyfill in
`inventory/static/inventory/vendor/barcode-detector/` (about 1 MB, loaded on
first use and served from this site). The camera requires HTTPS (or
`localhost`). Hardware and keyboard-app scanners keep working by typing into
the same fields.
