"""
Link previews of the map (docs/link-previews.md): what a chat shows of a shared map link, and the picture for it.

A link names what it shows in its query (map.js: ?p=loc:12, ?m=<lat>,<lng> or ?a=<lat>,<lng>;… with &t=<text>);
the view after # never reaches the server. describe() gives the page's OpenGraph tags (inventory/link_preview.py),
render() the picture: the level's plans and positions as the map draws them, the target highlighted, 1200×630.

Only from what the map shows guests anyway: plans from their public web images (never the uploaded file, whose PDF
metadata and notes may name people), no background map (no requests to other servers).

Pictures of locations, unique items and whole levels are kept as files (map_previews/<level>/<target>-<hash>.png),
named by a hash of everything drawn: a change of a plan or a position gives a new name. Writing one removes the
older ones of the same target; once a day the files of targets gone, and those not written for 90 days, go too.
Marked points and areas (any coordinates) are drawn on each request only.
"""
import functools
import hashlib
import io
import json
import math
import re
from dataclasses import dataclass, field
from datetime import timedelta
from pathlib import Path, PurePosixPath
from urllib.parse import quote

from django.apps import apps
from django.contrib.gis.geos import Point, Polygon
from django.core.files.base import ContentFile
from django.urls import reverse
from django.utils import timezone
from django.utils.text import Truncator
from django.utils.translation import gettext as _
from PIL import Image, ImageColor, ImageDraw, ImageFont

from inventory import link_preview
from inventory.models import Location, UniqueItem

from . import geo, levels
from .models import FloorPlan, LocationShape, UniqueItemPosition

RENDER_VERSION = 1  # raise when the drawing changes: kept pictures are made anew
WIDTH, HEIGHT = 1200, 630
SCALE = 2  # drawn at twice the size, then reduced: smooth edges (ImageDraw draws without)
MAX_TEXT = 60  # as map_mark.js
MAX_CORNERS = 100
MARGIN_M = 200  # marks this far beyond the level's plans and positions still count
POINT_SPAN_M = 24  # the width shown around a point (the map shows a marked point at about zoom 21)
MIN_SPAN_M = 12
PADDING = 0.3  # around a shape or a marked area, of its size
FOLDER = "map_previews"
KEEP = timedelta(days=90)
SWEEP_EVERY = timedelta(days=1)

# As map.js: STYLES, HIGHLIGHT, the white casing under areas, the marking's colour (map_mark.js).
STYLES = {
    "space": {"color": "#1f2937", "weight": 2, "fillColor": "#9ca3af", "fillOpacity": 0.12},
    "storage_unit": {"color": "#b35c00", "weight": 1.5, "fillColor": "#fd7e14", "fillOpacity": 0.45},
    "container": {"color": "#0b5ed7", "weight": 1.5, "fillColor": "#6ea8fe", "fillOpacity": 0.45},
    "item": {"color": "#a11d2b", "weight": 2, "fillColor": "#dc3545", "fillOpacity": 0.9},
}
HIGHLIGHT = {"color": "#d63384", "weight": 4, "fillOpacity": 0.35}
MARK = "#d6336c"
LABEL = "#495057"

FEATURE_ID = re.compile(r"^(loc|item):(\d+)$")


@dataclass
class Target:
    """What a link shows: a feature of the level ("loc:12", "item:3"), a marked point or area, or the whole level."""
    feature: dict | None = None
    point: tuple | None = None  # (lat, lng)
    corners: list = field(default_factory=list)  # [(lat, lng), …]
    text: str = ""

    def query(self):
        parts = []
        if self.point:
            parts.append("m=" + ",".join(f"{value:.7f}" for value in self.point))
        elif self.corners:
            parts.append("a=" + ";".join(",".join(f"{value:.7f}" for value in corner) for corner in self.corners))
        elif self.feature:
            parts.append("p=" + self.feature["properties"]["id"])
        if self.text and (self.point or self.corners):
            parts.append("t=" + quote(self.text, safe=""))
        return "&".join(parts)

    def key(self):
        """The file name's start for a kept picture, None for marks (not kept)."""
        if self.point or self.corners:
            return None
        return self.feature["properties"]["id"].replace(":", "-") if self.feature else "level"


