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
// data-modal-focus="without-keyboard" focuses the field without opening the keyboard.
(() => {
    const TEXT = 'textarea, input:not([type=checkbox], [type=radio], [type=file], [type=range], [type=color], [type=button], [type=submit], [type=reset])';

    document.addEventListener('show.bs.modal', event => {
        const modal = event.target;
        const field = modal.querySelector('[data-modal-focus]');
        if (event.defaultPrevented || !field?.matches(TEXT) || field.dataset.modalFocus === 'without-keyboard') return;
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

// [data-modal-open="<id>"] opens that modal instead of following its link, which stays the
// fallback without JavaScript.
document.addEventListener('click', event => {
    const opener = event.target.closest('[data-modal-open]');
    const modal = opener && document.getElementById(opener.dataset.modalOpen);
    if (!modal || !window.bootstrap) return;
    event.preventDefault();
    window.bootstrap.Modal.getOrCreateInstance(modal).show(opener);
});

// Closing a modal forgets what was changed in it, without reloading the page: its forms go back to
// how the page brought them (also choices an autocomplete added, and marked mistakes). This runs
// before the dialogs' own listeners (capture), so a dialog shown again right away keeps what it sets
// then. Dialogs with more state than their fields reset it on their form's "reset" event (the fields
// are reset just after it: read them in a microtask).
(() => {
    const options = new WeakMap();  // select → the values of its options as the page brought them
    document.querySelectorAll('.modal select').forEach(select => {
        options.set(select, new Set([...select.options].map(option => option.value)));
    });

    document.addEventListener('hidden.bs.modal', event => {
        const modal = event.target;
        const forms = modal.matches('form') ? [modal] : [...modal.querySelectorAll('form')];
        forms.forEach(form => {
            form.querySelectorAll('select').forEach(select => {
                const known = options.get(select);
                if (known) [...select.options].filter(option => !known.has(option.value)).forEach(option => option.remove());
            });
            form.reset();
            form.querySelectorAll('.is-invalid').forEach(field => field.classList.remove('is-invalid'));
            // Autocompletes (select2) show the reset value again.
            if (window.jQuery?.fn?.select2) window.jQuery(form).find('select').trigger('change.select2');
        });
    }, true);
})();
