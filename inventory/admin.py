from dal import autocomplete
from django import forms
from django.contrib import admin, messages
from django.contrib.admin.views.decorators import staff_member_required
from django.contrib.auth.mixins import PermissionRequiredMixin
from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import CharField, FileField, TextField
from django.forms.models import _get_foreign_key
from django.shortcuts import redirect
from django.urls import path, reverse
from django.utils.decorators import method_decorator
from django.utils.html import format_html
from django.utils.http import urlencode
from django.utils.translation import gettext_lazy as _, ngettext
from django.views.generic import FormView

from . import models
from .icons import icon
from .forms import AdminItemLocationForm, AdminLocationForm
from .soft_delete import SoftDeleteModel
from .soft_delete_admin import DeletedObjectFilter, SoftDeleteAdminMixin
from .stock_log import stock_changes
from .label_ids import core as label_id_core, naming as label_id_naming, parsing as label_id_parsing, services as label_id_services
from .label_ids.admin import ClaimOnAddMixin  # also registers LabelIdAdmin
from .label_ids.lookup import annotate_label_code


admin.site.register(models.MeasurementUnit)


@admin.register(models.LocationType)
class LocationTypeAdmin(admin.ModelAdmin):
    list_display = ("name", "category", "structure", "unique", "moveable", "area_numbering", "description")
    list_filter = ("category", "structure", "unique")


@admin.register(models.LocationAxis)
class LocationAxisAdmin(admin.ModelAdmin):
    list_display = ("number", "name")
admin.site.register(models.BarcodeType)


class CategoryAdmin(admin.ModelAdmin):
    model = models.Category
    fields = ("name", "description", "parent_category")
admin.site.register(models.Category, CategoryAdmin)


class LocationLabelTemplateAdmin(admin.ModelAdmin):
    model = models.LocationLabelTemplate
    fields = ("name", "zpl_template", "label_width", "label_height", "image_tag")
    readonly_fields = ("image_tag",)
admin.site.register(models.LocationLabelTemplate, LocationLabelTemplateAdmin)


class CappedFormSetMixin:
    max_rows = row_total = full_list_url = None

    def get_queryset(self):
        # Cached so the forms index the evaluated slice instead of querying per row.
        if not hasattr(self, "_capped_queryset"):
            self._capped_queryset = super().get_queryset()[: self.max_rows]
        return self._capped_queryset


class CappedInlineMixin:
    """Beyond `max_rows`, show the first rows read-only and link to the full change list.

    Every inline row posts its form fields, even read-only rows (pk and parent key),
    so hundreds of rows exceed DATA_UPLOAD_MAX_NUMBER_FIELDS on save.
    """
    max_rows = 50
    template = "admin/inventory/capped_tabular.html"

    def row_total(self, request, obj):
        if obj is None or obj.pk is None:
            return 0
        # The admin asks for permissions many times per request; count once.
        totals = getattr(request, "_capped_inline_totals", None)
        if totals is None:
            totals = request._capped_inline_totals = {}
        key = (type(self), obj.pk)
        if key not in totals:
            totals[key] = self.get_queryset(request).filter(**{self.fk().name: obj}).count()
        return totals[key]

    def is_capped(self, request, obj):
        return self.row_total(request, obj) > self.max_rows

    def fk(self):
        return _get_foreign_key(self.parent_model, self.model, fk_name=self.fk_name)

    def full_list_url(self, obj):
        url = reverse(f"admin:{self.opts.app_label}_{self.opts.model_name}_changelist")
        params = {f"{self.fk().name}__exact": obj.pk}
        if issubclass(self.model, SoftDeleteModel):
            # The inline lists deleted rows too; match it instead of the list's default filter.
            params[DeletedObjectFilter.parameter_name] = "all"
        return f"{url}?{urlencode(params)}"

    def has_add_permission(self, request, obj=None):
        return super().has_add_permission(request, obj) and not self.is_capped(request, obj)

    def has_change_permission(self, request, obj=None):
        return super().has_change_permission(request, obj) and not self.is_capped(request, obj)

    def has_delete_permission(self, request, obj=None):
        return super().has_delete_permission(request, obj) and not self.is_capped(request, obj)

    def get_formset(self, request, obj=None, **kwargs):
        formset = super().get_formset(request, obj, **kwargs)
        if not self.is_capped(request, obj):
            return formset
        return type(formset.__name__, (CappedFormSetMixin, formset), {
            "max_rows": self.max_rows,
            "row_total": self.row_total(request, obj),
            "full_list_url": self.full_list_url(obj),
        })


