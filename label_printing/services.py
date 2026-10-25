"""
The print queue: submitting jobs and moving them on (pending → processing → done/sent/failed/expired).

Network printers are served by the Celery task label_printing.tasks.process_job (or at once in the
request without a broker), printers on a print agent by the agent fetching its jobs (api.py).
"""
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta

from django.conf import settings
from django.core.cache import cache
from django.core.exceptions import ObjectDoesNotExist
from django.db import IntegrityError, transaction
from django.utils import timezone
from django.utils.translation import gettext as _

from inventory import change_log
from inventory.label_ids import services as label_ids
from inventory.models import Item, LabelId, Location, UniqueItem
from . import drivers, label_urls, messages, selection
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
                              offset=medium.offset_y, cut=printer.cut, chain=printer.chain_printing)


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
           quality=None, batch=None):
    """Queue labels for `subjects` (all of `subject_type`); a known request_id returns its job instead.
    Without a quality, the layout's (a label template's), else the medium's."""
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
    quality = quality or layout.quality or medium.quality
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
                copies=copies, pages=pages, quality=quality, payload=payload, request_id=request_id, batch=batch,
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
    """Jobs nobody picked up in time are not printed any more, nor those no printer could print while they
    waited; jobs without a result count as failed."""
    now = now or timezone.now()
    PrintJob.objects.filter(
        status=PrintJob.Status.PENDING, ready_at__lt=now - timedelta(seconds=settings.PRINT_JOB_MAX_AGE),
    ).update(status=PrintJob.Status.EXPIRED, code="expired", finished_at=now, payload=None)
    PrintJob.objects.filter(status=PrintJob.Status.WAITING, expires_at__lt=now).update(
        status=PrintJob.Status.EXPIRED, code="wait_expired", finished_at=now)
    PrintJob.objects.filter(
        status=PrintJob.Status.PROCESSING, claimed_at__lt=now - timedelta(seconds=settings.PRINT_JOB_LEASE),
    ).update(status=PrintJob.Status.FAILED, code="lease_expired", finished_at=now, payload=None)


def claim(job_id, by, agent=None):
    """Take a waiting job; only one worker or agent can, whatever the database."""
    now = timezone.now()
    return PrintJob.objects.filter(
        pk=job_id, status=PrintJob.Status.PENDING, payload__isnull=False,
        ready_at__gte=now - timedelta(seconds=settings.PRINT_JOB_MAX_AGE),
    ).update(status=PrintJob.Status.PROCESSING, claimed_by=by, claimed_at=now, agent=agent) == 1


def finish(job, result):
    """Record the result of a job that was being printed; returns the job, reloaded."""
    finished = PrintJob.objects.filter(pk=job.pk, status=PrintJob.Status.PROCESSING).update(
        status=RESULT_STATUS[result.status], code=result.code, detail=result.detail or {},
        printer_status=result.printer_status, finished_at=timezone.now(), payload=None,
    )
    job.printer.remember_status(result.printer_status)
    job.refresh_from_db()
    if job.status in (PrintJob.Status.DONE, PrintJob.Status.SENT):
        if job.subject_type in ("labelid", "uniqueitem"):
            label_ids.mark_printed(entry["code"] for entry in job.snapshot if entry.get("code"))
        selection.remember_job(job)
        if finished:  # once, also if a result is reported twice
            change_log.record_print(job, layout_name(job))
    return job


def layout_name(job):
    try:
        return get_layout(job.layout_key).name
    except ValueError:
        return job.layout_key


def process(job_id, attempts=3, wait=2.0):
    """Print a job on a network printer (Celery task). A printer that was not reached is tried again a
    few times, as nothing was sent; anything else is never repeated, so no label is printed twice."""
    expire_stale()
    if not claim(job_id, "worker"):
        return None
    job = PrintJob.objects.select_related("printer", "medium").get(pk=job_id)
    printer = job.printer
    deadline = job.ready_at + timedelta(seconds=settings.PRINT_JOB_MAX_AGE)
    for attempt in range(attempts):
        result = run_job(TcpDevice(printer.host, printer.port), printer.language, bytes(job.payload),
                         expected_tape_mm=job.medium.ptouch_tape if job.medium else None,
                         expected_length=expected_length(job), pages=job.pages, check_status=printer.reports_status)
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
    ).order_by("ready_at").values_list("pk", flat=True)
    for job_id in waiting[:10]:
        if claim(job_id, agent.name, agent):
            return PrintJob.objects.select_related("printer", "medium").get(pk=job_id)
    return None


