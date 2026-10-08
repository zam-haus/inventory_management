# barcode-detector (vendored)

Barcode Detection API ponyfill backed by ZXing-C++ compiled to WebAssembly.
Used by `inventory/static/inventory/barcode_scanner.js` when the browser has
no native `BarcodeDetector` for the requested formats.

| File | Source | Version |
|---|---|---|
| `barcode-detector-ponyfill.js` | npm `barcode-detector`, `dist/iife/ponyfill.js` | 3.2.2 |
| `zxing_reader.wasm` | npm `zxing-wasm`, `dist/reader/zxing_reader.wasm` | 3.1.3 (pinned by barcode-detector 3.2.2) |

The ponyfill checks the WASM file against its built-in SHA-256
(`2ebda08a93eea3efcd8399cda6b276e6a0b1de4fec60b4d8988a047de4c6d1ba`), so both
files must be updated together. The page points the ponyfill at the local
`.wasm` file instead of the default jsDelivr URL.

Licenses: barcode-detector and zxing-wasm are MIT (`LICENSE.barcode-detector`,
`LICENSE.zxing-wasm`); ZXing-C++ is Apache-2.0 (`LICENSE.zxing-cpp`).
