import re

from crispy_forms.helper import FormHelper
from crispy_forms import layout, bootstrap
from crispy_bootstrap5.bootstrap5 import FloatingField
from django.core.exceptions import ValidationError
from django.db.models import Q
from django.forms import (
    BooleanField, CharField, FileInput, Form, HiddenInput, IntegerField, ModelChoiceField, ModelForm,
    ModelMultipleChoiceField, RegexField, SelectMultiple, Textarea, TextInput,
)
from django.forms.utils import ErrorList
from extra_views import InlineFormSetFactory
from django.utils.translation import gettext_lazy as _
from django.utils import timezone
from dal import autocomplete


from .models import BarcodeType, Item, ItemBarcode, ItemImage, ItemLocation, Location


class LocationMultipleChoiceField(ModelMultipleChoiceField):
    def clean(self, value):
        # Validate the integer range before the choice field queries the database.
        if isinstance(value, (list, tuple)):
            for pk in value:
                try:
                    Location._meta.pk.clean(pk, None)
                except ValidationError:
                    raise ValidationError(
                        self.error_messages["invalid_pk_value"],
                        code="invalid_pk_value", params={"pk": pk},
                    )
        return super().clean(value)


class PrintableInventoryForm(Form):
    locations = LocationMultipleChoiceField(
        queryset=Location.active.all(),
        label=_("Locations"),
        help_text=_("Select one or more locations."),
        widget=SelectMultiple(attrs={"size": 12}),
    )


class TextDatalistInput(TextInput):
    template_name = "inventory/widgets/text_datalist.html"

    def __init__(self, options, attrs=None):
        super().__init__(attrs)
        self.options = options

    def get_context(self, name, value, attrs):
        context = super().get_context(name, value, attrs)
        context["widget"]["options"] = self.options
        context["widget"]["attrs"]["list"] = (
            context["widget"]["attrs"]["id"] + "_datalist"
        )
        return context


class ItemForm(ModelForm):
    class Meta:
        model = Item
        fields = "__all__"
        exclude = ["is_deleted"]
        widgets = {
            "description": Textarea(attrs={"rows": 3}),
            #'sale_price': TextInput(attrs={'type':'number', 'pattern':'[0-9,\.]*'})
        }

    barcode_data = RegexField(
        regex=r"(?:[^\s]+(?:[ \t]+[^\s]*)?\n)*[^\s]+(?:[ \t]+[^\s]*)?\n?",
        widget=Textarea(attrs={"rows": 2}),
        required=False,
    )

    def __init__(self, data=None, files=None, auto_id='id_%s', prefix=None,
                 initial=None, error_class=ErrorList, label_suffix=None,
                 empty_permitted=False, instance=None, use_required_attribute=None,
                 renderer=None, user=None):
        self.user = user
        # initial barcode_data
        if instance is not None:
            barcode_data_string = ""
            for bc in instance.itembarcode_set.all():
                barcode_data_string += bc.data
                if bc.type is not None:
                    barcode_data_string += " " + bc.type.name
                barcode_data_string += '\n'
            if initial is None:
                initial = {}
            initial['barcode_data'] = barcode_data_string

        super().__init__(data, files, auto_id, prefix,
                         initial, error_class, label_suffix,
                         empty_permitted, instance, use_required_attribute,
                         renderer)

        if user is not None and not any(user.has_perm(f"inventory.{action}_itembarcode") for action in ("add", "delete")):
            self.fields["barcode_data"].disabled = True

        self.helper = FormHelper()
        self.helper.form_tag = False
        self.helper.disable_csrf = True
        self.helper.layout = layout.Layout(
            "name",
            "description",
            layout.Div(
                layout.Div(
                    "measurement_unit",
                    css_class="col"),
                layout.Div(
                    bootstrap.AppendedText("sale_price", '€'),
                    css_class="col"),
                css_class="row"),
            bootstrap.FieldWithButtons("barcode_data")
        )

    def clean_barcode_data(self):
        value = self.cleaned_data["barcode_data"]
        if self.user is None:
            return value
        desired = set()
        for line in value.splitlines():
            parts = line.split()
            if parts:
                desired.add((parts[0], parts[1] if len(parts) == 2 else None))
        existing = set(self.instance.itembarcode_set.values_list("data", "type__name")) if self.instance.pk else set()
        required = set()
        if desired - existing:
            required.add("inventory.add_itembarcode")
        if existing - desired:
            required.add("inventory.delete_itembarcode")
        type_names = {name for _data, name in desired if name is not None}
        if type_names - set(BarcodeType.objects.filter(name__in=type_names).values_list("name", flat=True)):
            required.add("inventory.add_barcodetype")
        if not self.user.has_perms(required):
            raise ValidationError(_("You do not have permission to make these barcode changes."))
        return value

    def save(self, commit=True):
        # process barcode_data
        instance = super().save(commit=commit)
        if commit:
            # Add missing barcodes
            bc_list = []  # list of processed barcodes
            for barcode in self.cleaned_data["barcode_data"].split("\n"):
                barcode = barcode.split()
                if not barcode:
                    continue
                elif len(barcode) == 2:
                    barcode_type = BarcodeType.objects.get_or_create(name=barcode[1])[0]
                else:
                    barcode_type = None
                # get_or_create prevents inserting all entries twice, unclear why it happens
                # otherwise
                ItemBarcode.objects.get_or_create(
                    item=self.instance, data=barcode[0], type=barcode_type
                )
                bc_list.append((barcode[0], barcode_type))
            # Remove any that were not previously processed
            for bc in instance.itembarcode_set.all():
                bc_tuple = (bc.data, bc.type)
                if bc_tuple not in bc_list:
                    bc.delete()
        return instance


