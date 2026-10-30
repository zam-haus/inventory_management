"""The map (docs/maps.md): levels with their floor plans, building parts, storage units, containers and unique items.

The page loads a level's data as JSON (level_data) and draws it with Leaflet (static/maps/map.js). Positions are
saved from the placing dialog (map_place.js) as JSON; plans are uploaded and aligned on the plans pages (staff).
"""
import json
import mimetypes
from pathlib import PurePath

from django.contrib import messages
from django.contrib.auth.mixins import PermissionRequiredMixin
from django.contrib.gis.db.models.functions import AsGeoJSON
from django.contrib.gis.geos import Point
from django.core.exceptions import PermissionDenied
from django.db import transaction
from django.http import FileResponse, Http404, HttpResponseRedirect, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils.cache import patch_cache_control
from django.utils.translation import gettext as _
from django.views import View
from django.views.decorators.http import require_GET
from sorl.thumbnail import get_thumbnail

from inventory.models import Location, LocationType, UniqueItem

from . import geo, levels, plans, positions
from .render import RenderError, crop_polygon
from .forms import FloorPlanForm
from .models import FloorPlan, LocationShape, SurveyedPoint, UniqueItemPosition
from .permissions import (allowed_kinds, edit_map_denied, item_position_denied, placeable, plans_denied,
                          shape_denied)


def _lat_lng(point):
    return [round(point.y, 8), round(point.x, 8)]


def plan_image_url(plan):
    """The URL of a plan's web image; it changes with every new image (each one gets its own folder), since browsers
    keep the image for a day (plan_image)."""
    return reverse("maps:plan_image", args=[plan.pk]) + "?v=" + PurePath(plan.image.name).parent.name


def plan_page_url(plan):
    """The URL of a plan's whole page (plan_page); it changes with the uploaded file and the page."""
    return (reverse("maps:plan_page", args=[plan.pk]) + "?v=" + PurePath(plan.source.name).parent.name
            + f"-{plan.page}")


def plan_tiles(plan):
    """The pieces the map draws a plan from: its tiles (render.tiles), or the whole image (an SVG)."""
    version = "?v=" + PurePath(plan.image.name).parent.name
    if not plan.tiles:
        return [{"url": plan_image_url(plan), "x": 0, "y": 0, "w": plan.image_width, "h": plan.image_height}]
    return [{"url": reverse("maps:plan_tile", args=[plan.pk, index]) + version, "x": tile["x"], "y": tile["y"],
             "w": tile["w"], "h": tile["h"]} for index, tile in enumerate(plan.tiles)]


def _plan_json(plan):
    return {"id": plan.pk, "name": str(plan), "location": plan.location_id, "shown": plan.shown,
            "tiles": plan_tiles(plan), "opacity": plan.opacity,
            "corners": [_lat_lng(point) for point in plan.corners], "width": plan.image_width,
            "height": plan.image_height}


def _label(location, tree):
    """The label on the map, as locations are shown everywhere: purpose or name, the code chip (its unique
    identifier, e.g. ATR0.2) in the line below (map.js). The type's template (admin: map settings) replaces the first
    line; "-": no label at all."""
    settings_ = getattr(location.type, "map_settings", None)
    custom = settings_.render_label(location) if settings_ else None
    if custom == "" and settings_.label == "-":
        return {"title": "", "code": ""}
    return {"title": custom if custom is not None else location.title, "code": location.unique_identifier,
            "min_zoom": settings_.label_min_zoom if settings_ else None,
            "style": settings_.label_style() if settings_ else {}}


def location_photo_url(location):
    """The URL of a location's overview photo for its popup (location_photo), or None; it changes with every new
    photo (each one gets its own name), since browsers keep it for a day."""
    if not location.overview_photo:
        return None
    return reverse("maps:location_photo", args=[location.pk]) + "?v=" + PurePath(location.overview_photo.name).stem


