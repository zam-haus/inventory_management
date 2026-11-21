"""
API for print agents (label_printing/agent.py).

An admin creates each agent and gives its token to it (in its configuration, next to the server's address);
nothing registers itself. Every request carries the token (Authorization: Bearer …): unknown tokens get 401,
deactivated agents 403. With every poll an agent reports its host and the printers it found: new ones are
created inactive for an admin to check and activate; a known one stays as it is, also when it has moved to
another agent (it moves along). Agents get the next job of each of their active printers that is not busy and
report how it went (result). With every poll they report the jobs they hold (so these stay theirs, also while
paused) and the printers held on them, and get the commands for them from the admin (pause, go on, abort; a held
printer goes on), their printers' names and media,
and the labels waiting for one of their printers to be loaded with them (for the display); on the display
someone can set the labels and the ribbon loaded in a Zebra (loaded, ribbon).
"""
import base64
import io
import json
import re

from django.conf import settings
from django.db import IntegrityError, transaction
from django.db.models import Q
from django.http import JsonResponse
from django.shortcuts import get_object_or_404
from django.utils import timezone
from django.utils.text import slugify
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST
from ipware import get_client_ip

from . import drivers, render, services
from .devices.run import DONE, FAILED, SENT, Result
from .models import LabelStock, PrintAgent, Printer, PrintJob, Ribbon

ID_PATTERN = re.compile(r"^[A-Za-z0-9._:-]{1,128}$")


def authenticated_agent(request):
    scheme, _, token = request.headers.get("Authorization", "").partition(" ")
    return PrintAgent.for_token(token.strip()) if scheme.lower() == "bearer" else None


def json_body(request):
    try:
        data = json.loads(request.body or b"{}")
    except ValueError:
        return None
    return data if isinstance(data, dict) else None


def agent_api(view):
    """POST only, JSON body, the agent as second argument; 401 without a known token, 403 for a deactivated
    agent."""
    @csrf_exempt
    @require_POST
    def wrapper(request, *args, **kwargs):
        agent = authenticated_agent(request)
        if agent is None:
            return JsonResponse({"error": "unknown token: create the agent in the admin and give it its token"},
                                status=401)
        if not agent.is_active:
            return JsonResponse({"error": "this agent is deactivated in the admin"}, status=403)
        data = json_body(request)
        if data is None:
            return JsonResponse({"error": "invalid JSON"}, status=400)
        return view(request, agent, data, *args, **kwargs)
    return wrapper


def unique(model, field, base, max_length):
    """base, or base-2, base-3 … if taken."""
    candidate, number = base[:max_length], 1
    while model.objects.filter(**{field: candidate}).exists():
        number += 1
        suffix = f"-{number}"
        candidate = base[:max_length - len(suffix)] + suffix
    return candidate


# How printers name their maker over USB → as people say it
MANUFACTURERS = {"zebra technologies": "Zebra"}
# Makers' abbreviations in front of the product ("ZTC GK420t": Zebra Technologies Corporation)
PRODUCT_PREFIXES = ("ZTC ",)


def printer_name(info):
    """A new printer's name from what it reports: "Zebra GK420t" for "Zebra Technologies" and "ZTC GK420t",
    "Brother PT-P900W"; the maker once."""
    maker = str(info.get("manufacturer") or "").strip()
    maker = MANUFACTURERS.get(maker.casefold(), maker)
    product = str(info.get("product") or "").strip()
    for prefix in PRODUCT_PREFIXES:
        if product.startswith(prefix):
            product = product[len(prefix):]
    if maker and product.casefold().startswith(maker.casefold()):
        maker = ""
    return " ".join(part for part in (maker, product) if part)


def discovered(agent, uid, report):
    """The printer with this ID: created inactive if it is new (an admin checks, names and activates it); a known
    one is kept as it is, active or not, also when it is found again after being unplugged or the agent's restart,
    and moves along if it is now on another agent."""
    info = report.get("info") if isinstance(report.get("info"), dict) else {}
    printer = Printer.objects.filter(uid=uid).first()
    if printer is None:
        language = info.get("language")
        if language not in Printer.Language.values or agent.printers.count() >= settings.PRINT_AGENT_MAX_PRINTERS:
            return None
        model = str(info.get("model", ""))[:32]
        dpi = drivers.ptouch_dpi(model) if model in drivers.PTOUCH_MODELS else info.get("dpi") or 203
        name = printer_name(info) or uid
        try:
            with transaction.atomic():
                return Printer.objects.create(
                    name=str(name)[:64], slug=unique(Printer, "slug", slugify(uid) or "printer", 50), uid=uid,
                    language=language, model=model, dpi=dpi, transport=Printer.Transport.AGENT, agent=agent,
                    is_active=False, info=info, discovered_at=timezone.now(),
                )
        except IntegrityError:
            return Printer.objects.filter(uid=uid).first()
    changes = {}
    if printer.agent_id != agent.pk:  # moved to another agent
        changes.update(agent=agent, transport=Printer.Transport.AGENT)
    if info and info != printer.info:
        changes["info"] = info
    if changes:
        Printer.objects.filter(pk=printer.pk).update(**changes)
        for field, value in changes.items():
            setattr(printer, field, value)
    return printer


