"""
What a label ID can point at. Every target is a nullable column on LabelId; the
database constraints and triggers are generated from TARGET_FIELDS.

Adding a target kind (as was done for `UniqueItem`):
  1. add `<kind> = models.ForeignKey("<Model>", null=True, blank=True,
     on_delete=models.SET_NULL, related_name="label_ids")` to LabelId; deleting
     the target retires its IDs first (release_deleted_target),
  2. append "<kind>" to TARGET_FIELDS, FK_TARGET_FIELDS and (if members may
     claim it) CLAIMABLE_FIELDS, and add `@receiver(pre_delete, sender=<Model>)`
     to retire_ids_of_deleted_target,
  3. `makemigrations inventory`, then call `triggers.install(schema_editor,
     columns)` with the extended column list after the constraint changes,
  4. add the field to the select_related() calls that load targets
     (label_id views, resolver, admin, label_id_check).
Codes, URLs and labels stay unchanged.
"""

# Every column that can hold the target of an ID.
TARGET_FIELDS = ("item", "location", "url", "unique_item")
# Targets members may claim from the frontend. URLs are set in the admin only.
CLAIMABLE_FIELDS = ("item", "location", "unique_item")
# Targets that are model instances with a ForeignKey column.
FK_TARGET_FIELDS = ("item", "location", "unique_item")
# Target columns that load a related object.
RELATED_TARGETS = ("item", "location", "unique_item__item")


def column(field: str) -> str:
    return f"{field}_id" if field in FK_TARGET_FIELDS else field
