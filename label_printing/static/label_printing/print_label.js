// The print dialogs (label_printing/print_dialog.html, one per kind on a page; also the fallback page). For one
// subject: which label to print (the server picks the printer), the templates its rules recommend shown, others
// on request; labels no printer can print now are greyed but may wait for one. For several (a location with its
// sub-locations, the items at a location): an overview, a row per label with its best template, each printed as a
// job of its own. After printing the dialog follows the job (or the batch of jobs) until the printers report back,
// or until waiting jobs expire.
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
        children: form.elements.children,
    };
    const parts = {
        single: form.querySelector('[data-single]'),
        overview: form.querySelector('[data-overview]'),
        outcomes: [...form.querySelectorAll('[data-outcome]')],
        rows: [...form.querySelectorAll('[data-row]')],
        pricedOnly: form.querySelector('[data-priced-only]'),
        qrNote: form.querySelector('[data-qr-note]'),
        waitNote: form.querySelector('[data-wait-note]'),
        status: form.querySelector('[data-print-status]'),
        submit: form.querySelector('[data-print-submit]'),
    };
    const submitLabel = parts.submit.querySelector('span');
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
    const overview = () => Boolean(parts.overview) && (!parts.single || Boolean(fields.children?.checked));
    const printing = row => row.querySelector('[type=checkbox]');
    const select = row => row.querySelector('select');
    const wanted = () => parts.rows.filter(row => printing(row).checked && select(row));

    // A row's preview with the label chosen for it: as the printer gets it, else without a printer
    function previewUrl(data, item) {
        if (item.query) return `${data.preview}${data.preview.includes('?') ? '&' : '?'}${item.query}`;
        return data.template_preview.replace('{template}', item.template);
    }

    function rowPreview(row) {
        const image = row.querySelector('img');
        const item = outcome(select(row)?.value);
        if (image && item) image.src = previewUrl(options.rows[Number(row.dataset.row)], item);
    }

    // The button says what will happen: print on a printer, or wait for one (the note says what waiting means);
    // in the overview, how many labels.
    function update() {
        const several = overview();
        if (parts.single) parts.single.hidden = several;
        if (parts.overview) parts.overview.hidden = !several;
        if (several) {
            const rows = wanted();
            const items = rows.map(row => outcome(select(row).value)).filter(Boolean);
            parts.waitNote.hidden = !items.some(item => !item.printer);
            const labels = rows.length * (parseInt(fields.copies.value, 10) || 1);
            parts.submit.disabled = pending || !rows.length || items.some(item => !item.printer && !item.can_wait);
            if (!pending) submitLabel.textContent = text.labelPrintRows.replace('{count}', labels);
            return;
        }
        const current = chosen();
        parts.outcomes.forEach(card => card.classList.toggle('is-chosen', current && card.dataset.outcome === current.key));
        parts.waitNote.hidden = !(current && !current.printer && current.can_wait);
        parts.submit.disabled = pending || !current || (!current.printer && !current.can_wait);
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
            if (fields.location && url.pathname.endsWith('.png')) url.searchParams.set('location', fields.location.value);
            image.src = url.pathname + url.search;
        });
    }

    // Item labels: where the QR code leads (the item's label ID, with the location's code)
    function qrNote() {
        if (!parts.qrNote || !fields.location) return;
        const location = options.locations.find(item => String(item.id) === fields.location.value);
        const fill = template => template.replace('{item}', options.item).replace('{location}', location?.code || '')
            .replace('{id}', options.label_id);
        parts.qrNote.textContent = fill(options.label_id ? (location ? text.labelQrExisting : text.labelQrNoLocation)
            : (location ? text.labelQrNew : text.labelQrNewNoLocation));
    }

    form.addEventListener('input', event => {
        if (event.target === fields.copies) update();
    });

    form.addEventListener('change', event => {
        const row = event.target.closest('[data-row]');
        if (row && event.target.tagName === 'SELECT') rowPreview(row);
        if (event.target === parts.pricedOnly) {
            parts.rows.forEach(entry => {
                if (select(entry)) printing(entry).checked = !parts.pricedOnly.checked || options.rows[Number(entry.dataset.row)].priced;
            });
        }
        if (event.target === fields.location) {
            previews();
            qrNote();
        }
        update();
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

    function finish() {
        setBusy(false);
        startOver();
        submitLabel.textContent = text.labelAgain;
    }

    // Asks `url` again and again until `done(answer)` says the jobs are finished; waiting jobs are followed until
    // they expire, then as long as any job.
    function poll(url, current, show, done) {
        window.clearTimeout(polling);
        const waiting = current.jobs ? current.jobs.filter(job => job.expires_at) : (current.expires_at ? [current] : []);
        const deadline = Math.max(Date.now(), ...waiting.map(job => Date.parse(job.expires_at))) + 90000;
        const ask = async () => {
            try {
                const response = await fetch(url, {credentials: 'same-origin', headers: {Accept: 'application/json'}});
                const answer = await response.json();
                if (answer.finished) return done(answer);
                show(answer);
            } catch { /* try again */ }
            if (Date.now() > deadline) {
                showStatus(text.labelStillWaiting, 'warning');
                finish();
                return;
            }
            polling = window.setTimeout(ask, waiting.length ? 2000 : 1000);
        };
        polling = window.setTimeout(ask, 700);
    }

    function follow(job) {
        const progress = current => (current.status === 'processing' ? text.labelPrinting
            : current.status === 'waiting' ? current.message : text.labelWaiting);
        if (job.finished) {
            showStatus(job.status === 'done' ? text.labelPrinted : job.status === 'sent' ? text.labelSent : job.message,
                job.status === 'done' ? 'success' : job.ok ? 'warning' : 'danger');
            finish();
            return;
        }
        showStatus(progress(job), 'info');
        poll(options.status_url.replace(/0\.json$/, `${job.id}.json`), job,
            current => showStatus(progress(current), 'info'), follow);
    }

    function followBatch(batch) {
        if (batch.finished) {
            showStatus(batch.message, batch.ok ? 'success' : 'warning');
            finish();
            return;
        }
        showStatus(batch.message, 'info');
        poll(options.batch_url.replace(/[0-]{36}\.json$/, `${batch.id}.json`), batch,
            current => showStatus(current.message, 'info'), followBatch);
    }

    form.addEventListener('submit', async event => {
        event.preventDefault();
        if (pending) return;
        clearErrors();
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
            setBusy(false);  // same request ID: jobs that did arrive are not printed twice
            return;
        }
        if (result && result.ok) {
            if (result.batch) followBatch(result.batch);
            else follow(result.job);
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
