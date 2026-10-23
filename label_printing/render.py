"""Drawing labels as 1-bit images: text fitted into boxes without anti-aliasing, and crisp QR codes."""
import functools
from pathlib import Path

import segno
from PIL import Image, ImageDraw, ImageFont, ImageOps

FONTS = Path(__file__).resolve().parent.parent / "inventory" / "label_ids" / "labels" / "fonts"
SANS = str(FONTS / "Raleway%5Bwght%5D.ttf")
MONO = str(FONTS / "RobotoMono%5Bwght%5D.ttf")
MIN_FONT_PX = 8
QR_BORDER = 2  # modules of quiet zone; tape and label edges add to it
MIN_MODULE = 2  # dots per module, below that scanners struggle
# A version 1 QR code (21 modules, e.g. a label ID) at MIN_MODULE: the least height for a QR layout.
MIN_QR_DOTS = (21 + 2 * QR_BORDER) * MIN_MODULE


@functools.lru_cache(maxsize=512)
def font(path, size, weight=400):
    loaded = ImageFont.truetype(path, size)
    try:
        loaded.set_variation_by_axes([weight])
    except OSError:
        pass  # not a variable font
    return loaded


def blank(width, height):
    return Image.new("1", (max(width, 1), max(height, 1)), 1)


def line_height(loaded):
    ascent, descent = loaded.getmetrics()
    return ascent + descent


def text_width(loaded, text):
    return loaded.getlength(text)


def wrap(text, loaded, width):
    """Greedy word wrap; a word longer than the line is split."""
    lines = []
    for paragraph in text.splitlines() or [""]:
        line = ""
        for word in paragraph.split():
            candidate = f"{line} {word}".strip()
            if text_width(loaded, candidate) <= width:
                line = candidate
                continue
            if line:
                lines.append(line)
            while text_width(loaded, word) > width and len(word) > 1:
                cut = len(word)
                while cut > 1 and text_width(loaded, word[:cut]) > width:
                    cut -= 1
                lines.append(word[:cut])
                word = word[cut:]
            line = word
        lines.append(line)
    return lines


def ellipsize(loaded, text, width):
    if text_width(loaded, text) <= width:
        return text
    while text and text_width(loaded, text + "…") > width:
        text = text[:-1]
    return text.rstrip() + "…"