def _location_feature(shape, tree):
    location = shape.location
    size = shape.size_cm()
    settings_ = getattr(location.type, "map_settings", None)
    geometry = shape.geojson if hasattr(shape, "geojson") else shape.geometry.json
    return {"type": "Feature", "geometry": json.loads(geometry), "properties": {
        "label": _label(location, tree), "style": settings_.style() if settings_ else {},
        "id": f"loc:{location.pk}", "pk": location.pk, "category": location.type.category or "",
        "structure": location.type.structure or "", "kind": shape.kind, "rotation": shape.rotation,
        "size": [size[0] / 100, size[1] / 100] if size else None,
        "code": location.unique_identifier, "short": location.short_name, "title": location.title,
        "url": location.get_absolute_url(), "photo": location_photo_url(location), "stack": tree.stack(location.pk),
        "depth": tree.depth(location.pk),
    }}


def _item_feature(position, tree):
    item = position.unique_item
    return {"type": "Feature", "geometry": json.loads(position.point.json), "properties": {
        "id": f"item:{item.pk}", "pk": item.pk, "category": "item", "kind": "point", "title": str(item),
        "code": item.location.unique_identifier, "url": item.get_absolute_url(),
        "stack": tree.stack(item.location_id), "depth": tree.depth(item.location_id) + 1,
    }}


def level_payload(number, tree=None):
    """Everything the map shows of a level: plans, positions and the stacked areas with their parts."""
    tree = tree or levels.Tree()
    # What has a position, and where in the tree it is (one query); then only what is on this level.
    placed = LocationShape.objects.filter(geometry__isnull=False, location__is_deleted=False,
                                          location__is_reserved=False)
    tree.load(placed.values("location_id"))
    items = UniqueItemPosition.objects.filter(unique_item__disposed_at__isnull=True)
    tree.load(items.values("unique_item__location_id"))
    shaped_on_level = tree.on_level(list(placed.values_list("location_id", flat=True)), number)  # loaded: no query
    plans_ = FloorPlan.objects.filter(active=True, corners__isnull=False, level=number).order_by("name", "pk")
    # GeoJSON from the database (to the millimetre), not through GEOS and OGR shape by shape.
    shapes = placed.filter(location_id__in=shaped_on_level).select_related("location__type__map_settings") \
        .annotate(geojson=AsGeoJSON("geometry", precision=8))
    items = [position for position in items.select_related("unique_item__item", "unique_item__location")
             if tree.level_number(position.unique_item.location_id) == number]
    stacks = []
    for group in sorted(set(tree.on_level(tree.stacked, number)), key=tree.code):
        parts = tree.children(group)
        stacks.append({"group": group, "code": tree.code(group),
                       "parts": [{"pk": pk, "code": tree.code(pk), "short": tree.code(pk)[len(tree.code(group)):]}
                                 for pk in parts]})
    features = [_location_feature(shape, tree) for shape in shapes] + [_item_feature(p, tree) for p in items]
    features.sort(key=lambda feature: feature["properties"]["depth"])
    return {"level": number, "label": levels.label(number), "plans": [_plan_json(plan) for plan in plans_],
            "features": {"type": "FeatureCollection", "features": features}, "stacks": stacks}


@require_GET
def level_data(request, number):
    return JsonResponse(level_payload(number))


def map_view(request, number=None):
    tree = levels.Tree()
    numbers = tree.levels()
    if number is None:
        number = 0 if 0 in numbers else next(iter(numbers), 0)
    if number not in numbers and numbers:
        raise Http404
    houses = {n: [tree.code(pk) for pk in pks] for n, pks in numbers.items()}
    return render(request, "maps/map.html", {
        # Top down, as the floors lie in the building.
        "levels": [(n, levels.label(n), houses[n]) for n in sorted(numbers, reverse=True)], "number": number,
        "label": levels.label(number), "can_manage_plans": plans_denied(request.user) is None,
        "layer_names": layer_names(),
        # The edit mode (map_edit.js): for map editors; others logged in see it disabled with the reason.
        "edit_denied": edit_map_denied(request.user),
    })


def layer_names():
    return {"plan": _("Plan: {name}"), "space": _("Building parts"), "storage_unit": _("Storage units"),
            "container": _("Containers"), "item": _("Unique items"), "all": _("all")}


