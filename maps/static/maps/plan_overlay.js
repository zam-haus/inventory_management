// A floor plan image on the map, placed by three of its corners (top left, top right, bottom left), so it can be
// turned and scaled as its alignment says (maps/geo.py placement). Leaflet's own image overlay only knows
// north-up rectangles; this one positions the image with a CSS matrix instead.
(function () {
    'use strict';

    L.PlanOverlay = L.ImageOverlay.extend({
        initialize: function (url, corners, size, options) {
            this._corners = corners.map(function (corner) { return L.latLng(corner); });
            this._size = size;  // [width, height] of the image in pixels
            var bottomRight = L.latLng(this._corners[1].lat + this._corners[2].lat - this._corners[0].lat,
                this._corners[1].lng + this._corners[2].lng - this._corners[0].lng);
            L.ImageOverlay.prototype.initialize.call(this, url,
                L.latLngBounds(this._corners.concat([bottomRight])), options);
        },

        onAdd: function (map) {
            L.ImageOverlay.prototype.onAdd.call(this, map);
            this._image.style.transformOrigin = '0 0';
            this._image.style.width = this._size[0] + 'px';
            this._image.style.height = this._size[1] + 'px';
            this._image.draggable = false;
        },

        _place: function (project) {
            var w = this._size[0], h = this._size[1];
            var tl = project(this._corners[0]), tr = project(this._corners[1]), bl = project(this._corners[2]);
            var matrix = [(tr.x - tl.x) / w, (tr.y - tl.y) / w, (bl.x - tl.x) / h, (bl.y - tl.y) / h, tl.x, tl.y];
            this._image.style.transform = 'matrix(' + matrix.join(',') + ')';
        },

        _reset: function () {
            var map = this._map;
            this._place(function (latlng) { return map.latLngToLayerPoint(latlng); });
        },

        _animateZoom: function (event) {
            var map = this._map;
            this._place(function (latlng) { return map._latLngToNewLayerPoint(latlng, event.zoom, event.center); });
        }
    });

    L.planOverlay = function (url, corners, size, options) {
        return new L.PlanOverlay(url, corners, size, options);
    };
})();
