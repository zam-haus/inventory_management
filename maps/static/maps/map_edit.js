// The edit mode of the map page (maps/map.html, for map editors: all staff, maps.edit_map). A click selects a
// building part, storage unit or unique item; areas get draggable corners and can be dragged as a whole (Leaflet-
// Geoman), rectangles a middle handle to move and an outer one to turn, points a handle. Corners snap to the corners
// and edges around, turning to the edges nearby and the plan's walls (Alt while dragging: no snapping). Saving goes
// to the same views as the placing dialog (LocationShapeView, ItemPositionView); then the level is drawn anew.
// "New": a point, rectangle or area drawn on the map, then linked to a location of this level without a position
// (views.unplaced).
(function () {
    'use strict';

    var bar = document.querySelector('[data-map-edit]');
    var toggleButton = document.querySelector('[data-map-edit-toggle]');
    var page = window.ZamMap && ZamMap.page;
    if (!bar || !toggleButton || !page) {
        return;
    }
    var map = page.map, geometry = ZamMap.geometry, strings = bar.dataset;
    var title = bar.querySelector('[data-edit-title]'), hint = bar.querySelector('[data-edit-hint]');
    var actions = bar.querySelector('[data-edit-actions]'), rotationBox = bar.querySelector('[data-edit-rotation]');
    var rotationInput = rotationBox.querySelector('input'), rotationOutput = rotationBox.querySelector('output');
    // Areas: dragging corners or the whole area (Leaflet-Geoman does one at a time).
    var areaMode = bar.querySelector('[data-edit-area-mode]');
    var newButtons = bar.querySelector('[data-edit-new]'), locationSelect = bar.querySelector('[data-edit-location]');
    var searchBox = bar.querySelector('[data-edit-search]'), results = bar.querySelector('[data-edit-results]');
    var sizeBox = bar.querySelector('[data-edit-size]'), widthInput = sizeBox.querySelectorAll('input')[0];
    var depthInput = sizeBox.querySelectorAll('input')[1];
    var candidates = [];  // {pk, code, title, size} of the locations offered for a new position
    var chosen = null, active = -1, hits = [];

    // The location chosen in the search field: a hit picked from the list; else null.
    function chosenLocation() {
        return chosen;
    }

    function closeResults() {
        results.hidden = true;
        locationSelect.setAttribute('aria-expanded', 'false');
        locationSelect.removeAttribute('aria-activedescendant');
    }

    // The hits for what is typed: every word in the code, purpose or name; as purpose or name, the code chip below.
    function showResults() {
        var words = locationSelect.value.toLowerCase().split(/\s+/).filter(Boolean);
        hits = candidates.filter(function (location) {
            var text = (location.code + ' ' + location.title).toLowerCase();
            return words.every(function (word) { return text.indexOf(word) >= 0; });
        }).slice(0, 40);
        active = hits.length ? 0 : -1;
        results.textContent = '';
        hits.forEach(function (location, index) {
            var option = L.DomUtil.create('button', 'list-group-item list-group-item-action map-edit-hit', results);
            option.type = 'button';
            option.id = 'map-edit-hit-' + index;
            option.setAttribute('role', 'option');
            L.DomUtil.create('span', 'map-edit-hit-title', option).textContent = location.title;
            L.DomUtil.create('span', 'loc-code', option).textContent = location.code;
            option.addEventListener('mousedown', function (event) { event.preventDefault(); });  // keeps the focus
            option.addEventListener('click', function () { choose(location); });
        });
        results.hidden = !hits.length;
        locationSelect.setAttribute('aria-expanded', hits.length ? 'true' : 'false');
        mark();
    }

    function mark() {
        Array.prototype.forEach.call(results.children, function (option, index) {
            option.classList.toggle('active', index === active);
            option.setAttribute('aria-selected', index === active ? 'true' : 'false');
        });
        if (active >= 0) {
            locationSelect.setAttribute('aria-activedescendant', 'map-edit-hit-' + active);
            results.children[active].scrollIntoView({block: 'nearest'});
        }
    }

    function choose(location) {
        chosen = location;
        locationSelect.value = location.title + ' · ' + location.code;
        closeResults();
        chosenChanged();
    }

    locationSelect.addEventListener('input', function () {
        chosen = null;
        showResults();
    });
    locationSelect.addEventListener('focus', showResults);
    locationSelect.addEventListener('blur', closeResults);
    locationSelect.addEventListener('keydown', function (event) {
        if (event.key === 'ArrowDown' || event.key === 'ArrowUp') {
            if (results.hidden) {
                showResults();
            } else if (hits.length) {
                active = (active + (event.key === 'ArrowDown' ? 1 : hits.length - 1)) % hits.length;
                mark();
            }
            event.preventDefault();
        } else if (event.key === 'Enter' && !results.hidden && active >= 0) {
            choose(hits[active]);
            event.preventDefault();
        } else if (event.key === 'Escape' && !results.hidden) {
            closeResults();
            event.stopPropagation();  // only the list, not the change
        }
    });
    var AREA_EDITING = {allowSelfIntersection: false, snappable: true, snapDistance: 15};
    var HIGHLIGHT = {color: '#d63384', weight: 3, fillOpacity: 0.2};
    var editing = false;
    var selected = null;  // {feature, layer, kind, center, rotation, size, area, shape, handle, knob}
    var startLabel = toggleButton.querySelector('span').textContent;

    // The bar sits at the bottom of the map.
    var control = L.control({position: 'bottomleft'});
    control.onAdd = function () {
        L.DomEvent.disableClickPropagation(bar);
        L.DomEvent.disableScrollPropagation(bar);
        return bar;
    };
    control.addTo(map);

    function walls() {
        var plan = page.drawn && page.drawn.plans[0];
        return plan ? geometry.planRotation({corners: plan._corners.map(function (c) { return [c.lat, c.lng]; })})
            : null;
    }

    function targets() {
        return geometry.snapTargets(map, page.drawn, selected && selected.feature && selected.feature.properties.id);
    }

    function clearSelection() {
        if (!selected) {
            return;
        }
        if (selected.layer) {
            selected.layer.setStyle(selected.style);  // back as it was drawn
        }
        map.pm.disableDraw();
        ['area', 'shape', 'handle', 'knob'].forEach(function (name) {
            if (selected[name]) {
                if (selected[name].pm) {
                    selected[name].pm.disable();
                    selected[name].pm.disableLayerDrag();
                }
                map.removeLayer(selected[name]);
            }
        });
        selected = null;
        page.element.classList.remove('map-drawing');
        bar.querySelector('[data-edit-remove]').hidden = false;
        title.textContent = '';
        hint.textContent = editing ? strings.pick : '';
        actions.hidden = rotationBox.hidden = areaMode.hidden = sizeBox.hidden = searchBox.hidden = true;
        closeResults();
        newButtons.hidden = !editing;
    }

    function knobPosition() {
        return geometry.offset(selected.center, 0, selected.size[1] / 2 + Math.max(0.3, selected.size[1] * 0.4),
            selected.rotation);
    }

    function follow(turning) {
        if (selected.size) {
            selected.shape.setLatLngs(geometry.rectangle(selected.center, selected.size, selected.rotation));
            if (!turning) {
                selected.knob.setLatLng(knobPosition());
            }
            rotationInput.value = Math.round(selected.rotation);
            rotationOutput.textContent = Math.round(selected.rotation) + '°';
        } else {
            selected.shape.setLatLng(selected.center);
        }
    }

    function showSize() {
        sizeBox.hidden = !selected.size;
        if (selected.size) {
            widthInput.value = Math.round(selected.size[0] * 100);
            depthInput.value = Math.round(selected.size[1] * 100);
        }
        rotationBox.hidden = !selected.size;
        rotationInput.value = Math.round(selected.rotation || 0);
        rotationOutput.textContent = Math.round(selected.rotation || 0) + '°';
    }

    [widthInput, depthInput].forEach(function (input) {
        input.addEventListener('input', function () {
            var width = Number(widthInput.value), depth = Number(depthInput.value);
            if (selected && selected.size && width > 0 && depth > 0) {
                selected.size = [width / 100, depth / 100];
                selected.sizeChanged = true;
                follow();
            }
        });
    });

    function drawHandles() {
        var s = selected;
        s.shape = s.size ? L.polygon(geometry.rectangle(s.center, s.size, s.rotation), HIGHLIGHT)
            : L.circleMarker(s.center, Object.assign({radius: 8}, HIGHLIGHT));
        s.shape.addTo(map);
        s.handle = L.marker(s.center, {draggable: true, keyboard: false,
            icon: L.divIcon({className: 'map-place-handle', iconSize: [18, 18]})}).addTo(map);
        s.handle.on('drag', function (event) {
            var at = event.target.getLatLng();
            s.center = event.originalEvent && event.originalEvent.altKey ? at :
                geometry.snapCenter(map, targets(), at, function (center) {
                    return s.size ? geometry.rectangle(center, s.size, s.rotation) : [center];
                });
            follow();
        });
        s.handle.on('dragend', function () { s.handle.setLatLng(s.center); });
        if (!s.size) {
            return;
        }
        s.knob = L.marker(knobPosition(), {draggable: true, keyboard: false,
            icon: L.divIcon({className: 'map-place-handle map-place-knob', iconSize: [16, 16]})}).addTo(map);
        s.knob.on('drag', function (event) {
            var turned = geometry.bearing(s.center, event.target.getLatLng());
            s.rotation = event.originalEvent && event.originalEvent.altKey ? turned :
                geometry.snapRotation(map, targets(), s.center, turned, walls());
            follow(true);
        });
        s.knob.on('dragend', function () { s.knob.setLatLng(knobPosition()); });
    }

    function select(layer) {
        clearSelection();
        var feature = layer.feature, p = feature.properties;
        var drawnStyle = layer.getLayers()[0].options;
        selected = {feature: feature, layer: layer, kind: p.kind, style: {opacity: drawnStyle.opacity,
            fillOpacity: drawnStyle.fillOpacity}};
        layer.setStyle({opacity: 0.25, fillOpacity: 0.05});  // faded under what is being changed
        newButtons.hidden = true;
        title.textContent = p.title + (p.code ? ' · ' + p.code : '');
        actions.hidden = false;
        if (p.kind === 'area') {
            selected.area = L.geoJSON(feature.geometry, {style: function () { return HIGHLIGHT; }}).getLayers()[0];
            selected.area.addTo(map);
            map.pm.setLang((document.documentElement.lang || 'en').slice(0, 2));
            areaMode.hidden = false;
            areaMode.querySelector('[value=corners]').checked = true;
            selected.area.pm.enable(AREA_EDITING);
            hint.textContent = strings.area;
            return;
        }
        selected.center = L.latLng(layer.getBounds().getCenter());
        selected.rotation = p.rotation || 0;
        selected.size = p.kind === 'rectangle' && p.size ? p.size.slice() : null;
        showSize();
        drawHandles();
        hint.textContent = selected.size ? strings.rectangle : strings.point;
    }

    areaMode.querySelectorAll('input').forEach(function (radio) {
        radio.addEventListener('change', function () {
            if (!selected || !selected.area) {
                return;
            }
            if (radio.value === 'whole') {
                selected.area.pm.disable();
                selected.area.pm.enableLayerDrag();
            } else {
                selected.area.pm.disableLayerDrag();
                selected.area.pm.enable(AREA_EDITING);
            }
        });
    });

    rotationInput.addEventListener('input', function () {
        if (selected && selected.size) {
            selected.rotation = Number(rotationInput.value);
            follow();
        }
    });

    // A new position: drawn first, then linked to a location of this level that has none yet.
    function startNew(kind) {
        clearSelection();
        selected = {kind: kind, isNew: true, rotation: walls() || 0, size: kind === 'rectangle' ? [1, 0.5] : null};
        page.element.classList.add('map-drawing');  // clicks go through what is drawn, to the map
        newButtons.hidden = true;
        actions.hidden = false;
        bar.querySelector('[data-edit-remove]').hidden = true;
        searchBox.hidden = false;
        locationSelect.value = '';
        chosen = null;
        candidates = [];
        ZamMap.load(strings.unplacedUrl + '?kind=' + kind).then(function (answer) {  // whose type allows it
            candidates = answer.locations;
            if (!answer.locations.length) {
                hint.textContent = strings.noneLeft;
            }
        });
        if (kind === 'area') {
            map.pm.setLang((document.documentElement.lang || 'en').slice(0, 2));
            map.pm.enableDraw('Polygon', AREA_EDITING);
            map.once('pm:create', function (event) {
                if (!selected || !selected.isNew) {
                    map.removeLayer(event.layer);
                    return;
                }
                selected.area = event.layer;
                selected.area.pm.enable(AREA_EDITING);
                areaMode.hidden = false;
                hint.textContent = strings.area;
            });
            hint.textContent = strings.newArea;
        } else {
            selected.awaitingClick = true;
            hint.textContent = strings.newPoint;
        }
    }

    newButtons.querySelectorAll('[data-new]').forEach(function (button) {
        button.addEventListener('click', function () { startNew(button.dataset.new); });
    });

    // A new rectangle takes the usual size of the chosen location's type, unless a size was entered.
    function chosenChanged() {
        var location = chosenLocation();
        if (selected && selected.kind === 'rectangle' && !selected.sizeChanged && location && location.size) {
            selected.size = location.size.slice();
            showSize();
            if (selected.shape) {
                follow();
            }
        }
    }

    map.on('click', function (event) {
        if (!selected || !selected.awaitingClick) {
            return;
        }
        selected.awaitingClick = false;
        selected.center = geometry.snapCenter(map, targets(), event.latlng, function (center) {
            return selected.size ? geometry.rectangle(center, selected.size, selected.rotation) : [center];
        });
        showSize();
        drawHandles();
        hint.textContent = selected.size ? strings.rectangle : strings.point;
    });

    function post(remove) {
        if (selected.isNew && (!chosenLocation() || (!selected.center && !selected.area))) {
            hint.textContent = chosenLocation() ? strings.newPoint : strings.choose;
            return Promise.resolve();
        }
        var p = selected.isNew ? {pk: chosenLocation().pk, category: ''} : selected.feature.properties;
        var body = new FormData(), url;
        body.append('csrfmiddlewaretoken', bar.querySelector('[name=csrfmiddlewaretoken]').value);
        if (p.category === 'item') {
            url = strings.itemUrl.replace('/0/', '/' + p.pk + '/');
            body.append('map_point', remove ? '' : JSON.stringify(
                {type: 'Point', coordinates: [selected.center.lng, selected.center.lat]}));
        } else {
            url = strings.shapeUrl.replace('/0/', '/' + p.pk + '/');
            if (!remove) {
                var geojson = selected.area ? selected.area.toGeoJSON().geometry :
                    {type: 'Point', coordinates: [selected.center.lng, selected.center.lat]};
                body.append('map_geometry', JSON.stringify(geojson));
                body.append('map_kind', selected.area ? 'area' : selected.size ? 'rectangle' : 'point');
                body.append('map_rotation', selected.rotation || 0);
                if (selected.size) {
                    body.append('map_width_cm', Math.round(selected.size[0] * 100));
                    body.append('map_depth_cm', Math.round(selected.size[1] * 100));
                }
            } else {
                body.append('map_geometry', '');
            }
        }
        return fetch(url, {method: 'POST', body: body, credentials: 'same-origin',
            headers: {'Accept': 'application/json'}})
            .then(function (response) {
                return response.json().then(function (answer) {
                    if (!response.ok || !answer.ok) {
                        throw new Error(answer.error || response.status);
                    }
                });
            })
            .then(function () {
                clearSelection();
                return page.reload();
            })
            .catch(function (error) {
                hint.textContent = strings.error + ' ' + error.message;
            });
    }

    bar.querySelector('[data-edit-save]').addEventListener('click', function () { post(false); });
    bar.querySelector('[data-edit-remove]').addEventListener('click', function () { post(true); });
    bar.querySelector('[data-edit-discard]').addEventListener('click', clearSelection);
    document.addEventListener('keydown', function (event) {
        if (event.key === 'Escape' && editing) {
            clearSelection();
        }
    });

    // In the edit mode a click on something selects it, instead of its popup.
    function listen() {
        Object.keys(page.drawn.byId).forEach(function (id) {
            var layer = page.drawn.byId[id];
            layer.on('click', function (event) {
                if (!editing || (selected && selected.isNew)) {  // drawing a new one: clicks are corners
                    return;
                }
                L.DomEvent.stop(event);
                map.closePopup();
                select(layer);
            });
        });
    }
    document.addEventListener('zam-map-drawn', listen);
    if (page.drawn) {
        listen();
    }
    map.on('popupopen', function () {
        if (editing) {
            map.closePopup();
        }
    });

    function setEditing(on) {
        editing = on;
        clearSelection();
        bar.hidden = !on;
        page.element.classList.toggle('map-editing', on);
        toggleButton.querySelector('span').textContent = on ? toggleButton.dataset.done : startLabel;
        toggleButton.setAttribute('aria-pressed', on ? 'true' : 'false');
        hint.textContent = on ? strings.pick : '';
    }

    toggleButton.addEventListener('click', function () { setEditing(!editing); });
})();
