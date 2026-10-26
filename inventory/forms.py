
from crispy_forms.helper import FormHelper
from crispy_forms import layout, bootstrap
from crispy_bootstrap5.bootstrap5 import FloatingField
from django.core.exceptions import ValidationError
from django.db.models import Q
from django.forms import (
    BooleanField, CharField, CheckboxInput, ChoiceField, DateInput, DecimalField, FileInput, Form, HiddenInput,
    IntegerField, ModelChoiceField, ModelForm, ModelMultipleChoiceField, NullBooleanSelect, NumberInput,
    RadioSelect, SelectMultiple, Textarea, TextInput, UUIDField,
)
from django.forms.models import BaseInlineFormSet, inlineformset_factory
from extra_views import InlineFormSetFactory
from django.utils.html import format_html
from django.utils.translation import gettext_lazy as _
from dal import autocomplete


from .keyboard_layouts import layout_corrections
from .location_lookup import scan_prefixes
from .permissions import location_deletion_denied
from .models import (
    USAGE_LEVEL_DESCRIPTIONS, BarcodeType, Item, ItemBarcode, ItemFile, ItemImage, ItemLocation, Location, LocationType, ChangeLog,
    UniqueItem, UsageLevel, LabelId,
)
from .widgets import NEW_ITEM_PREFIX, AutocompleteSelect, CategorySelect, ItemOrNewSelect, LocationSelect
from .label_ids import core as label_id_core, naming as label_id_naming, parsing as label_id_parsing
from .label_ids.lookup import annotate_label_code


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


class LocationPurposeForm(ModelForm):
    class Meta:
        model = Location
        fields = ["purpose"]
        # data-modal-focus: modals.js focuses it when the dialog opens.
        widgets = {"purpose": TextInput(attrs={"class": "form-control", "maxlength": 50, "data-modal-focus": ""})}


class LocationDescriptionForm(ModelForm):
    """The physical description of a location that is not part of the building (LocationDescriptionUpdateView)."""
    class Meta:
        model = Location
        fields = ["physical_description"]
        widgets = {"physical_description": Textarea(attrs={"class": "form-control", "rows": 4, "data-modal-focus": ""})}


class LocationOverviewForm(ModelForm):
    """The overview photo of a location; its purpose has LocationPurposeForm."""
    remove_photo = BooleanField(
        required=False, label=_("Remove overview photo"),
    )

    class Meta:
        model = Location
        fields = ["overview_photo"]
        widgets = {
            "overview_photo": FileInput(attrs={"accept": "image/*", "capture": "environment"}),
        }

    def clean(self):
        cleaned = super().clean()
        if cleaned.get("remove_photo") and self.files.get("overview_photo"):
            self.add_error("overview_photo", _("Choose a new photo or remove the current photo, not both."))
        return cleaned

    def save(self, commit=True):
        location = super().save(commit=False)
        if self.cleaned_data.get("remove_photo"):
            location.overview_photo = ""
        if commit:
            location.save()
        return location


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


INTERNAL_DETAILS_PERMISSION = "inventory.view_internal_details"


def usage_level_choices(blank_label):
    """The briefing requirement with its explanation, so choosing it needs no extra help."""
    return [("", blank_label), *((level.value, USAGE_LEVEL_DESCRIPTIONS[level]) for level in UsageLevel)]
MARKDOWN_HELP = _("Markdown is supported, e.g. [link text](https://example.org), lists and **bold**.")


class ForSaleSelect(NullBooleanSelect):
    def __init__(self, attrs=None):
        super().__init__(attrs)
        self.choices = [("unknown", _("Not decided yet")), ("true", _("Yes")), ("false", _("No"))]


def hide_internal_fields(form, user, names):
    """Without the permission, internal fields are not rendered at all; their values stay untouched."""
    if user is not None and not user.has_perm(INTERNAL_DETAILS_PERMISSION):
        for name in names:
            form.fields.pop(name, None)


def clean_sale_fields(cleaned):
    # A price makes an undecided item one for sale; items with unique items are never sold.
    if cleaned.get("kind") == Item.Kind.UNIQUE:
        cleaned["for_sale"], cleaned["sale_price"] = None, None
    elif cleaned.get("sale_price") is not None and cleaned.get("for_sale") is None:
        cleaned["for_sale"] = True
    return cleaned