class LocationInlineFormSet(forms.BaseInlineFormSet):
    def clean(self):
        super().clean()
        for form in self.forms:
            location = form.instance
            if location.pk and form.cleaned_data.get("DELETE"):
                current = models.Location.objects.get(pk=location.pk)
                current.validate_deletion(hard=current.is_deleted)


class LocationInline(CappedInlineMixin, SoftDeleteAdminMixin, admin.TabularInline):
    model = models.Location
    show_change_link = True
    formset = LocationInlineFormSet
    verbose_name = _("sub-location")
    verbose_name_plural = _("sub-locations")

    formfield_overrides = {
        TextField: {"widget": forms.Textarea(attrs={"rows": 1, "cols": 30})},
        CharField: {"widget": forms.TextInput(attrs={"size": 20})},
    }

class LocationNumberRangeFormSet(forms.BaseInlineFormSet):
    """Ranges of one location type must not overlap, neither with each other here nor elsewhere, except
    for reservations within a range of a location above."""

    def get_form_kwargs(self, index):
        return {**super().get_form_kwargs(index), "location": self.instance}

    def clean(self):
        super().clean()
        kept = [form for form in self.forms
                if form.cleaned_data and not form.cleaned_data.get("DELETE") and form.cleaned_data.get("type")]
        own = [form.instance.pk for form in self.forms if form.instance.pk]
        for i, form in enumerate(kept):
            first, last, kind = form.cleaned_data["first"], form.cleaned_data["last"], form.cleaned_data["type"]
            error = models.LocationNumberRange.overlap_error(first, last, kind, self.instance, exclude=own)
            if error:
                form.add_error(None, error)
            for other in kept[i + 1:]:
                if (other.cleaned_data["first"] <= last and other.cleaned_data["last"] >= first
                        and other.cleaned_data["type"] == kind):
                    form.add_error(None, _("Overlaps another range of the same location type."))


class LocationNumberRangeForm(forms.ModelForm):
    """A new range starts as the suggestion for the first area-numbered type (LocationNumberRange.suggest)."""

    def __init__(self, *args, location=None, **kwargs):
        super().__init__(*args, **kwargs)
        if self.instance.pk is None and not self.is_bound:
            kind = models.LocationType.objects.filter(area_numbering=True).order_by("name").first()
            suggestion = models.LocationNumberRange.suggest(kind, location)
            if kind:
                self.initial.setdefault("type", kind.pk)
            if suggestion:
                self.initial.setdefault("first", suggestion[0])
                self.initial.setdefault("last", suggestion[1])


class LocationNumberRangeInline(admin.TabularInline):
    model = models.LocationNumberRange
    form = LocationNumberRangeForm
    formset = LocationNumberRangeFormSet
    extra = 0


