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

// Phones open the keyboard only for a field that is focused during the tap itself, but a modal's
// fields are still hidden then. So the field marked data-modal-focus gets a stand-in that takes
// the focus at once and hands it, together with the keyboard, to the field once it is shown.
(() => {
    const TEXT = 'textarea, input:not([type=checkbox], [type=radio], [type=file], [type=range], [type=color], [type=button], [type=submit], [type=reset])';

    document.addEventListener('show.bs.modal', event => {
        const modal = event.target;
        const field = modal.querySelector('[data-modal-focus]');
        if (event.defaultPrevented || !field?.matches(TEXT)) return;
        const standIn = document.createElement('input');
        standIn.className = 'modal-focus-stand-in';
        standIn.type = field.type === 'number' ? 'number' : 'text';  // the same kind of keyboard
        if (field.inputMode) standIn.inputMode = field.inputMode;
        standIn.tabIndex = -1;
        standIn.setAttribute('aria-hidden', 'true');
        document.body.append(standIn);
        standIn.focus({preventScroll: true});
        // Bootstrap focuses the dialog itself once it is shown, which would close the keyboard.
        modal.focus = options => field.focus(options);
        modal.addEventListener('shown.bs.modal', () => {
            delete modal.focus;
            standIn.remove();
        }, {once: true});
    });

    document.addEventListener('shown.bs.modal', event => {
        const field = event.target.querySelector('[data-modal-focus]');
        if (!field) return;
        field.focus();
        if (field.matches(TEXT)) field.select();
    });
})();
