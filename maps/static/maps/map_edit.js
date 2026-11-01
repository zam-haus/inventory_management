// The edit mode of the map page (maps/map.html, for map editors: all staff, maps.edit_map). A click selects a
// building part, storage unit or unique item; areas get draggable corners (Leaflet-Geoman) and are dragged as a whole
// by their inside, rectangles a middle handle to move and one on each side to turn, points a handle (the box above
// fades while dragging). A click beside the selection lets it go. Corners snap to the
// corners and edges around, turning to the edges nearby and the plan's walls (Alt while dragging: no snapping; the
// first snap says so beside the point). The shapes are changed, steps undone and keys handled as in the grey box of a
// location's or unique item's page (map_shape_edit.js).
// Above the selection, on the map, a box says what it belongs to (changeable: take_from), with "Save" while there is a
// change, and an X: asked first, the position is removed at once and the shape stays for another location; a shape
// that belongs to nothing goes. A chosen corner gets an X, too. Below "Done": "Save" and "Discard" while there is a
// change, the "New" buttons while nothing is selected. Saving goes to the same views as the placing dialog
// (LocationShapeView, ItemPositionView); then the level is drawn anew, the saved one still selected.
// "New position": first what it is for, a location or unique item of this level without a position (views.unplaced),
// in the box in the middle of the map; then the bar offers the shapes it can have, the usual one chosen, and it is
// drawn: a point by a click, an area by its corners, a rectangle by a corner and then its width and depth (Enter) or
// the opposite corner (clicked, or dragged from one to the other). A location with dimensions (Location.footprint_cm)
// has that size: a click places its middle, and it is not sized on the map; else a rectangle's corners size it, and
// saving gives the location that size. "Row": storage units of one size side by side, turned and moved as one; the
// next ones without a position of the chosen one's type follow in the order of their codes; saved together
// (views.LocationShapeRowView). Leaving the page or the edit mode ("Done", Esc) with a change not saved asks first; Esc
// while drawing a new one drops it instead. A popup open when the edit mode starts selects its building part,
// storage unit or unique item; so does the pencil in such a popup. Enter or Ctrl+S (⌘S) saves; Delete or Backspace
// does what the box's X does (a chosen corner of an area goes first). Each step on the
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
    var pending = document.querySelector('[data-map-edit-pending]'), saveButton = pending.querySelector('[data-edit-save]');
    var newButtons = document.querySelector('[data-edit-new]'), locationSelect = assignBox.querySelector('[data-edit-location]');
    var searchBox = assignBox.querySelector('[data-edit-search]'), results = assignBox.querySelector('[data-edit-results]');
    var sizeBox = bar.querySelector('[data-edit-size]'), widthInput = sizeBox.querySelectorAll('input')[0];
    var depthInput = sizeBox.querySelectorAll('input')[1];
    var countBox = bar.querySelector('[data-edit-count]'), countInput = countBox.querySelector('input');
    var reverseButton = countBox.querySelector('[data-edit-reverse]');
    var kindsBox = bar.querySelector('[data-edit-kinds]'), targetText = bar.querySelector('[data-edit-target]');
    var fixedText = bar.querySelector('[data-edit-size-fixed]');
    var ROW_MAX = 50;
    // {pk, code, title, kinds, default_kind, size, size_fixed} of the locations offered for a new position, or to
    // change to; unique items (item: true, their location's code) only for a new one
    var candidates = [];
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
        if (selected && selected.choosing) {  // a new position: now its shape
            selected.choosing = false;
            showKinds(location);
            startKind(location.default_kind);
            return;
        }
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

    // The locations of this level without a position (views.unplaced; with a `kind`: whose type allows it), for a new
    // one or another; `withItems`: the unique items without one, too (a shape of a location goes to another location
    // only).
    function loadCandidates(kind, withItems) {
        candidates = [];
        return ZamMap.load(strings.unplacedUrl + (kind ? '?kind=' + kind : '')).then(function (answer) {
            candidates = answer.locations.concat(withItems ? answer.items || [] : []);
            return candidates;
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
        body.append('map_geometry', '');
        if (p.category === 'item') {
            return send(strings.itemUrl.replace('/0/', '/' + p.pk + '/'), body);
        }
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
            loadCandidates(s.kind, true);
            steps.end();
            steps.begin();
            showAssignment();
            return page.reload();
        }).catch(function (error) {
            hint.textContent = strings.error + ' ' + error.message;
        });
    }

    var assignMarker = ZamMap.editBox(map, assignBox);

    // What it belongs to: above the middle of the area, or above the handle (the X above the chosen corner: the
    // shape editor); while choosing what a new one is for, in the middle of the map.
    function placeBoxes() {
        var s = selected;
        ZamMap.showBox(map, assignMarker, !editing || !s ? null : s.choosing ? map.getCenter() : s.area ?
            (map.hasLayer(s.area) ? s.area.getCenter() : null) : s.center);
        shapes.showCorner();
    }
    map.on('move', function () {
        if (selected && selected.choosing) {
            placeBoxes();
        }
    });
    var HIGHLIGHT = {color: '#d63384', weight: 3, fillOpacity: 0.2};
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

    var shapes = ZamMap.shapeEditor(map, {
        style: HIGHLIGHT, targets: targets, walls: walls, snapNote: strings.snapNote, cornerBox: cornerBox,
        active: function () { return editing; },
        moving: function (on) { moving(on); },
        changed: function () { placeBoxes(); },
        stepped: function () { record(); },
        resizable: true, sizeHandle: strings.sizeHandle,
        sized: function (s) {
            widthInput.value = Math.round(s.size[0] * 100);
            depthInput.value = Math.round(s.size[1] * 100);
            showPending();
        },
        followed: function (s) {
            placeBoxes();
            if (s.size) {
                rotationInput.value = Math.round(s.rotation);
                rotationOutput.textContent = Math.round(s.rotation) + '°';
            }
        },
        drawRow: function () { drawRow(); }
    });

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
        if (cornerTool) {  // made further down
            cornerTool.reset();
        }
        if (selected.layer) {
            selected.layer.setStyle(selected.style);  // back as it was drawn
        }
        shapes.clear(selected);
        selected = null;
        page.element.classList.remove('map-drawing');
        hint.textContent = editing ? strings.pick : '';
        rotationBox.hidden = sizeBox.hidden = countBox.hidden = fixedText.hidden = true;
        kindsBox.hidden = targetText.hidden = true;
        steps.end();
        closeResults();
        chosen = null;
        candidates = [];
        locationSelect.value = '';
        assignBox.classList.remove('is-searching');
        placeBoxes();
        newButtons.hidden = !editing;
        showPending();
    }

    // While something is dragged, the box above it fades almost away.
    function moving(on) {
        page.element.classList.toggle('map-edit-moving', on);
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
        shapes.centers(s, s.center).forEach(function (middle, index) {
            L.polygon(geometry.rectangle(middle, rowSize(locations[index]), s.rotation), HIGHLIGHT)
                .bindTooltip(locations[index] ? locations[index].code : '?', {permanent: true, direction: 'center',
                    className: 'map-label map-row-label'})
                .addTo(s.shape);
        });
    }

    // A location of a row keeps its own dimensions; the others get the row's size.
    function rowSize(location) {
        return location && location.size_fixed ? location.size : selected.size;
    }

    function follow() {
        shapes.follow(selected);
    }

    // The size: entered, or (fixed) said; a new rectangle's fields from its first corner on, for its size.
    function showSize() {
        var rectangle = Boolean(selected.size || selected.awaitingCorners);
        sizeBox.hidden = !rectangle || selected.sizeFixed;
        fixedText.hidden = !rectangle || !selected.sizeFixed;
        if (selected.sizeFixed && selected.size) {
            fixedText.textContent = strings.sizeFixed.replace('{width}', Math.round(selected.size[0] * 100))
                .replace('{depth}', Math.round(selected.size[1] * 100));
        }
        countBox.hidden = !selected.count;
        if (selected.count) {
            countInput.value = selected.count;
            reverseButton.setAttribute('aria-pressed', selected.reversed ? 'true' : 'false');
            reverseButton.classList.toggle('active', selected.reversed);
        }
        widthInput.value = selected.size ? Math.round(selected.size[0] * 100) : '';
        depthInput.value = selected.size ? Math.round(selected.size[1] * 100) : '';
        rotationBox.hidden = !rectangle;
        rotationInput.value = Math.round(selected.rotation || 0);
        rotationOutput.textContent = Math.round(selected.rotation || 0) + '°';
    }

    [widthInput, depthInput].forEach(function (input) {
        input.addEventListener('input', function () {
            var width = Number(widthInput.value), depth = Number(depthInput.value);
            if (selected && selected.awaitingCorners) {  // a new rectangle: of this size, or by its corners
                selected.size = width > 0 && depth > 0 ? [width / 100, depth / 100] : null;
                cornerTool.preview();
                return;
            }
            if (selected && selected.size && !selected.sizeFixed && width > 0 && depth > 0) {
                selected.size = [width / 100, depth / 100];
                selected.sizeChanged = true;
                if (selected.shape) {
                    follow();
                }
                showPending();
            }
        });
    });

    // Enter in the size of a new rectangle: placed from its first corner.
    [widthInput, depthInput].forEach(function (input) {
        input.addEventListener('keydown', function (event) {
            if (event.key === 'Enter' && selected && selected.awaitingCorners && cornerTool.hasFirst()) {
                event.preventDefault();
                event.stopPropagation();
                cornerTool.apply();
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
        shapes.drawHandles(selected);
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
            shapes.editArea(selected);
            hint.textContent = '';
            showAssignment();
            steps.begin();
            return;
        }
        selected.center = L.latLng(layer.getBounds().getCenter());
        selected.rotation = p.rotation || 0;
        selected.size = p.kind === 'rectangle' && p.size ? p.size.slice() : null;
        selected.sizeFixed = Boolean(selected.size && p.sizeFixed);
        showSize();
        drawHandles();
        hint.textContent = shapeHint();
        showAssignment();
        steps.begin();
    }

    rotationInput.addEventListener('input', function () {
        if (selected && (selected.size || selected.awaitingCorners)) {  // a new rectangle turns before it is drawn
            selected.rotation = Number(rotationInput.value);
            if (selected.shape) {  // a new one turns before it is placed, too
                follow();
            }
            cornerTool.preview();
            showPending();
        }
    });

    // A new rectangle: by two opposite corners, along the turn set (at first the plan's walls).
    var cornerTool = ZamMap.cornerDrawing(map, {
        active: function () { return Boolean(editing && selected && selected.awaitingCorners); },
        rotation: function () { return selected.rotation || 0; },
        snap: function (latlng, event) {
            return event && event.altKey ? latlng :
                geometry.snapCenter(map, targets(), latlng, function (at) { return [at]; });
        },
        style: HIGHLIGHT,
        size: function () { return selected.size; },
        started: function () {  // the first corner: now the size, or the opposite corner
            widthInput.focus({preventScroll: true});
            widthInput.select();
        },
        done: function (drawn) {
            selected.awaitingCorners = false;
            selected.center = drawn.center;
            selected.size = drawn.size.map(function (metres) { return Math.max(1, Math.round(metres * 100)) / 100; });
            selected.sizeChanged = true;  // drawn: not the usual size of what is chosen
            placed();
        }
    });

    // A new position: first what it is for, a location or unique item of this level that has none yet.
    function startNew() {
        clearSelection();
        selected = {isNew: true, choosing: true, kind: null, rotation: walls() || 0, size: null, count: 0,
            reversed: false};
        newButtons.hidden = true;
        hint.textContent = strings.chooseFirst;
        assignBox.classList.add('is-searching');
        showAssignment();
        loadCandidates(null, true).then(function (locations) {
            if (!locations.length) {
                hint.textContent = strings.noneLeft;
            } else if (document.activeElement === locationSelect) {
                showResults();  // typed before they were there
            }
        });
        locationSelect.focus({preventScroll: true});
    }

    newButtons.querySelector('[data-new]').addEventListener('click', startNew);

    // The shapes the chosen one can have (a row: storage units side by side, of a type with rectangles).
    function showKinds(location) {
        kindsBox.querySelectorAll('[data-kind]').forEach(function (button) {
            var kind = button.dataset.kind;
            button.hidden = kind === 'row' ? location.item || location.kinds.indexOf('rectangle') < 0 :
                location.kinds.indexOf(kind) < 0;
        });
        kindsBox.hidden = false;
        targetText.textContent = selectionTitle();
        targetText.hidden = false;
    }

    // Only the shape being drawn is highlighted.
    function markKind(kind) {
        kindsBox.querySelectorAll('[data-kind]').forEach(function (button) {
            button.classList.toggle('active', button.dataset.kind === kind);
            button.setAttribute('aria-pressed', button.dataset.kind === kind ? 'true' : 'false');
        });
    }

    kindsBox.querySelectorAll('[data-kind]').forEach(function (button) {
        button.addEventListener('click', function () {
            if (selected && selected.isNew && chosen && !selected.center && !selected.area) {
                startKind(button.dataset.kind);
            }
        });
    });

    // The new position is drawn as `kind`, of the chosen one's size: fixed (its dimensions) or the usual one.
    function startKind(kind) {
        var s = selected, row = kind === 'row', sized = kind === 'rectangle' || row;
        shapes.clear(s);
        cornerTool.reset();
        s.kind = kind;
        s.awaitingClick = s.awaitingCorners = false;
        s.count = row ? 3 : 0;
        s.size = sized ? (chosen.size ? chosen.size.slice() : row ? [1, 0.5] : null) : null;
        s.sizeFixed = sized && Boolean(chosen.size_fixed);
        s.sizeChanged = false;
        page.element.classList.add('map-drawing');  // clicks go through what is drawn, to the map
        markKind(kind);
        if (kind === 'area') {
            shapes.drawArea(s, function () {
                hint.textContent = '';
                kindsBox.hidden = targetText.hidden = true;
                showAssignment();
                placeBoxes();
                steps.begin();
            });
            hint.textContent = strings.newArea;
        } else if (kind === 'rectangle' && !s.sizeFixed) {
            s.awaitingCorners = true;
            hint.textContent = s.size ? strings.newRectangleSized : strings.newRectangle;
        } else {
            s.awaitingClick = true;
            hint.textContent = row ? strings.newRow : kind === 'rectangle' ? strings.newRectangleFixed :
                strings.newPoint;
        }
        showSize();
        placeBoxes();
    }

    // What can be done with the selected point or rectangle.
    function shapeHint() {
        return !selected.size ? strings.point : selected.sizeFixed ? strings.rectangleFixed : strings.rectangle;
    }

    // A rectangle given to a location with dimensions gets that size; a new one else takes the usual size of the
    // chosen location's type, unless a size was entered.
    function chosenChanged() {
        var location = chosenLocation();
        if (selected && selected.size && selected.center && !selected.count && location && location.size_fixed) {
            selected.size = location.size.slice();
            selected.sizeFixed = true;
            shapes.dropHandles(selected);
            drawHandles();
            showSize();
            hint.textContent = shapeHint();
        } else if (selected && selected.isNew && (selected.kind === 'rectangle' || selected.kind === 'row') &&
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
        if (editing && selected && !selected.awaitingClick && !selected.awaitingCorners && !cornerTool.clickTaken() &&
                (!selected.isNew || selected.center || selected.area)) {
            ask(clearSelection);
        }
    });

    map.on('click', function (event) {
        if (!selected || !selected.awaitingClick) {
            return;
        }
        selected.awaitingClick = false;
        selected.center = shapes.snapCenter(selected, event.latlng, false);
        placed();
    });

    // A new one has its place: handles, the box above it, the steps.
    function placed() {
        kindsBox.hidden = targetText.hidden = true;
        showSize();
        drawHandles();
        hint.textContent = shapeHint();
        rowHint();
        showAssignment();
        placeBoxes();
        steps.begin();
    }

    // A row: all its storage units at once.
    function postRow() {
        var locations = rowLocations();
        if (!selected.center || locations.length < selected.count) {
            rowHint();
            return Promise.resolve();
        }
        var body = new FormData();
        body.append('csrfmiddlewaretoken', bar.querySelector('[name=csrfmiddlewaretoken]').value);
        body.append('rows', JSON.stringify(shapes.centers(selected, selected.center).map(function (middle, index) {
            var size = rowSize(locations[index]);
            return {pk: locations[index].pk, kind: 'rectangle', rotation: selected.rotation,
                geometry: JSON.stringify({type: 'Point', coordinates: [middle.lng, middle.lat]}),
                width_cm: Math.round(size[0] * 100), depth_cm: Math.round(size[1] * 100)};
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
        var p = selected.isNew ? {pk: chosenLocation().pk, category: chosenLocation().item ? 'item' : ''} :
            selected.feature.properties;
        var pk = !selected.isNew && chosen ? chosen.pk : p.pk;
        var body = new FormData(), url;
        body.append('csrfmiddlewaretoken', bar.querySelector('[name=csrfmiddlewaretoken]').value);
        if (p.category === 'item') {  // unique items keep their position (only shown in the box)
            url = strings.itemUrl.replace('/0/', '/' + p.pk + '/');
        } else {
            url = strings.shapeUrl.replace('/0/', '/' + pk + '/');
            if (pk !== p.pk) {
                body.append('take_from', p.pk);
            }
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
                var layer = editing && id && ZamMap.reveal(page.drawn, id);  // also a point of a unique item
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
    // Enter or Ctrl+S (⌘S): "Save" (also in the fields of the bar and the box, not in the location search's list: it
    // chooses a hit there); Delete or Backspace: the chosen corner goes, else as the box's X: asked first, the position
    // is removed (a new shape that belongs to nothing yet is dropped).
    ZamMap.editKeys({
        active: function () { return editing; }, editor: shapes,
        fields: function (element) { return bar.contains(element) || assignBox.contains(element); },
        remove: function () {
            if (!selected || selected.choosing || (selected.isNew && !selected.center && !selected.area)) {
                return false;
            }
            removeButton.click();
            return true;
        },
        save: function () {
            if (selected && !pending.hidden) {
                saveButton.click();
                return true;
            }
            return false;
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

    // Undo and redo of each step on the selected position (map_shape_edit.js: through the browser's history).
    var undoButton = document.querySelector('[data-map-edit-undo]'), redoButton = document.querySelector('[data-map-edit-redo]');
    var steps = ZamMap.editSteps({undo: undoButton, redo: redoButton, snapshot: snapshot, changed: showPending,
        active: function () { return editing && Boolean(selected); },
        restore: function (state) {
            if (selected) {
                restore(state);
            }
        }});

    function snapshot() {
        var s = selected;
        var own = {to: chosen ? chosen.pk : null};
        if (!s) {
            return own;
        }
        if (s.area) {
            return Object.assign(own, {area: s.area.getLatLngs().map(function (ring) {
                return ring.map(function (corner) { return [corner.lat, corner.lng]; });
            })});
        }
        return Object.assign(own, {center: s.center ? [s.center.lat, s.center.lng] : null, rotation: s.rotation || 0,
            size: s.size ? s.size.slice() : null, count: s.count || 0, reversed: Boolean(s.reversed)});
    }

    function record() {
        if (selected) {
            steps.record();
        }
    }

    function restore(state) {
        chosen = state.to === null ? null : candidates.filter(function (location) {
            return location.pk === state.to;
        })[0] || chosen;
        locationSelect.value = chosen ? chosen.title + ' · ' + chosen.code : '';
        showAssignment();
        if (state.area) {
            shapes.setArea(selected, state.area.map(function (ring) {
                return ring.map(function (corner) { return L.latLng(corner[0], corner[1]); });
            }));
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

    // The id of what is selected (its feature on the map); a new one by its chosen location, a row has none.
    function selectedId() {
        if (!selected || selected.count) {
            return null;
        }
        if (chosen) {
            return (chosen.item ? 'item:' : 'loc:') + chosen.pk;
        }
        return selected.feature ? selected.feature.properties.id : null;
    }

    // Ending, what was selected last shows its popup.
    function setEditing(on) {
        var shown = on && popupFeature && page.drawn && page.drawn.byId[popupFeature.properties.id];
        var last = on ? null : selectedId();
        editing = on;
        clearSelection();
        if (on) {
            ZamMap.unselect(map);  // its halo (map.js select): the edit mode shows what is selected its own way
        }
        bar.hidden = !on;
        page.element.classList.toggle('map-editing', on);
        toggleButton.querySelector('span').textContent = on ? toggleButton.dataset.done : startLabel;
        toggleButton.setAttribute('aria-pressed', on ? 'true' : 'false');
        toggleButton.classList.toggle('active', on);
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
            ZamMap.openPopupAbove(layer);
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
        return Boolean(selected && (selected.isNew ? selected.center || selected.area : steps.unsaved()));
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
