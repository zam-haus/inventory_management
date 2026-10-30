// Results while typing (docs/search.md), on the search page and a category's page: a form[data-live-search] whose
// field names the element holding the results (aria-controls). Shortly after typing stops, the results of the words
// are fetched (?partial=1) and replace the shown ones; a newer search cancels an older one. Enter sends the form as
// usual, so that on the search page a typed or scanned code opens its page. Below two characters the results go
// away, or, with data-live-search-listing, the list without words comes back (a category's items). Above the
// results, how many there are of each kind; each chooses that kind or not, none chosen shows all (?kinds=, kept in a
// hidden field of the form for the next words and for Enter). The rows themselves are results.js's.
(() => {
    const MIN_LENGTH = 2;
    const DELAY = 200;  // ms after the last key
    const headers = {Accept: 'text/html'};

    document.querySelectorAll('form[data-live-search]').forEach(form => {
        const input = form.elements.q;
        const results = document.getElementById(input?.getAttribute('aria-controls'));
        if (!results) return;
        const page = form.closest('.search-page') || document;
        const status = page.querySelector('[data-search-status]');
        const error = page.querySelector('[data-search-error]');
        const listing = form.hasAttribute('data-live-search-listing');
        const shown = () => window.inventoryResults;

        // The field is ready to be typed on, after a given query. A page Chrome loaded in advance (from the navbar's
        // magnifier, navbar.js) gets the focus once it is shown.
        function ready() {
            input.focus();
            input.setSelectionRange(input.value.length, input.value.length);
        }
        if (input.autofocus) {
            if (document.prerendering) document.addEventListener('prerenderingchange', ready, {once: true});
            else if (document.activeElement === input) ready();
        }

        // Further rows (results.js) that could not be loaded show the same notice.
        results.addEventListener('results:error', () => { error.hidden = false; });
        results.addEventListener('results:loaded', () => { error.hidden = true; });

        let timer = 0;
        let controller = null;

        function url(query, partial) {
            const target = new URL(form.action, window.location.href);
            if (query) target.searchParams.set('q', query);
            if (query && form.elements.kinds?.value) target.searchParams.set('kinds', form.elements.kinds.value);
            if (partial) target.searchParams.set('partial', '1');
            target.search = target.search.replaceAll('%2C', ',');  // ?kinds=location,item, as the server's links
            return target;
        }

        // The kinds chosen, from the link of a kind in the summary.
        function choose(kinds) {
            let field = form.elements.kinds;
            if (!kinds) {
                field?.remove();
                return;
            }
            if (!field) {
                field = document.createElement('input');
                field.type = 'hidden';
                field.name = 'kinds';
                form.append(field);
            }
            field.value = kinds;
        }

        results.addEventListener('click', event => {
            const filter = event.target.closest('[data-result-kinds] a');
            if (!filter) return;
            event.preventDefault();
            choose(new URL(filter.href, window.location.href).searchParams.get('kinds'));
            const kind = filter.dataset.kind;
            // The summary comes anew with the results; the focus stays on the same kind.
            show(input.value.trim()).then(() => {
                if (results.contains(document.activeElement)) return;
                results.querySelector(`[data-result-kinds] [data-kind="${kind}"]`)?.focus();
            });
        });
        // They are buttons: space chooses, too.
        results.addEventListener('keydown', event => {
            if (event.key !== ' ' || !event.target.closest('[data-result-kinds] a')) return;
            event.preventDefault();
            event.target.click();
        });

        async function show(typed) {
            controller?.abort();
            controller = new AbortController();
            const query = typed.length < MIN_LENGTH ? '' : typed;
            window.history.replaceState(null, '', url(query, false));
            if (!query && !listing) {
                shown()?.close();
                results.replaceChildren();
                status.textContent = '';
                error.hidden = true;
                return;
            }
            try {
                const response = await fetch(url(query, true), {signal: controller.signal, credentials: 'same-origin', headers});
                if (!response.ok) throw new Error(`HTTP ${response.status}`);
                const text = await response.text();
                shown()?.close();
                results.innerHTML = text;
                status.textContent = results.firstElementChild?.dataset.status || '';
                error.hidden = true;
                shown()?.watch(results);
            } catch (failure) {
                if (failure.name === 'AbortError') return;
                error.hidden = false;
            }
        }

        input.addEventListener('input', () => {
            window.clearTimeout(timer);
            timer = window.setTimeout(() => show(input.value.trim()), DELAY);
        });
        form.addEventListener('submit', () => {
            window.clearTimeout(timer);
            controller?.abort();
        });
    });
})();
