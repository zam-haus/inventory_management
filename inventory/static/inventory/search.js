// The search page (search.html, docs/search.md):
// * Results while typing: shortly after typing stops, the results of the words are fetched (?partial=1) and
//   replace the shown ones; a newer search cancels an older one. Enter sends the form as usual, so that a
//   typed or scanned code opens its page.
// * More results while scrolling: the next page is loaded when its link comes near.
// * The up and down arrow keys move between the results (down from the field to the first, up from the
//   first back to it) and mark the current one; its photos open large below it, left and right go through
//   them, Escape closes them. Enter and space open the result.
// * A click on a row outside its links opens it, unless text was selected there to copy it.
// * The photo button opens the photos of a result below it, too. Swipe sideways for its other photos, up or
//   down for those of the next or previous result with photos.
(() => {
    const form = document.querySelector('[data-live-search]');
    const results = document.getElementById('search-results');
    const status = document.querySelector('[data-search-status]');
    const error = document.querySelector('[data-search-error]');
    if (!form || !results) return;
    const input = form.elements.q;
    const labels = results.dataset;
    const reducedMotion = window.matchMedia('(prefers-reduced-motion: reduce)').matches;
    const behavior = reducedMotion ? 'auto' : 'smooth';
    const MIN_LENGTH = 2;
    const DELAY = 200;  // ms after the last key
    const headers = {Accept: 'text/html'};

    // The field is ready to be typed on, after a given query. A page Chrome loaded in advance (from the navbar's
    // magnifier, navbar.js) gets the focus once it is shown.
    function ready() {
        input.focus();
        input.setSelectionRange(input.value.length, input.value.length);
    }
    if (document.prerendering) document.addEventListener('prerenderingchange', ready, {once: true});
    else if (document.activeElement === input) ready();

    const entries = () => [...results.querySelectorAll('[data-search-entry]')];

    function mark(entry) {
        results.querySelectorAll('[data-search-entry][aria-current]').forEach(other => other.removeAttribute('aria-current'));
        entry?.setAttribute('aria-current', 'true');
    }

    // More results while scrolling.
    let more = null;  // the request for the next page
    let observer = null;

    function watchNext() {
        observer?.disconnect();
        const next = results.querySelector('[data-search-next]');
        if (!next || !window.IntersectionObserver) return;
        observer = new IntersectionObserver(seen => {
            if (seen.some(entry => entry.isIntersecting)) loadMore();
        }, {rootMargin: '600px 0px'});
        observer.observe(next);
    }

    // Adds the next page of results; true if it did.
    async function loadMore() {
        const next = results.querySelector('[data-search-next]');
        if (!next || more) return false;
        more = new AbortController();
        const url = new URL(next.dataset.searchNext, window.location.href);
        url.searchParams.set('partial', '1');
        try {
            const response = await fetch(url, {signal: more.signal, credentials: 'same-origin', headers});
            if (!response.ok) throw new Error(`HTTP ${response.status}`);
            const page = document.createElement('div');
            page.innerHTML = await response.text();
            const found = page.querySelector('[data-search-entries]');
            results.querySelector('[data-search-list]').append(found.content);
            found.remove();
            next.replaceWith(...page.children);
            error.hidden = true;
            return true;
        } catch (failure) {
            if (failure.name !== 'AbortError') error.hidden = false;
            return false;
        } finally {
            more = null;
            watchNext();
        }
    }

    // The photos of a result, below it.
    const viewer = (() => {
        let current = null;  // the entry whose photos are shown
        const element = document.createElement('li');
        element.className = 'search-viewer';
        element.setAttribute('role', 'group');
        element.setAttribute('aria-label', labels.photosLabel);
        element.innerHTML = `
            <div class="search-viewer-strip" tabindex="0"></div>
            <p class="search-viewer-counter" aria-live="polite"></p>
            <button type="button" class="search-viewer-button search-viewer-prev" data-icon="chevron-left"></button>
            <button type="button" class="search-viewer-button search-viewer-next" data-icon="chevron-right"></button>
            <button type="button" class="search-viewer-button search-viewer-close" data-icon="x-lg"></button>`;
        element.querySelectorAll('[data-icon]').forEach(button => button.append(window.appIcon?.(button.dataset.icon) ?? ''));
        const strip = element.querySelector('.search-viewer-strip');
        const counter = element.querySelector('.search-viewer-counter');
        const prev = element.querySelector('.search-viewer-prev');
        const next = element.querySelector('.search-viewer-next');
        const closer = element.querySelector('.search-viewer-close');
        prev.setAttribute('aria-label', labels.previousLabel);
        next.setAttribute('aria-label', labels.nextLabel);
        closer.setAttribute('aria-label', labels.closeLabel);

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
            current?.querySelector('[data-search-photos]')?.setAttribute('aria-expanded', 'false');
            current = entry;
            mark(entry);
            entry.querySelector('[data-search-photos]')?.setAttribute('aria-expanded', 'true');
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
            current.querySelector('[data-search-photos]')?.setAttribute('aria-expanded', 'false');
            element.remove();
            current = null;
        }

        function step(direction) {
            strip.scrollTo({left: (index() + direction) * strip.clientWidth, behavior});
        }

        // The photos of the next (1) or previous (-1) result with photos, loading more results at the end.
        async function move(direction) {
            let list = entries();
            for (let position = list.indexOf(current) + direction; position >= 0; position += direction) {
                if (position >= list.length) {
                    if (direction < 0 || !await loadMore()) return;
                    list = entries();
                    if (position >= list.length) return;
                }
                if (list[position].dataset.photos) {
                    open(list[position]);
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
            entry.querySelector('[data-search-photos]').focus();
        });
        // Sideways swipes scroll through the photos (touch-action: pan-x); up and down go to other results.
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

    // A click on a row outside its links opens its title, unless text was selected there (to copy it).
    results.addEventListener('click', event => {
        const entry = event.target.closest('[data-search-entry]');
        if (!entry || event.target.closest('a, button, [data-location-info]') || String(window.getSelection())) return;
        entry.querySelector('.search-link').click();
    });

    results.addEventListener('click', event => {
        const button = event.target.closest('[data-search-photos]');
        if (!button) return;
        const entry = button.closest('[data-search-entry]');
        if (viewer.current === entry) viewer.close();
        else viewer.open(entry);
    });

    // Arrow keys between the results: the current one is marked, its photos are open.
    function go(entry) {
        mark(entry);
        if (entry.dataset.photos) {
            viewer.open(entry);
        } else {
            viewer.close();
            entry.querySelector('.search-link').focus();
        }
    }

    document.addEventListener('keydown', async event => {
        if (event.defaultPrevented || event.altKey || event.ctrlKey || event.metaKey || event.shiftKey) return;
        if (event.target === input) {
            const first = entries()[0];
            if (event.key !== 'ArrowDown' || !first) return;
            event.preventDefault();
            go(first);
            return;
        }
        const entry = viewer.current || event.target.closest?.('[data-search-entry]');
        if (!entry || !results.contains(entry)) return;
        if (event.key === 'ArrowDown' || event.key === 'ArrowUp') {
            event.preventDefault();
            const position = entries().indexOf(entry) + (event.key === 'ArrowDown' ? 1 : -1);
            if (position < 0) {
                viewer.close();
                mark(null);
                input.focus();
                return;
            }
            if (position >= entries().length && !await loadMore()) return;
            const target = entries()[position];
            if (target) go(target);
        } else if (viewer.current && (event.key === 'ArrowLeft' || event.key === 'ArrowRight')) {
            event.preventDefault();
            viewer.step(event.key === 'ArrowRight' ? 1 : -1);
        } else if (event.key === ' ' && !event.target.closest('button')) {
            // Space opens the marked result, like Enter (code chips handle their own keys, location_info.js).
            event.preventDefault();
            window.location.assign(entry.querySelector('.search-link').href);
        } else if (viewer.current && event.key === 'Enter' && !event.target.closest('button')) {
            // The photos have the focus, not the link.
            event.preventDefault();
            entry.querySelector('.search-link').click();
        } else if (viewer.current && event.key === 'Escape') {
            event.preventDefault();
            viewer.close();
            entry.querySelector('.search-link').focus();
        }
    });
    results.addEventListener('focusin', event => {
        const entry = event.target.closest('[data-search-entry]');
        if (entry && !viewer.current) mark(entry);
    });

    // Results while typing.
    let timer = 0;
    let controller = null;

    function url(query, partial) {
        const target = new URL(form.action, window.location.href);
        if (query) target.searchParams.set('q', query);
        if (partial) target.searchParams.set('partial', '1');
        return target;
    }

    async function show(query) {
        controller?.abort();
        more?.abort();
        controller = new AbortController();
        window.history.replaceState(null, '', url(query, false));
        if (query.length < MIN_LENGTH) {
            viewer.close();
            results.replaceChildren();
            status.textContent = '';
            error.hidden = true;
            return;
        }
        try {
            const response = await fetch(url(query, true), {signal: controller.signal, credentials: 'same-origin', headers});
            if (!response.ok) throw new Error(`HTTP ${response.status}`);
            const text = await response.text();
            viewer.close();
            results.innerHTML = text;
            status.textContent = results.firstElementChild?.dataset.status || '';
            error.hidden = true;
            watchNext();
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
    watchNext();
})();
