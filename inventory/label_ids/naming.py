"""
The name users see for label IDs, settings.LABEL_ID_NAME (e.g. "ZAMid"). Code,
database and migrations always say "label ID", so another organization only
changes the setting.
"""
from django.conf import settings
from django.utils.functional import lazy
from django.utils.html import format_html


def name():
    return settings.LABEL_ID_NAME


def plural():
    return f"{name()}s"


# For texts defined at import time (form labels, admin columns, model names).
NAME = lazy(name, str)()
PLURAL = lazy(plural, str)()


def html(display, mark=None):
    """A label ID as pages show it (docs/design-rules.md): its display form (K7R-4XD) in bold Roboto Mono, as on the
    label, class zamid (text.css). `mark`: what the text becomes (search words marked)."""
    return format_html('<span class="zamid">{}</span>', mark(display) if mark else display)


def context(request):
    return {"label_id_name": name(), "label_id_name_plural": plural()}
