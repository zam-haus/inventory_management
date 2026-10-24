"""
API for print agents (label_printing/agent.py).

An agent registers itself with its own ID and a token it made up (register); an admin activates it.
Its requests carry the token (Authorization: Bearer …). With every poll it reports the printers it
found, which appear in the admin as inactive printers until activated and named, and their status;
active agents get the next job of their active printers and report how it went (result).
"""
import base64
import json
import re

from django.conf import settings
from django.db import IntegrityError, transaction
from django.http import JsonResponse
from django.shortcuts import get_object_or_404
from django.utils import timezone
from django.utils.text import slugify
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST
from ipware import get_client_ip

from . import drivers, services
from .devices.run import DONE, FAILED, SENT, Result
from .models import PrintAgent, Printer, PrintJob, token_hash

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
    """POST only, JSON body, the agent as second argument; 401 without a valid token."""
    @csrf_exempt
    @require_POST
    def wrapper(request, *args, **kwargs):
        agent = authenticated_agent(request)
        if agent is None:
            return JsonResponse({"error": "invalid token"}, status=401)
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


@csrf_exempt
@require_POST
def register(request):
    """A new agent: {uid, token, hostname, version}. It is created inactive; registering again with the
    same token is fine (200), with another token refused (409) until an admin deletes the agent."""
    data = json_body(request)
    if data is None:
        return JsonResponse({"error": "invalid JSON"}, status=400)
    uid, token = str(data.get("uid", "")), str(data.get("token", ""))
    if not ID_PATTERN.match(uid) or len(token) < 32:
        return JsonResponse({"error": "uid (letters, digits, ._:-) and a token of 32+ characters needed"}, status=400)
    existing = PrintAgent.objects.filter(uid=uid).first()
    if existing is None:
        # An agent created in the admin, whose token was put into the agent's state.json: now it has an ID.
        existing = PrintAgent.objects.filter(token_hash=token_hash(token), uid=None).first()
        if existing is not None:
            existing.uid = uid
            existing.save(update_fields=["uid"])
    if existing is not None:
        if existing.token_hash != token_hash(token):
            return JsonResponse({"error": "registered with another token; an admin can delete the agent"}, status=409)
        return JsonResponse({"active": existing.is_active, "name": existing.name})
    if PrintAgent.objects.filter(is_active=False).count() >= settings.PRINT_AGENT_MAX_PENDING:
        return JsonResponse({"error": "too many agents wait for activation"}, status=429)
    hostname = str(data.get("hostname", ""))[:255]
    try:
        with transaction.atomic():
            agent = PrintAgent.objects.create(
                name=unique(PrintAgent, "name", hostname or uid, 64), uid=uid, token_hash=token_hash(token),
                is_active=False, hostname=hostname, address=get_client_ip(request)[0],
                version=str(data.get("version", ""))[:32], registered_at=timezone.now(), last_seen=timezone.now(),
            )
    except IntegrityError:
        return JsonResponse({"error": "registered with another token; an admin can delete the agent"}, status=409)
    return JsonResponse({"active": False, "name": agent.name}, status=201)


def discovered(agent, uid, report):
    """The printer with this ID, created inactive if it is new (named and activated in the admin)."""
    info = report.get("info") if isinstance(report.get("info"), dict) else {}
    printer = Printer.objects.filter(uid=uid).first()
    if printer is None:
        language = info.get("language")
        if language not in Printer.Language.values or agent.printers.count() >= settings.PRINT_AGENT_MAX_PRINTERS:
            return None
        model = str(info.get("model", ""))[:32]
        dpi = drivers.ptouch_dpi(model) if model in drivers.PTOUCH_MODELS else info.get("dpi") or 203
        name = " ".join(part for part in (info.get("manufacturer"), info.get("product")) if part) or uid
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
    """Heartbeat with the printers found and their status. Answers whether the agent is active, its active
    printers, and for active agents the next job, now claimed for the agent, or none."""
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
    printers = {printer.uid or printer.slug: {"language": printer.language, "check_status": printer.reports_status}
                for printer in agent.printers.filter(is_active=True)}
    services.dispatch_waiting(refresh=False)  # the agent's printers may just have come back or got other tape
    job = services.next_for_agent(agent) if agent.is_active else None
    return JsonResponse({"active": agent.is_active, "printers": printers, "job": job and {
        "id": job.pk,
        "printer": job.printer.uid or job.printer.slug,
        "language": job.printer.language,
        "payload": base64.b64encode(bytes(job.payload)).decode("ascii"),
        "pages": job.pages,
        "expected_tape_mm": job.medium.ptouch_tape if job.medium else None,
        "expected_length": services.expected_length(job),
        "check_status": job.printer.reports_status,
    }})


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
