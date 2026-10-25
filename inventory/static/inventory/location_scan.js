// Location search fields (widgets.LocationSelect): the QR button beside each scans a location
// label or a label ID and selects that location in the field. Without a camera the button
// stays disabled and says why (barcode_scanner.js).
(() => {
    async function choose(button, value) {
        const group = button.closest('.location-scan-group');
        const select = group.querySelector('select');
        const status = group.nextElementSibling;
        const data = button.dataset;
        try {
            const response = await fetch(`${data.lookupUrl}?q=${encodeURIComponent(value)}`, {credentials: 'same-origin'});
            const result = await response.json();
            if (!response.ok) throw new Error(result.error);
            select.querySelectorAll(`option[value="${CSS.escape(String(result.id))}"]`).forEach(option => option.remove());
            // The field shows its options as HTML (widgets.LocationSelect: title, name, code chip).
            const option = new Option(result.html || result.text, result.id, true, true);
            if (window.jQuery) window.jQuery(select).append(option).trigger('change');
            else {
                select.append(option);
                select.value = String(result.id);
                select.dispatchEvent(new Event('change', {bubbles: true}));
            }
            status.textContent = data.found.replace('{location}', result.text);
            status.classList.remove('text-danger');
        } catch (error) {
            status.textContent = error.message || String(error);
            status.classList.add('text-danger');
        }
    }

    function init() {
        const buttons = document.querySelectorAll('[data-location-scan]');
        if (!buttons.length || !window.createBarcodeScanner) return;
        const labels = buttons[0].dataset;
        let target = null;
        // One scanner for all fields; it fills the field whose button opened it.
        const scanner = window.createBarcodeScanner({
            formats: ['qr_code'],
            labels: {title: labels.title, hint: labels.hint, added: labels.added, duplicate: labels.duplicate},
            onDetect: value => {
                scanner.close();
                if (target) choose(target, value);
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
