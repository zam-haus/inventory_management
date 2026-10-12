// Home page: scanning a QR code opens its link if it points to a host this site
// serves. The host patterns (#scan-hosts) follow Django's ALLOWED_HOSTS: "*" is
// any host, ".example.org" is example.org and its subdomains.
(() => {
    const button = document.querySelector('[data-scan-link]');
    const hostList = document.getElementById('scan-hosts');
    if (!button || !hostList || !window.createBarcodeScanner) return;
    const hosts = JSON.parse(hostList.textContent).map(host => host.toLowerCase());
    const data = button.dataset;

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
        formats: ['qr_code'],
        labels: {title: data.title, hint: data.hint, added: data.opening, duplicate: data.foreign},
        onDetect: value => {
            const url = servedUrl(value);
            if (!url) return false;
            scanner.close();
            window.location.assign(url.href);
            return true;
        },
    });
    window.setupScanButton(button, scanner);
})();