class BaseItemForm(ModelForm):
    """Fields and barcodes shared by bulk items and items tracked as unique items."""

    INTERNAL_FIELDS = ("last_purchase_price",)
    # The kind of item this form edits; set by the subclasses.
    item_kind = None

    class Meta:
        model = Item
        # The category before the name: its naming (how its items are named) shows below it (CategorySelect).
        fields = ["kind", "category", "name", "description"]
        widgets = {
            "kind": RadioSelect,
            "category": CategorySelect,
            "description": Textarea(attrs={"rows": 3}),
            "procurement_source": Textarea(attrs={"rows": 2}),
            "last_purchase_date": DateInput(attrs={"type": "date"}),
        }

    barcode_data = CharField(
        label=_("Barcodes"),
        help_text=_("One barcode per line, optionally followed by its type, e.g. “4006381333931 EAN13”."),
        widget=Textarea(attrs={"rows": 2}),
        required=False,
    )

    def __init__(self, *args, user=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.user = user
        self.fields["description"].help_text = MARKDOWN_HELP
        if self.instance.pk:
            self.initial['barcode_data'] = ''.join(
                barcode.data + (f" {barcode.type.name}" if barcode.type else "") + '\n'
                for barcode in self.instance.itembarcode_set.select_related("type")
            )
            # The kind can only change while nothing depends on it.
            if self.instance.itemlocation_set.exists() or self.instance.unique_items.exists():
                self.fields["kind"].disabled = True
                self.fields["kind"].help_text = _("The kind cannot change while the item has stock entries or unique items.")
            # Submissions without a kind keep the current one.
            self.fields["kind"].required = False
        else:
            # New items get the kind chosen with the link above the form.
            self.fields["kind"].disabled = True
            self.fields["kind"].widget = HiddenInput()
            self.initial["kind"] = self.item_kind

        if user is not None and not any(user.has_perm(f"inventory.{action}_itembarcode") for action in ("add", "delete")):
            self.fields["barcode_data"].disabled = True
        if "usage_level" in self.fields:
            self.fields["usage_level"].choices = usage_level_choices(_("Not specified"))
        hide_internal_fields(self, user, self.INTERNAL_FIELDS)

        self.helper = FormHelper()
        self.helper.form_tag = False
        self.helper.disable_csrf = True
        # The category search needs jQuery, which the page loads at the end.
        self.helper.include_media = False
        self.helper.layout = layout.Layout(*self.layout_fields())

    def layout_fields(self):
        raise NotImplementedError

    def procurement_layout(self):
        return layout.Fieldset(
            _("Procurement"),
            layout.Div(
                layout.Div("last_purchase_date", css_class="col"),
                layout.Div(bootstrap.AppendedText("last_purchase_price", "€"), css_class="col")
                if "last_purchase_price" in self.fields else layout.Div(css_class="col"),
                css_class="row"),
            "procurement_source",
        )

    def clean_barcode_data(self):
        # Any whitespace separates code and type; blank lines are ignored. Normalized to "<code> <type>\n" lines.
        lines = [parts for parts in (line.split() for line in self.cleaned_data["barcode_data"].splitlines()) if parts]
        if any(len(parts) > 2 for parts in lines):
            raise ValidationError(_("Each line holds one barcode and at most one type without spaces, e.g. “4006381333931 EAN13”."))
        value = "".join(" ".join(parts) + "\n" for parts in lines)
        if self.user is None:
            return value
        desired = {(parts[0], parts[1] if len(parts) == 2 else None) for parts in lines}
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

    def clean_kind(self):
        return self.cleaned_data.get("kind") or self.instance.kind or self.item_kind

    def clean(self):
        return clean_sale_fields(super().clean())

    def save(self, commit=True):
        instance = super().save(commit=commit)
        if commit:
            # Add missing barcodes
            bc_list = []
            for barcode in self.cleaned_data["barcode_data"].split("\n"):
                barcode = barcode.split()
                if not barcode:
                    continue
                elif len(barcode) == 2:
                    barcode_type = BarcodeType.objects.get_or_create(name=barcode[1])[0]
                else:
                    barcode_type = None
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


class BulkItemForm(BaseItemForm):
    item_kind = Item.Kind.BULK

    class Meta(BaseItemForm.Meta):
        fields = [
            "kind", "category", "name", "description", "measurement_unit", "for_sale", "sale_price",
            "last_purchase_date", "last_purchase_price", "procurement_source",
        ]
        widgets = {**BaseItemForm.Meta.widgets, "for_sale": ForSaleSelect}

    def layout_fields(self):
        return [
            "kind",
            "category",
            "name",
            "description",
            layout.Div(
                layout.Div(
                    "measurement_unit",
                    css_class="col"),
                layout.Div(
                    "for_sale",
                    css_class="col"),
                layout.Div(
                    bootstrap.AppendedText("sale_price", '€'),
                    css_class="col"),
                css_class="row"),
            bootstrap.FieldWithButtons("barcode_data"),
            self.procurement_layout(),
        ]


class UniqueKindItemForm(BaseItemForm):
    """An item tracked as unique items describes them; the single objects are added as unique items."""

    item_kind = Item.Kind.UNIQUE

    class Meta(BaseItemForm.Meta):
        fields = [
            "kind", "category", "name", "description", "usage_level",
            "last_purchase_date", "last_purchase_price", "procurement_source",
        ]

    def layout_fields(self):
        return [
            "kind",
            "category",
            "name",
            "description",
            "usage_level",
            bootstrap.FieldWithButtons("barcode_data"),
            self.procurement_layout(),
        ]


ITEM_FORMS = {Item.Kind.BULK: BulkItemForm, Item.Kind.UNIQUE: UniqueKindItemForm}


class NewItemForm(BaseItemForm):
    """
    A new item, bulk or tracked as unique items. Both kinds' fields are on the
    page and the chosen kind shows its part (item_kind_switch.js), so switching
    keeps everything entered; only the chosen kind's fields are used.
    """

    class Meta(BaseItemForm.Meta):
        fields = [
            "kind", "category", "name", "description", "measurement_unit", "for_sale", "sale_price", "usage_level",
            "last_purchase_date", "last_purchase_price", "procurement_source",
        ]
        widgets = {**BaseItemForm.Meta.widgets, "for_sale": ForSaleSelect}

    def __init__(self, *args, allow_unique=True, **kwargs):
        chosen = (kwargs.get("initial") or {}).get("kind") or Item.Kind.BULK
        super().__init__(*args, **kwargs)
        self.initial["kind"] = chosen  # BaseItemForm presets the kind of single-kind forms
        kind = self.fields["kind"]
        kind.disabled = False
        kind.required = True
        kind.help_text = ""
        if not allow_unique:
            kind.choices = [(Item.Kind.BULK, Item.Kind.BULK.label)]
        kind.widget = RadioSelect(choices=kind.choices, attrs={"data-kind-switch": True})

    def layout_fields(self):
        return [
            layout.Div(bootstrap.InlineRadios("kind"), css_class="item-kind-switch"),
            layout.HTML(format_html(
                '<p class="text-muted" data-for-kind="bulk">{}</p><p class="text-muted" data-for-kind="unique">{}</p>',
                _("A bulk item is counted per location, such as screws or filament."),
                _("Unique items are objects tracked one by one, each with its own {name}, such as fire extinguishers "
                  "or machines. This item describes them; enter the first one below and add more later.").format(
                    name=label_id_naming.name()),
            )),
            "category",
            "name",
            "description",
            layout.Div(
                layout.Div("measurement_unit", css_class="col"),
                layout.Div("for_sale", css_class="col"),
                layout.Div(bootstrap.AppendedText("sale_price", "€"), css_class="col"),
                css_class="row", data_for_kind="bulk"),
            layout.Div("usage_level", data_for_kind="unique"),
            bootstrap.FieldWithButtons("barcode_data"),
            self.procurement_layout(),
        ]

    def clean(self):
        cleaned = super().clean()
        if cleaned.get("kind") == Item.Kind.BULK:
            cleaned["usage_level"] = ""  # only for items tracked as unique items
        return cleaned


class PhotoForm(ModelForm):
    def _get_validation_exclusions(self):
        # A newly chosen primary photo may meet the old one still saved; PrimaryPhotoFormSet
        # releases it on saving, and the database constraint still holds.
        return super()._get_validation_exclusions() | {"item", "unique_item"}


LEVEL_UNIQUE, LEVEL_GENERAL = "unique", "item"


class LevelFormMixin:
    """
    A photo or file row on a unique item's form: it belongs to this unique item
    or to the item in general. `target` is the unique item being edited.
    """

    target = None

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        general = self.instance.pk and self.instance.unique_item_id is None
        self.fields["level"] = ChoiceField(
            label=_("Belongs to"), widget=RadioSelect, initial=LEVEL_GENERAL if general else LEVEL_UNIQUE,
            choices=[(LEVEL_UNIQUE, _("This unique item")), (LEVEL_GENERAL, _("The item in general"))],
        )

    def chosen_unique_item(self):
        return self.target if self.cleaned_data.get("level") == LEVEL_UNIQUE else None

    def save(self, commit=True):
        self.instance.unique_item = self.chosen_unique_item()
        return super().save(commit)


class LevelPhotoForm(LevelFormMixin, PhotoForm):
    pass


class LevelFileForm(LevelFormMixin, ModelForm):
    pass


def chosen_unique_item(form):
    """The unique item a submitted photo or file row belongs to; None for the item in general."""
    if isinstance(form, LevelFormMixin):
        return form.chosen_unique_item()
    if "unique_item" in form.fields:
        return form.cleaned_data.get("unique_item")
    return form.instance.unique_item


class PrimaryPhotoFormSet(BaseInlineFormSet):
    """One primary photo for the item in general and one per unique item; choosing a new one releases the old."""

    def clean(self):
        super().clean()
        scopes = [id(chosen_unique_item(form)) for form in self.forms
                  if getattr(form, "cleaned_data", {}).get("is_primary")]
        if len(scopes) != len(set(scopes)):
            raise ValidationError(_("Choose only one primary photo."))

    def save(self, commit=True):
        chosen = [form for form in self.forms if form.has_changed() and form.cleaned_data.get("is_primary")]
        if commit:
            for form in chosen:
                unique_item = chosen_unique_item(form)
                primaries = self.model.objects.filter(item=self.instance, is_primary=True)
                primaries = primaries.filter(unique_item=unique_item) if unique_item else primaries.filter(unique_item__isnull=True)
                primaries.exclude(pk=form.instance.pk).update(is_primary=False)
        return super().save(commit)


# Each photo or file row carries what the gallery shows (media_gallery.js); without
# JavaScript the rows remain a plain form.
PHOTO_INFO = layout.HTML("""
    {% load thumbnail %}
    <span hidden data-media-info data-kind="photo"{% if formset_form.instance.pk %} data-saved
        data-name="{{ formset_form.instance.description }}" data-image="{{ formset_form.instance.image.url }}"
        {% thumbnail formset_form.instance.image "320x320" as im %}data-thumb="{{ im.url }}"{% endthumbnail %}{% endif %}></span>
    {% if formset_form.instance.pk %}{% thumbnail formset_form.instance.image "160x160" as im %}<img class="img-thumbnail mb-2" data-media-fallback src="{{ im.url }}" alt="">{% endthumbnail %}{% endif %}
""")
FILE_INFO = layout.HTML("""
    <span hidden data-media-info data-kind="file"{% if formset_form.instance.pk %} data-saved
        data-name="{{ formset_form.instance.display_name }}" data-href="{{ formset_form.instance.get_absolute_url }}"{% endif %}></span>
    {% if formset_form.instance.pk %}<p class="mb-1" data-media-fallback><a href="{{ formset_form.instance.get_absolute_url }}">{{ formset_form.instance.display_name }}</a></p>{% endif %}
""")
DELETE_CHECKBOX = layout.HTML("""
    {% if formset_form.DELETE and formset_form.instance.pk %}
    <div class="form-check mt-1" data-media-delete-field>
        {{ formset_form.DELETE }}
        <label class="form-check-label" for="{{ formset_form.DELETE.id_for_label }}">{{ formset_form.DELETE.label }}</label>
    </div>
    {% endif %}
""")


PRIMARY_PHOTO_CHECKBOX = layout.HTML("""
    <div class="form-check mt-1">
        {{ formset_form.is_primary }}
        <label class="form-check-label" for="{{ formset_form.is_primary.id_for_label }}">{{ formset_form.is_primary.label|capfirst }}</label>
    </div>
""")


def unique_item_choice_label(unique_item):
    code = unique_item.label_display or f"#{unique_item.pk}"
    where = unique_item.location.title_with_code if unique_item.location else _("removed from the inventory")
    return f"{code} @ {where}"


def offer_unique_items(formset, item):
    """
    On the item form, a row can be assigned to one of the item's unique items.
    Returns whether the choice is offered (items tracked as unique items that have some).
    """
    unique_items = []
    if item is not None and item.pk and item.tracks_unique_items:
        unique_items = list(annotate_label_code(item.unique_items.select_related("location")))
    for form in formset.forms:
        if not unique_items:
            form.fields.pop("unique_item", None)
            continue
        field = form.fields["unique_item"]
        field.queryset = item.unique_items.all()
        field.empty_label = _("The item in general")
        codes = {unique_item.pk: unique_item for unique_item in unique_items}
        field.label_from_instance = lambda unique_item, codes=codes: unique_item_choice_label(codes.get(unique_item.pk, unique_item))
    return bool(unique_items)


class ItemImageInline(InlineFormSetFactory):
    model = ItemImage
    fields = ["description", "image", "is_primary", "unique_item"]
    description_defaults = ["Price label", "Packaged", "Single item (unpacked)"]
    factory_kwargs = {
        "extra": 1,
        "can_order": False,
        "can_delete": True,
        "form": PhotoForm,
        "formset": PrimaryPhotoFormSet,
        "widgets": {
            "image": FileInput(attrs={"accept": "image/*", "capture": "environment"}),
            "description": TextDatalistInput(options=description_defaults)
        },
    }

    def construct_formset(self):
        formset = super().construct_formset()
        with_level = offer_unique_items(formset, self.object)
        formset.helper = FormHelper()
        formset.helper.form_tag = False
        formset.helper.disable_csrf = True
        formset.helper.form_title = _("Photos")
        formset.helper.form_show_labels = False
        formset.helper.layout = layout.Layout(
            layout.Div(
                PHOTO_INFO,
                FloatingField("description"),
                layout.Div("image", css_class="input-group"),
                *([FloatingField("unique_item")] if with_level else []),
                PRIMARY_PHOTO_CHECKBOX,
                DELETE_CHECKBOX,
                css_class="mb-3 formset-row",
            ),
        )
        return formset


PUBLIC_FILE_HELP = _("Files are public unless marked as internal documents. Mark invoices and anything with personal data as internal.")


class FileInline(InlineFormSetFactory):
    """Manuals, data sheets, invoices, test certificates. Internal ones stay hidden without the permission."""

    model = ItemFile
    fields = ["description", "file", "internal"]
    # Files are only offered through the download view, never by their storage path.
    factory_kwargs = {"extra": 1, "can_order": False, "can_delete": True, "widgets": {"file": FileInput}}

    def get_formset_kwargs(self):
        kwargs = super().get_formset_kwargs()
        queryset = kwargs.get("queryset", self.inline_model.objects.all())
        if not self.request.user.has_perm(INTERNAL_DETAILS_PERMISSION):
            kwargs["queryset"] = queryset.filter(internal=False)
        return kwargs

    def file_fields(self, formset, extra=()):
        for form in formset:
            form.fields["file"].help_text = PUBLIC_FILE_HELP
        formset.helper = FormHelper()
        formset.helper.form_tag = False
        formset.helper.disable_csrf = True
        formset.helper.form_title = _("Files")
        formset.helper.layout = layout.Layout(
            layout.Div(
                FILE_INFO,
                FloatingField("description"),
                "file",
                "internal",
                *extra,
                DELETE_CHECKBOX,
                css_class="mb-3 formset-row",
            ),
        )
        return formset


class ItemFileInline(FileInline):
    fields = ["description", "file", "internal", "unique_item"]

    def construct_formset(self):
        formset = super().construct_formset()
        with_level = offer_unique_items(formset, self.object)
        return self.file_fields(formset, ["unique_item"] if with_level else [])


class UniqueItemLevelInline(InlineFormSetFactory):
    """
    Photos or files edited on a unique item's form. The rows belong to its item;
    each chooses whether it is about this unique item or the item in general,
    and existing ones can change that level.
    """

    def get_formset(self):
        return inlineformset_factory(Item, self.inline_model, **self.get_factory_kwargs())

    def get_formset_kwargs(self):
        kwargs = super().get_formset_kwargs()
        unique_item = self.object
        # A new item is saved together with the unique item; the formset then uses it.
        try:
            kwargs["instance"] = unique_item.item if unique_item is not None else Item()
        except Item.DoesNotExist:
            kwargs["instance"] = Item()
        if unique_item is not None and unique_item.pk:
            kwargs["queryset"] = self.inline_model.objects.filter(Q(unique_item=unique_item) | Q(unique_item__isnull=True))
        else:
            kwargs["queryset"] = self.inline_model.objects.none()
        return kwargs

    def construct_formset(self):
        formset = super().construct_formset()
        for form in formset.forms:
            form.target = self.object
        return formset


class UniqueItemImageInline(UniqueItemLevelInline):
    model = ItemImage
    prefix = "images"
    fields = ["description", "image", "is_primary"]
    factory_kwargs = {
        "extra": 1,
        "can_order": False,
        "can_delete": True,
        "form": LevelPhotoForm,
        "formset": PrimaryPhotoFormSet,
        "widgets": {"image": FileInput(attrs={"accept": "image/*", "capture": "environment"})},
    }

    def construct_formset(self):
        formset = super().construct_formset()
        formset.helper = FormHelper()
        formset.helper.form_tag = False
        formset.helper.disable_csrf = True
        formset.helper.form_title = _("Photos")
        formset.helper.form_show_labels = False
        formset.helper.layout = layout.Layout(
            layout.Div(
                PHOTO_INFO,
                FloatingField("description"),
                layout.Div("image", css_class="input-group"),
                bootstrap.InlineRadios("level"),
                PRIMARY_PHOTO_CHECKBOX,
                DELETE_CHECKBOX,
                css_class="mb-3 formset-row",
            ),
        )
        return formset


class UniqueItemFileInline(FileInline, UniqueItemLevelInline):
    # FileInline first: it hides internal files from the queryset UniqueItemLevelInline chooses.
    prefix = "files"
    factory_kwargs = {**FileInline.factory_kwargs, "form": LevelFileForm}

    def construct_formset(self):
        formset = super().construct_formset()
        return self.file_fields(formset, [bootstrap.InlineRadios("level")])


class AdminItemLocationForm(ModelForm):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["location"].queryset = Location.active.all()

    class Meta:
        model = ItemLocation
        fields = "__all__"
        widgets = {
            'location': autocomplete.ModelSelect2(url='location-autocomplete')
        }

class ItemLocationForm(ModelForm):
    class Meta:
        model = ItemLocation
        fields = ['location', 'amount']
        widgets = {
            'location': LocationSelect(url='location-autocomplete')
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["location"].queryset = Location.active.all()
        if "location" in self.initial and "instance" not in kwargs:
            self.fields["location"].disabled = True
        # Only quick-items may keep an unknown amount; entering one makes them
        # regular items, which cannot return to an unknown amount.
        self.fields["amount"].required = not (self.instance.pk and self.instance.is_quick_item)

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
        if view_kwargs and "initial" in view_kwargs:
            self.initial = view_kwargs["initial"]

    def construct_formset(self):
        formset = super().construct_formset()
        formset.queryset = formset.queryset.filter(location__is_deleted=False)
        formset.helper = FormHelper()
        formset.helper.form_tag = False
        formset.helper.disable_csrf = True
        formset.helper.include_media = False
        formset.helper.form_title = _("Storage locations")
        formset.helper.layout = layout.Layout(
            layout.Div(
                layout.Div(bootstrap.Field("location"), css_class='col-md-6'),
                layout.Div(
                    bootstrap.FieldWithButtons(
                        "amount",
                        layout.HTML('<span class="amount_print_meas_unit ms-2 text-nowrap"></span>'),
                    ),
                    css_class='col-md-6',
                ),
                css_class='row',
            ),
        )
        return formset

class AdminLocationForm(ModelForm):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Retain the current parent when inspecting an archived hierarchy.
        self.fields["parent_location"].queryset = Location.objects.filter(
            Q(is_deleted=False) | Q(pk=self.instance.parent_location_id)
        )
        if self.instance.pk and "short_name" in self.fields:
            self.fields["short_name"].help_text = _(
                "Codes are meant to stay. Changing the short name keeps the current code (and those of sub-locations "
                "that include it) blocked as a former code, which still finds this location.")

    class Meta:
        model = Location
        fields = "__all__"
        widgets = {
            'parent_location': autocomplete.ModelSelect2(url='parent_location_autocomplete', forward=['id'])
        }

    id = IntegerField(widget=HiddenInput(), required = False)

class DissolveLocationForm(Form):
    def __init__(self, *args, plan, user, **kwargs):
        self.user = user
        super().__init__(*args, **kwargs)
        self.plan = plan
        # A location that is kept may receive entries from its own sub-locations.
        destinations = Location.active.exclude(pk=plan.root.pk) if plan.delete_root else Location.active.all()

        def destination_field(queryset):
            # Clearing a row's destination keeps that entry where it is.
            return ModelChoiceField(
                label=_("Destination"), queryset=queryset, required=False,
                widget=LocationSelect(
                    url="location-autocomplete",
                    attrs={"data-placeholder": _("Search for a location…"), "data-allow-clear": "true"},
                ),
            )

        self.fields["bulk_destination"] = destination_field(destinations)
        self.rows = []
        self.can_move_rows = False
        self.can_delete_rows = False
        for row in plan.rows:
            key = row["key"]
            model = "location" if row["kind"] == "location" else "itemlocation"
            if row["kind"] == "location":
                delete_denied = location_deletion_denied(user, row["object"])
            elif not user.has_perm("inventory.delete_itemlocation"):
                delete_denied = _("You do not have permission to delete this entry.")
            else:
                delete_denied = None
            can_delete = delete_denied is None
            can_move = user.has_perm(f"inventory.change_{model}")
            self.can_move_rows |= can_move
            self.can_delete_rows |= can_delete
            self.fields[key + "_delete"] = BooleanField(label=_("Delete"), required=False, disabled=not can_delete)
            if not can_delete:
                self.fields[key + "_delete"].widget.attrs["title"] = delete_denied
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
            destination = cleaned.get(key + "_destination")
            # Without a destination or deletion an entry stays where it is.
            action = "delete" if cleaned.get(key + "_delete") else "move" if destination else "keep"
            model = "location" if row["kind"] == "location" else "itemlocation"
            verb = "delete" if action == "delete" else "change"
            if action != "keep" and not self.user.has_perm(f"inventory.{verb}_{model}"):
                self.add_error(None, _("You do not have permission for the selected action."))
            elif action == "delete" and row["kind"] == "location" and location_deletion_denied(self.user, row["object"]):
                self.add_error(None, location_deletion_denied(self.user, row["object"]))
            operations.append([row["kind"], row["object"].pk, action, destination.pk if action == "move" else None])
        deleted = self.plan.deleted_locations(operations)
        for row, (kind, _pk, action, destination) in zip(self.plan.rows, operations):
            current = row["object"].location_id if kind == "item" else row["object"].parent_location_id
            if action == "keep" and current in deleted:
                self.add_error(row["key"] + "_destination", _("Choose a destination."))
            elif action == "move" and destination in deleted:
                self.add_error(row["key"] + "_destination", _("This destination is deleted by the plan. Choose another one."))
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

    def __init__(self, *args, dialog=False, **kwargs):
        super().__init__(*args, **kwargs)
        if dialog:
            # modals.js focuses the field on opening, for scanners that type. Phones keep their
            # keyboard closed; there the camera scan above the field is the usual way.
            attrs = self.fields["identifiers"].widget.attrs
            del attrs["autofocus"]
            attrs["data-modal-focus"] = "without-keyboard"

    def clean_identifiers(self):
        identifiers = []
        for chunk in self.cleaned_data["identifiers"].split():
            # A scanner with another keyboard layout may type ";" inside a URL.
            if any(any(layout_corrections(chunk, prefix)) for prefix in scan_prefixes()):
                identifiers.append(chunk)
            else:
                identifiers.extend(value for value in chunk.split(";") if value)
        if not identifiers:
            raise ValidationError(_("Enter at least one location."))
        return identifiers


class ContainerActivationForm(ModelForm):
    """Taking a reserved container into use (ContainerActivateView): where it is now (required), what it is for,
    what it looks like and a photo."""

    class Meta:
        model = Location
        fields = ["parent_location", "purpose", "physical_description", "overview_photo"]
        widgets = {
            "purpose": TextInput(attrs={"maxlength": 50}),
            "physical_description": Textarea(attrs={"rows": 3}),
            "overview_photo": FileInput(attrs={"accept": "image/*", "capture": "environment"}),
        }

    parent_location = ModelChoiceField(
        label=_("Where is it now?"),
        help_text=_("Search by location name or code, or scan the label of the location it is in."),
        queryset=Location.active.filter(type__no_sublocations=False),
        widget=LocationSelect(url="parent_location_autocomplete",
                              attrs={"data-placeholder": _("Search for a location…")}),
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.instance.is_reserved = False  # validated as activated (Location.clean)


class LocationMoveForm(ModelForm):
    class Meta:
        model = Location
        fields = ["parent_location", "id"]

    parent_location = ModelChoiceField(
        label=_("Destination"),
        help_text=_("Search by location name or identifier and select the new parent location."),
        queryset=Location.active.filter(type__no_sublocations = False),
        widget=LocationSelect(
            url='parent_location_autocomplete',
            forward=['id'],
            attrs={
                'data-placeholder': _("Search for a location…"),
                'data-allow-clear': 1,
            },
        ),
        blank=True,
        required=False,
    )

    id = IntegerField(widget=HiddenInput(), required = False)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Shelves and cabinets go into a level, room or area, or onto a pallet (Location.clean).
        if self.instance.pk and self.instance.type.area_numbering:
            field = self.fields["parent_location"]
            field.queryset = field.queryset.filter(LocationType.holding_storage_units())
            field.required = True


class StockChangeForm(Form):
    """Remove or add stock at one location; `entry` is the stock entry, locked by the view."""

    direction = ChoiceField(
        label=_("Change"), choices=ChangeLog.Direction.choices,
        widget=RadioSelect(attrs={"class": "btn-check"}),
    )
    amount = DecimalField(
        label=_("Amount"), required=False, min_value=0, max_digits=16, decimal_places=3,
        widget=NumberInput(attrs={"class": "form-control", "step": "any", "min": "0", "inputmode": "decimal"}),
    )
    complete = BooleanField(
        label=_("Remove everything stored at this location"), required=False,
        widget=CheckboxInput(attrs={"class": "form-check-input"}),
    )
    reason = ChoiceField(label=_("Reason"), choices=[(reason.value, reason.label) for reasons in ChangeLog.REASONS.values()
                                                    for reason in reasons])
    note = CharField(
        label=_("Note (optional)"), required=False, max_length=500,
        widget=Textarea(attrs={"class": "form-control", "rows": 2, "maxlength": 500}),
    )
    request_id = UUIDField(required=False, widget=HiddenInput)

    def __init__(self, *args, entry=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.entry = entry

    def reasons(self):
        """The reason radio buttons, grouped by direction."""
        value = self["reason"].value()
        return [
            {"direction": direction, "choices": [
                {"value": reason.value, "label": reason.label, "id": f"id_reason_{reason.value}", "checked": value == reason}
                for reason in ChangeLog.REASONS[direction]
            ]}
            for direction in ChangeLog.Direction
        ]

    def clean(self):
        cleaned = super().clean()
        direction, reason = cleaned.get("direction"), cleaned.get("reason")
        if direction and reason and reason not in ChangeLog.REASONS[direction]:
            self.add_error("reason", _("Choose a reason that fits the change."))
        if self.entry is None or not direction or "amount" in self.errors:
            return cleaned
        stock, kind = self.entry.amount, self.entry.amount_kind
        amount = cleaned.get("amount")
        complete = bool(cleaned.get("complete")) and direction == ChangeLog.Direction.DECREASE
        cleaned["estimated"] = False
        if direction == ChangeLog.Direction.DECREASE and kind == "precise":
            if complete:
                # "Everything" is unambiguous, even if the stock changed meanwhile.
                amount = stock
            elif amount is None:
                self.add_error("amount", _("Enter the amount."))
            elif amount <= 0:
                self.add_error("amount", _("Enter an amount greater than zero."))
            elif amount > stock:
                self.add_error("amount", _("Only %(amount)s are stored here.") % {"amount": self.entry.amount_text})
            elif amount == stock:
                complete = True
        else:
            # Estimates have no upper bound (see change_stock()); a changed
            # amount is always counted, never estimated.
            if amount is None and not complete:
                self.add_error("amount", _("Enter the amount."))
            elif amount is not None and amount <= 0:
                self.add_error("amount", _("Enter an amount greater than zero."))
            cleaned["estimated"] = bool(complete and kind == "estimate" and amount == abs(stock))
        cleaned["amount"], cleaned["complete"] = amount, complete
        return cleaned


class ItemOrNewField(ModelChoiceField):
    """
    An item tracked as unique items, or "new:<name>" (offered last by the item
    search) for a new one that is created only together with the unique item.
    """

    def to_python(self, value):
        if isinstance(value, str) and value.startswith(NEW_ITEM_PREFIX):
            name = " ".join(value[len(NEW_ITEM_PREFIX):].split())
            max_length = Item._meta.get_field("name").max_length
            if not name or len(name) > max_length:
                raise ValidationError(_("Item names need 1 to %(max)d characters.") % {"max": max_length})
            return Item(name=name, kind=Item.Kind.UNIQUE)
        return super().to_python(value)

    def prepare_value(self, value):
        if isinstance(value, Item) and value.pk is None:
            return NEW_ITEM_PREFIX + value.name
        return super().prepare_value(value)


class NewItemAlongsideMixin:
    """A unique item's form whose item may be new; it is created when the unique item is saved."""

    user = None

    def new_item(self):
        item = getattr(self, "cleaned_data", {}).get("item")
        return item if item is not None and item.pk is None else None

    def clean_item(self):
        item = self.cleaned_data.get("item")
        if item is not None and item.pk is None and not (self.user and self.user.has_perm("inventory.add_item")):
            raise ValidationError(_("You do not have permission to create items."))
        return item

    def _get_validation_exclusions(self):
        exclusions = super()._get_validation_exclusions()
        if self.new_item() is not None:
            exclusions.add("item")  # saved just before the unique item
        return exclusions

    def save(self, commit=True):
        item = self.new_item()
        if commit and item is not None:
            item.save()
            self.instance.item = item
        return super().save(commit)


def user_label(user):
    return f"{user.get_full_name() or user.username} ({user.username})"


class UniqueItemForm(NewItemAlongsideMixin, ModelForm):
    """Edit a unique item; who owns it and who is responsible is internal beyond first names."""

    INTERNAL_FIELDS = ("purchase_price", "responsible_user", "owner_user", "owner_contact")
    OWNER_FIELDS = ("owner_user", "owner_first_name", "owner_contact")
    OWNER_PERMISSION = "inventory.change_uniqueitem_owner"

    class Meta:
        model = UniqueItem
        fields = [
            "item", "name", "location", "usage_level", "warranty_until", "notes",
            "responsible_team", "responsible_user", "owner_user", "owner_first_name", "owner_contact",
            "purchase_date", "purchase_price", "procurement_source",
        ]
        field_classes = {"item": ItemOrNewField}
        widgets = {
            "item": ItemOrNewSelect(url="unique_kind_item_autocomplete",
                                    attrs={"data-placeholder": _("Search for an item with unique items…")}),
            "location": LocationSelect(url="location-autocomplete",
                                           attrs={"data-placeholder": _("Search for a location…")}),
            "responsible_user": AutocompleteSelect(url="user_autocomplete", attrs={"data-allow-clear": 1}),
            "owner_user": AutocompleteSelect(url="user_autocomplete", attrs={"data-allow-clear": 1}),
            "warranty_until": DateInput(attrs={"type": "date"}),
            "purchase_date": DateInput(attrs={"type": "date"}),
            "notes": Textarea(attrs={"rows": 3}),
            "owner_contact": Textarea(attrs={"rows": 2}),
            "procurement_source": Textarea(attrs={"rows": 2}),
        }

    def __init__(self, *args, user=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.user = user
        self.fields["item"].queryset = Item.active.filter(kind=Item.Kind.UNIQUE)
        self.fields["location"].queryset = Location.active.all()
        self.fields["location"].required = True
        if self.instance.pk:
            # A unique item stays the kind of thing it is.
            self.fields["item"].disabled = True
        self.fields["usage_level"].choices = usage_level_choices(_("As set for the item"))
        hide_internal_fields(self, user, self.INTERNAL_FIELDS)
        for name in ("responsible_user", "owner_user"):
            if name in self.fields:
                self.fields[name].label_from_instance = user_label
        # After creation, only admins or people with the permission change the owner.
        self.owner_locked = bool(self.instance.pk) and not (user is not None and user.has_perm(self.OWNER_PERMISSION))
        if self.owner_locked:
            for name in self.optional(*self.OWNER_FIELDS):
                self.fields[name].disabled = True

        self.helper = FormHelper()
        self.helper.form_tag = False
        self.helper.disable_csrf = True
        # The autocomplete scripts need jQuery, which the page loads at the end.
        self.helper.include_media = False
        self.helper.layout = layout.Layout(*self.layout_fields())

    def optional(self, *names):
        return [name for name in names if name in self.fields]

    def layout_fields(self):
        return [
            "item",
            "name",
            "location",
            "usage_level",
            "notes",
            layout.Fieldset(_("Responsibility"), "responsible_team", *self.optional("responsible_user")),
            layout.Fieldset(
                _("Owner"),
                layout.HTML('<p class="text-muted small">{}</p>'.format(
                    _("Only admins or people with the permission can change the owner after the unique item was created.")
                    if self.owner_locked else
                    _("Leave empty if the unique item belongs to the ZAM. First names are shown publicly."))),
                *self.optional("owner_user"), "owner_first_name", *self.optional("owner_contact"),
            ),
            layout.Fieldset(
                _("Procurement"),
                layout.Div(
                    layout.Div("purchase_date", css_class="col-sm"),
                    layout.Div(bootstrap.AppendedText("purchase_price", "€"), css_class="col-sm")
                    if "purchase_price" in self.fields else layout.Div(css_class="col-sm"),
                    layout.Div("warranty_until", css_class="col-sm"),
                    css_class="row"),
                "procurement_source",
            ),
        ]


class LabelIdChoiceForm(Form):
    """Every unique item gets its label ID when it is created: a reserved label or a new one."""

    GENERATE, RESERVED = "generate", "reserved"
    label_choice = ChoiceField(
        label=label_id_naming.NAME, initial=GENERATE, widget=RadioSelect,
        choices=[(GENERATE, _("Generate a new ID and print its label")),
                 (RESERVED, _("Use a pre-printed label"))],
    )
    label_code = CharField(
        label=_("ID on the label"), required=False, max_length=200,
        help_text=_("Scan the label or type the ID printed on it."),
        widget=TextInput(attrs={"autocomplete": "off", "autocapitalize": "characters"}),
    )

    @staticmethod
    def label_row():
        return layout.Div(
            layout.Div("label_choice", css_class="col-sm-6"),
            layout.Div("label_code", css_class="col-sm-6"),
            css_class="row",
        )

    def clean(self):
        cleaned = super().clean()
        if cleaned.get("label_choice") != self.RESERVED:
            cleaned["label_code"] = None
            return cleaned
        raw = (cleaned.get("label_code") or "").strip()
        if not raw:
            self.add_error("label_code", _("Scan or enter the ID on the label."))
            return cleaned
        try:
            code = label_id_parsing.code_from_scan(raw)
        except label_id_core.InvalidLabelId:
            self.add_error("label_code", _("%(code)s is not a valid ID.") % {"code": raw})
            return cleaned
        lid = LabelId.objects.filter(pk=code).first()
        if lid is None:
            self.add_error("label_code", _("The ID %(code)s does not exist.") % {"code": label_id_core.display(code)})
        elif lid.status != LabelId.Status.RESERVED:
            self.add_error("label_code", _("The ID %(code)s is already in use or retired.") % {"code": lid.display})
        else:
            cleaned["label_code"] = code
        return cleaned


class NewUniqueItemForm(LabelIdChoiceForm, UniqueItemForm):
    def layout_fields(self):
        return [layout.Fieldset(_("Label"), self.label_row()), *super().layout_fields()]


class FirstUniqueItemForm(LabelIdChoiceForm, ModelForm):
    """Creating an item tracked as unique items includes its first unique item, like stock for a bulk item."""

    class Meta:
        model = UniqueItem
        fields = ["location"]
        widgets = {"location": LocationSelect(url="location-autocomplete",
                                                  attrs={"data-placeholder": _("Search for a location…")})}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["location"].queryset = Location.active.all()
        self.fields["location"].required = True

    def has_changed(self):
        # Always saved, even when the preset location and the default ID choice are kept.
        return True


class FirstUniqueItemInline(InlineFormSetFactory):
    model = UniqueItem
    form_class = FirstUniqueItemForm
    fields = ["location"]
    prefix = "first_unique_item"
    factory_kwargs = {"extra": 0, "min_num": 1, "max_num": 1, "validate_min": True, "validate_max": True,
                      "can_delete": False, "can_order": False}

    def __init__(self, parent_model, request, instance, view_kwargs=None, view=None):
        super().__init__(parent_model, request, instance, view_kwargs, view)
        if view_kwargs and "initial" in view_kwargs:
            self.initial = view_kwargs["initial"]

    def construct_formset(self):
        formset = super().construct_formset()
        formset.helper = FormHelper()
        formset.helper.form_tag = False
        formset.helper.disable_csrf = True
        formset.helper.include_media = False
        formset.helper.form_title = _("First unique item")
        formset.helper.layout = layout.Layout("location", LabelIdChoiceForm.label_row())
        return formset


class DisposeUniqueItemForm(Form):
    reason = ChoiceField(label=_("Reason"), choices=UniqueItem.DisposalReason.choices, widget=RadioSelect)
    note = CharField(
        label=_("Note (optional)"), required=False, max_length=2000,
        widget=Textarea(attrs={"class": "form-control", "rows": 3}),
    )


class QuickPhotoForm(ModelForm):
    class Meta:
        model = ItemImage
        fields = ["image", "description", "is_primary"]


class QuickFileForm(ModelForm):
    class Meta:
        model = ItemFile
        fields = ["file", "description", "internal"]


class MoveUniqueItemForm(ModelForm):
    class Meta:
        model = UniqueItem
        fields = ["location"]
        widgets = {"location": LocationSelect(url="location-autocomplete",
                                                  attrs={"data-placeholder": _("Search for a location…")})}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["location"].queryset = Location.active.all()
        self.fields["location"].required = True
