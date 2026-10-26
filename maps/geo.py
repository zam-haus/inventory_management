"""Geometry in metres.

Positions are stored in WGS84 (lon/lat); sizes, rotations and the alignment of plans are computed in
settings.MAPS_LOCAL_SRID, a metric system with x to the east and y to the north. Rotations are in degrees
clockwise, as on the map. Pixels of plan images count from the top left, y downwards.
"""
import json
import math
from dataclasses import dataclass

import numpy as np
from django.conf import settings
from django.contrib.gis.geos import GEOSGeometry, MultiPoint, Point, Polygon

WGS84 = 4326


def local(geometry):
    """The geometry in metres (MAPS_LOCAL_SRID)."""
    return geometry.transform(settings.MAPS_LOCAL_SRID, clone=True)


def wgs84(geometry):
    return geometry.transform(WGS84, clone=True)


def _map_coordinates(geometry, function):
    """A copy with function((x, y)) → (x, y) applied to every coordinate."""
    def walk(value):
        if value and isinstance(value[0], (int, float)):
            return list(function(value[:2]))
        return [walk(part) for part in value]

    data = json.loads(geometry.json)
    data["coordinates"] = walk(data["coordinates"])
    result = GEOSGeometry(json.dumps(data))  # GeoJSON reads as WGS84; the coordinates are still in geometry's SRID
    result.srid = geometry.srid
    return result


def _rotate(x, y, degrees):
    """(x, y) turned clockwise around the origin."""
    angle = math.radians(degrees)
    return x * math.cos(angle) + y * math.sin(angle), -x * math.sin(angle) + y * math.cos(angle)


def rectangle(center, width_m, depth_m, rotation=0.0):
    """The rectangle (WGS84 polygon) of the given size around `center`; unrotated, the width runs east-west."""
    c = local(center)
    corners = [(-width_m / 2, depth_m / 2), (width_m / 2, depth_m / 2), (width_m / 2, -depth_m / 2),
               (-width_m / 2, -depth_m / 2)]
    ring = [(c.x + x, c.y + y) for x, y in (_rotate(*corner, rotation) for corner in corners)]
    return wgs84(Polygon([*ring, ring[0]], srid=c.srid))


def anchor(geometry):
    """The point a geometry moves and turns around: the point itself, else the centre of its area."""
    if geometry.geom_type == "Point":
        return geometry.clone()
    return wgs84(local(geometry).centroid)


def moved(geometry, from_anchor, to_anchor, turn=0.0):
    """The geometry carried along when what it belongs to moves from `from_anchor` to `to_anchor` and turns by
    `turn` degrees clockwise (e.g. the boxes on a pallet)."""
    start, end = local(from_anchor), local(to_anchor)

    def carry(coordinate):
        x, y = _rotate(coordinate[0] - start.x, coordinate[1] - start.y, turn)
        return end.x + x, end.y + y

    return wgs84(_map_coordinates(local(geometry), carry))


def area_m2(geometry):
    return local(geometry).area


def distance_m(a, b):
    return local(a).distance(local(b))


@dataclass
class Fit:
    """Pixels of a plan image → metres (MAPS_LOCAL_SRID): x = a·u + b·v + c, y = d·u + e·v + f with u = pixel x,
    v = −pixel y (image rows run downwards, north upwards)."""
    matrix: np.ndarray  # 2 × 3
    residual_m: float
    scale_m_per_px: float

    def to_local(self, x, y):
        east, north = self.matrix @ np.array([x, -y, 1.0])
        return float(east), float(north)

    def to_wgs84(self, x, y):
        return wgs84(Point(*self.to_local(x, y), srid=settings.MAPS_LOCAL_SRID))


def fit(control_points, affine=False):
    """The transform that puts a plan image where its control points say: [((x, y), Point in WGS84), …].

    Similarity (shift, turn, one scale) from two or more points, which suits plans drawn to scale; affine (may
    also shear and scale unevenly) from three or more. Raises ValueError for too few or coinciding points.
    """
    needed = 3 if affine else 2
    if len(control_points) < needed:
        raise ValueError(f"at least {needed} control points are needed")
    pixels = np.array([(x, -y) for (x, y), _point in control_points], dtype=float)
    targets = np.array([local(point).coords for _pixel, point in control_points], dtype=float)
    if np.ptp(pixels, axis=0).max() == 0 or np.ptp(targets, axis=0).max() == 0:
        raise ValueError("the control points coincide")
    rows, values = [], []
    for (u, v), (east, north) in zip(pixels, targets):
        if affine:
            rows += [[u, v, 1, 0, 0, 0], [0, 0, 0, u, v, 1]]
        else:  # east = a·u − b·v + c, north = b·u + a·v + f
            rows += [[u, -v, 1, 0], [v, u, 0, 1]]
        values += [east, north]
    solution, *_ = np.linalg.lstsq(np.array(rows), np.array(values), rcond=None)
    if affine:
        matrix = solution.reshape(2, 3)
    else:
        a, b, c, f = solution
        matrix = np.array([[a, -b, c], [b, a, f]])
    predicted = (matrix @ np.column_stack([pixels, np.ones(len(pixels))]).T).T
    residual = float(np.max(np.hypot(*(predicted - targets).T)))
    scale = float(math.sqrt(abs(np.linalg.det(matrix[:, :2]))))
    return Fit(matrix=matrix, residual_m=residual, scale_m_per_px=scale)


def placement(fit_, width_px, height_px):
    """(corners, outline) of a plan image placed by `fit_`: corners top left, top right, bottom left (as the map's
    plan overlay takes them), outline the whole image."""
    top_left, top_right = fit_.to_wgs84(0, 0), fit_.to_wgs84(width_px, 0)
    bottom_left, bottom_right = fit_.to_wgs84(0, height_px), fit_.to_wgs84(width_px, height_px)
    corners = MultiPoint(top_left, top_right, bottom_left, srid=WGS84)
    outline = Polygon([top_left.coords, top_right.coords, bottom_right.coords, bottom_left.coords,
                       top_left.coords], srid=WGS84)
    return corners, outline
