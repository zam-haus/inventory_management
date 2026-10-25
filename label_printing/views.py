import base64
import io
import uuid
from pathlib import Path

import markdown

from django.conf import settings
from django.contrib import admin, messages
from django.contrib.admin.views.decorators import staff_member_required
from django.contrib.auth.decorators import login_required, permission_required
from django.contrib.auth.mixins import PermissionRequiredMixin
from django.db import transaction
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

from inventory.models import LocationLabelTemplate
from . import dialog, editor, selection, services
from .design import variables as design_variables
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
        services.dispatch_waiting(refresh=not services.with_broker())  # else the worker asks the printers
        job.refresh_from_db()
    return JsonResponse(job_data(job))


def batch_data(batch, jobs):
    """How the jobs of a print from the overview are getting on, all in one."""
    counts = {status: sum(1 for job in jobs if job.status == status) for status in PrintJob.Status.values}
    printed = counts[PrintJob.Status.DONE] + counts[PrintJob.Status.SENT]
    parts = [gettext("%(printed)d of %(total)d labels printed") % {"printed": printed, "total": len(jobs)}]
    if counts[PrintJob.Status.WAITING]:
        parts.append(gettext("%(count)d waiting for a printer") % {"count": counts[PrintJob.Status.WAITING]})
    failed = counts[PrintJob.Status.FAILED] + counts[PrintJob.Status.EXPIRED]
    if failed:
        parts.append(gettext("%(count)d not printed") % {"count": failed})
    finished = all(job.is_finished for job in jobs)
    return {"id": str(batch), "finished": finished, "ok": finished and not failed,
            "message": ", ".join(parts) + ".", "jobs": [job_data(job) for job in jobs]}


@require_safe
@login_required
def batch_status(request, batch):
    """How the jobs of a print from the overview are getting on (see job_status)."""
    services.expire_stale()
    jobs = PrintJob.objects.filter(batch=batch).order_by("pk")
    if not request.user.has_perm("label_printing.view_printjob"):
        jobs = jobs.filter(user=request.user)
    if not jobs:
        raise Http404
    if any(job.status == PrintJob.Status.WAITING for job in jobs):
        services.dispatch_waiting(refresh=not services.with_broker())  # else the worker asks the printers
    return JsonResponse(batch_data(batch, list(jobs.all())))