def _coordinates(geometry):
    """(lat, lng) of every corner of a GeoJSON geometry."""
    def walk(value):
        if value and isinstance(value[0], (int, float)):
            yield value[1], value[0]
        else:
            for part in value:
                yield from walk(part)
    return list(walk(geometry["coordinates"]))


def _plan_corners(plan):
    """The four corners (lat, lng) of a plan: top left, top right, bottom left given, bottom right follows."""
    tl, tr, bl = plan["corners"]
    return [tl, tr, bl, [tr[0] + bl[0] - tl[0], tr[1] + bl[1] - tl[1]]]


def extent(payload):
    """(south, west, north, east) of the level's plans and positions, or None."""
    points = [corner for plan in payload["plans"] for corner in _plan_corners(plan)]
    points += [c for feature in payload["features"]["features"] for c in _coordinates(feature["geometry"])]
    if not points:
        return None
    lats, lngs = [p[0] for p in points], [p[1] for p in points]
    return min(lats), min(lngs), max(lats), max(lngs)


def _within(points, bounds):
    south, west, north, east = bounds
    east_m, north_m = geo.metres_per_degree((south + north) / 2)
    dlat, dlng = MARGIN_M / north_m, MARGIN_M / east_m
    return all(south - dlat <= lat <= north + dlat and west - dlng <= lng <= east + dlng for lat, lng in points)


def _pair(text):
    values = text.split(",")
    if len(values) != 2:
        raise ValueError
    lat, lng = float(values[0]), float(values[1])
    if not (math.isfinite(lat) and math.isfinite(lng)):
        raise ValueError
    return lat, lng


def target(params, payload):
    """The target a query names, if it is on this level (else the whole level): a marking first, as in map.js."""
    text = " ".join((params.get("t") or "").split())[:MAX_TEXT]
    bounds = extent(payload)
    try:
        if params.get("m") and bounds:
            point = _pair(params["m"])
            if _within([point], bounds):
                return Target(point=point, text=text)
        elif params.get("a") and bounds:
            corners = [_pair(corner) for corner in params["a"].split(";")]
            if 3 <= len(corners) <= MAX_CORNERS and _within(corners, bounds):
                return Target(corners=corners, text=text)
    except ValueError:
        pass
    if FEATURE_ID.match(params.get("p") or ""):
        for feature in payload["features"]["features"]:
            if feature["properties"]["id"] == params["p"]:
                return Target(feature=feature)
    return Target()


def area_at_point(point, number, current=None, tree=None):
    """The deepest room or area of a level at a point (WGS84), or None; where something is now (current, a pk) wins:
    stacked parts share their footprint (HBB.1 and HBB.2)."""
    tree = tree or levels.Tree()
    candidates = [pk for pk in LocationShape.objects.filter(kind=LocationShape.Kind.AREA, geometry__contains=point)
                  .values_list("location_id", flat=True) if tree.level_number(pk) == number]
    if not candidates:
        return None
    pk = current if current in candidates else max(candidates, key=tree.depth)
    return Location.active.filter(pk=pk).first()


def image_url(number, target_):
    query = target_.query()
    return reverse("maps:preview_image", args=[number]) + (f"?{query}" if query else "")


