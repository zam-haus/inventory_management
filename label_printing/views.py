import hashlib
import io

from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import login_required, permission_required
from django.contrib.auth.mixins import PermissionRequiredMixin
from django.core.cache import cache
from django.http import Http404, HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils.decorators import method_decorator
from django.views import View
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_safe

from . import dialog, labelary, services
from .render import coloured
from .layouts import get_layout
from .models import LabelMedium, PrintJob


def job_data(job):
    return {
        "id": job.pk,
        "status": job.status,
        "finished": job.is_finished,
        "ok": job.status in (PrintJob.Status.DONE, PrintJob.Status.SENT),
        "message": str(job.message),
    }


@require_safe
@login_required
def job_status(request, pk):
    """How a job is getting on, for the print dialog; users see their own jobs, admins every job."""
    services.expire_stale()
    job = get_object_or_404(PrintJob, pk=pk)
    if job.user_id != request.user.pk and not request.user.has_perm("label_printing.view_printjob"):
        raise Http404
    return JsonResponse(job_data(job))


@method_decorator(never_cache, name="dispatch")
class PrintLabelsView(PermissionRequiredMixin, View):
    """Print labels of a location or an item: the dialog's form as a page (without JavaScript), and where
    the dialog posts to (JSON with the job, which the dialog then follows)."""
    permission_required = "label_printing.print_label"

    def setup(self, request, *args, **kwargs):
        super().setup(request, *args, **kwargs)
        self.subject_type = kwargs["subject_type"]
        self.obj = dialog.subject_object(self.subject_type, kwargs["pk"])

    def render_page(self, form, status=200):
        return render(self.request, "label_printing/print_page.html", {
            "form": form, "object": self.obj, "subject_type": self.subject_type,
            "print_options": dialog.options(self.subject_type, self.obj),
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
                job = services.submit(printer=data["printer"], medium=data["medium"], layout_key=data["layout"],
                                      subject_type=subject_type, subjects=form.subjects(), copies=data["copies"],
                                      user=request.user, request_id=data["request_id"],
                                      quality=data.get("quality") or None)
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
        messages.add_message(request, level, job.message)
        return redirect(self.back_url())


@require_safe
@login_required
@permission_required("label_printing.print_label", raise_exception=True)
def preview(request, subject_type, pk):
    """The first label as PNG, as the printer gets it (dots); ZPL templates rendered by labelary.com
    (204 if that is switched off, 503 if it does not answer)."""
    obj = dialog.subject_object(subject_type, pk)
    medium = get_object_or_404(LabelMedium.objects.select_related("printer", "stock"), pk=request.GET.get("medium") or 0)
    try:
        layout = get_layout(request.GET.get("layout", ""))
    except ValueError:
        raise Http404 from None
    if layout.subject_type != subject_type or not layout.supports(medium.printer, medium):
        raise Http404
    if layout.key.startswith("zpl:") and not settings.PRINT_LABELARY_URL:
        return HttpResponse(status=204)
    if subject_type == "item":
        locations = {str(location.pk): location for location in dialog.item_locations(obj)}
        subject = dialog.ItemAt(obj, locations.get(request.GET.get("location", "")))
    else:
        subject = obj
    try:
        rendered, = services.render(layout, [subject], medium, preview=True)
    except services.PrintError as error:
        return HttpResponse(str(error), status=422, content_type="text/plain; charset=utf-8")
    if rendered.zpl is not None:
        return zpl_preview(rendered.zpl, medium)
    image = rendered.image
    if medium.stock is not None:
        image = coloured(image, medium.stock.background_color, medium.stock.print_color)
    out = io.BytesIO()
    image.save(out, format="PNG", dpi=(medium.printer.dpi, medium.printer.dpi))
    response = HttpResponse(out.getvalue(), content_type="image/png")
    response["Cache-Control"] = "private, max-age=60"
    return response


def zpl_preview(zpl, medium):
    """A ZPL template's label as PNG from labelary.com, kept a day in the cache (labelary limits requests)."""
    dpi = medium.printer.dpi
    key = "label_printing:labelary:" + hashlib.sha256(f"{dpi}:{medium.width_mm}:{medium.height_mm}:{zpl}".encode()).hexdigest()
    png = cache.get(key)
    if png is None:
        try:
            png, _extension = labelary.render(zpl, dpi, (medium.width_mm or 57) / 25.4, (medium.height_mm or 32) / 25.4,
                                              base=settings.PRINT_LABELARY_URL, timeout=8)
        except OSError:  # unreachable, refused, rate limit
            return HttpResponse(status=503)
        cache.set(key, png, 24 * 3600)
    response = HttpResponse(png, content_type="image/png")
    response["Cache-Control"] = "private, max-age=60"
    return response
