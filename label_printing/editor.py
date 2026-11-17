"""
Writing label templates in the admin: the preview, rendered by the server while the description is typed
(static/label_printing/label_template.js), with the problems by line; the variables and sample records of each
kind of label; and the preview of a saved template for one location, item or label ID.
"""
from django.utils.html import format_html_join

from inventory.models import LabelId
from . import drivers
from .design import Context, check, parse, render_labels
from .design import variables as design_variables
from .layouts import Canvas
from .layouts.designs import fits, images
from .models import LabelImage, LabelStock, Medium, Printer
from .render import coloured, stack

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


def preview(description, variables, medium=None):
    """(image or None, [Problem], canvas): the label as the medium's printer would print it (else nominal),
    in the colours of its label stock; drawn as far as it goes despite problems."""
    design, problems = parse(description)
    names = set(LabelImage.objects.filter(name__in=design.images()).values_list("name", flat=True))
    problems += check(design, names)
    if design.height is None:
        return None, problems, None
    canvas = Canvas.for_medium(medium) if medium is not None else nominal_canvas(design)
    width = canvas.width if canvas.width is not None or design.width is None else drivers.mm_to_dots(
        design.width, canvas.dpi)
    context = Context(canvas.dpi, variables, images())
    labels = render_labels(design, context, width, canvas.height)
    problems = sorted(set(problems + context.problems), key=lambda problem: (problem.line, problem.message))
    if medium is not None:
        print_color, background = medium.colours()
        labels = [coloured(image, background, print_color) for image in labels]
    # A list that goes on on further labels: all of them, one below the other
    return stack(labels, canvas.dots(3)), problems, canvas


def public_preview(subject_type, subject):
    """Labels anyone may see: they only show what is on the object anyway."""
    return subject_type in ("location", "uniqueitem") or (
        subject_type == "labelid" and subject.status == LabelId.Status.ASSIGNED)


def may_preview(user, subject_type, subject):
    """Whether the user may see the subject's label (views.template_preview, the admin's samples): public ones,
    the others for who may print (label IDs: or see them)."""
    return (public_preview(subject_type, subject) or user.has_perm("label_printing.print_label")
            or (subject_type == "labelid" and user.has_perm("inventory.view_labelid")))

def active_media():
    """The labels on hand of the active printers, by printer and name."""
    printers = Printer.objects.filter(is_active=True).select_related("loaded_ribbon").order_by("name")
    return [medium for printer in printers for medium in sorted(printer.media(), key=lambda medium: medium.name)]


def medium_key(medium):
    """How a medium (printer and label material) is chosen in a form: "printer:material"."""
    return f"{medium.printer.pk}:{medium.stock.pk}"


def medium_for(key):
    """The medium of a medium_key, or None (also if the printer does not take the material)."""
    printer_pk, _, stock_pk = str(key or "").partition(":")
    if not (printer_pk.isdigit() and stock_pk.isdigit()):
        return None
    printer = Printer.objects.select_related("loaded_ribbon").filter(pk=printer_pk).first()
    stock = LabelStock.objects.filter(pk=stock_pk).first()
    return Medium(printer, stock) if printer and stock and not printer.takes(stock) else None


def fitting_media(template):
    """The labels on hand of active printers the template is for (its size, material and colours)."""
    return [medium for medium in active_media() if fits(template, medium)]


def variable_tables():
    """The variables of each kind of label as tables for the admin; label_template.js shows the chosen kind's."""
    return format_html_join("", '<table data-label-fields="{}"><tbody>{}</tbody></table>', (
        (kind, format_html_join("", "<tr><td><code>{{{{ {} }}}}</code></td><td>{}</td></tr>",
                                ((variable.expression, variable.help)
                                 for variable in variables + design_variables.COMMON)))
        for kind, variables in design_variables.VARIABLES.items()))
