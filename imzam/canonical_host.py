"""
Every domain name redirects to the main one, keeping path and query: label ID
resolver hosts (settings.LABEL_ID_RESOLVER_HOSTS) to settings.LABEL_ID_RESOLVER_URL,
all others to settings.DEFAULT_URL. Logins (cookies per domain) and installed
apps then always use the same address, while old labels keep working.

Label scans on a resolver alias (the short host in the QR codes) are served
directly: the resolver sends them on to /id/<code>?via=label_scan on the inventory,
which records the scan with the logged-in user (label_ids/access.py), without a
detour over the main resolver host. Redirects keep the ?via marker as well.

IP addresses, localhost and *.localhost (development) and Django's test host are
never redirected. settings.CANONICAL_HOST_REDIRECT = False turns this off.
"""
import ipaddress
import re
from urllib.parse import urlsplit

from django.conf import settings
from django.http import HttpResponsePermanentRedirect
from django.http.request import split_domain_port

# A label's QR code holds the base URL and the canonical code, nothing else.
LABEL_SCAN_PATH = re.compile(r"/[0-9A-Z]+")


class HttpResponsePermanentRedirectKeepMethod(HttpResponsePermanentRedirect):
    status_code = 308


def is_development_host(domain):
    if domain in ("localhost", "testserver") or domain.endswith(".localhost"):
        return True
    try:
        ipaddress.ip_address(domain.strip("[]"))
    except ValueError:
        return False
    return True


def main_url(request):
    """The URL on the main domain for this request, or None if it is already there."""
    raw_host = request.META.get("HTTP_HOST") or request.META.get("SERVER_NAME", "")
    domain, _port = split_domain_port(raw_host.lower())
    if not domain or is_development_host(domain):
        return None
    inventory = settings.DEFAULT_URL.rstrip("/")
    resolver = settings.LABEL_ID_RESOLVER_URL.rstrip("/")
    if domain in (urlsplit(inventory).hostname, urlsplit(resolver).hostname):
        return None
    if domain in {host.lower() for host in settings.LABEL_ID_RESOLVER_HOSTS}:
        if request.method in ("GET", "HEAD") and not request.META.get("QUERY_STRING") \
                and LABEL_SCAN_PATH.fullmatch(request.path):
            return None
        base = resolver
    else:
        base = inventory
    return base + request.get_full_path()


class CanonicalHostMiddleware:
    """Redirect to the main domain (see the module docstring); first, before routing by host."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if getattr(settings, "CANONICAL_HOST_REDIRECT", True) and (url := main_url(request)):
            # 301 lets browsers turn a POST into a GET; 308 keeps the method.
            if request.method in ("GET", "HEAD"):
                return HttpResponsePermanentRedirect(url)
            return HttpResponsePermanentRedirectKeepMethod(url)
        return self.get_response(request)