class ItemAnnotationForm(ModelForm):
    class Meta:
        model = Item
        fields = ["name", "category", "description", "measurement_unit", "sale_price"]
        widgets = {
            "description": Textarea(attrs={"rows": 3}),
            #'sale_price': TextInput(attrs={'type':'number', 'pattern':'[0-9,\.]*'})
        }
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.helper = FormHelper()
        self.helper.form_title = "Item Storage Locations"
        self.helper.layout = layout.Layout(
            layout.Div(
                layout.Div(
                    FloatingField("name", autofocus=True),
                    css_class='col'),
                layout.Div(
                    FloatingField("category"),
                    css_class='col'),
            css_class='row'),
            "description",
            layout.Div(
                layout.Div(
                    FloatingField("measurement_unit"),
                    css_class='col'),
                layout.Div(
                    FloatingField("sale_price",),
                    css_class='col'),
            css_class='row'),
            layout.Submit("save_next", _("Save and go to next incomplete item"), css_class="btn btn-primary"),
            layout.Submit("save", _("Save"), css_class="btn btn-secondary", ),
        )

class ItemImageInline(InlineFormSetFactory):
    model = ItemImage
    fields = ["description", "image"]
    description_defaults = ["Price label", "Packaged", "Single item (unpacked)"]
    #initial = [{"description": d} for d in description_defaults]
    factory_kwargs = {
        "extra": 3,
        "can_order": False,
        "can_delete": False,
        "widgets": {
            "image": FileInput(attrs={"capture": True}),
            "description": TextDatalistInput(options=description_defaults)
        },
    }

    def construct_formset(self):
        formset = super().construct_formset()
        formset.helper = FormHelper()
        formset.helper.form_tag = False
        formset.helper.disable_csrf = True
        formset.helper.form_title = "Item Photos"
        formset.helper.form_show_labels = False
        formset.helper.layout = layout.Layout(
            layout.Div(
                layout.HTML(
                    """
                    {% load static %}
                    <div class="col-md-5" {% if not formset_form.image.field.disabled %}data-bs-toggle="modal" data-bs-target="#camera_modal"{% endif %}>
                    <img class="img-responsive" width="100%" src=
                    {% if formset_form.image.value %}
                        "{{ MEDIA_URL }}{{ formset_form.image.value }}"
                    {% else %}
                        "{% static 'inventory/placeholder.svg' %}"
                    {% endif %}
                    >
                    </div>
                    """,
                ),
                FloatingField("description"),
                layout.Div(
                    "image",
                    css_class="input-group",
                ),
                css_class='itemimage_set_item mb-3',
            ),
        )
        return formset


class AdminItemLocationForm(ModelForm):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["location"].queryset = Location.active.all()

    class Meta:
        model = ItemLocation
        fields = ('__all__')
        widgets = {
            'location': autocomplete.ModelSelect2(url='location-autocomplete')
        }