# ---------------------------------------------------------------- label outcomes and jobs that wait

def subject_refs(subjects):
    """How to find the subjects again (a waiting job's request)."""
    refs = []
    for subject in subjects:
        if isinstance(subject, label_urls.ItemAt):
            refs.append({"type": "item", "id": subject.item.pk, "location": getattr(subject.location, "pk", None)})
        elif isinstance(subject, LabelId):
            refs.append({"type": "labelid", "code": subject.code})
        elif isinstance(subject, UniqueItem):
            refs.append({"type": "uniqueitem", "id": subject.pk})
        else:
            refs.append({"type": "location", "id": subject.pk})
    return refs


def subjects_of_refs(refs):
    """The subjects again; LookupError if one is gone."""
    subjects = []
    for ref in refs:
        if ref["type"] == "item":
            item = Item.active.filter(pk=ref["id"]).first()
            location = Location.active.filter(pk=ref.get("location")).first() if ref.get("location") else None
            if item is None:
                raise LookupError(ref)
            subjects.append(label_urls.ItemAt(item, location))
        elif ref["type"] == "labelid":
            subjects.append(LabelId.objects.get(code=ref["code"]))
        elif ref["type"] == "uniqueitem":
            subjects.append(UniqueItem.objects.select_related("item", "location").get(pk=ref["id"]))
        else:
            subjects.append(Location.active.get(pk=ref["id"]))
    return subjects


def submit_outcome(outcome, *, subject_type, subjects, copies=1, user=None, request_id=None, quality=None,
                   wait=False, batch=None):
    """Print a label outcome (outcomes.py) on the printer that can print it now; else, with wait, queue a job
    that waits for one (PRINT_WAIT_MAX)."""
    if request_id and (job := PrintJob.objects.filter(request_id=request_id).first()):
        return job
    target = outcome.target()
    if target is not None:
        return submit(printer=target.printer, medium=target.medium, layout_key=outcome.layout.key,
                      subject_type=subject_type, subjects=subjects, copies=copies, user=user, request_id=request_id,
                      quality=quality, batch=batch)
    if not wait or not outcome.can_wait:
        raise PrintError(outcome.why_not or _("No printer can print this label now."))
    return queue_waiting(outcome, subject_type=subject_type, subjects=subjects, copies=copies, user=user,
                         request_id=request_id, quality=quality, batch=batch)


def queue_waiting(outcome, *, subject_type, subjects, copies, user, request_id, quality, batch=None):
    if not 1 <= copies <= settings.PRINT_MAX_COPIES:
        raise PrintError(_("Print between 1 and %(max)d copies.") % {"max": settings.PRINT_MAX_COPIES})
    if quality and quality not in Quality.values:
        raise PrintError(_("Unknown print quality."))
    label = str(subjects[0]) + (f" (+{len(subjects) - 1})" if len(subjects) > 1 else "")
    user = user if user is not None and user.is_authenticated else None
    try:
        job = PrintJob.objects.create(
            user=user, layout_key=outcome.layout.key, subject_type=subject_type,
            subject_id=pk if isinstance(pk := getattr(subjects[0], "pk", None), int) else None,
            subject_label=label[:255], copies=copies, pages=len(subjects) * copies,
            quality=quality or outcome.layout.quality or (outcome.targets[0].medium.quality if outcome.targets
                                                          else Quality.STANDARD),
            status=PrintJob.Status.WAITING,
            outcome=outcome.key, request={"subjects": subject_refs(subjects)}, request_id=request_id, batch=batch,
            expires_at=timezone.now() + timedelta(seconds=settings.PRINT_WAIT_MAX),
        )
    except IntegrityError:
        if request_id:
            return PrintJob.objects.get(request_id=request_id)
        raise
    schedule_dispatch()
    return job


def schedule_dispatch():
    """With a broker, look for printers for waiting jobs again in a few seconds (tasks.dispatch_waiting_jobs);
    once at a time."""
    if not with_broker():
        return  # no broker: the print dialog and the agents' requests look (job_status, api.poll)
    if cache.add("label_printing:dispatch_scheduled", True, timeout=DISPATCH_EVERY):
        from .tasks import dispatch_waiting_jobs

        transaction.on_commit(lambda: dispatch_waiting_jobs.apply_async(countdown=DISPATCH_EVERY))


DISPATCH_EVERY = 10  # seconds between looks for printers for waiting jobs (with a broker)
STATUS_FRESH = 20  # seconds a network printer's status counts as current for waiting jobs


