"""
The print queue, an offering: every job waits for a printer (waiting → processing → done/sent/failed/expired)
until a printer that is free and can print it takes it (take): a print agent for its printers with each poll
(api.py), the network dispatcher for network printers (offer_to_network_printers; the Celery task
label_printing.tasks.process_job prints, or the request at once without a broker). A job from the print dialog
is rendered when a printer takes it, for that printer and the labels in it; one for a given printer (test
labels, label IDs, reprints) is rendered when submitted and waits for that printer only.
"""
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta

from django.conf import settings
from django.core.cache import cache
from django.core.exceptions import ObjectDoesNotExist
from django.db import IntegrityError, transaction
from django.db.models import Q
from django.utils import timezone
from django.utils.translation import gettext as _

from inventory import change_log
from inventory.label_ids import services as label_ids
from inventory.models import Item, LabelId, Location, UniqueItem
from . import drivers, label_urls, messages, selection
from .devices.io import TcpDevice
from .devices.run import DONE, FAILED, SENT, Result, query_status, run_job
from .layouts import Canvas, LabelTooSmall, NotRendered, get_layout, layouts_for
from .models import LabelStock, Medium, PrintJob, Printer, Quality, Ribbon, ribbon_problem, suitable_ribbon
from .render import squeeze


class PrintError(Exception):
    """A job cannot be submitted; the message is meant for the user."""


RESULT_STATUS = {DONE: PrintJob.Status.DONE, SENT: PrintJob.Status.SENT, FAILED: PrintJob.Status.FAILED}


def build_payload(printer, medium, rendered, copies, quality=Quality.STANDARD):
    """(bytes, pages) for the printer: a ZPL format per label (the image as ^GFA, with the printer settings),
    or one P-touch job with half cuts between the labels."""
    if printer.language == Printer.Language.ZPL:
        formats = [drivers.zpl_raster_label(image, copies, (medium.offset_x, medium.offset_y),
                                            medium.zpl_darkness, quality) for label in rendered for image in label.images]
        return "".join(formats).encode("utf-8"), len(formats) * copies
    return drivers.ptouch_job(printer.model, medium.ptouch_tape, [image for label in rendered for image in label.images],
                              copies, quality,
                              offset=medium.offset_y, cut=printer.cut, chain=printer.chain_printing)


def print_quality(layout, printer, quality):
    """High quality prints as standard where the layout is drawn dot by dot or the printer has no high resolution
    (Brother PT-P700)."""
    if quality == Quality.HIGH and (layout.fixed_resolution or (
            printer.language == Printer.Language.PTOUCH and printer.model in drivers.PTOUCH_MODELS
            and not drivers.ptouch_high_resolution(printer.model))):
        return Quality.STANDARD
    return quality


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
        label.more = [squeeze(image, canvas.squeeze) for image in label.more]
    return rendered


