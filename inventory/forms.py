import re

from crispy_forms.helper import FormHelper
from crispy_forms import layout, bootstrap
from crispy_bootstrap5.bootstrap5 import FloatingField
from django.forms import FileInput, ModelForm, RegexField, Textarea, TextInput, IntegerField, HiddenInput, ModelChoiceField
from django.forms.utils import ErrorList
from extra_views import InlineFormSetFactory
from django.utils.translation import gettext_lazy as _
from django.utils import timezone
from dal import autocomplete


from .models import BarcodeType, Item, ItemBarcode, ItemImage, ItemLocation, Location


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
                 renderer=None):
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
        fields = ["name", "description", "measurement_unit", "sale_price"]
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
                    <div class="col-md-5" data-bs-toggle="modal" data-bs-target="#camera_modal">
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





class ItemLocationForm(ModelForm):
    class Meta:
        model = ItemLocation
        fields = ['location', 'amount']
        widgets = {
            'location': autocomplete.ModelSelect2(url='location-autocomplete')
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
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
    class Meta:
        model = Location
        fields = ('__all__')
        widgets = {
            'parent_location': autocomplete.ModelSelect2(url='parent_location_autocomplete', forward=['id'])
        }

    id = IntegerField(widget=HiddenInput(), required = False)

class LocationMoveForm(ModelForm):
    class Meta:
        model = Location
        fields = ["parent_location", "id"]

    parent_location = ModelChoiceField(
        queryset=Location.objects.filter(type__no_sublocations = False),
        widget=autocomplete.ModelSelect2(
            url='parent_location_autocomplete',
            forward=['id'],
            attrs={
                'data-placeholder': '---------',
                'data-allow-clear': 1,
            },
        ),
        blank=True,
        required=False,
    )

    id = IntegerField(widget=HiddenInput(), required = False)
