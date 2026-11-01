// Changing a shape on a map, the same way in the edit mode of the map page (map_edit.js) and in the grey box of a
// location's or unique item's page (map_place.js):
//   ZamMap.shapeEditor  an area gets draggable corners (Leaflet-Geoman) and is dragged as a whole by its inside; a
//                       corner tapped is chosen (an X above it removes it, so do tapping it again and Delete; a right
//                       click removes one at once; a triangle keeps its corners). A rectangle has a middle handle to
//                       move it and one on each side to turn it (options.resizable: and one on each corner to size
//                       it, the opposite one staying, unless its size is fixed), a point a handle. Corners snap to
//                       the corners and edges around, turning to the edges nearby and the plan's walls (Alt while
//                       dragging: no snapping; the first snap on the page says so beside the point).
//   ZamMap.editSteps    each step can be undone and redone: the arrows, Ctrl+Z (⌘Z) and Ctrl+Y, the browser's back
//                       and forward (each step is an entry of its history).
//   ZamMap.editKeys     Enter or Ctrl+S (⌘S) saves; Delete or Backspace removes the chosen corner, else (options.remove)
//                       what the X of the selection does.
// What is edited is a state object of the caller: {center, rotation, size ([width, depth] in m; a rectangle), sizeFixed
// (not sized on the map), count (a row of rectangles side by side), area (an L.Polygon)}; the editor adds its layers
// (shape, handle, knobs, corners).
(function () {
    'use strict';

    var geometry = ZamMap.geometry;
    // Removing a corner of a triangle flashes it instead of removing the whole area.
    var AREA_EDITING = {allowSelfIntersection: false, snappable: true, snapDistance: 15,
        removeLayerBelowMinVertexCount: false};
    // The turning handles, one on each side, as one may lie under something else: in front (where the depth points),
    // then clockwise; a row's sides are those of the whole row. Outside the edge, at least KNOB_PIXELS on the screen
    // (laid out anew on zooming).
    var SIDES = [0, 90, 180, 270];
    var KNOB_PIXELS = 28;
    var TAP_PIXELS = 3;  // a tap is no drag
    var SNAP_NOTE_MS = 8000;
    var snapNoted = false;  // once on the page

    // The boxes over the map (the X above a corner; map_edit.js: what the position belongs to) are markers of their
    // own pane, over the handles and the labels (tooltips: 650) and below the popups (700); clicks in them stay there.
    function overlay(map, element) {
        if (!map.getPane('mapEditBoxes')) {
            map.createPane('mapEditBoxes').style.zIndex = 660;
        }
        element.remove();  // only on the map, in its marker
        element.hidden = false;
        L.DomEvent.disableClickPropagation(element);
        L.DomEvent.disableScrollPropagation(element);
        return L.marker([0, 0], {icon: L.divIcon({className: 'map-edit-anchor', html: element, iconSize: [0, 0]}),
            interactive: false, keyboard: false, pane: 'mapEditBoxes'});
    }

    function showAt(map, marker, at) {
        if (!at) {
            map.removeLayer(marker);
            return;
        }
        marker.setLatLng(at);
        if (!map.hasLayer(marker)) {
            marker.addTo(map);
        }
    }

    // options: style (of the shape), targets() and walls() (what it snaps to: geometry.snapTargets, the plan's
    // turn), snapNote (the text), cornerBox (the element with the X, [data-edit-remove-corner]), active() (whether
    // editing), and what happens: moving(on) while dragging, changed(s) while it changes, stepped(s) once a step is
    // done (a drag let go, a corner removed), followed(s) after the shape followed, shapeMade(layer), drawRow(s).
    function shapeEditor(map, options) {
        var current = null;  // the state being edited
        var corner = null, cornerDragging = false;  // the marker of the corner of an area tapped last, to remove it
        var snapNote = null;
        var cornerMarker = options.cornerBox ? overlay(map, options.cornerBox) : null;

        function call(name, s, extra) {
            if (options[name]) {
                options[name](s, extra);
            }
        }

        function moving(on) {
            call('moving', on);
        }

        function targets() {
            return options.targets ? options.targets() : [];
        }

        function walls() {
            return options.walls ? options.walls() : null;
        }

        function snapped(at) {
            if (!at || !options.snapNote || !window.matchMedia('(any-pointer: fine)').matches) {
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
                .setLatLng(at).setContent(options.snapNote);
            map.openTooltip(snapNote);
            window.setTimeout(function () {
                map.closeTooltip(snapNote);
                snapNote = null;
            }, SNAP_NOTE_MS);
        }

        function snappedCorner(event) {
            snapped(event.snapLatLng || (event.marker && event.marker.getLatLng()));
        }

        // The X above the chosen corner, not while a corner is dragged.
        function showCorner() {
            if (cornerMarker) {
                var active = !options.active || options.active();
                showAt(map, cornerMarker, active && current && current.area && corner && !cornerDragging ?
                    corner.getLatLng() : null);
            }
        }

        // A corner of an area is removed by tapping it and then the X, tapping it again or Delete; a right click on
        // it removes it at once. All go through Leaflet-Geoman's removal (its removeVertexOn event), which keeps at
        // least three corners and refuses removals that would make the edges cross.
        function chooseCorner(marker) {
            if (corner && corner._icon) {
                corner._icon.classList.remove('map-corner-chosen');
            }
            corner = marker;
            if (corner && corner._icon) {
                corner._icon.classList.add('map-corner-chosen');
            }
            showCorner();
        }

        function removeCorner() {
            if (corner && current && current.area) {
                corner.fire(current.area.pm.options.removeVertexOn || 'contextmenu');
            }
        }

        if (options.cornerBox) {
            options.cornerBox.querySelector('[data-edit-remove-corner]').addEventListener('click', removeCorner);
        }

        // What is edited keeps its clicks from the map (a drag by the inside ends in one, too), which would let it go.
        function ownClicks(layer) {
            layer.on('click', L.DomEvent.stop);
        }

        function watchArea(s) {
            var area = s.area;
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
                showCorner();
            });
            area.on('pm:markerdragend', function () {
                cornerDragging = false;
                moving(false);
                showCorner();
            });
            area.on('pm:edit', function () {
                showCorner();
                call('changed', s);
                call('stepped', s);
            });
            dragArea(s);
        }

        // The area as a whole is dragged by its inside; its corners keep their handles. Geoman drags a layer only
        // with its corners' editing off, so that goes off while dragging.
        function dragArea(s) {
            var area = s.area, path = area.getElement();
            path.classList.add('map-edit-area');
            path.addEventListener('pointerdown', function (event) {
                if (event.button !== 0 || current !== s || s.area !== area) {
                    return;
                }
                var start = map.mouseEventToContainerPoint(event), moved = false;
                var rings = area.getLatLngs().map(function (ring) {
                    return ring.map(function (at) { return map.latLngToContainerPoint(at); });
                });
                map.dragging.disable();  // before the map's own listener, further up
                path.setPointerCapture(event.pointerId);

                function move(pointer) {
                    var shift = map.mouseEventToContainerPoint(pointer).subtract(start);
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
                        return ring.map(function (at) { return map.containerPointToLatLng(at.add(shift)); });
                    }));
                    call('changed', s);
                }

                function up() {
                    path.removeEventListener('pointermove', move);
                    path.removeEventListener('pointerup', up);
                    path.removeEventListener('pointercancel', up);
                    map.dragging.enable();
                    moving(false);
                    if (moved && current === s && s.area === area) {
                        area.pm.enable(AREA_EDITING);
                        call('stepped', s);
                    }
                }
                path.addEventListener('pointermove', move);
                path.addEventListener('pointerup', up);
                path.addEventListener('pointercancel', up);
            });
        }

        function language() {
            map.pm.setLang((document.documentElement.lang || 'en').slice(0, 2));
        }

        // An area that is there: its corners editable.
        function editArea(s) {
            current = s;
            s.area.setStyle(options.style);
            s.area.addTo(map);
            language();
            watchArea(s);
            s.area.pm.enable(AREA_EDITING);
            showCorner();
        }

        // A new area: its corners clicked one after the other; `done` once it is closed.
        function drawArea(s, done) {
            current = s;
            language();
            map.once('pm:drawstart', function (event) { event.workingLayer.on('pm:snap', snappedCorner); });
            map.pm.enableDraw('Polygon', Object.assign({pathOptions: options.style}, AREA_EDITING));
            map.once('pm:create', function (event) {
                if (current !== s) {
                    map.removeLayer(event.layer);
                    return;
                }
                s.area = event.layer;
                watchArea(s);
                s.area.pm.enable(AREA_EDITING);
                call('changed', s);
                if (done) {
                    done(s);
                }
            });
        }

        // The corners as they were (a step undone or redone).
        function setArea(s, rings) {
            chooseCorner(null);
            s.area.pm.disable();
            s.area.setLatLngs(rings);
            s.area.pm.enable(AREA_EDITING);
            showCorner();
        }

        function metresPerPixel() {
            var middle = map.getSize().divideBy(2);
            return map.distance(map.containerPointToLatLng(middle), map.containerPointToLatLng(middle.add([0, 100]))) /
                100;
        }

        function knobPosition(s, side) {
            var width = s.size[0] * (s.count || 1), depth = s.size[1];
            var reach = (side % 2 ? width : depth) / 2 +
                Math.max(Math.min(width, depth) * 0.4, KNOB_PIXELS * metresPerPixel());
            var angle = SIDES[side] * Math.PI / 180;
            return geometry.offset(s.center, reach * Math.sin(angle), reach * Math.cos(angle), s.rotation);
        }

        // All but the one being dragged (`turning`: its side).
        function placeKnobs(s, turning) {
            (s.knobs || []).forEach(function (knob, side) {
                if (side !== turning) {
                    knob.setLatLng(knobPosition(s, side));
                }
            });
            if (s.corners) {
                var at = geometry.rectangle(s.center, s.size, s.rotation);
                s.corners.forEach(function (handle, index) {
                    if (index !== s.sizing) {
                        handle.setLatLng(at[index]);
                    }
                });
            }
        }
        map.on('zoomend', function () {
            if (current && current.knobs) {
                placeKnobs(current);
            }
        });

        // The middles of a row's rectangles around `center` (the row's middle), side by side along their width; one
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

        // Where a point or rectangle goes when placed or dragged there (Alt: no snapping).
        function snapCenter(s, at, free) {
            if (free) {
                return at;
            }
            var center = geometry.snapCenter(map, targets(), at, function (middle) { return corners(s, middle); });
            if (center !== at) {
                snapped(center);
            }
            return center;
        }

        function follow(s, turning) {
            if (s.count) {
                call('drawRow', s);
                placeKnobs(s, turning);
            } else if (s.size) {
                s.shape.setLatLngs(geometry.rectangle(s.center, s.size, s.rotation));
                placeKnobs(s, turning);
            } else {
                s.shape.setLatLng(s.center);
            }
            call('followed', s);
        }

        // The handles of a point, rectangle or row: drawn anew (dropHandles first).
        function drawHandles(s) {
            current = s;
            s.shape = s.count ? L.featureGroup() : s.size ? L.polygon(geometry.rectangle(s.center, s.size, s.rotation),
                options.style) : L.circleMarker(s.center, Object.assign({radius: 8}, options.style));
            s.shape.addTo(map);
            ownClicks(s.shape);
            call('shapeMade', s.shape);
            if (s.count) {
                call('drawRow', s);
            }
            s.handle = L.marker(s.center, {draggable: true, keyboard: false, title: options.dragHandle || '',
                icon: L.divIcon({className: 'map-place-handle', iconSize: [18, 18]})}).addTo(map);
            s.handle.on('drag', function (event) {
                s.center = snapCenter(s, event.target.getLatLng(), event.originalEvent && event.originalEvent.altKey);
                follow(s);
                call('changed', s);
            });
            s.handle.on('dragstart', function () { moving(true); });
            s.handle.on('dragend', function () {
                moving(false);
                s.handle.setLatLng(s.center);
                call('stepped', s);
            });
            s.knobs = null;
            if (!s.size) {
                return;
            }
            s.knobs = SIDES.map(function (angle, side) {
                var knob = L.marker(knobPosition(s, side), {draggable: true, keyboard: false, title: options.turnHandle || '',
                    icon: L.divIcon({className: 'map-place-handle map-place-knob', iconSize: [16, 16]})}).addTo(map);
                knob.on('dragstart', function () { moving(true); });
                knob.on('drag', function (event) {
                    var turned = (geometry.bearing(s.center, event.target.getLatLng()) - angle + 360) % 360;
                    s.rotation = event.originalEvent && event.originalEvent.altKey ? turned :
                        geometry.snapRotation(map, targets(), s.center, turned, walls());
                    if (s.rotation !== turned) {
                        snapped(event.target.getLatLng());
                    }
                    follow(s, side);
                    call('changed', s);
                });
                knob.on('dragend', function () {
                    moving(false);
                    knob.setLatLng(knobPosition(s, side));
                    call('stepped', s);
                });
                return knob;
            });
            s.corners = options.resizable && !s.count && !s.sizeFixed ? [0, 1, 2, 3].map(function (index) {
                return sizeHandle(s, index);
            }) : null;
        }

        // A corner of a rectangle that sizes it: dragged, the opposite corner stays (snapping as a corner does).
        function sizeHandle(s, index) {
            var handle = L.marker(geometry.rectangle(s.center, s.size, s.rotation)[index], {draggable: true,
                keyboard: false, title: options.sizeHandle || '',
                icon: L.divIcon({className: 'map-place-handle map-place-corner', iconSize: [12, 12]})}).addTo(map);
            var opposite = null;
            handle.on('dragstart', function () {
                moving(true);
                s.sizing = index;
                opposite = geometry.rectangle(s.center, s.size, s.rotation)[(index + 2) % 4];
            });
            handle.on('drag', function (event) {
                var at = event.target.getLatLng();
                if (!(event.originalEvent && event.originalEvent.altKey)) {
                    var snapped_ = geometry.snapCenter(map, targets(), at, function (corner) { return [corner]; });
                    if (snapped_ !== at) {
                        snapped(snapped_);
                    }
                    at = snapped_;
                }
                var drawn = geometry.fromCorners(opposite, at, s.rotation);
                if (drawn.size[0] < 0.01 || drawn.size[1] < 0.01) {  // at least a centimetre
                    return;
                }
                s.center = drawn.center;
                s.size = drawn.size.map(function (metres) { return Math.max(1, Math.round(metres * 100)) / 100; });
                s.handle.setLatLng(s.center);
                follow(s);
                call('sized', s);
                call('changed', s);
            });
            handle.on('dragend', function () {
                moving(false);
                s.sizing = null;
                placeKnobs(s);
                call('stepped', s);
            });
            return handle;
        }

        function dropHandles(s) {
            ['shape', 'handle'].forEach(function (name) {
                if (s[name]) {
                    map.removeLayer(s[name]);
                    s[name] = null;
                }
            });
            (s.knobs || []).concat(s.corners || []).forEach(function (handle) { map.removeLayer(handle); });
            s.knobs = s.corners = null;
        }

        function dropArea(s) {
            if (s.area) {
                if (s.area.pm) {
                    s.area.pm.disable();
                    if (s.area.pm.disableLayerDrag) {
                        s.area.pm.disableLayerDrag();
                    }
                }
                map.removeLayer(s.area);
            }
        }

        // Done with it: its layers go (the area's polygon too, unless `keepArea`).
        function clear(s, keepArea) {
            if (map.pm) {
                map.pm.disableDraw();
            }
            if (s) {
                dropHandles(s);
                if (keepArea) {
                    if (s.area && s.area.pm) {
                        s.area.pm.disable();
                    }
                } else {
                    dropArea(s);
                }
            }
            chooseCorner(null);
            moving(false);
            if (current === s) {
                current = null;
            }
        }

        return {
            editArea: editArea, drawArea: drawArea, setArea: setArea, drawHandles: drawHandles,
            dropHandles: dropHandles, follow: follow, clear: clear, snapCenter: snapCenter, corners: corners,
            centers: centers, snapped: snapped, chooseCorner: chooseCorner, removeCorner: removeCorner,
            showCorner: showCorner, ownClicks: ownClicks,
            corner: function () { return corner; }
        };
    }

    // Undo and redo: each step is an entry of the browser's history (back and forward undo and redo it; so do the
    // arrows and Ctrl+Z, through the history), its state a snapshot kept here. Entries of an editing that is gone
    // (saved, discarded, another page load) are passed over, in the direction one went. options: undo and redo (the
    // buttons), snapshot() and restore(state) of what is edited, active() (whether editing), changed() after each
    // step, undone or redone one.
    function editSteps(options) {
        var steps = [], step = 0, session = null;
        var here = history.state && history.state.mapEdit ? history.state.mapEdit.seq : 0;  // the entry shown
        var seq = here;  // the last entry made

        function same(one, other) {
            return JSON.stringify(one) === JSON.stringify(other);
        }

        function entry() {
            return Object.assign({}, history.state, {mapEdit: {session: session, step: step, seq: here}});
        }

        function show() {
            options.undo.disabled = !session || step === 0;
            options.redo.disabled = !session || step >= steps.length - 1;
        }

        function changed() {
            if (options.changed) {
                options.changed();
            }
        }

        // The state as it is when editing starts: the first step, in the entry shown.
        function begin() {
            session = Math.random().toString(36).slice(2);
            steps = [options.snapshot()];
            step = 0;
            here = seq += 1;
            history.replaceState(entry(), '');
            show();
            changed();
        }

        function end() {
            session = null;
            steps = [];
            step = 0;
            show();
        }

        function record() {
            if (!session) {
                return;
            }
            var now = options.snapshot();
            if (same(now, steps[step])) {
                return;
            }
            steps = steps.slice(0, step + 1).concat([now]);
            step += 1;
            here = seq += 1;
            history.pushState(entry(), '');
            show();
            changed();
        }

        window.addEventListener('popstate', function (event) {
            var state = event.state && event.state.mapEdit;
            if (!state) {
                return;
            }
            var from = here;
            here = state.seq;
            if (session && state.session === session) {
                step = state.step;
                options.restore(steps[step]);
                show();
                changed();
            } else {
                history.go(state.seq < from ? -1 : 1);
            }
        });
        options.undo.addEventListener('click', function () {
            if (session && step > 0) {
                history.back();
            }
        });
        options.redo.addEventListener('click', function () {
            if (session && step < steps.length - 1) {
                history.forward();
            }
        });
        document.addEventListener('keydown', function (event) {
            if (!session || (options.active && !options.active()) || !(event.ctrlKey || event.metaKey) ||
                    event.altKey || event.target.closest('input, textarea, select, [contenteditable]')) {
                return;
            }
            var key = event.key.toLowerCase();
            if (key === 'z' && !event.shiftKey) {
                event.preventDefault();
                options.undo.click();
            } else if (key === 'y' || (key === 'z' && event.shiftKey)) {
                event.preventDefault();
                options.redo.click();
            }
        });
        show();
        return {
            begin: begin, end: end, record: record, same: same,
            started: function () { return Boolean(session); },
            // Changed since editing started.
            unsaved: function () { return Boolean(session && steps.length && !same(options.snapshot(), steps[0])); }
        };
    }

    // Enter or Ctrl+S (⌘S) saves; not Enter on a button or link (it presses them), in a field outside `fields` (the
    // editor's own fields, a function of the element) or in a dialog. A corner's handle that has the focus (Leaflet
    // makes markers buttons) saves, too, instead of being "clicked" (and removed). Delete or Backspace removes the
    // chosen corner. options: active(), save() (returns whether it saved or tried to), fields(element), editor.
    function editKeys(options) {
        document.addEventListener('keydown', function (event) {
            if (!options.active() || event.defaultPrevented || event.isComposing || event.target.closest('.modal')) {
                return;
            }
            if ((event.key === 'Delete' || event.key === 'Backspace') &&
                    !event.target.closest('input, textarea, select, [contenteditable]')) {
                if (options.editor && options.editor.corner()) {
                    event.preventDefault();
                    options.editor.removeCorner();
                } else if (options.remove && options.remove()) {
                    event.preventDefault();
                }
                return;
            }
            var saveKey = (event.ctrlKey || event.metaKey) && !event.altKey && !event.shiftKey &&
                event.key.toLowerCase() === 's';
            var enter = event.key === 'Enter' && !event.ctrlKey && !event.metaKey && !event.altKey && !event.shiftKey;
            if (!(saveKey || enter)) {
                return;
            }
            if (enter && (event.target.closest('button, a, textarea, select, [contenteditable], ' +
                    '[role=button]:not(.leaflet-marker-icon)') ||
                    (event.target.closest('input') && !(options.fields && options.fields(event.target))))) {
                return;
            }
            if (saveKey) {
                event.preventDefault();  // not the browser's "Save page"
            }
            if (options.save()) {
                event.preventDefault();
            }
        });
    }

    Object.assign(ZamMap, {shapeEditor: shapeEditor, editSteps: editSteps, editKeys: editKeys,
        AREA_EDITING: AREA_EDITING, editBox: overlay, showBox: showAt});
})();
