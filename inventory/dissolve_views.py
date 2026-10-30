from django.contrib import messages
from django.contrib.auth.mixins import PermissionRequiredMixin
from django.core import signing
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import DataError, IntegrityError, transaction
from django.shortcuts import get_object_or_404, redirect, render
from django.utils.translation import gettext as _
from django.views import View

from .dissolution import DissolutionPlan
from .forms import DissolveLocationForm
from .models import ChangeLog, Location
from .permissions import CONTENT_MOVE_PERMISSIONS, location_deletion_denied, require_dissolution_permissions
from .change_log import change_context


class DissolveLocationView(PermissionRequiredMixin, View):
    """Move, delete or keep a location's contents; deleting the emptied location itself is optional."""
    salt = "inventory.dissolve-location"

    def has_permission(self):
        # Deleting the location is checked per plan; moving contents alone needs no delete permission.
        return any(self.request.user.has_perm(permission) for permission in CONTENT_MOVE_PERMISSIONS)

    def check_delete_permission(self, delete_root, root):
        if delete_root and location_deletion_denied(self.request.user, root):
            raise PermissionDenied

    def show_plan(self, request, plan, form=None):
        return render(request, "inventory/location_dissolve.html", {
            "object": plan.root, "recursive": plan.recursive, "delete_root": plan.delete_root,
            # The plan ends with a choice: keep the location or delete it once empty.
            "delete_root_denied": location_deletion_denied(request.user, plan.root) or (
                _("Unique items are still stored here. Move them or remove them from the inventory first.")
                if plan.root_unique_items else None),
            "blocking_unique_items": plan.blocking_unique_items,
            "form": form if form is not None else DissolveLocationForm(plan=plan, user=request.user),
        })

    def get(self, request, pk):
        delete_root = request.GET.get("delete") != "0"
        root = get_object_or_404(Location.active.select_related("type"), pk=pk)
        self.check_delete_permission(delete_root, root)
        plan = DissolutionPlan(root, request.GET.get("recursive") == "1", delete_root=delete_root)
        return self.show_plan(request, plan)

    def post(self, request, pk):
        root = get_object_or_404(Location.active.select_related("type"), pk=pk)
        stage = request.POST.get("stage", "review")
        recursive = request.POST.get("recursive") == "1"
        delete_root = request.POST.get("delete") != "0"
        if stage in ("confirm", "edit"):
            try:
                payload = signing.loads(request.POST.get("plan", ""), salt=self.salt, max_age=1800)
                if payload["root"] != pk:
                    raise signing.BadSignature
                recursive = payload["recursive"]
                delete_root = payload["delete_root"]
            except (signing.BadSignature, KeyError):
                messages.error(request, _("The confirmation expired or is invalid. Review the plan again."))
                return redirect("location_dissolve", pk=pk)
            self.check_delete_permission(delete_root, root)
            if stage == "confirm":
                require_dissolution_permissions(request.user, payload["operations"], delete_root, root)
                try:
                    with transaction.atomic():
                        plan = DissolutionPlan(root, recursive, lock=True, delete_root=delete_root)
                        if payload["fingerprint"] != plan.fingerprint(payload["operations"]):
                            raise ValidationError(_("The inventory changed. Review the plan again."))
                        with change_context(source=ChangeLog.Source.DISSOLUTION,
                                            decrease_reason=ChangeLog.Reason.OTHER):
                            plan.apply(payload["operations"])
                except (ValidationError, IntegrityError, DataError) as error:
                    explanation = " ".join(error.messages) if isinstance(error, ValidationError) else _("The plan conflicts with the current inventory. No changes were saved.")
                    messages.error(request, explanation)
                else:
                    if not delete_root:
                        messages.success(request, _("Planned moves and deletions were completed. The location was kept."))
                        return redirect(root)
                    messages.success(request, _("Location dissolved. Planned moves and deletions were completed."))
                    if root.parent_location_id:
                        return redirect(Location.active.get(pk=root.parent_location_id))
                    return redirect("index_locations")
            # Preserve the reviewed choices when going back or after a failed confirmation.
            data = {}
            for kind, row_pk, action, destination in payload["operations"]:
                data[f"{kind}_{row_pk}_delete"] = action == "delete"
                data[f"{kind}_{row_pk}_destination"] = destination or ""
            plan = DissolutionPlan(root, recursive, delete_root=delete_root)
            return self.show_plan(request, plan, DissolveLocationForm(data, plan=plan, user=request.user))

        self.check_delete_permission(delete_root, root)
        plan = DissolutionPlan(root, recursive, delete_root=delete_root)
        form = DissolveLocationForm(request.POST, plan=plan, user=request.user)
        if not form.is_valid():
            return self.show_plan(request, plan, form)
        operations = form.cleaned_data["operations"]
        require_dissolution_permissions(request.user, operations, delete_root, root)
        token = signing.dumps({
            "root": pk, "recursive": recursive, "delete_root": delete_root, "operations": operations,
            "fingerprint": plan.fingerprint(operations),
        }, salt=self.salt, compress=True)
        rows = plan.review_rows(operations)
        return render(request, "inventory/location_dissolve_confirm.html", {
            "object": root, "plan_token": token, "delete_root": delete_root,
            "moves": [row for row in rows if row["action"] == "move"],
            "deletions": [row for row in rows if row["action"] == "delete"],
            "kept": [row for row in rows if row["action"] == "keep"],
        })
