"""Positions on floor plans (docs/maps.md).

Positions are stored in WGS84 (EPSG:4326); sizes, rotations and plan alignment are computed in the metric
MAPS_LOCAL_SRID (geo.py). Vertically, a position belongs to the level its location is in (levels.py), so a
location or unique item never names its level itself.
"""
import re
from pathlib import Path
from uuid import uuid4

from django.conf import settings
from django.contrib.gis.db import models
from django.core.exceptions import ValidationError
from django.core.validators import MaxValueValidator, MinValueValidator, RegexValidator
from django.db import transaction
from django.utils.text import get_valid_filename
from django.utils.translation import gettext_lazy as _, pgettext_lazy


class LocationShape(models.Model):
    """Where a location is on the map: a point, a rectangle of its size, or an area (building parts)."""

    class Kind(models.TextChoices):
        POINT = "point", _("Point")
        RECTANGLE = "rectangle", _("Rectangle")
        AREA = "area", _("Area")

    location = models.OneToOneField("inventory.Location", on_delete=models.CASCADE, related_name="map_shape",
                                    verbose_name=_("location"))
    kind = models.CharField(_("kind"), max_length=10, choices=Kind.choices, default=Kind.POINT)
    # Point for a point; Polygon for a rectangle (its corners, from centre, size and rotation) or an area.
    geometry = models.GeometryField(_("position"), srid=4326, null=True, blank=True)
    rotation = models.FloatField(_("rotation"), default=0, help_text=_("Degrees clockwise; rectangles only."))
    width_cm = models.PositiveIntegerField(_("width (cm)"), null=True, blank=True,
                                           help_text=_("Empty: the default of the location type."))
    depth_cm = models.PositiveIntegerField(_("depth (cm)"), null=True, blank=True,
                                           help_text=_("Empty: the default of the location type."))
    parts_stacked = models.BooleanField(
        _("parts stacked"), default=False,
        help_text=_("The parts of this room or area lie on top of each other, counted from the bottom "
                    "(platforms such as HBB.1 and HBB.2). The map then shows one part at a time."))

    class Meta:
        verbose_name = _("location shape")
        verbose_name_plural = _("location shapes")
        permissions = [("change_building_shape", _("Can draw levels, rooms and areas on the map")),
                       ("edit_map", _("Can edit and move everything on the map (all staff can)"))]

    def __str__(self):
        return str(self.location)

    def size_cm(self):
        """(width, depth) of the location, or None if unknown."""
        size = getattr(self.location.type, "map_settings", None)
        width = self.width_cm or (size.default_width_cm if size else None)
        depth = self.depth_cm or (size.default_depth_cm if size else None)
        return (width, depth) if width and depth else None


HEX_COLOR = RegexValidator(r"^#[0-9a-fA-F]{6}$", _("A colour as #rrggbb."))


def _number(low, high):
    return lambda value: isinstance(value, (int, float)) and not isinstance(value, bool) and low <= value <= high


def _color(value):
    return isinstance(value, str) and bool(re.fullmatch(r"#[0-9a-fA-F]{6}", value))


# The Leaflet path options a location type's map settings may give (style_options), with what each one takes.
STYLE_OPTIONS = {
    "color": _color, "fillColor": _color,
    "weight": _number(0, 20), "opacity": _number(0, 1), "fillOpacity": _number(0, 1), "radius": _number(1, 30),
    "dashArray": lambda value: isinstance(value, str) and bool(re.fullmatch(r"[0-9]+([ ,]+[0-9]+)*", value)),
    "dashOffset": lambda value: isinstance(value, str) and bool(re.fullmatch(r"[0-9]+", value)),
    "lineCap": lambda value: value in ("butt", "round", "square"),
    "lineJoin": lambda value: value in ("miter", "round", "bevel"),
    "fill": lambda value: isinstance(value, bool), "stroke": lambda value: isinstance(value, bool),
}
LABEL_FIELDS = ("code", "short", "name", "purpose", "title")


