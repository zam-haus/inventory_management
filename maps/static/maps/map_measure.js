// Measuring on the map page (maps/map.html), for everyone: a distance along a line, an area (with its perimeter) and
// a radius around a point. Clicks set the points; they go through what is drawn, so no popup opens. A click on the
// last point again finishes a line (a double click does that), a click on the first point an area, the second click
// a circle; Escape gives up the one being drawn. Afterwards the points can be dragged. Nothing is saved: closing the
// bar removes the measurements. Not together with the edit mode (map_edit.js), whose clicks select and draw.
(function () {
    'use strict';

    var bar = document.querySelector('[data-map-measure]');
    var toggleButton = document.querySelector('[data-map-measure-toggle]');
    var page = window.ZamMap && ZamMap.page;
    if (!bar || !toggleButton || !page) {
        return;
    }
    var map = page.map, strings = bar.dataset, hint = bar.querySelector('[data-measure-hint]');
    var toolButtons = bar.querySelectorAll('[data-measure-tool]');
    var STYLE = {color: '#6f42c1', weight: 3, fillColor: '#6f42c1', fillOpacity: 0.12, dashArray: null,
        interactive: false, pane: 'map-measure'};
    var FINISH_PIXELS = 8;  // a click this close to the last (or, for an area, the first) point finishes
    map.createPane('map-measure').style.zIndex = 450;  // over the positions, under labels and handles
    var handleIcon = L.divIcon({className: 'map-measure-handle', iconSize: [12, 12]});
    var lang = document.documentElement.lang || undefined;

    var open = false, tool = null, drawing = null, measurements = [];

    function number(value, digits) {
        return value.toLocaleString(lang, {minimumFractionDigits: digits, maximumFractionDigits: digits});
    }

    function metres(value) {
        return value < 1000 ? number(value, value < 10 ? 2 : 1) + ' m' : number(value / 1000, 3) + ' km';
    }

    function squareMetres(value) {
        return number(value, value < 100 ? 2 : 0) + ' m²';
    }

    function lengthOf(points, closed) {
        var sum = 0;
        for (var i = 1; i < points.length; i += 1) {
            sum += map.distance(points[i - 1], points[i]);
        }
        return closed && points.length > 2 ? sum + map.distance(points[points.length - 1], points[0]) : sum;
    }

    // On a plane in metres around the first point (a building's or a site's size: the earth's curve does not count),
    // with the earth's radius of map.distance, so that the area fits the lengths.
    function areaOf(points) {
        var north = L.CRS.Earth.R * Math.PI / 180, origin = points[0], sum = 0;
        var east = north * Math.cos(origin.lat * Math.PI / 180);
        var xy = points.map(function (p) { return [(p.lng - origin.lng) * east, (p.lat - origin.lat) * north]; });
        for (var i = 0; i < xy.length; i += 1) {
            var j = (i + 1) % xy.length;
            sum += xy[i][0] * xy[j][1] - xy[j][0] * xy[i][1];
        }
        return Math.abs(sum) / 2;
    }

    // A measurement: its points (a circle: centre and a point on it), the shape, the handles and the label. `cursor`
    // is where the pointer is while it is drawn: the next point.
    function Measurement(kind) {
        this.kind = kind;
        this.points = [];
        this.handles = [];
        this.shape = null;
        this.label = L.tooltip({permanent: true, direction: 'right', offset: [10, 0], className: 'map-measure-label'});
    }

    Measurement.prototype.update = function (cursor) {
        var points = cursor ? this.points.concat([cursor]) : this.points, text = null, at = points[points.length - 1];
        if (!points.length) {
            return;
        }
        if (this.kind === 'circle') {
            var radius = points.length > 1 ? map.distance(points[0], points[1]) : 0;
            if (!this.shape) {
                this.shape = L.circle(points[0], Object.assign({radius: radius}, STYLE)).addTo(map);
            }
            this.shape.setLatLng(points[0]).setRadius(radius);
            if (points.length > 1) {
                text = strings.radius + ' ' + metres(radius) + ' · ' + squareMetres(Math.PI * radius * radius);
            }
        } else {
            if (!this.shape) {
                this.shape = (this.kind === 'area' ? L.polygon([], STYLE) : L.polyline([], STYLE)).addTo(map);
            }
            this.shape.setLatLngs(points);
            if (this.kind === 'line' && points.length > 1) {
                text = metres(lengthOf(points, false));
            } else if (this.kind === 'area' && points.length > 2) {
                text = squareMetres(areaOf(points)) + ' · ' + strings.perimeter + ' ' + metres(lengthOf(points, true));
                at = this.finished ? this.shape.getCenter() : at;
            }
        }
        if (text) {
            this.label.setLatLng(at).setContent(text);
            if (!map.hasLayer(this.label)) {
                this.label.addTo(map);
            }
        } else if (map.hasLayer(this.label)) {
            map.removeLayer(this.label);
        }
    };

    // A draggable handle for each point; dragging a circle's centre moves the whole circle.
    Measurement.prototype.drawHandles = function () {
        var self = this;
        this.handles.forEach(function (handle) { map.removeLayer(handle); });
        this.handles = this.points.map(function (point, index) {
            var handle = L.marker(point, {icon: handleIcon, draggable: true, keyboard: false}).addTo(map);
            handle.on('drag', function (event) {
                var to = event.target.getLatLng();
                if (self.kind === 'circle' && index === 0 && self.points.length > 1) {
                    var edge = self.points[1], from = self.points[0];
                    self.points[1] = L.latLng(edge.lat + to.lat - from.lat, edge.lng + to.lng - from.lng);
                    self.handles[1].setLatLng(self.points[1]);
                }
                self.points[index] = to;
                self.update();
            });
            handle.on('click', function () {  // the last point again (a line), the first (an area): finished
                if (drawing === self && ((self.kind === 'line' && index === self.points.length - 1) ||
                        (self.kind === 'area' && index === 0))) {
                    finish();
                }
            });
            return handle;
        });
    };

    Measurement.prototype.remove = function () {
        [this.shape, this.label].concat(this.handles).forEach(function (layer) {
            if (layer && map.hasLayer(layer)) {
                map.removeLayer(layer);
            }
        });
    };

    function say() {
        if (!tool) {
            hint.textContent = strings.choose;
        } else {
            hint.textContent = strings[tool] + (measurements.length ? ' ' + strings.drag : '');
        }
    }

    function enough(measurement) {
        return measurement.points.length >= {line: 2, area: 3, circle: 2}[measurement.kind];
    }

    function finish() {
        var measurement = drawing;
        drawing = null;
        if (!enough(measurement)) {
            measurement.remove();
        } else {
            measurement.finished = true;
            measurements.push(measurement);
            measurement.update();
        }
        say();
    }

    function giveUp() {
        if (drawing) {
            drawing.remove();
            drawing = null;
        }
    }

    function near(a, b) {
        return map.latLngToContainerPoint(a).distanceTo(map.latLngToContainerPoint(b)) <= FINISH_PIXELS;
    }

    map.on('click', function (event) {
        if (!tool) {
            return;
        }
        var at = event.latlng;
        if (!drawing) {
            drawing = new Measurement(tool);
        }
        var points = drawing.points;
        if (points.length && ((tool === 'line' && near(at, points[points.length - 1])) ||
                (tool === 'area' && points.length > 2 && near(at, points[0])))) {
            finish();  // also the second click of a double click
            return;
        }
        points.push(at);
        drawing.drawHandles();
        drawing.update();
        if (tool === 'circle' && points.length === 2) {
            finish();
        }
    });

    map.on('mousemove', function (event) {
        if (drawing) {
            drawing.update(event.latlng);
        }
    });

    function setTool(name) {
        giveUp();
        tool = name;
        toolButtons.forEach(function (button) {
            var on = button.dataset.measureTool === name;
            button.classList.toggle('active', on);
            button.setAttribute('aria-pressed', String(on));
        });
        // Clicks go to the map, through what is drawn (their popups would stop them); a double click finishes.
        page.element.classList.toggle('map-drawing', Boolean(name));
        page.element.classList.toggle('map-measuring', Boolean(name));
        if (name) {
            map.doubleClickZoom.disable();
        } else {
            map.doubleClickZoom.enable();
        }
        say();
    }

    function clearAll() {
        giveUp();
        measurements.forEach(function (measurement) { measurement.remove(); });
        measurements = [];
        say();
    }

    function setOpen(on) {
        open = on;
        if (!on) {
            clearAll();
            setTool(null);
        }
        bar.hidden = !on;
        toggleButton.setAttribute('aria-pressed', String(on));
        if (on) {
            map.closePopup();
            setTool(null);
        }
    }

    var control = L.control({position: 'bottomleft'});
    control.onAdd = function () {
        L.DomEvent.disableClickPropagation(bar);
        L.DomEvent.disableScrollPropagation(bar);
        return bar;
    };
    control.addTo(map);
    bar.hidden = true;

    toolButtons.forEach(function (button) {
        button.addEventListener('click', function () {
            setTool(tool === button.dataset.measureTool ? null : button.dataset.measureTool);
        });
    });
    bar.querySelector('[data-measure-clear]').addEventListener('click', clearAll);
    bar.querySelector('[data-measure-close]').addEventListener('click', function () { setOpen(false); });
    toggleButton.addEventListener('click', function () { setOpen(!open); });
    document.addEventListener('keydown', function (event) {
        if (event.key === 'Escape' && drawing) {
            giveUp();
            say();
        }
    });
    map.on('popupopen', function () {
        if (tool) {
            map.closePopup();
        }
    });
    // The edit mode ends measuring; while it is on, measuring waits.
    new MutationObserver(function () {
        var editing = page.element.classList.contains('map-editing');
        if (editing && open) {
            setOpen(false);
        }
        toggleButton.disabled = editing;
    }).observe(page.element, {attributes: true, attributeFilter: ['class']});
})();
