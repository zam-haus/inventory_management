"""The print dialog on location, item, unique item and label ID pages: its subjects, options and form.

Kinds of dialog (subject_type): "location", "item", "uniqueitem", "labelid", and "items": price tags for the bulk
items stored at a location. The dialog has a row per label: one for a single subject, else an overview (a location
and its sub-locations, the items at a location), each row with the templates meant for its subject
(selection.py), the best preselected. Each label is printed as a job of its own, those of an overview as a batch.
"""
import uuid

from django import forms
from django.conf import settings
from django.http import Http404
from django.urls import reverse
from django.utils.http import urlencode
from django.utils.translation import gettext, gettext_lazy as _

from inventory.models import Item, LabelId, Location, UniqueItem
from . import label_urls, outcomes, selection
from .label_urls import ItemAt
from .layouts import layouts_for
from .models import LabelMedium

SUBJECT_TYPES = ("location", "item", "uniqueitem", "labelid", "items")


def label_kind(subject_type):
    """The kind of subjects a dialog prints labels for (selection.KINDS)."""
    return "item" if subject_type == "items" else subject_type


def subject_object(subject_type, pk):
    """The location, item, unique item or label ID a dialog prints for (for "items": the location); 404 for
    anything else."""
    if subject_type == "labelid":
        lid = LabelId.objects.filter(pk=str(pk)).first()
        if lid is None:
            raise Http404
        return lid
    if subject_type == "uniqueitem":
        unique_item = (UniqueItem.objects.select_related("item", "location").filter(pk=pk).first()
                       if str(pk).isdigit() else None)
        if unique_item is None or unique_item.is_disposed:
            raise Http404
        return unique_item
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
            "uniqueitem": lambda: str(obj),
            "items": lambda: gettext("Price tags at %(location)s") % {"location": obj.unique_identifier}}.get(
        subject_type, lambda: obj.name)()


def item_locations(item):
    """Where an item is stored, for the location on its labels."""
    return list(Location.active.filter(itemlocation__item=item).distinct().order_by("unique_identifier"))


def sub_locations(location):
    return list(Location.active.filter(parent_location=location).order_by("unique_identifier"))


def items_at(location):
    """The bulk items stored at a location, for their price tags."""
    return [ItemAt(item, location) for item in Item.active.filter(
        kind=Item.Kind.BULK, itemlocation__location=location).distinct().select_related(
        "measurement_unit").order_by("name")]


def priced(subject):
    """Whether an item at a location is for sale with a price."""
    return bool(subject.item.for_sale and subject.item.sale_price is not None)


def subjects(subject_type, obj, children=False):
    """The subjects of the dialog's rows: the subject, a location with its sub-locations, the items at a location."""
    if subject_type == "items":
        return items_at(obj)
    if subject_type == "item":
        locations = item_locations(obj)
        return [ItemAt(obj, locations[0] if locations else None)]
    if subject_type == "location" and children:
        return [obj] + sub_locations(obj)
    return [obj]


def dialog_outcomes(subject_type):
    """The outcomes of every kind of template the dialog's subjects may have (unique items: also label IDs)."""
    return [outcome for kind in selection.KINDS[label_kind(subject_type)] for outcome in outcomes.outcomes(kind)]


def subject_name(subject):
    if isinstance(subject, Location):
        return f"{subject.unique_identifier} {subject.name}"
    if isinstance(subject, ItemAt):
        price = label_urls.price_text(subject.item)
        return f"{subject.item.name} ({price})" if price else subject.item.name
    return str(subject)


def subject_pk(subject):
    return subject.item.pk if isinstance(subject, ItemAt) else subject.pk


def preview_urls(subject_type, subject):
    """(The print preview of the subject on a medium, without the medium and layout; the preview without
    printer, with {template} for the template's number)."""
    kind = label_kind(subject_type)
    query = (f"?{urlencode({'location': subject.location.pk})}"
             if isinstance(subject, ItemAt) and subject.location else "")
    on_medium = reverse("print_preview", args=[kind, subject_pk(subject)]) + query
    without = reverse("label_template_preview", args=[0, kind, subject_pk(subject)]).replace("/0/", "/{template}/", 1)
    return on_medium, without + query


