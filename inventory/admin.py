import hashlib
import json

from django import forms
from django.contrib import admin, messages
from django.contrib.admin.views.decorators import staff_member_required
from django.contrib.auth.models import AnonymousUser
from django.contrib.auth.mixins import PermissionRequiredMixin
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.db.models import CharField, Count, FileField, Q, TextField
from django.forms.models import _get_foreign_key
from django.shortcuts import get_object_or_404, redirect
from django.urls import path, reverse
from django.utils.decorators import method_decorator
from django.utils.html import format_html, format_html_join
from django.utils.http import urlencode
from django.utils.translation import gettext_lazy as _, ngettext
from django.views.generic import FormView
from label_printing import admin_printing, editor as label_editor, selection as label_selection
from label_printing.dialog import BatchPrintForm
from label_printing.design import variables as label_variables
from label_printing.layouts import designs as label_designs
from label_printing.models import LabelMedium

from . import models
from .numbered_location_views import create_numbered_container
from .forms import AdminItemLocationForm, AdminLocationForm
from .soft_delete import SoftDeleteModel
from .soft_delete_admin import DeletedObjectFilter, SoftDeleteAdminMixin
from .actor import current_request
from .change_log import change_context
from .templatetags import change_log as change_log_tags
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
    fields = ("name", "description", "keywords", "parent_category")
    list_display = ("full_name", "item_count")
    search_fields = ("full_name", "description", "keywords")

    def get_queryset(self, request):
        return super().get_queryset(request).annotate(item_count=Count("item", filter=Q(item__is_deleted=False)))

    @admin.display(description=_("items"), ordering="item_count")
    def item_count(self, category):
        return category.item_count
admin.site.register(models.Category, CategoryAdmin)


def stock_values(field):
    """The values label stock has for a field, to choose from (empty: any)."""
    from label_printing.models import LabelStock

    values = sorted({value for value in LabelStock.objects.values_list(field, flat=True) if value},
                    key=str.casefold)
    return [("", _("any"))] + [(value, value) for value in values]


class LocationLabelTemplateForm(forms.ModelForm):
    class Meta:
        model = models.LocationLabelTemplate
        fields = ("name", "subject_type", "quality", "description", "label_stock", "material", "print_color",
                  "background_color")
        widgets = {"description": forms.Textarea(attrs={
            "rows": 24, "cols": 72, "spellcheck": "false", "autocapitalize": "off", "class": "label-description"})}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Material and colours as label stock names them; a value no stock has (any more) stays choosable.
        for name in ("material", "print_color", "background_color"):
            if name in self.fields:
                choices = stock_values(name)
                current = self.initial.get(name) or getattr(self.instance, name, "")
                if current and current not in dict(choices):
                    choices.append((current, current))
                self.fields[name].widget = forms.Select(choices=choices)

    def clean(self):
        data = super().clean()
        if data.get("description"):
            template = models.LocationLabelTemplate(subject_type=data.get("subject_type", "location"),
                                                    description=data["description"])
            _design, problems = label_designs.problems_of(template)
            for problem in problems:
                self.add_error("description", _("Line %(line)s: %(message)s") % {
                    "line": problem.line, "message": problem.message})
        return data


class LabelTemplateRuleInline(admin.TabularInline):
    """Which subjects the template is meant for, and how much (label_printing.selection); without rules: every
    subject of its kind, on request."""
    model = models.LabelTemplateRule
    extra = 0
    fields = ("condition", "priority")
    formfield_overrides = {CharField: {"widget": forms.TextInput(attrs={"size": 70, "spellcheck": "false"})}}


