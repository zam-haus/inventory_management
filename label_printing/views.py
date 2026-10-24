import base64
import io
from pathlib import Path

import markdown

from django.conf import settings
from django.contrib import admin, messages
from django.contrib.admin.views.decorators import staff_member_required
from django.contrib.auth.decorators import login_required, permission_required
from django.contrib.auth.mixins import PermissionRequiredMixin
from django.http import Http404, HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils.decorators import method_decorator
from django.views import View
from django.views.decorators.cache import never_cache
from django.utils.safestring import mark_safe
from django.utils import timezone
from django.utils.formats import date_format
from django.utils.translation import gettext
from django.views.decorators.http import require_POST, require_safe

from inventory.models import LabelId, LocationLabelTemplate
from . import dialog, editor, label_urls, services
from .design import fields as design_fields
from .render import coloured
from .layouts import get_layout
from .models import LabelMedium, PrintJob


def job_data(job):
    data = {
        "id": job.pk,
        "status": job.status,
        "finished": job.is_finished,
        "ok": job.status in (PrintJob.Status.DONE, PrintJob.Status.SENT),
        "message": str(job.message),
        "printer": str(job.printer) if job.printer else "",
    }
    if job.status == PrintJob.Status.WAITING:
        data["message"] = gettext("Waiting for a printer that can print it, until %(time)s.") % {
            "time": date_format(timezone.localtime(job.expires_at), "TIME_FORMAT")}
        data["expires_at"] = job.expires_at.isoformat()
    return data


@require_safe
@login_required
def job_status(request, pk):
    """How a job is getting on, for the print dialog; users see their own jobs, admins every job. A waiting job
    is printed here as soon as a printer can (without a broker nobody else looks while no agent asks)."""
    services.expire_stale()
    job = get_object_or_404(PrintJob, pk=pk)
    if job.user_id != request.user.pk and not request.user.has_perm("label_printing.view_printjob"):
        raise Http404
    if job.status == PrintJob.Status.WAITING:
        services.dispatch_waiting()
        job.refresh_from_db()
    return JsonResponse(job_data(job))


@method_decorator(never_cache, name="dispatch")
class PrintLabelsView(PermissionRequiredMixin, View):
    """Print labels of a location, an item, a label ID or the items at a location: the dialog's form as a page
    (without JavaScript), and where the dialog posts to (JSON with the job, which the dialog then follows)."""
    permission_required = "label_printing.print_label"

    def setup(self, request, *args, **kwargs):
        super().setup(request, *args, **kwargs)
        self.subject_type = kwargs["subject_type"]
        self.obj = dialog.subject_object(self.subject_type, kwargs["pk"])

    def render_page(self, form, status=200):
        return render(self.request, "label_printing/print_page.html", {
            "form": form, "object": self.obj, "subject_type": self.subject_type,
            "print_options": dialog.options(self.subject_type, self.obj),
            "options_id": f"label-print-options-{self.subject_type}",
            "print_title": dialog.title(self.subject_type, self.obj), "back_url": self.back_url(),
        }, status=status)

    def back_url(self):
        if self.subject_type == "labelid":
            return reverse("label_id_info", args=[self.obj.code])
        return self.obj.get_absolute_url()

    def get(self, request, subject_type, pk):
        return self.render_page(dialog.PrintForm(subject_type=subject_type, obj=self.obj))

    def post(self, request, subject_type, pk):
        wants_json = "application/json" in request.headers.get("Accept", "")
        form = dialog.PrintForm(request.POST, subject_type=subject_type, obj=self.obj)
        job = None
        if form.is_valid():
            data = form.cleaned_data
            try:
                job = services.submit_outcome(form.chosen, subject_type=dialog.label_kind(subject_type),
                                              subjects=form.subjects(),
                                              copies=data["copies"], user=request.user, request_id=data["request_id"],
                                              wait=True)
            except services.PrintError as error:
                form.add_error(None, str(error))
        if job is None:
            if wants_json:
                return JsonResponse({"ok": False, "errors": form.errors.get_json_data()}, status=400)
            return self.render_page(form, status=400)
        job.refresh_from_db()  # without a broker it is printed already
        if wants_json:
            return JsonResponse({"ok": True, "job": job_data(job)})
        level = messages.ERROR if job.status == PrintJob.Status.FAILED else messages.SUCCESS
        messages.add_message(request, level, job_data(job)["message"])
        return redirect(self.back_url())