def with_broker():
    """Whether a Celery worker does the network printers' work (jobs, status checks); without, requests do."""
    return not getattr(settings, "CELERY_TASK_ALWAYS_EAGER", False)


def printing_now(printers):
    """The pks of these printers that have a job being printed: nothing else is sent to them meanwhile (a Brother
    is reset before its status is read)."""
    return set(PrintJob.objects.filter(status=PrintJob.Status.PROCESSING, printer__in=printers)
               .values_list("printer_id", flat=True))


def ask_network_printers(printers):
    """Ask these network printers for their status, all at once, and keep it (an unanswered question as the
    error): whether they are online and what is loaded. Printers printing now are left alone. Returns those asked."""
    busy = printing_now(printers)
    printers = [printer for printer in printers if printer.pk not in busy]
    if not printers:
        return []
    with ThreadPoolExecutor(max_workers=len(printers)) as pool:
        results = list(pool.map(lambda printer: query_status(TcpDevice(printer.host, printer.port), printer.language),
                                printers))
    for printer, result in zip(printers, results):
        printer.remember_status(result.printer_status or {"ok": False, "errors": [result.code or "no_response"]})
    return printers


def check_network_printers(now=None):
    """Ask the network printers due for it (tasks.check_network_printers, Celery beat): active ones that report
    their status, whose last status (from a job, the dialog, the admin or the last check) is older than their
    status_interval. Returns those asked."""
    now = now or timezone.now()
    due = [printer for printer in Printer.objects.filter(transport=Printer.Transport.NETWORK, is_active=True,
                                                         reports_status=True, status_interval__gt=0)
           if printer.last_status_at is None
           or printer.last_status_at <= now - timedelta(seconds=printer.status_interval)]
    return ask_network_printers(due)


def refresh_network_statuses(outcomes_):
    """Ask the network printers of these outcomes for their status if it is older than STATUS_FRESH: a job
    waits for a tape to be changed or paper to be loaded."""
    stale = timezone.now() - timedelta(seconds=STATUS_FRESH)
    printers = {target.printer.pk: target.printer for outcome in outcomes_ for target in outcome.targets
                if target.printer.transport == Printer.Transport.NETWORK and target.printer.reports_status
                and not target.printer.unavailable_code()
                and (target.printer.last_status_at is None or target.printer.last_status_at < stale)}
    return bool(ask_network_printers(list(printers.values())))


def dispatch_waiting(refresh=True):
    """Print waiting jobs whose label a printer can print now (rendered for that printer, then queued as usual).
    refresh: ask network printers for their status first (not while answering a print agent, nor in requests
    when a worker does it). Returns the number of jobs dispatched; reschedules itself while jobs wait (with a
    broker)."""
    from . import outcomes

    expire_stale()
    waiting = list(PrintJob.objects.filter(status=PrintJob.Status.WAITING).select_related("user").order_by("created_at")[:20])
    if not waiting:
        return 0
    found = {kind: {outcome.key: outcome for outcome in outcomes.outcomes(kind)}
             for kind in {job.subject_type for job in waiting}}
    layouts = {job.layout_key for job in waiting}
    if refresh and refresh_network_statuses(
            [outcome for kind in found.values() for outcome in kind.values() if outcome.layout.key in layouts]):
        found = {kind: {outcome.key: outcome for outcome in outcomes.outcomes(kind)} for kind in found}
    dispatched = 0
    for job in waiting:
        outcome = outcomes.waited_for(found[job.subject_type], job)
        target = outcome.target() if outcome else None
        if target is None:
            continue
        dispatched += dispatch(job, outcome, target)
    if PrintJob.objects.filter(status=PrintJob.Status.WAITING).exists():
        schedule_dispatch()
    return dispatched


def dispatch(job, outcome, target):
    """Render a waiting job for the target and queue it there; 1 if it was this call that did."""
    now = timezone.now()
    still_waiting = PrintJob.objects.filter(pk=job.pk, status=PrintJob.Status.WAITING)
    try:
        subjects = subjects_of_refs(job.request.get("subjects", []))
    except (LookupError, ObjectDoesNotExist):
        still_waiting.update(status=PrintJob.Status.FAILED, code="subject_gone", finished_at=now)
        return 0
    quality = job.quality
    if outcome.layout.fixed_resolution and quality == Quality.HIGH:
        quality = Quality.STANDARD
    try:
        rendered = render(outcome.layout, subjects, target.medium, user=job.user, quality=quality)
        payload, pages = build_payload(target.printer, target.medium, rendered, job.copies, quality)
    except PrintError as error:
        still_waiting.update(status=PrintJob.Status.FAILED, code="not_rendered", detail={"error": str(error)},
                             finished_at=now)
        return 0
    rows = still_waiting.update(
        status=PrintJob.Status.PENDING, printer=target.printer, medium=target.medium, payload=payload, pages=pages,
        quality=quality, label_code=rendered[0].label_code, snapshot=[label.snapshot for label in rendered],
        ready_at=now)
    if rows and target.printer.transport == Printer.Transport.NETWORK:
        from .tasks import process_job

        transaction.on_commit(lambda: process_job.delay(job.pk))
    return rows