class LocationAdmin(ClaimOnAddMixin, SoftDeleteAdminMixin, admin.ModelAdmin):
    list_display = ("locatable_identifier", "name", "descriptive_identifier", "deleted_status")
    ordering = ("locatable_identifier",)
    readonly_fields = ("label_image_tag",)
    search_fields = ('locatable_identifier', 'name', 'purpose', 'physical_description')
    list_filter = (DeletedObjectFilter, "type__structure", "axis", "fire_load_free", "outdoor", "responsible_teams")
    autocomplete_fields = ("responsible_teams",)
    actions = ["send_to_printer_action", "send_to_printer_twice_action"]
    inlines = [LocationInline, LocationNumberRangeInline]
    form = AdminLocationForm

    def save_model(self, request, obj, form, change):
        obj._history_actor = request.user
        super().save_model(request, obj, form, change)

    def save_formset(self, request, form, formset, change):
        if formset.model is models.Location:
            for inline_form in formset.forms:
                inline_form.instance._history_actor = request.user
        super().save_formset(request, form, formset, change)

    def get_form(self, request, obj=None, **kwargs):
        form = super().get_form(request, obj, **kwargs)
        form.base_fields["id"].initial = obj.pk if obj else 0
        return form

    def get_inlines(self, request, obj):
        if "_to_field" in request.GET and "_popup" in request.GET:
            return []
        return self.inlines

    def get_urls(self):
        urls = super().get_urls()
        info = self.model._meta.app_label, self.model._meta.model_name
        my_urls = [
            path(
                "<path:object_id>/massadd/",
                MassAddLocationsAdminView.as_view(),
                name="%s_%s_massadd" % info,
            ),
            path(
                "massadd/",
                MassAddLocationsAdminView.as_view(),
                name="%s_%s_massadd" % info,
            ),
            path(
                "<path:object_id>/print-label/",
                self.send_to_printer_view,
                name="%s_%s_print-label" % info,
            ),
        ]
        return my_urls + urls

    @method_decorator(staff_member_required)
    def send_to_printer_view(self, request, object_id=None):
        try:
            models.Location.objects.get(pk=object_id).send_to_printer()
            messages.add_message(request, messages.INFO, _("Sent label to printer."))
        except Exception as e:
            messages.add_message(
                request, messages.ERROR, _("Failed sending label to printer: %(error)s") % {"error": e}
            )
        return redirect(
            reverse(
                "admin:%s_%s_change"
                % (self.model._meta.app_label, self.model._meta.model_name),
                args=[object_id],
            )
        )

    @admin.action(description=_("Print location labels"))
    def send_to_printer_action(self, request, queryset):
        self._print_labels(request, queryset, copies=1)

    @admin.action(description=_("Print location labels twice (2x)"))
    def send_to_printer_twice_action(self, request, queryset):
        self._print_labels(request, queryset, copies=2)

    def _print_labels(self, request, queryset, copies):
        successes, failures = 0, []
        for location in queryset:
            try:
                for _ in range(copies):
                    location.send_to_printer()
                successes += copies
            except Exception as error:
                failures.append(str(error))
        if successes:
            messages.info(request, ngettext("Sent %(count)d label to printer.", "Sent %(count)d labels to printer.",
                                            successes) % {"count": successes})
        for error in set(failures):
            messages.error(
                request, ngettext("Failed sending %(count)d label to printer: %(error)s",
                                  "Failed sending %(count)d labels to printer: %(error)s",
                                  failures.count(error)) % {"count": failures.count(error), "error": error},
            )


admin.site.register(models.Location, LocationAdmin)


