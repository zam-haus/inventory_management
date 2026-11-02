// The small maps: in the location window (inventory/location_info.js, maps/slots/location_info_body.html) and after
// the photos of result rows (inventory/results.js, maps/slots/result_slides.html): the level with what they show
// highlighted (a location or the place it is in, a unique item, an item's places). Leaflet and the map scripts are
// loaded the first time one is shown (pages with a map have them already); a row's map is drawn once it is in view.
(function () {
    'use strict';

    var assets = JSON.parse(document.currentScript.dataset.assets);
    var loading = null;
    var levels = {};  // url → the level's data, loaded once for all maps of the page (many rows lie on one level)

    function asset(url) {
        return new Promise(function (resolve, reject) {
            var element;
            if (/\.css(\?|$)/.test(url)) {
                element = document.createElement('link');
                element.rel = 'stylesheet';
                element.href = url;
            } else {
                element = document.createElement('script');
                element.src = url;
                element.async = false;  // in order: Leaflet first
            }
            element.onload = resolve;
            element.onerror = reject;
            document.head.appendChild(element);
        });
    }

    function scripts() {
        if (window.ZamMap) {
            return Promise.resolve();
        }
        if (!loading) {
            loading = Promise.all(assets.map(asset));
        }
        return loading;
    }

    function level(url) {
        if (!levels[url]) {
            levels[url] = ZamMap.load(url).catch(function (error) {
                delete levels[url];  // tried again with the next map
                throw error;
            });
        }
        // Each map draws its own copy.
        return levels[url].then(function (data) { return JSON.parse(JSON.stringify(data)); });
    }

    // The map in `element` (data-url: the level's data, data-focus: what to highlight, feature ids separated by
    // commas), highlighted as on the large map with ?p=…, without its popup: the window or the caption names it
    // already, and the popup would cover it on the small map. No map rather than an empty box if it fails.
    function draw(element, options) {
        return scripts().then(function () {
            var map = ZamMap.create(element, Object.assign({zoomControl: true}, options));
            return level(element.dataset.url).then(function (data) {
                var drawn = ZamMap.draw(map, data);
                var focused = ZamMap.focusAll(drawn, element.dataset.focus.split(','));
                if (!focused && drawn.bounds) {
                    map.fitBounds(drawn.bounds, {padding: [10, 10], animate: false});
                }
            });
        }).catch(function () {
            element.remove();
        });
    }

    document.addEventListener('location-info:shown', function (event) {
        var element = event.target.querySelector('[data-map-mini]');
        if (element) {
            draw(element);
        }
    });

    // A row's maps once in view in the strip of its photos. Swipes and the arrow keys go through the photos and
    // rows there, so the map moves only by its buttons (and dragging with a mouse), as the grey box's (map_place.js).
    var observer = window.IntersectionObserver ? new IntersectionObserver(function (seen) {
        seen.filter(function (entry) { return entry.isIntersecting; }).forEach(function (entry) {
            observer.unobserve(entry.target);
            draw(entry.target, {dragging: !L.Browser.mobile, touchZoom: false, scrollWheelZoom: false,
                keyboard: false});
        });
    }) : null;  // once any of it shows: the strip hides those beside it

    document.addEventListener('result-viewer:shown', function (event) {
        var elements = event.target.querySelectorAll('[data-map-slide]');
        if (!elements.length) {
            return;
        }
        // The styles first (maps.css): the map's size.
        scripts().then(function () {
            elements.forEach(function (element) {
                if (observer) {
                    observer.observe(element);
                } else {
                    draw(element, {dragging: false, touchZoom: false, scrollWheelZoom: false, keyboard: false});
                }
            });
        }).catch(function () {
            elements.forEach(function (element) { element.remove(); });
        });
    });
})();
