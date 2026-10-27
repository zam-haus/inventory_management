// Placing a floor plan (maps/plan_align.html) in two steps. 1. Place: pairs of control points, a pixel on the plan
// (left) and where it is (right: clicked on the map with the plans already placed, or typed as "latitude,
// longitude"); both can be dragged. The server fits the plan to them (maps/geo.py). 2. Crop, once it is placed: an
// outline on the whole page (maps/views.py plan_page), drawn (rectangle or polygon, with Leaflet-Geoman) or copied
// from another plan, edited with everything outside it darkened, sent as fractions of the page (maps/render.py
// crop_polygon) together with the control points, so that points changed since placing are not lost.
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
    var mode = 'plan';  // what the next click sets: 'plan' (a pixel), 'place' (its coordinates); 'crop' in step 2
    var markIcon = L.divIcon({className: 'map-align-mark', iconSize: [25, 25], tooltipAnchor: [10, 0]});

    function clamp(value, low, high) {
        return Math.min(Math.max(value, low), high);
    }

    // Left: the plan in pixels (y downwards; Leaflet's simple CRS has y upwards, so pixel y is -lat).
    var planElement = root.querySelector('[data-align-plan]');
    var planMap = L.map(planElement, {crs: L.CRS.Simple, minZoom: -6, maxZoom: 4, zoomSnap: 0.25,
        attributionControl: false});
    var size = [config.width, config.height];
    var planBounds = L.latLngBounds([[-size[1], 0], [0, size[0]]]);
    config.tiles.forEach(function (tile) {  // the plan from its tiles (maps/views.py plan_tiles)
        L.imageOverlay(tile.url, [[-(tile.y + tile.h), tile.x], [-tile.y, tile.x + tile.w]]).addTo(planMap);
    });
    planMap.fitBounds(planBounds);
    var planMarks = L.layerGroup().addTo(planMap);

    // Right: the level with the plans already placed, this one on top (also when it is inactive or not shown at
    // first); its opacity can be tried here without saving it.
    var placeMap = ZamMap.create(root.querySelector('[data-align-map]'));
    ZamMap.layerControl(placeMap);
    var placeMarks = L.layerGroup().addTo(placeMap);
    var opacity = document.querySelector('[data-align-opacity]');
    var own = null;
    function showOwn() {
        if (config.planLayer) {
            own = ZamMap.planLayer(placeMap, config.planLayer).addTo(placeMap);
            own.setOpacity(opacity.value);
        }
    }
    if (opacity) {
        opacity.addEventListener('input', function () {
            if (own) {
                own.setOpacity(opacity.value);
            }
        });
    }
    if (config.data) {
        ZamMap.load(config.data).then(function (data) {
            data.plans = (data.plans || []).filter(function (plan) { return plan.id !== config.plan; });
            var drawn = ZamMap.draw(placeMap, data, {interactive: false});
            showOwn();
            var bounds = own ? own.getBounds() : drawn.bounds;
            if (bounds) {
                placeMap.fitBounds(bounds);
            }
        });
    } else {
        showOwn();
    }

    // Step 2: the whole page, loaded when the step is opened first; the outline in its pixels.
    var pageElement = root.querySelector('[data-align-page]');
    var cropTools = root.querySelector('[data-align-crop-tools]');
    var cropActions = root.querySelector('[data-align-crop-actions]');
    var pageMap = null, pageSize = null, pageFailed = false, outline = null, mask = null, drawing = false;

    function say(text) {
        hint.textContent = text || '';
    }

    function hintText() {
        if (mode !== 'crop') {
            return mode === 'place' ? root.dataset.pickPlace : root.dataset.pickPlan;
        }
        if (!pageMap) {
            return pageFailed ? root.dataset.pageError : root.dataset.pageLoading;
        }
        return drawing ? root.dataset.cropDraw : outline ? root.dataset.cropEdit : root.dataset.cropWhole;
    }

    function number(value, digits) {
        return value === undefined || value === null ? '' : Number(value).toFixed(digits);
    }

    // A control point's mark; dragged, it corrects the point.
    function mark(latlng, name, moved) {
        return L.marker(latlng, {icon: markIcon, draggable: true, keyboard: false})
            .bindTooltip(name, {permanent: true, direction: 'right'})
            .on('dragend', function (event) {
                moved(event.target.getLatLng());
                render();
            });
    }

    function pixel(latlng) {
        return [Math.round(clamp(latlng.lng, 0, size[0])), Math.round(clamp(-latlng.lat, 0, size[1]))];
    }

    function render() {
        planMarks.clearLayers();
        placeMarks.clearLayers();
        rows.textContent = '';
        points.forEach(function (point, index) {
            var name = String(index + 1);
            if (point.pixel) {
                mark([-point.pixel[1], point.pixel[0]], name, function (latlng) {
                    point.pixel = pixel(latlng);
                }).addTo(planMarks);
            }
            if (point.lonlat) {
                mark([point.lonlat[1], point.lonlat[0]], name, function (latlng) {
                    point.lonlat = [latlng.lng, latlng.lat];
                }).addTo(placeMarks);
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
                if (mode !== 'crop') {
                    mode = 'plan';
                }
                render();
            });
            row.insertCell().appendChild(remove);
        });
        planMap.getContainer().classList.toggle('map-align-pick', mode !== 'crop');
        placeMap.getContainer().classList.toggle('map-align-pick', mode === 'place');
        input.value = JSON.stringify(points.filter(function (p) { return p.pixel && p.lonlat; }));
        cropTools.querySelectorAll('button, select').forEach(function (element) {
            element.disabled = !pageMap;
        });
        cropActions.querySelector('[data-align-crop-apply]').disabled = !pageMap || drawing;
        say(hintText());
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
        if (mode === 'crop') {
            return;
        }
        var at = pixel(event.latlng);
        if (mode === 'place') {
            points.filter(function (p) { return !p.lonlat; })[0].pixel = at;  // a better pick of the same point
        } else {
            points.push({pixel: at, lonlat: null});
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

    // The outline: fractions of the page ([x, y], y downwards) and positions on the page in pixels.
    function toLatLng(fraction) {
        return [-fraction[1] * pageSize[1], fraction[0] * pageSize[0]];
    }

    function toFraction(latlng) {
        return [Math.round(clamp(latlng.lng / pageSize[0], 0, 1) * 1e5) / 1e5,
            Math.round(clamp(-latlng.lat / pageSize[1], 0, 1) * 1e5) / 1e5];
    }

    function preview() {
        if (mask) {
            pageMap.removeLayer(mask);
        }
        var page = L.latLngBounds([[-pageSize[1], 0], [0, pageSize[0]]]);
        mask = L.polygon([[page.getNorthWest(), page.getNorthEast(), page.getSouthEast(), page.getSouthWest()],
            outline.getLatLngs()[0]], {stroke: false, fillColor: '#000', fillOpacity: 0.55, interactive: false})
            .addTo(pageMap);
        outline.bringToFront();
    }

    // The outline to edit (corners dragged, added between two, removed with a double click), or none: the whole page.
    function setOutline(latlngs) {
        [outline, mask].forEach(function (layer) {
            if (layer) {
                pageMap.removeLayer(layer);
            }
        });
        outline = mask = null;
        if (latlngs) {
            outline = L.polygon(latlngs).addTo(pageMap);
            outline.pm.enable({allowSelfIntersection: false, removeVertexOn: 'dblclick'});
            outline.on('pm:edit pm:markerdrag pm:vertexadded pm:vertexremoved', preview);
            preview();
        }
        render();
    }

    function savedOutline() {
        return config.crop ? config.crop.map(toLatLng) : null;
    }

    function stopDrawing() {
        if (pageMap) {
            pageMap.pm.disableDraw();
        }
        drawing = false;
    }

    // While an outline is drawn, a double click on a corner (not the first, a click on it finishes the outline)
    // removes it. Leaflet-Geoman only removes the last one; this changes its drawing state (vendored 2.20.2).
    function removeDrawnCorner(marker) {
        var draw = pageMap.pm.Draw.Polygon, index = draw._markers.indexOf(marker);
        if (index < 1) {
            return;
        }
        draw._markers.splice(index, 1);
        draw._layerGroup.removeLayer(marker);
        var latlngs = draw._layer.getLatLngs();
        latlngs.splice(index, 1);
        draw._layer.setLatLngs(latlngs);
        (draw._layer._latlngInfo || []).splice(index, 1);
        draw._syncHintLine();
    }

    function openPage() {
        if (pageMap || pageFailed) {
            if (pageMap) {
                pageMap.invalidateSize();
            }
            return;
        }
        var image = new Image();
        image.onload = function () {
            pageSize = [image.naturalWidth, image.naturalHeight];
            pageMap = L.map(pageElement, {crs: L.CRS.Simple, minZoom: -6, maxZoom: 4, zoomSnap: 0.25,
                attributionControl: false, doubleClickZoom: false});
            var bounds = L.latLngBounds([[-pageSize[1], 0], [0, pageSize[0]]]);
            L.imageOverlay(config.page, bounds).addTo(pageMap);
            pageMap.fitBounds(bounds);
            pageMap.pm.setLang((document.documentElement.lang || 'en').slice(0, 2));
            pageMap.on('pm:drawstart', function (event) {
                if (event.shape === 'Polygon') {
                    event.workingLayer.on('pm:vertexadded', function (added) {
                        added.marker.on('dblclick', function () { removeDrawnCorner(added.marker); });
                    });
                }
            });
            pageMap.on('pm:create', function (event) {
                // A rectangle too becomes an outline of four corners, edited corner by corner.
                var corners = event.layer.getLatLngs()[0];
                pageMap.removeLayer(event.layer);
                drawing = false;
                setOutline(corners);
            });
            pageMap.on('pm:drawend', function () {  // also when drawing is given up (Escape)
                drawing = false;
                render();
            });
            setOutline(savedOutline());
        };
        image.onerror = function () {
            pageFailed = true;
            render();
        };
        image.src = config.page;
    }

    var stepButtons = root.querySelectorAll('[data-align-step]');
    function showStep(name) {
        var crop = name === 'crop';
        stepButtons.forEach(function (button) {
            var on = button.dataset.alignStep === name;
            button.classList.toggle('active', on);
            button.setAttribute('aria-pressed', String(on));
        });
        planElement.hidden = crop;
        pageElement.hidden = cropTools.hidden = cropActions.hidden = !crop;
        if (crop) {
            mode = 'crop';
            openPage();
        } else {
            stopDrawing();
            mode = points.some(function (p) { return !p.lonlat; }) ? 'place' : 'plan';
            planMap.invalidateSize();
        }
        render();
    }
    stepButtons.forEach(function (button) {
        button.addEventListener('click', function () { showStep(button.dataset.alignStep); });
    });

    cropTools.querySelectorAll('[data-align-crop]').forEach(function (button) {
        button.addEventListener('click', function () {
            stopDrawing();
            setOutline(null);
            drawing = true;
            pageMap.pm.enableDraw(button.dataset.alignCrop, {snappable: false, allowSelfIntersection: false});
            render();
        });
    });
    cropTools.querySelector('[data-align-crop-whole]').addEventListener('click', function () {
        stopDrawing();
        setOutline(null);
    });
    var copy = cropTools.querySelector('[data-align-crop-copy]');
    if (copy) {
        cropTools.querySelector('[data-align-crop-copy-use]').addEventListener('click', function () {
            stopDrawing();
            setOutline(config.otherCrops[copy.value].map(toLatLng));
        });
    }
    cropActions.querySelector('[data-align-crop-cancel]').addEventListener('click', function () {
        stopDrawing();
        if (pageMap) {
            setOutline(savedOutline());
        }
        showStep('place');
    });
    cropActions.querySelector('[data-align-crop-apply]').addEventListener('click', function () {
        var form = document.querySelector('[data-align-crop-form]');
        form.elements.crop.value = JSON.stringify(outline ? outline.getLatLngs()[0].map(toFraction) : null);
        form.elements.control_points.value = input.value;
        form.elements.affine.value = document.getElementById('align-affine').checked ? '1' : '';
        form.submit();
    });
    render();
})();
