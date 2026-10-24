from django import forms
from django.contrib import admin, messages
from django.core.exceptions import PermissionDenied, ValidationError
from django.shortcuts import redirect
from django.template.response import TemplateResponse
from django.urls import path
from django.utils.html import format_html
from django.utils.translation import gettext_lazy as _, gettext, ngettext

from inventory.models import LocationLabelTemplate

from . import services
from .messages import describe
from .image_import import import_images
from .models import LabelImage, LabelMedium, LabelStock, PrintAgent, Printer, PrintJob


@admin.register(LabelStock)
class LabelStockAdmin(admin.ModelAdmin):
    list_display = ("__str__", "language", "size", "colours", "method_text", "material")
    list_filter = ("language", "tape_mm", "method", "ribbon", "background_color", "print_color")
    search_fields = ("code", "name", "description", "background_color", "print_color", "material")
    filter_horizontal = ("label_templates",)
    fieldsets = (
        (None, {"fields": ("language", ("code", "name"), "description", "url")}),
        (_("Brother P-touch"), {"fields": ("tape_mm", ("print_color", "background_color"), "length_m")}),
        (_("Zebra"), {"fields": (("width_mm", "height_mm"), ("method", "ribbon"), "material", "label_templates")}),
    )

    @admin.display(description=_("size"))
    def size(self, stock):
        if stock.tape_mm:
            return stock.get_tape_mm_display()
        return f"{stock.width_mm} × {stock.height_mm} mm" if stock.width_mm else "–"

    @admin.display(description=_("colours"))
    def colours(self, stock):
        return " / ".join(part for part in (stock.print_color, stock.background_color) if part) or "–"

    @admin.display(description=_("printing method"))
    def method_text(self, stock):
        return stock.method_text or "–"


class MultipleFileInput(forms.ClearableFileInput):
    allow_multiple_selected = True


class MultipleFileField(forms.FileField):
    def __init__(self, *args, **kwargs):
        kwargs.setdefault("widget", MultipleFileInput(attrs={"accept": "image/png,image/gif,image/jpeg,image/webp,.zip"}))
        super().__init__(*args, **kwargs)

    def clean(self, data, initial=None):
        items = data if isinstance(data, (list, tuple)) else [data]
        return [super(MultipleFileField, self).clean(item, initial) for item in items]


class ImageImportForm(forms.Form):
    files = MultipleFileField(label=_("Images or ZIP archives"),
                              help_text=_("PNG, GIF, JPEG, WebP; ZIP archives of them, e.g. a set of safety signs."))


@admin.register(LabelImage)
class LabelImageAdmin(admin.ModelAdmin):
    """Images for label designs: stored once, cropped here; designs scale them (docs/label-designs.md)."""
    list_display = ("name", "thumbnail", "pixels", "used_by")
    search_fields = ("name",)
    readonly_fields = ("cropping", "used_by")
    fieldsets = (
        (None, {"fields": ("name", "image", "used_by")}),
        (_("Cut off"), {"fields": ("cropping", ("crop_left", "crop_top", "crop_right", "crop_bottom"))}),
    )
    change_list_template = "label_printing/admin/labelimage_change_list.html"

    class Media:
        js = ("label_printing/label_image.js",)

    @admin.display(description=_("image"))
    def thumbnail(self, image):
        return format_html('<img src="{}" alt="" style="max-height: 48px; max-width: 160px">', image.image.url)

    @admin.display(description=_("size (pixels)"))
    def pixels(self, image):
        try:
            return "{} × {}".format(*image.size())
        except (OSError, ValueError):
            return "–"

    @admin.display(description=_("used by"))
    def used_by(self, image):
        if not image.pk:
            return "–"
        templates = LocationLabelTemplate.objects.filter(description__contains=f'"{image.name}"').order_by("name")
        return ", ".join(template.name for template in templates) or "–"

    @admin.display(description=_("original"))
    def cropping(self, image):
        """The original with the part cut off greyed; drag over it to choose the part (label_image.js)."""
        if not image.pk or not image.image:
            return gettext("Save the image first.")
        try:
            width, height = image.size()
        except (OSError, ValueError):
            return "–"
        return format_html('<div class="label-graphic-crop" data-crop data-width="{}" data-height="{}">'
                           '<img src="{}" alt="" style="max-width: 640px; max-height: 400px"><div data-crop-box></div>'
                           '</div><div class="help">{}</div>', width, height, image.image.url,
                           gettext("Drag over the image to choose the part to keep; the margins below follow."))

    def get_urls(self):
        return [path("import/", self.admin_site.admin_view(self.import_view), name="label_printing_labelimage_import"),
                *super().get_urls()]

    def import_view(self, request):
        if not self.has_add_permission(request):
            raise PermissionDenied
        form = ImageImportForm(request.POST or None, request.FILES or None)
        if request.method == "POST" and form.is_valid():
            created, skipped = import_images(form.cleaned_data["files"])
            if created:
                self.message_user(request, ngettext("%(count)d image imported.", "%(count)d images imported.",
                                                    len(created)) % {"count": len(created)}, messages.SUCCESS)
            for filename, reason in skipped:
                self.message_user(request, f"{filename}: {reason}", messages.WARNING)
            return redirect("admin:label_printing_labelimage_changelist")
        context = {**self.admin_site.each_context(request), "opts": self.model._meta, "form": form,
                   "title": gettext("Import label images")}
        return TemplateResponse(request, "label_printing/admin/image_import.html", context)


