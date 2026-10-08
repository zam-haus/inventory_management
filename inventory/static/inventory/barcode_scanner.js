// Camera barcode scanner in a native <dialog>, reusable on any page.
//
// Include this script with data-ponyfill-src and data-wasm-src pointing at the
// vendored barcode-detector files. Browsers with a native BarcodeDetector for
// the requested formats use it; all others load the ZXing WebAssembly ponyfill
// on first use. Nothing is fetched from third-party servers.
//
// createBarcodeScanner({formats, labels, onDetect}) returns {open, close}.
// `onDetect(value, format)` returns false for codes it ignores (for example
// duplicates); the dialog then says so instead of confirming the scan.
// `labels` holds the page-specific title, hint, added and duplicate texts;
// `{code}` in added and duplicate is replaced by the scanned value. Shared
// texts come from data-label-* attributes of this script's tag.
(() => {
    const config = document.currentScript.dataset;
    const SCAN_INTERVAL = 120;
    // The same code in front of the camera is reported once per this period.
    const REPEAT_DELAY = 2500;
    const detectors = new Map();

    function loadScript(src) {
        return new Promise((resolve, reject) => {
            const script = document.createElement('script');
            script.src = src;
            script.onload = resolve;
            script.onerror = () => reject(new Error(`Could not load ${src}`));
            document.head.append(script);
        });
    }

    async function createDetector(formats) {
        if ('BarcodeDetector' in window) {
            try {
                const supported = await window.BarcodeDetector.getSupportedFormats();
                if (formats.every(format => supported.includes(format))) return new window.BarcodeDetector({formats});
            } catch { /* fall back to the ponyfill */ }
        }
        if (!window.BarcodeDetectionAPI) await loadScript(config.ponyfillSrc);
        const api = window.BarcodeDetectionAPI;
        // Serve the WebAssembly from this site instead of the default CDN. It is
        // loaded while the camera starts; a failed download surfaces here
        // instead of silently failing every frame.
        await api.prepareZXingModule({
            overrides: {locateFile: (path, prefix) => (path.endsWith('.wasm') ? config.wasmSrc : prefix + path)},
            fireImmediately: true,
        });
        return new api.BarcodeDetector({formats});
    }

    function detectorFor(formats) {
        const key = formats.join(',');
        if (!detectors.has(key)) {
            const promise = createDetector(formats);
            // A failed attempt (e.g. offline) may be retried next time.
            promise.catch(() => detectors.delete(key));
            detectors.set(key, promise);
        }
        return detectors.get(key);
    }

    function beep() {
        try {
            const audio = beep.context || (beep.context = new AudioContext());
            const oscillator = audio.createOscillator();
            const gain = audio.createGain();
            oscillator.frequency.value = 1200;
            gain.gain.value = 0.05;
            oscillator.connect(gain).connect(audio.destination);
            oscillator.start();
            oscillator.stop(audio.currentTime + 0.08);
        } catch { /* sound is optional */ }
    }

    const sharedLabels = {
        close: config.labelClose, done: config.labelDone, starting: config.labelStarting,
        denied: config.labelDenied, noCamera: config.labelNoCamera,
        insecure: config.labelInsecure, unavailable: config.labelUnavailable,
    };

    window.createBarcodeScanner = ({formats, labels: pageLabels, onDetect}) => {
        const labels = {...sharedLabels, ...pageLabels};
        let dialog = null;
        let parts = null;
        let stream = null;
        let generation = 0;
        const recent = new Map();

        function build() {
            dialog = document.createElement('dialog');
            dialog.className = 'barcode-scanner';
            dialog.setAttribute('aria-labelledby', 'barcode-scanner-title');
            dialog.innerHTML = `
                <div class="barcode-scanner-header">
                    <h2 class="fs-5 m-0" id="barcode-scanner-title"></h2>
                    <button type="button" class="btn-close" data-scanner-close></button>
                </div>
                <div class="barcode-scanner-view"><video muted playsinline></video><span class="barcode-scanner-frame" aria-hidden="true"></span></div>
                <p class="barcode-scanner-status" role="status"></p>
                <ol class="barcode-scanner-results"></ol>
                <div class="barcode-scanner-footer"><button type="button" class="btn btn-primary" data-scanner-done></button></div>`;
            document.body.append(dialog);
            parts = {
                video: dialog.querySelector('video'), view: dialog.querySelector('.barcode-scanner-view'),
                status: dialog.querySelector('.barcode-scanner-status'), results: dialog.querySelector('.barcode-scanner-results'),
            };
            dialog.querySelector('#barcode-scanner-title').textContent = labels.title;
            dialog.querySelector('[data-scanner-close]').setAttribute('aria-label', labels.close);
            dialog.querySelector('[data-scanner-done]').textContent = labels.done;
            dialog.querySelectorAll('[data-scanner-close], [data-scanner-done]').forEach(button => button.addEventListener('click', close));
            // Escape closes right away; the close event itself arrives later.
            dialog.addEventListener('cancel', event => {
                event.preventDefault();
                close();
            });
            dialog.addEventListener('close', stop);
        }

        function setStatus(text, kind = '') {
            parts.status.textContent = text;
            parts.status.dataset.kind = kind;
        }

        function stop() {
            generation += 1;
            if (stream) stream.getTracks().forEach(track => track.stop());
            stream = null;
            if (parts) parts.video.srcObject = null;
        }

        function close() {
            stop();
            if (dialog && dialog.open) dialog.close();
        }

        function report(value, format) {
            const now = Date.now();
            if (now - (recent.get(value) || 0) < REPEAT_DELAY) {
                recent.set(value, now);
                return;
            }
            recent.set(value, now);
            const accepted = onDetect(value, format) !== false;
            const item = document.createElement('li');
            item.textContent = value;
            item.className = accepted ? 'is-added' : 'is-duplicate';
            parts.results.prepend(item);
            while (parts.results.children.length > 5) parts.results.lastElementChild.remove();
            setStatus((accepted ? labels.added : labels.duplicate).replace('{code}', value), accepted ? 'added' : 'duplicate');
            parts.view.classList.remove('is-hit');
            void parts.view.offsetWidth;
            parts.view.classList.add('is-hit');
            if (accepted) {
                beep();
                if (navigator.vibrate) navigator.vibrate(60);
            }
        }

        async function scan(current, detector) {
            while (current === generation) {
                if (parts.video.readyState >= 2 && parts.video.videoWidth) {
                    try {
                        for (const code of await detector.detect(parts.video)) {
                            if (current !== generation) return;
                            report(code.rawValue, code.format);
                        }
                    } catch { /* a single unreadable frame is not an error */ }
                }
                await new Promise(resolve => window.setTimeout(resolve, SCAN_INTERVAL));
            }
        }

        async function open() {
            if (!dialog) build();
            if (!dialog.open) dialog.showModal();
            stop();
            const current = generation;
            parts.results.replaceChildren();
            recent.clear();
            parts.view.hidden = false;
            setStatus(labels.starting);
            if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia) {
                parts.view.hidden = true;
                setStatus(window.isSecureContext ? labels.noCamera : labels.insecure, 'error');
                return;
            }
            const detecting = detectorFor(formats);
            try {
                const media = await navigator.mediaDevices.getUserMedia({
                    audio: false,
                    video: {facingMode: {ideal: 'environment'}, width: {ideal: 1280}, height: {ideal: 720}},
                });
                if (current !== generation) {
                    media.getTracks().forEach(track => track.stop());
                    return;
                }
                stream = media;
                parts.video.srcObject = media;
                await parts.video.play().catch(() => {});
            } catch (error) {
                if (current !== generation) return;
                parts.view.hidden = true;
                const denied = error && (error.name === 'NotAllowedError' || error.name === 'SecurityError');
                setStatus(denied ? labels.denied : labels.noCamera, 'error');
                return;
            }
            let detector;
            try {
                detector = await detecting;
            } catch {
                if (current !== generation) return;
                stop();
                parts.view.hidden = true;
                setStatus(labels.unavailable, 'error');
                return;
            }
            if (current !== generation) return;
            setStatus(labels.hint);
            scan(current, detector);
        }

        return {open, close};
    };
})();
