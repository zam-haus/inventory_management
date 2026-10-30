// Marking a place or an area on the map page (maps/map.html), for everyone, to send a link to it. "Mark" opens a
// menu: "Place", then a click on the map sets a pin (it can be dragged); "Area", then clicks set the corners of a
// polygon (a click on the first or last corner again finishes it, Escape gives it up). One marking at a time: a new one
// replaces it. Its popup names the area it is in (maps:area_at) and has the link to copy or share: the level with the
// marking in view (#z=<zoom> and &m=<lat>,<lng> or &a=<lat>,<lng>;…; map.js keeps it in the address too). A click on
// "Here" changes that text (&t=<text>; empty: "Here" again). The marking belongs to its level: on another one it
// is hidden (and not in the address) until its level is shown again. Not while editing (map_edit.js) or measuring
// (map_measure.js), whose clicks draw.
(function () {
    'use strict';

    var toggleButton = document.querySelector('[data-map-mark-toggle]');
    var page = window.ZamMap && ZamMap.page;
    if (!toggleButton || !page) {
        return;
    }
    var map = page.map, strings = toggleButton.dataset, label = toggleButton.querySelector('[data-mark-label]');
    var labelText = label.textContent;
    var measureButton = document.querySelector('[data-map-measure-toggle]');
    var COLOUR = '#d6336c', FINISH_PIXELS = 10;
    // The marking: {kind: 'point' or 'area', layer, level: its level's number}; its text (null: "Here").
    var marked = null, text = null;
    var armed = null, corners = [], sketch = null, asked = 0;
    // A pink pin, its tip on the point, its shadow on the ground and "Here" above it (maps.css .map-mark-pin): plain
    // to see for whoever opens the link.
    var icon = L.divIcon({className: 'map-mark-pin', iconSize: [32, 44], iconAnchor: [16, 43], popupAnchor: [0, -74],
        tooltipAnchor: [0, -46], html: '<svg width="32" height="44" viewBox="0 0 32 44" aria-hidden="true">' +
            '<path d="M16 1C7.7 1 1 7.6 1 15.8 1 27 16 43 16 43s15-16 15-27.2C31 7.6 24.3 1 16 1z"/>' +
            '<circle cx="16" cy="15.5" r="6"/></svg>'});
    var AREA_STYLE = {color: COLOUR, weight: 3, fillColor: COLOUR, fillOpacity: 0.15, className: 'map-mark-area'};

    function currentLevel() {
        var link = document.querySelector('[data-map-level].map-level-current');
        return link ? link.dataset.number : null;
    }

    function corner(latlng) {
        return latlng.lat.toFixed(7) + ',' + latlng.lng.toFixed(7);
    }

    // For the address (map.js writeHash) and the link.
    page.markHash = function () {
        if (!marked || marked.level !== currentLevel()) {
            return '';
        }
        var where = marked.kind === 'point' ? '&m=' + corner(marked.layer.getLatLng()) :
            '&a=' + marked.layer.getLatLngs()[0].map(corner).join(';');
        return where + (text ? '&t=' + encodeURIComponent(text) : '');
    };

    // "Here" or the text given instead: a button over the marking; a click makes it a field, Enter or a click
    // elsewhere keeps the text, Escape leaves it as it was. Its clicks stay away from the map (no new marking).
    var MAX_TEXT = 60;
    var hereButton = L.DomUtil.create('button', 'map-mark-here-text');
    hereButton.type = 'button';
    hereButton.title = strings.rename;
    var hereField = L.DomUtil.create('input', 'map-mark-here-field');
    hereField.type = 'text';
    hereField.maxLength = MAX_TEXT;
    hereField.setAttribute('aria-label', strings.rename);
    [hereButton, hereField].forEach(function (element) {
        L.DomEvent.disableClickPropagation(element);
        L.DomEvent.on(element, 'dblclick contextmenu', L.DomEvent.stopPropagation);
    });
    var renaming = false;

    function showText() {
        hereButton.textContent = text || strings.here;
        if (marked) {
            marked.layer.setTooltipContent(hereButton);
        }
    }

    function fitField() {
        hereField.size = Math.max(hereField.value.length, 4);
    }

    hereButton.addEventListener('click', function () {
        renaming = true;
        hereField.value = text || strings.here;
        fitField();
        marked.layer.setTooltipContent(hereField);
        hereField.focus();
        hereField.select();
    });
    function stopRenaming(keep) {
        if (!renaming) {
            return;
        }
        renaming = false;
        if (keep) {
            var given = hereField.value.trim().slice(0, MAX_TEXT);
            text = given && given !== strings.here ? given : null;
            page.writeHash();
        }
        showText();
    }
    hereField.addEventListener('input', fitField);
    L.DomEvent.on(hereField, 'keypress keyup', L.DomEvent.stopPropagation);  // "+", "-", arrows: not the map's keys
    hereField.addEventListener('keydown', function (event) {
        event.stopPropagation();
        if (event.key === 'Enter' || event.key === 'Escape') {
            event.preventDefault();
            stopRenaming(event.key === 'Enter');
        }
    });
    hereField.addEventListener('blur', function () { stopRenaming(true); });

    // The popup: made once, filled when it opens.
    var box = document.createElement('div');
    box.className = 'map-mark-popup';
    var heading = L.DomUtil.create('strong', '', box);
    var where = L.DomUtil.create('div', 'map-mark-where', box);
    var buttons = L.DomUtil.create('div', 'map-mark-buttons', box);
    var icons = document.querySelector('[data-mark-icons]');
    function button(caption, classes, action, iconName) {
        var made = L.DomUtil.create('button', 'btn btn-sm ' + classes, buttons);
        made.type = 'button';
        var shown = iconName && icons && icons.content.querySelector('[data-icon="' + iconName + '"]');
        if (shown) {
            made.innerHTML = shown.innerHTML + ' ';  // the page's own icon (map.html)
        }
        made.appendChild(document.createTextNode(caption));
        made.addEventListener('click', action);
        return made;
    }
    var status = L.DomUtil.create('div', 'map-mark-status text-muted', box);
    status.setAttribute('aria-live', 'polite');

    function title() {
        return marked && marked.kind === 'area' ? strings.titleArea : strings.title;
    }

    function link() {
        return window.location.href.split('#')[0] + '#z=' + Math.round(map.getZoom() * 100) / 100 + page.markHash();
    }

    function updatePopup() {
        if (marked && marked.layer.isPopupOpen()) {
            marked.layer.getPopup().update();
        }
    }

    // The room or area the marking is in (an area: its middle), on the level shown (a level switch keeps it).
    function lookUp() {
        var at = marked.kind === 'point' ? marked.layer.getLatLng() : marked.layer.getCenter();
        var level = document.querySelector('[data-map-level].map-level-current');
        var question = asked += 1;
        where.textContent = '';
        if (!level) {
            return;
        }
        fetch(strings.areaUrl + '?' + new URLSearchParams({level: level.dataset.number, lon: at.lng, lat: at.lat}))
            .then(function (response) { return response.ok ? response.json() : null; })
            .then(function (data) {
                if (question !== asked || !data || !data.area || !marked) {
                    return;
                }
                where.textContent = strings.in + ' ';
                var area = L.DomUtil.create('a', '', where);
                area.href = data.area.url;
                area.textContent = data.area.title;
                updatePopup();
            })
            .catch(function () {});  // without the area
    }

    function copied(message) {
        status.textContent = message;
        updatePopup();
    }

    // On phones and in the installed app (a touch screen) sharing instead of copying: the system's share sheet
    // (messengers, mail, copying too), and the popup fits beside the levels. Elsewhere copying first. Sharing only
    // where the browser offers it (HTTPS).
    var shareFirst = Boolean(navigator.share) && window.matchMedia('(pointer: coarse)').matches;
    function share() {
        navigator.share({title: text || title(), url: link()}).catch(function () {});  // cancelled
    }
    if (shareFirst) {
        button(strings.share, 'btn-primary', share, 'share');
    }
    function copy() {
        var copiedLink = link();
        // Without the clipboard (no HTTPS): copied from a hidden field, else shown to copy by hand.
        function byHand() {
            var hidden = L.DomUtil.create('textarea', 'visually-hidden', document.body);
            hidden.value = copiedLink;
            hidden.readOnly = true;
            hidden.select();
            var done = false;
            try {
                done = document.execCommand('copy');
            } catch (error) {
                // copied by hand
            }
            hidden.remove();
            if (done) {
                copied(strings.copied);
            } else {
                window.prompt(strings.copyByHand, copiedLink);
            }
        }
        if (navigator.clipboard && window.isSecureContext) {
            navigator.clipboard.writeText(copiedLink).then(function () { copied(strings.copied); }, byHand);
        } else {
            byHand();
        }
    }
    if (!shareFirst) {
        button(strings.copy, 'btn-primary', copy);
    }
    if (navigator.share && !shareFirst) {
        button(strings.share, 'btn-outline-primary', share, 'share');
    }

    function remove() {
        if (marked) {
            map.removeLayer(marked.layer);
            marked.layer.unbindTooltip().unbindPopup();
        }
        marked = null;
        text = null;
        renaming = false;
        page.writeHash();
    }
    button(strings.remove, 'btn-outline-danger', remove, 'remove');

    // The new marking (a pin or a polygon) in place of the one before; `given`: its text from an address.
    function show(kind, layer, given) {
        if (marked) {
            map.removeLayer(marked.layer);
            marked.layer.unbindTooltip().unbindPopup();
        }
        if (given !== undefined) {
            text = given || null;
        }
        marked = {kind: kind, layer: layer, level: currentLevel()};
        layer.bindTooltip(hereButton, kind === 'point' ?
            {permanent: true, direction: 'top', className: 'map-mark-here'} :
            {permanent: true, direction: 'center', className: 'map-mark-here map-mark-here-area'});
        // Beside the levels (left), at most as wide as a phone allows then.
        layer.bindPopup(box, {minWidth: 200, maxWidth: Math.min(380, window.innerWidth - 110),
            autoPanPaddingTopLeft: [56, 10]});
        layer.on('popupopen', function () {
            heading.textContent = title();
            status.textContent = '';
            lookUp();
        });
        layer.addTo(map);
        showText();
        page.writeHash();
    }

    function markPoint(latlng, given) {
        if (marked && marked.kind === 'point' && marked.level === currentLevel()) {
            marked.layer.setLatLng(latlng);
            if (given !== undefined) {
                text = given || null;
            }
            showText();
            page.writeHash();
            return;
        }
        var pin = L.marker(latlng, {icon: icon, draggable: true, title: strings.title, autoPan: true});
        pin.on('dragend', function () { page.writeHash(); });
        show('point', pin, given);
    }

    function markArea(latlngs, given) {
        show('area', L.polygon(latlngs, AREA_STYLE), given);
    }

    function openPopup() {
        if (marked.kind === 'point') {
            marked.layer.openPopup();
        } else {  // at the top of the area, over its "Here"
            var bounds = marked.layer.getBounds();
            marked.layer.openPopup(L.latLng(bounds.getNorth(), bounds.getCenter().lng));
        }
    }

    // Drawing an area: the corners so far, the line on to the pointer (dashed), the first corner larger once a click
    // on it finishes.
    function sketchArea(cursor) {
        if (sketch) {
            map.removeLayer(sketch);
        }
        sketch = L.layerGroup().addTo(map);
        var line = cursor ? corners.concat([cursor]) : corners;
        if (line.length > 1) {
            L.polyline(line, {color: COLOUR, weight: 2, dashArray: '6 4', interactive: false}).addTo(sketch);
        }
        corners.forEach(function (point, index) {
            L.circleMarker(point, {radius: index === 0 && corners.length >= 3 ? 8 : 5, color: COLOUR, weight: 2,
                fillColor: '#fff', fillOpacity: 1, interactive: false}).addTo(sketch);
        });
        label.textContent = corners.length >= 3 ? strings.armedAreaClose : strings.armedArea;
    }

    function stopSketch() {
        corners = [];
        if (sketch) {
            map.removeLayer(sketch);
            sketch = null;
        }
    }

    function near(a, b) {
        return map.latLngToContainerPoint(a).distanceTo(map.latLngToContainerPoint(b)) <= FINISH_PIXELS;
    }

    function addCorner(at) {
        var count = corners.length;
        if (count >= 3 && (near(at, corners[0]) || near(at, corners[count - 1]))) {  // also a double click's second
            var done = corners.slice();
            setArmed(null);
            markArea(done);
            openPopup();
            return;
        }
        if (count && near(at, corners[count - 1])) {
            return;  // the same corner again (a double click)
        }
        corners.push(at);
        sketchArea();
    }

    // `kind`: what the next clicks mark ('point' or 'area'), or null.
    function setArmed(kind) {
        if (kind && measureButton && measureButton.getAttribute('aria-pressed') === 'true') {
            measureButton.click();  // measuring ends
        }
        stopSketch();
        armed = kind;
        toggleButton.setAttribute('aria-pressed', String(Boolean(kind)));
        toggleButton.classList.toggle('active', Boolean(kind));
        label.textContent = kind === 'point' ? strings.armed : kind === 'area' ? strings.armedArea : labelText;
        // Clicks go to the map, through what is drawn (their popups would stop them); a double click finishes.
        page.element.classList.toggle('map-drawing', Boolean(kind));
        page.element.classList.toggle('map-marking', Boolean(kind));
        if (kind) {
            map.closePopup();
            map.doubleClickZoom.disable();
        } else {
            map.doubleClickZoom.enable();
        }
    }

    // The menu (Bootstrap's dropdown) offers what to mark; while marking, the button gives it up instead.
    toggleButton.addEventListener('show.bs.dropdown', function (event) {
        if (armed) {
            event.preventDefault();  // the menu stays closed (Bootstrap handles the click before the button does)
        }
    });
    toggleButton.addEventListener('click', function () {
        if (armed) {
            setArmed(null);
        }
    });
    document.querySelectorAll('[data-mark-kind]').forEach(function (item) {
        item.addEventListener('click', function () { setArmed(item.dataset.markKind); });
    });
    if (measureButton) {
        measureButton.addEventListener('click', function () {
            if (armed) {
                setArmed(null);
            }
        });
    }
    map.on('click', function (event) {
        if (armed === 'point') {
            setArmed(null);
            markPoint(event.latlng);
            openPopup();
        } else if (armed === 'area') {
            addCorner(event.latlng);
        }
    });
    map.on('mousemove', function (event) {
        if (armed === 'area' && corners.length) {
            sketchArea(event.latlng);
        }
    });
    // Another level: the marking hidden, or shown again on its own; an area being drawn is given up.
    document.addEventListener('zam-map-level', function () {
        if (armed) {
            setArmed(null);
        }
        if (!marked) {
            return;
        }
        var own = marked.level === currentLevel();
        if (!own && map.hasLayer(marked.layer)) {
            map.removeLayer(marked.layer);
        } else if (own && !map.hasLayer(marked.layer)) {
            marked.layer.addTo(map);
        }
    });
    map.on('popupopen', function () {
        if (armed) {
            map.closePopup();  // a click on the marking while drawing
        }
    });
    document.addEventListener('keydown', function (event) {
        if (event.key === 'Escape' && armed) {
            setArmed(null);
        }
    });
    // The edit mode ends marking; while it is on, marking waits (the marking stays).
    new MutationObserver(function () {
        var editing = page.element.classList.contains('map-editing');
        if (editing && armed) {
            setArmed(null);
        }
        toggleButton.disabled = editing;
    }).observe(page.element, {attributes: true, attributeFilter: ['class']});

    // A link to a marking: shown, its popup closed (a click opens it); map.js brings it into view. Pasted into the open
    // page's address, it replaces the marking (a link without one removes it).
    function fromAddress(target) {
        if (target.mark) {
            markPoint(target.mark, target.label);
        } else if (target.area) {
            markArea(target.area, target.label);
        } else if (marked) {
            remove();
        }
    }
    if (page.start.mark || page.start.area) {
        fromAddress(page.start);
    }
    document.addEventListener('zam-map-address', function (event) { fromAddress(event.detail); });
})();
