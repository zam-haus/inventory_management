"""
The print queue: submitting jobs and moving them on (pending → processing → done/sent/failed/expired).

Network printers are served by the Celery task label_printing.tasks.process_job (or at once in the
request without a broker), printers on a print agent by the agent fetching its jobs (api.py).
"""
import time
from datetime import timedelta

from django.conf import settings
from django.db import IntegrityError, transaction
from django.utils import timezone
from django.utils.translation import gettext as _

from inventory.label_ids import services as label_ids
from inventory.models import Item, LabelId, Location
from . import drivers, label_urls, messages
from .devices.io import TcpDevice
from .devices.run import DONE, FAILED, SENT, Result, query_status, run_job
from .layouts import Canvas, LabelTooSmall, NotRendered, get_layout, layouts_for
from .models import PrintJob, Printer, Quality
from .render import squeeze


class PrintError(Exception):
    """A job cannot be submitted; the message is meant for the user."""


RESULT_STATUS = {DONE: PrintJob.Status.DONE, SENT: PrintJob.Status.SENT, FAILED: PrintJob.Status.FAILED}


def build_payload(printer, medium, rendered, copies, quality=Quality.STANDARD):
    """(bytes, pages) for the printer: a ZPL format per label (the image as ^GFA, with the printer settings),
    or one P-touch job with half cuts between the labels."""
    if printer.language == Printer.Language.ZPL:
        formats = [drivers.zpl_raster_label(label.image, copies, (medium.offset_x, medium.offset_y),
                                            medium.zpl_darkness, quality) for label in rendered]
        return "".join(formats).encode("utf-8"), len(rendered) * copies
    return drivers.ptouch_job(printer.model, medium.ptouch_tape, [label.image for label in rendered], copies, quality,
                              medium.offset_y)


def render(layout, subjects, medium, preview=False, user=None, quality=Quality.STANDARD):
    """The labels; for Brother high quality drawn at twice the resolution and squeezed across the tape."""
    canvas = Canvas.for_medium(medium, quality)
    try:
        rendered = [layout.render(subject, canvas, medium, preview=preview, user=user) for subject in subjects]
    except LabelTooSmall:
        raise PrintError(_("The content does not fit on %(medium)s; choose a larger label.") % {"medium": medium.name}) from None
    except NotRendered as error:
        raise PrintError(_("The label template has a mistake: %(error)s") % {"error": error}) from None
    for label in rendered:
        label.image = squeeze(label.image, canvas.squeeze)
    return rendered


def submit(*, printer, medium, layout_key, subject_type, subjects, copies=1, user=None, request_id=None,
           quality=None):
    """Queue labels for `subjects` (all of `subject_type`); a known request_id returns its job instead.
    Without a quality, the medium's."""
    if request_id and (job := PrintJob.objects.filter(request_id=request_id).first()):
        return job
    if medium is None or medium.printer_id != printer.pk:
        raise PrintError(_("Choose a label medium of this printer."))
    if code := printer.unavailable_code():
        raise PrintError(messages.describe(code))
    if not 1 <= copies <= settings.PRINT_MAX_COPIES:
        raise PrintError(_("Print between 1 and %(max)d copies.") % {"max": settings.PRINT_MAX_COPIES})
    if not subjects:
        raise PrintError(_("Nothing to print."))
    try:
        layout = get_layout(layout_key)
    except ValueError:
        raise PrintError(_("Unknown layout.")) from None
    if layout.subject_type != subject_type or not layout.supports(printer, medium):
        raise PrintError(_("This layout does not fit the chosen printer and medium."))
    quality = quality or medium.quality
    if quality not in Quality.values:
        raise PrintError(_("Unknown print quality."))
    if layout.fixed_resolution and quality == Quality.HIGH:
        quality = Quality.STANDARD
    rendered = render(layout, subjects, medium, user=user if user is not None and user.is_authenticated else None,
                      quality=quality)
    payload, pages = build_payload(printer, medium, rendered, copies, quality)
    label = str(subjects[0]) + (f" (+{len(subjects) - 1})" if len(subjects) > 1 else "")
    try:
        with transaction.atomic():
            job = PrintJob.objects.create(
                user=user if user is not None and user.is_authenticated else None,
                printer=printer, medium=medium, layout_key=layout_key, subject_type=subject_type,
                # Label IDs are known by their code (label_code), not a number.
                subject_id=pk if isinstance(pk := getattr(subjects[0], "pk", None), int) else None,
                subject_label=label[:255],
                label_code=rendered[0].label_code, snapshot=[label.snapshot for label in rendered],
                copies=copies, pages=pages, quality=quality, payload=payload, request_id=request_id,
            )
    except IntegrityError:
        if request_id:  # the same request, submitted twice at once
            return PrintJob.objects.get(request_id=request_id)
        raise
    if printer.transport == Printer.Transport.NETWORK:
        from .tasks import process_job

        transaction.on_commit(lambda: process_job.delay(job.pk))
    return job