class LabelMediumInline(admin.StackedInline):
    model = LabelMedium
    extra = 0
    fields = ("stock", ("name", "is_default"), ("width_mm", "height_mm", "ptouch_tape"),
              ("offset_x", "offset_y", "zpl_darkness"), "quality", "label_templates")
    autocomplete_fields = ("stock",)
    filter_horizontal = ("label_templates",)


@admin.register(Printer)
class PrinterAdmin(admin.ModelAdmin):
    list_display = ("name", "slug", "language", "model", "transport", "agent", "is_active", "is_default", "status",
                    "last_status_at")
    list_filter = ("is_active", "language", "transport", "agent")
    search_fields = ("name", "slug", "uid")
    prepopulated_fields = {"slug": ("name",)}
    readonly_fields = ("status", "last_status_at", "uid", "reported", "discovered_at")
    fieldsets = (
        (None, {"fields": ("name", "slug", ("language", "model", "dpi"), ("is_active", "is_default"))}),
        (_("Connection"), {"fields": ("transport", ("host", "port"), "agent", "reports_status")}),
        (_("Brother P-touch"), {"fields": ("cut", "chain_printing")}),
        (_("Status"), {"fields": ("status", "last_status_at")}),
        (_("Reported by the print agent"), {"fields": ("uid", "reported", "discovered_at")}),
    )
    inlines = [LabelMediumInline]
    actions = ["activate", "test_print", "calibration_print", "check_status"]

    @admin.display(description=_("reported details"))
    def reported(self, printer):
        info = printer.info or {}
        return ", ".join(f"{key}: {value}" for key, value in info.items() if value not in ("", None)) or "–"

    @admin.action(description=_("Activate (printers found by an agent)"))
    def activate(self, request, queryset):
        for printer in queryset:
            try:
                printer.clean()
            except ValidationError as error:
                self.message_user(request, f"{printer}: {' '.join(error.messages)}", messages.ERROR)
                continue
            printer.is_active = True
            printer.save()
            note = ""
            if printer.agent is not None and not printer.agent.is_active:
                note = " " + gettext("Its print agent %(agent)s is not active yet.") % {"agent": printer.agent}
            if not printer.media.exists():
                note += " " + gettext("Add the labels loaded in it.")
            self.message_user(request, gettext("%(printer)s is active.") % {"printer": printer} + note)

    @admin.display(description=_("status"))
    def status(self, printer):
        reason = printer.unavailable_reason()
        return reason or printer.status_text or "–"

    @admin.action(description=_("Print a test label"))
    def test_print(self, request, queryset):
        self.print_own_label(request, queryset, "test", gettext("test label"))

    @admin.action(description=_("Print a calibration label (lines numbered by row)"))
    def calibration_print(self, request, queryset):
        self.print_own_label(request, queryset, "calibration", gettext("calibration label"))

    def print_own_label(self, request, queryset, layout_key, what):
        for printer in queryset:
            try:
                job = services.submit(printer=printer, medium=services.default_medium(printer), layout_key=layout_key,
                                      subject_type="printer", subjects=[printer], user=request.user)
            except services.PrintError as error:
                self.message_user(request, f"{printer}: {error}", messages.ERROR)
                continue
            job.refresh_from_db()
            level = messages.ERROR if job.status == PrintJob.Status.FAILED else messages.INFO
            self.message_user(request, gettext("%(printer)s: %(what)s %(status)s") % {
                "printer": printer, "what": what, "status": job.message}, level)

    @admin.action(description=_("Check the printer status"))
    def check_status(self, request, queryset):
        for printer in queryset:
            result = services.check_status(printer)
            printer.refresh_from_db()
            if result.status == "failed":
                self.message_user(request, f"{printer}: {describe(result.code, result.detail)}",
                                  messages.ERROR)
            else:
                self.message_user(request, f"{printer}: {printer.status_text}")


