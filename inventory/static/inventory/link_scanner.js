// Scan buttons ([data-scan-link]: navbar, search page): scanning a QR code opens its link
// if it points to a host this site serves; a product barcode (EAN-13, EAN-8) is searched for (data-search-url). The host patterns (#scan-hosts) follow Django's ALLOWED_HOSTS: "*" is
// any host, ".example.org" is example.org and its subdomains.
(() => {
    const buttons = document.querySelectorAll('[data-scan-link]');
    const hostList = document.getElementById('scan-hosts');
    if (!buttons.length || !hostList || !window.createBarcodeScanner) return;
    const hosts = JSON.parse(hostList.textContent).map(host => host.toLowerCase());
    const data = buttons[0].dataset;

    function servedUrl(text) {
        let url;
        try {
            url = new URL(text.trim());
        } catch {
            return null;
        }
        if (url.protocol !== 'https:' && url.protocol !== 'http:') return null;
        const host = url.hostname;
        const served = hosts.some(pattern => pattern === '*' || host === pattern
            || (pattern.startsWith('.') && (host === pattern.slice(1) || host.endsWith(pattern))));
        return served ? url : null;
    }

    const scanner = window.createBarcodeScanner({
        formats: ['qr_code', 'ean_13', 'ean_8'],
        labels: {title: data.title, hint: data.hint, added: data.opening, duplicate: data.foreign},
        onDetect: (value, format) => {
            if (format !== 'qr_code') {
                scanner.close();
                const search = new URL(data.searchUrl, window.location.href);
                search.searchParams.set('q', value.trim());
                window.location.assign(search.href);
                return true;
            }
            const url = servedUrl(value);
            if (!url) return false;
            scanner.close();
            window.location.assign(url.href);
            return true;
        },
    });
    buttons.forEach(button => window.setupScanButton(button, scanner));
})();
