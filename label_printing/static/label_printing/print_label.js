// The print dialogs (label_printing/print_dialog.html, one per kind on a page; also the fallback page): which
// label to print (the server picks the printer), each with its preview; labels no printer can print now are
// greyed but may wait for one. Many labels at once must be confirmed. After printing the dialog follows the job
// until the printer reports back, or until a waiting job expires.
(() => {
    if (window.labelPrintDialogs) return;  // each dialog includes this script
    window.labelPrintDialogs = true;
    document.querySelectorAll('[data-label-print-form]').forEach(form => {
        const data = document.getElementById(form.dataset.options);
        if (data) setUp(form, JSON.parse(data.textContent));
    });
})();

function setUp(form, options) {
    const text = form.dataset;
    const modal = form.closest('.modal');
    const fields = {
        location: form.elements.location, copies: form.elements.copies, requestId: form.elements.request_id,
        children: form.elements.children, priced: form.elements.priced, confirm: form.elements.confirm,
    };
    const parts = {
        outcomes: [...form.querySelectorAll('[data-outcome]')],
        qrNote: form.querySelector('[data-qr-note]'),
        waitNote: form.querySelector('[data-wait-note]'),
        confirm: form.querySelector('[data-confirm]'),
        confirmText: form.querySelector('[data-error-for="confirm"]'),
        status: form.querySelector('[data-print-status]'),
        submit: form.querySelector('[data-print-submit]'),
    };
    const submitLabel = parts.submit.querySelector('span');
    // Per device: the label chosen last for each kind (private windows may forbid storage).
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

    const outcome = key => options.outcomes.find(item => item.key === key);
    const chosen = () => outcome(form.querySelector('[name=outcome]:checked')?.value);

    function choose(key) {
        const radio = form.querySelector(`[name=outcome][value="${CSS.escape(key)}"]`);
        if (radio) radio.checked = true;
        update();
    }

    // How many labels it will be: subjects × copies
    function labels() {
        const subjects = (fields.priced?.checked ? options.priced : options.labels)
            + (fields.children?.checked ? options.children : 0);
        return subjects * (parseInt(fields.copies.value, 10) || 1);
    }

    // More than confirm_labels labels must be confirmed; more than max_labels cannot be printed at once.
    function count() {
        const total = labels();
        const ask = total > options.confirm_labels;
        parts.confirm.hidden = !ask;
        if (!ask) fields.confirm.checked = false;
        parts.confirmText.textContent = (total > options.max_labels ? text.labelTooMany : text.labelConfirm)
            .replace('{count}', total).replace('{max}', options.max_labels);
        fields.confirm.disabled = total > options.max_labels;
        return !ask || (total <= options.max_labels && fields.confirm.checked);
    }

    // The button says what will happen: print on a printer, or wait for one (the note says what waiting means).
    function update() {
        const current = chosen();
        parts.outcomes.forEach(card => card.classList.toggle('is-chosen', current && card.dataset.outcome === current.key));
        const waits = Boolean(current && !current.printer && current.can_wait);
        parts.waitNote.hidden = !waits;
        const counted = count();
        parts.submit.disabled = pending || !current || (!current.printer && !current.can_wait) || !counted;
        if (!pending) {
            submitLabel.textContent = !current ? text.labelPrint
                : current.printer ? text.labelPrintOn.replace('{printer}', current.printer)
                    : current.can_wait ? text.labelQueue : text.labelPrint;
        }
    }

    // Previews of the location chosen for an item label (the QR code leads there)
    function previews() {
        parts.outcomes.forEach(card => {
            const image = card.querySelector('img');
            const url = new URL(image.dataset.preview, window.location.href);
            if (fields.location && url.pathname.endsWith('.png') && url.searchParams.has('medium')) {
                url.searchParams.set('location', fields.location.value);
            }
            image.src = url.pathname + url.search;
        });
    }

    // Item labels: where the QR code leads (the item's label ID, with the location as an argument)
    function qrNote() {
        if (!parts.qrNote || !fields.location) return;
        const location = options.locations.find(item => String(item.id) === fields.location.value);
        const fill = template => template.replace('{item}', options.item).replace('{location}', location?.code || '')
            .replace('{id}', options.label_id);
        parts.qrNote.textContent = fill(options.label_id ? (location ? text.labelQrExisting : text.labelQrNoLocation)
            : (location ? text.labelQrNew : text.labelQrNewNoLocation));
    }

    function remember() {
        if (chosen()) storage.set(`outcome:${text.subject}`, chosen().key);
    }

    form.addEventListener('input', event => {
        if (event.target === fields.copies) update();
    });

    form.addEventListener('change', event => {
        if (['outcome', 'children', 'priced', 'confirm', 'copies'].includes(event.target.name)) update();
        if (event.target === fields.location) {
            previews();
            qrNote();
        }
    });

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
                if (form.elements[name].classList) form.elements[name].classList.add('is-invalid');
                target.textContent = message;
                if (name === 'confirm') parts.confirm.hidden = false;
            } else {
                general.push(message);
            }
        });
        if (general.length) showStatus(general.join(' '), 'danger');
    }

    function setBusy(busy) {
        pending = busy;
        update();
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
        const progress = current => (current.status === 'processing' ? text.labelPrinting
            : current.status === 'waiting' ? current.message : text.labelWaiting);
        if (job.finished) {
            showStatus(job.status === 'done' ? text.labelPrinted : job.status === 'sent' ? text.labelSent : job.message,
                job.status === 'done' ? 'success' : job.ok ? 'warning' : 'danger');
            finish();
            return;
        }
        showStatus(progress(job), 'info');
        // A waiting job is followed until it expires, then as long as any job.
        const until = () => (job.expires_at ? Date.parse(job.expires_at) : Date.now()) + 90000;
        const deadline = job.status === 'waiting' ? until() : Date.now() + 90000;
        const poll = async () => {
            try {
                const response = await fetch(options.status_url.replace(/0\.json$/, `${job.id}.json`), {
                    credentials: 'same-origin', headers: {Accept: 'application/json'},
                });
                const current = await response.json();
                if (current.finished) return follow(current);
                showStatus(progress(current), 'info');
            } catch { /* try again */ }
            if (Date.now() > deadline) {
                showStatus(text.labelStillWaiting, 'warning');
                finish();
                return;
            }
            polling = window.setTimeout(poll, job.status === 'waiting' ? 2000 : 1000);
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
        startOver();
        update();
        previews();
        qrNote();
    }

    // The label chosen last, else the first one printable now
    const stored = storage.get(`outcome:${text.subject}`);
    const first = options.outcomes.find(item => item.key === stored) || options.outcomes.find(item => item.printer)
        || options.outcomes[0];
    if (first && !form.querySelector('[name=outcome]:checked')) choose(first.key);
    startOver();
    update();
    if (modal && window.bootstrap) {
        modal.addEventListener('show.bs.modal', open);
        // After creating a location, its page opens the dialog right away (?print=1).
        const url = new URL(window.location.href);
        if (url.searchParams.has('print') && text.subject === 'location') {
            url.searchParams.delete('print');
            window.history.replaceState(window.history.state, '', url);
            window.bootstrap.Modal.getOrCreateInstance(modal).show();
        }
    } else {
        open();
    }
}