class LocationTypeMap(models.Model):
    """How locations of a type are on the map: whether they are placed at all, and their usual size (a Euro pallet:
    120 × 80 cm). Types without these settings follow default_placed (permissions.py)."""
    type = models.OneToOneField("inventory.LocationType", on_delete=models.CASCADE, related_name="map_settings",
                                verbose_name=_("location type"))
    placeable = models.BooleanField(_("placeable on the map"), default=True, help_text=_(
        "Locations of this type get a position on the map. Otherwise they are shown where the location they are in "
        "is (e.g. the compartments of a shelf, boxes)."))
    # Which shapes its locations can have on the map (permissions.allowed_kinds).
    as_point = models.BooleanField(_("as point"), default=True)
    as_rectangle = models.BooleanField(_("as rectangle"), default=True, help_text=_("Of the usual size, or its own."))
    as_area = models.BooleanField(_("as area"), default=False, help_text=_("An outline drawn on the map, e.g. rooms."))
    default_width_cm = models.PositiveIntegerField(_("default width (cm)"), null=True, blank=True,
                                                   help_text=_("Of a rectangle, offered when placing one."))
    default_depth_cm = models.PositiveIntegerField(_("default depth (cm)"), null=True, blank=True)
    # How its locations look on the map; empty: as the others of their category (map.js STYLES).
    color = models.CharField(_("line colour"), max_length=7, blank=True, validators=[HEX_COLOR],
                             help_text=_("#rrggbb; empty: as usual for its category."))
    fill_color = models.CharField(_("fill colour"), max_length=7, blank=True, validators=[HEX_COLOR])
    fill_opacity = models.FloatField(_("fill opacity"), null=True, blank=True,
                                     validators=[MinValueValidator(0), MaxValueValidator(1)], help_text=_("0 to 1."))
    line_width = models.FloatField(_("line width"), null=True, blank=True,
                                   validators=[MinValueValidator(0), MaxValueValidator(20)], help_text=_("Pixels."))
    label_min_zoom = models.FloatField(_("label from zoom"), null=True, blank=True,
                                       validators=[MinValueValidator(0), MaxValueValidator(25)], help_text=_(
        "Their labels show from this zoom level on (the map's address shows the current one as z=…; 18: a room, "
        "20: a shelf fills some centimetres); empty: always."))
    style_options = models.JSONField(_("more style options"), default=dict, blank=True, help_text=_(
        "Leaflet's drawing options, e.g. {\"dashArray\": \"6 4\", \"lineJoin\": \"round\", \"fill\": false}: color, "
        "fillColor (#rrggbb), weight (0–20), opacity, fillOpacity (0–1), radius (points, 1–30), dashArray "
        "(“6 4”), dashOffset, lineCap (butt, round, square), lineJoin (miter, round, bevel), fill, stroke "
        "(true or false). The fields above come first when filled in."))
    label_size = models.PositiveSmallIntegerField(_("label size"), null=True, blank=True,
                                                  validators=[MinValueValidator(6), MaxValueValidator(32)],
                                                  help_text=_("Pixels of the label's first line; empty: as usual."))
    label_color = models.CharField(_("label colour"), max_length=7, blank=True, validators=[HEX_COLOR])
    label_bold = models.BooleanField(_("label bold"), default=False)
    label = models.CharField(pgettext_lazy("map", "label"), max_length=100, blank=True, help_text=_(
        "The first line of their label on the map, above the code chip, e.g. “{name}” or “{purpose}”: {code} "
        "the full code, {short} its own part, {name}, {purpose}, {title} (purpose, else name). Empty: purpose, "
        "else name; write “-” for no label at all."))

    class Meta:
        verbose_name = _("map settings of a location type")
        verbose_name_plural = _("map settings of location types")
        ordering = ["type__name"]

    def __str__(self):
        return str(self.type)

    def clean(self):
        if self.placeable and not self.kinds():
            raise ValidationError(_("A placeable type needs at least one shape: point, rectangle or area."))
        options = self.style_options or {}
        if not isinstance(options, dict):
            raise ValidationError({"style_options": _("The style options are a JSON object: {\"option\": value}.")})
        if unknown := sorted(set(options) - set(STYLE_OPTIONS)):
            raise ValidationError({"style_options": _("Unknown style options: %(options)s.") % {
                "options": ", ".join(unknown)}})
        if wrong := sorted(name for name, value in options.items() if not STYLE_OPTIONS[name](value)):
            raise ValidationError({"style_options": _("Not a fitting value for: %(options)s.") % {
                "options": ", ".join(wrong)}})
        try:
            self.render_label(None)
        except (KeyError, IndexError, ValueError) as error:
            raise ValidationError({"label": _("Unknown placeholder or brace in the label: %(error)s") % {
                "error": error}}) from error

    def render_label(self, location):
        """The label of a location of this type ("" for none), or None for the usual one; None as location: a check
        of the template."""
        if not self.label:
            return None
        if self.label == "-":
            return ""
        values = {name: "" for name in LABEL_FIELDS} if location is None else {
            "code": location.unique_identifier, "short": location.short_name, "name": location.name,
            "purpose": location.purpose or "", "title": location.title}
        return self.label.format(**values).strip()

    def kinds(self):
        """The shapes allowed, in the order the dialog offers them."""
        return [kind for kind, allowed in (("point", self.as_point), ("rectangle", self.as_rectangle),
                                           ("area", self.as_area)) if allowed]

    def style(self):
        """The look given here, for map.js (Leaflet path options): the style options (only the known ones), the
        fields above them."""
        style = {name: value for name, value in (self.style_options or {}).items()
                 if name in STYLE_OPTIONS and STYLE_OPTIONS[name](value)}
        fields = {"color": self.color, "fillColor": self.fill_color, "fillOpacity": self.fill_opacity,
                  "weight": self.line_width}
        style.update({key: value for key, value in fields.items() if value not in ("", None)})
        return style

    def label_style(self):
        """How the label's first line looks (map.js), only what is given."""
        style = {"fontSize": f"{self.label_size}px" if self.label_size else None, "color": self.label_color,
                 "fontWeight": "700" if self.label_bold else None}
        return {key: value for key, value in style.items() if value}


