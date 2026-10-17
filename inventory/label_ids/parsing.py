"""Turn whatever a person typed or a scanner read into a canonical label ID."""
import re
from urllib.parse import urlsplit

from django.conf import settings

from . import core


def _url_prefix():
    """Scanned labels contain a resolver URL (settings.LABEL_ID_BASE_URL); the inventory also serves it under /id/."""
    resolvers = {*settings.LABEL_ID_RESOLVER_HOSTS, urlsplit(settings.LABEL_ID_BASE_URL).netloc,
                 urlsplit(getattr(settings, "LABEL_ID_RESOLVER_URL", "")).netloc}
    inventory_urls = (settings.LABEL_ID_INVENTORY_BASE, settings.DEFAULT_DOMAIN, *getattr(settings, "DOMAIN_ALIASES", ()))
    inventories = {urlsplit(url).netloc for url in inventory_urls if url}
    hosts = [f"{re.escape(host)}/" for host in sorted(resolvers) if host]
    hosts += [f"{re.escape(host)}/id/" for host in sorted(inventories) if host]
    return rf"^\s*(?:https?://)?(?:{'|'.join(hosts)})"


def strip_url(raw: str) -> str:
    return re.sub(_url_prefix(), "", raw, flags=re.IGNORECASE).rstrip("/ \t\r\n")


def code_from_scan(raw: str) -> str:
    """Return the canonical ID for typed or scanned input, or raise core.InvalidLabelId."""
    return core.normalize(strip_url(raw))


def suggestions_for_scan(raw: str) -> list[str]:
    return core.suggestions(strip_url(raw))
