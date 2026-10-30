// "Report a problem" (problem_report_modal.html): [data-problem-report-open] opens the dialog instead of the page
// /problem/, the fallback without JavaScript. The visible part of the page is captured as it was when the dialog
// opened and sent with the description, the address and what problem_report_log.js noticed in this tab.
(() => {
    const modalElement = document.getElementById('problem-report');
    if (!modalElement || typeof bootstrap === 'undefined') return;
    const modal = bootstrap.Modal.getOrCreateInstance(modalElement);
    const form = modalElement.querySelector('form');
    const fields = modalElement.querySelector('[data-problem-report-fields]');
    const done = modalElement.querySelector('[data-problem-report-done]');
    const error = modalElement.querySelector('[data-problem-report-error]');
    const send = modalElement.querySelector('[data-problem-report-send]');
    const cancel = modalElement.querySelector('[data-problem-report-cancel]');
    const close = modalElement.querySelector('[data-problem-report-close]');
    const withScreenshot = modalElement.querySelector('[data-problem-report-with-screenshot]');
    const status = modalElement.querySelector('[data-problem-report-status]');
    const preview = modalElement.querySelector('[data-problem-report-preview]');
    const CAPTURE_TIMEOUT = 15000;

    let library = null;
    function loadLibrary() {
        library ??= new Promise((resolve, reject) => {
            const script = document.createElement('script');
            script.src = modalElement.dataset.screenshotScript;
            script.onload = () => resolve(window.modernScreenshot);
            script.onerror = () => { library = null; reject(new Error('screenshot script not loaded')); };
            document.head.append(script);
        });
        return library;
    }

    // Left out of the screenshot: this dialog and what opening it brings.
    const leftOut = node => !(node instanceof Element) || !(node === modalElement || node.matches(
        '.modal-backdrop, .modal-focus-stand-in, .dropdown-menu.show'));

    // The picture is taken of the page itself, scrolled to the top and shifted by the scroll position. Elements that
    // stick or are fixed to the screen would move with it: they are marked with the shift that puts them back.
    function markScreenElements() {
        const marked = [];
        document.body.querySelectorAll('*').forEach(element => {
            const position = getComputedStyle(element).position;
            if (position !== 'sticky' && position !== 'fixed') return;
            const box = element.getBoundingClientRect();
            if (!box.width || !box.height) return;
            if (position === 'fixed') {
                element.dataset.screenshotFixed = `${box.left + scrollX},${box.top + scrollY},${box.width},${box.height}`;
            } else {
                const inline = element.style.position;
                element.style.position = 'static';
                const natural = element.getBoundingClientRect();
                element.style.position = inline;
                if (natural.left === box.left && natural.top === box.top) return;
                element.dataset.screenshotSticky = `${box.left - natural.left},${box.top - natural.top}`;
            }
            marked.push(element);
        });
        return () => marked.forEach(element => {
            delete element.dataset.screenshotFixed;
            delete element.dataset.screenshotSticky;
        });
    }

    function placeScreenElement(clone) {
        if (!(clone instanceof HTMLElement)) return;
        const {screenshotFixed: fixed, screenshotSticky: sticky} = clone.dataset;
        if (fixed) {
            const [left, top, width, height] = fixed.split(',');
            Object.assign(clone.style, {position: 'absolute', left: `${left}px`, top: `${top}px`, width: `${width}px`,
                height: `${height}px`, right: 'auto', bottom: 'auto', margin: '0', transform: 'none'});
        } else if (sticky) {
            const [left, top] = sticky.split(',');
            Object.assign(clone.style, {position: 'relative', left: `${left}px`, top: `${top}px`});
        }
        delete clone.dataset.screenshotFixed;
        delete clone.dataset.screenshotSticky;
    }

    // A JPEG of the visible part of the page; started before the dialog shows, so it is measured without it.
    async function takeScreenshot() {
        const body = document.body;
        const style = getComputedStyle(body);
        const background = style.backgroundColor === 'rgba(0, 0, 0, 0)' ? '#fff' : style.backgroundColor;
        const width = document.documentElement.clientWidth;
        const height = window.innerHeight;
        const scale = Math.min(window.devicePixelRatio || 1, 2);
        const options = {
            width, height, scale, filter: leftOut, onCloneEachNode: placeScreenElement, timeout: 8000,
            features: {restoreScrollPosition: true},
            // The dialog sets these on the page while it is open.
            // The copy would get the browser's default margin of <body>.
            style: {transform: `translate(${-scrollX}px, ${-scrollY}px)`, minHeight: `${body.scrollHeight}px`,
                margin: style.margin, paddingRight: style.paddingRight, overflow: 'visible'},
        };
        const unmark = markScreenElements();
        try {
            const {domToCanvas} = await loadLibrary();
            const canvas = await domToCanvas(body, options);
            const picture = document.createElement('canvas');
            picture.width = canvas.width;
            picture.height = canvas.height;
            const context = picture.getContext('2d');
            context.fillStyle = background;  // JPEG has no transparency
            context.fillRect(0, 0, picture.width, picture.height);
            context.drawImage(canvas, 0, 0);
            return await new Promise((resolve, reject) => picture.toBlob(
                blob => blob ? resolve(blob) : reject(new Error('no picture')), 'image/jpeg', 0.85));
        } finally {
            unmark();
        }
    }

    let screenshot = null;  // Promise of the picture (a Blob) or null
    let screenshotProblem = '';
    let previewUrl = null;

    function capture() {
        status.textContent = status.dataset.taking;
        screenshotProblem = '';
        const attempt = Promise.race([
            takeScreenshot(),
            new Promise((_, reject) => setTimeout(() => reject(new Error('took too long')), CAPTURE_TIMEOUT)),
        ]);
        const current = attempt.then(blob => {
            if (screenshot !== current) return blob;  // the dialog was closed meanwhile
            previewUrl = URL.createObjectURL(blob);
            preview.src = previewUrl;
            preview.hidden = !withScreenshot.checked;
            status.textContent = '';
            return blob;
        }, problem => {
            screenshotProblem = String(problem?.message || problem);
            if (screenshot === current) {
                status.textContent = status.dataset.failed;
                withScreenshot.checked = false;
                withScreenshot.disabled = true;
            }
            return null;
        });
        screenshot = current;
    }

    withScreenshot.addEventListener('change', () => { preview.hidden = !withScreenshot.checked || !previewUrl; });

    document.addEventListener('click', event => {
        const opener = event.target.closest('[data-problem-report-open]');
        if (!opener) return;
        event.preventDefault();
        capture();
        modal.show(opener);
    });

    function browserContext(screenshotState) {
        const standalone = matchMedia('(display-mode: standalone)').matches || navigator.standalone === true;
        return JSON.stringify({
            title: document.title,
            referrer: document.referrer,
            viewport: `${window.innerWidth}×${window.innerHeight}`,
            screen: `${screen.width}×${screen.height}`,
            pixelRatio: window.devicePixelRatio,
            language: navigator.language,
            timeZone: Intl.DateTimeFormat().resolvedOptions().timeZone,
            clientTime: new Date().toISOString(),
            online: navigator.onLine,
            installedApp: standalone,
            serviceWorker: Boolean(navigator.serviceWorker?.controller),
            screenshot: screenshotState,
            log: window.problemReportLog?.() ?? [],
        });
    }

    function showError(message) {
        error.textContent = message;
        error.hidden = false;
    }

    form.addEventListener('submit', async event => {
        event.preventDefault();
        error.hidden = true;
        send.disabled = true;
        try {
            const data = new FormData(form);
            const blob = withScreenshot.checked ? await screenshot : null;
            if (blob) data.set('screenshot', blob, 'screenshot.jpg');
            const state = blob ? 'attached' : withScreenshot.checked ? `failed: ${screenshotProblem}` : 'left out';
            data.set('url', location.href);
            data.set('browser_context', browserContext(state));
            const response = await fetch(form.action, {method: 'POST', body: data, headers: {Accept: 'application/json'}});
            const answer = await response.json().catch(() => ({}));
            if (!response.ok || !answer.ok) {
                const messages = Object.values(answer.errors || {}).flat().map(problem => problem.message);
                showError([answer.error, ...messages].filter(Boolean).join(' ') || modalElement.dataset.error);
                return;
            }
            done.querySelector('p').textContent = answer.message;
            fields.hidden = true;
            done.hidden = false;
            send.hidden = true;
            cancel.hidden = true;
            close.hidden = false;
            close.focus();
        } catch {
            showError(modalElement.dataset.error);
        } finally {
            send.disabled = false;
        }
    });

    // Closing forgets the report (modals.js resets the fields): the next one starts with a new screenshot.
    form.addEventListener('reset', () => {
        screenshot = null;
        if (previewUrl) URL.revokeObjectURL(previewUrl);
        previewUrl = null;
        preview.removeAttribute('src');
        preview.hidden = true;
        status.textContent = '';
        withScreenshot.disabled = false;
        error.hidden = true;
        fields.hidden = false;
        done.hidden = true;
        send.hidden = false;
        cancel.hidden = false;
        close.hidden = true;
    });
})();