def expire_stale(now=None):
    """Jobs nobody picked up in time are not printed any more; jobs without a result count as failed."""
    now = now or timezone.now()
    PrintJob.objects.filter(
        status=PrintJob.Status.PENDING, created_at__lt=now - timedelta(seconds=settings.PRINT_JOB_MAX_AGE),
    ).update(status=PrintJob.Status.EXPIRED, code="expired", finished_at=now, payload=None)
    PrintJob.objects.filter(
        status=PrintJob.Status.PROCESSING, claimed_at__lt=now - timedelta(seconds=settings.PRINT_JOB_LEASE),
    ).update(status=PrintJob.Status.FAILED, code="lease_expired", finished_at=now, payload=None)


def claim(job_id, by, agent=None):
    """Take a waiting job; only one worker or agent can, whatever the database."""
    now = timezone.now()
    return PrintJob.objects.filter(
        pk=job_id, status=PrintJob.Status.PENDING,
        created_at__gte=now - timedelta(seconds=settings.PRINT_JOB_MAX_AGE),
    ).update(status=PrintJob.Status.PROCESSING, claimed_by=by, claimed_at=now, agent=agent) == 1


def finish(job, result):
    """Record the result of a job that was being printed; returns the job, reloaded."""
    PrintJob.objects.filter(pk=job.pk, status=PrintJob.Status.PROCESSING).update(
        status=RESULT_STATUS[result.status], code=result.code, detail=result.detail or {},
        printer_status=result.printer_status, finished_at=timezone.now(), payload=None,
    )
    job.printer.remember_status(result.printer_status)
    job.refresh_from_db()
    if job.subject_type == "labelid" and job.status in (PrintJob.Status.DONE, PrintJob.Status.SENT):
        label_ids.mark_printed(entry["code"] for entry in job.snapshot if entry.get("code"))
    return job


def process(job_id, attempts=3, wait=2.0):
    """Print a job on a network printer (Celery task). A printer that was not reached is tried again a
    few times, as nothing was sent; anything else is never repeated, so no label is printed twice."""
    expire_stale()
    if not claim(job_id, "worker"):
        return None
    job = PrintJob.objects.select_related("printer", "medium").get(pk=job_id)
    printer = job.printer
    deadline = job.created_at + timedelta(seconds=settings.PRINT_JOB_MAX_AGE)
    for attempt in range(attempts):
        result = run_job(TcpDevice(printer.host, printer.port), printer.language, bytes(job.payload),
                         expected_tape_mm=job.medium.ptouch_tape if job.medium else None,
                         pages=job.pages, check_status=printer.reports_status)
        if not result.retryable or attempt == attempts - 1 or timezone.now() + timedelta(seconds=wait) > deadline:
            break
        time.sleep(wait)
    return finish(job, result)


def next_for_agent(agent):
    """The oldest waiting job for one of the agent's printers, now claimed by it; None if there is none."""
    expire_stale()
    if not agent.is_active:
        return None
    waiting = PrintJob.objects.filter(
        status=PrintJob.Status.PENDING, printer__agent=agent, printer__transport=Printer.Transport.AGENT,
        printer__is_active=True,
    ).order_by("created_at").values_list("pk", flat=True)
    for job_id in waiting[:10]:
        if claim(job_id, agent.name, agent):
            return PrintJob.objects.select_related("printer", "medium").get(pk=job_id)
    return None


def check_status(printer):
    """The printer's current status as a Result. Network printers are asked now; printers on an agent
    report it with the agent's requests, so their last status is returned."""
    if printer.transport == Printer.Transport.NETWORK:
        result = query_status(TcpDevice(printer.host, printer.port), printer.language)
        printer.remember_status(result.printer_status)
        return result
    if code := printer.unavailable_code():
        return Result(FAILED, code)
    return Result(DONE, printer_status=printer.last_status) if printer.last_status else Result(FAILED, "no_response")