class _SaveView(View):
    """Saves a position from the placing dialog; answers JSON."""
    http_method_names = ["post"]

    def answer(self, error=None, status=400, **data):
        if error:
            return JsonResponse({"ok": False, "error": str(error)}, status=status)
        return JsonResponse({"ok": True, **data})


class LocationShapeView(_SaveView):
    def post(self, request, pk):
        with transaction.atomic():
            location = get_object_or_404(Location.active.select_for_update().select_related("type"), pk=pk)
            if reason := shape_denied(request.user, location):
                return self.answer(reason, status=403)
            try:
                placement = positions.placement_from(request.POST) or {"kind": None, "geometry": None,
                                                                       "rotation": 0.0, "size": None}
                kind = placement["kind"]
                shape = positions.set_location_shape(location, kind, placement["geometry"], placement["rotation"],
                                                     size=placement["size"])
            except positions.PlacementError as error:
                return self.answer(error)
        return self.answer(description=positions.describe(shape))


class LocationShapeRowView(_SaveView):
    """A row of storage units side by side (the edit mode's "Row", map_edit.js): rows=[{pk, kind, geometry, rotation,
    width_cm, depth_cm}, …] as the placing dialog sends one. All are placed, or none."""
    MAX = 50

    def post(self, request):
        try:
            rows = json.loads(request.POST.get("rows") or "[]")
        except ValueError:
            rows = None
        if (not isinstance(rows, list) or not 0 < len(rows) <= self.MAX or not all(isinstance(r, dict) for r in rows)
                or len({str(r.get("pk")) for r in rows}) != len(rows)):
            return self.answer(_("The row could not be read."))
        with transaction.atomic():
            for row in rows:
                location = Location.active.select_for_update().select_related("type").filter(
                    pk=str(row.get("pk")) if str(row.get("pk")).isdigit() else None).first()
                if location is None:
                    transaction.set_rollback(True)
                    return self.answer(_("A location of the row does not exist (any more)."), status=404)
                if reason := shape_denied(request.user, location):
                    transaction.set_rollback(True)
                    return self.answer(reason, status=403)
                try:
                    placement = positions.placement_from({f"map_{key}": str(value) for key, value in row.items()})
                    if placement is None:
                        raise positions.PlacementError(_("The position could not be read."))
                    positions.set_location_shape(location, placement["kind"], placement["geometry"],
                                                 placement["rotation"], size=placement["size"])
                except positions.PlacementError as error:
                    transaction.set_rollback(True)
                    return self.answer(f"{location.unique_identifier}: {error}")
        return self.answer(placed=len(rows))


class ItemPositionView(_SaveView):
    def post(self, request, pk):
        with transaction.atomic():
            item = get_object_or_404(UniqueItem.active.select_for_update(of=("self",)), pk=pk)
            if reason := item_position_denied(request.user, item):
                return self.answer(reason, status=403)
            try:
                positions.set_item_position(item, request.POST.get("map_point") or None)
            except positions.PlacementError as error:
                return self.answer(error)
        return self.answer(description=positions.describe_point(positions.item_point(item)))


def type_size(kind):
    """[width, depth] in m of a location type's usual size (admin: its map settings), or None."""
    settings_ = getattr(kind, "map_settings", None)
    if settings_ is None or not (settings_.default_width_cm and settings_.default_depth_cm):
        return None
    return [settings_.default_width_cm / 100, settings_.default_depth_cm / 100]


