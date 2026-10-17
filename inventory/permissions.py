"""Permission checks for frontend edits that span several models."""

from django.contrib.auth.mixins import PermissionRequiredMixin
from django.core.exceptions import PermissionDenied
from django.db import transaction

from .models import StockChange
from .stock_log import stock_changes


# Anyone who may create items may manage quick-items while they stay quick-items.
QUICK_ITEM_PERMISSIONS = ("inventory.add_item", "inventory.add_itemlocation")
# Every new unique item gets a label ID right away.
UNIQUE_ITEM_CREATE_PERMISSIONS = ("inventory.add_uniqueitem", "inventory.claim_labelid")


def model_permission(model, action):
    return f"{model._meta.app_label}.{action}_{model._meta.model_name}"


# Any of these lets a user plan a mass-move of a location's contents.
CONTENT_MOVE_PERMISSIONS = (
    "inventory.change_itemlocation", "inventory.delete_itemlocation",
    "inventory.change_location", "inventory.delete_location",
)


def require_dissolution_permissions(user, operations, delete_root=True):
    permissions = {"inventory.delete_location"} if delete_root else set()
    for kind, _pk, action, _destination in operations:
        if action == "keep":
            continue
        model = "location" if kind == "location" else "itemlocation"
        verb = "delete" if action == "delete" else "change"
        permissions.add(f"inventory.{verb}_{model}")
    if not user.has_perms(permissions):
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
        with stock_changes(actor=self.request.user, source=StockChange.Source.ITEM_FORM,
                           decrease_reason=StockChange.Reason.RECOUNT_LOST):
            return super().forms_valid(form, inlines)
