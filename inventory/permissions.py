"""Permission checks for frontend edits that span several models."""

from django.contrib.auth.mixins import PermissionRequiredMixin
from django.core.exceptions import PermissionDenied
from django.db import transaction


def model_permission(model, action):
    return f"{model._meta.app_label}.{action}_{model._meta.model_name}"


def require_dissolution_permissions(user, operations):
    permissions = {"inventory.delete_location"}
    for kind, _pk, action, _destination in operations:
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
            if not can_add:
                formset.extra = 0
            for form in formset:
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
        return super().forms_valid(form, inlines)
