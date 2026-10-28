// The edit mode of the map page (maps/map.html, for map editors: all staff, maps.edit_map). A click selects a
// building part, storage unit or unique item; areas get draggable corners and can be dragged as a whole (Leaflet-
// Geoman), rectangles a middle handle to move and an outer one to turn, points a handle. Corners snap to the corners
// and edges around, turning to the edges nearby and the plan's walls (Alt while dragging: no snapping). Saving goes
// to the same views as the placing dialog (LocationShapeView, ItemPositionView); then the level is drawn anew.
// "New": a point, rectangle or area drawn on the map, then linked to a location of this level without a position
// (views.unplaced). "Row": storage units of one size side by side, turned and moved as one; the first location is
// chosen, the next ones without a position of the same type follow in the order of their codes; saved together
// (views.LocationShapeRowView).
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
    var countBox = bar.querySelector('[data-edit-count]'), countInput = countBox.querySelector('input');
    var reverseButton = countBox.querySelector('[data-edit-reverse]');
    var ROW_MAX = 50;
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
                if (selected[name].pm && selected[name].pm.disableLayerDrag) {  // not on a row's group
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
        actions.hidden = rotationBox.hidden = areaMode.hidden = sizeBox.hidden = searchBox.hidden = countBox.hidden = true;
        closeResults();
        newButtons.hidden = !editing;
    }

    function knobPosition() {
        return geometry.offset(selected.center, 0, selected.size[1] / 2 + Math.max(0.3, selected.size[1] * 0.4),
            selected.rotation);
    }

    // The middles of a row's storage units around `center` (the row's middle), side by side along their width; one
    // for anything else.
    function centers(s, center) {
        if (!s.count) {
            return [center];
        }
        var result = [];
        for (var i = 0; i < s.count; i += 1) {
            result.push(geometry.offset(center, (i - (s.count - 1) / 2) * s.size[0], 0, s.rotation));
        }
        return result;
    }

    // The corners that snap: of each rectangle (of the row), else the point.
    function corners(s, center) {
        if (!s.size) {
            return [center];
        }
        return centers(s, center).reduce(function (all, middle) {
            return all.concat(geometry.rectangle(middle, s.size, s.rotation));
        }, []);
    }

    // The locations of a row, in the order of its storage units: the chosen one and the next ones of its type that
    // have no position yet (views.unplaced lists them in the order of their codes); fewer if not enough follow.
    function rowLocations() {
        var first = chosenLocation();
        if (!first || !selected || !selected.count) {
            return [];
        }
        var same = candidates.filter(function (location) { return location.type === first.type; });
        var run = same.slice(same.indexOf(first), same.indexOf(first) + selected.count);
        return selected.reversed && run.length === selected.count ? run.reverse() : run;
    }

    // A row: one rectangle per storage unit, labelled with the code it gets.
    function drawRow() {
        var s = selected;
        s.shape.clearLayers();
        var locations = rowLocations();
        centers(s, s.center).forEach(function (middle, index) {
            L.polygon(geometry.rectangle(middle, s.size, s.rotation), HIGHLIGHT)
                .bindTooltip(locations[index] ? locations[index].code : '?', {permanent: true, direction: 'center',
                    className: 'map-label map-row-label'})
                .addTo(s.shape);
        });
    }

    function follow(turning) {
        if (selected.count) {
            drawRow();
            if (!turning) {
                selected.knob.setLatLng(knobPosition());
            }
            rotationInput.value = Math.round(selected.rotation);
            rotationOutput.textContent = Math.round(selected.rotation) + '°';
        } else if (selected.size) {
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
        countBox.hidden = !selected.count;
        if (selected.count) {
            countInput.value = selected.count;
            reverseButton.setAttribute('aria-pressed', selected.reversed ? 'true' : 'false');
            reverseButton.classList.toggle('active', selected.reversed);
        }
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
                if (selected.shape) {
                    follow();
                }
            }
        });
    });

    countInput.addEventListener('input', function () {
        var count = Math.round(Number(countInput.value));
        if (selected && selected.count && count >= 2 && count <= ROW_MAX) {
            selected.count = count;
            if (selected.shape) {
                follow();
            }
            rowHint();
        }
    });
    reverseButton.addEventListener('click', function () {
        if (selected && selected.count) {
            selected.reversed = !selected.reversed;
            reverseButton.setAttribute('aria-pressed', selected.reversed ? 'true' : 'false');
            reverseButton.classList.toggle('active', selected.reversed);
            if (selected.shape) {
                follow();
            }
        }
    });

    // What a row still needs: its place, its first location, enough locations after it.
    function rowHint() {
        if (!selected || !selected.count) {
            return;
        }
        var found = rowLocations().length;
        hint.textContent = !selected.center ? strings.newRow : !chosenLocation() ? strings.choose :
            found < selected.count ? strings.rowShort.replace('{count}', found) : strings.row;
    }

    function drawHandles() {
        var s = selected;
        s.shape = s.count ? L.featureGroup() : s.size ? L.polygon(geometry.rectangle(s.center, s.size, s.rotation), HIGHLIGHT)
            : L.circleMarker(s.center, Object.assign({radius: 8}, HIGHLIGHT));
        s.shape.addTo(map);
        if (s.count) {
            drawRow();
        }
        s.handle = L.marker(s.center, {draggable: true, keyboard: false,
            icon: L.divIcon({className: 'map-place-handle', iconSize: [18, 18]})}).addTo(map);
        s.handle.on('drag', function (event) {
            var at = event.target.getLatLng();
            s.center = event.originalEvent && event.originalEvent.altKey ? at :
                geometry.snapCenter(map, targets(), at, function (center) { return corners(s, center); });
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
            if (selected.shape) {  // a new one turns before it is placed, too
                follow();
            }
        }
    });

    // A new position: drawn first, then linked to a location of this level that has none yet.
    function startNew(kind) {
        clearSelection();
        var row = kind === 'row';
        selected = {kind: kind, isNew: true, rotation: walls() || 0, size: kind === 'point' || kind === 'area' ? null : [1, 0.5],
            count: row ? 3 : 0, reversed: false};
        page.element.classList.add('map-drawing');  // clicks go through what is drawn, to the map
        newButtons.hidden = true;
        actions.hidden = false;
        bar.querySelector('[data-edit-remove]').hidden = true;
        searchBox.hidden = false;
        locationSelect.value = '';
        chosen = null;
        candidates = [];
        ZamMap.load(strings.unplacedUrl + '?kind=' + (row ? 'rectangle' : kind)).then(function (answer) {  // whose type allows it
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
            hint.textContent = row ? strings.newRow : strings.newPoint;
            countBox.hidden = !row;
            if (row) {
                showSize();
            }
        }
    }

    newButtons.querySelectorAll('[data-new]').forEach(function (button) {
        button.addEventListener('click', function () { startNew(button.dataset.new); });
    });

    // A new rectangle takes the usual size of the chosen location's type, unless a size was entered.
    function chosenChanged() {
        var location = chosenLocation();
        if (selected && (selected.kind === 'rectangle' || selected.kind === 'row') && !selected.sizeChanged && location &&
                location.size) {
            selected.size = location.size.slice();
            showSize();
            if (selected.shape) {
                follow();
            }
        } else if (selected && selected.count && selected.shape) {
            follow();  // the codes on the row
        }
        rowHint();
    }

    map.on('click', function (event) {
        if (!selected || !selected.awaitingClick) {
            return;
        }
        selected.awaitingClick = false;
        selected.center = geometry.snapCenter(map, targets(), event.latlng, function (center) {
            return corners(selected, center);
        });
        showSize();
        drawHandles();
        hint.textContent = selected.size ? strings.rectangle : strings.point;
        rowHint();
    });

    // A row: all its storage units at once.
    function postRow() {
        var locations = rowLocations();
        if (!selected.center || locations.length < selected.count) {
            rowHint();
            return Promise.resolve();
        }
        var body = new FormData();
        body.append('csrfmiddlewaretoken', bar.querySelector('[name=csrfmiddlewaretoken]').value);
        body.append('rows', JSON.stringify(centers(selected, selected.center).map(function (middle, index) {
            return {pk: locations[index].pk, kind: 'rectangle', rotation: selected.rotation,
                geometry: JSON.stringify({type: 'Point', coordinates: [middle.lng, middle.lat]}),
                width_cm: Math.round(selected.size[0] * 100), depth_cm: Math.round(selected.size[1] * 100)};
        })));
        return send(strings.rowUrl, body);
    }

    function post(remove) {
        if (selected.count) {
            return postRow();
        }
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
        return send(url, body);
    }

    function send(url, body) {
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
