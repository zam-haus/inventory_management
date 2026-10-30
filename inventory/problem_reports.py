"""Report a problem (/problem/): a technical problem goes by mail to PROBLEM_REPORT_EMAILS (default: the ADMINS).

The dialog on every page (problem_report_modal.html, problem_report.js) sends the description with a screenshot of
the visible part of the page, its address and what the browser noticed (problem_report_log.js: script errors, failed
loads and requests); without JavaScript the page /problem/ has the same form, without screenshot and browser details.
Nothing is stored: the mail is the report. Everyone may report, guests too; a light limit per user or address keeps
floods out.
"""
import json
import logging

from django import forms
from django.conf import settings
from django.contrib import messages
from django.core.cache import cache
from django.core.mail import EmailMessage
from django.http import Http404, JsonResponse
from django.shortcuts import redirect, render
from django.utils import timezone
from django.utils.http import url_has_allowed_host_and_scheme
from django.utils.text import Truncator, get_valid_filename
from django.utils.translation import gettext as _, gettext_lazy
from django.views import View
from ipware import get_client_ip

logger = logging.getLogger(__name__)

MAX_IMAGE_SIZE = 10 * 1024 * 1024
MAX_CONTEXT_SIZE = 100_000


def recipients():
    if settings.PROBLEM_REPORT_EMAILS:
        return list(settings.PROBLEM_REPORT_EMAILS)
    # ADMINS: addresses, or (name, address) pairs as before Django 6.
    return [admin[1] if isinstance(admin, (list, tuple)) else admin for admin in settings.ADMINS]


def context(request):
    """Whether the menu offers "Report a problem": only with somebody to send the reports to."""
    return {"problem_report_enabled": bool(recipients())}


class ProblemReportForm(forms.Form):
    description = forms.CharField(
        label=gettext_lazy("What happened?"), max_length=5000,
        widget=forms.Textarea(attrs={"rows": 5, "data-modal-focus": "", "placeholder": gettext_lazy(
            "E.g.: Saving the purpose shows an error message.")}),
        help_text=gettext_lazy("What did you do, what did you expect, and what happened instead?"))
    own_picture = forms.ImageField(
        label=gettext_lazy("Picture (optional)"), required=False,
        help_text=gettext_lazy("E.g. a screenshot or a photo of the screen."),
        widget=forms.ClearableFileInput(attrs={"accept": "image/*"}))
    contact = forms.CharField(
        label=gettext_lazy("Contact for questions (optional)"), max_length=200, required=False,
        help_text=gettext_lazy("E-mail address or name, if the admins may ask you."))
    # Filled by the dialog's script.
    url = forms.CharField(max_length=2000, required=False, widget=forms.HiddenInput)
    browser_context = forms.CharField(max_length=MAX_CONTEXT_SIZE, required=False, widget=forms.HiddenInput)
    screenshot = forms.ImageField(required=False)  # not shown: the script adds the file
    # Hidden from people; bots fill it in, and their reports are dropped.
    website = forms.CharField(required=False, widget=forms.TextInput(attrs={"tabindex": "-1", "autocomplete": "off"}))

    def __init__(self, *args, user=None, **kwargs):
        super().__init__(*args, **kwargs)
        if user is not None and user.is_authenticated:
            del self.fields["contact"]  # the user name is sent

    def _clean_size(self, name):
        image = self.cleaned_data.get(name)
        if image and image.size > MAX_IMAGE_SIZE:
            raise forms.ValidationError(_("The picture is too large (at most 10 MB)."))
        return image

    def clean_own_picture(self):
        return self._clean_size("own_picture")

    def clean_screenshot(self):
        return self._clean_size("screenshot")


def _limit_key(request):
    if request.user.is_authenticated:
        return f"problem_report:user:{request.user.pk}"
    address, _routable = get_client_ip(request)
    return f"problem_report:address:{address or 'unknown'}"


def _limited(request):
    return cache.get(_limit_key(request), 0) >= settings.PROBLEM_REPORT_LIMIT


def _count(request):
    key = _limit_key(request)
    if cache.add(key, 1, settings.PROBLEM_REPORT_WINDOW):
        return
    try:
        cache.incr(key)
    except ValueError:  # expired between add() and incr()
        cache.set(key, 1, settings.PROBLEM_REPORT_WINDOW)


def _reporter(request, contact):
    user = request.user
    if user.is_authenticated:
        name = user.username
    else:
        name = _("guest") + (f" ({contact})" if contact else "")
    if getattr(user, "is_local_member", False) or getattr(request, "from_local_network", False):
        name += f", {settings.LOCAL_NETWORK_NAME}"
    return name


