from dal import autocomplete
from django import forms
from django.utils.translation import gettext_lazy as _


from ..models import Item, Location
from . import labels
from .services import MAX_BATCH


def _select2(url, placeholder):
    return autocomplete.ModelSelect2(url=url, attrs={
        "data-placeholder": placeholder, "data-allow-clear": 1, "data-width": "100%",
    })


class ClaimItemForm(forms.Form):
    item = forms.ModelChoiceField(
        label=_("Existing item"), queryset=Item.active.all(),
        widget=_select2("zamid_item_autocomplete", _("Search for an item…")),
    )


class ClaimLocationForm(forms.Form):
    location = forms.ModelChoiceField(
        label=_("Existing location"), queryset=Location.active.all(),
        widget=_select2("location-autocomplete", _("Search for a location…")),
    )


class NewItemForm(forms.ModelForm):
    class Meta:
        model = Item
        fields = ["name", "category"]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["name"].required = True


class LabelForm(forms.Form):
    printer = forms.ChoiceField(label=_("Printer"), choices=[(p, f"PT-{p}") for p in labels.PRINTERS])
    tape = forms.TypedChoiceField(
        label=_("Tape width"), coerce=int,
        choices=[(t, f"{t} mm") for t in sorted({tape for _printer, tape in labels.PROFILES})],
    )

    def clean(self):
        data = super().clean()
        if (data.get("printer"), data.get("tape")) not in labels.PROFILES:
            raise forms.ValidationError(_("This printer does not support this tape width."))
        return data


class GenerateForm(forms.Form):
    count = forms.IntegerField(label=_("Number of IDs"), min_value=1, max_value=MAX_BATCH, initial=10)
    batch = forms.CharField(label=_("Batch"), max_length=64, required=False,
                            help_text=_("Name of the label batch or print run."))


class RetireForm(forms.Form):
    note = forms.CharField(label=_("Note"), required=False, widget=forms.Textarea(attrs={"rows": 2}))