@agent_api
def poll(request, agent, data):
    """Heartbeat with the printers found and their status. Answers the agent's printers, a job for each that is not
    busy (each the oldest it can print now, rendered for it and claimed for the agent), the commands for the jobs
    it holds and the labels waiting to be loaded; asked for ("recent": true, agents since 6.3), the last finished
    jobs. Agents before version 6 are refused: they must be updated."""
    if not version_at_least(data.get("version"), 6):
        return JsonResponse({"error": "update the print agent (version 6 or later)"}, status=426)
    agent.last_seen = timezone.now()
    agent.version = str(data.get("version", ""))[:32]
    agent.hostname = str(data.get("hostname", agent.hostname))[:255]
    agent.address = get_client_ip(request)[0]
    agent.save(update_fields=["last_seen", "version", "hostname", "address"])
    reports = data.get("printers") or {}
    if isinstance(reports, dict):
        for uid, report in reports.items():
            if not ID_PATTERN.match(str(uid)) or not isinstance(report, dict):
                continue
            printer = discovered(agent, str(uid), report)
            if printer is not None and isinstance(report.get("status"), dict):
                printer.remember_status(report["status"])
    printing = data.get("printing") if isinstance(data.get("printing"), dict) else {}
    busy = [str(uid) for uid in data["busy"] if ID_PATTERN.match(str(uid))] if isinstance(data.get("busy"), list) else []
    commands = services.keep_printing(agent, printing)
    held = [str(uid) for uid in data["held"]] if isinstance(data.get("held"), list) else None  # agents since 5.1
    printer_commands = services.held_printers(agent, held) if held is not None else {}
    found = {}  # the outcomes of waiting jobs, worked out once for both
    jobs = services.jobs_for_agent(agent, busy, found)
    return JsonResponse({"printers": services.agent_printers(agent), "jobs": [job_data(job) for job in jobs],
                         "commands": {str(pk): command for pk, command in commands.items()},
                         "printer_commands": printer_commands, "waiting": services.material_waits(agent, found),
                         "offered": services.offered_jobs(agent, found),
                         **({"recent": services.recent_jobs(agent)} if data.get("recent") is True else {})})


def version_at_least(version, major):
    """Whether an agent's version ("6.0") is `major` or later."""
    try:
        return int(str(version).split(".")[0]) >= major
    except ValueError:
        return False


def job_data(job):
    return {
        "id": job.pk,
        "printer": job.printer.uid or job.printer.slug,
        "language": job.printer.language,
        "payload": base64.b64encode(bytes(job.payload)).decode("ascii"),
        "pages": job.pages,
        "subject": job.subject_label,  # what it is for, for the agent's display (a location, item or label ID)
        "material": (job.medium.code or job.medium.name) if job.medium_id else "",  # e.g. TZe-231
        "expected_tape_mm": services.expected_tape_mm(job),
        "expected_length": services.expected_length(job),
        "check_status": job.printer.reports_status,
    }


@agent_api
def loaded(request, agent, data):
    """The labels now loaded in one of the agent's Zebras, confirmed on its display."""
    printer = agent_printer(agent, data)
    if printer is None:
        return JsonResponse({"error": "not a printer of this agent"}, status=404)
    stock = LabelStock.objects.filter(pk=data.get("medium") if isinstance(data.get("medium"), int) else None).first()
    if stock is None or printer.takes(stock):
        return JsonResponse({"error": "not labels of this printer"}, status=400)
    services.set_loaded(printer, stock)
    # whether the ribbon in it suits them: else the display asks for another one
    return JsonResponse({"ok": True, "ribbon_problem": str(printer.ribbon_problem())})


@agent_api
def ribbon(request, agent, data):
    """The ribbon now in one of the agent's Zebras (null: none), confirmed on its display."""
    printer = agent_printer(agent, data)
    if printer is None:
        return JsonResponse({"error": "not a printer of this agent"}, status=404)
    loaded = None
    if data.get("ribbon") is not None:
        loaded = Ribbon.objects.filter(pk=data["ribbon"] if isinstance(data["ribbon"], int) else None).first()
        if loaded is None:
            return JsonResponse({"error": "unknown ribbon"}, status=400)
    services.set_ribbon(printer, loaded)
    return JsonResponse({"ok": True, "ribbon_problem": str(printer.ribbon_problem())})


@agent_api
def own_label(request, agent, data):
    """A test or calibration label ("label") for one of the agent's printers, asked for on its display: queued like
    any job, fetched with the next poll. A refusal says why in words for the display."""
    printer = agent_printer(agent, data)
    if printer is None:
        return JsonResponse({"error": "not a printer of this agent"}, status=404)
    try:
        job = services.print_own_label(printer, str(data.get("label", "")))
    except services.PrintError as error:
        return JsonResponse({"error": str(error)}, status=400)
    return JsonResponse({"ok": True, "job": job.pk})