def check_status(printer):
    """The printer's current status as a Result. Network printers are asked now, unless they are printing;
    printers on an agent report it with the agent's requests, so their last status is returned."""
    if printer.transport == Printer.Transport.NETWORK:
        if printing_now([printer]):
            return Result(FAILED, "printing")
        result = query_status(TcpDevice(printer.host, printer.port), printer.language)
        printer.remember_status(result.printer_status)
        return result
    if code := printer.unavailable_code():
        return Result(FAILED, code)
    return Result(DONE, printer_status=printer.last_status) if printer.last_status else Result(FAILED, "no_response")


def default_medium(printer):
    """The labels loaded in a Zebra, else the printer's default medium."""
    if printer.language == Printer.Language.ZPL and printer.loaded_medium_id:
        return printer.loaded_medium
    return printer.media.order_by("-is_default", "name").first()


def expected_length(job):
    """Zebra: (mm, dpi) of the job's labels, to compare with the label length the printer measured; else None."""
    if job.printer.language != Printer.Language.ZPL or not job.medium or not job.medium.height_mm:
        return None
    return [job.medium.height_mm, job.printer.dpi]


def default_target():
    """The default printer and its default medium, for printing from the admin."""
    printer = Printer.objects.filter(is_default=True, is_active=True).first()
    if printer is None:
        raise PrintError(_("No default printer is set up (admin: Label printing → Printers)."))
    medium = default_medium(printer)
    if medium is None:
        raise PrintError(_("The printer %(printer)s has no label medium.") % {"printer": printer})
    return printer, medium


def print_batch(subject_type, subjects, *, outcome_key="", copies=1, user=None, chunk=20):
    """Labels for many subjects of one kind (the admin), printed like the print dialog's overviews: each with the
    label `outcome_key` (a template on labels of one size, outcomes.py) if that template is meant for it, else, without
    one, with the label the dialog preselects for it (its last one, else by the templates' rules). Each label prints on
    a printer that has its labels and can print now, else its job waits for one (submit_outcome). One batch, jobs of at
    most `chunk` labels, so long runs are not taken for stuck jobs. Returns (jobs, the subjects no label is meant
    for)."""
    from . import outcomes

    found = {outcome.key: outcome for kind in selection.KINDS[subject_type]
             for outcome in outcomes.outcomes(kind)}
    chosen = found.get(outcome_key) if outcome_key else None
    if outcome_key and chosen is None:
        raise PrintError(_("This label cannot be printed any more; choose another one."))
    meant = {id(subject) for subject in selection.meant_for(chosen.layout.template, subjects)} if chosen else set()
    groups, skipped = {}, []
    for subject in subjects:
        if chosen is not None:
            outcome = chosen if id(subject) in meant else None
        else:
            ranked = selection.rank(list(found.values()), subject_type, subject)
            outcome = ranked[0].outcome if ranked else None
        if outcome is None:
            skipped.append(subject)
        else:
            groups.setdefault(outcome.key, []).append(subject)
    batch = uuid.uuid4()
    jobs = [submit_outcome(found[key], subject_type=subject_type, subjects=group[start:start + chunk],
                           copies=copies, user=user, wait=True, batch=batch)
            for key, group in groups.items() for start in range(0, len(group), chunk)]
    return jobs, skipped


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
    """Label ID labels on the default printer (or the given one), with the label ID template its rules put first;
    jobs of at most `chunk` labels, so long batches are not taken for stuck jobs."""
    if printer is None:
        printer, medium = default_target()
    lids = list(lids)
    layout = selection.best_layout("labelid", lids[0], layouts_for("labelid", printer, medium)) if lids else None
    if layout is None:
        raise PrintError(_("No label ID label fits %(medium)s.") % {"medium": medium})
    return [submit(printer=printer, medium=medium, layout_key=layout.key, subject_type="labelid",
                   subjects=lids[start:start + chunk], copies=copies, user=user)
            for start in range(0, len(lids), chunk)]
