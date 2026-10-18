// While a modal is open, fit it to the part of the screen the on-screen keyboard leaves free.
// Phones do not shrink the page for the keyboard (iOS never, Android by default), so a modal of
// full screen height keeps its footer (Save) behind the keyboard, out of reach of scrolling.
// modals.css places .modal by --visible-top and --visible-height.
(() => {
    const viewport = window.visualViewport;
    if (!viewport) return;
    const root = document.documentElement;
    let open = 0;

    function update(event) {
        // Zoomed in, the visible part is no measure for the modal.
        if (!open || Math.abs(viewport.scale - 1) > 0.01) {
            root.style.removeProperty('--visible-top');
            root.style.removeProperty('--visible-height');
            return;
        }
        root.style.setProperty('--visible-top', `${viewport.offsetTop}px`);
        root.style.setProperty('--visible-height', `${viewport.height}px`);
        if (event?.type !== 'resize') return;
        // The keyboard came up or went away: keep the focused field visible in the shrunk body.
        const field = document.activeElement;
        const body = field?.closest('.modal-body');
        if (!body) return;
        const fieldBox = field.getBoundingClientRect();
        const bodyBox = body.getBoundingClientRect();
        if (fieldBox.bottom > bodyBox.bottom) body.scrollTop += fieldBox.bottom - bodyBox.bottom;
        else if (fieldBox.top < bodyBox.top) body.scrollTop -= bodyBox.top - fieldBox.top;
    }

    document.addEventListener('show.bs.modal', event => {
        if (event.defaultPrevented) return;  // it stays closed
        open += 1;
        update();
    });
    document.addEventListener('hidden.bs.modal', () => { open = Math.max(0, open - 1); update(); });
    viewport.addEventListener('resize', update);
    viewport.addEventListener('scroll', update);
})();