class LocationLabelTemplateAdmin(admin.ModelAdmin):
    """Label templates: a label design written in the description language (docs/label-designs.md), with a
    preview the server renders while it is typed (label_printing/editor.py)."""
    model = models.LocationLabelTemplate
    form = LocationLabelTemplateForm
    list_display = ("name", "sample", "subject_type", "size", "rules_list", "quality", "is_active")
    list_filter = ("is_active", "subject_type", "quality")
    search_fields = ("name", "description")
    fieldsets = (
        (None, {"fields": ("name", "subject_type", "is_active", "quality", "description", "variables_list")}),
        (_("Labels"), {"fields": ("label_stock", ("material", "print_color", "background_color"), "fitting_media"),
                       "description": _("Which labels of its size it prints on: a label stock, else by material and "
                                        "colours (label stock without colours is black on white).")}),
    )
    autocomplete_fields = ("label_stock",)
    actions = ["activate", "deactivate"]
    readonly_fields = ("variables_list", "fitting_media")
    inlines = [LabelTemplateRuleInline]
    change_form_template = "label_printing/admin/label_template_change_form.html"

    class Media:
        js = ("label_printing/label_samples.js",)

    STARTER = (
        "# The size first (width x height in mm, or: label height 12 for any length),\n"
        "# then one element per line; indented elements are laid out in their row or column.\n"
        "# Texts and QR codes are Django templates: {{ location.name }}, {% if %}, filters.\n"
        "label 70 x 32  margin 1.5\n"
        "row  gap 2\n"
        "  qr {{ qr }}  ecc Q\n"
        "  column  gap 1\n"
        "    text {{ location.unique_identifier }}  font mono  bold  invert\n"
        "    text {{ location.descriptive_identifier }}  font condensed  lines 2\n"
    )

    @admin.action(description=_("Activate: offer for printing"))
    def activate(self, request, queryset):
        count = queryset.update(is_active=True)
        self.message_user(request, ngettext("%(count)d label template is active.", "%(count)d label templates are active.",
                                            count) % {"count": count})

    @admin.action(description=_("Deactivate: no longer offer for printing"))
    def deactivate(self, request, queryset):
        count = queryset.update(is_active=False)
        self.message_user(request, ngettext("%(count)d label template is inactive.", "%(count)d label templates are inactive.",
                                            count) % {"count": count})

    def get_queryset(self, request):
        return super().get_queryset(request).prefetch_related("rules")

    @admin.display(description=_("rules"))
    def rules_list(self, obj):
        rules = list(obj.rules.all())
        if not rules:
            return _("every one, on request")
        return format_html_join("", "<div>{}</div>", ((str(rule),) for rule in rules))

    @admin.display(description=_("size"), ordering="label_width")
    def size(self, obj):
        return obj.size_text

    @admin.display(description=_("sample"))
    def sample(self, obj, records=()):
        """The label with each of a few records [(pk, name)] (label_samples.js shows one after another while the
        pointer is on it), else made up; the URLs change with the description, so browsers fetch it anew."""
        version = hashlib.sha1(obj.description.encode()).hexdigest()[:10]
        url = reverse("label_template_sample", args=[obj.pk])
        samples = [(f"{url}?{urlencode({'v': version, 'record': pk})}", name) for pk, name in records]
        samples = samples or [(f"{url}?v={version}", "")]
        return format_html('<img src="{}" title="{}" data-label-samples="{}" alt="" loading="lazy" style="display: '
                           'block; max-height: 4rem; max-width: 16rem; background: #fff; outline: 1px solid '
                           'var(--hairline-color)">', samples[0][0], samples[0][1], json.dumps(samples))

    SAMPLE_CANDIDATES = 40  # random records of a kind to find a template's samples among
    SAMPLES = 5

    def get_list_display(self, request):
        """The samples with up to five random records each that the template is meant for (its rules,
        label_printing.selection), drawn once per kind of template on the page; only records whose labels the
        user may see."""
        candidates = {}  # kind → [(pk, name, the pks of the kind's templates meant for it)]

        def meant(kind):
            if kind not in candidates:
                templates = list(models.LocationLabelTemplate.objects.filter(subject_type=kind))
                candidates[kind] = [
                    (subject.pk, name, set(label_selection.priorities(kind, subject, templates)))
                    for name, subject in label_variables.sample_subjects(kind, self.SAMPLE_CANDIDATES, shuffled=True)
                    if label_editor.may_preview(request.user, kind, subject)]
            return candidates[kind]

        @admin.display(description=_("sample"))
        def sample(obj):
            records = [(pk, name) for pk, name, templates in meant(obj.subject_type) if obj.pk in templates]
            return self.sample(obj, records[:self.SAMPLES])
        return [sample if name == "sample" else name for name in super().get_list_display(request)]

    @admin.display(description=_("variables"))
    def variables_list(self, obj):
        return label_editor.variable_tables()

    @admin.display(description=_("offered on"))
    def fitting_media(self, obj):
        if not obj or not obj.pk:
            return "–"
        media = label_editor.fitting_media(obj)
        if not media:
            return _("No printer has labels of this size.")
        return format_html_join("", "<div>{} – {}</div>", ((medium.printer, medium.name) for medium in media))

    def get_changeform_initial_data(self, request):
        return {"description": self.STARTER, **super().get_changeform_initial_data(request)}

    def render_change_form(self, request, context, add=False, change=False, form_url="", obj=None):
        media = LabelMedium.objects.filter(printer__is_active=True).select_related("printer").order_by("printer__name", "name")
        context["label_editor"] = {
            "preview_url": reverse("label_design_preview"),
            "media": [{"id": medium.pk, "name": f"{medium.printer} – {medium.name}"} for medium in media],
            # A saved template's records to preview: those its saved rules are meant for
            "template": obj.pk if obj and obj.pk else None,
        }
        return super().render_change_form(request, context, add, change, form_url, obj)
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


