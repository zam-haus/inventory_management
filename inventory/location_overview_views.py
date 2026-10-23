from django.contrib import messages
from django.contrib.auth.mixins import PermissionRequiredMixin
from django.core.exceptions import PermissionDenied
from django.db import transaction
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect
from django.utils.translation import gettext_lazy as _
from django.views import View
from django.views.generic import ListView

from .forms import LocationOverviewForm, LocationPurposeForm
from .models import Location
from .permissions import location_edit_denied, location_purpose_denied
from .views import DetailLocationView


class LocationEditView(PermissionRequiredMixin, View):
    """Saves one part of a location from a dialog on its page: JSON for the dialog, else back to the page."""
    permission_required = "inventory.change_location"
    http_method_names = ["post", "options"]
    form_class = fields = success_message = context_name = None
    # Why a user may not save this part; the purpose of admin-only locations stays editable.
    denied = staticmethod(location_edit_denied)

    def post(self, request, pk):
        wants_json = "application/json" in request.headers.get("Accept", "")
        with transaction.atomic():
            location = get_object_or_404(Location.active.select_for_update(), pk=pk)
            if self.denied(request.user, location):
                raise PermissionDenied
            form = self.form_class(request.POST, request.FILES, instance=location)
            if form.is_valid():
                location = form.save(commit=False)
                location.save(actor=request.user, update_fields=self.fields)
                messages.success(request, self.success_message)
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
        context = detail.get_context_data(**{f"{self.context_name}_form": form, f"{self.context_name}_editor_open": True})
        return detail.render_to_response(context, status=400)


class LocationOverviewUpdateView(LocationEditView):
    form_class = LocationOverviewForm
    fields = ["overview_photo"]
    success_message = _("Overview photo saved.")
    context_name = "overview"


class LocationPurposeUpdateView(LocationEditView):
    form_class = LocationPurposeForm
    fields = ["purpose"]
    denied = staticmethod(location_purpose_denied)
    success_message = _("Purpose saved.")
    context_name = "purpose"


class LocationHistoryView(PermissionRequiredMixin, ListView):
    # History exposes who changed what, so it is not public like the purpose and photo.
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
