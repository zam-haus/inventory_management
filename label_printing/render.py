"""Drawing labels as 1-bit images: text fitted into boxes without anti-aliasing, and crisp QR codes."""
import functools
import re
from pathlib import Path

import segno
from PIL import Image, ImageDraw, ImageFont, ImageOps

FONTS = Path(__file__).resolve().parent / "design" / "fonts"
SANS = str(FONTS / "Raleway%5Bwght%5D.ttf")
MONO = str(FONTS / "RobotoMono%5Bwght%5D.ttf")
MIN_FONT_PX = 8
QR_BORDER = 2  # modules of quiet zone; tape and label edges add to it
MIN_MODULE = 2  # dots per module, below that scanners struggle


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
    `max_lines` lines, without splitting a word if it fits that way; at the smallest size the last line is cut
    short with "…"."""
    words = text.split()
    for whole_words in (True, False):  # rather smaller than with a word split, if it fits that way
        high = max(MIN_FONT_PX, min(max_size or height, height))
        low, best = MIN_FONT_PX, None
        while low <= high:
            size = (low + high) // 2
            loaded = font(path, size, weight)
            lines = wrap(text, loaded, width)
            if (len(lines) <= max_lines and len(lines) * line_height(loaded) <= height
                    and not (whole_words and any(text_width(loaded, word) > width for word in words))):
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
        writing_lines(draw, x + offset, y, loaded, line, fill)
        y += step


UNDERSCORES = re.compile(r"_{2,}")


def writing_lines(draw, x, y, loaded, line, fill):
    """Runs of underscores as one unbroken line, a line to write on: fonts draw them with gaps."""
    for run in UNDERSCORES.finditer(line):
        _left, top, _right, bottom = loaded.getbbox("_")
        start = x + text_width(loaded, line[:run.start()])
        draw.rectangle((round(start), y + top, round(start + text_width(loaded, run.group())) - 1,
                        y + max(top, bottom - 1)), fill=fill)


def text_box(image, box, text, path=SANS, weight=400, max_lines=1, align="left", valign="top", fill=0, max_size=None):
    """Fit and draw `text` into box; returns the font used."""
    loaded, lines = fit(text, box[2], box[3], path, weight, max_lines, max_size)
    draw_lines(image, box, loaded, lines, align, valign, fill)
    return loaded


# Code 128: the widths of bar, space, bar, … of each symbol value (103–105 start A, B, C; 106 stop).
CODE128 = ("212222", "222122", "222221", "121223", "121322", "131222", "122213", "122312", "132212", "221213", "221312",
           "231212", "112232", "122132", "122231", "113222", "123122", "123221", "223211", "221132", "221231", "213212",
           "223112", "312131", "311222", "321122", "321221", "312212", "322112", "322211", "212123", "212321", "232121",
           "111323", "131123", "131321", "112313", "132113", "132311", "211313", "231113", "231311", "112133", "112331",
           "132131", "113123", "113321", "133121", "313121", "211331", "231131", "213113", "213311", "213131", "311123",
           "311321", "331121", "312113", "312311", "332111", "314111", "221411", "431111", "111224", "111422", "121124",
           "121421", "141122", "141221", "112214", "112412", "122114", "122411", "142112", "142211", "241211", "221114",
           "413111", "241112", "134111", "111242", "121142", "121241", "114212", "124112", "124211", "411212", "421112",
           "421211", "212141", "214121", "412121", "111143", "111341", "131141", "114113", "114311", "411113", "411311",
           "113141", "114131", "311141", "411131", "211412", "211214", "211232", "2331112")
CODE128_QUIET = 10  # modules of white before and after the bars
MIN_BAR_MM = 0.13  # narrowest bar scanners read well: 2 dots at 360 dpi, 1 at 180 or 203 dpi


def code128(text):
    """The modules of a Code 128 barcode of the text ("1" bar, "0" space), in set C for an even number of digits
    (half as long), else set B (ASCII 32–126); None for other characters or no text."""
    if text and text.isdigit() and len(text) % 2 == 0:
        values = [105] + [int(text[index:index + 2]) for index in range(0, len(text), 2)]
    elif text and all(32 <= ord(character) <= 126 for character in text):
        values = [104] + [ord(character) - 32 for character in text]
    else:
        return None
    values += [(values[0] + sum(position * value for position, value in enumerate(values[1:], start=1))) % 103, 106]
    return "".join(("1" if index % 2 == 0 else "0") * int(width)
                   for value in values for index, width in enumerate(CODE128[value]))


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


def stack(images, gap):
    """Labels one below the other, `gap` dots apart (transparent there), for previews of a list that goes on on
    further labels; a single label as it is. info["labels"]: how many."""
    if len(images) == 1:
        return images[0]
    sheet = Image.new("RGBA", (max(image.width for image in images), sum(image.height for image in images)
                               + gap * (len(images) - 1)), (0, 0, 0, 0))
    top = 0
    for image in images:
        sheet.paste(image.convert("RGBA"), (0, top))
        top += image.height + gap
    sheet.info["labels"] = len(images)
    return sheet


def align(value, step):
    """value rounded down to a multiple of step (positions that survive squeeze unchanged)."""
    return value - value % step


def squeeze(image, factor):
    """Squeeze a 1-bit image to 1/factor of its height; a dot is black if any of its rows was (thin lines stay)."""
    if factor == 1:
        return image
    grey = image.convert("L").resize((image.width, image.height // factor), Image.Resampling.BOX)
    return grey.point(lambda value: 0 if value < 255 - 255 // (2 * factor) else 255).convert("1")
