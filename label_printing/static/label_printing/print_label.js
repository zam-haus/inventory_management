// The print dialogs (label_printing/print_dialog.html, one per kind on a page; also the fallback page). For one
// subject: which label to print (the server picks the printer), the templates its rules recommend shown, others
// on request; labels no printer can print now are greyed but may wait for one. For several (a location with its
// sub-locations, the items at a location): an overview, a row per label with its best template, each printed as a
// job of its own: the labels in their real size, a tap on a row switches it, marks say what is missing (printer or
// material), and a summary what waits for what. After printing the dialog follows the job (or the batch of jobs) until the printers report back,
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
        waitSummary: form.querySelector('[data-wait-summary]'),
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

    // The label in its real size (1 mm on the label = 1 mm on the screen, as far as the screen says)
    function realSize(image, item) {
        if (!item?.dpi || !image.naturalWidth) return;
        image.style.width = `${(image.naturalWidth / item.dpi) * 25.4}mm`;
        image.style.height = `${(image.naturalHeight / item.dpi) * 25.4}mm`;
    }

    // A row's preview and what keeps its label from being printed now (printer or material)
    function rowState(row) {
        const image = row.querySelector('img');
        const item = outcome(select(row)?.value);
        if (!image || !item) return;
        const url = previewUrl(options.rows[Number(row.dataset.row)], item);
        if (image.getAttribute('src') !== url) image.src = url;
        else realSize(image, item);
        setMarks(row.querySelector('[data-marks]'), item);
        const toggle = row.querySelector('[data-picker-toggle]');
        if (toggle) toggle.textContent = select(row).selectedOptions[0]?.textContent || '';
    }

    // Printer and labels: green when there, struck through in red when they keep the label from printing now
    function setMarks(marks, item) {
        marks?.querySelectorAll('[data-mark]').forEach(mark => {
            const missing = !item.printer && item.missing === mark.dataset.mark;
            mark.classList.toggle('is-missing', missing);
            mark.classList.toggle('is-ok', !missing);
            mark.title = missing ? item.reason : (mark.dataset.mark === 'printer' ? item.printer : item.size);
        });
    }

    // The overview's choice of label: a menu with a preview of each (the select stays for the form)
    function setUpPicker(row) {
        const picker = row.querySelector('[data-picker]');
        if (!picker) return;
        const toggle = picker.querySelector('[data-picker-toggle]');
        const menu = picker.querySelector('[data-picker-menu]');
        select(row).hidden = true;
        toggle.hidden = false;
        const close = () => { menu.hidden = true; toggle.setAttribute('aria-expanded', 'false'); };
        const choose = value => {
            select(row).value = value;
            select(row).dispatchEvent(new Event('change', {bubbles: true}));
            close();
            toggle.focus();
        };
        toggle.addEventListener('click', () => {
            if (!menu.hidden) return close();
            menu.replaceChildren(...[...select(row).children].flatMap(group => [
                Object.assign(document.createElement('div'), {className: 'label-picker-group', textContent: group.label}),
                ...[...group.children].map(option => {
                    const item = outcome(option.value);
                    const entry = Object.assign(document.createElement('button'), {
                        type: 'button', className: `label-picker-item${option.selected ? ' is-chosen' : ''}`,
                    });
                    entry.setAttribute('role', 'menuitem');
                    const image = Object.assign(document.createElement('img'), {
                        alt: '', loading: 'lazy', src: previewUrl(options.rows[Number(row.dataset.row)], item),
                    });
                    const label = Object.assign(document.createElement('span'), {
                        className: 'label-picker-text', textContent: option.textContent,
                    });
                    const marks = row.querySelector('[data-marks]').cloneNode(true);
                    setMarks(marks, item);
                    entry.append(image, label, marks);
                    entry.addEventListener('click', () => choose(option.value));
                    return entry;
                }),
            ]));
            menu.hidden = false;
            toggle.setAttribute('aria-expanded', 'true');
            menu.querySelector('.is-chosen')?.focus();
        });
        picker.addEventListener('keydown', event => { if (event.key === 'Escape' && !menu.hidden) { event.stopPropagation(); close(); toggle.focus(); } });
        document.addEventListener('click', event => { if (!picker.contains(event.target)) close(); });
    }

    // What the overview's labels wait for: "16 at once, 3 waiting for labels (…), 3 for a printer (…)"
    function summary(rows, copies) {
        const now = [], waiting = {material: new Map(), printer: new Map()};
        rows.forEach(row => {
            const item = outcome(select(row).value);
            if (item.printer) now.push(row);
            else if (waiting[item.missing]) {
                waiting[item.missing].set(item.missing_name, (waiting[item.missing].get(item.missing_name) || 0) + copies);
            }
        });
        const count = map => [...map.values()].reduce((sum, value) => sum + value, 0);
        const names = map => [...map.keys()].join(', ');
        const parts = [text.labelSummaryNow.replace('{count}', now.length * copies)];
        if (waiting.material.size) {
            parts.push(text.labelSummaryMaterial.replace('{count}', count(waiting.material)).replace('{names}', names(waiting.material)));
        }
        if (waiting.printer.size) {
            parts.push(text.labelSummaryPrinter.replace('{count}', count(waiting.printer)).replace('{names}', names(waiting.printer)));
        }
        return waiting.material.size || waiting.printer.size ? `${parts.join(', ')}. ${text.labelSummaryWait}` : '';
    }

    // The button says what will happen: print on a printer, or wait for one (the note says what waiting means);
    // in the overview, how many labels.
    function update() {
        const several = overview();
        if (parts.single) parts.single.hidden = several;
        if (parts.overview) parts.overview.hidden = !several;
        parts.waitSummary.hidden = true;
        if (several) {
            const rows = wanted();
            const items = rows.map(row => outcome(select(row).value)).filter(Boolean);
            const copies = parseInt(fields.copies.value, 10) || 1;
            parts.waitNote.hidden = true;
            parts.waitSummary.textContent = summary(rows, copies);
            parts.waitSummary.hidden = !parts.waitSummary.textContent;
            parts.submit.disabled = pending || !rows.length || items.some(item => !item.printer && !item.can_wait);
            if (!pending) submitLabel.textContent = text.labelSubmitRows.replace('{count}', rows.length * copies);
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

    // A tap anywhere on a row of the overview (but its template) switches it on or off.
    form.addEventListener('click', event => {
        const row = event.target.closest('[data-row]');
        if (!row || event.target.closest('select, input, option, [data-picker], [data-apply-all]')) return;
        const box = printing(row);
        if (box.disabled) return;
        box.checked = !box.checked;
        update();
    });

    // The first row's label for all rows that may have it
    form.querySelector('[data-apply-all]')?.addEventListener('click', () => {
        const value = select(parts.rows[0]).value;
        parts.rows.slice(1).forEach(row => {
            if (select(row) && [...select(row).options].some(option => option.value === value)) {
                select(row).value = value;
                rowState(row);
            }
        });
        update();
    });

    form.addEventListener('load', event => {
        const row = event.target.closest?.('[data-row]');
        if (row && event.target.tagName === 'IMG') realSize(event.target, outcome(select(row)?.value));
    }, true);

    form.addEventListener('change', event => {
        const row = event.target.closest('[data-row]');
        if (row && event.target.tagName === 'SELECT') rowState(row);
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
    parts.rows.forEach(setUpPicker);
    parts.rows.forEach(rowState);
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
