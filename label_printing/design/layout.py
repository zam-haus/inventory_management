"""
Laying out and drawing a label Design as a 1-bit image for one printer. Millimetres become the printer's
dots only here, so a design prints bit-exact at any resolution.

Rows lay their elements out from left to right, columns from top to bottom (the label itself is a column).
Along that direction an element is as large as given (mm, or % of the row or column), as its content needs
("auto": the default for text with a size, QR codes, images, lines, fixed spaces), or shares what is left
with the other "fill" elements (the default otherwise; where the length is open, fill means auto). Across
it fills the row or column unless given; then the row's or column's align places it. Elements with
"at x y" (mm from the top left of their row or column) are placed there instead.
"""
import functools
import math
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from django.utils.translation import gettext as _
from PIL import Image, ImageDraw, ImageOps

from .. import render
from .language import FIELD, Element, Problem

HERE = Path(__file__).resolve().parent
FONT_FILES = {
    "sans": render.SANS,  # Raleway: the ZAMid lettering
    "mono": render.MONO,  # Roboto Mono: the ZAMid's ID
    "condensed": str(HERE / "fonts" / "RobotoCondensed-wght.ttf"),
    "ocr": str(HERE / "fonts" / "OCR-B.otf"),
}
DEFAULT_TEXT_MM = 3
DEFAULT_LINE_MM = 0.25


class TooSmall(Exception):
    """Something does not fit (a QR code too small to scan); raised when printing, a problem in previews."""

    def __init__(self, problem):
        super().__init__(problem.message)
        self.problem = problem


@dataclass
class Context:
    dpi: int
    values: dict = field(default_factory=dict)
    # A label image by name: its cropped original, greyscale; None if there is none.
    images: Callable[[str], Image.Image | None] = lambda name: None
    squeeze: int = 1
    strict: bool = False
    problems: list = field(default_factory=list)

    def dots(self, mm):
        return max(0, round(mm * self.dpi / 25.4))

    def problem(self, element, message):
        problem = Problem(element.line, message)
        if self.strict:
            raise TooSmall(problem)
        if problem not in self.problems:
            self.problems.append(problem)

    def text(self, element):
        return FIELD.sub(lambda match: str(self.values.get(match.group(1), "")), element.content or "")


@functools.lru_cache(maxsize=256)
def qr_code(content, ecc):
    return render.qr(content, error=ecc.lower())


def resolve(spec, total, context):
    """Dots of a size given in mm or %, or None (fill, auto, not given)."""
    if not spec:
        return None
    if spec[0] == "mm":
        return context.dots(spec[1])
    if spec[0] == "%" and total is not None:
        return round(total * spec[1] / 100)
    return None


def margins(element, context):
    """(top, right, bottom, left) in dots: white around the element's content, inside its box."""
    return tuple(context.dots(side) for side in element.get("margin", (0, 0, 0, 0)))


def intrinsic(element, horizontal):
    """Whether the element has a size of its own along a row (horizontal) or column (else it fills): text is as
    wide as it needs at the height it gets, and as high as its size."""
    return (element.kind in ("qr", "image", "line")
            or (element.kind == "text" and ("size" in element.options or horizontal))
            or (element.kind == "space" and element.get("extent", ("fill",))[0] != "fill"))


def shrinks(element):
    """Text without a size, rows and columns: they fit whatever room is left (after images and QR codes)."""
    return element.kind in ("row", "column") or (
        element.kind == "text" and ("size" not in element.options or bool(element.get("fit"))))


# ---------------------------------------------------------------- text

def font_for(element, context):
    return FONT_FILES[element.get("font", "sans")], element.get("weight", 400)