@admin.register(PrintAgent)
class PrintAgentAdmin(admin.ModelAdmin):
    list_display = ("name", "is_active", "online", "hostname", "address", "last_seen", "version", "printer_list")
    list_filter = ("is_active",)
    readonly_fields = ("uid", "hostname", "address", "registered_at", "last_seen", "version")
    fields = ("name", "is_active", "uid", "hostname", "address", "registered_at", "last_seen", "version")
    actions = ["activate", "new_token"]

    @admin.action(description=_("Activate"))
    def activate(self, request, queryset):
        count = queryset.update(is_active=True)
        self.message_user(request, gettext("%(count)d print agents active. Activate their printers, too.") % {"count": count})

    @admin.display(description=_("online"), boolean=True)
    def online(self, agent):
        return agent.is_online

    @admin.display(description=_("printers"))
    def printer_list(self, agent):
        return ", ".join(printer.name for printer in agent.printers.all())

    def save_model(self, request, obj, form, change):
        token = None if change or obj.token_hash else obj.new_token()
        super().save_model(request, obj, form, change)
        if token:
            self.show_token(request, obj, token)

    def show_token(self, request, agent, token):
        self.message_user(request, format_html(
            _("Token of {agent}, shown only now: <code>{token}</code>. Put it into the agent's token file."),
            agent=agent, token=token), messages.WARNING)

    @admin.action(description=_("Give a new token (the old one stops working)"))
    def new_token(self, request, queryset):
        for agent in queryset:
            if agent.uid:
                self.message_user(request, gettext(
                    "%(agent)s registered itself and keeps its own token; delete it to let it register again.")
                    % {"agent": agent}, messages.WARNING)
                continue
            token = agent.new_token()
            agent.save(update_fields=["token_hash"])
            self.show_token(request, agent, token)


class OutdatedFilter(admin.SimpleListFilter):
    """Printed labels whose location code, item name or price has changed since (newest jobs first)."""
    title = _("labels out of date")
    parameter_name = "outdated"
    LIMIT = 2000

    def lookups(self, request, model_admin):
        return [("1", _("out of date"))]

    def queryset(self, request, queryset):
        if self.value() != "1":
            return queryset
        printed = queryset.filter(status__in=(PrintJob.Status.DONE, PrintJob.Status.SENT),
                                  subject_type__in=("location", "item"))[:self.LIMIT]
        return queryset.filter(pk__in=[job.pk for job in printed if services.outdated_reasons(job)])


@admin.register(PrintJob)
class PrintJobAdmin(admin.ModelAdmin):
    list_display = ("created_at", "subject_label", "printer", "medium", "copies", "status", "message", "user",
                    "claimed_by", "outdated")
    list_filter = (OutdatedFilter, "status", "printer", "subject_type", "created_at")
    actions = ["reprint"]
    search_fields = ("subject_label", "label_code")
    date_hierarchy = "created_at"
    readonly_fields = [field.name for field in PrintJob._meta.fields if field.name != "payload"] + ["message", "outdated"]

    @admin.display(description=_("result"))
    def message(self, job):
        return job.message

    @admin.display(description=_("out of date"))
    def outdated(self, job):
        if job.status not in (PrintJob.Status.DONE, PrintJob.Status.SENT):
            return ""
        return "; ".join(str(reason) for reason in services.outdated_reasons(job))

    @admin.action(description=_("Print these labels again, as they are now"))
    def reprint(self, request, queryset):
        for job in queryset:
            try:
                new = services.reprint(job, request.user)
            except services.PrintError as error:
                self.message_user(request, str(error), messages.ERROR)
                continue
            self.message_user(request, gettext("Job %(old)s printed again as job %(new)s.") % {"old": job.pk, "new": new.pk})

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False