@require_GET
def place_context(request):
    """What the placing dialog needs: the thing placed (?location= or ?item=) with its own position and size, and
    the level and area around it: its current parent, or the one it is about to be moved to (?target=)."""
    tree = levels.Tree()
    data = {}
    if request.GET.get("item", "").isdigit():
        item = get_object_or_404(UniqueItem.active.select_related("location"), pk=request.GET["item"])
        point = positions.item_point(item)
        data["own"] = {"kind": "point", "geometry": json.loads(point.json) if point else None, "rotation": 0,
                       "size": None, "kinds": ["point"]}
        around = item.location
    elif request.GET.get("location", "").isdigit():
        location = get_object_or_404(Location.active.select_related("type__map_settings"), pk=request.GET["location"])
        shape = LocationShape.objects.filter(location=location).select_related("location__type__map_settings").first()
        size = (shape or LocationShape(location=location)).size_cm()
        has_geometry = shape is not None and shape.geometry is not None
        data["own"] = {"kind": shape.kind if has_geometry else None,
                       "geometry": json.loads(shape.geometry.json) if has_geometry else None,
                       "rotation": shape.rotation if shape else 0,
                       "size": [size[0] / 100, size[1] / 100] if size else None,
                       "id": f"loc:{location.pk}", "kinds": allowed_kinds(location.type),
                       "type_size": type_size(location.type),
                       }
        around = location.parent_location or location
    else:
        raise Http404
    if request.GET.get("target", "").isdigit():
        around = get_object_or_404(Location.active, pk=request.GET["target"])
    number = tree.level_number(around.pk) if around else None
    found = levels.effective_shape(around) if around else None
    data.update({
        "level": number, "around": around.pk if around else None,
        "around_title": around.title_with_code if around else "",
        "around_id": f"loc:{found[1].pk}" if found else None,
        "data_url": reverse("maps:level_data", args=[number]) if number is not None else None,
        "at_url": reverse("maps:area_at"),
    })
    return JsonResponse(data)


@require_GET
def unplaced(request, number):
    """For the edit mode (map editors): the locations on a level that can be placed but have no position yet, to link
    a new shape to (?kind=point, rectangle or area: those whose type allows it)."""
    if edit_map_denied(request.user):
        raise PermissionDenied
    kind = request.GET.get("kind", "point")
    # Placeable is a matter of the type: only the locations of those types are looked at.
    types = [location_type.pk for location_type in LocationType.objects.select_related("map_settings")
             if placeable(Location(type=location_type)) and kind in allowed_kinds(location_type)]
    unplaced_ = Location.active.filter(type__in=types).exclude(map_shape__geometry__isnull=False)
    tree = levels.Tree()
    on_level = set(tree.on_level(unplaced_.values_list("pk", flat=True), number))
    rows = []
    for location in unplaced_.filter(pk__in=on_level).select_related(
            "type__map_settings", "parent_location__type").order_by("unique_identifier"):
        rows.append({"pk": location.pk, "code": location.unique_identifier, "title": location.title,
                     "type": location.type_id, "size": type_size(location.type)})
    return JsonResponse({"locations": rows})


@require_GET
def area_at(request):
    """The deepest room or area at a point of a level (?level=&lon=&lat=), e.g. to offer moving something there."""
    try:
        point = Point(float(request.GET["lon"]), float(request.GET["lat"]), srid=geo.WGS84)
        number = int(request.GET["level"])
    except (KeyError, ValueError):
        raise Http404
    tree = levels.Tree()
    candidates = [pk for pk in LocationShape.objects.filter(kind=LocationShape.Kind.AREA, geometry__contains=point)
                  .values_list("location_id", flat=True) if tree.level_number(pk) == number]
    if not candidates:
        return JsonResponse({"area": None})
    # Where it is now wins (stacked parts share their footprint: HBB.1 and HBB.2), else the deepest area.
    current = request.GET.get("current", "")
    pk = int(current) if current.isdigit() and int(current) in candidates else max(candidates, key=tree.depth)
    location = Location.active.get(pk=pk)
    return JsonResponse({"area": {"pk": pk, "code": location.unique_identifier, "title": location.title_with_code}})


def _serve(file, as_attachment=False, name=None):
    try:
        handle = file.open("rb")
    except FileNotFoundError:
        raise Http404
    name = PurePath(name or file.name).name
    response = FileResponse(handle, filename=name, as_attachment=as_attachment,
                            content_type=mimetypes.guess_type(name)[0] or "application/octet-stream")
    response["Content-Security-Policy"] = "sandbox"  # an uploaded SVG cannot run scripts here
    response["X-Content-Type-Options"] = "nosniff"
    return response


