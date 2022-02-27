import re
from datetime import datetime, timezone

from crispy_forms.helper import FormHelper
from crispy_forms import layout, bootstrap
from crispy_bootstrap5.bootstrap5 import FloatingField
from django.forms import FileInput, ModelForm, RegexField, Textarea, TextInput
from extra_views import InlineFormSetFactory

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

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.helper = FormHelper()
        self.helper.form_tag = False
        self.helper.disable_csrf = True
        self.helper.layout = layout.Layout(
            "name",
            "description",
            "category",
            layout.Div(
                layout.Div(
                    "measurement_unit",
                    css_class="col"),
                layout.Div(
                    bootstrap.AppendedText("sale_price", '€'),
                    css_class="col"),
                css_class="row"),
        )


class CreateItemForm(ItemForm):
    # TODO use QuaggaJS? https://serratus.github.io/quaggaJS/
    barcode_data = RegexField(
        regex=r"(?:[^\s]+(?:[ \t]+[^\s]*)?\n)*[^\s]+(?:[ \t]+[^\s]*)?\n?",
        widget=Textarea(attrs={"rows": 2}),
        required=False,
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.helper.layout.fields.append(
            bootstrap.FieldWithButtons("barcode_data"))

    def save(self, commit=True):
        # process barcode_data
        instance = super().save(commit=commit)
        if commit:
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
        return instance


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
            "description": TextDatalistInput(options=description_defaults),
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
                css_class='container itemimage_set_item pb-3',
            ),
        )
        return formset


class ItemLocationForm(ModelForm):
    class Meta:
        model = ItemLocation
        fields = "__all__"

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if "location" in self.initial and not "instance" in kwargs:
            self.fields["location"].disabled = True

    def save(self, commit):
        instance = super().save(commit)
        # check if location was marked complete inventory
        if commit and "save_and_mark" in self.data:
            self.instance.location.last_complete_inventory = datetime.now(timezone.utc)
            self.instance.location.save()
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
        # formset.helper.template = 'bootstrap/table_inline_formset.html'
        formset.helper.form_title = "Item Storage Locations"
        formset.helper.layout = layout.Layout(layout.Div(
            FloatingField("location"),
            FloatingField("amount"),
            layout.HTML(
                """
                <span class="input-group-text amount_print_meas_unit mb-2"></span>
                """
            ),
            css_class='input-group item-location-group mb-3'
        ))
        return formset
