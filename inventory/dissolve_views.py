from django.contrib import messages
from django.contrib.auth.mixins import UserPassesTestMixin
from django.core import signing
from django.core.exceptions import ValidationError
from django.db import DataError, IntegrityError, transaction
from django.shortcuts import get_object_or_404, redirect, render
from django.utils.translation import gettext as _
from django.views import View

from .dissolution import DissolutionPlan
from .forms import DissolveLocationForm
from .models import Location
from .views import check_user_is_allowed


class DissolveLocationView(UserPassesTestMixin, View):
    salt = "inventory.dissolve-location"

    def test_func(self):
        return check_user_is_allowed(self.request)

    def show_plan(self, request, plan, form=None):
        return render(request, "inventory/location_dissolve.html", {
            "object": plan.root, "recursive": plan.recursive,
            "form": form if form is not None else DissolveLocationForm(plan=plan),
        })

    def get(self, request, pk):
        plan = DissolutionPlan(get_object_or_404(Location, pk=pk), request.GET.get("recursive") == "1")
        return self.show_plan(request, plan)

    def post(self, request, pk):
        root = get_object_or_404(Location, pk=pk)
        stage = request.POST.get("stage", "review")
        recursive = request.POST.get("recursive") == "1"
        if stage in ("confirm", "edit"):
            try:
                payload = signing.loads(request.POST.get("plan", ""), salt=self.salt, max_age=1800)
                if payload["root"] != pk:
                    raise signing.BadSignature
                recursive = payload["recursive"]
            except signing.BadSignature:
                messages.error(request, _("The confirmation expired or is invalid. Review the plan again."))
                return redirect("location_dissolve", pk=pk)
            if stage == "confirm":
                try:
                    with transaction.atomic():
                        plan = DissolutionPlan(root, recursive, lock=True)
                        if payload["fingerprint"] != plan.fingerprint():
                            raise ValidationError(_("The inventory changed. Review the plan again."))
                        plan.apply(payload["operations"])
                except (ValidationError, IntegrityError, DataError) as error:
                    explanation = " ".join(error.messages) if isinstance(error, ValidationError) else _("The plan conflicts with the current inventory. No changes were saved.")
                    messages.error(request, explanation)
                else:
                    messages.success(request, _("Location dissolved. Planned moves and deletions were completed."))
                    if root.parent_location_id:
                        return redirect(Location.objects.get(pk=root.parent_location_id))
                    return redirect("index_locations")
            # Preserve the reviewed choices when going back or after a failed confirmation.
            data = {}
            for kind, row_pk, action, destination in payload["operations"]:
                data[f"{kind}_{row_pk}_delete"] = action == "delete"
                data[f"{kind}_{row_pk}_destination"] = destination or ""
            plan = DissolutionPlan(root, recursive)
            return self.show_plan(request, plan, DissolveLocationForm(data, plan=plan))

        plan = DissolutionPlan(root, recursive)
        form = DissolveLocationForm(request.POST, plan=plan)
        if not form.is_valid():
            return self.show_plan(request, plan, form)
        operations = form.cleaned_data["operations"]
        token = signing.dumps({
            "root": pk, "recursive": recursive, "operations": operations,
            "fingerprint": plan.fingerprint(),
        }, salt=self.salt, compress=True)
        rows = plan.review_rows(operations)
        return render(request, "inventory/location_dissolve_confirm.html", {
            "object": root, "plan_token": token,
            "moves": [row for row in rows if row["action"] == "move"],
            "deletions": [row for row in rows if row["action"] == "delete"],
        })