@require_safe
@login_required
@permission_required("label_printing.print_label", raise_exception=True)
def preview(request, subject_type, pk):
    """The first label as PNG, as the printer gets it (dots), in the colours of its label stock."""
    obj = dialog.subject_object(subject_type, pk)
    medium = get_object_or_404(LabelMedium.objects.select_related("printer", "stock"), pk=request.GET.get("medium") or 0)
    try:
        layout = get_layout(request.GET.get("layout", ""))
    except ValueError:
        raise Http404 from None
    if layout.subject_type != dialog.label_kind(subject_type) or not layout.supports(medium.printer, medium):
        raise Http404
    if subject_type == "item":
        locations = {str(location.pk): location for location in dialog.item_locations(obj)}
        subject = dialog.ItemAt(obj, locations.get(request.GET.get("location", "")))
    elif subject_type == "items":  # the first price tag
        subject = dialog.sample_item(obj)
        if subject is None:
            raise Http404
    else:
        subject = obj
    try:
        rendered, = services.render(layout, [subject], medium, preview=True)
    except services.PrintError as error:
        return HttpResponse(str(error), status=422, content_type="text/plain; charset=utf-8")
    image = rendered.image
    if medium.stock is not None:
        image = coloured(image, medium.stock.background_color, medium.stock.print_color)
    return png_response(image, medium.printer.dpi)


def png(image, dpi):
    out = io.BytesIO()
    image.save(out, format="PNG", dpi=(dpi, dpi))
    return out.getvalue()


def png_response(image, dpi, cache_control="private, max-age=60"):
    response = HttpResponse(png(image, dpi), content_type="image/png")
    response["Cache-Control"] = cache_control
    return response


def template_subject(subject_type, pk):
    """(subject, values) for a template's preview; items with their first location."""
    obj = dialog.subject_object(subject_type, pk)
    if subject_type == "location":
        return obj, design_fields.location_values(obj)
    if subject_type == "item":
        locations = dialog.item_locations(obj)
        subject = dialog.ItemAt(obj, locations[0] if locations else None)
        return subject, design_fields.item_values(subject, label_urls.item_label_code(subject, create=False)
                                                  or label_urls.PREVIEW_CODE)
    return obj, design_fields.label_id_values(obj)


@require_safe
def template_preview(request, pk, subject_type, subject_pk):
    """A template's label for one location, item or label ID, without a printer (editor.nominal_canvas). Location
    labels are public like the location page that shows them, and so are those of assigned label IDs: they only
    show what is on the object anyway. The others for who may print (label IDs: or see them)."""
    template = get_object_or_404(LocationLabelTemplate, pk=pk, subject_type=subject_type)
    subject, values = template_subject(subject_type, subject_pk)
    public = subject_type == "location" or (subject_type == "labelid" and subject.status == LabelId.Status.ASSIGNED)
    if not (public or request.user.has_perm("label_printing.print_label")
            or (subject_type == "labelid" and request.user.has_perm("inventory.view_labelid"))):
        raise Http404
    image, _problems, canvas = editor.preview(template.description, subject_type, values)
    if image is None:
        raise Http404
    return png_response(image, canvas.dpi, f"{'public' if public else 'private'}, max-age=300")


@login_required
@permission_required("inventory.change_locationlabeltemplate", raise_exception=True)
@require_POST
def design_preview(request):
    """The admin's preview while a description is typed (label_template.js): JSON with the label as a PNG data URL,
    the problems by line, the size, and the sample records to choose from."""
    subject_type = request.POST.get("subject_type", "location")
    records = design_fields.sample_records(subject_type)
    try:
        values = records[int(request.POST.get("record") or 0)][1]
    except (IndexError, ValueError):
        values = {name: f"{{{name}}}" for name in design_fields.names(subject_type)}
    medium = LabelMedium.objects.select_related("printer", "stock").filter(pk=request.POST.get("medium") or 0).first()
    image, problems, canvas = editor.preview(request.POST.get("description", ""), subject_type, values, medium)
    data = {"problems": [{"line": problem.line, "message": problem.message} for problem in problems],
            "records": [name for name, _values in records], "image": None}
    if image is not None:
        data["image"] = "data:image/png;base64," + base64.b64encode(png(image, canvas.dpi)).decode("ascii")
        data["size"] = gettext("%(width)s × %(height)s dots at %(dpi)s dpi: %(width_mm).1f × %(height_mm).1f mm") % {
            "width": image.width, "height": image.height, "dpi": canvas.dpi,
            "width_mm": image.width * 25.4 / canvas.dpi, "height_mm": image.height * 25.4 / canvas.dpi}
    return JsonResponse(data)


@staff_member_required
def design_help(request):
    """The description language's reference (docs/label-designs.md) in the admin."""
    text = (Path(settings.BASE_DIR) / "docs" / "label-designs.md").read_text(encoding="utf-8")
    html = markdown.markdown(text, extensions=["tables", "fenced_code"])
    return render(request, "label_printing/admin/design_help.html", {
        **admin.site.each_context(request), "title": gettext("How to describe labels"), "content": mark_safe(html)})
