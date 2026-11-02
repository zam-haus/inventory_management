// The navbar sticks to the top (sticky-top), slides away while scrolling down and comes back
// as soon as the page is scrolled up a little. It stays at the top of the page, while its menus
// are open, while it has the keyboard focus and while held (data-held: the magnifier went to the page's field, so
// that a second click can go on to everything).
(() => {
    const navbar = document.querySelector('.app-navbar');
    if (!navbar) return;
    const SHOW_AFTER = 10;  // px scrolled up before it comes back
    let lastY = Math.max(0, window.scrollY);
    let scrolledUp = 0;
    let pending = false;

    const show = () => navbar.classList.remove('is-hidden');
    const busy = () => navbar.querySelector('.dropdown-menu.show')
        || navbar.contains(document.activeElement) || navbar.hasAttribute('data-held');

    function update() {
        pending = false;
        const y = Math.max(0, window.scrollY);  // iOS bounces below 0 at the top
        const delta = y - lastY;
        lastY = y;
        if (y <= navbar.offsetHeight || busy()) {
            scrolledUp = 0;
            show();
        } else if (delta > 0) {
            scrolledUp = 0;
            navbar.classList.add('is-hidden');
        } else if (delta < 0) {
            scrolledUp -= delta;
            if (scrolledUp >= SHOW_AFTER) show();
        }
    }

    window.addEventListener('scroll', () => {
        if (pending) return;
        pending = true;
        window.requestAnimationFrame(update);
    }, {passive: true});
    navbar.addEventListener('focusin', show);
})();

