"""A short test label naming printer and time, printed from the printer admin."""
from django.utils import timezone
from django.utils.formats import time_format
from django.utils.translation import gettext, gettext_lazy as _

from PIL import ImageDraw

from .. import render
from . import Layout, Rendered, register

# On tape the test label is this long, whatever the names: tape is not to be wasted on tests.
TAPE_LENGTH_MM = 30
# The calibration label's x ruler is fine over these first dots: a printer's shift is within them.
FINE = 50


@register
class TestLabel(Layout):
    key = "test"
    name = _("Test label")
    subject_type = "printer"

    def render(self, printer, canvas, medium, *, preview=False, user=None):
        title = gettext("Test print")
        detail = f"{printer.name} · {time_format(timezone.localtime(), 'H:i')}"
        margin = max(2, canvas.height // 16)
        width = canvas.width or canvas.dots(TAPE_LENGTH_MM)
        image = render.blank(width, canvas.height)
        inner_width, inner_height = width - 2 * margin, canvas.height - 2 * margin
        title_height = inner_height * 11 // 20
        render.text_box(image, (margin, margin, inner_width, title_height), title, weight=700, valign="middle")
        render.text_box(image, (margin, margin + title_height, inner_width, inner_height - title_height), detail,
                        valign="middle")
        return Rendered(image=image, snapshot={"printer": printer.name, "medium": medium.name})


@register
class CalibrationLabel(Layout):
    """Rulers in print head dots along the whole print area, with a frame along its edges: y down the left edge,
    lines numbered by row, shows how many rows a printer cuts off at the top or bottom (Brother: the medium's
    offset y moves the print); on labels of a given width (Zebra) x across the middle, where nothing is cut off,
    ticks numbered by column, shows the same at the left and right edge (offset x). Lines are a pin thick per
    180 dpi, each starting at its row or column: a single pin of a 360 dpi head prints too faint and broken."""
    key = "calibration"
    name = _("Calibration label")
    subject_type = "printer"
    # Row numbers are print head pins: always standard resolution.
    fixed_resolution = True

    def render(self, printer, canvas, medium, *, preview=False, user=None):
        height = canvas.height
        width = canvas.width or canvas.dots(TAPE_LENGTH_MM + 10)
        step = 10 if height <= 160 else 20
        thick = max(1, round(canvas.dpi / 180))
        image = render.blank(width, height)
        draw = ImageDraw.Draw(image)
        draw.fontmode = "1"
        draw.rectangle((0, 0, width - 1, height - 1), outline=0, width=thick)
        size = max(render.MIN_FONT_PX, min(step * 2 - 2, height // 6))
        loaded = render.font(render.MONO, size, 700)
        small = render.font(render.MONO, max(render.MIN_FONT_PX, size * 3 // 5), 700)
        skip = range(0)  # the rows the x ruler takes
        if canvas.width and height >= 6 * small.size:
            skip = self.x_ruler(draw, width, height, step, thick, small)
        numbers = width // 3 + 4  # where the row numbers start
        for row in range(0, height, step):
            numbered = row % (2 * step) == 0
            if numbered and row:
                box = draw.textbbox((numbers, row), str(row), font=loaded, anchor="lm")
                if any(edge in skip for edge in range(box[1], box[3] + 1)):
                    continue
                draw.text((numbers, row), str(row), font=loaded, fill=0, anchor="lm")
            if row not in skip:
                draw.rectangle((0, row, width // 3 if numbered else width // 6, row + thick - 1), fill=0)
        if skip:  # two rulers: "y" between the first two long lines, beside the short one
            render.text_box(image, (width // 6 + 4, thick + 1, width // 6 - 8, 2 * step - thick - 2), "y",
                            path=render.MONO, weight=700, align="center", valign="middle", max_size=size)
        # The last row, numbered from the bottom edge.
        draw.rectangle((width * 2 // 3, height - thick, width - 1, height - 1), fill=0)
        draw.text((width - 4, height - 3 - thick), str(height - 1), font=loaded, fill=0, anchor="rd")
        return Rendered(image=image, snapshot={"printer": printer.name, "medium": medium.name, "rows": height,
                                               "columns": width if canvas.width else None})

    @staticmethod
    def x_ruler(draw, width, height, step, thick, loaded):
        """Ticks up from a line across the middle: over the first FINE dots (where a shift shows) every 5 columns,
        numbered every 10 in two rows, further on every step columns, numbered as far apart as the numbers need;
        "x" below its start. Returns the rows it takes."""
        size = loaded.size
        fine = render.font(render.MONO, size, 700)
        while fine.size > render.MIN_FONT_PX and render.text_width(fine, str(FINE)) > 17:
            fine = render.font(render.MONO, fine.size - 1, 700)
        digits = draw.textbbox((0, 0), "0", font=fine, anchor="ls")[1] * -1  # height of a number
        low, high = size, size + digits + 4  # tick heights: numbers in the low row, in the high row
        base = height // 2 + (high + digits) // 2
        draw.rectangle((0, base, width - 1, base + thick - 1), fill=0)
        for column in range(0, FINE + 1, 5):
            tall = high if column % 20 == 10 else low if column % 10 == 0 else size // 2
            draw.rectangle((column, base - tall, column + thick - 1, base), fill=0)
            if column % 10 == 0 and column:
                draw.text((column, base - tall - 2), str(column), font=fine, fill=0, anchor="ms")
        numbered = 2 * step
        while render.text_width(loaded, str(width)) + size // 2 > numbered:
            numbered += 2 * step
        for column in range((FINE // step + 1) * step, width, step):
            long = column % (2 * step) == 0
            draw.rectangle((column, base - (size if long else size // 2), column + thick - 1, base), fill=0)
            half = render.text_width(loaded, str(column)) / 2
            if column % numbered == 0 and column - half > FINE + 10 and column + half < width - 4:
                draw.text((column, base - size - 2), str(column), font=loaded, fill=0, anchor="ms")
        letter = draw.textbbox((thick + 3, base + thick + 2), "x", font=loaded, anchor="lt")
        draw.text((thick + 3, base + thick + 2), "x", font=loaded, fill=0, anchor="lt")
        return range(base - high - digits - 2 - step // 2, letter[3] + step // 2)
