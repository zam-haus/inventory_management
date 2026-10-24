"""The print dialog on location and item pages: its subjects, options and form.

Kinds of dialog (subject_type): "location", "item", "labelid", and "items": price tags for the bulk items stored
at a location (labels of kind "item", one per item)."""
from django import forms
from django.conf import settings
from django.http import Http404
from django.urls import reverse
from django.utils.http import urlencode
from django.utils.translation import gettext, gettext_lazy as _

from inventory.models import Item, LabelId, Location
from . import label_urls, outcomes
from .label_urls import ItemAt
from .layouts import layouts_for
from .models import LabelMedium

SUBJECT_TYPES = ("location", "item", "labelid", "items")


def label_kind(subject_type):
    """The kind of labels (templates) a dialog prints."""
    return "item" if subject_type == "items" else subject_type


def subject_object(subject_type, pk):
    """The location, item or label ID a dialog prints for (for "items": the location); 404 for anything else."""
    if subject_type == "labelid":
        lid = LabelId.objects.filter(pk=str(pk)).first()
        if lid is None:
            raise Http404
        return lid
    model = {"location": Location, "item": Item, "items": Location}.get(subject_type)
    if model is None:
        raise Http404
    try:
        return model.active.get(pk=pk)
    except (model.DoesNotExist, ValueError):
        raise Http404 from None


def title(subject_type, obj):
    """How the dialog names what it prints."""
    return {"location": lambda: obj.unique_identifier, "labelid": lambda: obj.display,
            "items": lambda: gettext("Price tags at %(location)s") % {"location": obj.unique_identifier}}.get(
        subject_type, lambda: obj.name)()


def item_locations(item):
    """Where an item is stored, for the location on its labels."""
    return list(Location.active.filter(itemlocation__item=item).distinct().order_by("unique_identifier"))


def sub_locations(location):
    return list(Location.active.filter(parent_location=location).order_by("unique_identifier"))


def sample_item(location):
    """The price tag to preview: of the first item for sale with a price, else of the first item; or None."""
    return next(iter(items_at(location, priced=True) or items_at(location)), None)


def items_at(location, priced=False):
    """The bulk items stored at a location, for their price tags; priced: only those for sale with a price."""
    items = Item.active.filter(kind=Item.Kind.BULK, itemlocation__location=location)
    if priced:
        items = items.filter(for_sale=True, sale_price__isnull=False)
    return [ItemAt(item, location) for item in items.distinct().select_related("measurement_unit").order_by("name")]


def options(subject_type, obj):
    """What the dialog offers: label outcomes (outcomes.py) with their preview, whether they can be printed now
    (on which printer, else why not) and whether a job may wait for a printer."""
    preview_url = reverse("print_preview", args=[subject_type, obj.pk])
    kind = label_kind(subject_type)
    stored = items_at(obj) if subject_type == "items" else None
    items = []
    for outcome in outcomes.outcomes(kind) if stored is None or stored else []:
        target, medium = outcome.target(), outcome.sample_medium()
        if medium is not None:
            preview = f"{preview_url}?{urlencode({'medium': medium.pk, 'layout': outcome.layout.key})}"
        else:  # a template for labels no printer has: drawn without a printer
            preview = reverse("label_template_preview", args=[outcome.layout.template.pk, kind,
                                                              sample_item(obj).item.pk if stored else obj.pk])
        items.append({"key": outcome.key, "name": outcome.name, "size": outcome.size,
                      "printer": str(target.printer) if target else "", "reason": outcome.why_not,
                      "can_wait": outcome.can_wait, "preview": preview})
    data = {"outcomes": items, "max_copies": settings.PRINT_MAX_COPIES, "wait_minutes": settings.PRINT_WAIT_MAX // 60,
            "confirm_labels": settings.PRINT_CONFIRM_LABELS, "max_labels": settings.PRINT_MAX_LABELS, "labels": 1,
            "submit_url": reverse("print_labels", args=[subject_type, obj.pk]),
            "status_url": reverse("print_job_status", args=[0])}
    if subject_type == "item":
        # Where the QR code leads: the item's label ID (given out when first printed) with the location
        data["item"] = obj.name
        data["locations"] = [{"id": location.pk, "code": location.unique_identifier, "name": location.name}
                             for location in item_locations(obj)]
        code = label_urls.item_label_code(ItemAt(obj, None), create=False)
        data["label_id"] = label_urls.display(code) if code else ""
    elif subject_type == "location":
        data["children"] = len(sub_locations(obj))
    elif subject_type == "items":
        data["labels"] = data["items"] = len(stored)
        data["priced"] = len(items_at(obj, priced=True))
    return data