class ItemLocationForm(ModelForm):
    class Meta:
        model = ItemLocation
        fields = ['location', 'amount']
        widgets = {
            'location': autocomplete.ModelSelect2(url='location-autocomplete')
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["location"].queryset = Location.active.all()
        if "location" in self.initial and not "instance" in kwargs:
            self.fields["location"].disabled = True

    def save(self, commit=True):  # Add default value for commit
        instance = super().save(commit=commit)  # Pass commit parameter
        return instance

class ItemLocationInline(InlineFormSetFactory):
    model = ItemLocation
    form_class = ItemLocationForm
    factory_kwargs = {
        "extra": 1,
        "can_order": False,
        "can_delete": False,
    }

    def __init__(self, parent_model, request, instance, view_kwargs=None, view=None):
        super().__init__(parent_model, request, instance, view_kwargs, view)
        if "initial" in view_kwargs:
            self.initial = view_kwargs["initial"]

    def construct_formset(self):
        formset = super().construct_formset()
        formset.queryset = formset.queryset.filter(location__is_deleted=False)
        formset.helper = FormHelper()
        formset.helper.form_tag = False
        formset.helper.disable_csrf = True
        formset.helper.include_media = False
        formset.helper.form_title = "Item Storage Locations"
        formset.helper.layout = layout.Layout(
    layout.Div(
        layout.Div(
            bootstrap.Field("location"),
            css_class='col-md-6'),
        layout.Div(
            # change to use FieldWithButtons modified from floating fields
            bootstrap.FieldWithButtons(
                "amount",
                layout.HTML('<span class="amount_print_meas_unit ms-2 text-nowrap"></span>')
            ),
            css_class='col-md-6'
        ),
        css_class='row',
    )
)
        return formset

class AdminLocationForm(ModelForm):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Retain the current parent when inspecting an archived hierarchy.
        self.fields["parent_location"].queryset = Location.objects.filter(
            Q(is_deleted=False) | Q(pk=self.instance.parent_location_id)
        )

    class Meta:
        model = Location
        fields = ('__all__')
        widgets = {
            'parent_location': autocomplete.ModelSelect2(url='parent_location_autocomplete', forward=['id'])
        }

    id = IntegerField(widget=HiddenInput(), required = False)

class DissolveLocationForm(Form):
    def __init__(self, *args, plan, user, **kwargs):
        self.user = user
        super().__init__(*args, **kwargs)
        self.plan = plan
        destinations = Location.active.exclude(pk=plan.root.pk)

        def destination_field(queryset):
            return ModelChoiceField(
                label=_("Destination"), queryset=queryset, required=False,
                widget=autocomplete.ModelSelect2(
                    url="location-autocomplete",
                    attrs={"data-width": "100%", "data-placeholder": _("Search for a location…")},
                ),
            )

        self.fields["bulk_destination"] = destination_field(destinations)
        self.rows = []
        self.can_move_rows = False
        self.can_delete_rows = False
        for row in plan.rows:
            key = row["key"]
            model = "location" if row["kind"] == "location" else "itemlocation"
            can_delete = user.has_perm(f"inventory.delete_{model}")
            can_move = user.has_perm(f"inventory.change_{model}")
            self.can_move_rows |= can_move
            self.can_delete_rows |= can_delete
            self.fields[key + "_delete"] = BooleanField(label=_("Delete"), required=False, disabled=not can_delete)
            if not can_delete:
                self.fields[key + "_delete"].widget.attrs["title"] = _("You do not have permission to delete this entry.")
            queryset = destinations
            if row["kind"] == "location":
                queryset = queryset.exclude(pk=row["object"].pk).filter(type__no_sublocations=False)
            self.fields[key + "_destination"] = destination_field(queryset)
            if not can_move:
                self.fields[key + "_destination"].widget.attrs["data-move-forbidden"] = "true"
                self.fields[key + "_destination"].widget.attrs["title"] = _("You do not have permission to move this entry.")
            if not can_move or (self.is_bound and self[key + "_delete"].value()):
                self.fields[key + "_destination"].disabled = True
            self.rows.append({**row, "delete": self[key + "_delete"], "destination": self[key + "_destination"]})
        self.fields["bulk_destination"].disabled = not self.can_move_rows

    def clean(self):
        cleaned = super().clean()
        operations = []
        for row in self.plan.rows:
            key = row["key"]
            action = "delete" if cleaned.get(key + "_delete") else "move"
            destination = cleaned.get(key + "_destination")
            model = "location" if row["kind"] == "location" else "itemlocation"
            verb = "delete" if action == "delete" else "change"
            if not self.user.has_perm(f"inventory.{verb}_{model}"):
                self.add_error(None, _("You do not have permission for the selected action."))
            if action == "move" and destination is None:
                self.add_error(key + "_destination", _("Choose a destination."))
            operations.append([row["kind"], row["object"].pk, action, destination.pk if destination and action == "move" else None])
        if not self.errors:
            self.plan.validate(operations)
            cleaned["operations"] = operations
        return cleaned


class LocationsMoveHereForm(Form):
    identifiers = CharField(
        label=_("Locations to move here"),
        max_length=20000,
        widget=Textarea(attrs={"rows": 8, "autofocus": True}),
        help_text=_("Enter unique identifiers, locatable identifiers, numeric IDs or /loc URLs. Separate entries with spaces, newlines, tabs or semicolons."),
    )

    def clean_identifiers(self):
        identifiers = [value for value in re.split(r"[\s;]+", self.cleaned_data["identifiers"]) if value]
        if not identifiers:
            raise ValidationError(_("Enter at least one location."))
        return identifiers


class LocationMoveForm(ModelForm):
    class Meta:
        model = Location
        fields = ["parent_location", "id"]

    parent_location = ModelChoiceField(
        label=_("Destination"),
        help_text=_("Search by location name or identifier and select the new parent location."),
        queryset=Location.active.filter(type__no_sublocations = False),
        widget=autocomplete.ModelSelect2(
            url='parent_location_autocomplete',
            forward=['id'],
            attrs={
                'data-placeholder': _("Search for a location…"),
                'data-allow-clear': 1,
                'data-width': '100%',
            },
        ),
        blank=True,
        required=False,
    )

    id = IntegerField(widget=HiddenInput(), required = False)
