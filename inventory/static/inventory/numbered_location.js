// Adding storage furniture (numbered_location_create.html): one page, the type first. Choosing another type loads
// what depends on it (numbered_location_fields.html, ?partial=1: its drawing and text, the number fields, the
// compartments) and the submit button's text; purpose and description stay as typed. Only the fields of the chosen way
// to get a number are shown; hidden fields are disabled, so they are not sent; the server ignores them too. Several at
// once (a count above 1, unless only the following numbers are reserved) get no purpose.
(() => {
    const form = document.querySelector('[data-numbering-form]');
    if (!form) return;
    const fieldsFor = {reserved: ['reserved', 'count'], wish: ['wish', 'count', 'reserve_only'],
                       auto: ['count', 'reserve_only']};
    const show = (input, shown) => {
        const group = input?.closest('.mb-3');
        if (!group) return;
        group.hidden = !shown;
        input.disabled = !shown;
    };
    const several = mode => Number(form.elements.count?.value) > 1
        && !(mode !== 'reserved' && form.elements.reserve_only?.checked);
    const update = () => {
        const mode = form.querySelector('input[name="mode"]:checked')?.value;
        for (const name of ['reserved', 'wish', 'count', 'reserve_only']) {
            show(form.elements[name], (fieldsFor[mode] || []).includes(name));
        }
        show(form.elements.purpose, !several(mode));
    };

    const fields = form.querySelector('[data-numbering-fields]');
    const button = form.querySelector('[data-numbering-submit-button]');
    let loading = null;
    async function choose(type) {
        loading?.abort();
        loading = new AbortController();
        const url = new URL(form.dataset.fieldsUrl, window.location.href);
        url.searchParams.set('type', type);
        fields.setAttribute('aria-busy', 'true');
        button.disabled = true;
        try {
            const response = await fetch(`${url}&partial=1`, {signal: loading.signal, credentials: 'same-origin'});
            if (!response.ok) throw new Error(`HTTP ${response.status}`);
            const part = document.createElement('div');
            part.innerHTML = await response.text();
            const label = part.querySelector('template[data-numbering-submit]');
            if (label) button.replaceChildren(label.content);
            fields.replaceChildren(...part.children);
            window.history.replaceState(window.history.state, '', url);
            update();
        } catch (failure) {
            if (failure.name !== 'AbortError') window.location.assign(url);  // the page for that type, as without JavaScript
        } finally {
            fields.removeAttribute('aria-busy');
            button.disabled = false;
        }
    }

    form.addEventListener('change', event => {
        if (event.target.matches('[data-numbering-type]')) choose(event.target.value);
        else update();
    });
    form.addEventListener('input', update);
    update();
})();
