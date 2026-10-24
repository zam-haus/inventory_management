"""
Label templates (inventory's LocationLabelTemplate: a label design in the description language,
label_printing.design) as layouts. A template is designed for a label size and prints only on labels of that
size (fits), on any printer: it is drawn at the printer's resolution. Media offer the fitting active templates;
only those chosen for the medium or its label stock, if there are any of the kind.
"""
import functools

from django.utils.translation import gettext as _

from inventory.models import LocationLabelTemplate
from .. import label_urls
from ..design import Context, TooSmall, check, parse, render_design
from ..design import fields as design_fields
from . import Canvas, LabelTooSmall, Layout, NotRendered, Rendered

SIZE_TOLERANCE_MM = 1


def tape_width(medium):
    """The tape's width in mm (3.5 mm tape is stored as 4)."""
    return 3.5 if medium.ptouch_tape == 4 else medium.ptouch_tape


def close(size, wanted):
    return size is not None and wanted is not None and abs(size - wanted) <= SIZE_TOLERANCE_MM


def fits(template, medium):
    """Whether the template is for labels of the medium's size; a template prints on matching labels only.
    Zebra: labels of its width and height. Brother: tape as wide as its height; endless tape takes any length,
    tape with a label length only templates of that length."""
    if template.label_height is None:
        return False
    if medium.is_tape:
        if medium.ptouch_tape is None or template.label_height not in (medium.ptouch_tape, tape_width(medium)):
            return False
        return medium.height_mm is None or close(template.label_width, medium.height_mm)
    return close(template.label_width, medium.width_mm) and close(template.label_height, medium.height_mm)


# Values of typical length to try a template with: whether its QR code fits on a printer's labels at all
SAMPLES = {
    "location": {"code": "WH-1.R303.a", "qr": "HTTPS://I.ZAM.HAUS/WH-1.R303.A", "name": "Fach a", "path": "R303.a",
                 "purpose": "", "short": "R303.a"},
    "item": {"name": "Artikel", "price": "0,15 € / Stk", "amount": "0,15", "qr": "HTTPS://I.ZAM.HAUS/K7R4XD/WH-1.R303.A",
             "location": "R303.a", "id": "K7R-4XD", "unit": "Stk"},
    "labelid": {"id": "K7R-4XD", "id1": "K7R", "id2": "4XD", "qr": "HTTPS://I.ZAM.HAUS/K7R4XD", "idname": "ZAMid",
                "target": ""},
}


@functools.lru_cache(maxsize=512)
def renders(subject_type, description, dpi, height, width, squeeze):
    """Whether a description can be drawn on a canvas of this size (its QR codes big enough to scan)."""
    design, problems = parse(description)
    if problems or design.height is None:
        return False
    try:
        render_design(design, Context(dpi, SAMPLES.get(subject_type, {}), lambda name: None, squeeze, strict=True),
                      width, height)
    except TooSmall:
        return False
    return True


def drawable(template, medium):
    """Whether the template can be drawn on the medium at its printer's resolution (QR codes big enough)."""
    try:
        canvas = Canvas.for_medium(medium)
    except KeyError:  # tape the printer has no profile for
        return False
    return renders(template.subject_type, template.description, canvas.dpi, canvas.height, canvas.width,
                   canvas.squeeze)


def candidates(medium, subject_type):
    """The active templates a medium may offer for a kind of label: those chosen for it (or its stock), else
    all."""
    chosen = medium.chosen_templates().filter(subject_type=subject_type, is_active=True)
    return chosen if chosen.exists() else LocationLabelTemplate.objects.filter(subject_type=subject_type,
                                                                               is_active=True)


def images():
    """Label images by name for a Context, read once per render."""
    from ..models import LabelImage
    loaded = {}

    def image(name):
        if name not in loaded:
            found = LabelImage.objects.filter(name=name).first()
            try:
                loaded[name] = found.cropped() if found else None
            except (OSError, ValueError):  # a missing file
                loaded[name] = None
        return loaded[name]
    return image


def problems_of(template):
    """Everything wrong with a template's description: syntax, unknown fields and images."""
    from ..models import LabelImage
    design, problems = template.design()
    names = set(LabelImage.objects.filter(name__in=design.images()).values_list("name", flat=True))
    return design, problems + check(design, design_fields.names(template.subject_type), names)


class DesignLayout(Layout):
    def __init__(self, template):
        self.template = template
        self.key = f"design:{template.pk}"
        self.name = template.name
        self.subject_type = template.subject_type
        self.quality = template.quality

    def supports(self, printer, medium):
        """For labels of its size, if chosen for them, and if its QR codes are big enough on the printer."""
        return (printer.language in self.languages and fits(self.template, medium)
                and candidates(medium, self.subject_type).filter(pk=self.template.pk).exists()
                and drawable(self.template, medium))

    def subject_data(self, subject, preview, user):
        """(values, snapshot, code in the QR code)."""
        if self.subject_type == "location":
            return (design_fields.location_values(subject), label_urls.location_snapshot(subject),
                    subject.unique_identifier)
        if self.subject_type == "item":
            code = label_urls.item_label_code(subject, user, create=not preview) or label_urls.PREVIEW_CODE
            return design_fields.item_values(subject, code), label_urls.item_snapshot(subject, code), code
        return design_fields.label_id_values(subject), label_urls.label_id_snapshot(subject), subject.code

    def render(self, subject, canvas, medium, *, preview=False, user=None):
        design, problems = problems_of(self.template)
        if problems:
            raise NotRendered(_("Line %(line)s: %(message)s") % {"line": problems[0].line, "message": problems[0].message})
        values, snapshot, code = self.subject_data(subject, preview, user)
        context = Context(canvas.dpi, values, images(), canvas.squeeze, strict=True)
        try:
            image = render_design(design, context, canvas.width, canvas.height)
        except TooSmall as error:
            raise LabelTooSmall(str(error)) from error
        return Rendered(image=image, snapshot=snapshot, label_code=code)


def template_layouts(subject_type, printer, medium):
    if medium is None or medium.pk is None or printer.language not in DesignLayout.languages:
        return []
    return [DesignLayout(template) for template in candidates(medium, subject_type).order_by("name")
            if fits(template, medium) and drawable(template, medium)]


def template_layout(key):
    try:
        return DesignLayout(LocationLabelTemplate.objects.get(pk=int(key.removeprefix("design:"))))
    except (ValueError, LocationLabelTemplate.DoesNotExist):
        raise ValueError(f"unknown layout {key!r}") from None