class UniqueItemPosition(models.Model):
    """Where exactly a unique item is, in addition to its location."""
    unique_item = models.OneToOneField("inventory.UniqueItem", on_delete=models.CASCADE, related_name="map_position",
                                       verbose_name=_("unique item"))
    point = models.PointField(_("position"), srid=4326)

    class Meta:
        verbose_name = _("unique item position")
        verbose_name_plural = _("unique item positions")

    def __str__(self):
        return str(self.unique_item)


def floor_plan_source_path(instance, filename):
    # A folder of its own for each upload (a replaced file never shows up under the old path), with the file's
    # original name, which a download keeps.
    return f"floorplans/{uuid4().hex}/{get_valid_filename(Path(filename).name)}"


def floor_plan_image_path(instance, filename):
    return f"floorplans/{uuid4().hex}/plan{Path(filename).suffix.lower()}"


class FloorPlan(models.Model):
    """A floor plan on a level, placed in WGS84. A level can have several (one per house, or several sheets).

    A plan that shows only a stacked part (HBB.2 above HBB.1) names that part; the map shows it when that part is
    chosen. The source (PDF, PNG or SVG) is seen by staff only: PDFs can name people in their metadata. The public
    sees the web image, rendered from it (render.py) without annotations and cropped to the drawing.
    """
    level = models.IntegerField(_("level"), help_text=_(
        "The level's number as in the codes: -1 for WH-1 and HH-1 (levels with the same number share one map)."))
    location = models.ForeignKey(
        "inventory.Location", on_delete=models.SET_NULL, null=True, blank=True, related_name="floor_plans",
        verbose_name=_("stacked part"), limit_choices_to={"type__category": "space"},
        help_text=_("Only for a plan of a stacked part (e.g. HBB.2): the map shows it when that part is chosen."))
    name = models.CharField(_("name"), max_length=200, blank=True,
                            help_text=_("Where the plan comes from, e.g. “Bauaufnahme 02.2023, EG”."))
    source = models.FileField(_("source file"), upload_to=floor_plan_source_path,
                              help_text=_("PDF, PNG or SVG. DWG: convert it first (docs/maps.md)."))
    page = models.PositiveIntegerField(_("page"), default=1)
    dpi = models.PositiveIntegerField(_("resolution (dpi)"), default=300, help_text=_(
        "For PDFs; at 1:100, 300 dpi are 8.5 mm per pixel (images wider or higher than 6000 pixels are made smaller)."))
    # Part of the page to show: an outline [[x, y], …] as fractions of its width and height (render.crop_polygon).
    crop = models.JSONField(_("crop"), null=True, blank=True, help_text=_(
        "Part of the page shown: its outline [[x, y], …] as fractions of the page's width and height; empty for the "
        "whole page. Easier: “Crop” on the plan's page."))
    transparent = models.BooleanField(_("remove background"), default=False, help_text=_(
        "Makes the white paper transparent, so that the background map shows through; lines keep their colour."))
    image = models.FileField(_("image"), upload_to=floor_plan_image_path, blank=True)
    # The plan in tiles (render.tiles; none for an SVG): [{"name", "x", "y", "w", "h"}] in pixels of the plan.
    tiles = models.JSONField(_("tiles"), default=list, blank=True, editable=False)
    image_width = models.PositiveIntegerField(null=True, blank=True)
    image_height = models.PositiveIntegerField(null=True, blank=True)
    # [{"pixel": [x, y], "lonlat": [lon, lat]}, …]: pixels of the image (0, 0 top left) and where they are.
    control_points = models.JSONField(_("control points"), default=list, blank=True)
    # The image's top left, top right and bottom left corner, computed from the control points (geo.py).
    corners = models.MultiPointField(_("corners"), srid=4326, null=True, blank=True)
    outline = models.PolygonField(_("outline"), srid=4326, null=True, blank=True)
    affine = models.BooleanField(_("uneven scaling"), default=False, help_text=_(
        "Placed with uneven scaling and shearing (three control points or more), for distorted scans."))
    residual_m = models.FloatField(_("deviation (m)"), null=True, blank=True,
                                   help_text=_("Largest distance between a control point and where the fit puts it."))
    notes = models.TextField(_("internal notes"), blank=True, help_text=_(
        "For whoever looks after the plans; not shown on the map."))
    active = models.BooleanField(_("active"), default=True, help_text=_(
        "Offered on the map of its level; inactive plans stay for reference."))
    shown = models.BooleanField(_("shown at first"), default=True, help_text=_(
        "Shown when the map opens; otherwise it is switched on in the layer selection (e.g. an older survey)."))
    opacity = models.FloatField(_("opacity"), default=0.85)
    created = models.DateTimeField(_("created"), auto_now_add=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
                                   related_name="+", verbose_name=_("created by"))

    class Meta:
        verbose_name = _("floor plan")
        verbose_name_plural = _("floor plans")
        ordering = ["level", "-active", "name"]
        # The pages for floor plans (/map/plans/): for whoever is given it, beyond the model permissions.
        permissions = [("manage_floorplans", _("Can manage floor plans (upload, crop, place, download sources)"))]

    def __str__(self):
        return self.name or _("Plan of level %(level)+d") % {"level": self.level}

    def clean(self):
        from .levels import Tree
        from .render import RenderError, crop_polygon
        try:
            self.crop = crop_polygon(self.crop)
        except RenderError as error:
            raise ValidationError({"crop": str(error)}) from error
        if self.location_id and self.level is not None and Tree().level_number(self.location_id) != self.level:
            raise ValidationError({"location": _("%(location)s is not on level %(level)+d.") % {
                "location": self.location, "level": self.level}})

    @property
    def source_name(self):
        """The uploaded file's name."""
        return Path(self.source.name).name if self.source else ""

    @property
    def is_svg(self):
        return self.source.name.lower().endswith(".svg")

    @property
    def is_placed(self):
        return self.corners is not None