// The magnifier leads to the search (the home page). With a mouse and keyboard it simply goes there, and the
// page's field is ready to type on; Chrome loads the page already while the pointer rests on the magnifier
// (speculation rules), so that it opens at once. On touch screens it opens a search field beside it, over the
// navbar, because phones open the keyboard only for a field tapped on the same page; Enter shows the results.
// On a page with a search field of its own (the search page, a category's or a location's page) the magnifier goes
// to that field first; a second click, nothing typed in between, goes on to the search of everything, with the
// words of the field. Ctrl+F (⌘F on a Mac) does the same, on a page without a field at once; on the search page a
// second one is left to the browser, to find on the page. Ctrl+K (⌘K) goes straight to the search of everything. Going to the field, a hint below the magnifier (below
// the field without a navbar) says so, until typing, going elsewhere or a few seconds, at most once a week in a
// browser (localStorage); the navbar stays meanwhile.
(() => {
    const button = document.querySelector('[data-navbar-search]');
    const form = document.getElementById('navbar-search');
    if (!button || !form) return;
    const input = form.elements.q;
    const pageField = () => document.querySelector('[data-live-search] input[name="q"]');
    const searchPath = new URL(button.href, window.location.href).pathname;
    const isSearchPage = field => new URL(field.form.action, window.location.href).pathname === searchPath;
    const direct = window.matchMedia('(hover: hover) and (pointer: fine)').matches;
    const mac = /Mac|iPhone|iPad/.test(navigator.platform || navigator.userAgent);
    const initial = pageField();
    if (direct && !(initial && isSearchPage(initial)) && window.HTMLScriptElement?.supports?.('speculationrules')) {
        const rules = document.createElement('script');
        rules.type = 'speculationrules';
        rules.textContent = JSON.stringify({
            prerender: [{where: {selector_matches: '[data-navbar-search]'}, eagerness: 'moderate'}],
        });
        document.head.append(rules);
    }
    let closedAt = 0;  // a tap on the magnifier first blurs the field: it closes, and the tap must not reopen it
    // The page's field the magnifier or Ctrl+F went to, with what it held: once more goes on to everything.
    let armed = null;
    const again = field => Boolean(field && armed?.field === field && field.value === armed.value);
    // Meanwhile the navbar stays, also while scrolling to the field, until the reader scrolls on their own.
    const navbar = document.querySelector('.app-navbar');
    function hold() {
        navbar?.setAttribute('data-held', '');
        navbar?.classList.remove('is-hidden');
    }
    const release = () => navbar?.removeAttribute('data-held');
    ['wheel', 'touchmove'].forEach(type => window.addEventListener(type, release, {passive: true}));

    // What the next click does, with the keys for it; the keys for everything at once, too.
    const findKeys = mac ? '⌘F' : button.dataset.shortcut;
    const allKeys = mac ? '⌘K' : button.dataset.shortcutAll;
    function label() {
        const field = pageField();
        const text = field && !isSearchPage(field) && !again(field) ? button.dataset.textPage : button.dataset.textAll;
        button.setAttribute('aria-label', text);
        button.title = text === button.dataset.textAll ? `${text} (${findKeys}, ${allKeys})`
            : `${text} (${findKeys}) · ${button.dataset.textAll} (${allKeys})`;
    }
    button.setAttribute('aria-keyshortcuts', mac ? 'Meta+F Meta+K' : 'Control+F Control+K');
    label();

    function disarm() {
        hideHint();
        release();
        if (!armed) return;
        armed = null;
        label();
    }

    // The hint that once more goes on to everything: in the style of a tooltip, said by screen readers, too. Once a
    // week is enough to remember it; the magnifier's tooltip says it, too.
    const HINT_TIME = 6000;
    const HINT_AGAIN = 7 * 24 * 60 * 60 * 1000;
    const HINT_KEY = 'navbar-search-hint-shown';
    function hintDue() {
        try {
            const shown = Number(window.localStorage.getItem(HINT_KEY));
            if (shown && Date.now() - shown < HINT_AGAIN) return false;
            window.localStorage.setItem(HINT_KEY, String(Date.now()));
        } catch {
            // Without storage (a private window, blocked site data) it shows each time.
        }
        return true;
    }
    let hint = null;
    let hintTimer = 0;
    let hintShownAt = 0;
    function showHint(field) {
        hideHint();
        if (isSearchPage(field) || !button.dataset.textAgain || !hintDue()) return;
        const keys = findKeys;
        hint = document.createElement('div');
        hint.className = 'navbar-search-hint';
        hint.setAttribute('role', 'status');
        hint.textContent = button.dataset.textAgain.replace('{keys}', () => keys);
        document.body.append(hint);
        // Where the magnifier ends up: the navbar may still be sliding back in (hold).
        const magnifier = button.getBoundingClientRect();
        const shift = navbar ? Math.min(0, navbar.getBoundingClientRect().top) : 0;
        const anchor = magnifier.width ? {left: magnifier.left, width: magnifier.width, bottom: magnifier.bottom - shift}
            : field.getBoundingClientRect();
        const width = hint.offsetWidth;
        const left = Math.min(Math.max(8, anchor.left + anchor.width / 2 - width / 2), window.innerWidth - width - 8);
        hint.style.left = `${left}px`;
        hint.style.top = `${anchor.bottom + 8}px`;
        hint.style.setProperty('--hint-arrow', `${anchor.left + anchor.width / 2 - left}px`);
        hintShownAt = Date.now();
        hintTimer = window.setTimeout(hideHint, HINT_TIME);
    }
    function hideHint() {
        window.clearTimeout(hintTimer);
        hint?.remove();
        hint = null;
    }
    // Scrolling leaves it behind; not the scroll to the field itself.
    window.addEventListener('scroll', () => {
        if (hint && Date.now() - hintShownAt > 300) hideHint();
    }, {passive: true});

    // Right of the magnifier, in its row.
    function place() {
        const box = button.getBoundingClientRect();
        const container = form.parentElement.getBoundingClientRect();
        form.style.setProperty('--navbar-search-left', `${box.right - container.left + 8}px`);
        form.style.setProperty('--navbar-search-top', `${box.top - container.top}px`);
    }
    window.addEventListener('resize', () => {
        if (!form.hidden) place();
    });

    function close() {
        form.hidden = true;
        button.setAttribute('aria-expanded', 'false');
        closedAt = Date.now();
    }

    function open(words = '') {
        place();
        if (words) input.value = words;
        form.hidden = false;
        button.setAttribute('aria-expanded', 'true');
        input.focus();
    }

    // The page's field, just below the navbar and the breadcrumbs, straight there: scrolling smoothly past a
    // location's lists would load their further rows on the way.
    function toField(field) {
        hold();
        const breadcrumbs = document.querySelector('[data-page-breadcrumbs]');
        const top = (navbar ? navbar.offsetHeight : 0) + (breadcrumbs ? breadcrumbs.offsetHeight : 0) + 8;
        const box = field.closest('form').getBoundingClientRect();
        if (box.top < top || box.bottom > window.innerHeight) {
            window.scrollTo({top: window.scrollY + box.top - top, behavior: 'instant'});
        }
        field.focus({preventScroll: true});
        field.setSelectionRange(field.value.length, field.value.length);
        armed = {field, value: field.value};
        label();
        showHint(field);
    }

    // The search of everything, with these words: the search page, on touch screens the field beside the magnifier.
    function everything(words) {
        disarm();
        if (direct) {
            const url = new URL(button.href, window.location.href);
            if (words) url.searchParams.set('q', words);
            window.location.assign(url);
        } else {
            open(words);
        }
    }

    button.addEventListener('click', event => {
        const field = pageField();
        if (field && (isSearchPage(field) || !again(field))) {
            event.preventDefault();
            toField(field);
            return;
        }
        const words = field ? field.value.trim() : '';
        if (direct) {
            if (words) {
                event.preventDefault();
                everything(words);
            }
            return;  // the link to the search page
        }
        event.preventDefault();
        disarm();
        if (!form.hidden) {
            close();
            return;
        }
        if (Date.now() - closedAt < 400) return;
        open(words);
    });

    // Ctrl (⌘ on a Mac) with this key alone, unless something on the page took it or a dialog or photo is open.
    const shortcut = (event, key) => (mac ? event.metaKey && !event.ctrlKey : event.ctrlKey && !event.metaKey)
        && !event.altKey && !event.shiftKey && event.key.toLowerCase() === key && !event.defaultPrevented
        && !document.querySelector('.modal.show, dialog[open]');
    document.addEventListener('keydown', event => {
        if (!shortcut(event, 'k')) return;
        // Straight to the search of everything, without the words of a page's field; on the search page into its field.
        event.preventDefault();
        const field = pageField();
        if (field && isSearchPage(field)) toField(field);
        else everything('');
    });
    document.addEventListener('keydown', event => {
        if (!shortcut(event, 'f')) return;
        const field = pageField();
        if (field && again(field)) {
            if (isSearchPage(field)) {
                disarm();  // the browser's find on the page
                return;
            }
            event.preventDefault();
            everything(field.value.trim());
        } else if (field) {
            event.preventDefault();
            toField(field);
        } else {
            event.preventDefault();
            everything('');
        }
    });
    // Typing, or going elsewhere, ends it: the next time goes to the field again.
    document.addEventListener('input', event => {
        if (event.target === armed?.field) disarm();
    });
    document.addEventListener('pointerdown', event => {
        if (!button.contains(event.target)) disarm();
    });
    document.addEventListener('focusin', event => {
        if (armed && event.target !== armed.field && !button.contains(event.target)) disarm();
    });
    // The page shown again from the back/forward cache starts anew.
    window.addEventListener('pageshow', disarm);

    input.addEventListener('keydown', event => {
        if (event.key !== 'Escape') return;
        close();
        button.focus();
    });
    input.addEventListener('blur', () => {
        if (!input.value.trim()) close();
    });
})();

// The breadcrumbs below it (base.html, breadcrumbs.css) stay at the top as well: what else stays there goes below
// them, by their height (--breadcrumbs-height), which grows where a path wraps. Where a path scrolls sideways
// (narrow screens), it shows its end, the page itself.
(() => {
    const breadcrumbs = document.querySelector('[data-page-breadcrumbs]');
    if (!breadcrumbs || !breadcrumbs.children.length) return;
    const measure = () => {
        document.documentElement.style.setProperty('--breadcrumbs-height', `${Math.floor(breadcrumbs.getBoundingClientRect().height)}px`);
        breadcrumbs.querySelectorAll('.breadcrumb-row').forEach(row => { row.scrollLeft = row.scrollWidth; });
    };
    measure();
    if (window.ResizeObserver) new ResizeObserver(measure).observe(breadcrumbs);
    else window.addEventListener('resize', measure);
})();
