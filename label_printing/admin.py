import json

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
from .models import LabelImage, LabelStock, PrintAgent, Printer, PrintJob, Ribbon


@admin.register(LabelStock)
class LabelStockAdmin(admin.ModelAdmin):
    list_display = ("__str__", "in_stock", "language", "size", "colours", "method_text", "material", "printers")
    list_filter = ("in_stock", "language", "tape_mm", "method", "ribbon", "background_color", "print_color")
    search_fields = ("code", "name", "description", "background_color", "print_color", "material")
    fieldsets = (
        (None, {"fields": ("language", ("code", "name"), "in_stock", "description", "url", "quality")}),
        (_("Colours"), {"fields": (("print_color", "background_color"),),
                        "description": _("A Zebra prints in the colour of its ribbon: give Zebra labels only their "
                                         "background colour.")}),
        (_("Brother P-touch"), {"fields": ("tape_mm", "length_m")}),
        (_("Size"), {"fields": (("width_mm", "height_mm"),)}),
        (_("Zebra"), {"fields": (("core_mm", "winding"), ("method", "ribbon"), "material", "zpl_darkness")}),
    )
    actions = ["mark_in_stock", "mark_not_in_stock"]

    @admin.display(description=_("printers"))
    def printers(self, stock):
        """The active printers that take it."""
        return ", ".join(printer.name for printer in Printer.objects.filter(is_active=True, language=stock.language)
                         if not printer.takes(stock)) or "–"

    @admin.action(description=_("On hand"))
    def mark_in_stock(self, request, queryset):
        self.message_user(request, gettext("%(count)d label materials on hand.") % {"count": queryset.update(in_stock=True)})

    @admin.action(description=_("Not on hand"))
    def mark_not_in_stock(self, request, queryset):
        self.message_user(request, gettext("%(count)d label materials not on hand.") % {
            "count": queryset.update(in_stock=False)})

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


@admin.register(Ribbon)
class RibbonAdmin(admin.ModelAdmin):
    list_display = ("__str__", "material", "width_mm", "color", "loaded_in")
    list_filter = ("material", "width_mm", "color")
    fields = ("material", "width_mm", "color")

    @admin.display(description=_("loaded in"))
    def loaded_in(self, ribbon):
        return ", ".join(printer.name for printer in Printer.objects.filter(loaded_ribbon=ribbon)) or "–"


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



