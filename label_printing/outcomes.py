"""
What the print dialog offers: label outcomes instead of printer, labels and layout. An outcome is a layout on labels
of one size, e.g. the template "Preisschild 60x30" on 60 × 30 mm labels, or "QR code, code and path" on 12 mm tape.
The server picks a printer with these labels that can print now (Outcome.target); if none can, a job may wait for
one (services.wait).
"""
from dataclasses import dataclass, field

from django.utils.translation import gettext as _

from inventory.models import LocationLabelTemplate
from . import messages
from .layouts import layouts_for
from .layouts.designs import DesignLayout
from .models import LabelMedium, loaded_text

# How far the label length a Zebra reports may be off a medium's height
LENGTH_TOLERANCE_MM = 2


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
    """Why the medium is not in the printer as it last reported (Brother: the tape's width; Zebra: the labels'
    length), or "" if it is or the printer does not tell."""
    status = printer.last_status or {}
    if medium.is_tape:
        width = status.get("media_width_mm")
        if width and width not in (medium.ptouch_tape, 3.5 if medium.ptouch_tape == 4 else None):
            return str(loaded_text(status))
    else:
        length = status.get("label_length_mm")
        if length and medium.height_mm and abs(length - medium.height_mm) > LENGTH_TOLERANCE_MM:
            return str(loaded_text(status))
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
        """Whether a job may wait for a printer: there are printers with these labels."""
        return bool(self.targets)

    def sample_medium(self):
        """Labels to preview it on: those it would print on, else any it fits."""
        target = self.target() or (self.targets[0] if self.targets else None)
        return target.medium if target else None


def outcomes(subject_type):
    """The outcomes for subjects of this type: label templates (by name), then the built-in layouts."""
    found = {}
    media = (LabelMedium.objects.filter(printer__is_active=True).select_related("printer", "stock")
             .order_by("-printer__is_default", "printer__name", "-is_default", "name"))
    for medium in media:
        reason = unavailable(medium.printer, medium)
        for layout in layouts_for(subject_type, medium.printer, medium):
            key = f"{layout.key}@{size_key(medium)}"
            found.setdefault(key, Outcome(key, layout, size_text(medium))).targets.append(
                Target(medium.printer, medium, reason))
    # Templates for labels no printer has: shown, but neither printable nor able to wait.
    for template in LocationLabelTemplate.objects.filter(subject_type=subject_type):
        key = f"design:{template.pk}"
        if not any(outcome.layout.key == key for outcome in found.values()):
            found[key] = Outcome(key, DesignLayout(template), template.size_text,
                                 reason=_("No printer has labels of this size."))
    return sorted(found.values(), key=lambda outcome: (not outcome.layout.key.startswith("design:"), outcome.name,
                                                       outcome.size))


def find(subject_type, key):
    return next((outcome for outcome in outcomes(subject_type) if outcome.key == key), None)
