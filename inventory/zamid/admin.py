from django import forms
from django.contrib import admin, messages
from django.core.exceptions import PermissionDenied
from django.http import HttpResponse
from django.shortcuts import redirect
from django.template.response import TemplateResponse
from django.urls import path, reverse
from django.utils import timezone
from django.utils.html import format_html
from django.utils.translation import gettext, gettext_lazy as _

from ..models import ZamId
from . import core, labels, parsing, services
from .forms import GenerateForm, LabelForm, RetireForm
from .targets import RELATED_TARGETS, TARGET_FIELDS


class ClaimOnAddMixin:
    """
    Admin add views opened with ?zamid=<code> (from the claim page) link the new
    object to that reserved ID right after it is saved.
    """

    def save_model(self, request, obj, form, change):
        super().save_model(request, obj, form, change)
        raw = request.GET.get("zamid")
        if change or not raw:
            return
        try:
            zid = services.claim(parsing.code_from_scan(raw), obj, request.user)
        except core.InvalidZamId:
            messages.error(request, gettext("%(code)s is not a valid ID.") % {"code": raw})
        except services.ZamIdError as e:
            messages.error(request, str(e))
        else:
            messages.success(request, gettext("The ID %(code)s now belongs to %(target)s.") % {"code": zid.display, "target": obj})


class TargetKindFilter(admin.SimpleListFilter):
    title = _("target")
    parameter_name = "target"

    def lookups(self, request, model_admin):
        return [(field, ZamId._meta.get_field(field).verbose_name) for field in TARGET_FIELDS] + [("none", _("none"))]

    def queryset(self, request, queryset):
        if self.value() in TARGET_FIELDS:
            return queryset.filter(**{f"{self.value()}__isnull": False})
        if self.value() == "none":
            return queryset.filter(**{f"{field}__isnull": True for field in TARGET_FIELDS})
        return queryset


class ZamIdAdminForm(forms.ModelForm):
    class Meta:
        model = ZamId
        fields = ["url", "batch", "note"]

    def clean_url(self):
        url = self.cleaned_data.get("url") or None
        if url and url != self.instance.url:
            if self.instance.status != ZamId.Status.RESERVED:
                raise forms.ValidationError(_("Only reserved IDs can be linked to a URL."))
            if not url.lower().startswith(("http://", "https://")):
                raise forms.ValidationError(_("Enter a valid http or https URL."))
        return url


