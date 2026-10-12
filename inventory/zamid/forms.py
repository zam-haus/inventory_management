from django import forms
from django.utils.translation import gettext_lazy as _


from ..forms import ItemOrNewField, NewItemAlongsideMixin
from ..models import Item, Location, UniqueItem
from ..widgets import AutocompleteSelect, ItemOrNewSelect
from . import labels
from .services import MAX_BATCH


def _select2(url, placeholder):
    return AutocompleteSelect(url=url, attrs={"data-placeholder": placeholder, "data-allow-clear": 1})


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


class ClaimUniqueItemForm(forms.Form):
    """Only unique items whose ID was retired can get a new label."""
    unique_item = forms.ModelChoiceField(
        label=_("Unique item without an ID"), queryset=UniqueItem.active.all(),
        widget=_select2("unique_item_without_id_autocomplete", _("Search for a unique item…")),
    )


class NewUniqueItemForm(NewItemAlongsideMixin, forms.ModelForm):
    """The item can also be a new one, created together with the unique item."""

    class Meta:
        model = UniqueItem
        fields = ["item", "location"]
        field_classes = {"item": ItemOrNewField}
        widgets = {
            "item": ItemOrNewSelect(url="unique_kind_item_autocomplete",
                                    attrs={"data-placeholder": _("Search for an item with unique items…"), "data-allow-clear": 1}),
            "location": _select2("location-autocomplete", _("Search for a location…")),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["item"].queryset = Item.active.filter(kind=Item.Kind.UNIQUE)
        self.fields["location"].queryset = Location.active.all()
        self.fields["location"].required = True


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
