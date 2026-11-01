// The map of a level (maps/views.py level_payload): its floor plans, and the positions of building parts, storage
// units, containers and unique items, with a switch for stacked areas (HBB: .1 / .2). ZamMap is shared with the
// placing dialog (map_place.js) and the plan alignment (map_align.js); the map page itself is set up at the end.
(function () {
    'use strict';

    var STYLES = {
        space: {color: '#1f2937', weight: 2, fillColor: '#9ca3af', fillOpacity: 0.12},
        storage_unit: {color: '#b35c00', weight: 1.5, fillColor: '#fd7e14', fillOpacity: 0.45},
        container: {color: '#0b5ed7', weight: 1.5, fillColor: '#6ea8fe', fillOpacity: 0.45},
        // Unique items in petrol, a colour of their own that does not shout: rectangles and polygons lightly filled,
        // as storage units; points solid with a white rim, visible on aerial photos too (ITEM_POINT).
        item: {color: '#0f766e', weight: 1.5, fillColor: '#2dd4bf', fillOpacity: 0.35}
    };
    var ITEM_POINT = {color: '#ffffff', weight: 1.5, opacity: 1, fillColor: '#0f766e', fillOpacity: 0.95, radius: 5};
    // What is clicked on the map (while its popup is open) and what a link names: a wide white halo under it, its own
    // outline twice as thick (select). It keeps its colours, so one still sees what kind of thing it is.
    var HALO_PIXELS = 8;
    // Unique items that are points have a layer of their own, off at first (draw: showPoints): many of them hide the
    // rest. One a link names is shown all the same (reveal).
    var POINTS = 'item_point';

    // Touchpads send wheel events too: a pinch with ctrlKey, a two-finger swipe without. Leaflet zooms with all of
    // them, collecting the steps and animating each zoom, so a pinch lags behind the fingers and a swipe zooms
    // instead of moving the map. Here a pinch scales the map at once around the pointer, in fine steps (zoomSnap 0),
    // as Leaflet's own pinch on touch screens does: layers follow, background tiles are not loaded meanwhile (no
    // flicker); when the fingers rest (PINCH_END_MS), the zoom ends once (tiles, labels, the address). A swipe pans;
    // a mouse wheel keeps Leaflet's zooming.
    var PINCH_ZOOM_PER_PIXEL = 0.012;
    var PINCH_END_MS = 150;
    var SAFARI_WHEEL_STEP = 4.000244140625;  // Safari's mouse wheel moves by multiples of this
    var GESTURE_GAP_MS = 150;  // events closer than this belong to one gesture, which keeps its kind
    var lastWheel = {time: 0, pan: false};

    function isTouchpadSwipe(event) {
        var now = Date.now();
        if (now - lastWheel.time < GESTURE_GAP_MS) {
            lastWheel.time = now;
            return lastWheel.pan;
        }
        var mouseStep = event.deltaMode !== 0 ||
            (event.deltaY !== 0 && Math.abs(event.deltaY) % SAFARI_WHEEL_STEP === 0);
        var pan = !mouseStep && (event.deltaX !== 0 || !Number.isInteger(event.deltaY) ||
            // Chrome and Safari: a touchpad's legacy wheelDelta is three times its delta, a mouse wheel's is 120
            (typeof event.wheelDeltaY === 'number' && Math.abs(event.wheelDeltaY) === Math.abs(event.deltaY) * 3));
        lastWheel = {time: now, pan: pan};
        return pan;
    }

    function pinch(handler, event) {
        var map = handler._map;
        if (!handler._pinching) {
            map._stop();
            map._moveStart(true, false);
            handler._pinching = true;
        }
        var zoom = Math.min(Math.max(map.getZoom() - event.deltaY * PINCH_ZOOM_PER_PIXEL, map.getMinZoom()),
            map.getMaxZoom());
        // The point under the pointer stays where it is (as map.setZoomAround).
        var half = map.getSize().divideBy(2), at = map.mouseEventToContainerPoint(event);
        var offset = at.subtract(half).multiplyBy(1 - 1 / map.getZoomScale(zoom));
        map._move(map.containerPointToLatLng(half.add(offset)), zoom, {pinch: true, round: false});
        clearTimeout(handler._pinchEnd);
        handler._pinchEnd = setTimeout(function () {
            handler._pinching = false;
            map._moveEnd(true);
        }, PINCH_END_MS);
    }

    var wheelScroll = L.Map.ScrollWheelZoom.prototype._onWheelScroll;
    L.Map.ScrollWheelZoom.include({
        _onWheelScroll: function (event) {
            var map = this._map;
            if (event.ctrlKey && event.deltaMode === 0) {
                pinch(this, event);
                lastWheel = {time: Date.now(), pan: false};
            } else if (!event.ctrlKey && isTouchpadSwipe(event)) {
                map.panBy([event.deltaX, event.deltaY], {animate: false});
            } else {
                return wheelScroll.call(this, event);
            }
            L.DomEvent.stop(event);
        }
    });

    var CONFIG_ELEMENT = document.getElementById('map-config');
    var CONFIG = CONFIG_ELEMENT ? JSON.parse(CONFIG_ELEMENT.textContent) : {layers: [], start: [49.6, 11.0, 17]};
    var BASE_KEY = 'zam-map-background';

    function storedBase() {
        try {
            return window.localStorage.getItem(BASE_KEY);
        } catch (error) {
            return null;
        }
    }

    // A map with the background layers (admin: Background layers; aerial photos, OpenStreetMap), the one
    // chosen last in this browser shown; map.baseLayers {name: layer} for the layer switch.
    function create(element, options) {
        var map = L.map(element, Object.assign({
            zoomSnap: 0, zoomDelta: 0.5, maxZoom: 25, minZoom: 12, wheelDebounceTime: 20,
            // A pinch zooms in many small steps (above): tiles that fade in at each new zoom level flicker.
            fadeAnimation: false,
            attributionControl: CONFIG.layers.length > 0,
            center: CONFIG.start.slice(0, 2), zoom: CONFIG.start[2]
        }, options || {}));
        map.baseLayers = {};
        if (!CONFIG.layers.length) {
            return map;
        }
        CONFIG.layers.forEach(function (layer) {
            map.baseLayers[layer.name] = L.tileLayer(layer.url, {
                attribution: layer.attribution, maxNativeZoom: layer.max_zoom || 19, maxZoom: 25,
                updateWhenZooming: false  // the tiles of another zoom level once the zooming pauses
            });
        });
        map.baseLayers[CONFIG.none] = L.layerGroup();
        var chosen = storedBase();
        var first = map.baseLayers[chosen] ? chosen :
            (CONFIG.layers.filter(function (layer) { return layer.default; })[0] || CONFIG.layers[0]).name;
        map.baseLayers[first].addTo(map);
        map.on('baselayerchange', function (event) {
            try {
                window.localStorage.setItem(BASE_KEY, event.name);
            } catch (error) {
                // Not remembered (private window); the default comes back next time.
            }
        });
        return map;
    }

    // The switch for background layers and, if given, overlays.
    function layerControl(map, overlays) {
        if (Object.keys(map.baseLayers).length || overlays) {
            return L.control.layers(map.baseLayers, overlays || {}, {collapsed: true}).addTo(map);
        }
        return null;
    }

    function category(feature) {
        var c = feature.properties.category;
        return STYLES[c] ? c : 'container';
    }

    // The label (maps/views.py _label): purpose or name, the code chip in the line below; null for none.
    // A unique item's name and its own one in a line, or in two when that would be long.
    var LABEL_LINE = 24;

    function label(feature) {
        var given = feature.properties.label;
        if (!given || !(given.title || given.code)) {
            return null;
        }
        var box = document.createElement('span');
        var lines = !given.subtitle ? [given.title] : (given.title + ' ' + given.subtitle).length > LABEL_LINE ?
            [given.title, given.subtitle] : [given.title + ' ' + given.subtitle];
        lines.filter(Boolean).forEach(function (text) {
            var title = L.DomUtil.create('span', 'map-label-title', box);
            title.textContent = text;
            Object.assign(title.style, given.style || {});  // the type's label size, colour, weight
        });
        if (given.code) {
            L.DomUtil.create('span', 'loc-code map-label-code', box).textContent = given.code;
        }
        return box;
    }

    function isStackPart(feature) {
        var stack = feature.properties.stack;
        return Boolean(stack && stack[1] === feature.properties.pk);
    }

    // As locations are shown everywhere: purpose or name (a link to its page), the code chip in the line below; above
    // them the overview photo, if there is one (the popup is laid out again once it has loaded).
    function popup(feature, layer) {
        var p = feature.properties;
        var box = document.createElement('div');
        box.className = 'map-popup';
        if (p.photo) {
            var photo = L.DomUtil.create('img', 'map-popup-photo', box);
            photo.alt = '';
            photo.addEventListener('load', function () {
                var open = layer.getPopup();
                if (open && open.isOpen()) {
                    open.update();
                }
            });
            photo.src = p.photo;
        }
        var link = L.DomUtil.create('a', 'map-popup-title', box);
        link.href = p.url;
        link.textContent = p.title;
        // A unique item's own code is its ZAMid (its `code` is its location's).
        var code = p.category === 'item' ? p.lid : p.code;
        if (code) {
            L.DomUtil.create('span', 'loc-code', box).textContent = code;
        }
        return box;
    }

    // A plan: its tiles (maps/views.py plan_tiles), each placed by the corners of its part of the plan, in a pane of
    // its own that has the plan's opacity (maps.css .map-plan-pane), so their overlaps do not show.
    function planLayer(map, plan) {
        var paneName = 'map-plan-' + plan.id;
        var pane = map.getPane(paneName) || map.createPane(paneName);
        pane.classList.add('map-plan-pane');
        pane.style.opacity = plan.opacity;
        var tl = L.latLng(plan.corners[0]), tr = L.latLng(plan.corners[1]), bl = L.latLng(plan.corners[2]);
        function at(x, y) {  // a pixel of the plan, on the map (its placement is affine)
            var fx = x / plan.width, fy = y / plan.height;
            return [tl.lat + (tr.lat - tl.lat) * fx + (bl.lat - tl.lat) * fy,
                tl.lng + (tr.lng - tl.lng) * fx + (bl.lng - tl.lng) * fy];
        }
        var group = L.featureGroup(plan.tiles.map(function (tile) {
            return L.planOverlay(tile.url, [at(tile.x, tile.y), at(tile.x + tile.w, tile.y), at(tile.x, tile.y + tile.h)],
                [tile.w, tile.h], {interactive: false, className: 'map-plan', pane: paneName});
        }));
        group.planLocation = plan.location;
        group.planName = plan.name;
        group._corners = [tl, tr, bl];
        group.options.opacity = plan.opacity;
        group.setOpacity = function (opacity) {  // hidden as a whole (stacked parts)
            pane.style.opacity = opacity;
            return group;
        };
        return group;
    }

    // Draws a level's data; returns {plans, layers: {category: L.LayerGroup}, byId, stacks, bounds}. The unique items
    // that are points only with `showPoints` (their layer, POINTS).
    function draw(map, data, options) {
        options = options || {};
        unselect(map);  // of the level drawn before
        selectOnPopups(map);
        // Each plan is a layer of its own: shown at first, or switched on in the layer selection.
        var result = {plans: [], layers: {}, byId: {}, stacks: data.stacks || [], bounds: null, revealed: {}};
        var bounds = L.latLngBounds([]);
        (data.plans || []).forEach(function (plan) {
            var overlay = planLayer(map, plan);
            result.plans.push(overlay);
            if (plan.shown) {
                overlay.addTo(map);
            }
            bounds.extend(overlay.getBounds());
        });
        Object.keys(STYLES).concat([POINTS]).forEach(function (name) { result.layers[name] = L.layerGroup(); });
        (data.features.features || []).forEach(function (feature) {
            if (options.skip && options.skip(feature)) {
                return;
            }
            var name = category(feature);
            var group = name === 'item' && feature.properties.kind === 'point' ? POINTS : name;
            // The type's look (admin: map settings) over the usual one of its category.
            var style = Object.assign({className: 'map-feature'}, group === POINTS ? ITEM_POINT : STYLES[name],
                feature.properties.style || {});
            // A white halo under an area's outline: visible on aerial photos, plans and other areas. Made first, as a
            // group draws its layers in the order they were made.
            var casing = feature.properties.kind !== 'area' ? null : L.geoJSON(feature, {interactive: false,
                style: function () {
                    return {color: '#ffffff', opacity: 0.85, weight: (style.weight === undefined ? 2 : style.weight) + 3,
                        fill: false, lineCap: 'round', lineJoin: 'round', className: 'map-casing'};
                }});
            var layer = L.geoJSON(feature, {
                style: function () { return style; },
                pointToLayer: function (_feature, latlng) {  // the type's style may give the radius
                    return L.circleMarker(latlng, Object.assign({radius: name === 'item' ? 5 : 7}, style));
                },
                interactive: options.interactive !== false
            });
            layer.feature = feature;
            layer._drawn = result;
            layer._baseStyle = style;
            layer.eachLayer(function (part) { part._zamLayer = layer; });  // a popup's source is the part
            if (casing) {
                layer.casing = casing;
                result.layers[group].addLayer(casing);
            }
            if (options.interactive !== false) {
                // Made once: laying it out again (the photo's load) asks for the content anew, and a new photo
                // would load and ask again.
                var content = null;
                layer.bindPopup(function () { return content || (content = popup(feature, layer)); });
                layer.off('click', layer._openPopup, layer);  // above it, if it fits (openPopupAbove)
                layer.on('click', function (event) {
                    L.DomEvent.stop(event);
                    openPopupAbove(layer, event.latlng);
                });
            }
            var text = label(feature);
            if (text) {  // a tooltip once it is shown (filterStacks)
                layer._label = {text: text, options: {permanent: true, direction: 'center',
                    className: 'map-label map-label-' + name}};
            }
            result.layers[group].addLayer(layer);
            layer._group = group;
            result.byId[feature.properties.id] = layer;
            layer._extent = layer.getBounds ? layer.getBounds() : L.latLngBounds([layer.getLatLng()]);
            bounds.extend(layer._extent);
        });
        result.stacked = {};
        result.stacks.forEach(function (stack) { result.stacked[stack.group] = true; });
        Object.keys(result.layers).forEach(function (name) {
            if (name !== POINTS || options.showPoints) {
                result.layers[name].addTo(map);
            }
        });
        result.map = map;
        filterStacks(result, {});
        var relabel = function () { filterStacks(result, result.choice || {}); };
        map.on('moveend overlayadd overlayremove', relabel);  // moveend: also after zooming
        result.off = function () { map.off('moveend overlayadd overlayremove', relabel); };  // when drawn anew
        result.bounds = bounds.isValid() ? bounds : null;
        return result;
    }

    // Shows only one part of each stacked area (choice: {group pk: part pk or null for all}).
    function filterStacks(drawn, choice) {
        drawn.choice = choice;
        var zoom = drawn.map.getZoom(), view = drawn.map.getBounds().pad(0.25);
        Object.keys(drawn.byId).forEach(function (id) {
            var layer = drawn.byId[id];
            var stack = layer.feature.properties.stack;
            var hidden = stack && choice[stack[0]] && choice[stack[0]] !== stack[1];
            (layer.casing ? [layer, layer.casing] : [layer]).forEach(function (group) {
                group.eachLayer(function (part) {
                    var shape = part.getElement && part.getElement();
                    if (shape) {
                        shape.style.display = hidden ? 'none' : '';
                    }
                });
            });
            layer.eachLayer(function (part) {
                var tooltip = part.getTooltip && part.getTooltip();
                if (tooltip && tooltip.getElement()) {
                    tooltip.getElement().style.display = hidden ? 'none' : '';
                }
            });
            // The label is a tooltip only while it is shown and near the view: Leaflet measures every tooltip
            // whenever it places one, which took minutes with thousands of shelves (hidden ones counted, too).
            if (layer._label) {
                // Of the area and its parts, one label: the area's, or the chosen part's.
                var shown = !hidden && (isStackPart(layer.feature) ? Boolean(choice[stack[0]])
                    : !(drawn.stacked[layer.feature.properties.pk] && choice[layer.feature.properties.pk]));
                // From the zoom its type gives (admin: map settings, "label from zoom") on.
                var label = layer.feature.properties.label;
                shown = shown && !(label && label.min_zoom !== null && label.min_zoom !== undefined &&
                    zoom < label.min_zoom) && view.intersects(layer._extent);
                var tooltip = layer.getTooltip();
                if (shown && !tooltip) {
                    layer.bindTooltip(layer._label.text, layer._label.options);  // opens it (permanent)
                } else if (!shown && tooltip) {
                    layer.unbindTooltip();
                }
                tooltip = layer.getTooltip();
                if (tooltip && tooltip.getElement()) {
                    tooltip.getElement().style.display = '';
                    tooltip.getElement().dataset.ruledOut = '0';
                }
            }
        });
        layoutLabels(drawn);
        drawn.plans.forEach(function (plan) {
            var hidden = drawn.stacks.some(function (stack) {
                return choice[stack.group] && stack.parts.some(function (part) {
                    return part.pk === plan.planLocation && part.pk !== choice[stack.group];
                });
            });
            plan.setOpacity(hidden ? 0 : plan.options.opacity);
        });
    }

    // Labels without overlaps, parents before their parts (by depth in the location tree; the smaller first among
    // the same depth): the labels of storage units (and other non-areas) go in their middle; an area's label goes where
    // it was, if that still works, else to the free place nearest its middle that lies wholly inside its outline (a
    // grid fixed to the area). A label that fits nowhere stays in the middle if that is free, else it is hidden
    // (zoomed in, it comes back).
    var LABEL_GAP = 3;  // pixels between labels
    var LABEL_GRID = 12;  // places tried in an area: a grid of this many steps across and down

    function inside(point, ring) {
        var result = false;
        for (var i = 0, j = ring.length - 1; i < ring.length; j = i, i += 1) {
            if ((ring[i].y > point.y) !== (ring[j].y > point.y) &&
                    point.x < (ring[j].x - ring[i].x) * (point.y - ring[i].y) / (ring[j].y - ring[i].y) + ring[i].x) {
                result = !result;
            }
        }
        return result;
    }

    function layoutLabels(drawn) {
        var map = drawn.map, placed = [], items = [];
        Object.keys(drawn.byId).forEach(function (id) {
            var layer = drawn.byId[id], tooltip = layer.getTooltip && layer.getTooltip();
            var element = tooltip && tooltip.getElement();
            if (!element || element.dataset.ruledOut === '1' || !map.hasLayer(layer)) {
                return;
            }
            element.style.display = '';
            var latlngs = layer.feature.properties.kind === 'area' ? outerLatLngs(layer) : null;
            var ring = latlngs && latlngs.map(function (latlng) { return map.latLngToContainerPoint(latlng); });
            items.push({layer: layer, tooltip: tooltip, element: element, latlngs: latlngs, ring: ring,
                middle: layer.getBounds().getCenter(), size: L.point(element.offsetWidth, element.offsetHeight),
                depth: layer.feature.properties.depth || 0,
                order: latlngs ? areaSize(latlngs.map(function (latlng) {
                    return L.point(latlng.lng * Math.cos(latlng.lat * Math.PI / 180), latlng.lat);
                })) : 0});
        });
        // The same order at every zoom: unique items first (close up, their names count most; the areas' labels move
        // aside), then parents before their parts (they push them out), then the smaller first.
        function rank(item) {
            return item.layer.feature.properties.category === 'item' ? 0 : 1;
        }
        items.sort(function (a, b) {
            return rank(a) - rank(b) || a.depth - b.depth || a.order - b.order ||
                (a.layer._leaflet_id - b.layer._leaflet_id);
        });

        function box(latlng, size) {
            var center = map.latLngToContainerPoint(latlng);
            return L.bounds(center.subtract(size.divideBy(2)), center.add(size.divideBy(2)));
        }
        function free(bounds) {
            var grown = L.bounds(bounds.min.subtract([LABEL_GAP, LABEL_GAP]), bounds.max.add([LABEL_GAP, LABEL_GAP]));
            return placed.every(function (other) { return !grown.intersects(other); });
        }
        function fits(bounds, ring) {
            var corners = [bounds.min, L.point(bounds.max.x, bounds.min.y), bounds.max, L.point(bounds.min.x, bounds.max.y)];
            return corners.every(function (corner) { return inside(corner, ring); }) &&
                ring.every(function (vertex) { return !bounds.contains(vertex); });  // no corner of the area cuts it
        }
        items.forEach(function (item) {
            var spot = null, previous = item.layer._labelSpot;
            if (!item.ring) {
                spot = free(box(item.middle, item.size)) ? item.middle : null;
            } else {
                // Where it was, if that still works (labels do not jump when zooming); else the free place nearest
                // the middle, of a grid fixed to the area (the same at every zoom).
                var frame = L.latLngBounds(item.latlngs), candidates = [];
                for (var row = 0; row <= LABEL_GRID; row += 1) {
                    for (var column = 0; column <= LABEL_GRID; column += 1) {
                        candidates.push(L.latLng(
                            frame.getSouth() + (frame.getNorth() - frame.getSouth()) * row / LABEL_GRID,
                            frame.getWest() + (frame.getEast() - frame.getWest()) * column / LABEL_GRID));
                    }
                }
                candidates.sort(function (a, b) { return a.distanceTo(item.middle) - b.distanceTo(item.middle); });
                candidates.unshift(item.middle);
                // the areas inside it (its parts, rooms in a hall): their labels come later and need room
                var inner = items.filter(function (other) {
                    return other !== item && other.ring && other.order < item.order &&
                        frame.contains(L.latLngBounds(other.latlngs));
                }).map(function (other) { return L.bounds(other.ring); });
                var usable = function (latlng, offInner) {
                    var bounds = box(latlng, item.size);
                    return fits(bounds, item.ring) && free(bounds) &&
                        (!offInner || inner.every(function (other) { return !bounds.intersects(other); }));
                };
                if (previous && usable(previous, false)) {
                    spot = previous;
                } else {
                    // better off the smaller areas inside it (rooms in a hall), if there is room for that
                    spot = candidates.filter(function (latlng) { return usable(latlng, true); })[0] ||
                        candidates.filter(function (latlng) { return usable(latlng, false); })[0] ||
                        (free(box(item.middle, item.size)) ? item.middle : null);
                }
            }
            if (spot) {
                placed.push(box(spot, item.size));
                item.layer._labelSpot = spot;
                item.tooltip.setLatLng(spot);
                item.element.style.display = '';
            } else {
                item.element.style.display = 'none';
            }
        });
    }

    function outerLatLngs(layer) {
        var ring = null;
        layer.eachLayer(function (part) {
            var latlngs = part.getLatLngs ? part.getLatLngs() : null;
            while (latlngs && latlngs.length && !(latlngs[0] instanceof L.LatLng)) {
                latlngs = latlngs[0];
            }
            if (latlngs && latlngs.length > 2 && !ring) {
                ring = latlngs;
            }
        });
        return ring;
    }

    function areaSize(ring) {
        var sum = 0;
        for (var i = 0, j = ring.length - 1; i < ring.length; j = i, i += 1) {
            sum += (ring[j].x + ring[i].x) * (ring[j].y - ring[i].y);
        }
        return Math.abs(sum / 2);
    }

    // A control with one button group per stacked area: "HBB: all / .1 / .2".
    function stackControl(drawn, allLabel) {
        if (!drawn.stacks.length) {
            return null;
        }
        var choice = {};
        var control = L.control({position: 'topright'});
        control.onAdd = function () {
            var box = L.DomUtil.create('div', 'map-stacks leaflet-bar');
            L.DomEvent.disableClickPropagation(box);
            drawn.stacks.forEach(function (stack) {
                var row = L.DomUtil.create('div', 'map-stack', box);
                row.setAttribute('role', 'group');
                row.setAttribute('aria-label', stack.code);
                L.DomUtil.create('span', 'map-stack-code', row).textContent = stack.code;
                [{pk: null, short: allLabel}].concat(stack.parts).forEach(function (part) {
                    var button = L.DomUtil.create('button', 'btn btn-sm btn-outline-secondary', row);
                    button.type = 'button';
                    button.textContent = part.short;
                    button.setAttribute('aria-pressed', part.pk === null ? 'true' : 'false');
                    button.addEventListener('click', function () {
                        choice[stack.group] = part.pk;
                        row.querySelectorAll('button').forEach(function (other) {
                            other.setAttribute('aria-pressed', other === button ? 'true' : 'false');
                        });
                        filterStacks(drawn, choice);
                    });
                });
            });
            return box;
        };
        return control;
    }

    // Shows a unique item that is a point while their layer is off: it goes to the layer of unique items.
    function reveal(drawn, id) {
        var layer = drawn.byId[id];
        if (!layer || layer._group !== POINTS || drawn.map.hasLayer(drawn.layers[POINTS])) {
            return layer || null;
        }
        drawn.layers[POINTS].removeLayer(layer);
        drawn.layers.item.addLayer(layer);
        drawn.layers.item.addTo(drawn.map);
        layer._group = 'item';
        drawn.revealed[id] = true;
        return layer;
    }

    function highlight(drawn, id) {
        var layer = reveal(drawn, id);
        if (!layer) {
            return null;
        }
        select(layer, true);
        return layer;
    }

    // Over the rest, but not over what lies in it (its parts, storage units, unique items: deeper in the tree): they
    // stay to be clicked, in the order they were drawn. `under`: a layer that goes right below it (the halo).
    function raise(drawn, layer, under) {
        if (!layer.bringToFront) {
            return;
        }
        if (under) {
            under.bringToFront();
        }
        layer.bringToFront();
        var depth = layer.feature.properties.depth || 0;
        Object.keys(drawn.byId).forEach(function (id) {
            var other = drawn.byId[id];
            if (other !== layer && other.bringToFront && (other.feature.properties.depth || 0) > depth &&
                    other._extent.intersects(layer._extent)) {
                if (other.casing) {
                    other.casing.bringToFront();
                }
                other.bringToFront();
            }
        });
    }

    // What a popup is opened for, or a link names (highlight: `kept` when its popup closes), is selected (HALO_PIXELS),
    // one at a time on each map (map._zamSelection: {layer, halo, kept}). Closing the popup of one clicked, selecting
    // another, the edit mode (unselect) or drawing the level anew lets it go.
    function select(layer, kept) {
        var map = layer._map, drawn = layer._drawn, base = layer._baseStyle || {};
        if (!map || !drawn) {
            return;
        }
        var current = map._zamSelection;
        if (current && current.layer === layer) {
            current.kept = current.kept || Boolean(kept);
            return;
        }
        unselect(map);
        var weight = base.weight === undefined ? 2 : base.weight;
        var halo = L.geoJSON(layer.feature, {interactive: false,
            style: function () {
                return {color: '#ffffff', opacity: 0.9, weight: weight + 2 * HALO_PIXELS, fill: false,
                    lineCap: 'round', lineJoin: 'round', className: 'map-selected-halo'};
            },
            pointToLayer: function (_feature, latlng) {
                return L.circleMarker(latlng, {radius: (base.radius || 7), interactive: false});
            }
        }).addTo(map);
        layer.setStyle({weight: weight * 2, opacity: 1});
        raise(drawn, layer, halo);
        map._zamSelection = {layer: layer, halo: halo, kept: Boolean(kept), clips: clipOutside(layer, halo)};
    }

    // The halo only outside the outline, so it covers nothing inside it: each of its paths is clipped to what lies
    // outside the matching path of the layer (a large square minus it, even-odd). Leaflet draws the paths anew when the
    // map moves or zooms; the clips follow their `d`. Returns what to release (unselect).
    var SVG = 'http://www.w3.org/2000/svg', OUTSIDE = 'M-1e6 -1e6H1e6V1e6H-1e6Z', clipIds = 0;

    function clipOutside(layer, halo) {
        var parts = layer.getLayers();
        return halo.getLayers().map(function (ring, index) {
            var path = ring._path, own = parts[index] && parts[index]._path, svg = path && path.ownerSVGElement;
            if (!svg || !own) {
                return null;
            }
            var defs = svg.querySelector('defs') ||
                svg.insertBefore(document.createElementNS(SVG, 'defs'), svg.firstChild);
            var clip = document.createElementNS(SVG, 'clipPath'), shape = document.createElementNS(SVG, 'path');
            clip.id = 'map-halo-clip-' + (clipIds += 1);
            clip.setAttribute('clipPathUnits', 'userSpaceOnUse');
            shape.setAttribute('clip-rule', 'evenodd');
            clip.appendChild(shape);
            defs.appendChild(clip);
            var follow = function () { shape.setAttribute('d', OUTSIDE + (own.getAttribute('d') || '')); };
            follow();
            var observer = new MutationObserver(follow);
            observer.observe(own, {attributes: true, attributeFilter: ['d']});
            path.setAttribute('clip-path', 'url(#' + clip.id + ')');
            return {observer: observer, clip: clip};
        }).filter(Boolean);
    }

    function unselect(map) {
        var selection = map._zamSelection;
        if (!selection) {
            return;
        }
        map.removeLayer(selection.halo);
        selection.clips.forEach(function (clip) {
            clip.observer.disconnect();
            clip.clip.remove();
        });
        selection.layer.resetStyle();
        map._zamSelection = null;
    }

    // The layer of a drawn feature a popup is about (Leaflet gives the part of it), else null (a marker's, a
    // measurement's).
    function popupSource(event) {
        var source = event.popup._source;
        return source ? source._zamLayer || (source._drawn ? source : null) : null;
    }

    function selectOnPopups(map) {
        if (map._zamSelects) {
            return;
        }
        map._zamSelects = true;
        map.on('popupopen', function (event) {
            var layer = popupSource(event);
            if (layer) {
                select(layer);
            }
        });
        map.on('popupclose', function (event) {
            var layer = popupSource(event);
            if (layer && map._zamSelection && map._zamSelection.layer === layer && !map._zamSelection.kept) {
                unselect(map);
            }
        });
    }

    // A popup (clicked, or opened for a link's ?p=, in the location window, after editing, for a marked area) goes
    // right above what it is about, so as not to hide it, when it fits there wholly in view without moving the map;
    // else where it would open anyway: where clicked (`at`), else over its middle, the map moving to show it. A point's
    // goes above its circle.
    var POPUP_OFFSET = 7;  // Leaflet's: the tip ends this far below the point the popup is opened at

    // The highest point of a layer's outline (on the screen, in pixels of the map) between two x: where a popup over
    // that stretch can come down to (an area's top corner may lie aside, a turned rectangle's too).
    function topWithin(map, layer, left, right) {
        var best = Infinity;
        (layer.eachLayer ? layer.getLayers() : [layer]).forEach(function (part) {
            if (part.getRadius) {  // a circle: its rim
                var c = map.latLngToContainerPoint(part.getLatLng()), r = part.getRadius();
                var dx = c.x < left ? left - c.x : c.x > right ? c.x - right : 0;
                if (dx <= r) {
                    best = Math.min(best, c.y - Math.sqrt(r * r - dx * dx));
                }
                return;
            }
            if (!part.getLatLngs) {
                return;
            }
            var rings = [];
            (function collect(latlngs) {
                if (latlngs.length && latlngs[0] instanceof L.LatLng) {
                    rings.push(latlngs);
                } else {
                    latlngs.forEach(collect);
                }
            })(part.getLatLngs());
            rings.forEach(function (ring) {
                var points = ring.map(function (latlng) { return map.latLngToContainerPoint(latlng); });
                points.forEach(function (a, i) {
                    var b = points[(i + 1) % points.length];
                    var from = Math.max(left, Math.min(a.x, b.x)), to = Math.min(right, Math.max(a.x, b.x));
                    if (from > to) {
                        return;  // the edge lies beside the stretch
                    }
                    [from, to].forEach(function (x) {
                        var y = a.x === b.x ? Math.min(a.y, b.y) : a.y + (b.y - a.y) * (x - a.x) / (b.x - a.x);
                        best = Math.min(best, y);
                    });
                });
            });
        });
        return best;
    }

    function openPopupAbove(layer, at) {
        var map = layer._map, popup = layer.getPopup && layer.getPopup();
        if (!map || !popup) {
            layer.openPopup(at);
            return layer;
        }
        var bounds = layer.getBounds ? layer.getBounds() : L.latLngBounds([layer.getLatLng()]);
        var middle = map.latLngToContainerPoint(bounds.getCenter()).x;
        var autoPan = popup.options.autoPan;
        popup.options.autoPan = false;  // tried as it is
        layer.openPopup(map.containerPointToLatLng([middle, map.latLngToContainerPoint(bounds.getCenter()).y]));
        // As low as the outline under its width lets it: its tip on the highest point there.
        var width = popup.getElement() ? popup.getElement().offsetWidth : 0;
        var top = topWithin(map, layer, middle - width / 2, middle + width / 2);
        var point = L.point(middle, (isFinite(top) ? top : map.latLngToContainerPoint(
            L.latLng(bounds.getNorth(), bounds.getCenter().lng)).y) - POPUP_OFFSET);
        popup.setLatLng(map.containerPointToLatLng(point));
        popup.options.autoPan = autoPan;
        var box = popup.getElement() && popup.getElement().getBoundingClientRect();
        var frame = map.getContainer().getBoundingClientRect();
        var fits = box && point.y >= 0 && point.y <= frame.height && box.top >= frame.top && box.left >= frame.left &&
            box.right <= frame.right;
        if (!fits) {
            layer.closePopup();
            layer.openPopup(at);
        }
        return layer;
    }

    // What a link names (?p=, the "On the map" links) and what the small maps of a location or unique item show
    // (map_mini.js, map_place.js): highlighted and in view (`fit`: false to leave the view), as on the large map.
    function focus(drawn, id, fit) {
        var layer = highlight(drawn, id);
        if (layer && fit !== false) {
            drawn.map.fitBounds(layer.getBounds ? layer.getBounds() : L.latLngBounds([layer.getLatLng()]),
                {maxZoom: 22, padding: [40, 40], animate: false});
        }
        return layer;
    }

    function load(url) {
        return fetch(url, {headers: {'Accept': 'application/json'}, credentials: 'same-origin'})
            .then(function (response) {
                if (!response.ok) {
                    throw new Error(response.status);
                }
                return response.json();
            });
    }

    // Geometry in metres around a point and snapping, for placing (map_place.js) and the edit mode (map_edit.js).
    // The WGS84 ellipsoid, the earth the coordinates refer to: semi-major axis and squared eccentricity.
    var WGS84_A = 6378137, WGS84_E2 = 0.00669437999014;
    var SNAP_DEGREES = 4;  // turning snaps to edges and the plan's walls (and right angles to them) this close
    var SNAP_PIXELS = 12;  // corners snap to corners and edges this close on the screen
    var NEARBY_PIXELS = 250;  // edges this close to the middle give directions to turn to

    // Metres per degree of longitude and of latitude at `lat`, on the ellipsoid (as maps/geo.py). One figure for
    // both (111 320 m) was 0.2 % short east-west and 0.1 % long north-south in Erlangen: rows of shelves overlapped.
    function metresPerDegree(lat) {
        var p = lat * Math.PI / 180, w = Math.sqrt(1 - WGS84_E2 * Math.sin(p) * Math.sin(p));
        return [WGS84_A / w * Math.cos(p) * Math.PI / 180, WGS84_A * (1 - WGS84_E2) / (w * w * w) * Math.PI / 180];
    }

    // Metres between two points a site apart, on a plane around their middle (exact to well under a millimetre).
    function distance(a, b) {
        var m = metresPerDegree((a.lat + b.lat) / 2);
        return Math.sqrt(Math.pow((b.lng - a.lng) * m[0], 2) + Math.pow((b.lat - a.lat) * m[1], 2));
    }

    // The point `east` and `north` metres from `center`, after turning that offset clockwise.
    function offset(center, east, north, rotation) {
        var a = rotation * Math.PI / 180, cos = Math.cos(a), sin = Math.sin(a), m = metresPerDegree(center.lat);
        return L.latLng(center.lat + (-east * sin + north * cos) / m[1], center.lng + (east * cos + north * sin) / m[0]);
    }

    // The corners of a w × d metre rectangle around `center`, turned clockwise (as maps/geo.py rectangle).
    function rectangle(center, size, rotation) {
        return [[-1, 1], [1, 1], [1, -1], [-1, -1]].map(function (corner) {
            return offset(center, corner[0] * size[0] / 2, corner[1] * size[1] / 2, rotation);
        });
    }

    // The rectangle with the opposite corners `a` and `b`, its sides turned clockwise by `rotation`: {center, size}
    // (width along the turned east-west, depth across, in metres).
    function fromCorners(a, b, rotation) {
        var diagonal = alongAcross(a, b, rotation);
        return {center: L.latLng((a.lat + b.lat) / 2, (a.lng + b.lng) / 2),
            size: [Math.abs(diagonal[0]), Math.abs(diagonal[1])]};
    }

    // From `a` to `b` in the directions of a rectangle turned clockwise by `rotation`: [along, across] in metres
    // (back from offset()).
    function alongAcross(a, b, rotation) {
        var m = metresPerDegree((a.lat + b.lat) / 2), r = rotation * Math.PI / 180;
        var east = (b.lng - a.lng) * m[0], north = (b.lat - a.lat) * m[1];
        return [east * Math.cos(r) - north * Math.sin(r), east * Math.sin(r) + north * Math.cos(r)];
    }

    // The rectangle of `size` with the corner `a`, lying towards `toward` (at first: to the right and down):
    // {center, size}.
    function fromCorner(a, toward, size, rotation) {
        var way = toward ? alongAcross(a, toward, rotation) : [1, -1];
        return {center: offset(a, (way[0] < 0 ? -1 : 1) * size[0] / 2, (way[1] > 0 ? 1 : -1) * size[1] / 2, rotation),
            size: size.slice()};
    }

    // Drawing a rectangle by two opposite corners: a click on each, or pressing on one and letting go on the other
    // (the map does not pan meanwhile). While `options.active()`: the corners go through `options.snap(latlng, event)`,
    // the sides follow `options.rotation()`, the rectangle follows the pointer after the first corner; done({center,
    // size}) once both are there. With a size entered after the first corner (`options.size()`: [width, depth] in m,
    // else null) the rectangle has that size, towards the pointer: the second click or apply() (Enter in the size
    // fields) places it. started() once the first corner is there. reset() drops a first corner; clickTaken(): the
    // map's click that follows was one of the corners (other click handlers leave it alone); hasFirst(); preview()
    // draws it anew (the size changed).
    var DRAG_PIXELS = 6;  // a press that moves less is a click

    function cornerDrawing(map, options) {
        var first = null, pressed = null, preview = null, dragging = null, taken = false, pointer = null;
        function reset() {
            first = pressed = pointer = null;
            if (preview) {
                map.removeLayer(preview);
                preview = null;
            }
        }
        function size() {
            return options.size ? options.size() : null;
        }
        function drawnTo(latlng) {
            var given = size();
            return given ? fromCorner(first, latlng, given, options.rotation()) :
                fromCorners(first, latlng, options.rotation());
        }
        function show(latlng) {
            if (!latlng && !size()) {
                return;
            }
            var drawn = drawnTo(latlng);
            var corners = rectangle(drawn.center, drawn.size, options.rotation());
            if (preview) {
                preview.setLatLngs(corners);
            } else {
                preview = L.polygon(corners, Object.assign({interactive: false, dashArray: '6 4'}, options.style))
                    .addTo(map);
            }
        }
        function finish(latlng) {
            var drawn = drawnTo(latlng);
            reset();
            if (drawn.size[0] >= 0.01 && drawn.size[1] >= 0.01) {  // not on one line: at least a centimetre
                options.done(drawn);
            }
        }
        map.on('mousedown', function (event) {
            taken = false;
            if (!options.active() || event.originalEvent.button) {
                return;
            }
            dragging = map.dragging.enabled();
            map.dragging.disable();  // pressing and dragging draws (Leaflet's own drag starts after this)
            pressed = {point: event.containerPoint, first: !first};
            if (!first) {
                first = options.snap(event.latlng, event.originalEvent);
            }
        });
        map.on('mousemove', function (event) {
            if (first && options.active()) {
                pointer = options.snap(event.latlng, event.originalEvent);
                show(pointer);
            }
        });
        map.on('mouseup', function (event) {
            if (dragging) {
                map.dragging.enable();
            }
            dragging = null;
            if (!pressed || !options.active()) {
                pressed = null;
                return;
            }
            var moved = pressed.point.distanceTo(event.containerPoint) > DRAG_PIXELS, firstPress = pressed.first;
            pressed = null;
            taken = true;
            if (moved || !firstPress) {  // dragged from the first corner, or a click on the second
                finish(options.snap(event.latlng, event.originalEvent));
            } else if (options.started) {
                options.started();
            }
        });
        return {
            reset: reset, clickTaken: function () { return taken; }, hasFirst: function () { return Boolean(first); },
            preview: function () {
                if (first && options.active()) {
                    show(pointer);
                }
            },
            apply: function () {
                if (first && size() && options.active()) {
                    finish(pointer);
                }
            }
        };
    }

    // How far a plan is turned clockwise (its top edge against east-west), so rectangles follow its walls.
    function planRotation(plan) {
        var tl = plan.corners[0], tr = plan.corners[1], m = metresPerDegree(tl[0]);
        var east = (tr[1] - tl[1]) * m[0], north = (tr[0] - tl[0]) * m[1];
        return Math.round((-Math.atan2(north, east) * 180 / Math.PI + 360) % 360 * 10) / 10;
    }

    // The corners and edges of what is drawn (building parts, storage units), in screen pixels; without `skip`.
    function snapTargets(map, drawn, skip) {
        var corners = [], edges = [];
        function rings(latlngs) {
            if (!latlngs.length) {
                return;
            }
            if (latlngs[0] instanceof L.LatLng) {
                var points = latlngs.map(function (latlng) { return map.latLngToContainerPoint(latlng); });
                points.forEach(function (point, index) {
                    corners.push(point);
                    edges.push([point, points[(index + 1) % points.length]]);
                });
            } else {
                latlngs.forEach(rings);
            }
        }
        Object.keys(drawn ? drawn.byId : {}).forEach(function (id) {
            if (id === skip) {
                return;
            }
            drawn.byId[id].eachLayer(function (part) {
                if (part.getLatLngs) {
                    rings(part.getLatLngs());
                }
            });
        });
        return {corners: corners, edges: edges};
    }

    // Where `center` goes so that a corner of the shape (`corners(center)`: its points) touches a corner (first
    // choice) or an edge of the targets.
    function snapCenter(map, targets, center, corners) {
        var own = corners(center).map(function (latlng) { return map.latLngToContainerPoint(latlng); });
        var best = null;
        function consider(from, to) {
            var distance = from.distanceTo(to);
            if (distance <= SNAP_PIXELS && (!best || distance < best.distance)) {
                best = {distance: distance, shift: to.subtract(from)};
            }
        }
        own.forEach(function (point) {
            targets.corners.forEach(function (corner) { consider(point, corner); });
        });
        if (!best) {
            own.forEach(function (point) {
                targets.edges.forEach(function (edge) {
                    consider(point, L.LineUtil.closestPointOnSegment(point, edge[0], edge[1]));
                });
            });
        }
        return best ? map.containerPointToLatLng(map.latLngToContainerPoint(center).add(best.shift)) : center;
    }

    // The turn snapped parallel or at right angles to the plan's walls and to the edges near `center`.
    function snapRotation(map, targets, center, rotation, walls) {
        var middle = map.latLngToContainerPoint(center), directions = walls === null ? [] : [walls];
        targets.edges.forEach(function (edge) {
            if (L.LineUtil.pointToSegmentDistance(middle, edge[0], edge[1]) <= NEARBY_PIXELS) {
                // screen y runs downwards: the bearing of the edge, clockwise from north
                directions.push(Math.atan2(edge[1].x - edge[0].x, edge[0].y - edge[1].y) * 180 / Math.PI);
            }
        });
        var best = null;
        directions.forEach(function (direction) {
            for (var quarter = 0; quarter < 4; quarter += 1) {
                var wall = ((direction + quarter * 90) % 360 + 360) % 360;
                var gap = Math.abs(((rotation - wall + 540) % 360) - 180);
                if (gap <= SNAP_DEGREES && (!best || gap < best.gap)) {
                    best = {gap: gap, wall: wall};
                }
            }
        });
        return best ? Math.round(best.wall * 10) / 10 : rotation;
    }

    // The bearing (degrees clockwise from north) from `center` to `at`, for turning with a handle.
    function bearing(center, at) {
        var m = metresPerDegree(center.lat);
        return (Math.atan2((at.lng - center.lng) * m[0], (at.lat - center.lat) * m[1]) * 180 / Math.PI + 360) % 360;
    }

    window.ZamMap = {create: create, draw: draw, planLayer: planLayer, load: load, highlight: highlight, reveal: reveal,
        focus: focus, unselect: unselect, openPopupAbove: openPopupAbove,
        stackControl: stackControl,
        filterStacks: filterStacks, layerControl: layerControl, STYLES: STYLES, ITEM_POINT: ITEM_POINT,
        cornerDrawing: cornerDrawing,
        geometry: {metresPerDegree: metresPerDegree, distance: distance, offset: offset, rectangle: rectangle,
            fromCorners: fromCorners, planRotation: planRotation,
            snapTargets: snapTargets, snapCenter: snapCenter, snapRotation: snapRotation, bearing: bearing}};

    // The map page (maps/map.html).
    var element = document.querySelector('[data-map-page]');
    if (!element) {
        return;
    }
    var names = JSON.parse(document.getElementById('map-layer-names').textContent);
    // Down to the bottom of the window.
    function fit() {
        var top = element.getBoundingClientRect().top + window.scrollY;
        element.style.height = Math.max(window.innerHeight - top, 256) + 'px';
    }
    fit();
    var map = create(element);
    // The levels (left, below the zoom buttons) and the actions (below them) as parts of the map.
    function asControl(part, position) {
        if (!part) {
            return;
        }
        var control = L.control({position: position});
        control.onAdd = function () {
            L.DomEvent.disableClickPropagation(part);
            L.DomEvent.disableScrollPropagation(part);
            part.hidden = false;
            return part;
        };
        control.addTo(map);
    }
    asControl(document.querySelector('[data-map-levels]'), 'topleft');
    asControl(document.querySelector('[data-map-actions]'), 'topleft');
    window.addEventListener('resize', function () {
        fit();
        map.invalidateSize();
    });
    // The level, drawn anew after changes in the edit mode (map_edit.js); the view stays where it is then.
    var start = readHash();  // the view of the address (below)
    // `markQuery`: the marked point or area for the address (map_mark.js).
    var page = {map: map, drawn: null, element: element, controls: [], start: start, markQuery: null};
    ZamMap.page = page;

    // The plans drawn before go once the new ones' images are there (or after RETIRE_MS), so that the map does not
    // flash empty in between: changing the level looks like loading other tiles.
    var RETIRE_MS = 2000;
    function retire(old, fresh) {
        if (!old.length) {
            return;
        }
        var loading = [];
        fresh.forEach(function (plan) {
            if (map.hasLayer(plan)) {
                plan.eachLayer(function (tile) {
                    loading.push(new Promise(function (resolve) { tile.once('load error', resolve); }));
                });
            }
        });
        var gone = false;
        function remove() {
            if (!gone) {
                gone = true;
                old.forEach(function (plan) { map.removeLayer(plan); });
            }
        }
        Promise.all(loading).then(remove);
        setTimeout(remove, RETIRE_MS);
    }

    // The level's data drawn (anew); `level` for another level (switchLevel), whose plans start as they are set.
    function show(first, level) {
        var url = element.dataset.url;
        return load(url).then(function (data) {
            if (url !== element.dataset.url) {
                return;  // another level was chosen meanwhile
            }
            var old = [], showPoints = false, revealed = {};
            if (page.drawn) {  // what was drawn before, and its switches; plans that were switched on stay so
                // as do the unique items that are points, and those shown of them (in the edit mode: the one saved)
                showPoints = map.hasLayer(page.drawn.layers[POINTS]);
                revealed = page.drawn.revealed;
                page.drawn.off();
                var shown = {};
                page.drawn.plans.forEach(function (plan) {
                    shown[plan.planName] = map.hasLayer(plan);
                    old.push(plan);
                });
                data.plans.forEach(function (plan) {
                    if (!level && plan.name in shown) {
                        plan.shown = shown[plan.name];
                    }
                });
                Object.keys(page.drawn.layers).forEach(function (name) { map.removeLayer(page.drawn.layers[name]); });
                page.controls.forEach(function (control) { control.remove(); });
            }
            var drawn = draw(map, data, {interactive: true, showPoints: showPoints});
            page.drawn = drawn;
            if (!level) {
                Object.keys(revealed).forEach(function (id) { reveal(drawn, id); });
            }
            retire(old, drawn.plans);
            var overlays = {};
            drawn.plans.forEach(function (plan) { overlays[names.plan.replace('{name}', plan.planName)] = plan; });
            Object.keys(drawn.layers).forEach(function (name) {
                if (drawn.layers[name].getLayers().length) {  // only what the level has
                    overlays[names[name]] = drawn.layers[name];
                }
            });
            page.controls = [layerControl(map, overlays)];
            var stacks = stackControl(drawn, names.all);
            if (stacks) {
                stacks.addTo(map);
                page.controls.push(stacks);
            }
            document.dispatchEvent(new CustomEvent('zam-map-drawn', {detail: page}));
            if (!first) {
                return;
            }
            // The address's view (the marked point or #z, b: showView, below), else what #p names (the "On the map"
            // links), else the whole level.
            var view = start.bounds || start.mark || start.area;  // set below
            var named = start.popup ? focus(drawn, start.popup, !view) : null;
            if (view) {
                return;
            }
            if (!named && drawn.bounds) {
                map.fitBounds(drawn.bounds, {padding: [10, 10]});
            }
            if (!drawn.bounds && !Object.keys(map.baseLayers).length) {
                element.classList.add('map-empty');
                element.setAttribute('data-empty-text', element.dataset.empty);
            }
        });
    }

    page.reload = function () { return show(false); };

    // Another level without loading the page: its data drawn on the same map (the view, the background and the
    // measurements stay), the address, title and level buttons changed. In the edit mode, and if loading fails,
    // the link is followed as it is.
    var levelLinks = document.querySelectorAll('[data-map-level]');
    function switchLevel(link, push) {
        var url = link.href.split('#')[0];
        if (push) {
            history.pushState(null, '', url + window.location.hash);
        }
        levelLinks.forEach(function (other) {
            var current = other === link;
            other.classList.toggle('map-level-current', current);
            if (current) {
                other.setAttribute('aria-current', 'page');
            } else {
                other.removeAttribute('aria-current');
            }
        });
        document.title = link.dataset.title;
        document.dispatchEvent(new CustomEvent('zam-map-level'));  // e.g. the marking stays on its level (map_mark.js)
        var heading = document.querySelector('[data-map-heading]');
        if (heading) {
            heading.textContent = link.dataset.title;
        }
        element.dataset.url = link.dataset.dataUrl;
        var bar = document.querySelector('[data-map-edit]');
        if (bar) {
            bar.dataset.unplacedUrl = link.dataset.unplacedUrl;
        }
        map.closePopup();
        show(false, true).then(writeHash).catch(function () {
            window.location.href = link.href;
        });
    }
    levelLinks.forEach(function (link) {
        link.addEventListener('click', function (event) {
            if (event.button !== 0 || event.ctrlKey || event.metaKey || event.shiftKey || event.altKey ||
                    element.classList.contains('map-editing')) {
                return;  // followed as a link (a new tab; the edit mode keeps the level's state)
            }
            event.preventDefault();
            if (!link.classList.contains('map-level-current')) {
                switchLevel(link, true);
            }
        });
    });
    window.addEventListener('popstate', function () {  // back and forward between levels
        var path = window.location.pathname;
        var link = Array.prototype.filter.call(levelLinks, function (other) {
            return other.pathname === path;
        })[0];
        if (link && !link.classList.contains('map-level-current')) {
            switchLevel(link, false);
        }
    });

    // The address, to share it: what it shows in the query, ?p=<open popup, e.g. loc:12> or ?m=<lat>,<lng> or
    // ?a=<lat>,<lng>;<lat>,<lng>;… and &t=<its text> (the marked point or area, map_mark.js), so that a chat's link
    // preview shows it too (maps/preview.py: the server never sees the part after #); the view after #:
    // #z=<zoom>&b=<south>,<west>,<north>,<east>. Older links have p, m, a and t after # as well; with hashOnly only
    // that part counts (a link pasted into the open page's address: hashchange, below).
    function readHash(hashOnly) {
        var values = {};
        window.location.hash.replace(/^#/, '').split('&').forEach(function (part) {
            var pair = part.split('=');
            if (pair[0]) {
                values[decodeURIComponent(pair[0])] = decodeURIComponent(pair[1] || '');
            }
        });
        var query = new URLSearchParams(window.location.search);
        if (!hashOnly && (query.has('p') || query.has('m') || query.has('a'))) {
            ['p', 'm', 'a', 't'].forEach(function (key) {
                delete values[key];
                if (query.has(key)) {
                    values[key] = query.get(key);
                }
            });
        }
        var b = (values.b || '').split(',').map(Number), m = (values.m || '').split(',').map(Number);
        var a = values.a ? values.a.split(';').map(function (corner) { return corner.split(',').map(Number); }) : [];
        var areaOk = a.length >= 3 && a.every(function (c) { return c.length === 2 && c.every(isFinite); });
        return {zoom: values.z ? Number(values.z) : null, popup: values.p || null,
            bounds: b.length === 4 && b.every(isFinite) ? L.latLngBounds([b[0], b[1]], [b[2], b[3]]) : null,
            mark: m.length === 2 && m.every(isFinite) ? L.latLng(m[0], m[1]) : null,
            area: areaOk ? a.map(function (c) { return L.latLng(c[0], c[1]); }) : null, label: values.t || null};
    }
    var openPopup = null;  // the feature id of the open popup

    var hashTimer = null;
    function writeHash() {  // at most every 300 ms: browsers limit changes of the history (Firefox complains)
        clearTimeout(hashTimer);
        hashTimer = setTimeout(writeHashNow, 300);
    }

    page.writeHash = writeHash;

    function writeHashNow() {
        var bounds = map.getBounds(), digits = function (value) { return value.toFixed(6); };
        var view = 'z=' + (Math.round(map.getZoom() * 100) / 100) + '&b=' + [bounds.getSouth(), bounds.getWest(),
            bounds.getNorth(), bounds.getEast()].map(digits).join(',');
        var target = (openPopup ? ['p=' + encodeURIComponent(openPopup).replace('%3A', ':')] : [])
            .concat(page.markQuery ? page.markQuery() : []);
        // the state stays: the edit mode's steps (map_edit.js)
        history.replaceState(history.state, '', window.location.pathname + (target.length ? '?' + target.join('&') : '') +
            '#' + view);
        // The other levels keep the view.
        document.querySelectorAll('[data-map-level]').forEach(function (link) {
            link.href = link.href.split('#')[0] + '#' + view;
        });
    }

    map.on('popupopen', function (event) {
        var source = event.popup._source, feature = source && (source.feature || (source.getLayers &&
            source.getLayers()[0] && source.getLayers()[0].feature));
        openPopup = feature ? feature.properties.id : null;
        writeHash();
    });
    map.on('popupclose', function () {
        openPopup = null;
        writeHash();
    });
    // The view an address asks for: centred on the marked point (#m, map_mark.js) at #z, or the whole marked area
    // (#a) at most at #z, whatever rectangle it has (the sender's screen); else its rectangle (#b) at about #z.
    function showView(target) {
        if (target.mark) {
            map.setView(target.mark, target.zoom !== null ? target.zoom : 21, {animate: false});
        } else if (target.area) {
            map.fitBounds(L.latLngBounds(target.area), {padding: [60, 60], maxZoom: target.zoom !== null ? target.zoom : 22,
                animate: false});
        } else if (target.bounds) {
            map.fitBounds(target.bounds, {animate: false});
            if (target.zoom !== null && Math.abs(map.getZoom() - target.zoom) < 1) {
                map.setZoom(target.zoom, {animate: false});  // the same zoom on a screen of about the same size
            }
        }
        if (target.popup && page.drawn && page.drawn.byId[target.popup]) {
            openPopupAbove(reveal(page.drawn, target.popup));
        }
    }

    // A link to this level pasted into the address of the open page changes only the part after #, without loading
    // the page: its view (and marker, map_mark.js) apply then too. Not fired by writeHash (replaceState).
    window.addEventListener('hashchange', function () {
        var target = readHash(true);
        document.dispatchEvent(new CustomEvent('zam-map-address', {detail: target}));
        showView(target);
        writeHash();
    });

    show(true).then(function () {
        showView(start);
        writeHash();
        map.on('moveend', writeHash);
    }).catch(function () {
        element.classList.add('map-empty');
        element.setAttribute('data-empty-text', element.dataset.error);
    });
})();
