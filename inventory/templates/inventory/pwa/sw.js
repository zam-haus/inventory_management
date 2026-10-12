// Shows the offline page when a page cannot be loaded. Nothing else is cached:
// pages always come from the network, other requests are left to the browser.
const CACHE = "{{ cache }}";
const OFFLINE_URL = "{{ offline_url }}";

self.addEventListener("install", (event) => {
    event.waitUntil(caches.open(CACHE).then((cache) => cache.add(OFFLINE_URL)).then(() => self.skipWaiting()));
});

self.addEventListener("activate", (event) => {
    event.waitUntil((async () => {
        for (const key of await caches.keys()) {
            if (key !== CACHE) await caches.delete(key);
        }
        // Starts the page request while the worker boots, so pages load as fast as without it.
        await self.registration.navigationPreload?.enable();
        await self.clients.claim();
    })());
});

self.addEventListener("fetch", (event) => {
    const request = event.request;
    if (request.mode !== "navigate" || request.method !== "GET") return;
    event.respondWith((async () => {
        try {
            return (await event.preloadResponse) || (await fetch(request));
        } catch {
            return (await caches.match(OFFLINE_URL)) || Response.error();
        }
    })());
});
