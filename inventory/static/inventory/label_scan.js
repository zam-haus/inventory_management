// Label ID fields (widgets.LabelCodeInput): the QR button beside each scans a label; what it holds (the label's URL
// or its ID) goes into the field, which reads the ID from it when the form is saved, and the pre-printed label is
// chosen. Without a camera the button stays disabled and says why (barcode_scanner.js).
(() => {
    function fill(button, value) {
        const input = button.closest('.label-scan-group').querySelector('input');
        input.value = value;
        input.dispatchEvent(new Event('input', {bubbles: true}));
        // The pre-printed label it is (label_choice beside it: NewUniqueItemForm, FirstUniqueItemForm).
        const name = input.name.replace(/label_code$/, 'label_choice');
        const reserved = document.querySelector(`input[name="${CSS.escape(name)}"][value="reserved"]`);
        if (reserved && !reserved.checked) {
            reserved.checked = true;
            reserved.dispatchEvent(new Event('change', {bubbles: true}));
        }
    }

    function init() {
        const buttons = document.querySelectorAll('[data-label-scan]');
        if (!buttons.length || !window.createBarcodeScanner) return;
        const labels = buttons[0].dataset;
        let target = null;
        // One scanner for all fields; it fills the field whose button opened it.
        const scanner = window.createBarcodeScanner({
            formats: ['qr_code'],
            labels: {title: labels.title, hint: labels.hint, added: labels.added, duplicate: labels.duplicate},
            onDetect: value => {
                scanner.close();
                if (target) fill(target, value);
                return true;
            },
        });
        buttons.forEach(button => {
            button.addEventListener('click', () => { target = button; });
            window.setupScanButton(button, scanner);
        });
    }

    // The form media may come before the scanner scripts at the end of the page.
    if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', init);
    else init();
})();