def fit(text, width, height, path=SANS, weight=400, max_lines=1, max_size=None):
    """(font, lines): the largest font size that fits `text` into width × height dots in up to
    `max_lines` lines; at the smallest size the last line is cut short with "…"."""
    high = max(MIN_FONT_PX, min(max_size or height, height))
    low, best = MIN_FONT_PX, None
    while low <= high:
        size = (low + high) // 2
        loaded = font(path, size, weight)
        lines = wrap(text, loaded, width)
        if len(lines) <= max_lines and len(lines) * line_height(loaded) <= height:
            best, low = (loaded, lines), size + 1
        else:
            high = size - 1
    if best:
        return best
    loaded = font(path, MIN_FONT_PX, weight)
    lines = wrap(text, loaded, width)[:max(1, min(max_lines, height // line_height(loaded)))]
    lines[-1] = ellipsize(loaded, lines[-1] + ("…" if len(wrap(text, loaded, width)) > len(lines) else ""), width)
    return loaded, lines


def fit_height(text, height, path=SANS, weight=400):
    """The font for one line of `text` filling `height` dots (for tape, where the length is free)."""
    size = height
    while size > MIN_FONT_PX and line_height(font(path, size, weight)) > height:
        size -= 1
    return font(path, size, weight)


def draw_lines(image, box, loaded, lines, align="left", valign="top", fill=0):
    """Draw text lines into box = (x, y, width, height)."""
    x, y, width, height = box
    draw = ImageDraw.Draw(image)
    draw.fontmode = "1"
    step = line_height(loaded)
    if valign == "middle":
        y += max(0, (height - step * len(lines)) // 2)
    elif valign == "bottom":
        y += max(0, height - step * len(lines))
    for line in lines:
        offset = {"left": 0, "center": (width - text_width(loaded, line)) / 2,
                  "right": width - text_width(loaded, line)}[align]
        draw.text((x + offset, y), line, font=loaded, fill=fill)
        y += step


def text_box(image, box, text, path=SANS, weight=400, max_lines=1, align="left", valign="top", fill=0, max_size=None):
    """Fit and draw `text` into box; returns the font used."""
    loaded, lines = fit(text, box[2], box[3], path, weight, max_lines, max_size)
    draw_lines(image, box, loaded, lines, align, valign, fill)
    return loaded


def qr(content, error="l"):
    """A QR code; uppercase content in its alphanumeric mode keeps it small (see label_printing.label_urls)."""
    return segno.make(content, error=error, micro=False, boost_error=False)


def qr_size(code, border=QR_BORDER):
    """Size in modules including the quiet zone."""
    return code.symbol_size(scale=1, border=border)[0]


def qr_image(code, max_dots, border=QR_BORDER, min_module=MIN_MODULE, step=1):
    """The QR code as a 1-bit image with whole dots per module (a multiple of step), as large as fits
    into max_dots; None if not even min_module dots per module fit."""
    modules = qr_size(code, border)
    scale = max_dots // modules
    scale -= scale % step
    if scale < min_module * step:
        return None
    size = modules * scale
    image = blank(size, size)
    pixels = image.load()
    for row_index, row in enumerate(code.matrix):
        for column_index, dark in enumerate(row):
            if dark & 1:
                x0, y0 = (column_index + border) * scale, (row_index + border) * scale
                for y in range(y0, y0 + scale):
                    for x in range(x0, x0 + scale):
                        pixels[x, y] = 0
    return image


def inverted_text(image, box, text, path=MONO, weight=700, padding=None):
    """White text on a black box = (x, y, width, height); returns the font used."""
    x, y, width, height = box
    padding = max(1, height // 8) if padding is None else padding
    ImageDraw.Draw(image).rectangle((x, y, x + width - 1, y + height - 1), fill=0)
    return text_box(image, (x + padding, y + padding, width - 2 * padding, height - 2 * padding), text, path, weight,
                    align="center", valign="middle", fill=1)


# Colours of label stock (names as on Brother's tape list), for previews.
COLOURS = {
    "weiß": "#ffffff", "schwarz": "#1a1a1a", "gelb": "#ffd400", "transparent": "#eef1f4", "blau": "#1f5fbf",
    "rot": "#d0202a", "grün": "#1f9a48", "silber": "#c4c8cc", "gold": "#b8902b", "signalorange": "#ff7a00",
    "signalgelb": "#e8ff1a", "glitzergold": "#d4af37", "glitzersilber": "#cfd3d6", "dunkelblau": "#14306e",
    "weinrot": "#7a1f2b", "rosa": "#f6b5c9", "hellblau": "#8fd0f0", "mintgrün": "#9fe2bf", "apfelgrün": "#8dc63f",
    "hellgrau": "#d3d6d9", "pink": "#ff4fa3", "pastellblau": "#b9d7f2", "pastelllila": "#d6c4ef",
    "pastellrosa": "#f6d0dc",
}


def colour(name, default):
    """The colour for a name like "silber (matt)" or "rosa Herzen (matt)"; default if unknown."""
    words = name.lower().replace("(matt)", "").split()
    return COLOURS.get(" ".join(words)) or (COLOURS.get(words[0]) if words else None) or default


def coloured(image, background="", ink=""):
    """The 1-bit label in the colours of its stock (black prints in `ink`, white is `background`)."""
    if not (background or ink):
        return image
    return ImageOps.colorize(image.convert("L"), colour(ink, "#1a1a1a"), colour(background, "#ffffff"))


def align(value, step):
    """value rounded down to a multiple of step (positions that survive squeeze unchanged)."""
    return value - value % step


def squeeze(image, factor):
    """Squeeze a 1-bit image to 1/factor of its height; a dot is black if any of its rows was (thin lines stay)."""
    if factor == 1:
        return image
    grey = image.convert("L").resize((image.width, image.height // factor), Image.Resampling.BOX)
    return grey.point(lambda value: 0 if value < 255 - 255 // (2 * factor) else 255).convert("1")