@admin.register(ZamId)
class ZamIdAdmin(admin.ModelAdmin):
    form = ZamIdAdminForm
    list_display = ("display_code", "status", "target_link", "batch", "created_at", "printed_at", "assigned_at")
    list_filter = ("status", TargetKindFilter, "batch")
    list_select_related = RELATED_TARGETS
    search_fields = ("code", "batch", "note", "url")
    date_hierarchy = "created_at"
    actions = ["retire_action", "download_labels_action"]
    change_list_template = "admin/inventory/zamid/change_list.html"
    fieldsets = [
        (None, {"fields": ["label_preview", "display_code", "status", "id_link", "target_link", "url"]}),
        (_("Label"), {"fields": ["batch", "note", "printed_at"]}),
        (_("History"), {"fields": ["created_at", "created_by", "assigned_at", "assigned_by", "retired_at", "retired_by"]}),
    ]
    readonly_fields = ["label_preview", "display_code", "status", "id_link", "target_link", "printed_at",
                       "created_at", "created_by", "assigned_at", "assigned_by", "retired_at", "retired_by"]

    # IDs are created only by generating them, and never deleted.
    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return False

    def has_retire_permission(self, request):
        return request.user.has_perm("inventory.retire_zamid")

    def get_readonly_fields(self, request, obj=None):
        fields = list(super().get_readonly_fields(request, obj))
        can_link = request.user.has_perm("inventory.assign_url_zamid")
        if obj is None or obj.status != ZamId.Status.RESERVED or not can_link:
            fields.append("url")
        return fields

    def get_search_results(self, request, queryset, search_term):
        try:
            code = parsing.code_from_scan(search_term)
        except core.InvalidZamId:
            return super().get_search_results(request, queryset, search_term)
        return queryset.filter(pk=code), False

    def save_model(self, request, obj, form, change):
        ZamId.objects.filter(pk=obj.pk).update(batch=obj.batch, note=obj.note)
        if "url" in form.changed_data and obj.url:
            try:
                services.assign_url(obj.code, obj.url, request.user)
            except services.ZamIdError as e:
                self.message_user(request, str(e), messages.ERROR)

    @admin.display(description=_("ID"), ordering="code")
    def display_code(self, obj):
        return obj.display

    @admin.display(description=_("target"))
    def target_link(self, obj):
        if obj.url:
            return format_html('<a href="{}" rel="noopener">{}</a>', obj.url, obj.url)
        target = obj.target
        if target is None:
            return "–"
        deleted = gettext(" (deleted)") if obj.target_is_deleted else ""
        opts = target._meta
        url = reverse(f"admin:{opts.app_label}_{opts.model_name}_change", args=[target.pk])
        return format_html('{}: <a href="{}">{}</a>{}', opts.verbose_name, url, target, deleted)

    @admin.display(description=_("label"))
    def label_preview(self, obj):
        printer, tape = labels.PREVIEW
        url = f"{reverse('zamid_label', args=[obj.code])}?printer={printer}&tape={tape}"
        return format_html('<a href="{}"><img src="{}" alt="{}" style="height: 160px; max-width: 100%; '
                           'object-fit: contain; outline: 1px solid var(--hairline-color)"></a>', url, url, obj.display)

    @admin.display(description=_("link"))
    def id_link(self, obj):
        if obj.status == ZamId.Status.RESERVED:
            return format_html('<a href="{}">{}</a>', reverse("zamid_claim", args=[obj.code]), gettext("Claim this ID"))
        url = reverse("zamid_resolve", args=[obj.code])
        return format_html('<a href="{}">{}</a>', url, url)

    # ------------------------------------------------------------ generate
    def get_urls(self):
        return [
            path("generate/", self.admin_site.admin_view(self.generate_view), name="inventory_zamid_generate"),
        ] + super().get_urls()

    def generate_view(self, request):
        if not request.user.has_perm("inventory.generate_zamid"):
            raise PermissionDenied
        form = GenerateForm(request.POST or None)
        if request.method == "POST" and form.is_valid():
            created = services.generate_batch(form.cleaned_data["count"], form.cleaned_data["batch"], request.user)
            self.message_user(request, gettext("Generated %(count)d IDs: %(codes)s") % {
                "count": len(created), "codes": ", ".join(zid.display for zid in created)})
            url = reverse("admin:inventory_zamid_changelist")
            if form.cleaned_data["batch"]:
                url += "?" + f"batch={form.cleaned_data['batch']}"
            return redirect(url)
        return TemplateResponse(request, "admin/inventory/zamid/generate.html", {
            **self.admin_site.each_context(request), "opts": self.model._meta, "form": form,
            "title": gettext("Generate ZAM IDs"),
        })

    # ------------------------------------------------------------ actions
    def _intermediate(self, request, queryset, form, action, title, template):
        return TemplateResponse(request, template, {
            **self.admin_site.each_context(request), "opts": self.model._meta, "form": form,
            "queryset": queryset, "action": action, "title": title,
            "action_checkbox_name": admin.helpers.ACTION_CHECKBOX_NAME,
        })

    @admin.action(description=_("Retire selected IDs"), permissions=["retire"])
    def retire_action(self, request, queryset):
        queryset = queryset.exclude(status=ZamId.Status.RETIRED)
        form = RetireForm(request.POST if "apply" in request.POST else None)
        if form.is_valid():
            for zid in queryset:
                services.retire(zid.code, request.user, form.cleaned_data["note"])
            self.message_user(request, gettext("Retired %(count)d IDs.") % {"count": len(queryset)})
            return None
        return self._intermediate(request, queryset, form, "retire_action", gettext("Retire ZAM IDs"),
                                  "admin/inventory/zamid/action_form.html")

    @admin.action(description=_("Download labels (ZIP)"), permissions=["view"])
    def download_labels_action(self, request, queryset):
        form = LabelForm(request.POST if "apply" in request.POST else None)
        if form.is_valid():
            printer, tape = form.cleaned_data["printer"], form.cleaned_data["tape"]
            codes = list(queryset.values_list("code", flat=True))
            archive = labels.render_zip(codes, printer, tape)
            services.mark_printed(codes)
            response = HttpResponse(archive, content_type="application/zip")
            stamp = timezone.localtime().strftime("%Y%m%d-%H%M")
            response["Content-Disposition"] = f'attachment; filename="zamid-labels-{printer}-{tape}mm-{stamp}.zip"'
            return response
        return self._intermediate(request, queryset, form, "download_labels_action", gettext("Download labels"),
                                  "admin/inventory/zamid/action_form.html")