TILE_PLACEHOLDERS = ("{z}", "{x}", "{y}")


class BackgroundLayer(models.Model):
    """A background map under the plans (aerial photo, street map): tiles that the viewers' browsers load from a
    tile server, the only third party the pages load from. Each browser shows the one chosen there last, else the
    default."""
    name = models.CharField(_("name"), max_length=100, unique=True)
    url = models.CharField(_("tile URL"), max_length=500, help_text=_(
        "https://… with {z}, {x} and {y} for zoom, column and row, e.g. https://osm.rrze.fau.de/osmde/{z}/{x}/{y}.png"))
    attribution = models.CharField(_("attribution"), max_length=300, blank=True, help_text=_(
        "Shown in the corner of the map, as the tiles' licence asks."))
    max_zoom = models.PositiveSmallIntegerField(_("highest zoom of the tiles"), default=19, help_text=_(
        "Closer up, the tiles of this zoom are enlarged."))
    active = models.BooleanField(_("included"), default=True, help_text=_("Offered on the maps."))
    is_default = models.BooleanField(_("default"), default=False, help_text=_(
        "Shown until a viewer chooses another one; only one layer is the default."))
    position = models.PositiveSmallIntegerField(_("order"), default=0)

    class Meta:
        verbose_name = _("background layer")
        verbose_name_plural = _("background layers")
        ordering = ["position", "name"]
        constraints = [models.UniqueConstraint(fields=["is_default"], condition=models.Q(is_default=True),
                                               name="one_default_background_layer")]

    def __str__(self):
        return self.name

    def clean(self):
        if not self.url.startswith("https://"):
            raise ValidationError({"url": _("Tiles are loaded over HTTPS: the URL starts with https://.")})
        if missing := [part for part in TILE_PLACEHOLDERS if part not in self.url]:
            raise ValidationError({"url": _("The URL needs %(parts)s.") % {"parts": ", ".join(missing)}})
        if self.is_default and not self.active:
            raise ValidationError({"is_default": _("The default layer must be included.")})

    def save(self, *args, **kwargs):
        with transaction.atomic():
            if self.is_default:  # the new default replaces the old one
                BackgroundLayer.objects.filter(is_default=True).exclude(pk=self.pk).update(is_default=False)
            super().save(*args, **kwargs)


class SurveyedPoint(models.Model):
    """A place with known coordinates (e.g. a building corner, measured on site), offered when placing a plan
    (plan_align.html): picked from a list or on the map instead of clicked on the aerial photo, which is off by a
    metre or so."""
    name = models.CharField(_("name"), max_length=100, unique=True, help_text=_(
        "What and where it is, e.g. “WH: corner Engelstraße next to the stairs”."))
    latitude = models.FloatField(_("latitude"), validators=[MinValueValidator(-90), MaxValueValidator(90)])
    longitude = models.FloatField(_("longitude"), validators=[MinValueValidator(-180), MaxValueValidator(180)])
    active = models.BooleanField(_("offered"), default=True, help_text=_("Offered when placing plans."))
    position = models.PositiveSmallIntegerField(_("order"), default=0)

    class Meta:
        verbose_name = _("surveyed point")
        verbose_name_plural = _("surveyed points")
        ordering = ["position", "name"]

    def __str__(self):
        return self.name
