// The small map in the location window (inventory/location_info.js, maps/slots/location_info_body.html): the level
// with the location, or the place it is in, highlighted. Leaflet and the map scripts are loaded the first time a
// window has a map (pages with a map have them already).
(function () {
    'use strict';

    var assets = JSON.parse(document.currentScript.dataset.assets);
    var loading = null;

    function load(url) {
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
            loading = Promise.all(assets.map(load));
        }
        return loading;
    }

    document.addEventListener('location-info:shown', function (event) {
        var element = event.target.querySelector('[data-map-mini]');
        if (!element) {
            return;
        }
        scripts().then(function () {
            var map = ZamMap.create(element, {zoomControl: true});
            return ZamMap.load(element.dataset.url).then(function (data) {
                var drawn = ZamMap.draw(map, data);
                var focused = ZamMap.highlight(drawn, element.dataset.focus);
                var bounds = focused ? focused.getBounds() : drawn.bounds;
                if (bounds) {
                    map.fitBounds(bounds, {maxZoom: 21, padding: [30, 30], animate: false});
                }
                if (focused) {
                    focused.openPopup();  // its name and chip on the map, as on the large map with ?p=…
                }
            });
        }).catch(function () {
            element.remove();  // no map rather than an empty box
        });
    });
})();
