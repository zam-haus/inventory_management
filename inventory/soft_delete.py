from collections import Counter

from django.core.exceptions import ValidationError
from django.db import models, router, transaction
from django.utils.translation import gettext_lazy as _


class SoftDeleteQuerySet(models.QuerySet):
    def delete(self):
        """Process each selected record once, resolving deletion dependencies."""
        if self.query.is_sliced or self._fields is not None:
            raise TypeError("Cannot delete a sliced or values queryset.")
        self._for_write = True
        with transaction.atomic(using=self.db):
            # A join can yield the same record twice. Never turn a single bulk
            # deletion into both a soft and a permanent deletion of that record.
            pending = list(self.model.objects.using(self.db).filter(
                pk__in=self.values("pk"),
            ).select_for_update(of=("self",)).order_by("pk"))
            counts = Counter()
            while pending:
                progress = False
                error = None
                for obj in pending[:]:
                    try:
                        obj.validate_deletion(hard=obj.is_deleted)
                    except ValidationError as blocked:
                        error = blocked
                        continue
                    _count, details = obj.delete(using=self.db)
                    counts.update(details)
                    pending.remove(obj)
                    progress = True
                if not progress:
                    raise error
            self._result_cache = None
            return sum(counts.values()), dict(counts)


class ActiveManager(models.Manager.from_queryset(SoftDeleteQuerySet)):
    def get_queryset(self):
        return super().get_queryset().filter(is_deleted=False)


class SoftDeleteModel(models.Model):
    """Keep records on first deletion; a second deletion removes them permanently."""
    is_deleted = models.BooleanField(_("deleted"), default=False, db_index=True)
    objects = models.Manager.from_queryset(SoftDeleteQuerySet)()
    active = ActiveManager()

    class Meta:
        abstract = True

    def validate_deletion(self, *, hard=False, soft_ids=(), hard_ids=()):
        """Override to protect relations; selected IDs aid admin confirmation."""

    def delete(self, using=None, keep_parents=False):
        if self.pk is None:
            raise ValueError("Cannot delete an object without a primary key.")
        using = using or router.db_for_write(type(self), instance=self)
        with transaction.atomic(using=using):
            current = type(self).objects.using(using).select_for_update().get(pk=self.pk)
            current.validate_deletion(hard=current.is_deleted)
            if current.is_deleted:
                result = super(SoftDeleteModel, current).delete(using=using, keep_parents=keep_parents)
                self.pk = current.pk
                return result
            type(self).objects.using(using).filter(pk=self.pk).update(is_deleted=True)
            self.is_deleted = True
            return 1, {self._meta.label: 1}
