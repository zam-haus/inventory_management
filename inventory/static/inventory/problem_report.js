// "Report a problem" (problem_report_modal.html): [data-problem-report-open] opens the dialog instead of the page
// /problem/, the fallback without JavaScript. The visible part of the page is captured as it was when the dialog
// opened and sent with the description, the address and what problem_report_log.js noticed in this tab. The user can
// mark the problem on it: a tap circles a spot, dragging circles an area; the marks are drawn into the picture sent.
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
    const shot = modalElement.querySelector('[data-problem-report-shot]');
    const preview = modalElement.querySelector('[data-problem-report-preview]');
    const unmark = modalElement.querySelector('[data-problem-report-unmark]');
    const CAPTURE_TIMEOUT = 15000;
    const SPOT = 28;  // radius of a tapped mark, in pixels of the page
    const TAP = 8;  // moving less than this (pixels on the screen) is a tap

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
    let picture = null;  // the screenshot as image, drawn under the marks
    let pageScale = 1;  // pixels of the picture per pixel of the page
    let marks = [];  // ellipses {x, y, rx, ry} in pixels of the picture, and what is there on the page
    let drawing = null;  // the mark being drawn: {start, mark, pointer}

    function draw() {
        const context = preview.getContext('2d');
        context.drawImage(picture, 0, 0);
        const width = Math.max(3, 3 * pageScale);
        for (const {x, y, rx, ry} of [...marks, ...(drawing ? [drawing.mark] : [])]) {
            context.beginPath();
            context.ellipse(x, y, Math.max(rx, width), Math.max(ry, width), 0, 0, 2 * Math.PI);
            context.lineWidth = width * 2;  // a light edge, so that the mark stands out on dark parts, too
            context.strokeStyle = 'rgba(255, 255, 255, .85)';
            context.stroke();
            context.lineWidth = width;
            context.strokeStyle = '#dc3545';
            context.stroke();
        }
        unmark.hidden = !marks.length;
    }

    async function showPicture(blob) {
        picture = await createImageBitmap(blob);
        preview.width = picture.width;
        preview.height = picture.height;
        pageScale = picture.width / document.documentElement.clientWidth;
        draw();
    }

    // A point of the picture from a pointer event on it.
    function at(event) {
        const box = preview.getBoundingClientRect();
        return {x: (event.clientX - box.left) * preview.width / box.width,
            y: (event.clientY - box.top) * preview.height / box.height};
    }

    // What the page shows at a point of the picture, for the admins: e.g. 'button.btn "Save"'. The page is still
    // where it was when the screenshot was taken; the dialog over it is skipped.
    function shownAt(x, y) {
        const element = document.elementsFromPoint(x / pageScale, y / pageScale).find(found =>
            !modalElement.contains(found) && !found.matches('.modal-backdrop'));
        if (!element) return '';
        const classes = [...element.classList].slice(0, 2).map(name => `.${name}`).join('');
        const text = (element.innerText || element.getAttribute('aria-label') || element.getAttribute('alt') || '')
            .replace(/\s+/g, ' ').trim();
        const name = `${element.localName}${element.id ? `#${element.id}` : ''}${classes}`;
        return text ? `${name} "${text.length > 60 ? `${text.slice(0, 60)}…` : text}"` : name;
    }

    preview.addEventListener('pointerdown', event => {
        if (!picture || event.button !== 0) return;
        event.preventDefault();
        preview.setPointerCapture(event.pointerId);
        const start = at(event);
        drawing = {start, pointer: event.pointerId, screen: [event.clientX, event.clientY],
            mark: {x: start.x, y: start.y, rx: SPOT * pageScale, ry: SPOT * pageScale}};
        draw();
    });
    preview.addEventListener('pointermove', event => {
        if (drawing?.pointer !== event.pointerId) return;
        const [screenX, screenY] = drawing.screen;
        if (Math.hypot(event.clientX - screenX, event.clientY - screenY) < TAP) return;
        const {start} = drawing;
        const end = at(event);
        drawing.mark = {x: (start.x + end.x) / 2, y: (start.y + end.y) / 2,
            rx: Math.abs(end.x - start.x) / 2, ry: Math.abs(end.y - start.y) / 2};
        draw();
    });
    function finish(event) {
        if (drawing?.pointer !== event.pointerId) return;
        const {mark} = drawing;
        drawing = null;
        if (event.type === 'pointerup') marks.push({...mark, shows: shownAt(mark.x, mark.y)});
        draw();
    }
    preview.addEventListener('pointerup', finish);
    preview.addEventListener('pointercancel', finish);
    unmark.addEventListener('click', () => {
        marks = [];
        draw();
    });

    // The picture to send: the screenshot as taken, or with the marks drawn into it.
    async function pictureToSend() {
        const blob = await screenshot;
        if (!blob || !marks.length) return blob;
        return new Promise(resolve => preview.toBlob(marked => resolve(marked || blob), 'image/jpeg', 0.85));
    }

    function capture() {
        status.textContent = status.dataset.taking;
        screenshotProblem = '';
        const attempt = Promise.race([
            takeScreenshot(),
            new Promise((_, reject) => setTimeout(() => reject(new Error('took too long')), CAPTURE_TIMEOUT)),
        ]);
        const current = attempt.then(async blob => {
            if (screenshot !== current) return blob;  // the dialog was closed meanwhile
            await showPicture(blob);
            shot.hidden = !withScreenshot.checked;
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

    withScreenshot.addEventListener('change', () => { shot.hidden = !withScreenshot.checked || !picture; });

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
            // What the page shows where the problem was marked.
            ...(marks.length ? {marked: marks.map(mark => mark.shows || '?').join('; ')} : {}),
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
            const blob = withScreenshot.checked ? await pictureToSend() : null;
            if (blob) data.set('screenshot', blob, 'screenshot.jpg');
            const state = blob ? (marks.length ? `attached, ${marks.length} marked` : 'attached')
                : withScreenshot.checked ? `failed: ${screenshotProblem}` : 'left out';
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
        picture?.close();
        picture = null;
        marks = [];
        drawing = null;
        preview.width = preview.height = 0;
        shot.hidden = true;
        unmark.hidden = true;
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