def describe(number, target_):
    """The link preview of the map of a level showing target_ (inventory/link_preview.py)."""
    label = levels.label(number)
    title, description = None, ""
    if target_.point or target_.corners:
        if target_.point:
            lat, lng = target_.point
            title = target_.text or _("Marked point")
        else:
            polygon = Polygon([(lng, lat) for lat, lng in target_.corners + target_.corners[:1]], srid=geo.WGS84)
            lng, lat = polygon.centroid.coords
            title = target_.text or _("Marked area")
        area = area_at_point(Point(lng, lat, srid=geo.WGS84), number)
        if target_.point:
            description = (_("Marked point in %(area)s, level %(level)s") if area else
                           _("Marked point on level %(level)s")) % {"area": area and area.title_with_code, "level": label}
        else:
            values = {"area": area and area.title_with_code, "level": label,
                      "size": f"{geo.area_m2(polygon):.0f}"}
            description = (_("Marked area in %(area)s, level %(level)s, about %(size)s m²") if area else
                           _("Marked area on level %(level)s, about %(size)s m²")) % values
    elif target_.feature:
        kind, pk = FEATURE_ID.match(target_.feature["properties"]["id"]).groups()
        if kind == "loc":
            location = Location.active.get(pk=pk)
            title = location.title_with_code
            path = " › ".join(ancestor.title for ancestor in location.ancestors)
            where = path
        else:
            unique_item = UniqueItem.objects.select_related("item", "location").get(pk=pk)
            title = str(unique_item)
            where = unique_item.location.title_with_code
        description = (_("%(where)s, on the map of level %(level)s") if where else
                       _("On the map of level %(level)s")) % {"where": where, "level": label}
    query = target_.query()
    alt = title or _("Map, level %(label)s") % {"label": label}
    return link_preview.Preview(
        title, Truncator(description).chars(link_preview.DESCRIPTION_LENGTH),
        link_preview.Image(image_url(number, target_), WIDTH, HEIGHT, alt),
        reverse("maps:level", args=[number]) + (f"?{query}" if query else ""))


# Drawing.

class _Frame:
    """Pixels of the picture (at SCALE) for WGS84 coordinates: around a centre, north up, metres per pixel."""

    def __init__(self, south, west, north, east):
        self.lat, self.lng = (south + north) / 2, (west + east) / 2
        self.east_m, self.north_m = geo.metres_per_degree(self.lat)
        width_m, height_m = (east - west) * self.east_m, (north - south) * self.north_m
        self.mpp = max(width_m / WIDTH, height_m / HEIGHT, 1e-6) / SCALE

    def __call__(self, lat, lng):
        return (WIDTH * SCALE / 2 + (lng - self.lng) * self.east_m / self.mpp,
                HEIGHT * SCALE / 2 - (lat - self.lat) * self.north_m / self.mpp)

    @classmethod
    def around(cls, points, padding=PADDING, minimum=MIN_SPAN_M):
        """A frame showing the points with room around them (of their size, at least `minimum` metres wide)."""
        lats, lngs = [p[0] for p in points], [p[1] for p in points]
        south, west, north, east = min(lats), min(lngs), max(lats), max(lngs)
        east_m, north_m = geo.metres_per_degree((south + north) / 2)
        pad_lng = max((east - west) * padding, (minimum / east_m - (east - west)) / 2)
        pad_lat = max((north - south) * padding, (minimum * HEIGHT / WIDTH / north_m - (north - south)) / 2)
        return cls(south - pad_lat, west - pad_lng, north + pad_lat, east + pad_lng)


def _frame(target_, payload):
    if target_.point:
        return _Frame.around([target_.point], 0, POINT_SPAN_M)
    if target_.corners:
        return _Frame.around(target_.corners)
    if target_.feature:
        points = _coordinates(target_.feature["geometry"])
        return _Frame.around(points, minimum=MIN_SPAN_M if len(points) > 1 else POINT_SPAN_M)
    bounds = extent(payload)
    return _Frame.around([bounds[:2], bounds[2:]], 0.05, 0) if bounds else None


def _rgba(colour, opacity, fallback):
    try:
        rgb = ImageColor.getrgb(colour)[:3]
    except (ValueError, TypeError):
        rgb = ImageColor.getrgb(fallback)[:3]
    return (*rgb, round(255 * max(0.0, min(1.0, float(opacity)))))


def _style(feature):
    """The look map.js gives a feature: its category's, the type's over it (admin: map settings). Dashes are left
    out."""
    category = feature["properties"].get("category")
    category = category if category in STYLES else "container"
    return category, {**STYLES[category], **(feature["properties"].get("style") or {})}


@functools.lru_cache(maxsize=8)
def _font(size, weight=600):
    """The labels' font: the label printing's sans (with umlauts, unlike Pillow's own), else Pillow's."""
    path = Path(apps.get_app_config("label_printing").path) / "design" / "fonts" / "RobotoCondensed-wght.ttf" \
        if apps.is_installed("label_printing") else None
    if path is None or not path.exists():
        return ImageFont.load_default(size=size * SCALE)
    loaded = ImageFont.truetype(str(path), size * SCALE)
    loaded.set_variation_by_axes([weight])
    return loaded


