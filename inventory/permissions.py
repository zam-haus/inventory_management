"""Permission checks for frontend edits that span several models."""

from django.contrib.auth.mixins import PermissionRequiredMixin
from django.core.exceptions import PermissionDenied
from django.db import transaction
from django.utils.translation import gettext as _

from .change_log import change_context
from .models import ChangeLog, LocationType


# Anyone who may create items may manage quick-items while they stay quick-items.
QUICK_ITEM_PERMISSIONS = ("inventory.add_item", "inventory.add_itemlocation")
# Every new unique item gets a label ID right away.
UNIQUE_ITEM_CREATE_PERMISSIONS = ("inventory.add_uniqueitem", "inventory.claim_labelid")
# A bulk item becomes a serialized item: its stock goes, a unique item comes (unique_item_views.serialize).
ITEM_CONVERSION_PERMISSIONS = ("inventory.change_item", "inventory.change_stock", *UNIQUE_ITEM_CREATE_PERMISSIONS)


def model_permission(model, action):
    return f"{model._meta.app_label}.{action}_{model._meta.model_name}"


# Any of these lets a user plan a mass-move of a location's contents.
CONTENT_MOVE_PERMISSIONS = (
    "inventory.change_itemlocation", "inventory.delete_itemlocation",
    "inventory.change_location", "inventory.delete_location",
)


def location_edit_denied(user, location):
    """
    Why `user` may not change the details of `location` (purpose, description, overview photo) on the
    inventory pages, or None. Locations of admin-only types (the building structure) are changed in the admin only.
    """
    if not user.has_perm("inventory.change_location"):
        return _("You do not have permission to change this location.")
    if location.type.admin_only:
        return _("Locations of type “%(type)s” can only be changed in the admin.") % {"type": location.type}
    return None


def item_conversion_unavailable(item):
    """Why the item cannot become a serialized item with one unique item, or None: only one piece at one location
    can, or a quick-item (unknown amount, at its one location), not an estimate."""
    if item.is_serialized:
        return _("It is a serialized item already.")
    entries = list(item.itemlocation_set.all())
    if len(entries) != 1 or entries[0].amount not in (1, None) or entries[0].location.is_deleted:
        return _("Only an item with exactly one piece, or an unknown amount, at exactly one location can become a serialized item.")
    return None


def item_conversion_denied_by_permission(user):
    """Why `user` may not turn any item into a serialized item, or None."""
    if not user.has_perms(ITEM_CONVERSION_PERMISSIONS):
        return _("You do not have permission to turn items into serialized items.")
    return None


def item_conversion_denied(user, item):
    """Why `user` may not turn the item into a serialized item, or None."""
    return item_conversion_denied_by_permission(user) or item_conversion_unavailable(item)


def location_purpose_denied(user, location):
    """Why `user` may not change the purpose of `location` on the inventory pages, or None: as for its other details."""
    return location_edit_denied(user, location)


# Who may see contact details (the "active" members) may also say who is responsible for containers and unique items.
INTERNAL_DETAILS_PERMISSION = "inventory.view_internal_details"
UNIQUE_ITEM_RESPONSIBILITY_PERMISSIONS = ("inventory.change_uniqueitem", INTERNAL_DETAILS_PERMISSION)


def location_responsibility_denied(user, location):
    """Why `user` may not change the responsible teams of `location` on the inventory pages (a dialog on its page), or
    None: those of the building structure and of storage furniture need the permission to change locations, those of
    containers and anything else the permission to see contact details."""
    if location.type.category in (LocationType.Category.SPACE, LocationType.Category.STORAGE_UNIT):
        if not user.has_perm("inventory.change_location"):
            return _("Only who may change locations says who is responsible for the building structure and storage "
                     "furniture.")
    elif not user.has_perm(INTERNAL_DETAILS_PERMISSION):
        return _("Only who may see contact details says who is responsible for containers.")
    return None


def unique_item_responsibility_denied(user, unique_item):
    """Why `user` may not change the responsible team and person of `unique_item` on its page, or None."""
    if unique_item.is_disposed:
        return _("It is no longer in the inventory.")
    if not user.has_perms(UNIQUE_ITEM_RESPONSIBILITY_PERMISSIONS):
        return _("Only who may change unique items and see contact details says who is responsible for them.")
    return None


def location_deletion_denied(user, location):
    """
    Why `user` may not delete `location` on the inventory pages, or None. Location types that
    are not deletable there can only be deleted in the admin, also by staff.
    """
    if not user.has_perm("inventory.delete_location"):
        return _("You do not have permission to delete this location.")
    if location.type.admin_only or not location.type.deletable_in_frontend:
        return _("Locations of type “%(type)s” can only be deleted in the admin.") % {"type": location.type}
    return None


def can_delete_location(user, location):
    return location_deletion_denied(user, location) is None


def require_dissolution_permissions(user, operations, delete_root=True, root=None):
    permissions = {"inventory.delete_location"} if delete_root else set()
    for kind, _pk, action, _destination in operations:
        if action == "keep":
            continue
        model = "location" if kind == "location" else "itemlocation"
        verb = "delete" if action == "delete" else "change"
        permissions.add(f"inventory.{verb}_{model}")
    if not user.has_perms(permissions):
        raise PermissionDenied
    from .models import Location
    deleted = {pk for kind, pk, action, _destination in operations if kind == "location" and action == "delete"}
    if delete_root and root is not None:
        deleted.add(root.pk)
    if any(not can_delete_location(user, location) for location in Location.objects.filter(pk__in=deleted).select_related("type")):
        raise PermissionDenied


class ItemEditorPermissionMixin(PermissionRequiredMixin):
    def get_form_kwargs(self):
        return {**super().get_form_kwargs(), "user": self.request.user}

    def get_inlines(self):
        return [inline for inline in super().get_inlines() if any(
            self.request.user.has_perm(model_permission(inline.model, action))
            for action in ("add", "change")
        )]

    def construct_inlines(self):
        inlines = super().construct_inlines()
        for formset in inlines:
            can_add = self.request.user.has_perm(model_permission(formset.model, "add"))
            can_change = self.request.user.has_perm(model_permission(formset.model, "change"))
            can_delete = self.request.user.has_perm(model_permission(formset.model, "delete"))
            # Shown to the photo and file galleries (media_gallery.js).
            formset.user_can_add, formset.user_can_delete = can_add, can_delete
            if not can_add:
                formset.extra = 0
            for form in formset:
                if not can_delete:
                    form.fields.pop("DELETE", None)
                if form.instance.pk and not can_change:
                    for field in form.fields.values():
                        field.disabled = True
        return inlines

    @transaction.atomic
    def forms_valid(self, form, inlines):
        # Validate every related mutation before saving the parent or any inline.
        for formset in inlines:
            for inline_form in formset:
                if not inline_form.has_changed():
                    continue
                if inline_form.cleaned_data.get("DELETE"):
                    action = "delete"
                else:
                    action = "change" if inline_form.instance.pk else "add"
                if not self.request.user.has_perm(model_permission(formset.model, action)):
                    raise PermissionDenied
        # Changing an amount here corrects the count; it is logged as a recount.
        with change_context(decrease_reason=ChangeLog.Reason.RECOUNT_LOST):
            return super().forms_valid(form, inlines)