def unavailable_reason(data):
    """Why the print button is disabled, or "": labels can be printed now or wait for a printer."""
    if data.get("items") == 0:
        return gettext("No bulk items are stored here.")
    if not any(item["printer"] or item["can_wait"] for item in data["outcomes"]):
        return gettext("No printer is set up for these labels yet.")
    return ""


class PrintForm(forms.Form):
    outcome = forms.CharField(label=_("Label"), max_length=96)
    copies = forms.IntegerField(label=_("Copies"), min_value=1, initial=1)
    location = forms.ModelChoiceField(Location.active.all(), label=_("Location"), required=False)
    children = forms.BooleanField(label=_("Also the sub-locations"), required=False)
    priced = forms.BooleanField(label=_("Only items with a sale price"), required=False)
    confirm = forms.BooleanField(required=False)  # more than PRINT_CONFIRM_LABELS labels
    request_id = forms.UUIDField(required=False, widget=forms.HiddenInput)

    def __init__(self, *args, subject_type, obj, **kwargs):
        super().__init__(*args, **kwargs)
        self.subject_type, self.obj = subject_type, obj
        self.chosen = None
        self.fields["copies"].widget.attrs["max"] = settings.PRINT_MAX_COPIES
        if subject_type == "item":
            self.fields["location"].queryset = Location.active.filter(itemlocation__item=obj).distinct()
            del self.fields["children"]
        elif subject_type == "location":
            del self.fields["location"]
        else:
            del self.fields["location"], self.fields["children"]
        if subject_type != "items":
            del self.fields["priced"]

    def clean_copies(self):
        copies = self.cleaned_data["copies"]
        if copies > settings.PRINT_MAX_COPIES:
            raise forms.ValidationError(_("At most %(max)d copies.") % {"max": settings.PRINT_MAX_COPIES})
        return copies

    def clean(self):
        data = super().clean()
        if not data.get("outcome"):
            return data
        self.chosen = outcomes.find(label_kind(self.subject_type), data["outcome"])
        if self.chosen is None:
            self.add_error("outcome", _("These labels cannot be printed here."))
        elif not self.chosen.target() and not self.chosen.can_wait:  # else it waits for a printer
            self.add_error("outcome", self.chosen.why_not)
        if data.get("copies") and not self.errors:
            self.check_count(len(self.subjects()) * data["copies"])
        return data

    def check_count(self, labels):
        """Many labels at once are probably a mistake: more than PRINT_CONFIRM_LABELS must be confirmed, more
        than PRINT_MAX_LABELS are refused."""
        if not labels:
            self.add_error(None, _("There is nothing to print."))
        elif labels > settings.PRINT_MAX_LABELS:
            self.add_error("copies", _("That would be %(labels)d labels; at most %(max)d can be printed at once.")
                           % {"labels": labels, "max": settings.PRINT_MAX_LABELS})
        elif labels > settings.PRINT_CONFIRM_LABELS and not self.cleaned_data.get("confirm"):
            self.add_error("confirm", forms.ValidationError(
                _("That is %(labels)d labels. Print them all?") % {"labels": labels}, code="confirm"))

    def subjects(self):
        if self.subject_type == "item":
            return [ItemAt(self.obj, self.cleaned_data.get("location"))]
        if self.subject_type == "labelid":
            return [self.obj]
        if self.subject_type == "items":
            return items_at(self.obj, priced=self.cleaned_data.get("priced"))
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