def default_medium(printer):
    return printer.media.order_by("-is_default", "name").first()


def default_target():
    """The default printer and its default medium, for printing from the admin."""
    printer = Printer.objects.filter(is_default=True, is_active=True).first()
    if printer is None:
        raise PrintError(_("No default printer is set up (admin: Label printing → Printers)."))
    medium = default_medium(printer)
    if medium is None:
        raise PrintError(_("The printer %(printer)s has no label medium.") % {"printer": printer})
    return printer, medium


def location_layout(location, printer, medium):
    """The location's own ZPL template or its type's, if offered for the medium; else the first location layout."""
    layouts = layouts_for("location", printer, medium)
    preferred = location.label_template_id or location.type.default_label_template_id
    for layout in layouts:
        if getattr(layout, "template", None) is not None and layout.template.pk == preferred:
            return layout
    if not layouts:
        raise PrintError(_("No location label fits %(medium)s.") % {"medium": medium})
    return layouts[0]


def print_locations(locations, copies=1, user=None, printer=None, medium=None):
    """Labels for locations on the default printer (or the given one); one job per layout used."""
    if printer is None:
        printer, medium = default_target()
    groups = {}
    for location in locations:
        groups.setdefault(location_layout(location, printer, medium).key, []).append(location)
    return [submit(printer=printer, medium=medium, layout_key=key, subject_type="location", subjects=group,
                   copies=copies, user=user) for key, group in groups.items()]


def outdated_reasons(job):
    """Why labels of a printed job no longer match the inventory: changed codes, names or prices."""
    reasons = []
    entries = [entry for entry in job.snapshot if isinstance(entry, dict)]
    locations = Location.objects.in_bulk([entry["id"] for entry in entries if entry.get("type") == "location"])
    items = Item.objects.select_related("measurement_unit").in_bulk(
        [entry["id"] for entry in entries if entry.get("type") == "item"])
    for entry in entries:
        if entry.get("type") == "location" and (location := locations.get(entry["id"])):
            if location.unique_identifier != entry["code"]:
                reasons.append(_("%(old)s is now %(new)s") % {"old": entry["code"], "new": location.unique_identifier})
        elif entry.get("type") == "item" and (item := items.get(entry["id"])):
            if label_urls.price_text(item) != entry.get("price", ""):
                reasons.append(_("%(name)s: price now %(price)s") % {
                    "name": item.name, "price": label_urls.price_text(item) or _("none")})
            elif item.name != entry.get("name"):
                reasons.append(_("%(old)s is now called %(new)s") % {"old": entry.get("name"), "new": item.name})
    return reasons


def subjects_of(job):
    """The current subjects of a job's labels, to print them again."""
    subjects = []
    for entry in job.snapshot:
        if entry.get("type") == "location":
            location = Location.active.filter(pk=entry["id"]).first()
            if location:
                subjects.append(location)
        elif entry.get("type") == "item":
            item = Item.active.filter(pk=entry["id"]).first()
            location = Location.active.filter(pk=entry["location_id"]).first() if entry.get("location_id") else None
            if item:
                subjects.append(label_urls.ItemAt(item, location))
        elif entry.get("type") == "labelid":
            lid = LabelId.objects.filter(pk=entry.get("code")).first()
            if lid:
                subjects.append(lid)
    return subjects


def reprint(job, user=None):
    """The same labels again, as they are now, on the same printer and medium."""
    subjects = subjects_of(job)
    if not subjects or job.medium is None:
        raise PrintError(_("Nothing of job %(job)s can be printed again.") % {"job": job.pk})
    return submit(printer=job.printer, medium=job.medium, layout_key=job.layout_key, subject_type=job.subject_type,
                  subjects=subjects, copies=job.copies, user=user, quality=job.quality)


def print_label_ids(lids, user=None, printer=None, medium=None, copies=1, chunk=20):
    """Label ID labels on the default printer (or the given one), with its first label ID layout;
    jobs of at most `chunk` labels, so long batches are not taken for stuck jobs."""
    if printer is None:
        printer, medium = default_target()
    layouts = layouts_for("labelid", printer, medium)
    if not layouts:
        raise PrintError(_("No label ID label fits %(medium)s.") % {"medium": medium})
    lids = list(lids)
    return [submit(printer=printer, medium=medium, layout_key=layouts[0].key, subject_type="labelid",
                   subjects=lids[start:start + chunk], copies=copies, user=user)
            for start in range(0, len(lids), chunk)]
