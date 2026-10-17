"""
The name users see for label IDs, settings.LABEL_ID_NAME (e.g. "ZAMid"). Code,
database and migrations always say "label ID", so another organization only
changes the setting.
"""
from django.conf import settings
from django.utils.functional import lazy


def name():
    return settings.LABEL_ID_NAME


def plural():
    return f"{name()}s"


# For texts defined at import time (form labels, admin columns, model names).
NAME = lazy(name, str)()
PLURAL = lazy(plural, str)()


def context(request):
    return {"label_id_name": name(), "label_id_name_plural": plural()}
