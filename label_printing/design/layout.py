"""
Laying out and drawing a label Design as a 1-bit image for one printer. Millimetres become the printer's
dots only here, so a design prints bit-exact at any resolution.

Rows lay their elements out from left to right, columns from top to bottom (the label itself is a column).
Along that direction an element is as large as given (mm, or % of the row or column), as its content needs
("auto": the default for text with a size, QR codes, images, lines, fixed spaces), or shares what is left
with the other "fill" elements (the default otherwise; where the length is open, fill means auto). Across
it fills the row or column unless given ("auto": as large as its content, e.g. a price frame or inverted
text beside a long name); then the row's or column's align places it. Elements with "at x y" (mm from the
top left of their row or column) are placed there instead. A row or column that shows nothing (blank) is left
out.

A list shows one entry per line, as many as fit its box; the others go on on further labels, the whole design
drawn again (render_labels), with page and pages to number them.
"""
import functools
import math
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Callable

from django.template import Variable, VariableDoesNotExist
from django.utils.translation import gettext as _
from PIL import Image, ImageDraw, ImageOps

from .. import render
from . import texts
from .language import Element, Problem

HERE = Path(__file__).resolve().parent
FONT_FILES = {
    "sans": render.SANS,  # Raleway: the ZAMid lettering
    "mono": render.MONO,  # Roboto Mono: the ZAMid's ID
    "condensed": str(HERE / "fonts" / "RobotoCondensed-wght.ttf"),
    "ocr": str(HERE / "fonts" / "OCR-B.otf"),
}
DEFAULT_TEXT_MM = 3
DEFAULT_LINE_MM = 0.25
MAX_LABELS = 20  # a list goes on on at most this many labels


class TooSmall(Exception):
    """Something does not fit (a QR code too small to scan); raised when printing, a problem in previews."""

    def __init__(self, problem):
        super().__init__(problem.message)
        self.problem = problem


@dataclass
class Context:
    dpi: int
    # What the texts and QR codes show: {"location": …, "qr": …} (texts.py)
    variables: dict = field(default_factory=dict)
    # A label image by name: its cropped original, greyscale; None if there is none.
    images: Callable[[str], Image.Image | None] = lambda name: None
    squeeze: int = 1
    strict: bool = False
    problems: list = field(default_factory=list)
    rendered: dict = field(default_factory=dict)
    lists: dict = field(default_factory=dict)  # the entries of each list, by line
    start: int = 0  # the first entry of a list on this label
    next: int | None = None  # the first entry that did not fit, for the next label
    continued: Element | None = None  # the list that goes on

    def dots(self, mm):
        return max(0, round(mm * self.dpi / 25.4))

    def problem(self, element, message):
        problem = Problem(element.line, message)
        if self.strict:
            raise TooSmall(problem)
        if problem not in self.problems:
            self.problems.append(problem)

    def text(self, element):
        """The element's content rendered with the variables (once per element: properties may query); with a
        syntax error the content itself. Previews say which variables have no value."""
        if element.line not in self.rendered:
            source = element.content or ""
            error = texts.syntax_error(source)
            if error is not None:
                if not self.strict:
                    self.problem(element, error)
                self.rendered[element.line] = source
            else:
                if not self.strict:
                    for name in texts.missing(source, self.variables):
                        self.problem(element, _("There is no “%s”, at least not for this record.") % name)
                self.rendered[element.line] = texts.render(source, self.variables)
        return self.rendered[element.line]


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


def blank(element, context):
    """Whether a row or column shows nothing although it has texts: they all came out as nothing at all (e.g. a
    price frame for an item without a price, "{% if %}…{% endif %}"), and it holds nothing else but spaces. It
    is left out, frame and all. Texts of blanks keep their room (an empty frame), as does a frame around just
    spaces."""
    inside = list(element.walk())
    texts = [child for child in inside if child.kind == "text"]
    return (bool(texts) and all(child.kind in ("row", "column", "space", "text") for child in inside)
            and not any(context.text(text) for text in texts))


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
    if not context.text(element):  # came out as nothing at all: takes no room (blanks do)
        return 0, 0
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
    if not context.text(element):  # nothing at all: no inverted box either (e.g. the code of no location)
        return
    rotation = element.get("rotate", 0)
    box_width, box_height = (height, width) if rotation in (90, 270) else (width, height)
    # Crowded out by the other elements of its row or column: not even the smallest font fits (a sliver of a box
    # would draw it too small to see)
    if box_width < 1 or box_height < render.MIN_FONT_PX:
        if context.text(element).strip():
            context.problem(element, _("There is no room left for this text."))
        return
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


# ---------------------------------------------------------------- lists

