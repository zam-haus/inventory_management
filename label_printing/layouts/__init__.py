"""
Label layouts: what goes on a label of a subject (location, item, the printer itself for a test).

Raster layouts draw a 1-bit image for any printer; ZPL templates of locations (inventory's
LocationLabelTemplate) are offered on the Zebra media they are assigned to.
"""
from dataclasses import dataclass, field

from PIL import Image

from .. import drivers


@dataclass
class Canvas:
    """The printable area in dots; width None is tape, where the layout chooses the length.

    squeeze 2 (Brother high resolution): everything is drawn at twice the resolution and the image is then
    squeezed to half its height (render.squeeze), keeping twice the dots along the tape. Layouts keep QR
    codes intact by placing them at multiples of squeeze (render.align)."""
    dpi: int
    height: int
    width: int | None = None
    squeeze: int = 1

    def dots(self, mm):
        return drivers.mm_to_dots(mm, self.dpi)

    @classmethod
    def for_medium(cls, medium, quality="standard"):
        printer = medium.printer
        if medium.is_tape:
            squeeze = 2 if quality == "high" else 1
            height = drivers.ptouch_print_pins(printer.model, medium.ptouch_tape) * squeeze
            dpi = printer.dpi * squeeze
            length = drivers.mm_to_dots(medium.height_mm, dpi) if medium.height_mm else None
            return cls(dpi, height, length, squeeze)
        return cls(printer.dpi, drivers.mm_to_dots(medium.height_mm, printer.dpi),
                   drivers.mm_to_dots(medium.width_mm, printer.dpi))


@dataclass
class Rendered:
    """One label: an image (raster layouts) or ZPL (templates), and what is on it."""
    image: Image.Image | None = None
    zpl: str | None = None
    snapshot: dict = field(default_factory=dict)
    label_code: str = ""


class LabelTooSmall(ValueError):
    """The content does not fit the label (e.g. no readable QR code)."""


class Layout:
    key = ""
    name = ""
    subject_type = ""
    languages = ("zpl", "ptouch")
    # Drawn pixel-exact for the printer's standard resolution: printed in high quality as standard.
    fixed_resolution = False
    # Height in dots a label needs at least (raster layouts with a QR code: see render.MIN_QR_DOTS).
    min_height = 0

    def supports(self, printer, medium):
        return printer.language in self.languages and Canvas.for_medium(medium).height >= self.min_height

    def render(self, subject, canvas, medium, *, preview=False, user=None):
        """The label for `subject`; a preview must not change anything (e.g. hand out label IDs)."""
        raise NotImplementedError

    def __str__(self):
        return str(self.name)


REGISTRY = {}


def register(cls):
    REGISTRY[cls.key] = cls()
    return cls


def layouts_for(subject_type, printer, medium):
    """The layouts for subjects of this type on this printer and medium, ZPL templates first."""
    layouts = list(template_layouts(subject_type, printer, medium))
    layouts += [layout for layout in REGISTRY.values()
                if layout.subject_type == subject_type and layout.supports(printer, medium)]
    return layouts


def get_layout(key):
    if key.startswith("zpl:"):
        return template_layout(key)
    try:
        return REGISTRY[key]
    except KeyError:
        raise ValueError(f"unknown layout {key!r}") from None


# The layouts register themselves.
from . import item, label_id, location, test_label  # noqa: E402,F401
from .zpl_templates import template_layout, template_layouts  # noqa: E402