@method_decorator(never_cache, name="dispatch")
class PrintLabelsView(PermissionRequiredMixin, View):
    """Print labels of a location (and its sub-locations), an item, a unique item, a label ID or the items at a
    location: the dialog's form as a page (without JavaScript), and where the dialog posts to (JSON with the job,
    or the batch of an overview, which the dialog then follows)."""
    permission_required = "label_printing.print_label"

    def setup(self, request, *args, **kwargs):
        super().setup(request, *args, **kwargs)
        self.subject_type = kwargs["subject_type"]
        self.obj = dialog.subject_object(self.subject_type, kwargs["pk"])

    def render_page(self, form, status=200):
        print_options = dialog.options(self.subject_type, self.obj)
        return render(self.request, "label_printing/print_page.html", {
            "form": form, "object": self.obj, "subject_type": self.subject_type, "print_options": print_options,
            "unavailable": dialog.unavailable_reason(self.subject_type, print_options),
            "options_id": f"label-print-options-{self.subject_type}",
            "print_title": dialog.title(self.subject_type, self.obj),
            "print_heading": dialog.title_html(self.subject_type, self.obj), "back_url": self.back_url(),
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
        jobs = []
        if form.is_valid():
            # A job per label; those of an overview as a batch, followed together
            batch = uuid.uuid5(form.cleaned_data["request_id"], "batch") if form.overview and form.cleaned_data[
                "request_id"] else (uuid.uuid4() if form.overview else None)
            try:
                with transaction.atomic():
                    for outcome, subject, request_id in form.jobs(request.user):
                        jobs.append(services.submit_outcome(
                            outcome, subject_type=outcome.layout.subject_type, subjects=[subject],
                            copies=form.cleaned_data["copies"], user=request.user, request_id=request_id,
                            wait=True, batch=batch))
            except services.PrintError as error:
                jobs = []
                form.add_error(None, str(error))
        if not jobs:
            if wants_json:
                return JsonResponse({"ok": False, "errors": form.errors.get_json_data()}, status=400)
            return self.render_page(form, status=400)
        for job in jobs:
            job.refresh_from_db()  # without a broker it is printed already
        if wants_json:
            if form.overview:
                return JsonResponse({"ok": True, "batch": batch_data(jobs[0].batch, jobs)})
            return JsonResponse({"ok": True, "job": job_data(jobs[0])})
        data = batch_data(jobs[0].batch, jobs) if form.overview else job_data(jobs[0])
        failed = any(job.status == PrintJob.Status.FAILED for job in jobs)
        messages.add_message(request, messages.ERROR if failed else messages.SUCCESS, data["message"])
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
    if (layout.subject_type not in selection.KINDS.get(dialog.label_kind(subject_type), ())
            or not layout.supports(medium.printer, medium)):
        raise Http404
    if subject_type == "item":
        locations = {str(location.pk): location for location in dialog.item_locations(obj)}
        subject = dialog.ItemAt(obj, locations.get(request.GET.get("location", "")))
    else:
        subject = selection.subject_for(layout.subject_type, obj)
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


def template_subject(subject_type, pk, location=None):
    """The subject of a template's preview; items at the given location, else their first."""
    obj = dialog.subject_object(subject_type, pk)
    if subject_type == "item":
        locations = {str(entry.pk): entry for entry in dialog.item_locations(obj)}
        return dialog.ItemAt(obj, locations.get(location or "") or next(iter(locations.values()), None))
    return obj


@require_safe
def template_preview(request, pk, subject_type, subject_pk):
    """A template's label for one location, item, unique item or label ID, without a printer
    (editor.nominal_canvas). Location labels are public like the location page that shows them, and so are those
    of unique items and assigned label IDs: they only show what is on the object anyway. The others for who may
    print (label IDs: or see them)."""
    template = get_object_or_404(LocationLabelTemplate, pk=pk,
                                 subject_type__in=selection.KINDS.get(subject_type, ()))
    subject = template_subject(subject_type, subject_pk, request.GET.get("location"))
    variables = selection.variables_for(template.subject_type, subject)
    if not editor.may_preview(request.user, subject_type, subject):
        raise Http404
    image, _problems, canvas = editor.preview(template.description, variables)
    if image is None:
        raise Http404
    return png_response(image, canvas.dpi,
                        f"{'public' if editor.public_preview(subject_type, subject) else 'private'}, max-age=300")



@login_required
@permission_required("inventory.view_locationlabeltemplate", raise_exception=True)
@require_safe
def template_sample(request, pk):
    """A template's label without a printer for the admin's list of templates: with the record ?record= of its kind
    (inventory.admin picks a few at random), else made up (design.variables.placeholders)."""
    template = get_object_or_404(LocationLabelTemplate, pk=pk)
    variables = design_variables.placeholders(template.subject_type)
    if request.GET.get("record"):
        subject = template_subject(template.subject_type, request.GET["record"])
        if not editor.may_preview(request.user, template.subject_type, subject):
            raise Http404
        variables = selection.variables_for(template.subject_type, subject)
    image, _problems, canvas = editor.preview(template.description, variables)
    if image is None:
        raise Http404
    return png_response(image, canvas.dpi, "private, max-age=3600")


PREVIEW_RECORDS, PREVIEW_CANDIDATES = 5, 40


def preview_records(subject_type, template_pk=None):
    """The newest records to preview a template with: [(name, subject)]; for a saved template of this kind only
    those its saved rules are meant for (among the newest PREVIEW_CANDIDATES)."""
    template = LocationLabelTemplate.objects.filter(pk=template_pk, subject_type=subject_type).first() if str(
        template_pk or "").isdigit() else None
    if template is None:
        return design_variables.sample_subjects(subject_type, PREVIEW_RECORDS)
    records = design_variables.sample_subjects(subject_type, PREVIEW_CANDIDATES)
    meant = selection.meant_for(template, [subject for _name, subject in records])
    return [(name, subject) for name, subject in records if subject in meant][:PREVIEW_RECORDS]


@login_required
@permission_required("inventory.change_locationlabeltemplate", raise_exception=True)
@require_POST
def design_preview(request):
    """The admin's preview while a description is typed (label_template.js): JSON with the label as a PNG data URL,
    the problems by line, the size, and the sample records to choose from: of a saved template those its saved
    rules are meant for."""
    subject_type = request.POST.get("subject_type", "location")
    records = preview_records(subject_type, request.POST.get("template"))
    try:
        variables = selection.variables_for(subject_type, records[int(request.POST.get("record") or 0)][1])
    except (IndexError, ValueError):
        variables = design_variables.placeholders(subject_type)
    medium = LabelMedium.objects.select_related("printer", "stock").filter(pk=request.POST.get("medium") or 0).first()
    image, problems, canvas = editor.preview(request.POST.get("description", ""), variables, medium)
    data = {"problems": [{"line": problem.line, "message": problem.message} for problem in problems],
            "records": [name for name, _subject in records], "image": None}
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