def submit(*, printer, medium, layout_key, subject_type, subjects, copies=1, user=None, request_id=None,
           quality=None, batch=None):
    """Labels for `subjects` (all of `subject_type`) on this printer and medium: rendered now, waiting for the
    printer to take them (PRINT_JOB_MAX_AGE); a known request_id returns its job instead. Without a quality, the
    layout's (a label template's), else the medium's."""
    if request_id and (job := PrintJob.objects.filter(request_id=request_id).first()):
        return job
    if medium is None or medium.printer_id != printer.pk:
        raise PrintError(_("Choose labels for this printer."))
    if reason := printer.takes(medium.stock):
        raise PrintError(reason)
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
    quality = print_quality(layout, printer, quality)
    rendered = render(layout, subjects, medium, user=user if user is not None and user.is_authenticated else None,
                      quality=quality)
    payload, pages = build_payload(printer, medium, rendered, copies, quality)
    label = str(subjects[0]) + (f" (+{len(subjects) - 1})" if len(subjects) > 1 else "")
    try:
        with transaction.atomic():
            job = PrintJob.objects.create(
                user=user if user is not None and user.is_authenticated else None, status=PrintJob.Status.WAITING,
                expires_at=timezone.now() + timedelta(seconds=settings.PRINT_JOB_MAX_AGE),
                printer=printer, medium=medium.stock, layout_key=layout_key, subject_type=subject_type,
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
        offer_soon()
    return job


def expire_stale(now=None):
    """Jobs no printer took in time are not printed any more; jobs without a result count as failed."""
    now = now or timezone.now()
    PrintJob.objects.filter(status=PrintJob.Status.WAITING, expires_at__lt=now).update(
        status=PrintJob.Status.EXPIRED, code="wait_expired", finished_at=now, payload=None)
    PrintJob.objects.filter(
        status=PrintJob.Status.PROCESSING, claimed_at__lt=now - timedelta(seconds=settings.PRINT_JOB_LEASE),
    ).update(status=PrintJob.Status.FAILED, code="lease_expired", finished_at=now, payload=None)


def take(printer, by, agent=None, found=None):
    """Offer the waiting jobs to a free printer: the oldest it can print now is claimed for `by` (and the agent)
    and returned, rendered for this printer (processing); None if none fits. A job for another printer is left
    out; one rendered for its printer when submitted is taken while the printer can print on its labels (its test
    and calibration labels: while it is available at all); one of the print dialog when the printer has the
    labels of its outcome loaded and can print (outcomes.Target). found: outcomes worked out in this request."""
    from . import outcomes

    waiting = list(PrintJob.objects.filter(status=PrintJob.Status.WAITING)
                   .filter(Q(printer__isnull=True) | Q(printer=printer)).select_related("user", "medium")
                   .order_by("ready_at", "pk")[:50])
    if not waiting:
        return None
    found = waiting_outcomes({job.subject_type for job in waiting if job.payload is None}, found)
    for job in waiting:
        if job.payload is not None:
            medium = Medium(printer, job.medium) if job.medium_id else None
            if (printer.unavailable_code() or printer.ribbon_problem() if medium is None or job.layout_key in OWN_LABELS
                    else outcomes.unavailable(printer, medium)[0]):
                continue
            changes = {}
        elif job.layout_key in OWN_LABELS:  # on the labels in the printer now, whatever they are
            medium = default_medium(printer)
            if medium is None or printer.unavailable_code() or printer.ribbon_problem():
                continue
            changes = own_label_for(job, printer, medium)
        else:
            outcome = outcomes.waited_for(found.get(job.subject_type, {}), job, printer)
            target = outcome and next((target for target in outcome.targets
                                       if target.printer.pk == printer.pk and not target.reason), None)
            if target is None:
                continue
            changes = rendered_for(job, outcome, target)
            if changes is None:
                continue  # failed: not to be printed
        now = timezone.now()
        if PrintJob.objects.filter(pk=job.pk, status=PrintJob.Status.WAITING).update(
                status=PrintJob.Status.PROCESSING, claimed_by=by, claimed_at=now, agent=agent, **changes):
            return PrintJob.objects.select_related("printer", "medium").get(pk=job.pk)
    return None


def own_label_for(job, printer, medium):
    """The fields of a printer's test or calibration label rendered for the labels in it now."""
    layout = get_layout(job.layout_key)
    quality = print_quality(layout, printer, layout.quality or medium.quality)
    rendered = render(layout, [printer], medium, user=job.user, quality=quality)
    payload, pages = build_payload(printer, medium, rendered, job.copies, quality)
    return {"medium": medium.stock, "payload": payload, "pages": pages, "quality": quality,
            "snapshot": [label.snapshot for label in rendered]}


def rendered_for(job, outcome, target):
    """The fields of a job of the print dialog rendered for the target (printer and labels); None if it cannot be
    rendered (the job failed: its subject is gone, or the label does not come out)."""
    now = timezone.now()
    still_waiting = PrintJob.objects.filter(pk=job.pk, status=PrintJob.Status.WAITING)
    try:
        subjects = subjects_of_refs(job.request.get("subjects", []))
    except (LookupError, ObjectDoesNotExist):
        still_waiting.update(status=PrintJob.Status.FAILED, code="subject_gone", finished_at=now)
        return None
    quality = print_quality(outcome.layout, target.printer, job.quality)
    try:
        rendered = render(outcome.layout, subjects, target.medium, user=job.user, quality=quality)
        payload, pages = build_payload(target.printer, target.medium, rendered, job.copies, quality)
    except PrintError as error:
        still_waiting.update(status=PrintJob.Status.FAILED, code="not_rendered", detail={"error": str(error)},
                             finished_at=now)
        return None
    return {"printer": target.printer, "medium": target.medium.stock, "layout_key": outcome.layout.key,
            "payload": payload, "pages": pages, "quality": quality, "label_code": rendered[0].label_code,
            "snapshot": [label.snapshot for label in rendered]}


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
        if finished:  # once, also if a result is reported twice
            change_log.record_print(job, layout_name(job))
    return job


def layout_name(job):
    try:
        return get_layout(job.layout_key).name
    except ValueError:
        return job.layout_key


def process(job_id, attempts=3, wait=2.0):
    """Print a job a network printer took (Celery task). A printer that was not reached is tried again a few
    times, as nothing was sent; anything else is never repeated, so no label is printed twice. Then the printer
    takes its next job."""
    expire_stale()
    job = PrintJob.objects.select_related("printer", "medium").filter(
        pk=job_id, status=PrintJob.Status.PROCESSING, agent__isnull=True).first()
    if job is None:
        return None
    printer = job.printer
    deadline = job.claimed_at + timedelta(seconds=settings.PRINT_JOB_MAX_AGE)
    for attempt in range(attempts):
        result = run_job(TcpDevice(printer.host, printer.port), printer.language, bytes(job.payload),
                         expected_tape_mm=expected_tape_mm(job),
                         expected_length=expected_length(job), pages=job.pages, check_status=printer.reports_status)
        if not result.retryable or attempt == attempts - 1 or timezone.now() + timedelta(seconds=wait) > deadline:
            break
        time.sleep(wait)
    job = finish(job, result)
    offer_soon()
    return job


def jobs_for_agent(agent, busy=(), found=None):
    """A job for each of the agent's active printers but the `busy` ones (by uid or short name), each the oldest
    it can print now (take), now claimed by the agent: each printer prints on its own."""
    expire_stale()
    if not agent.is_active:
        return []
    printers = (agent.printers.filter(is_active=True, transport=Printer.Transport.AGENT)
                .exclude(uid__in=busy).exclude(slug__in=busy).select_related("loaded_medium", "loaded_ribbon"))
    found = {} if found is None else found
    return [job for printer in printers if (job := take(printer, agent.name, agent, found))]


def keep_printing(agent, printing):
    """The agent's report of its jobs ({job id: {"paused": bool}}): their lease starts again (they may be paused
    for long, or wait behind another job), paused_at follows the agent, and commands it carried out are
    done. Returns the commands still to send: {job id: command}."""
    now = timezone.now()
    ids = [int(job_id) for job_id in printing if str(job_id).isdigit()]
    jobs = PrintJob.objects.filter(pk__in=ids, agent=agent, status=PrintJob.Status.PROCESSING)
    for job in jobs:
        paused = bool((printing.get(str(job.pk)) or {}).get("paused"))
        changes = {"claimed_at": now}
        if paused != bool(job.paused_at):
            changes["paused_at"] = now if paused else None
        if (job.command, paused) in ((PrintJob.Command.PAUSE, True), (PrintJob.Command.RESUME, False)):
            changes["command"] = ""
        PrintJob.objects.filter(pk=job.pk, status=PrintJob.Status.PROCESSING).update(**changes)
    return dict(PrintJob.objects.filter(agent=agent, status=PrintJob.Status.PROCESSING).exclude(command="")
                .values_list("pk", "command"))


def held_printers(agent, held):
    """The agent's report of its held printers (by uid or short name): held_at follows it, and a "go on" asked for
    in the admin is done once the printer is no longer held. Returns the commands to send: {uid: "resume"}."""
    now, commands = timezone.now(), {}
    for printer in agent.printers.all():
        is_held = printer.uid in held or printer.slug in held
        if is_held and printer.held_at is None:
            Printer.objects.filter(pk=printer.pk).update(held_at=now)
        elif not is_held and (printer.held_at or printer.resume_requested):
            Printer.objects.filter(pk=printer.pk).update(held_at=None, resume_requested=False)
        if is_held and printer.resume_requested:
            commands[printer.uid or printer.slug] = "resume"
    return commands


def resume_printer(printer):
    """Let a printer held on its print agent go on (admin), whoever held it (on the display, or by pausing a job
    since aborted): the agent gets the command with its next poll. Returns a message, or raises PrintError."""
    printer.refresh_from_db()
    if printer.held_at is None:
        raise PrintError(_("%(printer)s is not held.") % {"printer": printer})
    Printer.objects.filter(pk=printer.pk).update(resume_requested=True)
    return _("%(printer)s goes on with the next poll of its print agent.") % {"printer": printer}


def control(job, command, by="admin"):
    """Pause, go on with or abort a job (admin; by "display": a print agent's display, for a waiting job). A job a print agent is printing gets the command with the agent's
    next poll; a job no printer has taken yet is simply not printed when aborted. Returns a message, or raises
    PrintError."""
    job.refresh_from_db()
    if command == PrintJob.Command.ABORT and job.status == PrintJob.Status.WAITING:
        if PrintJob.objects.filter(pk=job.pk, status=job.status).update(
                status=PrintJob.Status.FAILED, code="aborted", detail={"by": by}, finished_at=timezone.now(),
                payload=None):
            return _("Job %(job)s aborted before it was printed.") % {"job": job.pk}
        job.refresh_from_db()
    if job.status != PrintJob.Status.PROCESSING:
        raise PrintError(_("Job %(job)s is %(status)s.") % {"job": job.pk, "status": job.get_status_display()})
    if job.agent_id is None:
        raise PrintError(_("Job %(job)s is printed by the print worker on the network; it cannot be stopped.")
                         % {"job": job.pk})
    PrintJob.objects.filter(pk=job.pk).update(command=command)
    return _("Job %(job)s: the print agent %(agent)s gets the command “%(command)s”.") % {
        "job": job.pk, "agent": job.agent, "command": PrintJob.Command(command).label}


def material_waits(agent, found=None):
    """Labels waiting for one of the agent's printers that is online, but has other labels loaded (or none left):
    [{"printer": uid, "printers": uids, "medium": pk, "material", "reason", "jobs"}], one entry per printer and
    labels, for its display; labels no printer has, loaded or on hand: for the first of them that takes such
    labels (as offered_jobs). printers: that one and, for a Brother, the other Brothers that would do (it reports
    its tape: put into any, they are printed). found: the outcomes jobs_for_agent worked out in the same request
    (waiting_outcomes)."""
    from . import outcomes

    waiting = list(PrintJob.objects.filter(status=PrintJob.Status.WAITING, payload__isnull=True)
                   .order_by("created_at")[:50])
    if not waiting:
        return []
    found = waiting_outcomes({job.subject_type for job in waiting}, found)
    entries, taking, printers = {}, {}, None
    for job in waiting:
        outcome = outcomes.waited_for(found[job.subject_type], job)
        if outcome is None:
            continue
        targets = [target for target in outcome.targets if job.printer_id in (None, target.printer.pk)]
        if any(not target.reason for target in targets):
            continue  # a printer can print it now
        here = [(target.printer, target.medium, short_name(target.medium.stock)) for target in targets
                if target.printer.agent_id == agent.pk and target.missing == "material"]
        if not here and not outcome.targets and not job.printer_id:  # labels no printer has
            printers = active_printers_of(agent) if printers is None else printers
            here = [(printer, medium, labels_to_put_in(outcome.layout, medium))
                    for printer, medium in printers_taking(outcome.layout, printers, taking)
                    if outcomes.unavailable(printer, medium)[1] == "material"]  # online, without these labels
        if not here:
            continue
        printer, medium, material = here[0]
        key = (printer.pk, material)
        if key not in entries:
            stock = medium.stock
            loaded = loaded_stock(printer)
            change = loaded is None or loaded.pk != stock.pk  # else only the ribbon
            problem = ribbon_problem(stock, printer.loaded_ribbon)
            ribbon = suitable_ribbon(stock, printer) if problem else None
            brothers = [other for other, _medium, _material in here
                        if printer.language == other.language == Printer.Language.PTOUCH]
            entries[key] = {
                "printer": printer.uid or printer.slug, "printers": with_alternatives(printer, brothers),
                "medium": stock.pk if change else None,
                "material": material if change else "",
                "loaded": short_name(loaded) if change and loaded else "",
                # these labels with the ribbon in the printer now: which to take out, which to put in
                "ribbon_problem": str(problem), "ribbon_out": str(printer.loaded_ribbon) if problem else "",
                "ribbon_in": str(ribbon) if ribbon else (stock.get_ribbon_display() if problem else ""),
                "jobs": 0}
        entries[key]["jobs"] += 1
    return list(entries.values())


def labels_to_put_in(layout, medium):
    """What to put into the printer for a layout waiting for labels no printer has: the labels' article number or
    name; a Brother, for a template that does not name its label stock: its labels in words ("18-mm-Band"), as
    the tape it gets (of any colour the template allows) is reported by the printer."""
    from . import outcomes

    template = getattr(layout, "template", None)
    if template is not None and not template.label_stock_id and medium.printer.language == Printer.Language.PTOUCH:
        return outcomes.labels_text(template)
    return short_name(medium.stock)


def short_name(stock):
    """Label material as people at a printer know it: its article number (TZe-231), else its name (57 × 32)."""
    return stock.code or stock.name or str(stock)


def loaded_stock(printer):
    """The label material in a printer now (a Zebra's set as loaded, Brother: of the tape it reported), or None."""
    ids = printer.loaded_stock_ids()
    return LabelStock.objects.filter(pk=ids[0]).first() if ids else None  # the likeliest


def agent_printers(agent):
    """What the agent needs to know of its printers: name, whether active, how to check them; a Zebra's media and
    ribbons and which are loaded (to set them on the agent's display), and whether the ribbon suits the labels."""
    answer = {}
    materials = list(LabelStock.Ribbon.values)  # wax, wax/resin, resin
    ribbons = [{"id": ribbon.pk, "name": str(ribbon)} for ribbon in sorted(
        Ribbon.objects.all(), key=lambda ribbon: (ribbon.color != "schwarz", ribbon.color, ribbon.width_mm,
                                                  materials.index(ribbon.material)))]
    for printer in agent.printers.select_related("loaded_medium", "loaded_ribbon"):
        entry = {"name": printer.name, "active": printer.is_active, "language": printer.language,
                 "check_status": printer.reports_status, "offset_x": printer.offset_x, "offset_y": printer.offset_y}
        if printer.language == Printer.Language.PTOUCH:  # the tape it reported, by article number (TZe-231)
            ids = printer.loaded_stock_ids()  # the likeliest first
            stocks = sorted(LabelStock.objects.filter(pk__in=ids), key=lambda stock: ids.index(stock.pk))
            entry["tapes"] = list(dict.fromkeys(stock.code or stock.name for stock in stocks))
        if printer.language == Printer.Language.ZPL:
            # each with whether the ribbon in it now would have to be changed for them
            entry["media"] = [{"id": medium.pk, "name": medium.name,
                               "ribbon_change": bool(ribbon_problem(medium.stock, printer.loaded_ribbon))}
                              for medium in sorted(printer.media(), key=lambda medium: medium.name)]
            entry["thermal_transfer"] = printer.thermal_transfer
            entry["loaded"] = printer.loaded_medium_id
            entry["ribbons"] = ribbons
            entry["ribbon"] = printer.loaded_ribbon_id
            entry["ribbon_problem"] = str(printer.ribbon_problem())
        answer[printer.uid or printer.slug] = entry
    return answer


def offered_jobs(agent, found=None, limit=30):
    """The waiting jobs one of the agent's printers could print, given the right labels (those for one of its
    printers, and those of the print dialog whose labels one of them takes; labels no printer has, loaded or on
    hand: the first of them that takes such labels at all), for its display to show, extend and cancel:
    [{"id", "subject", "label", "printer", "printers", "material", "expires_in"}], the oldest first; printers:
    all of the agent's printers that would do (the first is printer); material: what to put in for it ("" if
    any will do)."""
    from . import outcomes

    printers = {printer.pk: printer for printer in active_printers_of(agent)}
    if not printers:
        return []
    waiting = list(PrintJob.objects.filter(status=PrintJob.Status.WAITING).filter(
        Q(printer__isnull=True) | Q(printer__in=list(printers))).order_by("ready_at", "pk")[:200])
    found = waiting_outcomes({job.subject_type for job in waiting if not job.printer_id}, found)
    now, entries, taking = timezone.now(), [], {}
    for job in waiting:
        if job.printer_id:
            printer, label = printers[job.printer_id], layout_name(job)
            material, others = (short_name(job.medium) if job.medium_id else ""), []
        else:
            outcome = outcomes.waited_for(found.get(job.subject_type, {}), job)
            if outcome is None:
                continue
            here = [(target.printer, short_name(target.medium.stock)) for target in outcome.targets
                    if target.printer.pk in printers]
            if not outcome.targets:  # waits for labels no printer has
                here = [(printer, labels_to_put_in(outcome.layout, medium))
                        for printer, medium in printers_taking(outcome.layout, list(printers.values()), taking)]
            if not here:
                continue
            (printer, material), others = here[0], [other for other, _material in here]
            label = f"{outcome.name} ({outcome.size})"
        entries.append({"id": job.pk, "subject": job.subject_label, "label": str(label),
                        "printer": printer.uid or printer.slug, "printers": with_alternatives(printer, others),
                        "material": str(material),
                        "expires_in": max(0, int((job.expires_at - now).total_seconds())) if job.expires_at else None})
        if len(entries) >= limit:
            break
    return entries


def active_printers_of(agent):
    """The agent's active printers, those that reported a status first (connected to it at some time)."""
    return sorted(agent.printers.filter(is_active=True), key=lambda printer: (
        not printer.last_status, not printer.is_default, printer.name, printer.pk))


def printers_taking(layout, printers, taking):
    """[(printer, labels)]: each of the printers that takes labels the layout prints on, on hand or not, with the
    likeliest such labels (likely_media); taking: the answers so far, by layout key."""
    if layout.key not in taking:
        taking[layout.key] = [(printer, medium) for printer in printers for medium in [next(
            (medium for medium in likely_media(printer) if layout.supports(printer, medium)), None)] if medium]
    return taking[layout.key]


def likely_media(printer):
    """All labels the printer takes, the likeliest to be put in first: loaded, on hand, standard tape, white."""
    loaded = printer.loaded_stock_ids()
    return sorted(printer.media(in_stock=False), key=lambda medium: (
        loaded.index(medium.pk) if medium.pk in loaded else len(loaded), not medium.stock.in_stock,
        not medium.stock.description.startswith("Standard"), medium.stock.background_color not in ("", "weiß"),
        medium.pk))


def with_alternatives(printer, others):
    """The uids of the printer and of the others that would do as well, each once; of those, only printers that
    reported a status (connected to their agent at some time)."""
    uids = [printer.uid or printer.slug]
    for other in others:
        uid = other.uid or other.slug
        if uid not in uids and other.last_status:
            uids.append(uid)
    return uids


RECENT_JOBS = 25
FINISHED = (PrintJob.Status.DONE, PrintJob.Status.SENT, PrintJob.Status.FAILED, PrintJob.Status.EXPIRED)


def concerns(agent, job, printers=None, taking=None):
    """Whether a job is one for the agent's display: for one of its printers, or, without a printer, for labels
    one of its active printers takes (on hand or not)."""
    if job.printer_id:
        return job.printer.agent_id == agent.pk
    try:
        layout = get_layout(job.layout_key)
    except ValueError:
        return False
    printers = active_printers_of(agent) if printers is None else printers
    return bool(printers_taking(layout, printers, {} if taking is None else taking))


def job_entry(job, now=None):
    """A job for the agent's display: {"id", "subject", "label", "printer", "material", "status", "message", "copies",
    "age" (seconds since it finished, or None)}."""
    now = now or timezone.now()
    return {"id": job.pk, "subject": job.subject_label, "label": str(layout_name(job)),
            "printer": (job.printer.uid or job.printer.slug) if job.printer_id else "",
            "material": short_name(job.medium) if job.medium_id else "", "status": job.status,
            "message": str(job.message), "copies": job.copies,
            "age": max(0, int((now - job.finished_at).total_seconds())) if job.finished_at else None}


def recent_jobs(agent, limit=RECENT_JOBS):
    """The agent's last finished jobs (printed, failed, expired), the newest first (job_entry each): those of its
    printers, and those without a printer for labels one of them takes."""
    printers, taking, now = active_printers_of(agent), {}, timezone.now()
    jobs = (PrintJob.objects.filter(status__in=FINISHED).filter(Q(printer__agent=agent) | Q(printer__isnull=True))
            .select_related("printer", "medium").order_by("-finished_at", "-pk")[:4 * limit])
    return [job_entry(job, now) for job in jobs if concerns(agent, job, printers, taking)][:limit]


def preview_target(agent, job):
    """(layout, subjects, labels) to show a job's labels with, as they would print now: on its printer and
    labels, else on labels one of the agent's printers takes; None if they cannot be shown (subjects gone)."""
    try:
        layout = get_layout(job.layout_key)
    except ValueError:
        return None
    if job.layout_key in OWN_LABELS:
        subjects = [job.printer] if job.printer_id else []
    elif job.snapshot:
        subjects = subjects_of(job)
    else:
        try:
            subjects = subjects_of_refs(job.request.get("subjects", []))
        except (LookupError, ObjectDoesNotExist):
            subjects = []
    medium = job_medium(job) or (default_medium(job.printer) if job.printer_id else None)
    if medium is None:
        taken = printers_taking(layout, active_printers_of(agent), {})
        medium = taken[0][1] if taken else None
    if not subjects or medium is None:
        return None
    return layout, subjects, medium


def again(job):
    """A job's labels again, from the agent's display; the new job. A printed one on its printer and labels, as
    they are now (reprint); a test or calibration label as one; one that never got a printer (expired) back into
    the queue. PrintError if it cannot be."""
    if job.layout_key in OWN_LABELS and job.printer_id:
        return print_own_label(job.printer, job.layout_key)
    if job.printer_id and job.medium_id and job.snapshot:
        return reprint(job)
    if job.outcome and job.request.get("subjects"):
        try:
            subjects_of_refs(job.request["subjects"])
        except (LookupError, ObjectDoesNotExist):
            raise PrintError(_("Nothing of job %(job)s can be printed again.") % {"job": job.pk}) from None
        new = PrintJob.objects.create(
            printer=job.printer, layout_key=job.layout_key, subject_type=job.subject_type, subject_id=job.subject_id,
            subject_label=job.subject_label, copies=job.copies, pages=job.pages, quality=job.quality,
            status=PrintJob.Status.WAITING, outcome=job.outcome, request={"subjects": job.request["subjects"]},
            expires_at=timezone.now() + timedelta(seconds=settings.PRINT_WAIT_MAX))
        offer_soon()
        return new
    raise PrintError(_("Nothing of job %(job)s can be printed again.") % {"job": job.pk})


def offered_to(agent, job):
    """Whether a waiting job is one the agent's display may extend or cancel (offered_jobs)."""
    return job.status == PrintJob.Status.WAITING and any(entry["id"] == job.pk for entry in offered_jobs(agent, limit=200))


def extend(job):
    """A waiting job waits PRINT_WAIT_MAX longer (from the agent's display), at most twelve times that from now."""
    now = timezone.now()
    step = timedelta(seconds=settings.PRINT_WAIT_MAX)
    expires_at = min(max(job.expires_at or now, now) + step, now + 12 * step)
    PrintJob.objects.filter(pk=job.pk, status=PrintJob.Status.WAITING).update(expires_at=expires_at)
    return expires_at


OFFSET_LIMIT = 999  # dots


def set_offsets(printer, offset_x, offset_y):
    """The printer's calibration (from its agent's display after a calibration label), in dots."""
    for value in (offset_x, offset_y):
        if not isinstance(value, int) or isinstance(value, bool) or abs(value) > OFFSET_LIMIT:
            raise PrintError(_("Offsets are whole numbers of dots between -%(limit)d and %(limit)d.") % {
                "limit": OFFSET_LIMIT})
    Printer.objects.filter(pk=printer.pk).update(offset_x=offset_x, offset_y=offset_y)
    printer.offset_x, printer.offset_y = offset_x, offset_y


def set_ribbon(printer, ribbon):
    """The ribbon now in a Zebra (set on its print agent's display), or None: none. Jobs waiting for its colour
    are taken with the agent's next poll."""
    Printer.objects.filter(pk=printer.pk).update(loaded_ribbon=ribbon)
    printer.loaded_ribbon = ribbon


def set_loaded(printer, stock):
    """The labels (label material) now in a Zebra (set on its print agent's display, or the admin's for a network
    Zebra); jobs waiting for them are taken by it next."""
    if reason := printer.takes(stock):
        raise PrintError(reason)
    Printer.objects.filter(pk=printer.pk).update(loaded_medium=stock)
    printer.loaded_medium = stock
    if printer.transport == Printer.Transport.NETWORK:
        offer_soon()


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
                   wait=False, batch=None, printer=None):
    """Offer a label outcome (outcomes.py) to the printers: a job that waits until one that has its labels loaded
    and is free takes it (PRINT_WAIT_MAX); printer: only that one. Without wait, only if a printer can print it
    now."""
    if request_id and (job := PrintJob.objects.filter(request_id=request_id).first()):
        return job
    targets = [target for target in outcome.targets if printer is None or target.printer.pk == printer.pk]
    if printer is not None and not targets:
        raise PrintError(_("%(printer)s does not take these labels.") % {"printer": printer})
    if not any(not target.reason for target in targets) and (
            not wait or not (targets or (printer is None and outcome.waits_for_labels))):
        raise PrintError((targets[0].reason if targets else outcome.why_not)
                         or _("No printer can print this label now."))
    return queue_waiting(outcome, subject_type=subject_type, subjects=subjects, copies=copies, user=user,
                         request_id=request_id, quality=quality, batch=batch, printer=printer)


