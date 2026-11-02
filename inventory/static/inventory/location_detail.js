(() => {
    const detail = document.querySelector('.location-detail[data-lightbox-gallery-label]');
    if (!detail || !window.setupPhotoLightbox) return;
    const data = detail.dataset;
    const labels = {
        gallery: data.lightboxGalleryLabel, close: data.lightboxCloseLabel,
        previous: data.lightboxPreviousLabel, next: data.lightboxNextLabel,
        error: data.lightboxErrorMessage, retry: data.lightboxRetryLabel,
        loading: data.lightboxLoadingLabel,
    };
    const setup = links => window.setupPhotoLightbox(links, {className: 'location-lightbox', labels});
    // The overview photo and each quick-item photo open alone. Those of the items and unique items open below their
    // rows (results.js).
    const groups = [
        [...detail.querySelectorAll('a.location-overview-photo')],
        ...[...detail.querySelectorAll('.location-quick-readonly a.location-quick-photo')].map(link => [link]),
    ];
    groups.forEach(setup);
    // Editable quick-items (location_quick_items.js) set up their single photo, also once it is uploaded.
    window.setupLocationPhotoLink = link => setup([link]);
})();

// The headings of the lists stay at the top (location_detail.css): the category headings of the items go below
// them (--panel-heading-height), and a row the keys move to below both (--location-sticky).
(() => {
    const headings = [...document.querySelectorAll('.location-stored-items > .location-panel-heading, .location-children > .location-panel-heading')];
    if (!headings.length) return;
    const measure = () => {
        let highest = 0;
        headings.forEach(heading => {
            // Rounded down: the category headings overlap it by a fraction of a pixel rather than leave a gap.
            const height = Math.floor(heading.getBoundingClientRect().height);
            heading.parentElement.style.setProperty('--panel-heading-height', `${height}px`);
            highest = Math.max(highest, height);
        });
        const group = document.querySelector('.location-panel .result-group');
        document.documentElement.style.setProperty('--location-sticky', `${highest + (group ? group.offsetHeight : 0) + 8}px`);
    };
    measure();
    if (window.ResizeObserver) {
        const observer = new ResizeObserver(measure);
        headings.forEach(heading => observer.observe(heading));
    } else {
        window.addEventListener('resize', measure);
    }
})();

// The jump buttons to the sections (base.html, page_jump.js): the one of the section being read marked.
//
// Going to a section (a jump button, the overview's counts, a link with its #anchor) goes straight there, as smooth
// scrolling past a list would load its further rows (results.js) on the way. Rows that load above it still push it
// down, so it is held in place until the reader scrolls or a few seconds have passed.
(() => {
    const sections = [...document.querySelectorAll('.location-panel[id]')];
    const navbar = document.querySelector('.app-navbar');
    const breadcrumbs = document.querySelector('[data-page-breadcrumbs]');
    // Sections go just below the navbar and the breadcrumbs, also while the navbar is hidden, so that the one gone
    // to is the one marked.
    const top = () => (navbar ? navbar.offsetHeight : 0) + (breadcrumbs ? breadcrumbs.offsetHeight : 0);

    const buttons = [...document.querySelectorAll('[data-page-jump] a[href^="#"]:not([data-page-jump-top])')];
    // The sections at the top of the page: one per column on wide screens (items beside the sub-locations). At the
    // end of the page, the last one that has come into view, even if it is too short to reach the top.
    function current() {
        const line = top() + 16;
        const atEnd = window.innerHeight + window.scrollY >= document.documentElement.scrollHeight - 2;
        const reading = sections.filter(section => {
            const box = section.getBoundingClientRect();
            return box.top <= (atEnd ? window.innerHeight - 1 : line) && box.bottom > line;
        });
        return (atEnd ? reading.slice(-1) : reading).map(section => `#${section.id}`);
    }
    let pending = false;
    function update() {
        pending = false;
        const hashes = current();
        buttons.forEach(button => {
            if (hashes.includes(button.hash)) button.setAttribute('aria-current', 'location');
            else button.removeAttribute('aria-current');
        });
    }
    if (buttons.length) {
        window.addEventListener('scroll', () => { if (!pending) { pending = true; requestAnimationFrame(update); } }, {passive: true});
        document.addEventListener('results:loaded', update);
        update();
    }

    let held = null;
    let until = 0;
    const hold = target => { held = target; until = Date.now() + 4000; };
    const place = () => {
        if (held && Date.now() < until) window.scrollTo({top: window.scrollY + held.getBoundingClientRect().top - top(), behavior: 'instant'});
    };
    document.addEventListener('click', event => {
        const link = event.target.closest('a[href^="#"]');
        const target = link && link.hash.length > 1 && document.getElementById(link.hash.slice(1));
        if (!sections.includes(target) || event.defaultPrevented || event.button !== 0
            || event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return;
        event.preventDefault();
        history.pushState(null, '', link.hash);
        hold(target);
        place();
    });
    document.addEventListener('results:loaded', place);
    ['wheel', 'touchstart', 'keydown', 'pointerdown'].forEach(type => window.addEventListener(type, () => { held = null; }, {passive: true}));
    const initial = location.hash.length > 1 && document.getElementById(location.hash.slice(1));
    if (sections.includes(initial)) { hold(initial); place(); }
})();
