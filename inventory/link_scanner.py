"""Hosts whose links the QR scanner in the navbar opens (inventory/static/inventory/link_scanner.js)."""
from urllib.parse import urlsplit

from django.conf import settings
from django.http.request import split_domain_port


def scan_hosts(request):
    """Patterns as in ALLOWED_HOSTS, plus earlier domains on old labels, which redirect to the main one."""
    aliases = {urlsplit(url).hostname for url in (*settings.DOMAIN_ALIASES, settings.LABEL_ID_BASE_URL, settings.LABEL_ID_RESOLVER_URL)}
    hosts = {*settings.ALLOWED_HOSTS, *settings.LABEL_ID_RESOLVER_HOSTS, *(host for host in aliases if host),
             split_domain_port(request.get_host())[0]}
    return {"scan_hosts": sorted(hosts)}
