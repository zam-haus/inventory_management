"""Cheap lookups from an item or location to its active ZAM ID."""
from django.db.models import OuterRef, Subquery

from .models import ZamId
from .services import target_field_for


def active_id(obj):
    """The assigned ZamId of `obj`, or None. One query on a unique partial index."""
    field = target_field_for(obj)
    if field is None or obj.pk is None:
        return None
    return ZamId.objects.assigned().filter(**{field: obj}).first()


def active_code(obj):
    field = target_field_for(obj)
    if field is None or obj.pk is None:
        return None
    return ZamId.objects.assigned().filter(**{field: obj}).values_list("code", flat=True).first()


def annotate_zam_code(queryset, name="zam_code"):
    """Add each row's active code as `name`, in the same query (no N+1)."""
    field = target_field_for(queryset.model)
    codes = ZamId.objects.assigned().filter(**{field: OuterRef("pk")}).values("code")[:1]
    return queryset.annotate(**{name: Subquery(codes)})
