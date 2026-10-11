"""
What a ZAM ID can point at. Every target is a nullable column on ZamId; the
database constraints and triggers are generated from TARGET_FIELDS.

Adding a target kind (e.g. a future `Asset` model):
  1. add `asset = models.ForeignKey("Asset", null=True, blank=True,
     on_delete=models.PROTECT, related_name="zam_ids")` to ZamId,
  2. append "asset" to TARGET_FIELDS and CLAIMABLE_FIELDS, and add
     `@receiver(pre_delete, sender=Asset)` to retire_ids_of_deleted_target,
  3. `makemigrations inventory`, then add a migration calling
     `triggers.install(schema_editor, columns)` with the extended column list.
Codes, URLs and labels stay unchanged.
"""

# Every column that can hold the target of an ID.
TARGET_FIELDS = ("item", "location", "url")
# Targets members may claim from the frontend. URLs are set in the admin only.
CLAIMABLE_FIELDS = ("item", "location")
# Targets that are model instances with a ForeignKey column.
FK_TARGET_FIELDS = ("item", "location")


def column(field: str) -> str:
    return f"{field}_id" if field in FK_TARGET_FIELDS else field
