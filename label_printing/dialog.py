"""The print dialog on location and item pages: its subjects, options and form."""
from django import forms
from django.conf import settings
from django.http import Http404
from django.urls import reverse
from django.utils.translation import gettext, gettext_lazy as _

from inventory.models import Item, LabelId, Location
from . import messages
from .label_urls import ItemAt
from .layouts import layouts_for
from .models import LabelMedium, Printer, Quality

SUBJECT_TYPES = ("location", "item", "labelid")


def subject_object(subject_type, pk):
    """The location, item or label ID a dialog prints for; 404 for anything else."""
    if subject_type == "labelid":
        lid = LabelId.objects.filter(pk=str(pk)).first()
        if lid is None:
            raise Http404
        return lid
    model = {"location": Location, "item": Item}.get(subject_type)
    if model is None:
        raise Http404
    try:
        return model.active.get(pk=pk)
    except (model.DoesNotExist, ValueError):
        raise Http404 from None


def title(subject_type, obj):
    """How the dialog names what it prints."""
    return {"location": lambda: obj.unique_identifier, "labelid": lambda: obj.display}.get(
        subject_type, lambda: obj.name)()


def item_locations(item):
    """Where an item is stored, for the location on its labels."""
    return list(Location.active.filter(itemlocation__item=item).distinct().order_by("unique_identifier"))


def sub_locations(location):
    return list(Location.active.filter(parent_location=location).order_by("unique_identifier"))


def options(subject_type, obj):
    """What the dialog offers: printers with their media and layouts (unavailable printers with the reason)."""
    printers = []
    for printer in Printer.objects.filter(is_active=True).prefetch_related("media__stock").order_by("name"):
        media = []
        for medium in printer.media.all():
            layouts = layouts_for(subject_type, printer, medium)
            if layouts:
                media.append({"id": medium.pk, "name": medium.name, "default": medium.is_default,
                              "tape": medium.ptouch_tape, "detail": medium_detail(medium), "quality": medium.quality,
                              "colors": [medium.stock.print_color, medium.stock.background_color]
                              if medium.stock else None,
                              "layouts": [{"key": layout.key, "name": str(layout)} for layout in layouts]})
        if media:
            printers.append({"id": printer.pk, "name": printer.name, "default": printer.is_default,
                             "unavailable": printer.unavailable_reason(), "status": str(printer.status_text),
                             "tape": (printer.last_status or {}).get("media_width_mm"),
                             "colors": [(printer.last_status or {}).get("text_color"),
                                        (printer.last_status or {}).get("tape_color")], "media": media})
    data = {"printers": printers, "max_copies": settings.PRINT_MAX_COPIES,
            "submit_url": reverse("print_labels", args=[subject_type, obj.pk]),
            "preview_url": reverse("print_preview", args=[subject_type, obj.pk]),
            "status_url": reverse("print_job_status", args=[0])}
    if subject_type == "item":
        data["locations"] = [{"id": location.pk, "code": location.unique_identifier, "name": location.name}
                             for location in item_locations(obj)]
    elif subject_type == "location":
        data["children"] = len(sub_locations(obj))
    return data


def medium_detail(medium):
    """What else to know about the labels: printing method and material (Zebra), or the tape kind (Brother)."""
    stock = medium.stock
    if stock is None:
        return ""
    if stock.language == Printer.Language.PTOUCH:
        return stock.description_short
    return ", ".join(part for part in (stock.method_text, stock.material) if part)


def unavailable_reason(data):
    """Why the print button is disabled, or ""."""
    if not data["printers"]:
        return gettext("No printer is set up for these labels yet.")
    if all(printer["unavailable"] for printer in data["printers"]):
        return gettext("No printer can print right now: %(reason)s") % {"reason": data["printers"][0]["unavailable"]}
    return ""


class PrintForm(forms.Form):
    printer = forms.ModelChoiceField(Printer.objects.filter(is_active=True), label=_("Printer"))
    medium = forms.ModelChoiceField(LabelMedium.objects.select_related("printer"), label=_("Labels"))
    layout = forms.CharField(label=_("Layout"), max_length=64)
    copies = forms.IntegerField(label=_("Copies"), min_value=1, initial=1)
    quality = forms.ChoiceField(label=_("Print quality"), choices=Quality.choices, required=False)
    location = forms.ModelChoiceField(Location.active.all(), label=_("Location"), required=False)
    children = forms.BooleanField(label=_("Also the sub-locations"), required=False)
    request_id = forms.UUIDField(required=False, widget=forms.HiddenInput)

    def __init__(self, *args, subject_type, obj, **kwargs):
        super().__init__(*args, **kwargs)
        self.subject_type, self.obj = subject_type, obj
        self.fields["copies"].widget.attrs["max"] = settings.PRINT_MAX_COPIES
        if subject_type == "item":
            self.fields["location"].queryset = Location.active.filter(itemlocation__item=obj).distinct()
            del self.fields["children"]
        elif subject_type == "location":
            del self.fields["location"]
        else:
            del self.fields["location"], self.fields["children"]

    def clean_copies(self):
        copies = self.cleaned_data["copies"]
        if copies > settings.PRINT_MAX_COPIES:
            raise forms.ValidationError(_("At most %(max)d copies.") % {"max": settings.PRINT_MAX_COPIES})
        return copies

    def clean(self):
        data = super().clean()
        printer, medium = data.get("printer"), data.get("medium")
        if printer and medium and medium.printer_id != printer.pk:
            self.add_error("medium", _("Choose labels of this printer."))
        elif printer and medium and data.get("layout") not in {
                layout.key for layout in layouts_for(self.subject_type, printer, medium)}:
            self.add_error("layout", _("This layout does not fit the chosen labels."))
        if printer and (code := printer.unavailable_code()):
            self.add_error("printer", messages.describe(code))
        return data

    def subjects(self):
        if self.subject_type == "item":
            return [ItemAt(self.obj, self.cleaned_data.get("location"))]
        if self.subject_type == "labelid":
            return [self.obj]
        return [self.obj] + (sub_locations(self.obj) if self.cleaned_data.get("children") else [])


def label_id_media():
    """Media of active printers that a label ID layout fits, best layout first per medium."""
    media = []
    for medium in LabelMedium.objects.filter(printer__is_active=True).select_related("printer", "stock"):
        if layouts_for("labelid", medium.printer, medium):
            media.append(medium.pk)
    return LabelMedium.objects.filter(pk__in=media).select_related("printer").order_by("printer__name", "name")


class LabelIdPrintForm(forms.Form):
    """Printing label IDs in the admin: where, and how often."""
    medium = forms.ModelChoiceField(LabelMedium.objects.none(), label=_("Printer and labels"))
    copies = forms.IntegerField(label=_("Copies"), min_value=1, initial=1)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["medium"].queryset = label_id_media()
        self.fields["medium"].label_from_instance = lambda medium: f"{medium.printer}: {medium.name}"

    def clean_copies(self):
        copies = self.cleaned_data["copies"]
        if copies > settings.PRINT_MAX_COPIES:
            raise forms.ValidationError(_("At most %(max)d copies.") % {"max": settings.PRINT_MAX_COPIES})
        return copies