class ChangeLogDisplayMixin:
    """Read-only presentation shared by the change log and its inlines. Internal values (and the raw changes)
    need inventory.view_internal_details, as on the unique item."""

    @admin.display(description=_("changes"))
    def summary(self, obj):
        request = current_request()
        shown = change_log_tags.describe(obj, None, request.user if request is not None else AnonymousUser())
        parts = []
        if "move" in shown:
            parts.append(format_html("{} → {}", *shown["move"]))
        parts.extend(format_html("{}", line) for line in shown["lines"])
        parts.extend(format_html("{}: {}", change["field"], _("changed (internal)")) if change["internal"]
                     else format_html("{}: {} → {}", change["field"], change["before"], change["after"])
                     for change in shown["changes"])
        return format_html_join("", "<div>{}</div>", ((part,) for part in parts)) or "–"

    @admin.display(description=_("sale value"), ordering="sale_value")
    def sale_value_text(self, obj):
        if obj.sale_value is None:
            return "–"
        return ("~" if obj.details.get("estimated") else "") + f"{obj.sale_value} €"


class ChangeLogInline(CappedInlineMixin, ChangeLogDisplayMixin, admin.TabularInline):
    model = models.ChangeLog
    extra = 0
    can_delete = False
    fields = ("created_at", "action", "subject_label", "summary", "reason", "sale_value_text", "actor")
    readonly_fields = fields
    verbose_name_plural = _("change log")

    def has_add_permission(self, request, obj=None):
        return False

    def has_change_permission(self, request, obj=None):
        return False


class ItemChangeLogInline(ChangeLogInline):
    fk_name = "item"


class UniqueItemChangeLogInline(ChangeLogInline):
    fk_name = "unique_item"


class LocationChangeLogInline(ChangeLogInline):
    fk_name = "location"


class ShownOnLocationFilter(admin.SimpleListFilter):
    """The entries a location's page shows: about it, or with it as the other location (link from the page)."""
    title = _("location page")
    parameter_name = "shown_on_location"

    def lookups(self, request, model_admin):
        location = models.Location.objects.filter(pk=self.value()).first() if (self.value() or "").isdigit() else None
        return [(str(location.pk), location.title_with_code)] if location else []

    def queryset(self, request, queryset):
        if (self.value() or "").isdigit():
            return queryset.filter(Q(location=self.value()) | Q(other_location=self.value()))
        return queryset


