// What went wrong in this browser tab, for "Report a problem" (problem_report.js): script errors, images, scripts
// or stylesheets that did not load, and requests (fetch, XMLHttpRequest) answered with an error or not at all.
// The last 20, kept across the pages of the tab (sessionStorage). Loaded first in <head>, so it also notices what
// goes wrong while a page loads.
(() => {
    const KEY = 'problem-report-log';
    const KEEP = 20;
    const page = location.pathname + location.search;
    let entries = [];
    try { entries = JSON.parse(sessionStorage.getItem(KEY)) || []; } catch { /* private mode, blocked storage */ }

    const cut = (text, length = 2000) => String(text ?? '').slice(0, length);
    function add(entry) {
        entries = [...entries, {time: new Date().toISOString(), page, ...entry}].slice(-KEEP);
        try { sessionStorage.setItem(KEY, JSON.stringify(entries)); } catch { /* kept for this page only */ }
    }
    window.problemReportLog = () => entries.slice();

    window.addEventListener('error', event => {
        const target = event.target;
        if (target instanceof Element) {  // a resource; it does not bubble, hence the capture
            const address = target.currentSrc || target.src || target.href;
            if (address) add({kind: 'load', message: `${target.tagName.toLowerCase()} ${cut(address, 500)}`});
            return;
        }
        add({kind: 'error', message: cut(event.message),
             source: event.filename ? `${event.filename}:${event.lineno}:${event.colno}` : '', stack: cut(event.error?.stack)});
    }, true);
    window.addEventListener('unhandledrejection', event => {
        const reason = event.reason;
        add({kind: 'rejection', message: cut(reason?.message ?? reason), stack: cut(reason?.stack)});
    });

    const request = (method, url, status, message) =>
        add({kind: 'request', method: String(method || 'GET').toUpperCase(), url: cut(url, 500), status, message: cut(message)});

    const originalFetch = window.fetch;
    if (originalFetch) {
        window.fetch = function (input, init) {
            const method = init?.method || (input instanceof Request ? input.method : 'GET');
            const url = input instanceof Request ? input.url : String(input);
            return originalFetch.apply(this, arguments).then(response => {
                if (response.status >= 400) request(method, url, response.status);
                return response;
            }, error => {
                if (error?.name !== 'AbortError') request(method, url, 0, error?.message);
                throw error;
            });
        };
    }

    const open = XMLHttpRequest.prototype.open;
    XMLHttpRequest.prototype.open = function (method, url) {
        this.problemReportRequest = {method, url: String(url)};
        return open.apply(this, arguments);
    };
    const send = XMLHttpRequest.prototype.send;
    XMLHttpRequest.prototype.send = function () {
        let aborted = false;
        this.addEventListener('abort', () => { aborted = true; });
        this.addEventListener('loadend', () => {
            const {method, url} = this.problemReportRequest || {};
            if (!aborted && (this.status === 0 || this.status >= 400)) request(method, url, this.status);
        });
        return send.apply(this, arguments);
    };
})();