@agent_api
def cancel(request, agent, data, pk):
    """A waiting job one of the agent's printers could print, cancelled on its display."""
    job = PrintJob.objects.filter(pk=pk).first()
    if job is None or not services.offered_to(agent, job):
        return JsonResponse({"error": "not a waiting job for this agent"}, status=404)
    services.control(job, PrintJob.Command.ABORT, by="display")
    return JsonResponse({"ok": True})


@agent_api
def extend(request, agent, data, pk):
    """A waiting job one of the agent's printers could print waits longer (its display's countdown tapped)."""
    job = PrintJob.objects.filter(pk=pk).first()
    if job is None or not services.offered_to(agent, job):
        return JsonResponse({"error": "not a waiting job for this agent"}, status=404)
    expires_at = services.extend(job)
    return JsonResponse({"ok": True, "expires_in": int((expires_at - timezone.now()).total_seconds())})


# Previews of a job's labels on the agent's display (800 × 480): at most so wide and high (a label higher than wide:
# higher), at most so many
PREVIEW_WIDTH, PREVIEW_HEIGHT, PREVIEW_HEIGHT_TALL, PREVIEW_LABELS = 640, 110, 200, 20


def preview_png(images, medium):
    """A label's pages side by side, in the colours of its labels, scaled for the display; PNG bytes."""
    from PIL import Image

    print_color, background = medium.colours()
    image = render.stack([render.coloured(page, background, print_color) for page in images],
                         drivers.mm_to_dots(3, medium.printer.dpi))
    height = PREVIEW_HEIGHT_TALL if image.height > image.width else PREVIEW_HEIGHT
    scale = min(height / image.height, PREVIEW_WIDTH / image.width, 3)
    size = (max(1, round(image.width * scale)), max(1, round(image.height * scale)))
    image = image.convert("RGB").resize(size, Image.NEAREST if scale >= 1 else Image.LANCZOS)
    out = io.BytesIO()
    image.save(out, format="PNG", optimize=True)
    return out.getvalue()


@agent_api
def detail(request, agent, data, pk):
    """A job of the agent's (one of its printers', or without a printer, for labels one of them takes) for its
    display: the job, previews of its labels as they would print now (each with how many: its copies), and
    whether it can be printed again."""
    job = PrintJob.objects.select_related("printer", "medium").filter(pk=pk).first()
    if job is None or not services.concerns(agent, job):
        return JsonResponse({"error": "not a job of this agent"}, status=404)
    labels, problem = [], ""
    target = services.preview_target(agent, job)
    if target is None:
        problem = "Keine Vorschau: was gedruckt wurde, gibt es nicht mehr."
    else:
        layout, subjects, medium = target
        try:
            rendered = services.render(layout, subjects[:PREVIEW_LABELS], medium, preview=True)
        except services.PrintError as error:
            rendered, problem = [], str(error)
        for subject, label in zip(subjects, rendered):
            labels.append({"subject": str(subject), "count": job.copies,
                           "image": base64.b64encode(preview_png(label.images, medium)).decode("ascii")})
    return JsonResponse({"job": services.job_entry(job), "labels": labels, "problem": problem,
                         "more": max(0, len(target[1]) - PREVIEW_LABELS) if target else 0})


@agent_api
def reprint(request, agent, data, pk):
    """A job of the agent's printed again, asked for on its display (services.again): the new job's id."""
    job = PrintJob.objects.select_related("printer", "medium").filter(pk=pk).first()
    if job is None or not services.concerns(agent, job):
        return JsonResponse({"error": "not a job of this agent"}, status=404)
    try:
        new = services.again(job)
    except services.PrintError as error:
        return JsonResponse({"error": str(error)}, status=400)
    return JsonResponse({"ok": True, "job": new.pk})


@agent_api
def offsets(request, agent, data):
    """A printer's calibration, set on its agent's display after a calibration label."""
    printer = agent_printer(agent, data)
    if printer is None:
        return JsonResponse({"error": "not a printer of this agent"}, status=404)
    try:
        services.set_offsets(printer, data.get("offset_x"), data.get("offset_y"))
    except services.PrintError as error:
        return JsonResponse({"error": str(error)}, status=400)
    return JsonResponse({"ok": True})


def agent_printer(agent, data):
    return Printer.objects.filter(agent=agent).filter(
        Q(uid=str(data.get("printer", ""))) | Q(slug=str(data.get("printer", "")))).first()


@agent_api
def result(request, agent, data, pk):
    """How a job went; only the agent that fetched it may tell."""
    job = get_object_or_404(PrintJob.objects.select_related("printer"), pk=pk, agent=agent)
    if job.status != PrintJob.Status.PROCESSING:
        return JsonResponse({"error": f"job is {job.status}"}, status=409)
    outcome = Result.from_dict(data)
    if outcome.status not in (DONE, SENT, FAILED):
        return JsonResponse({"error": "status must be done, sent or failed"}, status=400)
    services.finish(job, outcome)
    return JsonResponse({"ok": True})
