from urllib.parse import unquote, urlsplit

from django.core.exceptions import ValidationError
from django.db.models import Q
from django.urls import Resolver404, resolve
from django.utils.translation import gettext_lazy as _

from .models import Location


def resolve_location_reference(value):
    """Resolve identifiers or a detail URL, whose primary key wins over its slug."""
    try:
        if "/" in value:
            url = urlsplit(value)
            if url.scheme and url.scheme not in ("http", "https"):
                raise ValueError
            match = resolve(unquote(url.path))
            if match.url_name not in ("view_location", "view_location2"):
                raise ValueError
            pk = Location._meta.pk.clean(match.kwargs["pk"], None)
            return Location.active.get(pk=pk)

        matches = Location.active.filter(
            Q(unique_identifier=value) | Q(locatable_identifier=value)
        )
        # A numeric label is an identifier first, a database ID only as fallback.
        if matches.exists():
            return matches.get()
        if value.isdecimal():
            pk = Location._meta.pk.clean(value, None)
            return Location.active.get(pk=pk)
    except Location.MultipleObjectsReturned:
        raise ValidationError(_("Ambiguous identifier; use the location URL."))
    except (Location.DoesNotExist, Resolver404, ValueError, ValidationError):
        pass
    raise ValidationError(_("Location not found."))