class MassAddLocationsForm(forms.Form):
    parent_location = forms.ModelChoiceField(
        label=_("Parent location"),
        queryset=models.Location.active.all(),
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
    location_type = forms.ModelChoiceField(
        label=_("Location type"), required=True, queryset=models.LocationType.objects.all()
    )
    label_template = forms.ModelChoiceField(
        label=_("Overwrite default location label template"),
        required=False,
        queryset=models.LocationLabelTemplate.objects.all(),
    )
    sequence_start = forms.CharField(label=_("Sequence start"), max_length=32)
    count = forms.IntegerField(label=_("Count"))
    physical_description = forms.CharField(label=_("Physical description"), required=False)
    print = forms.BooleanField(label=_("Print location labels"), required=False)
    print_multiple = forms.IntegerField(label=_("Copies per label"), required=False)

    sub_type = forms.ModelChoiceField(
        label=_("Sub-location type"),
        required=False,
        queryset=models.LocationType.objects.all(),
    )
    sub_label_template = forms.ModelChoiceField(
        label=_("Overwrite default sub-location label template"),
        required=False,
        queryset=models.LocationLabelTemplate.objects.all(),
    )
    sub_count = forms.IntegerField(label=_("Sub-location count"), required=False)
    sub_print = forms.BooleanField(label=_("Print sub-location labels"), required=False)

    def clean(self):
        cleaned = super().clean()
        kind, start = cleaned.get("location_type"), cleaned.get("sequence_start")
        if kind and start and not kind.is_valid_start(start):
            self.add_error("sequence_start", _("Use only characters of the sequence of “%(type)s”.") % {"type": kind})
        return cleaned

    def clean_sub_type(self):
        sub_type = self.cleaned_data["sub_type"]
        if sub_type and sub_type.unique and self.cleaned_data["sub_count"]:
            raise ValidationError(
                _("The sub-location type must not be unique if sub-locations are created.")
            )
        return sub_type


class MassAddLocationsAdminView(PermissionRequiredMixin, FormView):
    permission_required = "inventory.add_location"
    form_class = MassAddLocationsForm
    template_name = "admin/inventory/location_massadd.html"
    success_url = "/admin/inventory/location"

    @method_decorator(staff_member_required)
    def dispatch(self, *args, **kwargs):
        return super().dispatch(*args, **kwargs)

    def get(self, request, *args, **kwargs):
        context = self.get_context_data(**kwargs)
        context.update(admin.site.each_context(request))
        return self.render_to_response(context)

    @transaction.atomic
    def form_valid(self, form):
        data = form.cleaned_data
        loc_type = data["location_type"]
        sub_type = data["sub_type"]

        # create locations; codes of unique types that are taken (e.g. older codes of another sequence) are skipped
        generate = loc_type.free_names if loc_type.unique else loc_type.generate_names
        for name, short_name in generate(data["count"], start=data["sequence_start"]):
            location = models.Location.objects.create(
                name=name,
                short_name=short_name,
                type=loc_type,
                parent_location=data["parent_location"],
                label_template=data["label_template"],
                physical_description=data["physical_description"] or "",
            )
            if data["print"]:
                for _ in range(data["print_multiple"] or 1):
                    location.send_to_printer()

            # create sub-locations
            if sub_type is not None:
                for name, short_name in sub_type.free_sublocation_names(location, data["sub_count"]):
                    child = models.Location.objects.create(
                        name=name,
                        short_name=short_name,
                        type=sub_type,
                        parent_location=location,
                        label_template=data["sub_label_template"],
                    )
                    if data["sub_print"]:
                        child.send_to_printer()

        return super().form_valid(form)


class ItemLocationInline(admin.TabularInline):
    model = models.ItemLocation
    extra = 1
    form = AdminItemLocationForm


class ItemBarcodeInline(admin.TabularInline):
    model = models.ItemBarcode
    extra = 1
    formfield_overrides = {
        TextField: {"widget": forms.Textarea(attrs={"rows": 1, "cols": 30})},
    }


class ItemImageInline(admin.TabularInline):
    model = models.ItemImage
    extra = 1
    readonly_fields = ('image_tag', 'ocr_text')

class DocumentInlineMixin:
    """Files are opened through the inventory's download view; storage paths stay hidden."""
    fields = ("description", "file", "internal", "download")
    readonly_fields = ("download",)
    formfield_overrides = {FileField: {"widget": forms.FileInput}}

    @admin.display(description=_("file"))
    def download(self, obj):
        return format_html('<a href="{}">{}</a>', obj.get_absolute_url(), obj.display_name) if obj.pk else "–"


class ItemFileInline(DocumentInlineMixin, admin.TabularInline):
    model = models.ItemFile
    extra = 0


class StockChangeDisplayMixin:
    """Read-only presentation shared by the stock log and its item inline."""

    @admin.display(description=_("change"), ordering="amount")
    def change(self, obj):
        sign, arrow, color = ("+", "arrow-up", "#198754") if obj.is_increase else ("−", "arrow-down", "#dc3545")
        if obj.amount is None:
            amount = _("everything (amount unknown)") if obj.entry_removed else _("unknown amount")
        else:
            amount = ("~" if obj.is_estimate else "") + obj.amount_text(obj.amount)
        return format_html('<span style="color: {}; font-weight: 600">{} {}{}</span>', color, icon(arrow), sign, amount)

    @admin.display(description=_("stock"))
    def stock(self, obj):
        after = _("removed from location") if obj.entry_removed else obj.amount_text(obj.amount_after)
        return f"{obj.amount_text(obj.amount_before)} → {after}"

    @admin.display(description=_("sale value"), ordering="sale_value")
    def sale_value_text(self, obj):
        if obj.sale_value is None:
            return _("unknown")
        return ("~" if obj.is_estimate else "") + f"{obj.sale_value} €"


class StockChangeInline(CappedInlineMixin, StockChangeDisplayMixin, admin.TabularInline):
    model = models.StockChange
    fk_name = "item"
    extra = 0
    can_delete = False
    fields = ("created_at", "location_name", "change", "stock", "reason", "note", "sale_value_text", "actor")
    readonly_fields = fields
    verbose_name_plural = _("stock changes")

    def has_add_permission(self, request, obj=None):
        return False

    def has_change_permission(self, request, obj=None):
        return False


class ItemAdmin(ClaimOnAddMixin, SoftDeleteAdminMixin, admin.ModelAdmin):
    list_display = ("name", "kind", "deleted_status")
    list_filter = (*SoftDeleteAdminMixin.list_filter, "kind")
    search_fields = ("name", "description")
    inlines = [ItemBarcodeInline, ItemImageInline, ItemFileInline, ItemLocationInline, StockChangeInline]
    formfield_overrides = {
        TextField: {"widget": forms.Textarea(attrs={"rows": 3, "cols": 60})},
    }

    def stock_change_context(self, request):
        # Amounts edited here are corrections; they are logged as recounts.
        return stock_changes(actor=request.user, source=models.StockChange.Source.ADMIN,
                             decrease_reason=models.StockChange.Reason.RECOUNT_LOST)

    def save_formset(self, request, form, formset, change):
        with self.stock_change_context(request):
            super().save_formset(request, form, formset, change)

    def delete_model(self, request, obj):
        with self.stock_change_context(request):
            super().delete_model(request, obj)

    def delete_queryset(self, request, queryset):
        with self.stock_change_context(request):
            super().delete_queryset(request, queryset)


admin.site.register(models.Item, ItemAdmin)


@admin.register(models.StockChange)
class StockChangeAdmin(StockChangeDisplayMixin, admin.ModelAdmin):
    list_display = ("created_at", "item_link", "location_name", "change", "reason", "sale_value_text", "actor", "source")
    list_filter = ("direction", "reason", "source", "entry_removed", "created_at")
    date_hierarchy = "created_at"
    search_fields = ("item_name", "location_name", "note", "actor__username")
    fields = (
        "created_at", "actor", "direction", "reason", "note", "source", "item_link", "location_link",
        "change", "stock", "unit_price", "sale_value_text",
    )
    readonly_fields = fields

    @admin.display(description=_("item"), ordering="item_name")
    def item_link(self, obj):
        if obj.item_id is None:
            return obj.item_name
        return format_html('<a href="{}">{}</a>', obj.item.get_admin_url(), obj.item_name)

    @admin.display(description=_("location"), ordering="location_name")
    def location_link(self, obj):
        if obj.location_id is None:
            return obj.location_name
        return format_html('<a href="{}">{}</a>', obj.location.get_admin_url(), obj.location_name)

    def get_queryset(self, request):
        return super().get_queryset(request).select_related("item", "location", "actor")

    # The log is append-only; entries are created by the inventory itself.
    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


class UniqueItemFileInline(DocumentInlineMixin, admin.TabularInline):
    """Files of this unique item only; general ones are on the item."""
    model = models.ItemFile
    fk_name = "unique_item"
    extra = 0


class UniqueItemImageInline(admin.TabularInline):
    """Photos of this unique item only; general ones are on the item."""
    model = models.ItemImage
    fk_name = "unique_item"
    fields = ("image", "description", "is_primary")
    extra = 0


class UniqueItemEventInline(CappedInlineMixin, admin.TabularInline):
    model = models.UniqueItemEvent
    extra = 0
    can_delete = False
    fields = ("created_at", "type", "from_location_name", "to_location_name", "from_owner_name", "to_owner_name",
              "reason", "note", "actor")
    readonly_fields = fields
    verbose_name_plural = _("history")

    def has_add_permission(self, request, obj=None):
        return False

    def has_change_permission(self, request, obj=None):
        return False


@admin.register(models.UniqueItem)
class UniqueItemAdmin(admin.ModelAdmin):
    list_display = ("__str__", "label_code_display", "location", "responsible_team", "disposed_at")
    list_filter = ("item", "responsible_team", ("disposed_at", admin.EmptyFieldListFilter))
    search_fields = ("item__name", "notes", "owner_first_name")
    autocomplete_fields = ("item", "location", "responsible_user", "owner_user")
    readonly_fields = ("label_code_display",)
    inlines = [UniqueItemImageInline, UniqueItemFileInline, UniqueItemEventInline]

    INTERNAL_FIELDS = ("owner_user", "responsible_user", "owner_contact", "purchase_price")

    def get_fieldsets(self, request, obj=None):
        # Owner and responsible person accounts, owner contact and price are internal details.
        if request.user.has_perm("inventory.view_internal_details"):
            return super().get_fieldsets(request, obj)
        return [(name, {**options, "fields": [field for field in options["fields"] if field not in self.INTERNAL_FIELDS]})
                for name, options in super().get_fieldsets(request, obj)]

    def get_readonly_fields(self, request, obj=None):
        fields = super().get_readonly_fields(request, obj)
        # The owner is set on creation; afterwards only with the permission (superusers have it).
        if obj is not None and not request.user.has_perm("inventory.change_uniqueitem_owner"):
            fields = (*fields, "owner_user", "owner_first_name", "owner_contact")
        return fields
    fieldsets = (
        (None, {"fields": ("label_code_display", "item", "location", "usage_level", "warranty_until", "notes")}),
        (_("Responsibility"), {"fields": ("responsible_team", "responsible_user")}),
        (_("Owner"), {"fields": ("owner_user", "owner_first_name", "owner_contact")}),
        (_("Procurement"), {"fields": ("purchase_date", "purchase_price", "procurement_source")}),
        (_("Removal from the inventory"), {"fields": ("disposed_at", "disposal_reason", "disposal_note")}),
    )

    def get_queryset(self, request):
        return annotate_label_code(super().get_queryset(request).select_related("item", "location"))

    @admin.display(description=label_id_naming.NAME, ordering="label_code")
    def label_code_display(self, obj):
        return obj.label_display or "–"

    @transaction.atomic
    def save_model(self, request, obj, form, change):
        obj.save(actor=request.user)
        if change:
            return
        # Every unique item gets its ID right away: the scanned label (?label_id=) or a new one.
        raw = request.GET.get("label_id")
        if raw:
            try:
                lid = label_id_services.claim(label_id_parsing.code_from_scan(raw), obj, request.user)
            except (label_id_core.InvalidLabelId, label_id_services.LabelIdError) as error:
                messages.warning(request, _("%(code)s could not be used (%(error)s); a new ID was generated.")
                                 % {"code": raw, "error": error})
                raw = None
        if not raw:
            lid = label_id_services.generate_and_claim(obj, request.user)
        messages.success(request, _("The ID %(code)s now belongs to %(target)s.") % {"code": lid.display, "target": obj})

    def has_delete_permission(self, request, obj=None):
        # Unique items leave the inventory by being disposed; their history stays.
        return False


@admin.register(models.UniqueItemEvent)
class UniqueItemEventAdmin(admin.ModelAdmin):
    list_display = ("created_at", "unique_item", "type", "from_location_name", "to_location_name", "reason", "actor")
    list_filter = ("type", "reason", "created_at")
    date_hierarchy = "created_at"
    search_fields = ("unique_item__item__name", "from_location_name", "to_location_name", "note", "actor__username")
    readonly_fields = [field.name for field in models.UniqueItemEvent._meta.fields]
    INTERNAL_FIELDS = ("from_owner_user", "from_owner_contact", "to_owner_user", "to_owner_contact")

    def get_fields(self, request, obj=None):
        # Owner accounts and contacts are internal details, as on the unique item.
        fields = super().get_fields(request, obj)
        if request.user.has_perm("inventory.view_internal_details"):
            return fields
        return [field for field in fields if field not in self.INTERNAL_FIELDS]

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