def row(subject_type, subject, found):
    """A row of the dialog: its subject, the outcomes meant for it ([key, priority, shown], the preselected first)."""
    ranked = selection.rank(found, label_kind(subject_type), subject)
    on_medium, without = preview_urls(subject_type, subject)
    return {"name": subject_name(subject), "pk": str(subject_pk(subject)),
            "outcomes": [[entry.outcome.key, entry.priority, entry.shown] for entry in ranked],
            "chosen": ranked[0].outcome.key if ranked else "", "preview": on_medium, "template_preview": without,
            "priced": priced(subject) if isinstance(subject, ItemAt) else None}


def preview_url(row_data, outcome):
    """The preview of a row's subject with an outcome: as the printer gets it, else without a printer."""
    if outcome["query"]:
        return f"{row_data['preview']}{'&' if '?' in row_data['preview'] else '?'}{outcome['query']}"
    return row_data["template_preview"].replace("{template}", str(outcome["template"]))


def choice_label(outcome):
    """An outcome as an option of an overview's row: name, size, and the printer or why it waits."""
    return f"{outcome['name']} · {outcome['size']} · {outcome['printer'] or outcome['reason']}"


def presented(data):
    """The cards of a single subject and the choices of an overview's rows, ready for the template."""
    by_key = {outcome["key"]: outcome for outcome in data["outcomes"]}
    for row_data in data["rows"]:
        row_data["choices"] = [{"key": key, "label": choice_label(by_key[key]), "shown": shown,
                                "chosen": key == row_data["chosen"]} for key, _priority, shown in row_data["outcomes"]]
        row_data["image"] = preview_url(row_data, by_key[row_data["chosen"]]) if row_data["chosen"] else ""
        row_data["more"] = any(not choice["shown"] for choice in row_data["choices"])
    first = data["rows"][0] if data["rows"] else None
    data["cards"] = [{**by_key[key], "shown": shown, "chosen": key == first["chosen"],
                      "preview": preview_url(first, by_key[key])}
                     for key, _priority, shown in (first["outcomes"] if first else [])]
    data["more"] = sum(1 for card in data["cards"] if not card["shown"])
    return data


def options(subject_type, obj):
    """What the dialog offers: every label outcome (outcomes.py) with whether it can be printed now (on which
    printer, else why not) and whether a job may wait for a printer; and the rows, a row per label (for a
    location also its sub-locations, printed on request)."""
    found = dialog_outcomes(subject_type)
    data = {"outcomes": [{"key": outcome.key, "name": outcome.name, "size": outcome.size,
                          "printer": str(target.printer) if (target := outcome.target()) else "",
                          "reason": outcome.why_not, "can_wait": outcome.can_wait,
                          "template": outcome.layout.template.pk,
                          "query": urlencode({"medium": medium.pk, "layout": outcome.layout.key})
                          if (medium := outcome.sample_medium()) else ""}
                         for outcome in found],
            "rows": [row(subject_type, subject, found)
                     for subject in subjects(subject_type, obj, children=subject_type == "location")],
            "max_copies": settings.PRINT_MAX_COPIES, "wait_minutes": settings.PRINT_WAIT_MAX // 60,
            "submit_url": reverse("print_labels", args=[subject_type, obj.pk]),
            "status_url": reverse("print_job_status", args=[0]),
            "batch_url": reverse("print_batch_status", args=[uuid.UUID(int=0)])}
    if subject_type == "item":
        # Where the QR code leads: the item's label ID (given out when first printed) with the location
        data["item"] = obj.name
        data["locations"] = [{"id": location.pk, "code": location.unique_identifier, "name": location.name}
                             for location in item_locations(obj)]
        code = label_urls.item_label_code(ItemAt(obj, None), create=False)
        data["label_id"] = label_urls.display(code) if code else ""
    elif subject_type == "location":
        data["children"] = len(data["rows"]) - 1
    elif subject_type == "items":
        data["priced"] = sum(1 for entry in data["rows"] if entry["priced"])
    return presented(data)