@require_GET
def plan_image(request, pk):
    plan = get_object_or_404(FloorPlan, pk=pk)
    if not plan.image:
        raise Http404
    response = _serve(plan.image)
    response["Cache-Control"] = "public, max-age=86400"  # a new image gets a new URL (plan_image_url)
    return response


@require_GET
def location_photo(request, pk):
    """The overview photo in a location's popup: its thumbnail, made when the popup is opened rather than for every
    location of the level (level_data); the size of the location window's, so that most exist already."""
    location = get_object_or_404(Location.active, pk=pk)
    if not location.overview_photo:
        raise Http404
    response = HttpResponseRedirect(get_thumbnail(location.overview_photo, "640x480").url)
    patch_cache_control(response, public=True, max_age=86400)  # a new photo gets a new URL (location_photo_url)
    return response


@require_GET
def plan_tile(request, pk, index):
    """One tile of a plan (render.tiles), public like the plan's image."""
    tiles = list(get_object_or_404(FloorPlan, pk=pk).tiles or [])
    if not 0 <= index < len(tiles):
        raise Http404  # e.g. a page still asking for the tiles of an older rendering
    storage = FloorPlan._meta.get_field("image").storage
    if not storage.exists(tiles[index]["name"]):
        raise Http404
    response = _serve(storage.open(tiles[index]["name"]), name=tiles[index]["name"])
    response["Cache-Control"] = "public, max-age=86400"  # a new rendering gets new URLs (plan_tiles)
    return response


@require_GET
def plan_source(request, pk):
    """The uploaded file, for staff only: PDFs can name people in their metadata and annotations."""
    if plans_denied(request.user):
        raise PermissionDenied
    plan = get_object_or_404(FloorPlan, pk=pk)
    response = _serve(plan.source, as_attachment=True)
    response["Cache-Control"] = "private, no-store"
    return response


@require_GET
def plan_page(request, pk):
    """The whole page of a plan without its crop, small, for drawing the crop on it (plan_align.html); for staff only,
    like the source."""
    if plans_denied(request.user):
        raise PermissionDenied
    plan = get_object_or_404(FloorPlan, pk=pk)
    if plan.is_svg:
        raise Http404
    try:
        name = plans.page_preview(plan)
    except plans.PlanError:
        raise Http404
    response = _serve(plan.source.storage.open(name), name=name)
    response["Cache-Control"] = "private, max-age=86400"  # another file or page gets another URL (plan_page_url)
    return response


class PlansView(PermissionRequiredMixin, View):
    """Floor plans by level; uploading one."""
    permission_required = "maps.manage_floorplans"

    def get(self, request, form=None):
        plans_ = FloorPlan.objects.select_related("location").order_by("-level", "-active", "name")
        return render(request, "maps/plans.html", {"plans": plans_, "form": form or FloorPlanForm()})

    def post(self, request):
        form = FloorPlanForm(request.POST, request.FILES)
        if not form.is_valid():
            return self.get(request, form)
        plan = form.save(commit=False)
        plan.created_by = request.user
        try:
            plans.save(plan)
        except plans.PlanError as error:
            form.add_error("source", str(error))
            return self.get(request, form)
        messages.success(request, _("Plan added. Now place it, then crop it to the drawing."))
        return redirect("maps:plan_align", pk=plan.pk)


def _plan_label(plan):
    return f"{plan} ({levels.label(plan.level)})"


