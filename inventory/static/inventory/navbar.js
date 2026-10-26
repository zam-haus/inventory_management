// The navbar sticks to the top (sticky-top), slides away while scrolling down and comes back
// as soon as the page is scrolled up a little. It stays at the top of the page, while its menus
// are open and while it has the keyboard focus.
(() => {
    const navbar = document.querySelector('.app-navbar');
    if (!navbar) return;
    const SHOW_AFTER = 10;  // px scrolled up before it comes back
    let lastY = Math.max(0, window.scrollY);
    let scrolledUp = 0;
    let pending = false;

    const show = () => navbar.classList.remove('is-hidden');
    const busy = () => navbar.querySelector('.navbar-collapse.show, .navbar-collapse.collapsing, .dropdown-menu.show')
        || navbar.contains(document.activeElement);

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
// On the search page itself the magnifier goes to the page's own field.
(() => {
    const button = document.querySelector('[data-navbar-search]');
    const form = document.getElementById('navbar-search');
    if (!button || !form) return;
    const input = form.elements.q;
    const searchPage = () => document.querySelector('[data-live-search] input[name="q"]');
    const direct = window.matchMedia('(hover: hover) and (pointer: fine)').matches;
    if (direct && !searchPage() && window.HTMLScriptElement?.supports?.('speculationrules')) {
        const rules = document.createElement('script');
        rules.type = 'speculationrules';
        rules.textContent = JSON.stringify({
            prerender: [{where: {selector_matches: '[data-navbar-search]'}, eagerness: 'moderate'}],
        });
        document.head.append(rules);
    }
    let closedAt = 0;  // a tap on the magnifier first blurs the field: it closes, and the tap must not reopen it

    // Right of the magnifier, in its row (also while the menu below is open).
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

    button.addEventListener('click', event => {
        const field = searchPage();
        if (direct && !field) return;  // the link to the search page
        event.preventDefault();
        if (field) {
            window.scrollTo({top: 0});
            field.focus();
            field.setSelectionRange(field.value.length, field.value.length);
            return;
        }
        if (!form.hidden) {
            close();
            return;
        }
        if (Date.now() - closedAt < 400) return;
        place();
        form.hidden = false;
        button.setAttribute('aria-expanded', 'true');
        input.focus();
    });
    input.addEventListener('keydown', event => {
        if (event.key !== 'Escape') return;
        close();
        button.focus();
    });
    input.addEventListener('blur', () => {
        if (!input.value.trim()) close();
    });
})();