def _hidden(feature, choice):
    """Hidden as on the map with a stacked area's part chosen (map.js filterStacks)."""
    stack = feature["properties"].get("stack")
    return bool(stack and choice.get(stack[0]) and choice[stack[0]] != stack[1])


def _draw_plans(canvas, payload, frame, choice):
    shown = {plan["id"]: plan for plan in payload["plans"] if plan["shown"] and not any(
        choice.get(stack["group"]) and plan["location"] in [part["pk"] for part in stack["parts"]]
        and plan["location"] != choice[stack["group"]] for stack in payload["stacks"])}
    for plan in FloorPlan.objects.filter(pk__in=shown):
        if plan.image.name.lower().endswith(".svg"):
            continue  # drawn in the browser only (rasterising SVG would need a library more)
        try:
            with plan.image.open("rb") as handle:
                image = Image.open(handle).convert("RGBA")
        except OSError:  # its file gone or unreadable: drawn without it
            continue
        data = shown[plan.pk]
        tl, tr, bl = (frame(*corner) for corner in data["corners"])
        # The plan's pixel (u, v) of this image (the web image, smaller than the plan) lies at
        # tl + u·(tr − tl)/w + v·(bl − tl)/h; PIL wants the inverse, from the picture's pixel to the plan's.
        w, h = image.size
        a, b = (tr[0] - tl[0]) / w, (bl[0] - tl[0]) / h
        c, d = (tr[1] - tl[1]) / w, (bl[1] - tl[1]) / h
        det = a * d - b * c
        if abs(det) < 1e-12:
            continue
        inverse = (d / det, -b / det, (b * tl[1] - d * tl[0]) / det,
                   -c / det, a / det, (c * tl[0] - a * tl[1]) / det)
        layer = image.transform(canvas.size, Image.Transform.AFFINE, inverse, resample=Image.Resampling.BILINEAR)
        alpha = layer.getchannel("A").point(lambda value: round(value * data["opacity"]))
        layer.putalpha(alpha)
        canvas.alpha_composite(layer)


def _draw_feature(draw, feature, frame, style, category, highlighted=False):
    if highlighted:
        style = {**style, **HIGHLIGHT}
    geometry = feature["geometry"]
    weight = float(style.get("weight", 3)) * SCALE
    stroke = _rgba(style.get("color", "#3388ff"), style.get("opacity", 1), STYLES[category]["color"]) \
        if style.get("stroke", True) else None
    fill = _rgba(style.get("fillColor", style.get("color", "#3388ff")), style.get("fillOpacity", 0.2),
                 STYLES[category]["fillColor"]) if style.get("fill", True) else None
    if geometry["type"] == "Point":
        x, y = frame(*_coordinates(geometry)[0])
        radius = float(style.get("radius", 5 if category == "item" else 7)) * SCALE
        draw.ellipse((x - radius, y - radius, x + radius, y + radius), fill=fill,
                     outline=stroke, width=round(weight) if stroke else 0)
        return
    # Outlines only: holes are not drawn.
    rings = [geometry["coordinates"][0]] if geometry["type"] == "Polygon" else \
        [polygon[0] for polygon in geometry["coordinates"]]
    for ring in rings:
        points = [frame(lat, lng) for lng, lat, *_rest in ring]
        if feature["properties"].get("kind") == "area" and not highlighted:
            draw.line(points + points[:1], fill=(255, 255, 255, 217), width=round(weight + 3 * SCALE), joint="curve")
        if fill:
            draw.polygon(points, fill=fill)
        if stroke:
            draw.line(points + points[:1], fill=stroke, width=max(1, round(weight)), joint="curve")


def _label(draw, text, x, y, colour, size=22, above=0):
    """Text in a white box with a coloured edge, its bottom middle `above` pixels over (x, y)."""
    font = _font(size)
    left, top, right, bottom = draw.textbbox((0, 0), text, font=font)
    pad = 8 * SCALE
    box_w, box_h = right - left + 2 * pad, bottom - top + 2 * pad
    x0 = min(max(x - box_w / 2, 4 * SCALE), WIDTH * SCALE - box_w - 4 * SCALE)
    y0 = max(y - above - box_h, 4 * SCALE)
    draw.rounded_rectangle((x0, y0, x0 + box_w, y0 + box_h), radius=6 * SCALE, fill=(255, 255, 255, 240),
                           outline=colour, width=2 * SCALE)
    draw.text((x0 + pad - left, y0 + pad - top), text, font=font, fill=(33, 37, 41, 255))


