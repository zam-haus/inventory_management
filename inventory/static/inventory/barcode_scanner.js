// Camera barcode scanner in a native <dialog>, reusable on any page.
//
// Include this script with data-ponyfill-src and data-wasm-src pointing at the
// vendored barcode-detector files. Browsers with a native BarcodeDetector for
// the requested formats use it; all others load the ZXing WebAssembly ponyfill
// on first use. Nothing is fetched from third-party servers.
//
// createBarcodeScanner({formats, labels, onDetect}) returns {open, close}.
// Only codes wholly inside the drawn box are read. `onDetect(value, format)`
// returns false for a code scanned already (a duplicate) and 'error' for one it
// cannot use (e.g. a link to another site); the dialog then says so, with its
// own sound, instead of confirming the scan. The list keeps the codes taken; a
// failed last scan shows above them until the next one. `labels` holds the
// page-specific title, hint, added, duplicate and error texts; `{code}` in them
// is replaced by the scanned value. Shared texts come from data-label-*
// attributes of this script's tag. Cameras with a light get a flashlight button.
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

    // What a scan sounds and feels like: a short high beep for a code taken, two
    // lower ones for one scanned already, a low buzz for one that cannot be used.
    const FEEDBACK = {
        added: {tones: [[1200, 0, 0.08]], vibrate: 60},
        duplicate: {tones: [[700, 0, 0.07], [700, 0.12, 0.07]], vibrate: [40, 60, 40]},
        error: {tones: [[220, 0, 0.3, 'square']], vibrate: 250},
    };
    let audio = null;

    // Created (or woken) while the user opens the scanner: browsers only allow sound after a gesture.
    function wakeAudio() {
        try {
            audio = audio || new AudioContext();
            if (audio.state === 'suspended') audio.resume();
        } catch { /* sound is optional */ }
    }

    function feedback(kind) {
        const {tones, vibrate} = FEEDBACK[kind];
        try {
            for (const [frequency, start, length, type = 'sine'] of tones) {
                const oscillator = audio.createOscillator();
                const gain = audio.createGain();
                oscillator.type = type;
                oscillator.frequency.value = frequency;
                gain.gain.value = type === 'square' ? 0.03 : 0.05;
                oscillator.connect(gain).connect(audio.destination);
                oscillator.start(audio.currentTime + start);
                oscillator.stop(audio.currentTime + start + length);
            }
        } catch { /* sound is optional */ }
        if (navigator.vibrate) navigator.vibrate(vibrate);
    }

    const sharedLabels = {
        close: config.labelClose, done: config.labelDone, starting: config.labelStarting, torch: config.labelTorch,
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
        const canvas = document.createElement('canvas');

        function build() {
            dialog = document.createElement('dialog');
            dialog.className = 'barcode-scanner';
            dialog.setAttribute('aria-labelledby', 'barcode-scanner-title');
            dialog.innerHTML = `
                <div class="barcode-scanner-header">
                    <h2 class="fs-5 m-0" id="barcode-scanner-title"></h2>
                    <button type="button" class="btn-close" data-scanner-close></button>
                </div>
                <div class="barcode-scanner-view"><video muted playsinline></video><span class="barcode-scanner-frame" aria-hidden="true"></span><button type="button" class="barcode-scanner-torch" aria-pressed="false" hidden></button></div>
                <p class="barcode-scanner-status" role="status"></p>
                <ol class="barcode-scanner-results"></ol>
                <div class="barcode-scanner-footer"><button type="button" class="btn btn-primary" data-scanner-done></button></div>`;
            document.body.append(dialog);
            parts = {
                video: dialog.querySelector('video'), view: dialog.querySelector('.barcode-scanner-view'),
                frame: dialog.querySelector('.barcode-scanner-frame'), torch: dialog.querySelector('.barcode-scanner-torch'),
                status: dialog.querySelector('.barcode-scanner-status'), results: dialog.querySelector('.barcode-scanner-results'),
            };
            parts.torch.setAttribute('aria-label', labels.torch);
            parts.torch.title = labels.torch;
            parts.torch.addEventListener('click', toggleTorch);
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
            if (stream) stream.getTracks().forEach(track => track.stop());  // the light goes off with it
            stream = null;
            if (parts) {
                parts.video.srcObject = null;
                parts.torch.hidden = true;
                showTorch(false);
            }
        }

        function showTorch(lit) {
            parts.torch.setAttribute('aria-pressed', String(lit));
            parts.torch.replaceChildren(window.appIcon(lit ? 'lightning-charge-fill' : 'lightning-charge'));
        }

        // The flashlight button, for a camera that can switch its light (not every phone browser can tell).
        function offerTorch(track) {
            const capabilities = track.getCapabilities ? track.getCapabilities() : {};
            parts.torch.hidden = !capabilities.torch;
        }

        async function toggleTorch() {
            const track = stream && stream.getVideoTracks()[0];
            if (!track) return;
            const lit = parts.torch.getAttribute('aria-pressed') !== 'true';
            try {
                await track.applyConstraints({advanced: [{torch: lit}]});
                showTorch(lit);
            } catch {
                parts.torch.hidden = true;  // it said it could, but cannot
            }
        }

        // The video's pixels inside the drawn box (the video fills the view, cropped as needed: object-fit cover).
        function inFrame() {
            const {video} = parts;
            const view = parts.view.getBoundingClientRect();
            const frame = parts.frame.getBoundingClientRect();
            const scale = Math.max(view.width / video.videoWidth, view.height / video.videoHeight);
            if (!scale) return null;
            const left = view.left + (view.width - video.videoWidth * scale) / 2;
            const top = view.top + (view.height - video.videoHeight * scale) / 2;
            const x = Math.max(0, (frame.left - left) / scale);
            const y = Math.max(0, (frame.top - top) / scale);
            const width = Math.min(video.videoWidth - x, frame.width / scale);
            const height = Math.min(video.videoHeight - y, frame.height / scale);
            if (width < 1 || height < 1) return null;
            canvas.width = Math.round(width);
            canvas.height = Math.round(height);
            canvas.getContext('2d', {willReadFrequently: true}).drawImage(video, x, y, width, height, 0, 0, canvas.width, canvas.height);
            return canvas;
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
            const result = onDetect(value, format);
            const kind = result === 'error' ? 'error' : result === false ? 'duplicate' : 'added';
            // The codes taken; a failed scan only until the next one, above them
            parts.results.querySelectorAll('.is-duplicate, .is-error').forEach(item => item.remove());
            const item = document.createElement('li');
            item.textContent = value;
            item.className = `is-${kind}`;
            parts.results.prepend(item);
            const taken = parts.results.querySelectorAll('.is-added');
            if (taken.length > 5) taken[taken.length - 1].remove();
            setStatus((labels[kind] || labels.duplicate).replace('{code}', value), kind);
            parts.view.dataset.hit = kind;
            parts.view.classList.remove('is-hit');
            void parts.view.offsetWidth;
            parts.view.classList.add('is-hit');
            feedback(kind);
        }

        async function scan(current, detector) {
            while (current === generation) {
                const image = parts.video.readyState >= 2 && parts.video.videoWidth ? inFrame() : null;
                if (image) {
                    try {
                        for (const code of await detector.detect(image)) {
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
            wakeAudio();
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
                offerTorch(media.getVideoTracks()[0]);
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

    // Why the camera cannot be used here, or null. Denied access is only known
    // after asking, so the scanner dialog explains that one.
    async function unavailableReason() {
        if (!window.isSecureContext) return sharedLabels.insecure;
        if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia) return sharedLabels.noCamera;
        try {
            const devices = await navigator.mediaDevices.enumerateDevices();
            if (!devices.some(device => device.kind === 'videoinput')) return sharedLabels.noCamera;
        } catch { /* unknown: let the scanner try */ }
        return null;
    }

    // Enables a scan button rendered as unavailable (see inventoryActions in
    // actions.js), or keeps it disabled and says why.
    window.setupScanButton = async (button, scanner) => {
        const reason = await unavailableReason();
        if (reason) {
            window.inventoryActions.explain(button, reason);
            return;
        }
        button.addEventListener('click', () => scanner.open());
        window.inventoryActions.enable(button);
    };
})();
