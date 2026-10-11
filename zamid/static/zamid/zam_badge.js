// Scan a new ZAM ID label from an item or location page and attach it.
(() => {
    if (!window.createBarcodeScanner) return;
    for (const form of document.querySelectorAll('[data-zamid-claim]')) {
        const button = form.querySelector('[data-zamid-scan]');
        const field = form.querySelector('input[name="code"]');
        if (!button || !field) continue;
        const data = button.dataset;
        const scanner = window.createBarcodeScanner({
            formats: ['qr_code'],
            labels: {title: data.title, hint: data.hint, added: data.added, duplicate: data.duplicate},
            onDetect: value => {
                field.value = value;
                // Let the dialog confirm the scan before the page submits.
                setTimeout(() => { scanner.close(); form.requestSubmit(); }, 400);
                return true;
            },
        });
        button.hidden = false;
        button.addEventListener('click', () => scanner.open());
    }
})();
