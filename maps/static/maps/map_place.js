// Placing a location or unique item on the map (maps/views.py place_context, LocationShapeView, ItemPositionView).
// A click sets where it is. A storage unit is a point or a rectangle of the width and depth entered here: the
// middle handle drags it, the outer one turns it; the slider turns it too. Dragging snaps its corners to the corners
// and edges of the rooms, areas and storage units around it, turning to their edges and the plan's walls (Alt while
// dragging: no snapping).
// Levels, rooms and areas get an area drawn with Leaflet-Geoman. Two uses:
//   [data-map-place]  the dialog on the page of a location or unique item: saves at once;
//   [data-map-pick]   a step in the move dialogs: fills hidden fields that go with the move (signals.moved).
(function () {
    'use strict';

    var geometry = ZamMap.geometry, offset = geometry.offset, rectangle = geometry.rectangle;
    var planRotation = geometry.planRotation;

    // Areas snap to the corners and edges of the other areas and storage units (Leaflet-Geoman); Alt: no snapping.
    var AREA_EDITING = {allowSelfIntersection: false, snappable: true, snapDistance: 15};

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
        this.reset();
        this.rotationInput.addEventListener('input', function () {
            self.rotation = Number(self.rotationInput.value);
            self.redraw();
        });
        root.querySelectorAll('[data-place-turn]').forEach(function (button) {
            button.addEventListener('click', function () {
                self.rotation = (self.rotation + Number(button.dataset.placeTurn) + 360) % 360;
                self.redraw();
            });
        });
        root.querySelectorAll('[data-place-kind]').forEach(function (radio) {
            radio.addEventListener('change', function () {
                var wasArea = self.kind === 'area';
                self.kind = radio.value;
                if (wasArea !== (self.kind === 'area')) {  // an area and a point are different drawings
                    self.dropArea();
                    self.center = null;
                }
                self.redraw();
                self.showArea();
                self.sayWhatToDo();
            });
        });
        [this.widthInput, this.depthInput].forEach(function (input) {
            input.addEventListener('input', function () {
                var width = Number(self.widthInput.value), depth = Number(self.depthInput.value);
                self.size = width > 0 && depth > 0 ? [width / 100, depth / 100] : null;
                self.redraw();
                self.sayWhatToDo();
            });
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

    Placer.prototype.sayWhatToDo = function () {
        var strings = this.root.dataset;
        if (!this.editing) {
            // Viewing: where it is, or that only the place around it is known.
            var own = this.own();
            this.say(own.geometry || !this.context || !this.context.around_title ? '' :
                strings.approximate.replace('{where}', this.context.around_title));
            return;
        }
        if (this.kind === 'area') {
            this.say(this.area ? strings.editArea : strings.drawArea);
            return;
        }
        if (this.kind === 'rectangle' && !this.size) {
            this.say(strings.enterSize);
        } else {
            this.say(this.isRectangle() ? strings.clickRectangle : strings.clickPoint);
        }
    };

    // Loads the context (thing, level, area around) and draws the level; `query` e.g. "location=12&target=40".
    Placer.prototype.load = function (query) {
        var self = this;
        var strings = this.root.dataset;
        if (!this.map) {
            this.map = ZamMap.create(this.canvas);
            ZamMap.layerControl(this.map);
            this.map.on('click', function (event) { self.click(event.latlng); });
        }
        if (this.map.pm) {
            this.map.pm.disableDraw();
        }
        if (this.drawn) {
            this.drawn.off();  // drawn anew below
        }
        var backgrounds = Object.keys(this.map.baseLayers).map(function (name) { return self.map.baseLayers[name]; });
        this.map.eachLayer(function (layer) {
            if (backgrounds.indexOf(layer) < 0) {
                self.map.removeLayer(layer);
            }
        });
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
            // The type's usual size as a hint (admin: the location type's map settings).
            self.widthInput.placeholder = own.type_size ? Math.round(own.type_size[0] * 100) : '';
            self.depthInput.placeholder = own.type_size ? Math.round(own.type_size[1] * 100) : '';
            self.root.querySelectorAll('[data-place-kind]').forEach(function (radio) {
                radio.checked = radio.value === self.kind;
            });
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
                self.redraw();
                var focus = self.area ? self.area.getBounds() : self.center ? L.latLngBounds([self.center]).pad(0.0005)
                    : around ? around.getBounds() : drawn.bounds;
                if (focus) {
                    self.map.fitBounds(focus, {maxZoom: 22, padding: [20, 20]});
                }
                self.showArea();
                self.sayWhatToDo();
                return context;
            });
        }).catch(function () {
            self.say(strings.error);
        });
    };

    Placer.prototype.click = function (latlng) {
        if (!this.editing || !this.context || !this.context.data_url || this.kind === 'area') {
            return;
        }
        this.center = this.snappedCenter(latlng);
        this.changed = true;
        this.redraw();
        this.lookUpArea();
    };

    // Where the dragged center goes: a corner of the shape snaps to the corners and edges around it.
    Placer.prototype.snappedCenter = function (center) {
        var self = this;
        return geometry.snapCenter(this.map, geometry.snapTargets(this.map, this.drawn), center, function (at) {
            return self.isRectangle() ? rectangle(at, self.size, self.rotation) : [at];
        });
    };

    // The turn snapped to the edges nearby and the plan's walls.
    Placer.prototype.snapped = function (rotation) {
        return geometry.snapRotation(this.map, geometry.snapTargets(this.map, this.drawn), this.center, rotation,
            this.walls);
    };

    Placer.prototype.knobPosition = function () {
        // Beyond the middle of the rectangle's far side ("north" before turning).
        return offset(this.center, 0, this.size[1] / 2 + Math.max(0.3, this.size[1] * 0.4), this.rotation);
    };

    Placer.prototype.redraw = function () {
        var self = this;
        [this.shape, this.handle, this.knob].forEach(function (layer) {
            if (layer) {
                self.map.removeLayer(layer);
            }
        });
        this.shape = this.handle = this.knob = null;
        var rectangular = this.isRectangle();
        // The choice of shape when the type allows several; the size when it is a rectangle.
        var choice = (this.kinds || []).length > 1;
        this.shapeBox.hidden = !this.editing || !(choice || this.kind === 'rectangle');
        this.kindGroup.hidden = !choice;
        this.sizeBox.hidden = this.kind !== 'rectangle';
        this.rotationBox.hidden = !this.editing || !rectangular;
        this.rotationInput.value = Math.round(this.rotation);
        this.rotationOutput.textContent = Math.round(this.rotation) + '°';
        if (!this.center || !this.map) {
            this.changedFields();
            return;
        }
        var style = Object.assign({}, ZamMap.STYLES[rectangular ? 'storage_unit' : 'item'], {color: '#d63384', weight: 3});
        this.shape = rectangular ? L.polygon(rectangle(this.center, this.size, this.rotation), style)
            : L.circleMarker(this.center, Object.assign({radius: 8}, style));
        this.shape.addTo(this.map);
        if (!this.editing) {
            return;
        }
        this.handle = L.marker(this.center, {draggable: true, keyboard: false, title: this.root.dataset.dragHandle,
            icon: L.divIcon({className: 'map-place-handle', iconSize: [18, 18]})}).addTo(this.map);
        this.handle.on('drag', function (event) {
            var free = event.originalEvent && event.originalEvent.altKey;
            self.center = free ? event.target.getLatLng() : self.snappedCenter(event.target.getLatLng());
            self.changed = true;
            self.follow();
        });
        this.handle.on('dragend', function () {
            self.handle.setLatLng(self.center);
            self.changedFields();
            self.lookUpArea();
        });
        if (rectangular) {
            this.knob = L.marker(this.knobPosition(), {draggable: true, keyboard: false,
                title: this.root.dataset.turnHandle,
                icon: L.divIcon({className: 'map-place-handle map-place-knob', iconSize: [16, 16]})}).addTo(this.map);
            this.knob.on('drag', function (event) {
                var turned = geometry.bearing(self.center, event.target.getLatLng());
                self.rotation = event.originalEvent && event.originalEvent.altKey ? turned : self.snapped(turned);
                self.changed = true;
                self.follow(true);
            });
            this.knob.on('dragend', function () {
                self.knob.setLatLng(self.knobPosition());
                self.changedFields();
            });
        }
        this.changedFields();
    };

    // Moves the drawn shape (and the turning knob unless it is being dragged) along while dragging.
    Placer.prototype.follow = function (turning) {
        if (this.isRectangle()) {
            this.shape.setLatLngs(rectangle(this.center, this.size, this.rotation));
            if (!turning && this.knob) {
                this.knob.setLatLng(this.knobPosition());
            }
            this.rotationInput.value = Math.round(this.rotation);
            this.rotationOutput.textContent = Math.round(this.rotation) + '°';
        } else {
            this.shape.setLatLng(this.center);
        }
    };

    // A level's, room's or area's own area: shown, or editable with Leaflet-Geoman.
    Placer.prototype.showArea = function () {
        if (this.kind !== 'area') {
            return;
        }
        if (this.editing) {
            this.startArea();
        } else if (this.area) {
            this.area.setStyle({color: '#d63384', weight: 3, fillOpacity: 0.15});
            this.area.addTo(this.map);
        }
    };

    Placer.prototype.dropArea = function () {
        if (this.map && this.map.pm) {
            this.map.pm.disableDraw();
        }
        if (this.area) {
            if (this.area.pm) {
                this.area.pm.disable();
            }
            this.map.removeLayer(this.area);
            this.area = null;
        }
    };

    // Switches between looking at the map and changing the position (explicitly, against accidental changes).
    Placer.prototype.setEditing = function (on) {
        this.editing = on;
        if (!on && this.map && this.map.pm) {
            this.map.pm.disableDraw();
            if (this.area && this.area.pm) {
                this.area.pm.disable();
            }
        }
        this.showArea();
        this.redraw();
        this.sayWhatToDo();
    };

    Placer.prototype.startArea = function () {
        var self = this;
        var strings = this.root.dataset;
        if (typeof this.map.pm === 'undefined') {
            this.say(strings.error);
            return;
        }
        this.map.pm.setLang((document.documentElement.lang || 'en').slice(0, 2));
        if (this.area) {
            this.area.addTo(this.map);
            this.area.pm.enable(AREA_EDITING);
            this.area.on('pm:edit', function () { self.changed = true; });
            this.say(strings.editArea);
        } else {
            this.map.pm.enableDraw('Polygon', AREA_EDITING);
            this.map.once('pm:create', function (event) {
                self.area = event.layer;
                self.changed = true;
                self.area.pm.enable(AREA_EDITING);
                self.area.on('pm:edit', function () { self.changed = true; });
                self.say(strings.editArea);
            });
            this.say(strings.drawArea);
        }
    };

    // Offers moving it into the room or area the point lies in, if that is not where it is.
    Placer.prototype.lookUpArea = function () {
        var self = this;
        if (!this.moveBox || !this.root.dataset.move || !this.center || this.context.level === null) {
            return;
        }
        var url = this.context.at_url + '?level=' + this.context.level + '&lon=' + this.center.lng + '&lat=' +
            this.center.lat + '&current=' + this.context.around;
        ZamMap.load(url).then(function (answer) {
            var area = answer.area;
            self.moveTo = area && area.pk !== self.context.around ? area : null;
            self.moveBox.hidden = !self.moveTo;
            if (self.moveTo) {
                self.moveLabel.textContent = self.root.dataset.moveInto.replace('{title}', area.title);
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

    // The fields saved with a location's position (LocationShapeView, positions.placement_from).
    Placer.prototype.fields = function (geometry) {
        var own = this.own();
        var fields = {map_geometry: geometry, map_rotation: this.rotation,
            map_kind: this.kind === 'area' ? 'area' : (this.isRectangle() ? 'rectangle' : 'point')};
        if (this.isRectangle()) {
            fields.map_width_cm = Math.round(this.size[0] * 100);
            fields.map_depth_cm = Math.round(this.size[1] * 100);
        }
        return fields;
    };

    Placer.prototype.changedFields = function () {};

    // The dialog on a location's or unique item's page: shows where it is; who may change it switches to editing.
    function setUpDialog(root) {
        var placer = new Placer(root, root.querySelector('[data-place-canvas]'));
        var strings = root.dataset;

        function mode(editing) {
            root.querySelectorAll('[data-place-view-only]').forEach(function (element) { element.hidden = editing; });
            root.querySelectorAll('[data-place-edit-only]').forEach(function (element) { element.hidden = !editing; });
        }

        function load() {
            mode(false);
            placer.editing = false;
            return placer.load(strings.query).then(function () { placer.map.invalidateSize(); });
        }

        root.addEventListener('shown.bs.modal', load);
        // Closing forgets what was changed and not saved (modals.js: dialogs forget on close).
        root.addEventListener('hidden.bs.modal', function () { mode(false); });
        var edit = root.querySelector('[data-place-edit]');
        if (edit) {
            edit.addEventListener('click', function () {
                mode(true);
                placer.setEditing(true);
            });
        }
        root.querySelector('[data-place-cancel]').addEventListener('click', load);

        function post(url, fields) {
            var body = new FormData();
            body.append('csrfmiddlewaretoken', csrf(root));
            Object.keys(fields).forEach(function (name) { body.append(name, fields[name]); });
            return fetch(url, {method: 'POST', body: body, credentials: 'same-origin',
                headers: {'Accept': 'application/json'}});
        }

        function fields(geometry) {
            return strings.field === 'map_point' ? {map_point: geometry} : placer.fields(geometry);
        }

        function finish(response) {
            if (!response.ok) {
                return response.json().then(function (answer) { throw new Error(answer.error || response.status); },
                    function () { throw new Error(response.status); });
            }
            window.location.reload();
        }

        root.querySelector('[data-place-save]').addEventListener('click', function () {
            var geometry = placer.geometry();
            if (!geometry) {
                placer.say(strings.nothing);
                return;
            }
            if (placer.kind === 'rectangle' && !placer.size) {
                placer.say(strings.enterSize);
                return;
            }
            var data = fields(geometry);
            var moving = placer.moveTo && placer.moveBox.querySelector('input').checked;
            var request;
            if (moving) {
                data[strings.moveField] = placer.moveTo.pk;
                request = post(strings.move, data);
            } else {
                request = post(strings.save, data);
            }
            request.then(finish).catch(function (error) { placer.say(error.message || strings.error); });
        });
        var remove = root.querySelector('[data-place-remove]');
        if (remove) {
            remove.addEventListener('click', function () {
                post(strings.save, fields('')).then(finish).catch(function (error) {
                    placer.say(error.message || strings.error);
                });
            });
        }
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
            if (strings.field === 'map_point') {
                form.querySelector('[name=map_point]').value = geometry;
                return;
            }
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
                placer.changedFields();
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
                placer.changedFields();
            });
        }
    }

    document.querySelectorAll('[data-map-place]').forEach(setUpDialog);
    document.querySelectorAll('[data-map-pick]').forEach(setUpPick);
})();