def entries(element, context):
    """The entries of a list: its variable's value, e.g. {{ contents }} (design/variables.py Entry: amount, name and
    label ID; other values show as their text)."""
    if element.line not in context.lists:
        name = element.content.strip("{} ")
        try:
            found = list(Variable(name).resolve(context.variables))
        except (VariableDoesNotExist, TypeError):
            found = None
        context.lists[element.line] = found
    found = context.lists[element.line]
    if found is None:
        context.problem(element, _("“%s” is not a list.") % element.content.strip("{} "))
        return []
    return found


def entry_parts(entry):
    """(amount, name, code, note) of an entry."""
    return (str(getattr(entry, "amount", "")), str(getattr(entry, "name", entry)), str(getattr(entry, "code", "")),
            str(getattr(entry, "note", "")))


def code_width(look, code):
    """Dots the label ID or code takes after the name."""
    return round(render.text_width(look.code_font, code)) + look.space // 2 if code else 0


@dataclass
class ListLook:
    font: object
    code_font: object
    line: int  # dots per line
    gap: int  # between entries
    space: int  # between the columns
    amount: int  # width of the amounts' column (right-aligned)


def list_look(element, context, found):
    path, weight = font_for(element, context)
    size = max(1, context.dots(element.get("size", DEFAULT_TEXT_MM)))
    loaded = render.font(path, size, weight)
    code_font = render.font(FONT_FILES["mono"], size, 700)
    line = render.line_height(loaded)
    return ListLook(loaded, code_font, line,
                    context.dots(element.get("gap")) if "gap" in element.options else max(1, line // 6),
                    round(render.text_width(loaded, "  ")),
                    round(max((render.text_width(loaded, entry_parts(entry)[0]) for entry in found), default=0)))


def name_width(look, width):
    """Dots left for the names: the row less the amounts' column."""
    return max(1, width - (look.amount + look.space if look.amount else 0))


def name_lines(element, look, name, code, width):
    """The name in at most `lines` lines, the last cut short with "…" so the label ID still fits after it."""
    max_lines = element.get("lines", 1)
    lines = render.wrap(name, look.font, width) if max_lines > 1 else [name]
    if len(lines) > max_lines:
        lines = lines[:max_lines - 1] + [" ".join(lines[max_lines - 1:])]
    return lines[:-1] + [render.ellipsize(look.font, lines[-1], max(1, width - code_width(look, code)))]


def entry_lines(element, look, name, code, note, width):
    """(name lines, note lines): the note (whose a unique item is) on a line of its own below the name."""
    return name_lines(element, look, name, code, width), [render.ellipsize(look.font, note, width)] if note else []


def list_natural(element, context, width, height):
    found = entries(element, context)[context.start:]
    if not found:
        return 0, 0
    look = list_look(element, context, entries(element, context))
    if width is None:
        names = max(max(round(render.text_width(look.font, name)) + code_width(look, code),
                        round(render.text_width(look.font, note)))
                    for _amount, name, code, note in map(entry_parts, found))
        width = (look.amount + look.space if look.amount else 0) + names
    room = name_width(look, width)
    used = sum(sum(map(len, entry_lines(element, look, *entry_parts(entry)[1:], room))) * look.line for entry in found)
    used += look.gap * (len(found) - 1)
    return width, used if height is None else min(used, height)


def draw_list(element, context, image, x, y, width, height):
    found = entries(element, context)
    if context.start >= len(found):
        return
    look = list_look(element, context, found)
    room = name_width(look, width)
    left = x + (look.amount + look.space if look.amount else 0)
    top, index = y, context.start
    while index < len(found):
        amount, name, code, note = entry_parts(found[index])
        lines, notes = entry_lines(element, look, name, code, note, room)
        if top + (len(lines) + len(notes)) * look.line > y + height:
            break
        if amount:
            render.draw_lines(image, (x, top, look.amount, look.line), look.font, [amount], "right")
        render.draw_lines(image, (left, top, room, len(lines) * look.line), look.font, lines)
        if code:  # right after the name, on its baseline
            after = left + round(render.text_width(look.font, lines[-1])) + look.space // 2
            baseline = look.font.getmetrics()[0] - look.code_font.getmetrics()[0]
            render.draw_lines(image, (after, top + (len(lines) - 1) * look.line + baseline, max(1, x + width - after),
                                      look.line), look.code_font, [code])
        if notes:  # below the name
            render.draw_lines(image, (left, top + len(lines) * look.line, room, look.line), look.font, notes)
        top += (len(lines) + len(notes)) * look.line + look.gap
        index += 1
    if index < len(found):
        if index == context.start:  # not even one entry: it would go on forever
            context.problem(element, _("There is no room left for this list."))
        elif context.next is None:
            context.next, context.continued = index, element


# ---------------------------------------------------------------- barcodes

def barcode_modules(element, context):
    """The Code 128 modules of the element's text, with its quiet zone on each side; "" for no text."""
    text = context.text(element)
    if not text:
        return ""
    modules = render.code128(text)
    if modules is None:
        context.problem(element, _("A Code 128 barcode takes letters, digits and signs, not “%s”.") % text)
        return ""
    quiet = "0" * element.get("quiet", render.CODE128_QUIET)
    return quiet + modules + quiet


def barcode_scale(element, context, extent):
    """(dots per module, the least it may be): whole dots, a multiple of squeeze across a tape (where the image is
    squeezed); the least MIN_BAR_MM."""
    across = element.get("rotate", 0) in (90, 270)
    step = context.squeeze if across else 1
    least = max(1, round(render.MIN_BAR_MM * context.dpi / step / 25.4)) * step
    modules = len(barcode_modules(element, context))
    scale = extent // modules if modules and extent is not None else least
    return scale - scale % step, least


def barcode_natural(element, context, width, height):
    modules = barcode_modules(element, context)
    if not modules:
        return 0, 0
    across = element.get("rotate", 0) in (90, 270)
    scale, least = barcode_scale(element, context, height if across else width)
    along = len(modules) * max(scale, least)
    bars = (width if across else height) or context.dots(8)
    return (bars, along) if across else (along, bars)


def draw_barcode(element, context, image, x, y, width, height):
    modules = barcode_modules(element, context)
    if not modules or width < 1 or height < 1:
        return
    rotation = element.get("rotate", 0)
    across = rotation in (90, 270)
    scale, least = barcode_scale(element, context, height if across else width)
    if scale < least:
        context.problem(element, _("The barcode does not fit: it needs %(mm).1f mm at least.") % {
            "mm": len(modules) * least * 25.4 / context.dpi})
        return
    if rotation in (180, 270):  # read from the other end
        modules = modules[::-1]
    start = ((height if across else width) - len(modules) * scale) // 2
    start = render.align((y if across else x) + start, context.squeeze if across else 1)
    draw = ImageDraw.Draw(image)
    for index, dark in enumerate(modules):
        if dark == "1":
            offset = start + index * scale
            if across:
                draw.rectangle((x, offset, x + width - 1, offset + scale - 1), fill=0)
            else:
                draw.rectangle((offset, y, offset + scale - 1, y + height - 1), fill=0)


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
        if "border" in element.options:  # just the outline, e.g. to colour in by hand
            draw.polygon(points, outline=0, width=max(1, context.dots(element.get("border"))))
        else:
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
        # As wide as its content, at most width; then as high as that needs, at most height (with "height auto" in a
        # column: only as high as its content, e.g. lines of text above a list that takes the rest).
        _placed, used_width, _height = arrange(element, context, None, height)
        if width is not None:
            used_width = min(used_width, width)
        to_content = not horizontal and element.get("height") == ("auto",)
        _placed, _width, used_height = arrange(element, context, used_width, None if to_content else height)
        if height is not None:
            used_height = min(used_height, height)
        return used_width, used_height
    if element.kind == "text":
        return text_natural(element, context, width, height)
    if element.kind == "qr":
        return qr_natural(element, context, width, height)
    if element.kind == "image":
        return image_natural(element, context, width, height)
    if element.kind == "list":
        return list_natural(element, context, width, height)
    if element.kind == "barcode":
        return barcode_natural(element, context, width, height)
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
    shown = [child for child in container.children if child.kind not in ("row", "column") or not blank(child, context)]
    flow = [child for child in shown if "at" not in child.options]

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
    for child in shown:
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
    elif element.kind == "list":
        draw_list(element, context, image, x, y, width, height)
    elif element.kind == "barcode":
        draw_barcode(element, context, image, x, y, width, height)
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
    turned = design.rotate in (90, 270)
    if turned:  # laid out across, turned clockwise onto the label
        width, height = height, width
        inner_height = max(0, height - top - bottom)
    image = render.blank(width, height)
    draw(root, context, image, left, top, max(0, width - left - right), inner_height)
    if design.rotate:
        image = image.rotate(-design.rotate, expand=True)
    if design.invert:  # the whole label white (its colour) on black
        image = ImageOps.invert(image.convert("L")).convert("1")
    return image


def render_labels(design, context, width=None, height=None):
    """The label, and the labels a list goes on on where its entries do not all fit (render_design each time,
    with page and pages: worked out once, then drawn with their number): [image], at most MAX_LABELS."""
    def labels(pages):
        images, start = [], 0
        while True:
            page = replace(context, variables={**context.variables, "page": len(images) + 1, "pages": pages},
                           rendered={}, start=start, next=None, continued=None)
            images.append(render_design(design, page, width, height))
            if page.next is None:
                return images
            if len(images) == MAX_LABELS:
                page.problem(page.continued, _("The list does not fit on %d labels.") % MAX_LABELS)
                return images
            start = page.next

    images = labels(1)
    return labels(len(images)) if len(images) > 1 else images
