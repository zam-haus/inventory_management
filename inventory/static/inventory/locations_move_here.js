(() => {
    const button = document.querySelector('[data-scan-locations]');
    const field = document.getElementById('id_identifiers');
    if (!button || !field || !window.createBarcodeScanner) return;
    const data = button.dataset;
    const scanner = window.createBarcodeScanner({
        formats: ['qr_code'],
        labels: {title: data.title, hint: data.hint, added: data.added, duplicate: data.duplicate},
        onDetect: value => {
            if (field.value.split(/[\s;]+/).includes(value)) return false;
            // One scanned label per line, after whatever was typed already.
            const typed = field.value.replace(/\s+$/, '');
            field.value = `${typed ? `${typed}\n` : ''}${value}\n`;
            field.scrollTop = field.scrollHeight;
            return true;
        },
    });
    button.hidden = false;
    button.addEventListener('click', () => scanner.open());
})();
