// Placing a location or unique item on the map (maps/views.py place_context, LocationShapeView, ItemPositionView).
// A click sets where it is. A storage unit (or unique item) is a point or a rectangle of the width and depth entered
// here; the slider turns it too. Without a size, a rectangle is drawn by two opposite corners (a click on each, or
// dragging from one to the other), along the turn set (at first the plan's walls). Levels, rooms and areas (and unique
// items, if chosen) get an area drawn with Leaflet-Geoman. The handles, corners, snapping and steps are those of the
// map's edit mode (map_shape_edit.js). Two uses:
//   [data-map-place]  the grey box on the page of a location or unique item: the map as on the large one, saves at once;
//   [data-map-pick]   a step in the move dialogs: fills hidden fields that go with the move (signals.moved).
(function () {
    'use strict';

    var geometry = ZamMap.geometry, planRotation = geometry.planRotation;
    var STYLE = {color: '#d63384', weight: 3, fillOpacity: 0.15};

    function csrf(root) {
        var input = root.querySelector('[name=csrfmiddlewaretoken]') ||
            document.querySelector('[name=csrfmiddlewaretoken]');
        return input ? input.value : '';
    }

    function Placer(root, canvas) {
        var self = this;
        this.root = root;
        this.canvas = canvas;
        this.hint = root.querySelector('[data-place-hint]');
        this.shapeBox = root.querySelector('[data-place-shape]');
        this.kindGroup = root.querySelector('[data-place-kinds]');
        this.sizeBox = root.querySelector('[data-place-size]');
        this.widthInput = root.querySelector('[data-place-width]');
        this.depthInput = root.querySelector('[data-place-depth]');
        this.rotationBox = root.querySelector('[data-place-rotation]');
        this.rotationInput = root.querySelector('[data-place-rotation] input[type=range]');
        this.rotationOutput = root.querySelector('[data-place-rotation] output');
        this.moveBox = root.querySelector('[data-place-move]');
        this.moveLabel = root.querySelector('[data-place-move-label]');
        this.map = null;
        this.editing = false;
        this.onStep = null;  // after each step (a drag let go, a click, a size or turn entered)
        this.reset();
        this.rotationInput.addEventListener('input', function () {
            self.rotation = Number(self.rotationInput.value);
            self.changed = true;
            self.redraw();
        });
        this.rotationInput.addEventListener('change', function () { self.stepped(); });  // let go
        root.querySelectorAll('[data-place-turn]').forEach(function (button) {
            button.addEventListener('click', function () {
                self.rotation = (self.rotation + Number(button.dataset.placeTurn) + 360) % 360;
                self.changed = true;
                self.redraw();
                self.stepped();
            });
        });
        root.querySelectorAll('[data-place-kind]').forEach(function (radio) {
            radio.addEventListener('change', function () {
                self.setKind(radio.value);
                self.stepped();
            });
        });
        [this.widthInput, this.depthInput].forEach(function (input) {
            input.addEventListener('input', function () {
                self.readSize();
                self.corners.reset();
                self.changed = true;
                self.redraw();
                self.sayWhatToDo();
            });
            input.addEventListener('change', function () { self.stepped(); });  // entered
        });
    }

    Placer.prototype.reset = function () {
        this.context = null;
        this.center = null;
        this.area = null;
        this.rotation = 0;
        this.walls = null;
        this.kind = 'point';
        this.size = null;
        this.moveTo = null;
        this.changed = false;
        this.s = null;  // what the shape editor changes: {center, rotation, size} or {area}
    };

    Placer.prototype.say = function (text) {
        if (this.hint) {
            this.hint.textContent = text || '';
        }
    };

    Placer.prototype.own = function () {
        return (this.context && this.context.own) || {};
    };

    Placer.prototype.isRectangle = function () {
        return this.kind === 'rectangle' && Boolean(this.size);
    };

    Placer.prototype.readSize = function () {
        var width = Number(this.widthInput.value), depth = Number(this.depthInput.value);
        this.size = width > 0 && depth > 0 ? [width / 100, depth / 100] : null;
    };

    Placer.prototype.sayWhatToDo = function () {
        var strings = this.root.dataset;
        if (this.kind === 'area') {
            this.say(this.area ? strings.editArea : strings.drawArea);
            return;
        }
        if (this.kind === 'rectangle' && !this.size) {
            this.say(strings.drawRectangle);
        } else {
            this.say(this.isRectangle() ? strings.clickRectangle : strings.clickPoint);
        }
    };

    // The map (made the first time) without anything on it but its background.
    Placer.prototype.prepare = function () {
        var self = this;
        var strings = this.root.dataset;
        if (!this.map) {
            this.map = ZamMap.create(this.canvas);
            ZamMap.layerControl(this.map);
            this.map.on('click', function (event) { self.click(event.latlng); });
            this.corners = ZamMap.cornerDrawing(this.map, {
                active: function () { return self.drawsCorners(); },
                rotation: function () { return self.rotation; },
                snap: function (latlng, event) {
                    return event && event.altKey ? latlng : geometry.snapCenter(self.map,
                        geometry.snapTargets(self.map, self.drawn), latlng, function (at) { return [at]; });
                },
                style: STYLE,
                done: function (drawn) { self.drawnCorners(drawn); }
            });
            this.shapes = ZamMap.shapeEditor(this.map, {
                style: STYLE, snapNote: strings.snapNote, dragHandle: strings.dragHandle, turnHandle: strings.turnHandle,
                cornerBox: this.root.querySelector('[data-edit-corner-box]'),
                targets: function () { return geometry.snapTargets(self.map, self.drawn); },
                walls: function () { return self.walls; },
                active: function () { return self.editing; },
                changed: function (s) { self.shapeChanged(s); },
                stepped: function () { self.stepped(); }
            });
        }
        this.corners.reset();
        this.shapes.clear(this.s);
        this.map.closePopup();
        if (this.drawn) {
            this.drawn.off();  // drawn anew
            this.drawn = null;
        }
        var backgrounds = Object.keys(this.map.baseLayers).map(function (name) { return self.map.baseLayers[name]; });
        this.map.eachLayer(function (layer) {
            if (backgrounds.indexOf(layer) < 0) {
                self.map.removeLayer(layer);
            }
        });
    };

    // Loads the context (thing, level, area around) and draws the level to place it on; `query` e.g.
    // "location=12&target=40".
    Placer.prototype.load = function (query) {
        var self = this;
        var strings = this.root.dataset;
        this.prepare();
        this.reset();
        this.say(strings.loading);
        return ZamMap.load(strings.context + '?' + query).then(function (context) {
            self.context = context;
            var own = self.own();
            // The shapes its type allows (admin: map settings): as stored, else a rectangle if its size is known.
            var kinds = (own.kinds || ['point']).filter(function (kind) {
                return !(self.pointsOnly && kind === 'area');  // the move dialogs: a place in the new location
            });
            self.kinds = kinds;
            self.kind = kinds.indexOf(own.kind) >= 0 ? own.kind :
                (kinds.indexOf('rectangle') >= 0 && own.size ? 'rectangle' : kinds[0]);
            self.size = own.size ? own.size.slice() : null;
            self.root.querySelectorAll('[data-place-kind-label]').forEach(function (label) {
                label.hidden = kinds.indexOf(label.dataset.placeKindLabel) < 0;
            });
            self.widthInput.value = self.size ? Math.round(self.size[0] * 100) : '';
            self.depthInput.value = self.size ? Math.round(self.size[1] * 100) : '';
            // A location with dimensions has that size (views.place_context: size_fixed); changed on its page.
            self.widthInput.disabled = self.depthInput.disabled = Boolean(own.size_fixed);
            self.root.querySelector('[data-place-size-fixed]').hidden = !own.size_fixed;
            // The type's usual size as a hint (admin: the location type's map settings).
            self.widthInput.placeholder = own.type_size ? Math.round(own.type_size[0] * 100) : '';
            self.depthInput.placeholder = own.type_size ? Math.round(own.type_size[1] * 100) : '';
            self.checkKind();
            if (!context.data_url) {
                self.say(strings.noLevel);
                return null;
            }
            return ZamMap.load(context.data_url).then(function (data) {
                var drawn = ZamMap.draw(self.map, data, {interactive: false, skip: function (feature) {
                    return feature.properties.id === own.id;
                }});
                self.drawn = drawn;
                self.walls = data.plans.length ? planRotation(data.plans[0]) : null;
                var around = context.around_id ? ZamMap.highlight(drawn, context.around_id) : null;
                if (own.geometry && own.kind === 'area') {
                    self.area = L.geoJSON(own.geometry).getLayers()[0];
                } else if (own.geometry) {
                    self.center = L.latLng(L.geoJSON(own.geometry).getBounds().getCenter());
                    self.rotation = own.rotation || 0;
                } else if (self.walls !== null) {
                    self.rotation = self.walls;
                }
                self.map.invalidateSize();
                var focus = self.area ? self.area.getBounds() : self.center ? L.latLngBounds([self.center]).pad(0.0005)
                    : around ? around.getBounds() : drawn.bounds;
                if (focus) {
                    self.map.fitBounds(focus, {maxZoom: 22, padding: [20, 20], animate: false});
                }
                self.redraw();
                self.showArea();
                self.sayWhatToDo();
                return context;
            });
        }).catch(function () {
            self.say(strings.error);
        });
    };

    // Done editing (saved or cancelled): the handles and corners go, and so do the shape, size and turn above and
    // below the map (redraw shows them while editing).
    Placer.prototype.stop = function () {
        this.editing = false;
        if (this.map) {
            this.corners.reset();
            this.shapes.clear(this.s);
        }
        this.s = null;
        this.shapeBox.hidden = this.rotationBox.hidden = true;
    };

    Placer.prototype.checkKind = function () {
        var self = this;
        this.root.querySelectorAll('[data-place-kind]').forEach(function (radio) {
            radio.checked = radio.value === self.kind;
        });
    };

    // Another shape: an area and a point are different drawings.
    Placer.prototype.setKind = function (kind) {
        var wasArea = this.kind === 'area';
        this.kind = kind;
        this.checkKind();
        this.corners.reset();
        if (wasArea !== (kind === 'area')) {
            this.dropArea();
            this.center = null;
        }
        this.readSize();
        this.changed = true;
        this.redraw();
        this.showArea();
        this.sayWhatToDo();
    };

    // A rectangle without a size yet is drawn by its corners (cornerDrawing).
    Placer.prototype.drawsCorners = function () {
        return this.editing && Boolean(this.context && this.context.data_url) && this.kind === 'rectangle' && !this.size;
    };

    Placer.prototype.drawnCorners = function (drawn) {
        this.center = drawn.center;
        this.size = drawn.size.map(function (metres) { return Math.max(1, Math.round(metres * 100)) / 100; });
        this.widthInput.value = Math.round(this.size[0] * 100);
        this.depthInput.value = Math.round(this.size[1] * 100);
        this.changed = true;
        this.redraw();
        this.sayWhatToDo();
        this.stepped();
    };

    Placer.prototype.click = function (latlng) {
        if (!this.editing || !this.context || !this.context.data_url || this.kind === 'area' ||
                this.drawsCorners() || this.corners.clickTaken()) {
            return;
        }
        this.center = this.shapes.snapCenter({rotation: this.rotation, size: this.isRectangle() ? this.size : null},
            latlng, false);
        this.changed = true;
        this.redraw();
        this.stepped();
    };

    // The shape editor moved, turned or reshaped it.
    Placer.prototype.shapeChanged = function (s) {
        if (s.area) {
            this.area = s.area;
        } else {
            this.center = s.center;
            this.rotation = s.rotation;
            this.rotationInput.value = Math.round(this.rotation);
            this.rotationOutput.textContent = Math.round(this.rotation) + '°';
        }
        this.changed = true;
    };

    Placer.prototype.stepped = function () {
        this.changedFields();
        this.lookUpArea();
        if (this.onStep) {
            this.onStep();
        }
    };

    // The tools for the shape, and the handles of a point or rectangle (drawn anew).
    Placer.prototype.redraw = function () {
        if (this.s && !this.s.area) {
            this.shapes.dropHandles(this.s);
            this.s = null;
        }
        // The choice of shape when the type allows several; the size when it is a rectangle.
        var choice = (this.kinds || []).length > 1;
        this.shapeBox.hidden = !this.editing || !(choice || this.kind === 'rectangle');
        this.kindGroup.hidden = !choice;
        this.sizeBox.hidden = this.kind !== 'rectangle';
        this.rotationBox.hidden = !this.editing || this.kind !== 'rectangle';  // also to turn one before drawing it
        this.rotationInput.value = Math.round(this.rotation);
        this.rotationOutput.textContent = Math.round(this.rotation) + '°';
        if (this.center && this.map && this.editing && this.kind !== 'area') {
            this.s = {center: this.center, rotation: this.rotation, size: this.isRectangle() ? this.size : null};
            this.shapes.drawHandles(this.s);
        }
        this.changedFields();
    };

    // A level's, room's or area's own area: its corners editable, or drawn anew.
    Placer.prototype.showArea = function () {
        var self = this;
        var strings = this.root.dataset;
        if (this.kind !== 'area' || !this.editing || !this.map) {
            return;
        }
        if (typeof this.map.pm === 'undefined') {
            this.say(strings.error);
            return;
        }
        this.s = {area: this.area};
        if (this.area) {
            this.shapes.editArea(this.s);
            this.say(strings.editArea);
        } else {
            var s = this.s;
            this.shapes.drawArea(s, function () {
                self.area = s.area;
                self.changed = true;
                self.say(strings.editArea);
                self.stepped();
            });
            this.say(strings.drawArea);
        }
    };

    Placer.prototype.dropArea = function () {
        if (this.s && this.s.area !== undefined) {
            this.shapes.clear(this.s);
            this.s = null;
        } else if (this.area && this.map) {
            this.map.removeLayer(this.area);
        }
        this.area = null;
    };

    // What can be undone and redone (map_shape_edit.js editSteps).
    Placer.prototype.snapshot = function () {
        return {kind: this.kind, rotation: this.rotation, size: this.size ? this.size.slice() : null,
            center: this.center ? [this.center.lat, this.center.lng] : null,
            area: this.area ? this.area.getLatLngs().map(function (ring) {
                return ring.map(function (corner) { return [corner.lat, corner.lng]; });
            }) : null};
    };

    Placer.prototype.restore = function (state) {
        var rings = state.area && state.area.map(function (ring) {
            return ring.map(function (corner) { return L.latLng(corner[0], corner[1]); });
        });
        if (state.kind !== this.kind || (this.area && !rings)) {
            this.dropArea();
        }
        this.kind = state.kind;
        this.checkKind();
        this.size = state.size && state.size.slice();
        this.widthInput.value = this.size ? Math.round(this.size[0] * 100) : '';
        this.depthInput.value = this.size ? Math.round(this.size[1] * 100) : '';
        this.rotation = state.rotation;
        this.center = state.center ? L.latLng(state.center[0], state.center[1]) : null;
        if (rings && this.area && this.s && this.s.area === this.area) {
            this.shapes.setArea(this.s, rings);
        } else if (rings) {
            this.area = L.polygon(rings, STYLE);
            this.showArea();
        } else if (this.kind === 'area') {
            this.showArea();  // drawn anew
        }
        this.redraw();
        this.sayWhatToDo();
        this.changedFields();
        this.lookUpArea();
    };

    // Where it is placed: the point or the middle of the rectangle, else the middle of the area drawn.
    Placer.prototype.point = function () {
        return this.center || (this.area ? this.area.getBounds().getCenter() : null);
    };

    // The room or area at that point on the level shown (maps/views.py area_at), or null.
    Placer.prototype.areaAt = function () {
        var point = this.point();
        if (!point || !this.context || this.context.level === null) {
            return Promise.resolve(null);
        }
        var url = this.context.at_url + '?level=' + this.context.level + '&lon=' + point.lng + '&lat=' + point.lat +
            '&current=' + (this.context.around || '');
        return ZamMap.load(url).then(function (answer) { return answer.area; });
    };

    // Offers moving it into the room or area the point lies in, if that is not where it is. On another level
    // (nothing around it) moving is confirmed on saving instead.
    Placer.prototype.lookUpArea = function () {
        var self = this;
        if (!this.moveBox || !this.root.dataset.move || !this.center || !this.context || this.context.around === null) {
            if (this.moveBox) {
                this.moveBox.hidden = true;
            }
            this.moveTo = null;
            return;
        }
        this.areaAt().then(function (area) {
            self.moveTo = area && area.pk !== self.context.around ? area : null;
            self.moveBox.hidden = !self.moveTo;
            if (self.moveTo) {
                window.fillTemplate(self.moveLabel, self.root.dataset.moveInto, {title: window.typeName(area.icon, area.title)});
                self.moveBox.querySelector('input').checked = false;
            }
        });
    };

    Placer.prototype.geometry = function () {
        if (this.area) {
            return JSON.stringify(this.area.toGeoJSON().geometry);
        }
        if (this.center) {
            return JSON.stringify({type: 'Point', coordinates: [this.center.lng, this.center.lat]});
        }
        return '';
    };

    // The fields saved with a location's or unique item's position (LocationShapeView, ItemPositionView,
    // positions.placement_from).
    Placer.prototype.fields = function (geometry) {
        var fields = {map_geometry: geometry, map_rotation: this.rotation,
            map_kind: this.kind === 'area' ? 'area' : (this.isRectangle() ? 'rectangle' : 'point')};
        if (this.isRectangle()) {
            fields.map_width_cm = Math.round(this.size[0] * 100);
            fields.map_depth_cm = Math.round(this.size[1] * 100);
        }
        return fields;
    };

    Placer.prototype.changedFields = function () {};

    // The position in the grey box of a location's or unique item's page (place_inline.html): the map as on the large
    // one (map.js focus: highlighted; no popup, the page is about it); whoever may change it switches to editing
    // there, the box growing for it (on phones: the whole screen). Another level moves it into the room or area at the
    // point, once confirmed.
    function setUpInline(root) {
        var cell = root.closest('[data-map-place-cell]') || root;
        var canvas = root.querySelector('[data-place-canvas]');
        var placer = new Placer(root, canvas);
        var strings = root.dataset;
        var levelSelect = root.querySelector('[data-place-level]');
        var confirmBox = root.querySelector('[data-place-confirm]');
        var phone = window.matchMedia('(max-width: 575.98px)');
        var home = null;  // the level it is on
        var level = null;  // another level chosen to move it to
        var editing = false;

        function mode(on) {
            editing = on;
            cell.classList.toggle('is-editing', on);
            canvas.classList.toggle('map-editing', on);
            cell.querySelectorAll('[data-place-view-only]').forEach(function (element) { element.hidden = on; });
            cell.querySelectorAll('[data-place-edit-only]').forEach(function (element) { element.hidden = !on; });
            confirmBox.hidden = true;
            document.body.classList.toggle('map-place-fullscreen', on && phone.matches);
        }

        // Looking at it in the page: scrolling (and on phones swiping) moves the page, not the map.
        function interactive(on) {
            placer.map.scrollWheelZoom[on ? 'enable' : 'disable']();
            placer.map.dragging[on || !L.Browser.mobile ? 'enable' : 'disable']();
        }

        // As on the large map with ?p=: everything as drawn there (the others' popups too), what it shows highlighted.
        function view() {
            if (!strings.focus) {
                return;
            }
            placer.prepare();
            placer.say('');
            ZamMap.load(strings.mapUrl).then(function (data) {
                if (editing) {
                    return;
                }
                placer.map.invalidateSize();
                var drawn = ZamMap.draw(placer.map, data);
                placer.drawn = drawn;
                var layer = ZamMap.focus(drawn, strings.focus);
                if (!layer && drawn.bounds) {
                    placer.map.fitBounds(drawn.bounds, {padding: [10, 10], animate: false});
                }
                interactive(false);
            }).catch(function () {
                placer.say(strings.error);
            });
        }

        function fillLevels(context) {
            home = context.home_level;
            if (!levelSelect || !context.levels || levelSelect.options.length) {
                return;
            }
            if (home === null) {
                levelSelect.add(new Option(strings.noLevelOption, ''));
            }
            context.levels.forEach(function (entry) {
                levelSelect.add(new Option(strings.levelOption.replace('{label}', entry.label), entry.number));
            });
        }

        // Undo and redo, as in the map's edit mode.
        var steps = ZamMap.editSteps({
            undo: root.querySelector('[data-place-undo]'), redo: root.querySelector('[data-place-redo]'),
            snapshot: function () { return placer.snapshot(); },
            restore: function (state) { placer.restore(state); },
            active: function () { return editing; }
        });
        placer.onStep = function () { steps.record(); };

        function load() {
            steps.end();
            placer.editing = true;
            var query = strings.query + (level !== null ? '&level=' + level : '') +
                (levelSelect && !levelSelect.options.length ? '&levels=1' : '');
            return placer.load(query).then(function (context) {
                if (placer.context) {
                    fillLevels(placer.context);
                    if (levelSelect) {
                        levelSelect.value = level !== null ? String(level) : (home === null ? '' : String(home));
                    }
                }
                interactive(true);
                if (editing) {
                    steps.begin();
                }
                return context;
            });
        }

        function edit() {
            mode(true);
            load();
        }

        // Cancelling forgets what was changed and not saved (modals.js: dialogs forget on close).
        function cancel() {
            steps.end();
            level = null;
            placer.stop();
            mode(false);
            view();
        }

        cell.querySelectorAll('[data-place-start]').forEach(function (button) {
            button.addEventListener('click', edit);
        });
        root.querySelectorAll('[data-place-cancel]').forEach(function (button) {
            button.addEventListener('click', cancel);
        });
        cell.addEventListener('keydown', function (event) {
            if (event.key === 'Escape' && editing && !event.defaultPrevented) {
                cancel();
            }
        });
        phone.addEventListener('change', function () {
            document.body.classList.toggle('map-place-fullscreen', editing && phone.matches);
            if (placer.map) {
                placer.map.invalidateSize();
            }
        });
        if (levelSelect) {
            levelSelect.addEventListener('change', function () {
                var value = levelSelect.value;
                level = value === '' || Number(value) === home ? null : Number(value);
                confirmBox.hidden = true;
                load();
            });
        }

        function post(url, fields) {
            var body = new FormData();
            body.append('csrfmiddlewaretoken', csrf(root));
            Object.keys(fields).forEach(function (name) { body.append(name, fields[name]); });
            return fetch(url, {method: 'POST', body: body, credentials: 'same-origin',
                headers: {'Accept': 'application/json'}});
        }

        // Saved: the page anew (after a move: the page it was sent to, its address may have changed).
        function finish(response, moving) {
            if (!response.ok) {
                return response.json().then(function (answer) { throw new Error(answer.error || response.status); },
                    function () { throw new Error(response.status); });
            }
            if (moving && !response.redirected) {
                // The move form came back with its errors (LocationMoveView).
                return response.text().then(function (html) {
                    var page = new DOMParser().parseFromString(html, 'text/html');
                    var errors = Array.prototype.map.call(page.querySelectorAll('.invalid-feedback, .errorlist, ' +
                        '.alert-danger'), function (element) { return element.textContent.trim(); });
                    throw new Error(errors.filter(Boolean).join(' ') || strings.error);
                });
            }
            leaving = true;
            if (response.redirected) {
                window.location.assign(response.url);
            } else {
                window.location.reload();
            }
        }

        function send(url, data, moving) {
            post(url, data).then(function (response) { return finish(response, moving); })
                .catch(function (error) { placer.say(error.message || strings.error); });
        }

        function move() {
            var data = placer.fields(placer.geometry());
            data[strings.moveField] = placer.moveTo.pk;
            send(strings.move, data, true);
        }

        var save = root.querySelector('[data-place-save]');
        if (save) {
            save.addEventListener('click', function () {
                var geometry = placer.geometry();
                if (!geometry) {
                    placer.say(strings.nothing);
                    return;
                }
                if (placer.kind === 'rectangle' && !placer.size) {
                    placer.say(strings.enterSize);
                    return;
                }
                if (level !== null) {
                    // Another level: into the room or area at the point, once confirmed.
                    placer.areaAt().then(function (area) {
                        placer.moveTo = area;
                        if (!area) {
                            placer.say(strings.needArea);
                            return;
                        }
                        var option = levelSelect.options[levelSelect.selectedIndex];
                        window.fillTemplate(confirmBox.querySelector('[data-place-confirm-text]'), strings.confirmMove,
                            {title: window.typeName(area.icon, area.title), level: option ? option.text : level});
                        confirmBox.hidden = false;
                        confirmBox.querySelector('[data-place-confirm-yes]').focus();
                    }).catch(function () { placer.say(strings.error); });
                    return;
                }
                if (placer.moveTo && placer.moveBox.querySelector('input').checked) {
                    move();
                } else {
                    send(strings.save, placer.fields(geometry), false);
                }
            });
            confirmBox.querySelector('[data-place-confirm-yes]').addEventListener('click', move);
            confirmBox.querySelector('[data-place-confirm-no]').addEventListener('click', function () {
                confirmBox.hidden = true;
            });
            // Enter or Ctrl+S (⌘S) saves (in the confirmation: moves), Delete removes the chosen corner.
            ZamMap.editKeys({
                active: function () { return editing; }, editor: {
                    corner: function () { return placer.shapes && placer.shapes.corner(); },
                    removeCorner: function () { placer.shapes.removeCorner(); }
                },
                fields: function (element) { return root.contains(element); },
                save: function () {
                    (confirmBox.hidden ? save : confirmBox.querySelector('[data-place-confirm-yes]')).click();
                    return true;
                }
            });
        }
        var remove = root.querySelector('[data-place-remove]');
        if (remove) {
            remove.addEventListener('click', function () {
                send(strings.save, placer.fields(''), false);
            });
        }
        // Leaving the page while editing with a change not saved asks first (as on the large map).
        var leaving = false;
        window.addEventListener('beforeunload', function (event) {
            if (editing && !leaving && (steps.unsaved() || level !== null)) {
                event.preventDefault();
                event.returnValue = '';  // older browsers ask only with this
            }
        });
        mode(false);
        view();
    }

    // A step in a move dialog: the place in the new location, sent along with the move.
    function setUpPick(root) {
        var form = root.closest('form');
        var placer = new Placer(root, root.querySelector('[data-place-canvas]'));
        var strings = root.dataset;
        var panel = root.querySelector('[data-pick-panel]');
        var target = form.querySelector('[name="' + strings.targetField + '"]');
        placer.moveBox = null;  // the move dialog chooses where it goes
        placer.pointsOnly = true;
        placer.editing = true;

        placer.changedFields = function () {
            var geometry = placer.geometry();
            var fields = placer.fields(geometry);
            ['map_geometry', 'map_kind', 'map_rotation', 'map_width_cm', 'map_depth_cm'].forEach(function (name) {
                form.querySelector('[name=' + name + ']').value = geometry && name in fields ? fields[name] : '';
            });
        };

        function load() {
            if (panel.hidden) {
                return;
            }
            var query = strings.query + (target && target.value ? '&target=' + target.value : '');
            placer.editing = true;
            placer.load(query).then(function () {
                placer.map.invalidateSize();
                placer.changedFields();
            });
        }

        root.querySelector('[data-pick-toggle]').addEventListener('click', function () {
            panel.hidden = !panel.hidden;
            if (panel.hidden) {
                placer.center = null;
                placer.redraw();
            }
            load();
        });
        if (target) {
            target.addEventListener('change', load);
            if (window.jQuery) {
                window.jQuery(target).on('change', load);  // the search field (select2) fires jQuery events
            }
        }
        // Closing the dialog forgets the mark (modals.js: dialogs forget on close).
        var modal = root.closest('.modal');
        if (modal) {
            modal.addEventListener('hidden.bs.modal', function () {
                panel.hidden = true;
                placer.center = null;
                if (placer.map) {
                    placer.redraw();
                } else {
                    placer.changedFields();
                }
            });
        }
    }

    document.querySelectorAll('[data-map-place]').forEach(setUpInline);
    document.querySelectorAll('[data-map-pick]').forEach(setUpPick);
})();