@admin.register(models.ChangeLog)
class ChangeLogAdmin(ChangeLogDisplayMixin, admin.ModelAdmin):
    list_display = ("created_at", "action", "subject_link", "summary", "reason", "sale_value_text", "actor_name",
                    "source")
    list_filter = ("action", "source", "reason", "subject_type", "created_at", ShownOnLocationFilter)
    date_hierarchy = "created_at"
    search_fields = ("subject_label", "actor_name", "actor__username", "note")
    fields = ("created_at", "actor", "actor_name", "source", "action", "subject_type", "subject_id", "subject_link",
              "item", "unique_item", "location", "other_location", "summary", "reason", "sale_value_text", "note",
              "changes", "details")
    readonly_fields = fields
    INTERNAL_FIELDS = ("changes", "details")

    def get_fields(self, request, obj=None):
        if request.user.has_perm("inventory.view_internal_details"):
            return self.fields
        return [field for field in self.fields if field not in self.INTERNAL_FIELDS]

    @admin.display(description=_("subject"), ordering="subject_label")
    def subject_link(self, obj):
        target = {"item": obj.item, "uniqueitem": obj.unique_item, "location": obj.location}.get(obj.subject_type)
        if target is None or target.pk != obj.subject_id:
            return obj.subject_label
        return format_html('<a href="{}">{}</a>', target.get_absolute_url(), obj.subject_label)

    def get_queryset(self, request):
        return super().get_queryset(request).select_related(
            "actor", "item", "unique_item__item", "location", "other_location")

    # The log is append-only; entries are written by the inventory itself.
    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


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


class LocationFormerCodeInline(admin.TabularInline):
    """Codes the location had before; they stay blocked and still find it. Removing one frees the code."""
    model = models.LocationFormerCode
    fields = ("code", "note", "created_at")
    readonly_fields = ("created_at",)
    extra = 0


@admin.register(models.LocationFormerCode)
class LocationFormerCodeAdmin(admin.ModelAdmin):
    list_display = ("code", "location", "note", "created_at")
    search_fields = ("code", "note", "location__unique_identifier", "location__name")
    list_filter = (("location", admin.EmptyFieldListFilter),)
    autocomplete_fields = ("location",)
    readonly_fields = ("created_at",)


class LocationAdmin(ClaimOnAddMixin, SoftDeleteAdminMixin, admin.ModelAdmin):
    list_display = ("unique_identifier", "name", "descriptive_identifier", "is_reserved", "deleted_status")
    ordering = ("locatable_identifier",)
    readonly_fields = ("label_image_tag",)
    search_fields = ("unique_identifier", "name", "descriptive_identifier", "purpose", "physical_description",
                     "former_codes__code")
    list_filter = (DeletedObjectFilter, "is_reserved", "type__structure", "axis", "fire_load_free", "outdoor",
                   "responsible_teams")
    autocomplete_fields = ("responsible_teams",)
    actions = ["print_labels_action"]
    inlines = [LocationInline, LocationNumberRangeInline, LocationFormerCodeInline, LocationChangeLogInline]
    form = AdminLocationForm

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
                "reserve/",
                ReserveContainersAdminView.as_view(),
                name="%s_%s_reserve" % info,
            ),
            path(
                "<path:object_id>/print-label/",
                self.print_label_view,
                name="%s_%s_print-label" % info,
            ),
        ]
        return my_urls + urls

    @method_decorator(staff_member_required)
    def print_label_view(self, request, object_id=None):
        if not may_print_labels(request.user):
            raise PermissionDenied
        location = get_object_or_404(models.Location, pk=object_id)
        page = admin_printing.print_page(self, request, [location], "location", title=_("Print label"))
        return page or redirect("admin:inventory_location_change", object_id)

    @admin.action(description=_("Print location labels"), permissions=["print_label"])
    def print_labels_action(self, request, queryset):
        return admin_printing.print_page(self, request, list(queryset), "location", action="print_labels_action")

    def has_print_label_permission(self, request):
        return may_print_labels(request.user)


def may_print_labels(user):
    """Printing labels is for who has label_printing.print_label (the local group, migration
    label_printing.0002), also in the admin."""
    return user.has_perm("label_printing.print_label")


