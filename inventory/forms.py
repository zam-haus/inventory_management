import re
from datetime import datetime, timezone

from crispy_forms.helper import FormHelper
from crispy_forms.layout import HTML, ButtonHolder, Div, Fieldset, Layout, Submit
from django.core.exceptions import ObjectDoesNotExist
from django.forms import FileInput, ModelForm, RegexField, Textarea, TextInput, Select
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


class CreateItemForm(ModelForm):
    # TODO use QuaggaJS? https://serratus.github.io/quaggaJS/
    barcode_data = RegexField(
        regex=r"(?:[^\s]+(?:[ \t]+[^\s]*)?\n)*[^\s]+(?:[ \t]+[^\s]*)?\n?",
        widget=Textarea(attrs={"rows": 3}),
        required=False,
    )

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
    initial = [{"description": d} for d in description_defaults]
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
        # formset.helper.template = 'bootstrap/table_inline_formset.html'
        return formset


class ItemLocationForm(ModelForm):
    class Meta:
        model = ItemLocation
        fields = "__all__"

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if "location" in self.initial:
            self.fields["location"].disabled = True

    def save(self, commit):
        instance = super().save(commit)
        # check if location was marked finished
        print(self.data)
        print(self.cleaned_data)
        print()
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
        return formset
