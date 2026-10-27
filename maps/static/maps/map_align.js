// Placing a floor plan (maps/plan_align.html): pairs of control points, a pixel on the plan (left) and where it is
// (right: clicked on the map with the plans already placed, or typed as "latitude, longitude"). The server fits the
// plan to them (maps/geo.py). Cropping: an outline drawn on the plan (rectangle or polygon, with Leaflet-Geoman),
// previewed with everything outside it darkened, sent as fractions of the page (maps/render.py crop_polygon).
(function () {
    'use strict';

    var root = document.querySelector('[data-map-align]');
    if (!root) {
        return;
    }
    var config = JSON.parse(document.getElementById('map-align-config').textContent);
    var hint = document.querySelector('[data-align-hint]');
    var rows = document.querySelector('[data-align-points]');
    var input = document.querySelector('[data-align-points-input]');
    var points = (config.controlPoints || []).map(function (p) { return {pixel: p.pixel, lonlat: p.lonlat}; });
    var mode = 'plan';  // what the next click sets: 'plan' (a pixel), 'place' (its coordinates); or 'crop'
    var cropLayer = null, cropMask = null;

    // Left: the plan in pixels (y downwards; Leaflet's simple CRS has y upwards, so pixel y is -lat).
    var planMap = L.map(root.querySelector('[data-align-plan]'), {crs: L.CRS.Simple, minZoom: -6, maxZoom: 4,
        zoomSnap: 0.25, attributionControl: false});
    var size = [config.width, config.height];
    var planBounds = L.latLngBounds([[-size[1], 0], [0, size[0]]]);
    config.tiles.forEach(function (tile) {  // the plan from its tiles (maps/views.py plan_tiles)
        L.imageOverlay(tile.url, [[-(tile.y + tile.h), tile.x], [-tile.y, tile.x + tile.w]]).addTo(planMap);
    });
    planMap.fitBounds(planBounds);
    var planMarks = L.layerGroup().addTo(planMap);

    // Right: the level with the plans already placed.
    var placeMap = ZamMap.create(root.querySelector('[data-align-map]'));
    ZamMap.layerControl(placeMap);
    var placeMarks = L.layerGroup().addTo(placeMap);
    // A chosen point: not interactive, so a click on it picks (more exactly) through it.
    var markIcon = L.divIcon({className: 'map-align-mark', iconSize: [25, 25], tooltipAnchor: [10, 0]});
    if (config.data) {
        ZamMap.load(config.data).then(function (data) {
            var drawn = ZamMap.draw(placeMap, data, {interactive: false});
            if (drawn.bounds) {
                placeMap.fitBounds(drawn.bounds);
            }
        });
    }

    function say(text) {
        hint.textContent = text || '';
    }

    function number(value, digits) {
        return value === undefined || value === null ? '' : Number(value).toFixed(digits);
    }

    function render() {
        planMarks.clearLayers();
        placeMarks.clearLayers();
        rows.textContent = '';
        points.forEach(function (point, index) {
            var name = String(index + 1);
            if (point.pixel) {
                L.marker([-point.pixel[1], point.pixel[0]], {icon: markIcon, interactive: false, keyboard: false})
                    .bindTooltip(name, {permanent: true, direction: 'right'}).addTo(planMarks);
            }
            if (point.lonlat) {
                L.marker([point.lonlat[1], point.lonlat[0]], {icon: markIcon, interactive: false, keyboard: false})
                    .bindTooltip(name, {permanent: true, direction: 'right'}).addTo(placeMarks);
            }
            var row = rows.insertRow();
            row.insertCell().textContent = name;
            row.insertCell().textContent = point.pixel ? number(point.pixel[0], 0) + ', ' + number(point.pixel[1], 0) : '';
            row.insertCell().textContent = point.lonlat ? number(point.lonlat[1], 7) + ', ' + number(point.lonlat[0], 7) : '…';
            var remove = document.createElement('button');
            remove.type = 'button';
            remove.className = 'btn btn-sm btn-outline-danger';
            remove.textContent = '×';
            remove.addEventListener('click', function () {
                points.splice(index, 1);
                mode = 'plan';
                render();
            });
            row.insertCell().appendChild(remove);
        });
        planMap.getContainer().classList.toggle('map-align-pick', mode !== 'crop');
        placeMap.getContainer().classList.toggle('map-align-pick', mode === 'place');
        input.value = JSON.stringify(points.filter(function (p) { return p.pixel && p.lonlat; }));
        say(mode === 'place' ? root.dataset.pickPlace : mode === 'crop' ?
            (cropLayer ? root.dataset.cropEdit : root.dataset.cropStart) : root.dataset.pickPlan);
    }

    function setPlace(lon, lat) {
        var open = points.filter(function (p) { return !p.lonlat; })[0];
        if (!open) {
            return;
        }
        open.lonlat = [lon, lat];
        mode = 'plan';
        render();
    }

    planMap.on('click', function (event) {
        var x = Math.round(Math.min(Math.max(event.latlng.lng, 0), size[0]));
        var y = Math.round(Math.min(Math.max(-event.latlng.lat, 0), size[1]));
        if (mode === 'crop') {
            return;
        }
        if (mode === 'place') {
            points.filter(function (p) { return !p.lonlat; })[0].pixel = [x, y];  // a better pick of the same point
        } else {
            points.push({pixel: [x, y], lonlat: null});
            mode = 'place';
        }
        render();
    });

    placeMap.on('click', function (event) {
        if (mode === 'place') {
            setPlace(event.latlng.lng, event.latlng.lat);
        }
    });

    var typed = document.querySelector('[data-align-coordinates]');
    function useTyped() {
        var parts = typed.value.split(/[,;\s]+/).filter(Boolean).map(Number);
        if (parts.length !== 2 || parts.some(isNaN) || Math.abs(parts[0]) > 90 || Math.abs(parts[1]) > 180) {
            say(root.dataset.badCoordinates);
            return;
        }
        setPlace(parts[1], parts[0]);
        placeMap.setView([parts[0], parts[1]], Math.max(placeMap.getZoom(), 19));
        typed.value = '';
    }
    document.querySelector('[data-align-use]').addEventListener('click', useTyped);
    typed.addEventListener('keydown', function (event) {
        if (event.key === 'Enter') {
            event.preventDefault();
            useTyped();
        }
    });
    // Cropping: draw the outline, correct it with the preview, apply it.
    var cropButtons = document.querySelector('[data-align-crop-actions]');

    function stopCrop() {
        planMap.pm.disableDraw();
        [cropLayer, cropMask].forEach(function (layer) {
            if (layer) {
                planMap.removeLayer(layer);
            }
        });
        cropLayer = cropMask = null;
        cropButtons.hidden = true;
        mode = 'plan';
        render();
    }

    function preview() {
        if (cropMask) {
            planMap.removeLayer(cropMask);
        }
        var outside = [planBounds.getNorthWest(), planBounds.getNorthEast(), planBounds.getSouthEast(),
            planBounds.getSouthWest()];
        cropMask = L.polygon([outside, cropLayer.getLatLngs()[0]], {stroke: false, fillColor: '#000',
            fillOpacity: 0.55, interactive: false}).addTo(planMap);
        cropLayer.bringToFront();
    }

    document.querySelectorAll('[data-align-crop]').forEach(function (button) {
        button.addEventListener('click', function () {
            stopCrop();
            mode = 'crop';
            planMap.pm.setLang((document.documentElement.lang || 'en').slice(0, 2));
            planMap.pm.enableDraw(button.dataset.alignCrop, {snappable: false, allowSelfIntersection: false});
            render();
        });
    });
    planMap.on('pm:create', function (event) {
        if (mode !== 'crop') {
            return;
        }
        cropLayer = event.layer;
        cropLayer.pm.enable({allowSelfIntersection: false});
        cropLayer.on('pm:edit pm:markerdrag pm:vertexadded pm:vertexremoved', preview);
        preview();
        cropButtons.hidden = false;
        render();
    });
    cropButtons.querySelector('[data-align-crop-cancel]').addEventListener('click', stopCrop);
    cropButtons.querySelector('[data-align-crop-apply]').addEventListener('click', function () {
        // Fractions of the page: the image shows the box around the current crop (config.cropBounds).
        var bounds = config.cropBounds || [0, 0, 1, 1];
        var outline = cropLayer.getLatLngs()[0].map(function (latlng) {
            var x = Math.min(Math.max(latlng.lng, 0), size[0]), y = Math.min(Math.max(-latlng.lat, 0), size[1]);
            return [bounds[0] + (bounds[2] - bounds[0]) * x / size[0], bounds[1] + (bounds[3] - bounds[1]) * y / size[1]];
        });
        document.querySelector('[data-align-crop-input]').value = JSON.stringify(outline);
        document.querySelector('[data-align-crop-form]').submit();
    });
    render();
})();