def _space_labels(draw, features, frame, choice):
    """The names of rooms and areas big enough for them, as the map shows them."""
    font = _font(15)
    for feature in features:
        if feature["properties"].get("category") != "space" or feature["geometry"]["type"] == "Point" \
                or _hidden(feature, choice):
            continue
        title = (feature["properties"].get("label") or {}).get("title")
        if not title:
            continue
        xs, ys = zip(*(frame(lat, lng) for lat, lng in _coordinates(feature["geometry"])))
        left, top, right, bottom = draw.textbbox((0, 0), title, font=font)
        if right - left > (max(xs) - min(xs)) * 0.9 or bottom - top > (max(ys) - min(ys)) * 0.5:
            continue
        x, y = (min(xs) + max(xs)) / 2, (min(ys) + max(ys)) / 2
        draw.text((x - (right - left) / 2 - left, y - (bottom - top) / 2 - top), title, font=font,
                  fill=_rgba(LABEL, 1, LABEL), stroke_width=2 * SCALE, stroke_fill=(255, 255, 255, 255))


def _pin(draw, x, y):
    """The marking's pin (map_mark.js: 32×44, its tip on the point)."""
    s = SCALE
    head = (x, y - 28 * s)
    points = [(x, y)] + [(head[0] + 15 * s * math.cos(math.radians(angle)), head[1] + 15 * s * math.sin(math.radians(angle)))
                         for angle in range(150, 391, 10)]
    draw.ellipse((x - 9 * s, y - 3 * s, x + 9 * s, y + 3 * s), fill=(0, 0, 0, 60))
    draw.polygon(points, fill=_rgba(MARK, 1, MARK), outline=(255, 255, 255, 255), width=2 * s)
    draw.ellipse((head[0] - 6 * s, head[1] - 6 * s, head[0] + 6 * s, head[1] + 6 * s), fill=(255, 255, 255, 255))


def render(payload, target_):
    """The picture as PNG bytes, or None if the level has nothing to draw."""
    frame = _frame(target_, payload)
    if frame is None:
        return None
    stack = target_.feature and target_.feature["properties"].get("stack")
    choice = {stack[0]: stack[1]} if stack else {}  # the part the target is in, else all of them (as map.js)
    canvas = Image.new("RGBA", (WIDTH * SCALE, HEIGHT * SCALE), (255, 255, 255, 255))
    _draw_plans(canvas, payload, frame, choice)
    canvas = canvas.convert("RGB")  # ImageDraw blends translucent colours only into RGB pictures
    draw = ImageDraw.Draw(canvas, "RGBA")
    view = (-WIDTH * SCALE * 0.2, -HEIGHT * SCALE * 0.2, WIDTH * SCALE * 1.2, HEIGHT * SCALE * 1.2)
    features = []
    for feature in payload["features"]["features"]:
        xs, ys = zip(*(frame(lat, lng) for lat, lng in _coordinates(feature["geometry"])))
        if max(xs) < view[0] or min(xs) > view[2] or max(ys) < view[1] or min(ys) > view[3] or _hidden(feature, choice):
            continue
        features.append(feature)
        category, style = _style(feature)
        _draw_feature(draw, feature, frame, style, category)
    # The target's name goes in its box (below), not again inside it.
    _space_labels(draw, [f for f in features if f is not target_.feature], frame, choice)
    if target_.feature:
        category, style = _style(target_.feature)
        _draw_feature(draw, target_.feature, frame, style, category, highlighted=True)
        xs, ys = zip(*(frame(lat, lng) for lat, lng in _coordinates(target_.feature["geometry"])))
        title = (target_.feature["properties"].get("label") or {}).get("title") or target_.feature["properties"]["title"]
        _label(draw, title, (min(xs) + max(xs)) / 2, min(ys), _rgba(HIGHLIGHT["color"], 1, MARK), above=10 * SCALE)
    elif target_.corners:
        points = [frame(*corner) for corner in target_.corners]
        draw.polygon(points, fill=_rgba(MARK, 0.15, MARK))
        draw.line(points + points[:1], fill=_rgba(MARK, 1, MARK), width=3 * SCALE, joint="curve")
        if target_.text:
            xs, ys = zip(*points)
            _label(draw, target_.text, (min(xs) + max(xs)) / 2, (min(ys) + max(ys)) / 2, _rgba(MARK, 1, MARK))
    elif target_.point:
        x, y = frame(*target_.point)
        _pin(draw, x, y)
        if target_.text:
            _label(draw, target_.text, x, y, _rgba(MARK, 1, MARK), above=50 * SCALE)
    picture = canvas.resize((WIDTH, HEIGHT), Image.Resampling.LANCZOS)
    out = io.BytesIO()
    picture.save(out, "PNG", optimize=True)
    return out.getvalue()


