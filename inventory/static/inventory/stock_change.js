// Stock changes: choose remove or add, live sale value, "remove everything"
// and safe submission.
//
// The 🛒 buttons on the item and location pages carry their stock entry in data
// attributes and open one shared Bootstrap modal, which submits in the
// background and then reloads the page. Without JavaScript, the buttons lead to
// the same form as a page, which this script enhances as well.
(() => {
    const form = document.querySelector('[data-stock-change-form]');
    if (!form) return;
    const text = form.dataset;
    const modal = form.closest('.modal');
    const amountInput = form.elements.amount;
    const completeInput = form.elements.complete;
    const requestInput = form.elements.request_id;
    const part = name => form.querySelector(`[data-change-${name}]`);
    const parts = {
        item: part('item'), location: part('location'), details: part('details'), stock: part('stock'),
        unit: part('unit'), sign: part('sign'), amountLabel: part('amount-label'), hint: part('amount-hint'),
        after: part('after'), decreaseOnly: part('decrease-only'), completeHint: part('complete-hint'),
        lastStock: part('last-stock'), value: part('value'), errors: part('errors'),
        submit: form.querySelector('[data-change-submit]'),
    };
    const reasonGroups = [...form.querySelectorAll('[data-change-reasons]')];
    const language = (document.documentElement.lang || 'en').replace('_', '-');
    const formatter = options => {
        try {
            return new Intl.NumberFormat(language, options);
        } catch {
            return new Intl.NumberFormat('en', options);
        }
    };
    const money = formatter({style: 'currency', currency: 'EUR'});
    const quantity = formatter({maximumFractionDigits: 3});
    // A retried submission keeps its ID, so the server applies it only once.
    const requestIds = new Map();
    let entry = null;
    let typedAmount = '';
    let pending = false;

    const number = value => (value === undefined || value === '' ? null : Number(value));
    const direction = () => form.querySelector('[name=direction]:checked')?.value || null;

    function newRequestId() {
        if (crypto.randomUUID) return crypto.randomUUID();
        // randomUUID() needs HTTPS; getRandomValues() does not.
        const bytes = crypto.getRandomValues(new Uint8Array(16));
        bytes[6] = (bytes[6] & 0x0f) | 0x40;
        bytes[8] = (bytes[8] & 0x3f) | 0x80;
        const hex = [...bytes].map(byte => byte.toString(16).padStart(2, '0')).join('');
        return [hex.slice(0, 8), hex.slice(8, 12), hex.slice(12, 16), hex.slice(16, 20), hex.slice(20)].join('-');
    }

    function load(data) {
        entry = {
            amount: number(data.amount), kind: data.kind, amountText: data.amountText, unit: data.unit,
            price: number(data.price), lastStock: data.lastStock === 'true',
        };
        if (parts.item) parts.item.textContent = data.item;
        if (parts.location) parts.location.textContent = data.location;
        parts.stock.textContent = entry.amountText;
        parts.unit.textContent = entry.unit;
        update();
    }

    // Removing everything prefills a known or estimated amount.
    const prefill = () => (entry.kind === 'precise' || entry.kind === 'estimate' ? String(Math.abs(entry.amount)) : null);

    function update() {
        const change = direction();
        const increase = change === 'increase';
        form.dataset.direction = change || '';
        parts.details.hidden = !change;
        parts.submit.disabled = pending || !change;
        parts.submit.classList.toggle('btn-primary', !change);
        parts.submit.classList.toggle('btn-danger', change === 'decrease');
        parts.submit.classList.toggle('btn-success', increase);
        if (!pending) {
            parts.submit.textContent = change ? `${increase ? '↑ +' : '↓ −'} ${increase ? text.labelSubmitIncrease : text.labelSubmitDecrease}` : parts.submit.dataset.initial;
        }
        if (!change) return;

        parts.sign.textContent = increase ? '+' : '−';
        parts.amountLabel.textContent = increase ? text.labelAmountIncrease : text.labelAmountDecrease;
        reasonGroups.forEach(group => {
            const active = group.dataset.changeReasons === change;
            group.hidden = !active;
            group.querySelectorAll('input').forEach(input => {
                input.disabled = !active;
                if (!active) input.checked = false;
            });
            group.querySelector('[data-change-reason-heading]').hidden = true;
        });
        parts.decreaseOnly.hidden = increase;
        if (increase && completeInput.checked) {
            completeInput.checked = false;
            amountInput.value = typedAmount;
        }
        const complete = completeInput.checked;
        const precise = entry.kind === 'precise';
        if (precise) {
            parts.hint.textContent = increase ? '' : text.hintPrecise.replace('{amount}', entry.amountText);
            if (increase) amountInput.removeAttribute('max');
            else amountInput.max = entry.amount;
        } else {
            parts.hint.textContent = entry.kind === 'estimate' ? text.hintEstimate : text.hintUnknown;
            amountInput.removeAttribute('max');
        }
        parts.hint.hidden = !parts.hint.textContent;
        amountInput.readOnly = complete && precise;
        amountInput.required = !complete;
        parts.completeHint.hidden = !complete || precise;
        parts.completeHint.textContent = entry.kind === 'estimate' ? text.hintCompleteEstimate : text.hintCompleteUnknown;

        const amount = amountInput.value === '' ? null : Number(amountInput.value);
        const valid = amount !== null && !Number.isNaN(amount);
        const everything = !increase && (complete || (precise && valid && amount >= entry.amount));
        parts.lastStock.hidden = !(entry.lastStock && everything);

        // Mirrors change_stock(): an estimate remains one, or becomes "few".
        let afterText = null;
        if (valid && !complete && precise) {
            const after = entry.amount + (increase ? amount : -amount);
            if (after >= 0) afterText = `${quantity.format(after)} ${entry.unit}`;
        } else if (valid && !complete && entry.kind === 'estimate') {
            const after = -entry.amount + (increase ? amount : -amount);
            afterText = after > 0 && after !== 1 ? `~${quantity.format(after)} ${entry.unit}` : `${text.labelFew} ${entry.unit}`;
        }
        parts.after.hidden = afterText === null;
        if (afterText !== null) parts.after.textContent = text.hintAfter.replace('{amount}', afterText);

        const estimated = complete && entry.kind === 'estimate' && amount === Math.abs(entry.amount);
        let value;
        if (!valid) value = text.labelUnknownAmount;
        else if (entry.price === null) value = text.labelUnknownPrice;
        else value = (estimated ? '~' : '') + money.format(amount * entry.price);
        parts.value.textContent = `${estimated ? text.labelEstimatedValue : text.labelValue}: ${value}`;
        parts.value.hidden = false;
    }

    function clearErrors() {
        parts.errors.hidden = true;
        parts.errors.replaceChildren();
        form.querySelectorAll('[data-change-field-errors]').forEach(element => element.replaceChildren());
        form.querySelectorAll('.is-invalid').forEach(element => element.classList.remove('is-invalid'));
    }

    function addMessage(container, message) {
        const paragraph = document.createElement('p');
        paragraph.className = 'mb-0';
        paragraph.textContent = message;
        container.append(paragraph);
    }

    function showErrors(errors) {
        Object.entries(errors).forEach(([name, list]) => {
            const container = form.querySelector(`[data-change-field-errors="${name}"]`) || parts.errors;
            list.forEach(error => addMessage(container, error.message));
            if (container === parts.errors) parts.errors.hidden = false;
            const input = form.elements[name];
            if (input && input.classList) input.classList.add('is-invalid');
        });
    }

    function showError(message) {
        addMessage(parts.errors, message);
        parts.errors.hidden = false;
    }

    function setBusy(busy) {
        pending = busy;
        if (busy) {
            parts.submit.disabled = true;
            parts.submit.textContent = text.labelSaving;
        } else {
            update();
        }
    }

    function go(url) {
        const target = new URL(url, window.location.href);
        // Reloading keeps the scroll position in the list.
        if (target.pathname + target.search === window.location.pathname + window.location.search) {
            window.location.reload();
        } else {
            window.location.assign(target.href);
        }
    }

    parts.submit.dataset.initial = parts.submit.textContent;
    form.querySelectorAll('[name=direction]').forEach(input => input.addEventListener('change', update));
    completeInput.addEventListener('change', () => {
        const value = prefill();
        if (value !== null) {
            if (completeInput.checked) {
                typedAmount = amountInput.value;
                amountInput.value = value;
            } else {
                amountInput.value = typedAmount;
            }
        }
        update();
    });
    amountInput.addEventListener('input', update);

    if (!modal || !window.bootstrap) {
        // The fallback page submits normally; only prevent double submission.
        load(form.dataset);
        form.addEventListener('submit', () => {
            window.setTimeout(() => setBusy(true));
        });
        return;
    }

    // Bootstrap ignores show() while the dialog is still fading out.
    let hiding = false;
    modal.addEventListener('hide.bs.modal', () => { hiding = true; });
    modal.addEventListener('hidden.bs.modal', () => { hiding = false; });
    function show() {
        const dialog = window.bootstrap.Modal.getOrCreateInstance(modal);
        if (hiding) modal.addEventListener('hidden.bs.modal', () => dialog.show(), {once: true});
        else dialog.show();
    }

    document.querySelectorAll('[data-stock-change]').forEach(button => {
        button.addEventListener('click', event => {
            event.preventDefault();
            window.bootstrap.Tooltip.getInstance(button)?.hide();
            if (!pending) {
                form.reset();
                clearErrors();
                typedAmount = '';
                form.action = button.href;
                if (!requestIds.has(button.href)) requestIds.set(button.href, newRequestId());
                requestInput.value = requestIds.get(button.href);
                load(button.dataset);
            }
            show();
        });
    });
    modal.addEventListener('shown.bs.modal', () => {
        // Remove or add is chosen first; then the amount.
        (direction() ? amountInput : form.querySelector('[name=direction]')).focus();
    });
    form.querySelectorAll('[name=direction]').forEach(input => input.addEventListener('change', () => amountInput.focus()));

    form.addEventListener('submit', async event => {
        event.preventDefault();
        if (pending) return;
        clearErrors();
        setBusy(true);
        const controller = new AbortController();
        const timer = window.setTimeout(() => controller.abort(), 20000);
        let data = null;
        try {
            const response = await fetch(form.action, {
                method: 'POST', body: new FormData(form), credentials: 'same-origin',
                headers: {Accept: 'application/json'}, signal: controller.signal,
            });
            data = await response.json().catch(() => null);
            if (data && data.ok) {
                // Also when the dialog was closed meanwhile: the stock has changed.
                go(data.url);
                return;
            }
            if (data && data.errors) showErrors(data.errors);
            else showError(text.labelError);
        } catch {
            showError(text.labelNetworkError);
        } finally {
            window.clearTimeout(timer);
        }
        setBusy(false);
    });
})();