class PlanAlignView(PermissionRequiredMixin, View):
    """Place a plan with control points (plan pixels ↔ coordinates, typed or picked on the map), then crop it: an
    outline on its whole page, drawn or copied from another plan."""
    permission_required = "maps.manage_floorplans"

    def get(self, request, pk):
        plan = get_object_or_404(FloorPlan.objects.select_related("location"), pk=pk)
        number = plan.level
        # Other plans' outlines and placements to start from (e.g. the sheets of one survey have their title block and
        # the building at the same places on the page): their control points converted to pixels of this plan.
        others = list(FloorPlan.objects.exclude(pk=plan.pk).order_by("-level", "name", "pk"))
        cropped = [other for other in others if other.crop]
        placed = [other for other in others if other.is_placed and other.image_width and plan.image_width]
        # Places with known coordinates, to take for the control points instead of clicking the aerial photo.
        surveyed = [{"name": point.name, "lonlat": [point.longitude, point.latitude]}
                    for point in SurveyedPoint.objects.filter(active=True)]
        return render(request, "maps/plan_align.html", {
            "plan": plan, "number": number, "surveyed_points": surveyed,
            "other_crops": [{"pk": other.pk, "label": _plan_label(other)} for other in cropped],
            "other_placements": [{"pk": other.pk, "label": _plan_label(other)} for other in placed],
            # Cropping comes second: the crop keeps the control points at their places on the page.
            "crop_denied": (_("SVG plans cannot be cropped here; crop them before uploading.") if plan.is_svg
                            else None if plan.is_placed else _("Place the plan first.")),
            "config": {
                "tiles": plan_tiles(plan), "width": plan.image_width,
                "height": plan.image_height, "controlPoints": plan.control_points,
                "crop": plan.crop, "page": None if plan.is_svg else plan_page_url(plan),
                "otherCrops": {str(other.pk): other.crop for other in cropped},
                "otherPlacements": {str(other.pk): {
                    "controlPoints": plans.moved_points(other.control_points, (other.image_width, other.image_height),
                                                        other.crop, (plan.image_width, plan.image_height), plan.crop),
                    "affine": other.affine} for other in placed},
                "surveyedPoints": surveyed,
                "data": reverse("maps:level_data", args=[number]) if number is not None else None,
                "plan": plan.pk, "planLayer": _plan_json(plan) if plan.is_placed else None,
            },
        })

    def post(self, request, pk):
        with transaction.atomic():
            plan = get_object_or_404(FloorPlan.objects.select_for_update(), pk=pk)
            action = request.POST.get("action")
            try:
                if action == "crop":
                    if "control_points" in request.POST:  # changed since placing (dragged), but not placed again
                        plan.control_points = json.loads(request.POST["control_points"] or "[]")
                        plan.affine = request.POST.get("affine") == "1"
                    plan.crop = crop_polygon(json.loads(request.POST.get("crop") or "null"))
                    plans.save(plan, rendered=True)
                    message = _("Plan cropped; its placement stays.") if plan.is_placed else _("Plan cropped.")
                elif action == "place":
                    plan.control_points = json.loads(request.POST.get("control_points") or "[]")
                    plan.affine = request.POST.get("affine") == "1"
                    plans.save(plan, rendered=False)
                    message = _("Plan placed; largest deviation %(residual).2f m.") % {
                        "residual": plan.residual_m or 0} if plan.is_placed else _("Control points saved.")
                elif action == "source":  # a new file (e.g. a revised drawing): placement and crop carry over
                    if "source" not in request.FILES:
                        raise ValueError(_("Choose the new file."))
                    page = request.POST.get("page") or str(plan.page)
                    if not page.isdigit() or int(page) < 1:
                        raise ValueError(_("The page is a number from 1."))
                    page = int(page)
                    plan.source, plan.page = request.FILES["source"], page
                    plans.save(plan, rendered=True)
                    message = _("New source file: the plan keeps its placement and crop, at the same places on the "
                                "page. Check them.") if plan.is_placed else _("New source file.")
                elif action == "settings":
                    plan.opacity = min(max(float(request.POST.get("opacity", plan.opacity)), 0.1), 1)
                    plan.active = request.POST.get("active") == "1"
                    plan.shown = request.POST.get("shown") == "1"
                    plan.notes = request.POST.get("notes", plan.notes).strip()
                    transparent = request.POST.get("transparent") == "1"
                    rendered, plan.transparent = transparent != plan.transparent, transparent
                    plans.save(plan, rendered=rendered)
                    message = _("Saved.")
                else:
                    raise Http404
            except (ValueError, plans.PlanError, RenderError) as error:
                transaction.set_rollback(True)
                messages.error(request, str(error))
                return redirect("maps:plan_align", pk=pk)
        messages.success(request, message)
        return redirect("maps:plan_align", pk=pk)
