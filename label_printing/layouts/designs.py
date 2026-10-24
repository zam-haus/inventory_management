"""
Label templates (inventory's LocationLabelTemplate: a label design in the description language,
label_printing.design) as layouts. A template is designed for a label size and prints only on labels of that
size (fits), on any printer: it is drawn at the printer's resolution. Media offer the fitting templates; only
those chosen for the medium or its label stock, if there are any of the kind.
"""
from django.utils.translation import gettext as _

from inventory.models import LocationLabelTemplate
from .. import label_urls
from ..design import Context, TooSmall, check, render_design
from ..design import fields as design_fields
from . import LabelTooSmall, Layout, NotRendered, Rendered
from .label_id import snapshot as label_id_snapshot

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


def candidates(medium, subject_type):
    """The templates a medium may offer for a kind of label: those chosen for it (or its stock), else all."""
    chosen = medium.chosen_templates().filter(subject_type=subject_type)
    return chosen if chosen.exists() else LocationLabelTemplate.objects.filter(subject_type=subject_type)


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

    def supports(self, printer, medium):
        return (printer.language in self.languages and fits(self.template, medium)
                and candidates(medium, self.subject_type).filter(pk=self.template.pk).exists())

    def subject_data(self, subject, preview, user):
        """(values, snapshot, code in the QR code)."""
        if self.subject_type == "location":
            return (design_fields.location_values(subject), label_urls.location_snapshot(subject),
                    subject.unique_identifier)
        if self.subject_type == "item":
            code = label_urls.item_label_code(subject, user, create=not preview) or label_urls.PREVIEW_CODE
            return design_fields.item_values(subject, code), label_urls.item_snapshot(subject, code), code
        return design_fields.label_id_values(subject), label_id_snapshot(subject), subject.code

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
            if fits(template, medium)]


def template_layout(key):
    try:
        return DesignLayout(LocationLabelTemplate.objects.get(pk=int(key.removeprefix("design:"))))
    except (ValueError, LocationLabelTemplate.DoesNotExist):
        raise ValueError(f"unknown layout {key!r}") from None
