"""Cheap lookups from an item or location to its active label ID."""
from django.db.models import OuterRef, Subquery

from ..models import LabelId
from .services import target_field_for


def active_id(obj):
    """The assigned LabelId of `obj`, or None. One query on a unique partial index."""
    field = target_field_for(obj)
    if field is None or obj.pk is None:
        return None
    return LabelId.objects.assigned().filter(**{field: obj}).first()


def active_code(obj):
    field = target_field_for(obj)
    if field is None or obj.pk is None:
        return None
    return LabelId.objects.assigned().filter(**{field: obj}).values_list("code", flat=True).first()


def annotate_label_code(queryset, name="label_code"):
    """Add each row's active code as `name`, in the same query (no N+1)."""
    field = target_field_for(queryset.model)
    codes = LabelId.objects.assigned().filter(**{field: OuterRef("pk")}).values("code")[:1]
    return queryset.annotate(**{name: Subquery(codes)})
