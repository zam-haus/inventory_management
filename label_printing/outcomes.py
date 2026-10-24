"""
What the print dialog offers: label outcomes instead of printer, labels and layout. An outcome is a layout on labels
of one size, e.g. the template "Preisschild" on 60 × 30 mm labels, or "QR-Code, Kennung und Ort" on 12 mm tape.
The server picks a printer with these labels that can print now (Outcome.target); if none can, a job may wait for
one (services.wait).
"""
from dataclasses import dataclass, field

from django.utils.translation import gettext as _

from inventory.models import LocationLabelTemplate
from . import messages
from .devices.run import LENGTH_TOLERANCE_MM
from .layouts import layouts_for
from .layouts.designs import DesignLayout
from .models import LabelMedium, Printer, loaded_text



def size_key(medium):
    if medium.is_tape:
        return f"tape{medium.ptouch_tape}" + (f"x{medium.height_mm}" if medium.height_mm else "")
    return f"{medium.width_mm}x{medium.height_mm}"


def size_text(medium):
    if medium.is_tape:
        text = _("%(width)s mm tape") % {"width": "3,5" if medium.ptouch_tape == 4 else medium.ptouch_tape}
        return text + (f", {medium.height_mm} mm" if medium.height_mm else "")
    return _("%(width)s × %(height)s mm labels") % {"width": medium.width_mm, "height": medium.height_mm}


def not_loaded(printer, medium):
    """Why the medium is not in the printer, or "" if it is (or the printer does not tell). Brother: the tape's
    width as it last reported. Zebra: the labels set as loaded in the admin, whose height must match the label
    length the printer measured (their width it cannot tell)."""
    status = printer.last_status or {}
    if medium.is_tape:
        width = status.get("media_width_mm")
        if width and width not in (medium.ptouch_tape, 3.5 if medium.ptouch_tape == 4 else None):
            return str(loaded_text(status))
        return ""
    if printer.loaded_medium_id is None:
        return _("No labels are set as loaded in this printer (admin: its settings).")
    if printer.loaded_medium_id != medium.pk:
        return _("Loaded: %(media)s.") % {"media": printer.loaded_medium.name}
    length = status.get("label_length_mm")
    if length and medium.height_mm and abs(length - medium.height_mm) > LENGTH_TOLERANCE_MM:
        return str(messages.describe("wrong_length", {"measured_mm": length, "expected_mm": medium.height_mm}))
    return ""


def unavailable(printer, medium):
    """Why the printer cannot print on the medium now, or ""."""
    if code := printer.unavailable_code():
        return str(messages.describe(code))
    if errors := (printer.last_status or {}).get("errors"):
        return str(messages.describe(errors[0]))
    return not_loaded(printer, medium)


@dataclass
class Target:
    printer: object
    medium: object
    reason: str  # why it cannot print now; "" if it can


@dataclass
class Outcome:
    key: str
    layout: object
    size: str
    targets: list = field(default_factory=list)  # printers with these labels, the default first
    reason: str = ""  # why there are none
    waits_for_labels: bool = False  # no printer has these labels, but one may get them

    @property
    def name(self):
        return str(self.layout)

    def target(self):
        """The printer and labels to print on now, or None."""
        return next((target for target in self.targets if not target.reason), None)

    @property
    def why_not(self):
        """Why it cannot be printed now, or ""."""
        if self.target():
            return ""
        return self.targets[0].reason if self.targets else self.reason

    @property
    def can_wait(self):
        """Whether a job may wait for a printer: there are printers with these labels, or there are active
        printers and the labels may be loaded into one."""
        return bool(self.targets) or self.waits_for_labels

    def sample_medium(self):
        """Labels to preview it on: those it would print on, else any it fits."""
        target = self.target() or (self.targets[0] if self.targets else None)
        return target.medium if target else None


def outcomes(subject_type):
    """The outcomes for subjects of this type: the active label templates by name and size."""
    found = {}
    media = (LabelMedium.objects.filter(printer__is_active=True).select_related("printer__loaded_medium", "stock")
             .order_by("-printer__is_default", "printer__name", "-is_default", "name"))
    for medium in media:
        reason = unavailable(medium.printer, medium)
        for layout in layouts_for(subject_type, medium.printer, medium):
            key = f"{layout.key}@{size_key(medium)}"
            found.setdefault(key, Outcome(key, layout, size_text(medium))).targets.append(
                Target(medium.printer, medium, reason))
    # Templates for labels no printer has: shown, not printable now; jobs may wait for the labels to be put in
    # (a Zebra: also set as loaded) while there are active printers.
    printers = None
    for template in LocationLabelTemplate.objects.filter(subject_type=subject_type, is_active=True):
        key = f"design:{template.pk}"
        if not any(outcome.layout.key == key for outcome in found.values()):
            if printers is None:
                printers = Printer.objects.filter(is_active=True).exists()
            found[key] = Outcome(key, DesignLayout(template), template.size_text,
                                 reason=_("No printer has labels of this size."), waits_for_labels=printers)
    return sorted(found.values(), key=lambda outcome: (outcome.name, size_order(outcome.layout)))


def size_order(layout):
    """Tape by width, then labels by width and height."""
    template = getattr(layout, "template", None)
    if template is None or template.label_height is None:
        return (2, 0, 0)
    if template.label_width is None:
        return (0, template.label_height, 0)
    return (1, template.label_width, template.label_height)


def find(subject_type, key):
    return next((outcome for outcome in outcomes(subject_type) if outcome.key == key), None)


def waited_for(found, job):
    """The outcome a waiting job waits for, among `found` (by key): its own, or, for a template that no printer
    had labels for when the job was queued, the template on the labels a printer has now (a template has one
    size)."""
    outcome = found.get(job.outcome)
    if outcome is not None and outcome.target():
        return outcome
    return next((other for other in found.values() if other.layout.key == job.layout_key and other.target()),
                outcome)


def preview_template(subject_type):
    """The template that shows a subject's label outside the print dialog (e.g. a label ID's page): the first
    that can be printed now, else the first offered, else the first active one; None if there is none."""
    found = outcomes(subject_type)
    for outcome in [outcome for outcome in found if outcome.target()] + found:
        return outcome.layout.template
    return LocationLabelTemplate.objects.filter(subject_type=subject_type, is_active=True).first()
