// Move a unique item: choose the new location in the search, or scan its
// label (a ZAM ID or location label). Without JavaScript, "Move" opens the edit form.
(() => {
    const modalElement = document.getElementById('move-modal');
    if (!modalElement || typeof bootstrap === 'undefined') return;
    // The scanner opens its own dialog above this one, which needs the focus.
    const modal = new bootstrap.Modal(modalElement, {focus: false});
    document.querySelectorAll('[data-move-open]').forEach(button => button.addEventListener('click', event => {
        event.preventDefault();
        modal.show(button);
    }));
    const select = modalElement.querySelector('select[name="location"]');
    const button = modalElement.querySelector('[data-scan-location]');
    const status = modalElement.querySelector('[data-scan-status]');
    if (!button || !select || !window.createBarcodeScanner) return;
    const data = button.dataset;

    function choose(location) {
        const option = new Option(location.text, location.id, true, true);
        if (window.jQuery) window.jQuery(select).append(option).trigger('change');
        else {
            select.append(option);
            select.value = String(location.id);
        }
        status.textContent = data.found.replace('{location}', location.text);
        status.classList.remove('text-danger');
    }

    async function lookup(value) {
        try {
            const response = await fetch(`${data.lookupUrl}?q=${encodeURIComponent(value)}`, {credentials: 'same-origin'});
            const result = await response.json();
            if (!response.ok) throw new Error(result.error);
            choose(result);
        } catch (error) {
            status.textContent = error.message || String(error);
            status.classList.add('text-danger');
        }
    }

    const scanner = window.createBarcodeScanner({
        formats: ['qr_code'],
        labels: {title: data.title, hint: data.hint, added: data.added, duplicate: data.duplicate},
        onDetect: value => {
            // One label is enough: show the result in the move dialog.
            scanner.close();
            lookup(value);
            return true;
        },
    });
    button.hidden = false;
    button.addEventListener('click', () => scanner.open());
    modalElement.addEventListener('hidden.bs.modal', () => {
        status.textContent = '';
        status.classList.remove('text-danger');
    });
})();
