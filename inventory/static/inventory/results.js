// Result rows (results/entries.html, docs/search.md) in every list of them ([data-result-list]): the search results,
// a category's items, a location's items and sub-locations, an item's places.
// * A click on a row outside its links, buttons and code chips opens it, unless text was selected there to copy it.
// * The photo button opens the photos of a row below it. Swipe sideways for its other photos, up or down for those
//   of the next or previous row with photos in the same list.
// * The up and down arrow keys move between the rows of a list (down from a search field that controls the list to
//   its first row, up from the first back to it) and mark the current one; its photos open large below it, left and
//   right go through them, Escape closes them. Enter opens the row, space too. A row in a collapsed list
//   (list_collapse.js) opens the list.
// * More rows while scrolling: the next ones are loaded when the link to them comes near.
// window.inventoryResults: close() closes the photos; watch(container) loads more rows for the lists in it (after
// they were replaced, live_search.js). Lists announce results:loaded and results:error (bubbling).
(() => {
    const template = document.getElementById('result-viewer');
    if (!template) return;
    const reducedMotion = window.matchMedia('(prefers-reduced-motion: reduce)').matches;
    const behavior = reducedMotion ? 'auto' : 'smooth';
    const headers = {Accept: 'text/html'};
    // What a click handles itself, instead of opening the row.
    const INTERACTIVE = 'a, button, input, select, textarea, label, [role="button"], .disabled-action, [data-location-info]';

    const rows = list => [...list.children].filter(child => child.matches('[data-result-entry]'));
    const listOf = entry => entry.closest('[data-result-list]');
    const linkOf = entry => entry.querySelector('.result-link');

    function mark(entry) {
        document.querySelectorAll('.result-entry.is-marked').forEach(other => other.classList.remove('is-marked'));
        entry?.classList.add('is-marked');
    }

    // More rows while scrolling: the link to them follows the list (results/next.html).
    const loading = new WeakMap();  // list → its request for the next rows
    const observer = window.IntersectionObserver ? new IntersectionObserver(seen => {
        seen.filter(entry => entry.isIntersecting).forEach(entry => {
            const list = entry.target.previousElementSibling;
            if (list?.matches('[data-result-list]')) loadMore(list);
        });
    }, {rootMargin: '600px 0px'}) : null;

    function watch(container) {
        container.querySelectorAll('[data-result-next]').forEach(next => observer?.observe(next));
    }

    // Adds the next rows of the list; true if it did.
    async function loadMore(list) {
        const next = list.nextElementSibling;
        if (!next?.matches('[data-result-next]') || loading.has(list)) return false;
        const controller = new AbortController();
        loading.set(list, controller);
        const url = new URL(next.dataset.resultNext, window.location.href);
        url.searchParams.set('partial', '1');
        try {
            const response = await fetch(url, {signal: controller.signal, credentials: 'same-origin', headers});
            if (!response.ok) throw new Error(`HTTP ${response.status}`);
            const page = document.createElement('div');
            page.innerHTML = await response.text();
            const found = page.querySelector('[data-result-entries]');
            list.append(found.content);
            found.remove();
            observer?.unobserve(next);
            next.replaceWith(...page.children);
            list.dispatchEvent(new CustomEvent('results:loaded', {bubbles: true}));
            return true;
        } catch (failure) {
            if (failure.name !== 'AbortError') list.dispatchEvent(new CustomEvent('results:error', {bubbles: true}));
            return false;
        } finally {
            loading.delete(list);
            if (list.parentElement) watch(list.parentElement);
        }
    }

    // A row hidden in a collapsed list opens the list (list_collapse.js).
    function reveal(entry) {
        if (entry.hidden) entry.dispatchEvent(new CustomEvent('list-collapse:expand', {bubbles: true}));
    }

    // The photos of a row, below it; one viewer for the page.
    const viewer = (() => {
        let current = null;  // the row whose photos are shown
        const element = template.content.firstElementChild.cloneNode(true);
        const strip = element.querySelector('.result-viewer-strip');
        const counter = element.querySelector('.result-viewer-counter');
        const prev = element.querySelector('.result-viewer-prev');
        const next = element.querySelector('.result-viewer-next');
        const closer = element.querySelector('.result-viewer-close');

        const photos = entry => {
            try {
                return JSON.parse(entry?.dataset.photos || '[]');
            } catch {
                return [];
            }
        };
        const index = () => Math.round(strip.scrollLeft / Math.max(strip.clientWidth, 1));

        function count() {
            const total = strip.children.length;
            const shown = Math.min(index(), total - 1);
            counter.textContent = total > 1 ? `${shown + 1} / ${total}` : '';
            prev.hidden = next.hidden = total < 2;
            prev.disabled = shown <= 0;
            next.disabled = shown >= total - 1;
        }

        function open(entry) {
            const list = photos(entry);
            if (!list.length) return;
            current?.querySelector('[data-result-photos]')?.setAttribute('aria-expanded', 'false');
            current = entry;
            mark(entry);
            entry.querySelector('[data-result-photos]')?.setAttribute('aria-expanded', 'true');
            strip.replaceChildren(...list.map((photo, position) => {
                const figure = document.createElement('figure');
                const image = document.createElement('img');
                image.loading = position ? 'lazy' : 'eager';
                image.draggable = false;
                image.alt = photo.alt || '';
                image.src = photo.src;
                figure.append(image);
                if (photo.alt) {
                    const caption = document.createElement('figcaption');
                    caption.textContent = photo.alt;
                    figure.append(caption);
                }
                return figure;
            }));
            entry.after(element);  // moving it blurs the strip
            strip.scrollLeft = 0;
            count();
            entry.scrollIntoView({block: 'start', behavior});
            // The keys work on the photos now (on phones this also puts the keyboard away).
            strip.focus({preventScroll: true});
        }

        function close() {
            if (!current) return;
            current.querySelector('[data-result-photos]')?.setAttribute('aria-expanded', 'false');
            element.remove();
            current = null;
        }

        function step(direction) {
            strip.scrollTo({left: (index() + direction) * strip.clientWidth, behavior});
        }

        // The photos of the next (1) or previous (-1) row with photos in the list, loading more rows at the end.
        async function move(direction) {
            const list = listOf(current);
            let all = rows(list);
            for (let position = all.indexOf(current) + direction; position >= 0; position += direction) {
                if (position >= all.length) {
                    if (direction < 0 || !await loadMore(list)) return;
                    all = rows(list);
                    if (position >= all.length) return;
                }
                if (all[position].dataset.photos && !all[position].hidden) {
                    open(all[position]);
                    return;
                }
            }
        }

        strip.addEventListener('scroll', () => window.requestAnimationFrame(count), {passive: true});
        prev.addEventListener('click', () => step(-1));
        next.addEventListener('click', () => step(1));
        closer.addEventListener('click', () => {
            const entry = current;
            close();
            entry.querySelector('[data-result-photos]').focus();
        });
        // Sideways swipes scroll through the photos (touch-action: pan-x); up and down go to other rows.
        let start = null;
        element.addEventListener('touchstart', event => {
            const touch = event.touches[0];
            start = event.touches.length === 1 ? {x: touch.clientX, y: touch.clientY} : null;
        }, {passive: true});
        element.addEventListener('touchend', event => {
            if (!start) return;
            const touch = event.changedTouches[0];
            const dx = touch.clientX - start.x;
            const dy = touch.clientY - start.y;
            start = null;
            if (Math.abs(dy) > 40 && Math.abs(dy) > 1.5 * Math.abs(dx)) move(dy < 0 ? 1 : -1);
        });
        return {open, close, step, get current() { return current; }};
    })();

    document.addEventListener('click', event => {
        const button = event.target.closest('[data-result-photos]');
        if (button) {
            const entry = button.closest('[data-result-entry]');
            if (viewer.current === entry) viewer.close();
            else viewer.open(entry);
            return;
        }
        // A click on a row outside its links opens its title, unless text was selected there (to copy it).
        const entry = event.target.closest('[data-result-entry]');
        if (!entry || event.target.closest(INTERACTIVE) || String(window.getSelection())) return;
        linkOf(entry).click();
    });

    // A collapsed list hides the photos of its rows, too.
    document.addEventListener('change', event => {
        if (event.target.matches('.list-collapse-state') && viewer.current?.hidden) viewer.close();
    });

    // The search field controlling a list: aria-controls names the element the list is in.
    const fieldOf = list => [...document.querySelectorAll('input[aria-controls]')].find(input =>
        document.getElementById(input.getAttribute('aria-controls'))?.contains(list));

    // Arrow keys between the rows: the current one is marked, its photos are open.
    function go(entry) {
        reveal(entry);
        mark(entry);
        if (entry.dataset.photos) {
            viewer.open(entry);
        } else {
            viewer.close();
            linkOf(entry).focus();
        }
    }

    document.addEventListener('keydown', async event => {
        if (event.defaultPrevented || event.altKey || event.ctrlKey || event.metaKey || event.shiftKey) return;
        const target = event.target;
        if (target.matches?.('input[aria-controls]')) {
            const list = document.getElementById(target.getAttribute('aria-controls'))?.querySelector('[data-result-list]');
            const first = list && rows(list)[0];
            if (event.key !== 'ArrowDown' || !first) return;
            event.preventDefault();
            go(first);
            return;
        }
        const entry = viewer.current || target.closest?.('[data-result-entry]');
        if (!entry) return;
        const inViewer = Boolean(target.closest?.('.result-viewer-strip'));
        if (event.key === 'ArrowDown' || event.key === 'ArrowUp') {
            event.preventDefault();
            const list = listOf(entry);
            const position = rows(list).indexOf(entry) + (event.key === 'ArrowDown' ? 1 : -1);
            if (position < 0) {
                const field = fieldOf(list);
                if (!field) return;
                viewer.close();
                mark(null);
                field.focus();
                return;
            }
            if (position >= rows(list).length && !await loadMore(list)) return;
            const row = rows(list)[position];
            if (row) go(row);
        } else if (viewer.current && (event.key === 'ArrowLeft' || event.key === 'ArrowRight')) {
            event.preventDefault();
            viewer.step(event.key === 'ArrowRight' ? 1 : -1);
        } else if (event.key === ' ' && (target.matches?.('.result-link') || inViewer)) {
            // Space opens the marked row, like Enter (buttons and code chips in it handle their own keys).
            event.preventDefault();
            window.location.assign(linkOf(entry).href);
        } else if (event.key === 'Enter' && inViewer) {
            // The photos have the focus, not the link.
            event.preventDefault();
            linkOf(entry).click();
        } else if (viewer.current && event.key === 'Escape') {
            event.preventDefault();
            viewer.close();
            linkOf(entry).focus();
        }
    });
    document.addEventListener('focusin', event => {
        const entry = event.target.closest?.('[data-result-entry]');
        if (entry && !viewer.current) mark(entry);
    });

    watch(document);
    window.inventoryResults = {close: viewer.close, watch};
})();
