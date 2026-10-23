"""A short test label naming printer and time, printed from the printer admin."""
from django.utils import timezone
from django.utils.formats import time_format
from django.utils.translation import gettext, gettext_lazy as _

from PIL import ImageDraw

from .. import render
from . import Layout, Rendered, register

# On tape the test label is this long, whatever the names: tape is not to be wasted on tests.
TAPE_LENGTH_MM = 30


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
    """Lines across the whole print area, numbered by row, with a frame along its edges: shows how many rows
    a printer cuts off at the top or bottom (Brother: the medium's offset y moves the print)."""
    key = "calibration"
    name = _("Calibration label")
    subject_type = "printer"
    # Row numbers are print head pins: always standard resolution.
    fixed_resolution = True

    def render(self, printer, canvas, medium, *, preview=False, user=None):
        height = canvas.height
        width = canvas.width or canvas.dots(TAPE_LENGTH_MM + 10)
        step = 10 if height <= 160 else 20
        image = render.blank(width, height)
        draw = ImageDraw.Draw(image)
        draw.rectangle((0, 0, width - 1, height - 1), outline=0)
        loaded = render.font(render.MONO, max(render.MIN_FONT_PX, min(step * 2 - 2, height // 6)), 700)
        for row in range(0, height, step):
            draw.line((0, row, width // 6 if row % (2 * step) else width // 3, row), fill=0)
            if row % (2 * step) == 0 and row:
                draw.fontmode = "1"
                draw.text((width // 3 + 4, row), str(row), font=loaded, fill=0, anchor="lm")
        # The last row, numbered from the bottom edge.
        draw.line((width * 2 // 3, height - 1, width - 1, height - 1), fill=0)
        draw.text((width - 4, height - 3), str(height - 1), font=loaded, fill=0, anchor="rd")
        return Rendered(image=image, snapshot={"printer": printer.name, "medium": medium.name, "rows": height})