# Kept pictures.

def _storage():
    return FloorPlan._meta.get_field("image").storage


def _digest(payload, target_):
    """A hash of everything the picture is drawn from."""
    plans = [{key: plan[key] for key in ("id", "location", "shown", "opacity", "corners")} |
             {"version": [tile["url"] for tile in plan["tiles"]]} for plan in payload["plans"]]
    features = [{"geometry": feature["geometry"], **{key: feature["properties"].get(key) for key in
                                                       ("id", "category", "kind", "style", "stack", "title")},
                 "label": (feature["properties"].get("label") or {}).get("title")}
                for feature in payload["features"]["features"]]
    data = json.dumps({"v": RENDER_VERSION, "plans": plans, "features": features, "stacks": payload["stacks"],
                       "target": target_.query()}, sort_keys=True, default=str)
    return hashlib.sha256(data.encode()).hexdigest()[:20]


def picture(number, payload, target_):
    """The PNG bytes for target_ on a level: a kept one, else drawn (and kept, unless a mark); None if empty."""
    key = target_.key()
    if key is None:
        return render(payload, target_)
    storage, folder = _storage(), f"{FOLDER}/{number}"
    name = f"{folder}/{key}-{_digest(payload, target_)}.png"
    if storage.exists(name):
        with storage.open(name, "rb") as handle:
            return handle.read()
    data = render(payload, target_)
    if data is None:
        return None
    saved = storage.save(name, ContentFile(data))
    if saved != name:  # made at the same time by another request
        storage.delete(saved)
    _, files = storage.listdir(folder)
    for other in files:
        if other.startswith(f"{key}-") and f"{folder}/{other}" != name:
            storage.delete(f"{folder}/{other}")
    sweep()
    return data


def sweep(now=None):
    """Once a day: removes kept pictures of targets gone and those not written for KEEP."""
    storage, now = _storage(), now or timezone.now()
    marker = f"{FOLDER}/.swept"
    if storage.exists(marker) and now - storage.get_modified_time(marker) < SWEEP_EVERY:
        return
    folders, _ = storage.listdir(FOLDER) if storage.exists(FOLDER) else ([], [])
    names = [f"{FOLDER}/{folder}/{name}" for folder in folders for name in storage.listdir(f"{FOLDER}/{folder}")[1]]
    wanted = {"loc": set(), "item": set()}
    for name in names:
        match = re.match(r"(loc|item)-(\d+)-", PurePosixPath(name).name)
        if match:
            wanted[match[1]].add(int(match[2]))
    present = {
        "loc": set(LocationShape.objects.filter(location_id__in=wanted["loc"], geometry__isnull=False,
                                                location__is_deleted=False).values_list("location_id", flat=True)),
        "item": set(UniqueItemPosition.objects.filter(unique_item_id__in=wanted["item"],
                                                      unique_item__disposed_at__isnull=True)
                    .values_list("unique_item_id", flat=True)),
    }
    for name in names:
        match = re.match(r"(loc|item)-(\d+)-", PurePosixPath(name).name)
        gone = match and int(match[2]) not in present[match[1]]
        if gone or now - storage.get_modified_time(name) > KEEP:
            storage.delete(name)
    if storage.exists(marker):
        storage.delete(marker)
    storage.save(marker, ContentFile(b""))