@admin.register(Printer)
class PrinterAdmin(admin.ModelAdmin):
    list_display = ("name", "slug", "language", "model", "transport", "agent", "is_active", "is_default", "status",
                    "last_status_at")
    list_filter = ("is_active", "language", "transport", "agent")
    search_fields = ("name", "slug", "uid")
    prepopulated_fields = {"slug": ("name",)}
    readonly_fields = ("status", "last_status_at", "uid", "reported", "discovered_at", "labels_taken")
    fieldsets = (
        (None, {"fields": ("name", "slug", ("language", "model", "dpi"), ("is_active", "is_default"))}),
        (_("Connection"), {"fields": ("transport", ("host", "port"), "agent", ("reports_status", "status_interval"))}),
        (_("Labels it takes"), {"fields": ("max_width_mm", ("core_mm", "winding"), "thermal_transfer", "labels_taken")}),
        (_("Calibration"), {"fields": (("offset_x", "offset_y"),)}),
        (_("Zebra"), {"fields": ("loaded_medium", "loaded_ribbon")}),
        (_("Brother P-touch"), {"fields": ("cut", "chain_printing")}),
        (_("Status"), {"fields": ("status", "last_status_at")}),
        (_("Reported by the print agent"), {"fields": ("uid", "reported", "discovered_at")}),
    )
    actions = ["activate", "test_print", "calibration_print", "check_status", "resume_held"]

    def get_readonly_fields(self, request, obj=None):
        """The model is fixed: another model is another printer (delete it and add it anew). A Zebra on a print
        agent has its labels and ribbon set on the agent's display, which knows what is in it."""
        fields = super().get_readonly_fields(request, obj)
        if obj is None:
            return fields
        fields = (*fields, "language", "model")
        if obj.transport == Printer.Transport.AGENT:
            fields = (*fields, "loaded_medium", "loaded_ribbon")
        return fields

    def has_print_label_permission(self, request):
        """Printing labels is for who may (label_printing.print_label: the local group), also in the admin."""
        return request.user.has_perm("label_printing.print_label")

    def formfield_for_foreignkey(self, db_field, request, **kwargs):
        if db_field.name == "loaded_medium":  # label material it takes
            printer = Printer.objects.filter(pk=request.resolver_match.kwargs.get("object_id")).first()
            taken = [medium.stock.pk for medium in printer.media(in_stock=False)] if printer else []
            kwargs["queryset"] = LabelStock.objects.filter(pk__in=taken).order_by("-in_stock", "name")
        return super().formfield_for_foreignkey(db_field, request, **kwargs)

    @admin.display(description=_("label material loaded or on hand it takes"))
    def labels_taken(self, printer):
        if not printer.pk:
            return "–"
        return ", ".join(medium.name for medium in sorted(printer.media(), key=lambda medium: medium.name)) or _(
            "none: mark label material as on hand (Label material) or check what the printer takes")

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
            if not printer.media():
                note += " " + services.no_material_text()
            elif printer.language == Printer.Language.ZPL and not printer.loaded_medium_id:
                note += " " + (gettext("Set the labels loaded in it on the print agent's display.")
                               if printer.transport == Printer.Transport.AGENT else gettext("Set the labels loaded in it."))
            self.message_user(request, gettext("%(printer)s is active.") % {"printer": printer} + note)

    @admin.display(description=_("status"))
    def status(self, printer):
        reason = printer.unavailable_reason()
        text = reason or printer.status_text or "–"
        if printer.held_at:
            text = format_html("<strong>⏸ {}</strong> {}", gettext("Held on the print agent.")
                               if not printer.resume_requested else gettext("Goes on with the next poll."), text)
        if problem := printer.ribbon_problem():
            return format_html("{} <strong>⚠ {}</strong>", text, problem)
        return text

    @admin.action(description=_("Go on (printers held on their print agent)"), permissions=["print_label"])
    def resume_held(self, request, queryset):
        for printer in queryset:
            try:
                self.message_user(request, services.resume_printer(printer))
            except services.PrintError as error:
                self.message_user(request, str(error), messages.ERROR)

    @admin.action(description=_("Print a test label"), permissions=["print_label"])
    def test_print(self, request, queryset):
        self.print_own_label(request, queryset, "test", gettext("test label"))

    @admin.action(description=_("Print a calibration label (lines numbered by row)"), permissions=["print_label"])
    def calibration_print(self, request, queryset):
        self.print_own_label(request, queryset, "calibration", gettext("calibration label"))

    def print_own_label(self, request, queryset, layout_key, what):
        for printer in queryset:
            try:
                job = services.print_own_label(printer, layout_key, user=request.user)
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
    readonly_fields = ("hostname", "address", "last_seen", "version")
    fields = ("name", "is_active", "hostname", "address", "last_seen", "version")
    actions = ["activate", "new_token"]

    @admin.action(description=_("Activate"))
    def activate(self, request, queryset):
        count = queryset.update(is_active=True)
        self.message_user(request, gettext("%(count)d print agents active.") % {"count": count})

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
        """The token, once: as the entry of the agent's configuration for this server."""
        entry = json.dumps({"url": request.build_absolute_uri("/").rstrip("/"), "token": token})
        self.message_user(request, format_html(
            _("Token of {agent}, shown only now. Put this into the agent's configuration (config.json, "
              "\"servers\"): <code>{entry}</code>"), agent=agent, entry=entry), messages.WARNING)

    @admin.action(description=_("Give a new token (the old one stops working)"))
    def new_token(self, request, queryset):
        for agent in queryset:
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
    actions = ["reprint", "pause", "resume", "abort"]

    def has_print_label_permission(self, request):
        """Printing labels is for who may (label_printing.print_label: the local group), also in the admin."""
        return request.user.has_perm("label_printing.print_label")
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

    @admin.action(description=_("Print these labels again, as they are now"), permissions=["print_label"])
    def reprint(self, request, queryset):
        for job in queryset:
            try:
                new = services.reprint(job, request.user)
            except services.PrintError as error:
                self.message_user(request, str(error), messages.ERROR)
                continue
            self.message_user(request, gettext("Job %(old)s printed again as job %(new)s.") % {"old": job.pk, "new": new.pk})

    @admin.action(description=_("Pause (jobs a print agent is printing)"), permissions=["print_label"])
    def pause(self, request, queryset):
        self.control(request, queryset, PrintJob.Command.PAUSE)

    @admin.action(description=_("Go on (paused jobs)"), permissions=["print_label"])
    def resume(self, request, queryset):
        self.control(request, queryset, PrintJob.Command.RESUME)

    @admin.action(description=_("Abort"), permissions=["print_label"])
    def abort(self, request, queryset):
        self.control(request, queryset, PrintJob.Command.ABORT)

    def control(self, request, queryset, command):
        for job in queryset:
            try:
                self.message_user(request, services.control(job, command))
            except services.PrintError as error:
                self.message_user(request, str(error), messages.ERROR)

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False
