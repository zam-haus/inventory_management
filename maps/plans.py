"""Preparing floor plans: the web image from the source (render.py) and the placement from the control points."""
from pathlib import PurePosixPath

from django.contrib.gis.geos import Point
from django.core.files.base import ContentFile
from django.core.files.storage import default_storage
from django.db import transaction
from django.utils.translation import gettext as _

from . import geo, render
from .models import FloorPlan


# The whole page for drawing the crop on it (plan_align.html): PDFs rendered at PAGE_DPI, at most PAGE_SIDE pixels.
PAGE_DPI = 100
PAGE_SIDE = 4000


class PlanError(ValueError):
    pass


def render_image(plan):
    """Renders the web image from the source, page, resolution and crop. The control points stay where they are on
    the page (they are converted to pixels of the new image), unless the source file or page changed."""
    try:
        plan.crop = render.crop_polygon(plan.crop)
    except render.RenderError as error:
        raise PlanError(str(error)) from error
    stored = FloorPlan.objects.filter(pk=plan.pk).values("source", "page", "crop").first() if plan.pk else None
    if not plan.source._committed:  # a new upload: stored first, so that reading it does not use it up
        plan.source.save(plan.source.name, plan.source.file, save=False)
    plan.source.open("rb")
    try:
        image, width, height = render.render(plan.source.file, suffix=plan.source.name[plan.source.name.rfind("."):],
                                             page=plan.page, dpi=plan.dpi, crop=plan.crop,
                                             transparent=plan.transparent)
    except render.RenderError as error:
        raise PlanError(str(error)) from error
    finally:
        plan.source.close()
    old = [plan.image.name] + [tile["name"] for tile in plan.tiles or []] if plan.image else []
    if isinstance(image, ContentFile):  # an SVG: shown as it is
        plan.image.save(image.name, image, save=False)
        plan.tiles = []
    else:
        # A small image, and the plan itself in tiles in the same folder (a new one for each rendering).
        plan.image.save("plan.webp", render.preview(image), save=False)
        folder = PurePosixPath(plan.image.name).parent
        plan.tiles = []
        for x, y, content in render.tiles(image):
            name = default_storage.save(str(folder / content.name), content)
            plan.tiles.append({"name": name, "x": x, "y": y, "w": min(render.TILE_SIDE + render.TILE_OVERLAP, width - x),
                               "h": min(render.TILE_SIDE + render.TILE_OVERLAP, height - y)})
    width, height = round(width), round(height)
    if stored and plan.image_width and plan.control_points:
        if stored["source"] != plan.source.name or stored["page"] != plan.page:
            plan.control_points = []
        else:
            plan.control_points = moved_points(plan.control_points, (plan.image_width, plan.image_height),
                                               stored["crop"], (width, height), plan.crop)
    plan.image_width, plan.image_height = width, height
    if old:
        transaction.on_commit(lambda: [plan.image.storage.delete(name) for name in old])


def page_preview(plan):
    """The name in storage of the plan's whole page, small and without crop: rendered once per uploaded file and page,
    next to the source (and like it for staff only: the page shows what the crop leaves off, e.g. the title block)."""
    storage = plan.source.storage
    name = str(PurePosixPath(plan.source.name).parent / f"page-{plan.page}.webp")
    if storage.exists(name):
        return name
    plan.source.open("rb")
    try:
        image, _width, _height = render.render(plan.source.file, page=plan.page, dpi=PAGE_DPI,
                                               suffix=plan.source.name[plan.source.name.rfind("."):])
    except render.RenderError as error:
        raise PlanError(str(error)) from error
    finally:
        plan.source.close()
    return storage.save(name, render.preview(image, PAGE_SIDE, "page.webp"))


def moved_points(points, old_size, old_crop, new_size, new_crop):
    """Control points converted from pixels of the old image to pixels of the new one: the same places on the page
    (the image is the box around the crop's outline). Points outside the new crop are kept; they still place it."""
    (ol, ot, orr, ob), (nl, nt, nr, nb) = render.crop_bounds(old_crop), render.crop_bounds(new_crop)
    result = []
    for point in points:
        x, y = point["pixel"]
        page_x = ol + x / old_size[0] * (orr - ol)
        page_y = ot + y / old_size[1] * (ob - ot)
        result.append({**point, "pixel": [round((page_x - nl) / (nr - nl) * new_size[0], 2),
                                          round((page_y - nt) / (nb - nt) * new_size[1], 2)]})
    return result


def control_points(plan):
    """[((x, y), Point), …] of the plan's stored control points."""
    try:
        return [((float(p["pixel"][0]), float(p["pixel"][1])), Point(float(p["lonlat"][0]), float(p["lonlat"][1]),
                                                                       srid=geo.WGS84))
                for p in plan.control_points or []]
    except (KeyError, IndexError, TypeError, ValueError) as error:
        raise PlanError(_("The control points cannot be read.")) from error


def place(plan):
    """Places the plan from its control points (two or more); fewer leave it unplaced."""
    pairs = control_points(plan)
    if len(pairs) < 2:
        plan.corners = plan.outline = plan.residual_m = None
        return
    try:
        fit = geo.fit(pairs, affine=plan.affine and len(pairs) >= 3)
    except ValueError as error:
        raise PlanError(_("The control points do not place the plan: %(error)s") % {"error": error}) from error
    plan.corners, plan.outline = geo.placement(fit, plan.image_width, plan.image_height)
    plan.residual_m = fit.residual_m


@transaction.atomic
def save(plan, *, rendered=True):
    """Saves the plan with a fresh image (if `rendered`) and its placement."""
    if rendered or not plan.image:
        render_image(plan)
    place(plan)
    plan.save()
    return plan