admin.site.register(models.Location, LocationAdmin)


class ReserveContainersForm(forms.Form):
    type = forms.ModelChoiceField(label=_("Container type"), queryset=models.LocationType.objects.none(),
                                  widget=forms.RadioSelect)
    count = forms.IntegerField(label=_("Count"), min_value=1, max_value=200, initial=10)
    print = forms.BooleanField(label=_("Print their labels"), required=False, initial=True,
                               help_text=_("On a printer that has the labels, as in the print dialog."))

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields.update(BatchPrintForm(subject_type="location").fields)  # label and copies
        self.fields["type"].queryset = models.LocationType.numbered_containers()
        # Each type with the code its next container gets, as on the inventory pages.
        self.fields["type"].label_from_instance = lambda kind: f"{kind.name} · {kind.next_free_number()[2]}"


class ReserveContainersAdminView(PermissionRequiredMixin, FormView):
    """Containers (boxes, cartons, pallets) with the next numbers, reserved and hidden until activated on first
    use (ContainerActivateView), and their labels printed in advance."""
    permission_required = "inventory.add_location"
    form_class = ReserveContainersForm
    template_name = "admin/inventory/location_reserve.html"

    @method_decorator(staff_member_required)
    def dispatch(self, *args, **kwargs):
        return super().dispatch(*args, **kwargs)

    def get_context_data(self, **kwargs):
        return {**super().get_context_data(**kwargs), **admin.site.each_context(self.request),
                "opts": models.Location._meta, "title": _("Reserve containers")}

    def get_form(self, form_class=None):
        form = super().get_form(form_class)
        if not may_print_labels(self.request.user):  # printing labels is for who may
            del form.fields["print"], form.fields["label"], form.fields["copies"]
        return form

    def form_valid(self, form):
        data = form.cleaned_data
        try:
            with transaction.atomic():
                reserved = [create_numbered_container(data["type"], reserved=True, actor=self.request.user)
                            for _index in range(data["count"])]
        except ValidationError as error:
            form.add_error(None, " ".join(error.messages))
            return self.form_invalid(form)
        messages.success(self.request, _("%(count)s × %(type)s reserved: %(codes)s.") % {
            "count": len(reserved), "type": data["type"].name,
            "codes": ", ".join(location.short_name for location in reserved)})
        if data.get("print"):
            admin_printing.print_and_report(self.request, "location", reserved, outcome_key=data["label"],
                                            copies=data["copies"])
        url = reverse("admin:inventory_location_changelist")
        return redirect(f"{url}?{urlencode({'id__in': ','.join(str(location.pk) for location in reserved)})}")


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


class ItemAdmin(ClaimOnAddMixin, SoftDeleteAdminMixin, admin.ModelAdmin):
    list_display = ("name", "kind", "category", "deleted_status")
    list_filter = (*SoftDeleteAdminMixin.list_filter, "kind", "category")
    search_fields = ("name", "description")
    inlines = [ItemBarcodeInline, ItemImageInline, ItemFileInline, ItemLocationInline, ItemChangeLogInline]
    formfield_overrides = {
        TextField: {"widget": forms.Textarea(attrs={"rows": 3, "cols": 60})},
    }

    def stock_change_context(self, request):
        # Amounts edited here are corrections; they are logged as recounts.
        return change_context(decrease_reason=models.ChangeLog.Reason.RECOUNT_LOST)

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


@admin.register(models.UniqueItem)
class UniqueItemAdmin(admin.ModelAdmin):
    list_display = ("__str__", "label_code_display", "location", "responsible_team", "disposed_at")
    list_filter = ("item", "responsible_team", ("disposed_at", admin.EmptyFieldListFilter))
    search_fields = ("item__name", "name", "notes", "owner_first_name")
    autocomplete_fields = ("item", "location", "responsible_user", "owner_user")
    readonly_fields = ("label_code_display",)
    inlines = [UniqueItemImageInline, UniqueItemFileInline, UniqueItemChangeLogInline]

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
