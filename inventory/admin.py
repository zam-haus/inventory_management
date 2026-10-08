from dal import autocomplete
from django import forms
from django.contrib import admin, messages
from django.contrib.admin.views.decorators import staff_member_required
from django.contrib.auth.mixins import PermissionRequiredMixin
from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import CharField, TextField
from django.shortcuts import redirect
from django.urls import path, reverse
from django.utils.decorators import method_decorator
from django.utils.html import format_html
from django.utils.translation import gettext_lazy as _
from django.views.generic import FormView

from . import models
from .forms import AdminItemLocationForm, AdminLocationForm
from .soft_delete_admin import SoftDeleteAdminMixin
from .stock_log import stock_changes


admin.site.register(models.LocationType)
admin.site.register(models.MeasurementUnit)
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


class LocationInlineFormSet(forms.BaseInlineFormSet):
    def clean(self):
        super().clean()
        for form in self.forms:
            location = form.instance
            if location.pk and form.cleaned_data.get("DELETE"):
                current = models.Location.objects.get(pk=location.pk)
                current.validate_deletion(hard=current.is_deleted)


class LocationInline(SoftDeleteAdminMixin, admin.TabularInline):
    model = models.Location
    formset = LocationInlineFormSet
    verbose_name = "location's child"
    verbose_name_plural = "location's children"

    formfield_overrides = {
        TextField: {"widget": forms.Textarea(attrs={"rows": 1, "cols": 30})},
        CharField: {"widget": forms.TextInput(attrs={"size": 20})},
    }

class LocationAdmin(SoftDeleteAdminMixin, admin.ModelAdmin):
    list_display = ("locatable_identifier", "name", "descriptive_identifier", "deleted_status")
    ordering = ("locatable_identifier",)
    readonly_fields = ("label_image_tag",)
    search_fields = ('locatable_identifier', 'name', 'summary', 'physical_description')
    actions = ["send_to_printer_action", "send_to_printer_twice_action"]
    inlines = [LocationInline]
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
            messages.add_message(request, messages.INFO, "Sent label to printer.")
        except Exception as e:
            messages.add_message(
                request, messages.ERROR, "Failed sending label to printer: {}".format(e)
            )
        return redirect(
            reverse(
                "admin:%s_%s_change"
                % (self.model._meta.app_label, self.model._meta.model_name),
                args=[object_id],
            )
        )

    @admin.action(description="Print location labels")
    def send_to_printer_action(self, request, queryset):
        self._print_labels(request, queryset, copies=1)

    @admin.action(description="Print location labels twice (2x)")
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
            messages.info(request, f"Sent {successes} label(s) to printer.")
        for error in set(failures):
            messages.error(
                request, f"Failed sending {failures.count(error)} label(s) to printer: {error}",
            )


admin.site.register(models.Location, LocationAdmin)


class MassAddLocationsForm(forms.Form):
    parent_location = forms.ModelChoiceField(
        label="Parent location",
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
        label="Location type", required=True, queryset=models.LocationType.objects.all()
    )
    label_template = forms.ModelChoiceField(
        label="Overwrite default location label template",
        required=False,
        queryset=models.LocationLabelTemplate.objects.all(),
    )
    sequence_start = forms.CharField(max_length=32)
    count = forms.IntegerField()
    physical_description = forms.CharField(label=_("Physical description"), required=False)
    print = forms.BooleanField(label="print main lables", required=False)
    print_multiple = forms.IntegerField(label="print multiple", required=False)

    sub_type = forms.ModelChoiceField(
        label="Sub-location type",
        required=False,
        queryset=models.LocationType.objects.all(),
    )
    sub_label_template = forms.ModelChoiceField(
        label="Overwrite default sub-location label template",
        required=False,
        queryset=models.LocationLabelTemplate.objects.all(),
    )
    sub_count = forms.IntegerField(label="Sub-location count", required=False)
    sub_print = forms.BooleanField(label="print sub-location labels", required=False)

    def clean_sub_type(self):
        sub_type = self.cleaned_data["sub_type"]
        if sub_type and sub_type.unique and self.cleaned_data["sub_count"]:
            raise ValidationError(
                "Sub-Type must be a non-unique type, if sub-location count is >0."
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

        # create locations
        for name, short_name in loc_type.generate_names(
            data["count"], start=data["sequence_start"]
        ):
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
                for name, short_name in sub_type.generate_names(data["sub_count"]):
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

class ItemFileInline(admin.TabularInline):
    model = models.ItemFile
    extra = 0


class StockChangeDisplayMixin:
    """Read-only presentation shared by the stock log and its item inline."""

    @admin.display(description=_("change"), ordering="amount")
    def change(self, obj):
        sign, arrow, color = ("+", "↑", "#198754") if obj.is_increase else ("−", "↓", "#dc3545")
        if obj.amount is None:
            amount = _("everything (amount unknown)") if obj.entry_removed else _("unknown amount")
        else:
            amount = ("~" if obj.is_estimate else "") + obj.amount_text(obj.amount)
        return format_html('<span style="color: {}; font-weight: 600">{} {}{}</span>', color, arrow, sign, amount)

    @admin.display(description=_("stock"))
    def stock(self, obj):
        after = _("removed from location") if obj.entry_removed else obj.amount_text(obj.amount_after)
        return f"{obj.amount_text(obj.amount_before)} → {after}"

    @admin.display(description=_("sale value"), ordering="sale_value")
    def sale_value_text(self, obj):
        if obj.sale_value is None:
            return _("unknown")
        return ("~" if obj.is_estimate else "") + f"{obj.sale_value} €"


class StockChangeInline(StockChangeDisplayMixin, admin.TabularInline):
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


class ItemAdmin(SoftDeleteAdminMixin, admin.ModelAdmin):
    list_display = ("name", "deleted_status")
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