def unavailable_reason(subject_type, data):
    """Why the print button is disabled, or "": labels can be printed now or wait for a printer."""
    if subject_type == "items" and not data["rows"]:
        return gettext("No bulk items are stored here.")
    keys = {key for entry in (data["rows"] if subject_type == "items" else data["rows"][:1])
            for key, _priority, _shown in entry["outcomes"]}
    if not keys:
        return gettext("No label template is meant for this.")
    if not any(item["printer"] or item["can_wait"] for item in data["outcomes"] if item["key"] in keys):
        return gettext("No printer is set up for these labels yet.")
    return ""


class PrintForm(forms.Form):
    """One label (outcome) for the subject, or in an overview a row per subject: row-<n>-print, row-<n>-outcome."""
    outcome = forms.CharField(label=_("Label"), max_length=96, required=False)
    copies = forms.IntegerField(label=_("Copies"), min_value=1, initial=1)
    location = forms.ModelChoiceField(Location.active.all(), label=_("Location"), required=False)
    children = forms.BooleanField(label=_("Also the sub-locations"), required=False)
    request_id = forms.UUIDField(required=False, widget=forms.HiddenInput)

    def __init__(self, *args, subject_type, obj, **kwargs):
        super().__init__(*args, **kwargs)
        self.subject_type, self.obj = subject_type, obj
        self.chosen = []  # [(outcome, subject)], in the rows' order
        self.fields["copies"].widget.attrs["max"] = settings.PRINT_MAX_COPIES
        if subject_type == "item":
            self.fields["location"].queryset = Location.active.filter(itemlocation__item=obj).distinct()
        else:
            del self.fields["location"]
        if subject_type != "location":
            del self.fields["children"]

    @property
    def overview(self):
        """Whether the form has a row per subject."""
        return self.subject_type == "items" or bool(self.data.get("children"))

    def clean_copies(self):
        copies = self.cleaned_data["copies"]
        if copies > settings.PRINT_MAX_COPIES:
            raise forms.ValidationError(_("At most %(max)d copies.") % {"max": settings.PRINT_MAX_COPIES})
        return copies

    def wanted(self):
        """[(row, subject, outcome key)] to print."""
        if self.subject_type == "item":
            return [(0, ItemAt(self.obj, self.cleaned_data.get("location")), self.cleaned_data.get("outcome", ""))]
        rows = subjects(self.subject_type, self.obj, children=self.overview)
        if not self.overview:
            return [(0, rows[0], self.cleaned_data.get("outcome", ""))]
        return [(index, subject, self.data.get(f"row-{index}-outcome", "")) for index, subject in enumerate(rows)
                if self.data.get(f"row-{index}-print")]

    def clean(self):
        data = super().clean()
        wanted = self.wanted()
        if not wanted:
            self.add_error(None, _("There is nothing to print."))
            return data
        found = {outcome.key: outcome for outcome in dialog_outcomes(self.subject_type)}
        kind = label_kind(self.subject_type)
        for _index, subject, key in wanted:
            outcome = found.get(key)
            if outcome is None or outcome.layout.template.pk not in selection.priorities(
                    kind, subject, [outcome.layout.template]):
                problem = _("These labels cannot be printed here.")
            elif not outcome.target() and not outcome.can_wait:  # else it waits for a printer
                problem = outcome.why_not
            else:
                self.chosen.append((outcome, subject))
                continue
            if self.overview:
                self.add_error(None, f"{subject_name(subject)}: {problem}")
            else:
                self.add_error("outcome", problem)
        return data

    def jobs(self, user):
        """[(outcome, the subject its template draws, request ID)]: a job per label, in the rows' order. A unique
        item printed with a label ID template gets its label ID now if it has none yet."""
        request_id = self.cleaned_data.get("request_id")
        found = []
        for index, (outcome, subject) in enumerate(self.chosen):
            if outcome.layout.subject_type == "labelid" and isinstance(subject, UniqueItem):
                subject = LabelId.objects.get(code=label_urls.unique_item_label_code(subject, user))
            found.append((outcome, subject,
                          uuid.uuid5(request_id, str(index)) if request_id and self.overview else request_id))
        return found


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