def text_padding(element, height, context):
    if "padding" in element.options:
        return context.dots(element.get("padding"))
    return max(1, height // 8) if element.get("invert") else 0


def text_layout(element, context, width, height):
    """(font, lines, padding) for the text in a box (either side may be None: as needed)."""
    text = context.text(element)
    path, weight = font_for(element, context)
    max_lines = element.get("lines", 1)
    if "size" in element.options and not element.get("fit"):
        loaded = render.font(path, max(1, context.dots(element.get("size"))), weight)
        padding = text_padding(element, render.line_height(loaded), context)
        if width is None or max_lines == 1:
            lines = [text]
        else:
            lines = render.wrap(text, loaded, max(1, width - 2 * padding))
        if len(lines) > max_lines:
            lines = lines[:max_lines - 1] + [render.ellipsize(loaded, " ".join(lines[max_lines - 1:]),
                                                              (width or 10 ** 6) - 2 * padding)]
        if width is not None:
            lines[-1] = render.ellipsize(loaded, lines[-1], max(1, width - 2 * padding)) if len(lines) == 1 else lines[-1]
        return loaded, lines, padding
    if height is None:  # as large as fits the width in one line (a turned name along a tape's height)
        height = context.dots(element.get("size", DEFAULT_TEXT_MM)) if width is None else width
    padding = text_padding(element, height, context)
    inner_height = max(1, height - 2 * padding)
    max_size = context.dots(element.get("size")) if "size" in element.options else None
    if width is None:
        loaded = render.fit_height(text, inner_height if max_size is None else min(inner_height, max_size), path, weight)
        return loaded, [text], padding
    loaded, lines = render.fit(text, max(1, width - 2 * padding), inner_height, path, weight, max_lines, max_size)
    return loaded, lines, padding


def text_natural(element, context, width, height):
    rotated = element.get("rotate", 0) in (90, 270)
    if rotated:
        width, height = height, width
    loaded, lines, padding = text_layout(element, context, width, height)
    natural_width = max((round(render.text_width(loaded, line)) for line in lines), default=0) + 2 * padding
    natural_height = len(lines) * render.line_height(loaded) + 2 * padding
    if height is not None:
        natural_height = min(natural_height, height)
    if width is not None:
        natural_width = min(natural_width, width)
    return (natural_height, natural_width) if rotated else (natural_width, natural_height)


def draw_text(element, context, image, x, y, width, height):
    rotation = element.get("rotate", 0)
    box_width, box_height = (height, width) if rotation in (90, 270) else (width, height)
    canvas = render.blank(box_width, box_height)
    loaded, lines, padding = text_layout(element, context, box_width, box_height)
    invert = bool(element.get("invert"))
    if invert:
        ImageDraw.Draw(canvas).rectangle((0, 0, box_width - 1, box_height - 1), fill=0)
    render.draw_lines(canvas, (padding, padding, box_width - 2 * padding, box_height - 2 * padding), loaded, lines,
                      element.get("align", "center" if invert else "left"), element.get("valign", "middle"),
                      fill=1 if invert else 0)
    if rotation:
        canvas = canvas.rotate(-rotation, expand=True)
    image.paste(canvas, (x, y))


# ---------------------------------------------------------------- QR codes, images, shapes

def qr_limit(element, context, width, height):
    limits = [side for side in (width, height) if side is not None]
    size = element.get("size")
    if size and size != ("fill",):
        limits.append(context.dots(size))
    if "max" in element.options:
        limits.append(context.dots(element.get("max")))
    return min(limits) if limits else context.dots(20)


def qr_image(element, context, width, height):
    code = qr_code(context.text(element), element.get("ecc", "L"))
    return render.qr_image(code, qr_limit(element, context, width, height), border=element.get("quiet", 2),
                           step=context.squeeze), code


def qr_natural(element, context, width, height):
    image, _code = qr_image(element, context, width, height)
    return (image.width, image.height) if image else (0, 0)


def place(outer, inner, align, default="center"):
    """Offset of something inner long in outer, by alignment."""
    align = align or default
    if align in ("left", "top"):
        return 0
    if align in ("right", "bottom"):
        return max(0, outer - inner)
    return max(0, (outer - inner) // 2)


def draw_qr(element, context, image, x, y, width, height):
    picture, code = qr_image(element, context, width, height)
    if picture is None:
        modules = render.qr_size(code, element.get("quiet", 2))
        context.problem(element, _("The QR code does not fit: it needs %(mm).1f mm at least.") % {
            "mm": modules * render.MIN_MODULE * context.squeeze * 25.4 / context.dpi})
        return
    top = render.align(y + place(height, picture.height, element.get("valign"), "middle"), context.squeeze)
    image.paste(picture, (x + place(width, picture.width, element.get("align")), top))


def picture_for(element, context):
    """The label image, turned as asked, or None (a problem)."""
    picture = context.images(element.content)
    if picture is None:
        context.problem(element, _("There is no label image “%s”.") % element.content)
        return None
    if element.get("rotate"):
        picture = picture.rotate(-element.get("rotate"), expand=True, fillcolor=255)
    return picture


def image_natural(element, context, width, height):
    picture = picture_for(element, context)
    if picture is None:
        return 0, 0
    scales = [side / size for side, size in ((width, picture.width), (height, picture.height)) if side is not None]
    scale = min(scales) if scales else 1
    return max(1, round(picture.width * scale)), max(1, round(picture.height * scale))


def draw_image(element, context, image, x, y, width, height):
    picture = picture_for(element, context)
    if picture is None or width < 1 or height < 1:
        return
    scale = min(width / picture.width, height / picture.height)
    size = (max(1, round(picture.width * scale)), max(1, round(picture.height * scale)))
    picture = picture.resize(size, Image.Resampling.LANCZOS)
    if element.get("invert"):
        picture = ImageOps.invert(picture)
    if element.get("dither"):
        bitmap = picture.convert("1")
    else:
        threshold = element.get("threshold", 128)
        bitmap = picture.point(lambda value: 255 if value >= threshold else 0).convert("1", dither=Image.Dither.NONE)
    image.paste(bitmap, (x + place(width, size[0], element.get("align")),
                         y + place(height, size[1], element.get("valign"), "middle")))


def line_thickness(element, context):
    return max(1, context.dots(element.get("thickness", DEFAULT_LINE_MM)))


def draw_shape(element, context, image, x, y, width, height, horizontal):
    draw = ImageDraw.Draw(image)
    if width < 1 or height < 1:
        return
    if element.kind == "box":
        if "border" in element.options:
            draw.rectangle((x, y, x + width - 1, y + height - 1), outline=0,
                           width=max(1, context.dots(element.get("border"))))
        else:
            draw.rectangle((x, y, x + width - 1, y + height - 1), fill=0)
    elif element.kind == "line":
        thickness = line_thickness(element, context)
        if horizontal:  # in a row: across it, upright
            left = x + (width - thickness) // 2
            draw.rectangle((left, y, left + thickness - 1, y + height - 1), fill=0)
        else:
            top = y + (height - thickness) // 2
            draw.rectangle((x, top, x + width - 1, top + thickness - 1), fill=0)
    elif element.kind == "arrow":
        right, bottom = x + width - 1, y + height - 1
        points = {"up": [(x, bottom), (right, bottom), ((x + right) / 2, y)],
                  "down": [(x, y), (right, y), ((x + right) / 2, bottom)],
                  "left": [(right, y), (right, bottom), (x, (y + bottom) / 2)],
                  "right": [(x, y), (x, bottom), (right, (y + bottom) / 2)]}[element.get("direction", "up")]
        draw.polygon(points, fill=0)


# ---------------------------------------------------------------- layout

def natural(element, context, width, height, horizontal=False):
    """(width, height) the element needs within at most width × height (None: open), its margin included.
    horizontal: its parent is a row."""
    top, right, bottom, left = margins(element, context)
    if top or right or bottom or left:
        inner = natural_content(element, context, None if width is None else max(0, width - left - right),
                                None if height is None else max(0, height - top - bottom), horizontal)
        return inner[0] + left + right, inner[1] + top + bottom
    return natural_content(element, context, width, height, horizontal)


def natural_content(element, context, width, height, horizontal):
    if element.kind in ("row", "column"):
        # As wide as its content, at most width; then as high as that needs, at most height.
        _placed, used_width, _height = arrange(element, context, None, height)
        if width is not None:
            used_width = min(used_width, width)
        _placed, _width, used_height = arrange(element, context, used_width, height)
        return used_width, used_height
    if element.kind == "text":
        return text_natural(element, context, width, height)
    if element.kind == "qr":
        return qr_natural(element, context, width, height)
    if element.kind == "image":
        return image_natural(element, context, width, height)
    if element.kind == "line":
        thickness = line_thickness(element, context)
        return (thickness, height or 0) if horizontal else (width or 0, thickness)
    if element.kind == "space":
        return 0, 0
    return width or context.dots(5), height or context.dots(5)


def bulge_depth(container, context, height):
    """How far a bulged frame's sides arch out: given, else a fifth of its height."""
    if "bulge" in container.options:
        return context.dots(container.get("bulge"))
    return max(1, height // 5) if height else context.dots(1.5)


def insets(container, context, height):
    """(top, right, bottom, left) between a row's or column's edge and its elements: padding, the frame's
    border and, for a bulged frame, the depth of its arches."""
    top, right, bottom, left = (context.dots(side) for side in container.get("padding", (0, 0, 0, 0)))
    border = context.dots(container.get("border", 0)) if "border" in container.options else 0
    arch = bulge_depth(container, context, height) if container.get("shape") == "bulge" else 0
    return top + border, right + border + arch, bottom + border, left + border + arch


def draw_frame(container, context, image, x, y, width, height):
    """The frame of a row or column: its border, square, with round corners or with arched sides."""
    if "border" not in container.options or width < 2 or height < 2:
        return
    border = max(1, context.dots(container.get("border")))
    draw = ImageDraw.Draw(image)
    shape = container.get("shape", "rect")
    right, bottom = x + width - 1, y + height - 1
    if shape == "bulge":
        # One line of the same thickness all round, its outer edge on the box.
        half = border / 2
        outline = bulge_outline(x + half, y + half, right - half, bottom - half, bulge_depth(container, context, height))
        stroke(image, outline, border)
    elif shape == "round":
        radius = context.dots(container.get("radius")) if "radius" in container.options else min(width, height) // 4
        draw.rounded_rectangle((x, y, right, bottom), radius=radius, outline=0, width=border)
    else:
        draw.rectangle((x, y, right, bottom), outline=0, width=border)


def stroke(image, points, width, scale=4):
    """A closed line through the points, width dots thick everywhere, with round joins: drawn four times as
    large (each piece a quadrilateral, each join a disc) and brought down to the image's dots, so it has no
    holes or notches at any resolution."""
    radius = width / 2
    left = math.floor(min(x for x, _y in points) - radius) - 1
    top = math.floor(min(y for _x, y in points) - radius) - 1
    right = math.ceil(max(x for x, _y in points) + radius) + 1
    bottom = math.ceil(max(y for _x, y in points) + radius) + 1
    canvas = Image.new("L", ((right - left) * scale, (bottom - top) * scale), 0)
    draw = ImageDraw.Draw(canvas)
    scaled = [((x - left) * scale, (y - top) * scale) for x, y in points]
    big = radius * scale
    for (x0, y0), (x1, y1) in zip(scaled, scaled[1:] + scaled[:1]):
        length = math.hypot(x1 - x0, y1 - y0)
        if length:
            nx, ny = -(y1 - y0) / length * big, (x1 - x0) / length * big
            draw.polygon([(x0 + nx, y0 + ny), (x1 + nx, y1 + ny), (x1 - nx, y1 - ny), (x0 - nx, y0 - ny)], fill=255)
        draw.ellipse((x0 - big, y0 - big, x0 + big, y0 + big), fill=255)
    mask = canvas.resize((right - left, bottom - top), Image.Resampling.BOX).point(lambda value: 255 if value >= 128 else 0)
    image.paste(0, (left, top), mask.convert("1"))


def bulge_outline(left, top, right, bottom, depth):
    """Points of a price tag's shape: straight top and bottom, and sides like a price gun's labels, which leave
    the corners straight down, swing out and reach the middle upright again, depth beyond the corners."""
    height = bottom - top
    depth = max(1, min(depth, (right - left) // 2))
    # Upper half of a side as a cubic Bézier curve: (outwards from the corner, down), corner to middle.
    points = ((0, 0), (0, 0.22 * height), (depth, 0.2 * height), (depth, height / 2))
    steps = max(8, int(height) // 3)
    half = []
    for step in range(steps + 1):
        t = step / steps
        weights = ((1 - t) ** 3, 3 * (1 - t) ** 2 * t, 3 * (1 - t) * t * t, t ** 3)
        half.append((sum(w * point[0] for w, point in zip(weights, points)),
                     sum(w * point[1] for w, point in zip(weights, points))))
    side = half + [(out, height - down) for out, down in reversed(half[:-1])]
    right_side = [(right - depth + out, top + down) for out, down in side]
    left_side = [(left + depth - out, top + down) for out, down in side]
    return right_side + left_side[::-1]


def arrange(container, context, width, height):
    """([(element, x, y, width, height)], used width, used height): the container's elements placed within its
    size (width or height None: as needed), relative to its top left."""
    horizontal = container.kind == "row"
    inset_top, inset_right, inset_bottom, inset_left = insets(container, context, height)
    inner_width = None if width is None else max(0, width - inset_left - inset_right)
    inner_height = None if height is None else max(0, height - inset_top - inset_bottom)
    main_total, cross_total = (inner_width, inner_height) if horizontal else (inner_height, inner_width)
    main_name, cross_name = ("width", "height") if horizontal else ("height", "width")
    gap = context.dots(container.get("gap", 0))
    flow = [child for child in container.children if "at" not in child.options]

    def size(main, cross):
        return (main, cross) if horizontal else (cross, main)

    # Along: fixed first, then auto (what it needs, within what is left), fill shares the rest.
    def margin(child, along):
        top, right, bottom, left = margins(child, context)
        return (left + right) if along == horizontal else (top + bottom)

    kinds, mains = [], []
    for child in flow:
        spec = child.get(main_name) or (child.get("extent") if child.kind == "space" else None)
        fixed = resolve(spec, main_total, context)
        fixed = None if fixed is None else fixed + margin(child, True)
        if fixed is not None:
            kinds.append("fixed")
        elif (spec == ("fill",) or (spec is None and not intrinsic(child, horizontal))) and main_total is not None:
            kinds.append("fill")
        else:
            kinds.append("auto")
        mains.append(fixed)
    taken = sum(main for main in mains if main is not None) + gap * max(0, len(flow) - 1)
    # Text that fits its box comes last: it shrinks to leave room for the others (a logo after a name).
    autos = [index for index, kind in enumerate(kinds) if kind == "auto"]
    for index in sorted(autos, key=lambda index: shrinks(flow[index])):
        child = flow[index]
        cross = resolve(child.get(cross_name), cross_total, context)
        cross = cross_total if cross is None else cross + margin(child, False)
        room = None if main_total is None else max(0, main_total - taken)
        mains[index] = natural(child, context, *size(room, cross), horizontal=horizontal)[0 if horizontal else 1]
        taken += mains[index]
    fills = [child for child, kind in zip(flow, kinds) if kind == "fill"]
    if fills:
        rest = max(0, main_total - taken)
        share, extra = divmod(rest, len(fills))
        mains = [main if main is not None else share + (1 if fills.index(child) < extra else 0)
                 for child, main in zip(flow, mains)]
        taken = main_total
    if main_total is not None and taken > main_total and flow:
        context.problem(container, _("The elements are %(mm).1f mm too long for this %(kind)s.") % {
            "mm": (taken - main_total) * 25.4 / context.dpi, "kind": container.kind})

    # Across: given, else stretched to the row or column (as wide as the widest element where open).
    crosses = []
    for child, main in zip(flow, mains):
        given = resolve(child.get(cross_name), cross_total, context)
        given = None if given is None else given + margin(child, False)
        if given is None and child.get(cross_name) == ("auto",) or (given is None and cross_total is None):
            given = natural(child, context, *size(main, cross_total), horizontal=horizontal)[1 if horizontal else 0]
        crosses.append(given)
    if cross_total is None:
        cross_total = max([cross for cross in crosses if cross is not None], default=0)
    crosses = [cross_total if cross is None else cross for cross in crosses]

    placed, position = [], inset_left if horizontal else inset_top
    if main_total is not None and taken < main_total:  # room left: where the elements go along
        position += place(main_total, taken, {"start": "left", "end": "right"}.get(container.get("justify"), "center")
                          if container.get("justify") else "left")
    align = container.get("align")
    for child, main, cross in zip(flow, mains, crosses):
        offset = (inset_top if horizontal else inset_left) + place(cross_total, cross, align,
                                                                  "middle" if horizontal else "center")
        x, y = (position, offset) if horizontal else (offset, position)
        placed.append((child, x, y, *size(main, cross)))
        position += main + gap
    for child in container.children:
        if "at" not in child.options:
            continue
        x, y = (context.dots(value) for value in child.get("at"))
        room_width = None if inner_width is None else max(0, inner_width - x)
        room_height = None if inner_height is None else max(0, inner_height - y)
        top, right, bottom, left = margins(child, context)
        child_width = resolve(child.get("width"), inner_width, context)
        child_width = None if child_width is None else child_width + left + right
        child_height = resolve(child.get("height"), inner_height, context)
        child_height = None if child_height is None else child_height + top + bottom
        need = natural(child, context, child_width or room_width, child_height or room_height)
        placed.append((child, inset_left + x, inset_top + y, child_width or need[0], child_height or need[1]))
    used_width = (taken if horizontal else cross_total) + inset_left + inset_right
    used_height = (cross_total if horizontal else taken) + inset_top + inset_bottom
    return placed, width if width is not None else used_width, height if height is not None else used_height


def draw(element, context, image, x, y, width, height, horizontal=False):
    top, right, bottom, left = margins(element, context)
    x, y, width, height = x + left, y + top, max(0, width - left - right), max(0, height - top - bottom)
    if element.kind in ("row", "column"):
        draw_frame(element, context, image, x, y, width, height)
        placed, _width, _height = arrange(element, context, width, height)
        for child, child_x, child_y, child_width, child_height in placed:
            draw(child, context, image, x + child_x, y + child_y, child_width, child_height, element.kind == "row")
    elif element.kind == "text":
        draw_text(element, context, image, x, y, width, height)
    elif element.kind == "qr":
        draw_qr(element, context, image, x, y, width, height)
    elif element.kind == "image":
        draw_image(element, context, image, x, y, width, height)
    elif element.kind in ("box", "line", "arrow"):
        draw_shape(element, context, image, x, y, width, height, horizontal)


def render_design(design, context, width=None, height=None):
    """The label as a 1-bit image: width × height dots (the printer's label), or the design's size; a label
    without width is as long as its content (within its min and max length)."""
    top, right, bottom, left = (context.dots(side) for side in design.margin)
    height = height or context.dots(design.height)
    if width is None and design.width:
        width = context.dots(design.width)
    root = Element("column", 0, options={"align": "left"}, children=design.children)
    inner_height = max(0, height - top - bottom)
    if width is None:
        _placed, inner_width, _height = arrange(root, context, None, inner_height)
        width = inner_width + left + right
        if design.max_length and width > context.dots(design.max_length):
            width = context.dots(design.max_length)
        if design.min_length:
            width = max(width, context.dots(design.min_length))
    image = render.blank(width, height)
    draw(root, context, image, left, top, max(0, width - left - right), inner_height)
    if design.rotate:
        image = image.rotate(design.rotate)
    return image
