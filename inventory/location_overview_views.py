from django.contrib import messages
from django.contrib.auth.mixins import PermissionRequiredMixin
from django.db import transaction
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect
from django.utils.translation import gettext as _
from django.views import View
from django.views.generic import ListView

from .forms import LocationOverviewForm
from .models import Location
from .views import DetailLocationView


class LocationOverviewUpdateView(PermissionRequiredMixin, View):
    permission_required = "inventory.change_location"
    http_method_names = ["post", "options"]

    def post(self, request, pk):
        wants_json = "application/json" in request.headers.get("Accept", "")
        with transaction.atomic():
            location = get_object_or_404(Location.active.select_for_update(), pk=pk)
            form = LocationOverviewForm(request.POST, request.FILES, instance=location)
            if form.is_valid():
                location = form.save(commit=False)
                location.save(
                    actor=request.user,
                    update_fields=["summary", "overview_photo"],
                )
                messages.success(request, _("Location summary saved."))
                if wants_json:
                    return JsonResponse({"ok": True, "url": location.get_absolute_url()})
                return redirect(location)

        if wants_json:
            return JsonResponse({"ok": False, "errors": form.errors.get_json_data()}, status=400)

        # Keep validation errors and entered values on the same detail page,
        # including when JavaScript is unavailable.
        detail = DetailLocationView()
        detail.setup(request, pk=pk)
        detail.object = detail.get_object()
        context = detail.get_context_data(overview_form=form, overview_editor_open=True)
        return detail.render_to_response(context, status=400)


class LocationHistoryView(PermissionRequiredMixin, ListView):
    # History exposes who changed what, so it is not public like the summary.
    permission_required = "inventory.view_locationhistory"
    template_name = "inventory/location_history.html"
    paginate_by = 25

    def get_queryset(self):
        self.location = get_object_or_404(Location.active, pk=self.kwargs["pk"])
        return self.location.history.select_related("actor")

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["object"] = self.location
        return context
