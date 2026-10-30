// The help as a layer over the page (help_overlay.html): links to the help page (the menu entry, "More about this")
// open it without leaving the page. The address becomes the help's (/help/#section), so reloading or sharing shows
// the help page itself; the browser's Back only closes the layer and Forward opens it again. The help is fetched
// from /help/ once and kept. Not on the help page itself, and without JavaScript the links lead there.
(() => {
    const overlay = document.getElementById('help-overlay');
    if (!overlay || typeof bootstrap === 'undefined') return;
    const modal = bootstrap.Modal.getOrCreateInstance(overlay);
    const body = overlay.querySelector('[data-help-overlay-body]');
    const helpPath = new URL(overlay.dataset.helpUrl, location.href).pathname;
    if (location.pathname === helpPath) return;
    const pageTitle = document.title;
    let content = null;  // Promise of the help's content

    function load() {
        content ??= fetch(helpPath, {headers: {Accept: 'text/html'}}).then(async response => {
            if (!response.ok) throw new Error(`help: ${response.status}`);
            const page = new DOMParser().parseFromString(await response.text(), 'text/html');
            const help = page.querySelector('.help-page');
            if (!help) throw new Error('help: no content');
            body.replaceChildren(document.adoptNode(help));
            return page.title;
        });
        content.catch(() => { content = null; });
        return content;
    }

    function scrollTo(anchor) {
        const section = anchor && body.querySelector(`#${CSS.escape(anchor)}`);
        if (section) section.scrollIntoView({block: 'start'});
        else body.scrollTop = 0;
    }

    // Bootstrap shows the layer after the backdrop faded in; it can only scroll from then on (still rolling down).
    const displayed = () => new Promise(resolve => {
        const check = () => (overlay.style.display === 'block' ? resolve() : requestAnimationFrame(check));
        check();
    });

    async function show(anchor) {
        modal.show();
        try {
            document.title = await load();
        } catch {
            location.assign(helpPath + (anchor ? `#${anchor}` : ''));  // the help page itself
            return;
        }
        await displayed();
        scrollTo(anchor);
    }

    const anchorOf = url => decodeURIComponent(url.hash.slice(1));
    const helpLink = event => {
        const link = event.target.closest('a[href]');
        if (!link || link.target || event.defaultPrevented || event.button !== 0
            || event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return null;
        const url = new URL(link.href, location.href);
        return url.origin === location.origin && url.pathname === helpPath ? url : null;
    };

    document.addEventListener('click', event => {
        // Within the help: its table of contents and links to its sections scroll the layer.
        if (overlay.contains(event.target)) {
            const link = event.target.closest('a[href^="#"]');
            const url = link ? new URL(link.href, location.href) : helpLink(event);
            if (!url) return;
            event.preventDefault();
            history.replaceState({helpOverlay: true}, '', helpPath + url.hash);
            scrollTo(anchorOf(url));
            return;
        }
        const url = helpLink(event);
        if (!url) return;
        event.preventDefault();
        if (history.state?.helpOverlay) history.replaceState({helpOverlay: true}, '', helpPath + url.hash);
        else history.pushState({helpOverlay: true}, '', helpPath + url.hash);
        show(anchorOf(url));
    });

    // Closing (button, Esc, outside) goes back to the page's own entry in the history.
    overlay.addEventListener('hide.bs.modal', () => {
        if (history.state?.helpOverlay) history.back();
    });
    overlay.addEventListener('hidden.bs.modal', () => { document.title = pageTitle; });

    window.addEventListener('popstate', event => {
        if (event.state?.helpOverlay) show(anchorOf(location));
        else if (overlay.classList.contains('show')) modal.hide();
    });
})();
