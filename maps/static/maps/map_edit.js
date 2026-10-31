// The edit mode of the map page (maps/map.html, for map editors: all staff, maps.edit_map). A click selects a
// building part, storage unit or unique item; areas get draggable corners (Leaflet-Geoman) and are dragged as a whole
// by their inside, rectangles a middle handle to move and one on each side to turn, points a handle (the box above
// fades while dragging). A click beside the selection lets it go. Corners snap to the
// corners and edges around, turning to the edges nearby and the plan's walls (Alt while dragging: no snapping; the
// first snap says so beside the point).
// Above the selection, on the map, a box says what it belongs to (changeable: take_from), with "Save" while there is a
// change, and an X: asked first, the position is removed at once and the shape stays for another location; a shape
// that belongs to nothing goes. A chosen corner gets an X, too. Below "Done": "Save" and "Discard" while there is a
// change, the "New" buttons while nothing is selected. Saving goes to the same views as the placing dialog
// (LocationShapeView, ItemPositionView); then the level is drawn anew, the saved one still selected.
// "New": a point, rectangle or area drawn on the map, then linked to a location of this level without a position
// (views.unplaced). "Row": storage units of one size side by side, turned and moved as one; the first location is
// chosen, the next ones without a position of the same type follow in the order of their codes; saved together
// (views.LocationShapeRowView). Leaving the page or the edit mode ("Done", Esc) with a change not saved asks first; Esc
// while drawing a new one drops it instead. A popup open when the edit mode starts selects its building part,
// storage unit or unique item; so does the pencil in such a popup. Enter or Ctrl+S (⌘S) saves. Each step on the
// selected position can be undone and redone (the arrows beside "Done", the browser's back and forward, Ctrl+Z).
(function () {
    'use strict';

    var bar = document.querySelector('[data-map-edit]');
    var toggleButton = document.querySelector('[data-map-edit-toggle]');
    var page = window.ZamMap && ZamMap.page;
    if (!bar || !toggleButton || !page) {
        return;
    }
    var map = page.map, geometry = ZamMap.geometry, strings = bar.dataset;
    var hint = bar.querySelector('[data-edit-hint]'), rotationBox = bar.querySelector('[data-edit-rotation]');
    var rotationInput = rotationBox.querySelector('input'), rotationOutput = rotationBox.querySelector('output');
    var assignBox = document.querySelector('[data-edit-box]'), assignButton = assignBox.querySelector('[data-edit-assign]');
    var removeButton = assignBox.querySelector('[data-edit-remove]'), boxSave = assignBox.querySelector('[data-edit-box-save]');
    var cornerBox = document.querySelector('[data-edit-corner-box]');
    var cornerButton = cornerBox.querySelector('[data-edit-remove-corner]');
    var corner = null, cornerDragging = false;  // the marker of the corner of an area tapped last, to remove it
    var pending = document.querySelector('[data-map-edit-pending]'), saveButton = pending.querySelector('[data-edit-save]');
    var newButtons = document.querySelector('[data-edit-new]'), locationSelect = assignBox.querySelector('[data-edit-location]');
    var searchBox = assignBox.querySelector('[data-edit-search]'), results = assignBox.querySelector('[data-edit-results]');
    var sizeBox = bar.querySelector('[data-edit-size]'), widthInput = sizeBox.querySelectorAll('input')[0];
    var depthInput = sizeBox.querySelectorAll('input')[1];
    var countBox = bar.querySelector('[data-edit-count]'), countInput = countBox.querySelector('input');
    var reverseButton = countBox.querySelector('[data-edit-reverse]');
    var ROW_MAX = 50;
    var candidates = [];  // {pk, code, title, size} of the locations offered for a new position, or to change to
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
        assignBox.classList.remove('is-searching');
        chosenChanged();
        showAssignment();
        record();
    }

    locationSelect.addEventListener('input', showResults);
    locationSelect.addEventListener('focus', showResults);
    locationSelect.addEventListener('blur', function () {
        closeResults();
        window.setTimeout(function () {  // left without choosing: back to what it belongs to, if anything
            if (document.activeElement !== locationSelect && selected && target()) {
                stopSearching();
            }
        }, 0);
    });
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
        } else if (event.key === 'Escape' && target()) {
            stopSearching();
            event.stopPropagation();
        }
    });

    // What the selected position belongs to: the location chosen in the box, else its own; none for a new one yet.
    function target() {
        var p = selected && selected.feature && selected.feature.properties;
        return chosen || (p ? {title: p.title, code: p.code} : null);
    }

    function selectionTitle() {
        var t = target();
        return t ? t.title + (t.code ? ' · ' + t.code : '') : '';
    }

    // The box above the position: what it belongs to (a button to change it; for unique items only shown), or the
    // search while choosing; the X ends what it belongs to, or drops a shape that belongs to nothing yet.
    function showAssignment() {
        if (!selected) {
            return;
        }
        var p = selected.feature && selected.feature.properties, item = p && p.category === 'item', t = target();
        var searching = !item && (!t || assignBox.classList.contains('is-searching'));
        assignButton.hidden = searching;
        searchBox.hidden = !searching;
        assignButton.disabled = item;
        assignButton.textContent = '';
        if (t) {
            L.DomUtil.create('span', 'map-edit-assign-title', assignButton).textContent = t.title;
            if (t.code) {
                L.DomUtil.create('span', 'loc-code', assignButton).textContent = t.code;
            }
        }
        var label = selected.isNew ? removeButton.dataset.drop : removeButton.dataset.remove;
        removeButton.title = label;
        removeButton.setAttribute('aria-label', label);
        placeBoxes();
    }

    function stopSearching() {
        assignBox.classList.remove('is-searching');
        closeResults();
        showAssignment();
    }

    // The locations of this level without a position whose type allows it (views.unplaced), for a new one or another.
    function loadCandidates(kind) {
        candidates = [];
        return ZamMap.load(strings.unplacedUrl + '?kind=' + kind).then(function (answer) {
            candidates = answer.locations;
            return answer.locations;
        });
    }

    assignButton.addEventListener('click', function () {
        if (!selected) {
            return;
        }
        assignBox.classList.add('is-searching');
        locationSelect.value = '';
        showAssignment();
        if (!selected.isNew && !candidates.length) {
            loadCandidates(selected.kind).then(function () {
                if (document.activeElement === locationSelect) {
                    showResults();
                }
            });
        }
        locationSelect.focus();
    });

    // The X: a shape that belongs to nothing (yet) is dropped. Else, asked first, the position is removed and saved at
    // once; a location's shape stays, as a new one, to give it to another location (a unique item's goes).
    var unassignDialog = document.querySelector('[data-edit-unassign]');
    removeButton.addEventListener('click', function () {
        if (!selected) {
            return;
        }
        if (selected.isNew) {
            clearSelection();
            return;
        }
        unassignDialog.querySelector('[data-unassign-title]').textContent = selectionTitle();
        bootstrap.Modal.getOrCreateInstance(unassignDialog).show();
    });
    unassignDialog.addEventListener('shown.bs.modal', function () {
        unassignDialog.querySelector('[data-unassign-confirm]').focus();
    });
    unassignDialog.querySelector('[data-unassign-confirm]').addEventListener('click', function () {
        bootstrap.Modal.getOrCreateInstance(unassignDialog).hide();
        if (selected && !selected.isNew) {
            unassign();
        }
    });

    function unassign() {
        var s = selected, p = s.feature.properties, body = new FormData();
        body.append('csrfmiddlewaretoken', bar.querySelector('[name=csrfmiddlewaretoken]').value);
        if (p.category === 'item') {
            body.append('map_point', '');
            return send(strings.itemUrl.replace('/0/', '/' + p.pk + '/'), body);
        }
        body.append('map_geometry', '');
        return request(strings.shapeUrl.replace('/0/', '/' + p.pk + '/'), body).then(function () {
            if (selected !== s) {
                return null;
            }
            hideLabel(false);
            s.feature = s.layer = null;  // drawn anew without it, below
            s.isNew = s.sizeChanged = true;
            chosen = null;
            locationSelect.value = '';
            assignBox.classList.add('is-searching');
            hint.textContent = strings.choose;
            loadCandidates(s.kind);
            endSteps();
            beginSteps();
            showAssignment();
            return page.reload();
        }).catch(function (error) {
            hint.textContent = strings.error + ' ' + error.message;
        });
    }

    // The boxes are markers of their own pane, over the handles and below the popups; clicks in them stay there.
    map.createPane('mapEditBoxes').style.zIndex = 640;

    function overlay(element) {
        element.remove();  // only on the map, in its marker
        element.hidden = false;
        L.DomEvent.disableClickPropagation(element);
        L.DomEvent.disableScrollPropagation(element);
        return L.marker([0, 0], {icon: L.divIcon({className: 'map-edit-anchor', html: element, iconSize: [0, 0]}),
            interactive: false, keyboard: false, pane: 'mapEditBoxes'});
    }
    var assignMarker = overlay(assignBox), cornerMarker = overlay(cornerBox);

    function show(marker, at) {
        if (!at) {
            map.removeLayer(marker);
            return;
        }
        marker.setLatLng(at);
        if (!map.hasLayer(marker)) {
            marker.addTo(map);
        }
    }

    // What it belongs to: above the middle of the area, or above the handle; the X above the chosen corner, not while
    // a corner is dragged.
    function placeBoxes() {
        var s = selected;
        show(assignMarker, !editing || !s ? null : s.area ? (map.hasLayer(s.area) ? s.area.getCenter() : null) :
            s.center);
        show(cornerMarker, editing && s && s.area && corner && !cornerDragging ? corner.getLatLng() : null);
    }
    // Removing a corner of a triangle flashes it instead of removing the whole area.
    var AREA_EDITING = {allowSelfIntersection: false, snappable: true, snapDistance: 15,
        removeLayerBelowMinVertexCount: false};
    var HIGHLIGHT = {color: '#d63384', weight: 3, fillOpacity: 0.2};
    // The first snap on the page says how to place without snapping, beside the snapped point (it follows further
    // snaps), for a while; not on touch screens (no Alt).
    var snapNote = null, snapNoted = false;
    var SNAP_NOTE_MS = 8000;

    function snapped(at) {
        if (!at || !window.matchMedia('(any-pointer: fine)').matches) {
            return;
        }
        if (snapNote) {
            snapNote.setLatLng(at);
            return;
        }
        if (snapNoted) {
            return;
        }
        snapNoted = true;
        snapNote = L.tooltip({direction: 'right', offset: [16, 0], className: 'map-snap-note', permanent: true})
            .setLatLng(at).setContent(strings.snapNote);
        map.openTooltip(snapNote);
        window.setTimeout(function () {
            map.closeTooltip(snapNote);
            snapNote = null;
        }, SNAP_NOTE_MS);
    }

    function snappedCorner(event) {
        snapped(event.snapLatLng || (event.marker && event.marker.getLatLng()));
    }
    var editing = false;
    var selected = null;  // {feature, layer, kind, center, rotation, size, area, shape, handle, knobs}
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

    // The label of what is selected goes while the box above it says what it is (labels are laid out anew on
    // zooming, map.js layoutLabels; then again).
    function hideLabel(hidden) {
        var tooltip = selected && selected.layer && selected.layer.getTooltip && selected.layer.getTooltip();
        var element = tooltip && tooltip.getElement();
        if (element) {
            element.classList.toggle('map-label-selected', hidden);
        }
    }
    map.on('zoomend', function () { hideLabel(true); });

    function clearSelection() {
        if (!selected) {
            return;
        }
        hideLabel(false);
        if (selected.layer) {
            selected.layer.setStyle(selected.style);  // back as it was drawn
        }
        map.pm.disableDraw();
        ['area', 'shape', 'handle'].forEach(function (name) {
            if (selected[name]) {
                if (selected[name].pm && selected[name].pm.disableLayerDrag) {  // not on a row's group
                    selected[name].pm.disable();
                    selected[name].pm.disableLayerDrag();
                }
                map.removeLayer(selected[name]);
            }
        });
        (selected.knobs || []).forEach(function (knob) { map.removeLayer(knob); });
        selected = null;
        moving(false);
        page.element.classList.remove('map-drawing');
        hint.textContent = editing ? strings.pick : '';
        rotationBox.hidden = sizeBox.hidden = countBox.hidden = true;
        endSteps();
        chooseCorner(null);
        closeResults();
        chosen = null;
        candidates = [];
        locationSelect.value = '';
        assignBox.classList.remove('is-searching');
        placeBoxes();
        newButtons.hidden = !editing;
        showPending();
    }

    // The turning handles, one on each side, as one may lie under something else: in front (where the depth points),
    // then clockwise; a row's sides are those of the whole row. Outside the edge, at least KNOB_PIXELS on the screen
    // (laid out anew on zooming).
    var SIDES = [0, 90, 180, 270];
    var KNOB_PIXELS = 28;

    function metresPerPixel() {
        var middle = map.getSize().divideBy(2);
        return map.distance(map.containerPointToLatLng(middle), map.containerPointToLatLng(middle.add([0, 100]))) / 100;
    }

    function knobPosition(side) {
        var width = selected.size[0] * (selected.count || 1), depth = selected.size[1];
        var reach = (side % 2 ? width : depth) / 2 + Math.max(Math.min(width, depth) * 0.4, KNOB_PIXELS * metresPerPixel());
        var angle = SIDES[side] * Math.PI / 180;
        return geometry.offset(selected.center, reach * Math.sin(angle), reach * Math.cos(angle), selected.rotation);
    }
    map.on('zoomend', function () {
        if (selected && selected.knobs) {
            placeKnobs();
        }
    });

    // All but the one being dragged (`turning`: its side).
    function placeKnobs(turning) {
        selected.knobs.forEach(function (knob, side) {
            if (side !== turning) {
                knob.setLatLng(knobPosition(side));
            }
        });
    }

    // While something is dragged, the box above it fades almost away.
    function moving(on) {
        page.element.classList.toggle('map-edit-moving', on);
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
        placeBoxes();
        if (selected.count) {
            drawRow();
            placeKnobs(turning);
            rotationInput.value = Math.round(selected.rotation);
            rotationOutput.textContent = Math.round(selected.rotation) + '°';
        } else if (selected.size) {
            selected.shape.setLatLngs(geometry.rectangle(selected.center, selected.size, selected.rotation));
            placeKnobs(turning);
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
                showPending();
            }
        });
    });

    // A typed size, number or turn is a step once it is entered (the slider: let go).
    [widthInput, depthInput, countInput, rotationInput].forEach(function (input) {
        input.addEventListener('change', record);
    });

    countInput.addEventListener('input', function () {
        var count = Math.round(Number(countInput.value));
        if (selected && selected.count && count >= 2 && count <= ROW_MAX) {
            selected.count = count;
            if (selected.shape) {
                follow();
            }
            rowHint();
            showPending();
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
            record();
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
        ownClicks(s.shape);
        if (s.count) {
            drawRow();
        }
        s.handle = L.marker(s.center, {draggable: true, keyboard: false,
            icon: L.divIcon({className: 'map-place-handle', iconSize: [18, 18]})}).addTo(map);
        s.handle.on('drag', function (event) {
            var at = event.target.getLatLng();
            s.center = event.originalEvent && event.originalEvent.altKey ? at :
                geometry.snapCenter(map, targets(), at, function (center) { return corners(s, center); });
            if (s.center !== at) {
                snapped(s.center);
            }
            follow();
        });
        s.handle.on('dragstart', function () { moving(true); });
        s.handle.on('dragend', function () {
            moving(false);
            s.handle.setLatLng(s.center);
            record();
        });
        if (!s.size) {
            return;
        }
        s.knobs = SIDES.map(function (angle, side) {
            var knob = L.marker(knobPosition(side), {draggable: true, keyboard: false,
                icon: L.divIcon({className: 'map-place-handle map-place-knob', iconSize: [16, 16]})}).addTo(map);
            knob.on('dragstart', function () { moving(true); });
            knob.on('drag', function (event) {
                var turned = (geometry.bearing(s.center, event.target.getLatLng()) - angle + 360) % 360;
                s.rotation = event.originalEvent && event.originalEvent.altKey ? turned :
                    geometry.snapRotation(map, targets(), s.center, turned, walls());
                if (s.rotation !== turned) {
                    snapped(event.target.getLatLng());
                }
                follow(side);
            });
            knob.on('dragend', function () {
                moving(false);
                knob.setLatLng(knobPosition(side));
                record();
            });
            return knob;
        });
    }

    // A corner of an area is removed by tapping it and then the button, tapping it again or Delete; a right click on
    // it removes it at once. Both go through Leaflet-Geoman's removal (its removeVertexOn event), which keeps at least three corners
    // and refuses removals that would make the edges cross.
    function chooseCorner(marker) {
        if (corner && corner._icon) {
            corner._icon.classList.remove('map-corner-chosen');
        }
        corner = marker;
        if (corner && corner._icon) {
            corner._icon.classList.add('map-corner-chosen');
        }
        placeBoxes();
    }

    function removeCorner() {
        if (corner && selected && selected.area) {
            corner.fire(selected.area.pm.options.removeVertexOn || 'contextmenu');
        }
    }

    // What is selected keeps its clicks from the map (a drag by the inside ends in one, too), which would let it go.
    function ownClicks(layer) {
        layer.on('click', L.DomEvent.stop);
    }

    function watchArea(area) {
        ownClicks(area);
        area.on('pm:vertexclick', function (event) {
            if (event.markerEvent.target === corner) {
                removeCorner();
            } else {
                chooseCorner(event.markerEvent.target);
            }
        });
        area.on('pm:vertexremoved pm:disable', function () { chooseCorner(null); });
        area.on('pm:snap', snappedCorner);
        area.on('pm:markerdragstart', function () {
            cornerDragging = true;
            moving(true);
            placeBoxes();
        });
        area.on('pm:markerdragend', function () {
            cornerDragging = false;
            moving(false);
            placeBoxes();
        });
        area.on('pm:edit', function () {
            placeBoxes();
            record();
        });
        dragArea(area);
    }

    // The area as a whole is dragged by its inside; its corners keep their handles. Geoman drags a layer only with
    // its corners' editing off, so that goes off while dragging.
    var TAP_PIXELS = 3;  // a tap is no drag

    function dragArea(area) {
        var path = area.getElement();
        path.classList.add('map-edit-area');
        path.addEventListener('pointerdown', function (event) {
            if (event.button !== 0 || !selected || selected.area !== area) {
                return;
            }
            var start = map.mouseEventToContainerPoint(event), moved = false;
            var rings = area.getLatLngs().map(function (ring) {
                return ring.map(function (corner) { return map.latLngToContainerPoint(corner); });
            });
            map.dragging.disable();  // before the map's own listener, further up
            path.setPointerCapture(event.pointerId);

            function move(moving) {
                var shift = map.mouseEventToContainerPoint(moving).subtract(start);
                if (!moved && shift.distanceTo(L.point(0, 0)) < TAP_PIXELS) {
                    return;
                }
                if (!moved) {
                    moved = true;
                    moving(true);
                    chooseCorner(null);
                    area.pm.disable();
                }
                area.setLatLngs(rings.map(function (ring) {
                    return ring.map(function (corner) { return map.containerPointToLatLng(corner.add(shift)); });
                }));
                placeBoxes();
            }

            function up() {
                path.removeEventListener('pointermove', move);
                path.removeEventListener('pointerup', up);
                path.removeEventListener('pointercancel', up);
                map.dragging.enable();
                moving(false);
                if (moved && selected && selected.area === area) {
                    area.pm.enable(AREA_EDITING);
                    record();
                }
            }
            path.addEventListener('pointermove', move);
            path.addEventListener('pointerup', up);
            path.addEventListener('pointercancel', up);
        });
    }

    function select(layer) {
        clearSelection();
        var feature = layer.feature, p = feature.properties;
        var drawnStyle = layer.getLayers()[0].options;
        selected = {feature: feature, layer: layer, kind: p.kind, style: {opacity: drawnStyle.opacity,
            fillOpacity: drawnStyle.fillOpacity}};
        layer.setStyle({opacity: 0.25, fillOpacity: 0.05});  // faded under what is being changed
        hideLabel(true);
        newButtons.hidden = true;
        if (p.kind === 'area') {
            selected.area = L.geoJSON(feature.geometry, {style: function () { return HIGHLIGHT; }}).getLayers()[0];
            selected.area.addTo(map);
            map.pm.setLang((document.documentElement.lang || 'en').slice(0, 2));
            watchArea(selected.area);
            selected.area.pm.enable(AREA_EDITING);
            hint.textContent = '';
            showAssignment();
            beginSteps();
            return;
        }
        selected.center = L.latLng(layer.getBounds().getCenter());
        selected.rotation = p.rotation || 0;
        selected.size = p.kind === 'rectangle' && p.size ? p.size.slice() : null;
        showSize();
        drawHandles();
        hint.textContent = selected.size ? strings.rectangle : strings.point;
        showAssignment();
        beginSteps();
    }

    rotationInput.addEventListener('input', function () {
        if (selected && selected.size) {
            selected.rotation = Number(rotationInput.value);
            if (selected.shape) {  // a new one turns before it is placed, too
                follow();
            }
            showPending();
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
        loadCandidates(row ? 'rectangle' : kind).then(function (locations) {
            if (!locations.length) {
                hint.textContent = strings.noneLeft;
            }
        });
        if (kind === 'area') {
            map.pm.setLang((document.documentElement.lang || 'en').slice(0, 2));
            map.once('pm:drawstart', function (event) { event.workingLayer.on('pm:snap', snappedCorner); });
            map.pm.enableDraw('Polygon', AREA_EDITING);
            map.once('pm:create', function (event) {
                if (!selected || !selected.isNew) {
                    map.removeLayer(event.layer);
                    return;
                }
                selected.area = event.layer;
                watchArea(selected.area);
                selected.area.pm.enable(AREA_EDITING);
                hint.textContent = '';
                showAssignment();
                placeBoxes();
                beginSteps();
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
        if (selected && selected.isNew && (selected.kind === 'rectangle' || selected.kind === 'row') &&
                !selected.sizeChanged && location && location.size) {
            selected.size = location.size.slice();
            showSize();
            if (selected.shape) {
                follow();
            }
        } else if (selected && selected.count && selected.shape) {
            follow();  // the codes on the row
        }
        if (selected && selected.isNew && !selected.count && location && hint.textContent === strings.choose) {
            hint.textContent = '';
        }
        rowHint();
    }

    // A click beside the selection (not on what is selected or on another thing, which selects that) lets it go.
    map.on('click', function () {
        if (editing && selected && !selected.awaitingClick && (!selected.isNew || selected.center || selected.area)) {
            ask(clearSelection);
        }
    });

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
        showAssignment();
        placeBoxes();
        beginSteps();
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

    // Saves the selected position: changed, or given to another location (`take_from`).
    function post() {
        if (selected.count) {
            return postRow();
        }
        if (selected.isNew && (!chosenLocation() || (!selected.center && !selected.area))) {
            hint.textContent = chosenLocation() ? strings.newPoint : strings.choose;
            return Promise.resolve();
        }
        var p = selected.isNew ? {pk: chosenLocation().pk, category: ''} : selected.feature.properties;
        var pk = !selected.isNew && chosen ? chosen.pk : p.pk;
        var body = new FormData(), url;
        body.append('csrfmiddlewaretoken', bar.querySelector('[name=csrfmiddlewaretoken]').value);
        if (p.category === 'item') {
            url = strings.itemUrl.replace('/0/', '/' + p.pk + '/');
            body.append('map_point', JSON.stringify(
                {type: 'Point', coordinates: [selected.center.lng, selected.center.lat]}));
        } else {
            url = strings.shapeUrl.replace('/0/', '/' + pk + '/');
            if (pk !== p.pk) {
                body.append('take_from', p.pk);
            }
            var geojson = selected.area ? selected.area.toGeoJSON().geometry :
                {type: 'Point', coordinates: [selected.center.lng, selected.center.lat]};
            body.append('map_geometry', JSON.stringify(geojson));
            body.append('map_kind', selected.area ? 'area' : selected.size ? 'rectangle' : 'point');
            body.append('map_rotation', selected.rotation || 0);
            if (selected.size) {
                body.append('map_width_cm', Math.round(selected.size[0] * 100));
                body.append('map_depth_cm', Math.round(selected.size[1] * 100));
            }
        }
        return send(url, body);
    }

    // Saved, the level is drawn anew and what was saved stays selected. Resolves true then, else false (the bar says
    // why).
    function request(url, body) {
        return fetch(url, {method: 'POST', body: body, credentials: 'same-origin',
            headers: {'Accept': 'application/json'}})
            .then(function (response) {
                return response.json().then(function (answer) {
                    if (!response.ok || !answer.ok) {
                        throw new Error(answer.error || response.status);
                    }
                });
            });
    }

    function send(url, body) {
        var id = selectedId();
        return request(url, body)
            .then(function () {
                clearSelection();
                return page.reload();
            })
            .then(function () {
                var layer = editing && id && page.drawn.byId[id];
                if (layer && map.hasLayer(layer)) {
                    select(layer);
                }
                return true;
            })
            .catch(function (error) {
                hint.textContent = strings.error + ' ' + error.message;
                return false;
            });
    }

    saveButton.addEventListener('click', function () { post(); });
    boxSave.addEventListener('click', function () { post(); });
    pending.querySelector('[data-edit-discard]').addEventListener('click', clearSelection);
    cornerButton.addEventListener('click', removeCorner);
    // Enter or Ctrl+S (⌘S): "Save". Not for Enter on a button or link (it presses them), in a field outside the bar and
    // the box or in the location search's list (it chooses a hit there). A corner's handle that has the focus
    // (Leaflet makes markers buttons) saves, too, instead of being "clicked" (and removed).
    document.addEventListener('keydown', function (event) {
        var saveKey = (event.ctrlKey || event.metaKey) && !event.altKey && !event.shiftKey &&
            event.key.toLowerCase() === 's';
        var enter = event.key === 'Enter' && !event.ctrlKey && !event.metaKey && !event.altKey && !event.shiftKey;
        if (!editing || !(saveKey || enter) || event.defaultPrevented || event.isComposing ||
                event.target.closest('.modal')) {
            return;
        }
        if (enter && (event.target.closest('button, a, textarea, select, [contenteditable], [role=button]:not(.leaflet-marker-icon)') ||
                (event.target.closest('input') && !bar.contains(event.target) && !assignBox.contains(event.target)))) {
            return;
        }
        if (saveKey) {
            event.preventDefault();  // not the browser's "Save page"
        }
        if (selected && !pending.hidden) {
            event.preventDefault();
            saveButton.click();
        }
    });

    // Esc: a new one not saved yet is dropped; else the edit mode ends, as with "Done".
    document.addEventListener('keydown', function (event) {
        if (event.key === 'Escape' && editing && !event.target.closest('.modal') && !document.querySelector('.modal.show')) {
            if (selected && selected.isNew) {
                clearSelection();
            } else {
                leave();
            }
        } else if ((event.key === 'Delete' || event.key === 'Backspace') && corner &&
                !event.target.closest('input, textarea, select, [contenteditable]')) {
            event.preventDefault();
            removeCorner();
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

    // What a popup was opened for, outside the edit mode: selected when it starts.
    var popupFeature = null;
    map.on('popupopen', function (event) {
        var source = event.popup._source;
        popupFeature = source && (source.feature || (source.getLayers && source.getLayers()[0] &&
            source.getLayers()[0].feature)) || null;
        var box = event.popup.getElement().querySelector('.map-popup');
        if (editing || !popupFeature || !page.drawn || !page.drawn.byId[popupFeature.properties.id] || !box ||
                box.querySelector('.map-popup-edit')) {
            return;
        }
        // A pencil to edit it at once (the popup's content is made once, so it stays).
        var pencil = L.DomUtil.create('button', 'map-popup-edit', box);  // below the popup's close button
        pencil.type = 'button';
        pencil.title = strings.editThis;
        pencil.setAttribute('aria-label', strings.editThis);
        pencil.appendChild(toggleButton.querySelector('svg').cloneNode(true));
        pencil.addEventListener('click', function () { setEditing(true); });
        event.popup.update();  // laid out anew, with it
    });
    map.on('popupclose', function () {
        if (!editing) {
            popupFeature = null;
        }
    });

    // Undo and redo: each step on the selected position is an entry of the browser's history (back and forward undo
    // and redo it; so do the arrows and Ctrl+Z, through the history), its state a snapshot kept here. Entries of a
    // selection that is gone (saved, discarded, another page load) are passed over, in the direction one went.
    var undoButton = document.querySelector('[data-map-edit-undo]'), redoButton = document.querySelector('[data-map-edit-redo]');
    var steps = [], step = 0, session = null;
    var here = history.state && history.state.mapEdit ? history.state.mapEdit.seq : 0;  // the entry shown
    var seq = here;  // the last entry made

    function snapshot() {
        var s = selected;
        var own = {to: chosen ? chosen.pk : null};
        if (s.area) {
            return Object.assign(own, {area: s.area.getLatLngs().map(function (ring) {
                return ring.map(function (corner) { return [corner.lat, corner.lng]; });
            })});
        }
        return Object.assign(own, {center: s.center ? [s.center.lat, s.center.lng] : null, rotation: s.rotation || 0,
            size: s.size ? s.size.slice() : null, count: s.count || 0, reversed: Boolean(s.reversed)});
    }

    function same(one, other) {
        return JSON.stringify(one) === JSON.stringify(other);
    }

    function entry() {
        return Object.assign({}, history.state, {mapEdit: {session: session, step: step, seq: here}});
    }

    function showSteps() {
        undoButton.disabled = !session || step === 0;
        redoButton.disabled = !session || step >= steps.length - 1;
    }

    // The position as it is when selected (or a new one placed): the first step, in the entry shown.
    function beginSteps() {
        session = Math.random().toString(36).slice(2);
        steps = [snapshot()];
        step = 0;
        here = seq += 1;
        history.replaceState(entry(), '');
        showSteps();
        showPending();
    }

    function endSteps() {
        session = null;
        steps = [];
        step = 0;
        showSteps();
    }

    function record() {
        if (!session || !selected) {
            return;
        }
        var now = snapshot();
        if (same(now, steps[step])) {
            return;
        }
        steps = steps.slice(0, step + 1).concat([now]);
        step += 1;
        here = seq += 1;
        history.pushState(entry(), '');
        showSteps();
        showPending();
    }

    function restore(state) {
        chosen = state.to === null ? null : candidates.filter(function (location) {
            return location.pk === state.to;
        })[0] || chosen;
        locationSelect.value = chosen ? chosen.title + ' · ' + chosen.code : '';
        showAssignment();
        if (state.area) {
            chooseCorner(null);
            selected.area.pm.disable();
            selected.area.setLatLngs(state.area.map(function (ring) {
                return ring.map(function (corner) { return L.latLng(corner[0], corner[1]); });
            }));
            selected.area.pm.enable(AREA_EDITING);
            placeBoxes();
            return;
        }
        selected.center = L.latLng(state.center[0], state.center[1]);
        selected.rotation = state.rotation;
        selected.size = state.size && state.size.slice();
        selected.count = state.count;
        selected.reversed = state.reversed;
        showSize();
        follow();
        selected.handle.setLatLng(selected.center);
        rowHint();
    }

    window.addEventListener('popstate', function (event) {
        var state = event.state && event.state.mapEdit;
        if (!state) {
            return;
        }
        var from = here;
        here = state.seq;
        if (session && state.session === session && selected) {
            step = state.step;
            restore(steps[step]);
            showSteps();
            showPending();
        } else {
            history.go(state.seq < from ? -1 : 1);
        }
    });
    undoButton.addEventListener('click', function () {
        if (session && step > 0) {
            history.back();
        }
    });
    redoButton.addEventListener('click', function () {
        if (session && step < steps.length - 1) {
            history.forward();
        }
    });
    document.addEventListener('keydown', function (event) {
        if (!editing || !session || !(event.ctrlKey || event.metaKey) || event.altKey ||
                event.target.closest('input, textarea, select, [contenteditable]')) {
            return;
        }
        var key = event.key.toLowerCase();
        if (key === 'z' && !event.shiftKey) {
            event.preventDefault();
            undoButton.click();
        } else if (key === 'y' || (key === 'z' && event.shiftKey)) {
            event.preventDefault();
            redoButton.click();
        }
    });

    // The id of what is selected (its feature on the map); a new one by its chosen location, a row has none.
    function selectedId() {
        if (!selected || selected.count) {
            return null;
        }
        if (chosen) {
            return 'loc:' + chosen.pk;
        }
        return selected.feature ? selected.feature.properties.id : null;
    }

    // Ending, what was selected last shows its popup.
    function setEditing(on) {
        var shown = on && popupFeature && page.drawn && page.drawn.byId[popupFeature.properties.id];
        var last = on ? null : selectedId();
        editing = on;
        clearSelection();
        bar.hidden = !on;
        page.element.classList.toggle('map-editing', on);
        toggleButton.querySelector('span').textContent = on ? toggleButton.dataset.done : startLabel;
        toggleButton.setAttribute('aria-pressed', on ? 'true' : 'false');
        undoButton.hidden = redoButton.hidden = !on;
        hint.textContent = on ? strings.pick : '';
        showPending();
        popupFeature = null;
        if (shown) {
            map.closePopup();
            select(shown);
        }
        newButtons.hidden = !on || Boolean(selected);
        var layer = last && page.drawn && page.drawn.byId[last];
        if (layer && map.hasLayer(layer)) {
            layer.openPopup();
        }
    }

    // Leaving the selection ("Done", Esc, a click beside it) with a change not saved: save it, discard it, or go on
    // editing; a shape that belongs to nothing yet: assign it (then save) or discard it. `then`: what follows saving
    // or discarding.
    var unsavedDialog = document.querySelector('[data-edit-unsaved]'), afterDialog = null;
    var dialogHeading = unsavedDialog.querySelector('.modal-title'), dialogText = unsavedDialog.querySelector('[data-unsaved-text]');
    var dialogSave = unsavedDialog.querySelector('[data-unsaved-save]'), dialogAssign = unsavedDialog.querySelector('[data-unsaved-assign]');
    var dialogKeep = unsavedDialog.querySelector('[data-unsaved-keep]');
    toggleButton.addEventListener('click', function () {
        if (editing) {
            leave();
        } else {
            setEditing(true);
        }
    });

    function ask(then) {
        if (!unsaved()) {
            then();
            return;
        }
        var unassigned = selected.isNew && !chosen;
        afterDialog = then;
        dialogHeading.textContent = unassigned ? dialogHeading.dataset.assign : dialogHeading.dataset.save;
        dialogText.textContent = unassigned ? dialogText.dataset.assign : dialogText.dataset.save;
        dialogSave.hidden = dialogKeep.hidden = unassigned;
        dialogAssign.hidden = !unassigned;
        var what = unsavedDialog.querySelector('[data-unsaved-title]');
        what.textContent = selectionTitle();
        what.hidden = !what.textContent;
        bootstrap.Modal.getOrCreateInstance(unsavedDialog).show();
    }

    function leave() {
        ask(function () { setEditing(false); });
    }

    unsavedDialog.addEventListener('shown.bs.modal', function () {
        (dialogSave.hidden ? dialogAssign : dialogSave).focus();
    });
    unsavedDialog.querySelector('[data-unsaved-discard]').addEventListener('click', function () {
        bootstrap.Modal.getOrCreateInstance(unsavedDialog).hide();
        afterDialog();
    });
    dialogSave.addEventListener('click', function () {
        bootstrap.Modal.getOrCreateInstance(unsavedDialog).hide();
        post().then(function (saved) {
            if (saved) {  // else the bar says what is missing or went wrong
                afterDialog();
            }
        });
    });
    // Assigning: the search in the box, once the dialog is gone (it gives the focus back first).
    dialogAssign.addEventListener('click', function () {
        unsavedDialog.addEventListener('hidden.bs.modal', function () {
            if (selected) {
                assignBox.classList.add('is-searching');
                showAssignment();
                locationSelect.focus();
            }
        }, {once: true});
        bootstrap.Modal.getOrCreateInstance(unsavedDialog).hide();
    });

    // Something moved, turned, resized, removed, given to another location or drawn anew, and not saved yet.
    function unsaved() {
        return Boolean(selected && (selected.isNew ? selected.center || selected.area :
            steps.length && !same(snapshot(), steps[0])));
    }

    // "Save" and "Discard" below "Done", and "Save" in the box, while there is a change that can be saved: a new
    // shape once its location is chosen.
    function showPending() {
        pending.hidden = boxSave.hidden = !(editing && unsaved() && (!selected.isNew || chosen));
    }

    window.addEventListener('beforeunload', function (event) {
        if (unsaved()) {
            event.preventDefault();
            event.returnValue = '';  // older browsers ask only with this
        }
    });
})();