def _browser_lines(raw):
    """The browser's details as lines of "key: value", then what went wrong in the tab, oldest first."""
    try:
        data = json.loads(raw)
    except ValueError:
        return [raw]
    if not isinstance(data, dict):
        return [raw]
    lines = [f"{key}: {value if isinstance(value, str) else json.dumps(value)}" for key, value in data.items()
             if key != "log" and not isinstance(value, (dict, list))]
    log = data.get("log") if isinstance(data.get("log"), list) else []
    lines += ["", _("Noticed in this browser tab (oldest first):") if log else _("Nothing noticed in this browser tab.")]
    for entry in log:
        if not isinstance(entry, dict):
            continue
        head = " ".join(str(entry.get(key)) for key in ("time", "kind", "page") if entry.get(key))
        if entry.get("kind") == "request":
            detail = f"{entry.get('method', '')} {entry.get('url', '')} → {entry.get('status') or _('no answer')}"
        else:
            detail = str(entry.get("message", ""))
        lines.append(f"- {head}: {detail}")
        for key in ("source", "stack"):
            if entry.get(key):
                lines += [f"    {line}" for line in str(entry[key]).splitlines()]
    return lines


def build_mail(request, form):
    data = form.cleaned_data
    url = data["url"] or request.headers.get("Referer", "")
    description = data["description"].strip()
    subject = Truncator(" ".join(description.split())).chars(70)
    lines = [
        description,
        "",
        "—",
        f"{_('Page')}: {url or '?'}",
        f"{_('Reported by')}: {_reporter(request, data.get('contact', ''))}",
        f"{_('Time')}: {timezone.localtime():%Y-%m-%d %H:%M:%S %Z}",
        f"{_('Version')}: {settings.APP_VERSION or '?'}",
        f"{_('Browser')}: {request.headers.get('User-Agent', '?')}",
    ]
    if data["browser_context"]:
        lines += ["", *_browser_lines(data["browser_context"])]
    mail = EmailMessage(
        subject=f"{settings.EMAIL_SUBJECT_PREFIX}{_('Problem report')}: {subject}",
        body="\n".join(lines) + "\n",
        from_email=settings.SERVER_EMAIL,
        to=recipients(),
    )
    for name in ("screenshot", "own_picture"):
        image = data.get(name)
        if image:
            filename = "screenshot.jpg" if name == "screenshot" else get_valid_filename(image.name) or "image"
            image.seek(0)
            mail.attach(filename, image.read(), image.content_type or "application/octet-stream")
    if data["browser_context"]:
        mail.attach("browser.json", data["browser_context"], "application/json")
    return mail


class ProblemReportView(View):
    """The form as a page (without JavaScript), and sending a report: JSON for the dialog, else back to the page."""
    template_name = "inventory/problem_report.html"

    def dispatch(self, request, *args, **kwargs):
        if not recipients():
            raise Http404
        return super().dispatch(request, *args, **kwargs)

    def get(self, request):
        url = request.GET.get("url") or request.headers.get("Referer", "")
        form = ProblemReportForm(initial={"url": request.build_absolute_uri(url) if url else ""}, user=request.user)
        return render(request, self.template_name, {"form": form})

    def post(self, request):
        wants_json = "application/json" in request.headers.get("Accept", "")
        form = ProblemReportForm(request.POST, request.FILES, user=request.user)

        def failed(message, status):
            if wants_json:
                return JsonResponse({"ok": False, "error": message, "errors": form.errors.get_json_data()},
                                    status=status)
            if message:
                messages.error(request, message)
            return render(request, self.template_name, {"form": form}, status=status)

        if _limited(request):
            return failed(_("Too many reports in a short time. Please try again later."), 429)
        if not form.is_valid():
            return failed("", 400)
        _count(request)
        if not form.cleaned_data["website"]:
            try:
                build_mail(request, form).send()
            except Exception:
                logger.exception("Could not send a problem report")
                response = failed(_("The report could not be sent. Please try again later."), 503)
                # Logged above; Django's own log of the 503 would try the mail server again for the admins.
                response._has_been_logged = True
                return response

        message = _("Thank you! The admins received your report.")
        if wants_json:
            return JsonResponse({"ok": True, "message": message})
        messages.success(request, message)
        url = form.cleaned_data["url"]
        if url and url_has_allowed_host_and_scheme(url, {request.get_host()}, request.is_secure()):
            return redirect(url)
        return redirect("index")
