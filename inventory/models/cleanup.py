"""
Cleanup imports: proposals for cleaning up item texts and the category tree, made outside (e.g. by a script or
an AI tool) from the cleanup export, uploaded in the admin, reviewed change by change and then applied
(inventory/cleanup, docs/item-cleanup.md).
"""
from django.conf import settings
from django.db import models
from django.utils import timezone
from django.utils.translation import gettext_lazy as _


class CleanupImport(models.Model):
    created_at = models.DateTimeField(_("uploaded"), default=timezone.now)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+",
        verbose_name=_("uploaded by"),
    )
    file_name = models.CharField(_("file"), max_length=255)
    # When the export the proposals were made from was taken; items changed since are declined at first.
    exported_at = models.DateTimeField(_("exported"), null=True, blank=True)
    # The proposals as uploaded: {"categories": [operation, …], "items": [proposal, …]}.
    proposals = models.JSONField(_("proposals"), default=dict)
    # Decisions other than accepting, by key of the change (inventory.cleanup.proposals.Change.key): "deferred" (not
    # now, still to be decided) or "declined"; the others are accepted. Any can be changed, also after applying.
    decisions = models.JSONField(_("decisions"), default=dict, blank=True)
    # Text fields accepted with a change by the reviewer: key -> the value applied instead of the proposed one.
    modified = models.JSONField(_("modified changes"), default=dict, blank=True)
    applied_at = models.DateTimeField(_("applied"), null=True, blank=True)
    applied_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+",
        verbose_name=_("applied by"),
    )
    # What applying did: {"applied": [key, …], "skipped": {key: why}}.
    result = models.JSONField(_("result"), default=dict, blank=True)

    class Meta:
        verbose_name = _("cleanup import")
        verbose_name_plural = _("cleanup imports")
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.file_name} ({timezone.localtime(self.created_at):%Y-%m-%d %H:%M})"
