"""Error pages: 400, 403, 404, 500 and the failed form check (CSRF), set in imzam/urls.py and settings.py.

403, 404 and the form check are inventory pages (base.html): the navigation, the search, Login for guests. 400 and
500 stand alone, without database or context processors, since what failed may be just these. On the resolver hosts
(i.zam.haus), which have no inventory pages to link, every error page stands alone (label_ids/urls_resolver.py).
"""
from urllib.parse import urlencode

from django.conf import settings
from django.http import HttpResponse
from django.middleware.csrf import REASON_NO_CSRF_COOKIE
from django.shortcuts import render
from django.template.loader import render_to_string
from django.urls import reverse
from django.utils.http import url_has_allowed_host_and_scheme
from django.utils.translation import gettext_lazy as _

from . import problem_reports, pwa

TITLES = {
    400: _("Bad request"),
    403: _("No access"),
    404: _("Page not found"),
    500: _("Something went wrong"),
}


def page(request, status, **context):
    return render(request, "inventory/errors/page.html", {"status": status, "title": TITLES[status], **context},
                  status=status)


def standalone(request, status):
    # "/" is the search on the inventory and the lookup on the resolver hosts.
    context = {**pwa.offline_context(), "status": status, "title": TITLES[status], "home_url": "/"}
    if status == 500:
        # Django mails uncaught errors to the ADMINS (its default logging).
        context["admins_notified"] = bool(settings.ADMINS)
        if problem_reports.recipients() and not getattr(request, "label_id_resolver_host", False):
            context["report_url"] = f"{reverse('problem_report')}?{urlencode({'url': request.get_full_path()})}"
    return HttpResponse(render_to_string("inventory/errors/standalone.html", context), status=status)


def bad_request(request, exception=None):
    return standalone(request, 400)


def permission_denied(request, exception=None):
    # A reason given with PermissionDenied is shown (e.g. a location that cannot contain sub-locations).
    return page(request, 403, reason=str(exception or ""))


def page_not_found(request, exception=None):
    return page(request, 404)


def server_error(request):
    return standalone(request, 500)


def csrf_failure(request, reason=""):
    """CSRF_FAILURE_VIEW: mostly a form left open too long, or a login or logout in another tab meanwhile."""
    referer = request.META.get("HTTP_REFERER", "")
    safe = url_has_allowed_host_and_scheme(referer, {request.get_host()}, require_https=request.is_secure())
    return page(request, 403, title=_("Form expired"), csrf=True, no_cookie=reason == REASON_NO_CSRF_COOKIE,
                back_url=referer if safe else None)


def standalone_permission_denied(request, exception=None):
    return standalone(request, 403)


def standalone_page_not_found(request, exception=None):
    return standalone(request, 404)
