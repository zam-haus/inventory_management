(() => {
    const field = document.getElementById('id_barcode_data');
    const config = document.getElementById('item-barcode-scanner');
    if (!field || field.disabled || !config || !window.createBarcodeScanner) return;
    const data = config.dataset;
    const scanner = window.createBarcodeScanner({
        formats: ['ean_13', 'ean_8'],
        labels: {title: data.title, hint: data.hint, added: data.added, duplicate: data.duplicate},
        onDetect: (value, format) => {
            const codes = field.value.split('\n').map(line => line.trim().split(/\s+/)[0]).filter(Boolean);
            if (codes.includes(value)) return false;
            // Lines read "<code> <type>", e.g. "4006381333931 ean_13".
            const typed = field.value.replace(/\s+$/, '');
            field.value = `${typed ? `${typed}\n` : ''}${value} ${format}\n`;
            return true;
        },
    });
    // Disabled until the camera is known to be usable; otherwise it says why.
    const wrapper = document.createElement('span');
    wrapper.className = 'disabled-action';
    wrapper.tabIndex = 0;
    const button = document.createElement('button');
    button.type = 'button';
    button.className = 'btn btn-primary';
    button.textContent = data.buttonLabel;
    button.disabled = true;
    wrapper.append(button);
    field.after(wrapper);
    window.setupScanButton(button, scanner);
})();
