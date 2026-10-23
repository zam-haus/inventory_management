// The print dialog (label_printing/print_dialog.html, also the fallback page): printer → labels → layout,
// a preview, and after printing the job's progress until the printer reports back.
(() => {
    const form = document.querySelector('[data-label-print-form]');
    const data = document.getElementById('label-print-options');
    if (!form || !data) return;
    const options = JSON.parse(data.textContent);
    const text = form.dataset;
    const modal = form.closest('.modal');
    const fields = {
        printer: form.elements.printer, medium: form.elements.medium, layout: form.elements.layout,
        location: form.elements.location, children: form.elements.children, copies: form.elements.copies,
        quality: form.elements.quality,
        requestId: form.elements.request_id,
    };
    const parts = {
        printerStatus: form.querySelector('[data-printer-status]'),
        mediumDetail: form.querySelector('[data-medium-detail]'),
        preview: form.querySelector('[data-preview]'),
        image: form.querySelector('[data-preview-image]'),
        note: form.querySelector('[data-preview-note]'),
        status: form.querySelector('[data-print-status]'),
        submit: form.querySelector('[data-print-submit]'),
    };
    const submitLabel = parts.submit.querySelector('span');
    // Per device: the printer, labels and layout chosen last (private windows may forbid storage).
    const storage = {
        get(key) { try { return window.localStorage.getItem(`label-print:${key}`); } catch { return null; } },
        set(key, value) { try { window.localStorage.setItem(`label-print:${key}`, value); } catch { /* not kept */ } },
    };
    let pending = false;
    let polling = null;

    function newRequestId() {
        if (crypto.randomUUID) return crypto.randomUUID();
        // randomUUID() needs HTTPS; getRandomValues() does not.
        const bytes = crypto.getRandomValues(new Uint8Array(16));
        bytes[6] = (bytes[6] & 0x0f) | 0x40;
        bytes[8] = (bytes[8] & 0x3f) | 0x80;
        const hex = [...bytes].map(byte => byte.toString(16).padStart(2, '0')).join('');
        return [hex.slice(0, 8), hex.slice(8, 12), hex.slice(12, 16), hex.slice(16, 20), hex.slice(20)].join('-');
    }

    function fill(select, items, label, chosen) {
        select.replaceChildren(...items.map(item => {
            const option = new Option(label(item), item.id ?? item.key);
            option.disabled = Boolean(item.unavailable);
            return option;
        }));
        const usable = items.filter(item => !item.unavailable);
        const pick = usable.find(chosen) || usable[0];
        if (pick) select.value = String(pick.id ?? pick.key);
    }

    const printer = () => options.printers.find(p => String(p.id) === fields.printer.value);
    const medium = () => printer()?.media.find(m => String(m.id) === fields.medium.value);
    const layout = () => medium()?.layouts.find(l => l.key === fields.layout.value);

    function choosePrinter() {
        const stored = storage.get('printer');
        fill(fields.printer, options.printers, p => (p.unavailable ? `${p.name} – ${p.unavailable}` : p.name),
            p => String(p.id) === stored || (!stored && p.default));
        chooseMedium();
    }

    function chooseMedium() {
        const current = printer();
        if (!current) return;
        const stored = storage.get(`medium:${current.id}`);
        // A Brother tells which tape is loaded (width and colours): the medium of that tape comes first.
        const sameColors = m => m.colors && current.colors && m.colors[0] === current.colors[0] && m.colors[1] === current.colors[1];
        const loaded = current.tape && (current.media.find(m => m.tape === current.tape && sameColors(m))
            || current.media.find(m => m.tape === current.tape));
        fill(fields.medium, current.media, m => m.name,
            m => (loaded ? m === loaded : String(m.id) === stored || (!stored && m.default)));
        const info = [current.status];
        if (current.tape) info.push(text.labelTape.replace('{width}', current.tape));
        parts.printerStatus.textContent = info.filter(Boolean).join(' · ');
        chooseLayout();
    }

    function chooseLayout() {
        const current = medium();
        if (!current) return;
        parts.mediumDetail.textContent = current.detail || '';
        if (current.quality) fields.quality.value = current.quality;
        const stored = storage.get(`layout:${text.subject}`);
        fill(fields.layout, current.layouts, l => l.name, l => l.key === stored);
        preview();
    }

    let previewTimer = null;
    function preview() {
        window.clearTimeout(previewTimer);
        previewTimer = window.setTimeout(() => {
            const current = layout();
            if (!current) {
                parts.preview.hidden = true;
                return;
            }
            parts.preview.hidden = false;
            if (!current.preview) {
                parts.image.hidden = true;
                parts.image.removeAttribute('src');
                parts.note.textContent = text.labelNoPreview;
                return;
            }
            const query = new URLSearchParams({medium: fields.medium.value, layout: current.key});
            if (fields.location) query.set('location', fields.location.value);
            parts.image.hidden = false;
            parts.image.src = `${options.preview_url}?${query}`;
            parts.note.textContent = current.labelary ? text.labelLabelary
                : text.subject === 'item' ? text.labelPreviewNewId : '';
        }, 150);
    }
    parts.image.addEventListener('error', () => {
        parts.image.hidden = true;
        parts.note.textContent = text.labelPreviewFailed;
    });

    function remember() {
        storage.set('printer', fields.printer.value);
        storage.set(`medium:${fields.printer.value}`, fields.medium.value);
        storage.set(`layout:${text.subject}`, fields.layout.value);
    }

    fields.printer.addEventListener('change', chooseMedium);
    fields.medium.addEventListener('change', chooseLayout);
    fields.layout.addEventListener('change', preview);
    fields.location?.addEventListener('change', preview);

    function showStatus(message, kind) {
        parts.status.hidden = !message;
        parts.status.textContent = message || '';
        parts.status.className = `label-print-status alert alert-${kind || 'info'}`;
    }

    function clearErrors() {
        form.querySelectorAll('.is-invalid').forEach(field => field.classList.remove('is-invalid'));
        form.querySelectorAll('[data-error-for]').forEach(error => { error.textContent = ''; });
    }

    function showErrors(errors) {
        const general = [];
        Object.entries(errors).forEach(([name, list]) => {
            const message = list.map(error => error.message).join(' ');
            const target = form.querySelector(`[data-error-for="${name}"]`);
            if (target && form.elements[name]) {
                form.elements[name].classList.add('is-invalid');
                target.textContent = message;
            } else {
                general.push(message);
            }
        });
        if (general.length) showStatus(general.join(' '), 'danger');
    }

    function setBusy(busy) {
        pending = busy;
        parts.submit.disabled = busy;
    }

    function startOver() {
        // A new job from now on; a job that failed may be printed again on purpose.
        fields.requestId.value = newRequestId();
    }

    function follow(job) {
        window.clearTimeout(polling);
        const finish = () => {
            setBusy(false);
            startOver();
            submitLabel.textContent = text.labelAgain;
        };
        if (job.finished) {
            showStatus(job.status === 'done' ? text.labelPrinted : job.status === 'sent' ? text.labelSent : job.message,
                job.status === 'done' ? 'success' : job.ok ? 'warning' : 'danger');
            finish();
            return;
        }
        showStatus(job.status === 'processing' ? text.labelPrinting : text.labelWaiting, 'info');
        const started = Date.now();
        const poll = async () => {
            try {
                const response = await fetch(options.status_url.replace(/0\.json$/, `${job.id}.json`), {
                    credentials: 'same-origin', headers: {Accept: 'application/json'},
                });
                const current = await response.json();
                if (current.finished) return follow(current);
                showStatus(current.status === 'processing' ? text.labelPrinting : text.labelWaiting, 'info');
            } catch { /* try again */ }
            if (Date.now() - started > 90000) {
                showStatus(text.labelStillWaiting, 'warning');
                finish();
                return;
            }
            polling = window.setTimeout(poll, 1000);
        };
        polling = window.setTimeout(poll, 700);
    }

    form.addEventListener('submit', async event => {
        event.preventDefault();
        if (pending) return;
        clearErrors();
        remember();
        setBusy(true);
        showStatus(text.labelWaiting, 'info');
        let result = null;
        try {
            const response = await fetch(form.action, {
                method: 'POST', body: new FormData(form), credentials: 'same-origin',
                headers: {Accept: 'application/json'},
            });
            result = await response.json().catch(() => null);
        } catch {
            showStatus(text.labelNetworkError, 'danger');
            setBusy(false);  // same request ID: a job that did arrive is not printed twice
            return;
        }
        if (result && result.ok) {
            follow(result.job);
            return;
        }
        showStatus('', 'info');
        if (result && result.errors) showErrors(result.errors);
        else showStatus(text.labelError, 'danger');
        setBusy(false);
    });

    function open() {
        if (pending) return;
        clearErrors();
        showStatus('', 'info');
        submitLabel.textContent = text.labelPrint;
        startOver();
        preview();
    }

    choosePrinter();
    startOver();
    if (modal && window.bootstrap) {
        modal.addEventListener('show.bs.modal', open);
        // After creating a location, its page opens the dialog right away (?print=1).
        const url = new URL(window.location.href);
        if (url.searchParams.has('print')) {
            url.searchParams.delete('print');
            window.history.replaceState(window.history.state, '', url);
            window.bootstrap.Modal.getOrCreateInstance(modal).show();
        }
    } else {
        open();
    }
})();
