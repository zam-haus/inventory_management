"""
Writing label templates in the admin: the preview, rendered by the server while the description is typed
(static/label_printing/label_template.js), with the problems by line; the fields and sample records of each
kind of label; and the preview of a saved template for one location, item or label ID.
"""
from django.utils.html import format_html_join

from . import drivers
from .design import Context, check, parse, render_design
from .design import fields as design_fields
from .layouts import Canvas
from .layouts.designs import fits, images
from .models import LabelImage, LabelMedium
from .render import coloured

# Without a printer: Zebra labels at 203 dpi, Brother tape as a P900 prints it (360 dpi).
NOMINAL_DPI = 203
NOMINAL_TAPE_PRINTER = "P900W"


def nominal_canvas(design):
    """Canvas (dpi, height, width) for a design without a printer."""
    if design.width is None:
        dpi = drivers.ptouch_dpi(NOMINAL_TAPE_PRINTER)
        try:
            height = drivers.ptouch_print_pins(NOMINAL_TAPE_PRINTER, int(design.height))
        except (KeyError, ValueError):
            height = drivers.mm_to_dots(design.height, dpi)
        return Canvas(dpi, height, None)
    return Canvas(NOMINAL_DPI, drivers.mm_to_dots(design.height, NOMINAL_DPI),
                  drivers.mm_to_dots(design.width, NOMINAL_DPI))


def preview(description, subject_type, values, medium=None):
    """(image or None, [Problem], canvas): the label as the medium's printer would print it (else nominal),
    in the colours of its label stock; drawn as far as it goes despite problems."""
    design, problems = parse(description)
    names = set(LabelImage.objects.filter(name__in=design.images()).values_list("name", flat=True))
    problems += check(design, design_fields.names(subject_type), names)
    if design.height is None:
        return None, problems, None
    canvas = Canvas.for_medium(medium) if medium is not None else nominal_canvas(design)
    width = canvas.width if canvas.width is not None or design.width is None else drivers.mm_to_dots(
        design.width, canvas.dpi)
    context = Context(canvas.dpi, values, images())
    image = render_design(design, context, width, canvas.height)
    problems = sorted(set(problems + context.problems), key=lambda problem: (problem.line, problem.message))
    if medium is not None and medium.stock is not None:
        image = coloured(image, medium.stock.background_color, medium.stock.print_color)
    return image, problems, canvas


def fitting_media(template):
    """Media of active printers with labels of the template's size."""
    return [medium for medium in LabelMedium.objects.filter(printer__is_active=True).select_related("printer", "stock")
            .order_by("printer__name", "name") if fits(template, medium)]


def field_tables():
    """The fields of each kind of label as tables for the admin; label_template.js shows the chosen kind's."""
    return format_html_join("", '<table data-label-fields="{}"><tbody>{}</tbody></table>', (
        (kind, format_html_join("", "<tr><td><code>{{{}}}</code></td><td>{}</td></tr>",
                                ((field.name, field.help) for field in fields)))
        for kind, fields in design_fields.FIELDS.items()))
