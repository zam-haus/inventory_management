"""
A ZAM ID is a permanent, opaque label code. It lives in its own table so codes
can exist before they are attached (pre-printed labels) and stay reserved after
retirement. Rows are never deleted and a set target never changes; this is
enforced here, in services.py, and by database triggers (triggers.py).
"""
from django.conf import settings
from django.db import IntegrityError, models
from django.db.models import Q
from django.utils.translation import gettext_lazy as _

from ..zamid import core
from ..zamid.fields import ZamIdField
from ..zamid.targets import FK_TARGET_FIELDS, TARGET_FIELDS


class ZamIdImmutable(IntegrityError):
    """A change that would delete a ZAM ID, relink it or reverse its lifecycle."""


def _no_target():
    return Q(**{f"{f}__isnull": True for f in TARGET_FIELDS})


def _one_target():
    q = Q()
    for field in TARGET_FIELDS:
        q |= Q(**{f"{other}__isnull": other != field for other in TARGET_FIELDS})
    return q


class ZamIdQuerySet(models.QuerySet):
    def delete(self):
        raise ZamIdImmutable("ZAM IDs are never deleted; retire them instead.")

    def assigned(self):
        return self.filter(status=ZamId.Status.ASSIGNED)


class ZamId(models.Model):
    class Status(models.TextChoices):
        RESERVED = "reserved", _("reserved")
        ASSIGNED = "assigned", _("assigned")
        RETIRED = "retired", _("retired")

    # (old, new) status pairs a saved row may go through.
    TRANSITIONS = {
        (Status.RESERVED, Status.RESERVED), (Status.RESERVED, Status.ASSIGNED),
        (Status.RESERVED, Status.RETIRED), (Status.ASSIGNED, Status.ASSIGNED),
        (Status.ASSIGNED, Status.RETIRED), (Status.RETIRED, Status.RETIRED),
    }

    code = ZamIdField(_("ID"), primary_key=True)
    status = models.CharField(_("status"), max_length=8, choices=Status.choices,
                              default=Status.RESERVED, db_index=True)
    item = models.ForeignKey("Item", on_delete=models.PROTECT, null=True, blank=True,
                             related_name="zam_ids", verbose_name=_("item"))
    location = models.ForeignKey("Location", on_delete=models.PROTECT, null=True, blank=True,
                                 related_name="zam_ids", verbose_name=_("location"))
    url = models.URLField(_("URL"), max_length=2000, null=True, blank=True)
    batch = models.CharField(_("batch"), max_length=64, blank=True, db_index=True,
                             help_text=_("Label batch or print run."))
    note = models.TextField(_("note"), blank=True)
    created_at = models.DateTimeField(_("created at"), auto_now_add=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
                                   related_name="+", verbose_name=_("created by"))
    printed_at = models.DateTimeField(_("printed at"), null=True, blank=True)
    assigned_at = models.DateTimeField(_("assigned at"), null=True, blank=True)
    assigned_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
                                    related_name="+", verbose_name=_("assigned by"))
    retired_at = models.DateTimeField(_("retired at"), null=True, blank=True)
    retired_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
                                   related_name="+", verbose_name=_("retired by"))

    objects = ZamIdQuerySet.as_manager()

    class Meta:
        verbose_name = _("ZAM ID")
        verbose_name_plural = _("ZAM IDs")
        ordering = ["-created_at", "code"]
        default_permissions = ("view", "change")
        permissions = [
            ("claim_zamid", _("Can claim a ZAM ID for an item or location")),
            ("generate_zamid", _("Can generate ZAM IDs")),
            ("retire_zamid", _("Can retire ZAM IDs")),
            ("assign_url_zamid", _("Can link a ZAM ID to an arbitrary URL")),
        ]
        constraints = [
            models.CheckConstraint(
                name="zamid_status_matches_target",
                condition=(
                    Q(status="reserved") & _no_target()
                    | Q(status="assigned") & _one_target()
                    | Q(status="retired") & (_no_target() | _one_target())
                ),
            ),
            # One active ID per target; also the index for target -> code lookups.
            *(
                models.UniqueConstraint(fields=[field], condition=Q(status="assigned"),
                                        name=f"zamid_one_active_per_{field}")
                for field in FK_TARGET_FIELDS
            ),
        ]

    def __str__(self):
        return self.display

    @classmethod
    def from_db(cls, db, field_names, values):
        instance = super().from_db(db, field_names, values)
        instance._loaded = {f: getattr(instance, f"{f}_id" if f in FK_TARGET_FIELDS else f)
                            for f in ("code", "status", *TARGET_FIELDS) if f in field_names
                            or f"{f}_id" in field_names}
        return instance

    def save(self, *args, **kwargs):
        if self.url == "":
            self.url = None
        if not self._state.adding:
            self._check_change()
        super().save(*args, **kwargs)
        self._loaded = {f: self._target_value(f) for f in TARGET_FIELDS} | {"code": self.code, "status": self.status}

    def _target_value(self, field):
        return getattr(self, f"{field}_id" if field in FK_TARGET_FIELDS else field)

    def _check_change(self):
        loaded = getattr(self, "_loaded", None)
        if loaded is None:
            return  # instance not from the database; triggers still guard the row
        if loaded.get("code") != self.code:
            raise ZamIdImmutable("The code of a ZAM ID cannot change.")
        if (loaded.get("status"), self.status) not in self.TRANSITIONS:
            raise ZamIdImmutable(f"A ZAM ID cannot go from {loaded.get('status')} to {self.status}.")
        if loaded.get("status") != self.Status.RESERVED:
            for field in TARGET_FIELDS:
                if field in loaded and loaded[field] != self._target_value(field):
                    raise ZamIdImmutable("The target of a claimed ZAM ID cannot change.")

    def delete(self, *args, **kwargs):
        raise ZamIdImmutable("ZAM IDs are never deleted; retire them instead.")

    @property
    def display(self):
        return core.display(self.code)

    @property
    def target_field(self):
        for field in TARGET_FIELDS:
            if self._target_value(field) is not None:
                return field
        return None

    @property
    def target(self):
        field = self.target_field
        return getattr(self, field) if field else None

    @property
    def target_is_deleted(self):
        target = self.target
        return getattr(target, "is_deleted", False)