def queue_waiting(outcome, *, subject_type, subjects, copies, user, request_id, quality, batch=None, printer=None):
    if not 1 <= copies <= settings.PRINT_MAX_COPIES:
        raise PrintError(_("Print between 1 and %(max)d copies.") % {"max": settings.PRINT_MAX_COPIES})
    if quality and quality not in Quality.values:
        raise PrintError(_("Unknown print quality."))
    label = str(subjects[0]) + (f" (+{len(subjects) - 1})" if len(subjects) > 1 else "")
    user = user if user is not None and user.is_authenticated else None
    try:
        job = PrintJob.objects.create(
            user=user, printer=printer, layout_key=outcome.layout.key, subject_type=subject_type,
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
    offer_soon()
    return job


def offer_soon():
    """Offer the waiting jobs to the network printers once the transaction is done: at once without a broker
    (the request prints), else by the worker (agents take theirs with their next poll)."""
    if not Printer.objects.filter(is_active=True, transport=Printer.Transport.NETWORK).exists():
        return
    if with_broker():
        schedule_dispatch(countdown=0)
    else:
        transaction.on_commit(lambda: offer_to_network_printers(refresh=False))


def schedule_dispatch(countdown=None):
    """With a broker, offer the waiting jobs to the network printers again in a few seconds
    (tasks.dispatch_waiting_jobs); once at a time. countdown 0: at once (a new job, a printer done)."""
    if not with_broker():
        return  # no broker: the print dialog's requests do (job_status)
    countdown = DISPATCH_EVERY if countdown is None else countdown
    if countdown == 0 or cache.add("label_printing:dispatch_scheduled", True, timeout=DISPATCH_EVERY):
        from .tasks import dispatch_waiting_jobs

        transaction.on_commit(lambda: dispatch_waiting_jobs.apply_async(countdown=countdown))


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


def waiting_outcomes(kinds, found=None):
    """{subject type: {outcome key: outcome}} for waiting jobs of these kinds, added to `found` (kept for the rest
    of a request: building the outcomes asks every printer what it takes)."""
    from . import outcomes

    found = {} if found is None else found
    for kind in set(kinds) - found.keys():
        found[kind] = {outcome.key: outcome for outcome in outcomes.outcomes(kind)}
    return found


def offer_to_network_printers(refresh=True, found=None):
    """The network dispatcher: each free active network printer takes the oldest waiting job it can print now
    (take), printed by the worker (tasks.process_job; without a broker at once). refresh: ask the printers for
    their status first. Returns the number of jobs taken; looks again in a while as long as jobs wait (with a
    broker)."""
    expire_stale()
    if not PrintJob.objects.filter(status=PrintJob.Status.WAITING).exists():
        return 0
    printers = list(Printer.objects.filter(is_active=True, transport=Printer.Transport.NETWORK)
                    .select_related("loaded_medium", "loaded_ribbon"))
    busy = printing_now(printers)
    printers = [printer for printer in printers if printer.pk not in busy]
    if refresh:  # whether they are online and what is loaded, if not known of late
        stale = timezone.now() - timedelta(seconds=STATUS_FRESH)
        ask_network_printers([printer for printer in printers if printer.reports_status and (
            printer.last_status_at is None or printer.last_status_at < stale)])
    found = {} if found is None else found
    taken = [job for printer in printers if (job := take(printer, "worker", found=found))]
    if taken:
        from .tasks import process_job

        for job in taken:
            transaction.on_commit(lambda pk=job.pk: process_job.delay(pk))
    if PrintJob.objects.filter(status=PrintJob.Status.WAITING).exists():
        schedule_dispatch()
    return len(taken)


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
    """The labels loaded in the printer (a Zebra's set as loaded, Brother: the tape it reported), else the first
    material on hand it takes, or None."""
    loaded = printer.loaded_stock_ids()  # the likeliest first
    media = sorted(printer.media(), key=lambda medium: (loaded.index(medium.pk) if medium.pk in loaded else len(loaded),
                                                        medium.name))
    return media[0] if media else None


OWN_LABELS = ("test", "calibration")


def no_material_text():
    return " ".join((_("It takes no label material on hand."),
                     _("Mark label material as on hand (Label material) or check what the printer takes.")))


def print_own_label(printer, layout_key, user=None):
    """A printer's test or calibration label (the admin, the print agent's display): waiting for that printer,
    rendered when it takes it, on the labels loaded in it then (take)."""
    if layout_key not in OWN_LABELS:
        raise PrintError(_("Unknown layout."))
    if code := printer.unavailable_code():
        raise PrintError(messages.describe(code))
    if default_medium(printer) is None:
        raise PrintError(no_material_text())
    if problem := printer.ribbon_problem():
        raise PrintError(problem)
    job = PrintJob.objects.create(
        user=user if user is not None and user.is_authenticated else None, printer=printer,
        status=PrintJob.Status.WAITING, layout_key=layout_key, subject_type="printer", subject_id=printer.pk,
        subject_label=str(printer)[:255], expires_at=timezone.now() + timedelta(seconds=settings.PRINT_JOB_MAX_AGE))
    if printer.transport == Printer.Transport.NETWORK:
        offer_soon()
    return job


def job_medium(job):
    """The job's labels on its printer, or None."""
    return Medium(job.printer, job.medium) if job.printer_id and job.medium_id else None


def expected_tape_mm(job):
    """Brother: the tape width the job is for (checked against the loaded tape before printing); else None."""
    return job.medium.tape_mm if job.medium_id and job.printer.language == Printer.Language.PTOUCH else None


def expected_length(job):
    """Zebra: (mm, dpi) of the job's labels, to compare with the label length the printer measured; else None."""
    if job.printer.language != Printer.Language.ZPL or not job.medium_id or not job.medium.height_mm:
        return None
    return [job.medium.height_mm, job.printer.dpi]


def default_target():
    """The default printer and its default medium, for printing from the admin."""
    printer = Printer.objects.filter(is_default=True, is_active=True).first()
    if printer is None:
        raise PrintError(_("No default printer is set up (admin: Label printing → Printers)."))
    medium = default_medium(printer)
    if medium is None:
        raise PrintError(_("The printer %(printer)s takes no label material on hand.") % {"printer": printer})
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
    return submit(printer=job.printer, medium=job_medium(job), layout_key=job.layout_key, subject_type=job.subject_type,
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
