from django.contrib import messages
from django.contrib.auth.mixins import PermissionRequiredMixin
from django.core.exceptions import PermissionDenied
from django.db import transaction
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect
from django.utils.translation import gettext_lazy as _
from django.views import View

from .forms import (LocationDescriptionForm, LocationDimensionsForm, LocationOverviewForm, LocationPurposeForm,
                    LocationResponsibilityForm)
from .models import Location
from .permissions import location_edit_denied, location_purpose_denied, location_responsibility_denied
from .views import DetailLocationView


class LocationEditView(PermissionRequiredMixin, View):
    """Saves one part of a location from a dialog on its page: JSON for the dialog, else back to the page."""
    permission_required = "inventory.change_location"
    http_method_names = ["post", "options"]
    form_class = fields = success_message = context_name = None
    # Why a user may not save this part; locations of admin-only types are changed in the admin only.
    denied = staticmethod(location_edit_denied)

    def post(self, request, pk):
        wants_json = "application/json" in request.headers.get("Accept", "")
        with transaction.atomic():
            location = get_object_or_404(Location.active.select_for_update(), pk=pk)
            if self.denied(request.user, location):
                raise PermissionDenied
            form = self.form_class(request.POST, request.FILES, instance=location)
            if form.is_valid():
                location = self.save(form, request.user)
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

    def save(self, form, user):
        location = form.save(commit=False)
        location.save(actor=user, update_fields=self.fields)
        return location


class LocationOverviewUpdateView(LocationEditView):
    form_class = LocationOverviewForm
    fields = ["overview_photo"]
    success_message = _("Overview photo saved.")
    context_name = "overview"


class LocationDescriptionUpdateView(LocationEditView):
    # Like the overview photo, locked for the building structure (location_edit_denied).
    form_class = LocationDescriptionForm
    fields = ["description"]
    success_message = _("Description saved.")
    context_name = "description"


class LocationDimensionsUpdateView(LocationEditView):
    form_class = LocationDimensionsForm
    fields = ["width_cm", "depth_cm", "height_cm"]
    success_message = _("Dimensions saved.")
    context_name = "dimensions"


class LocationPurposeUpdateView(LocationEditView):
    form_class = LocationPurposeForm
    fields = ["purpose"]
    denied = staticmethod(location_purpose_denied)
    success_message = _("Purpose saved.")
    context_name = "purpose"


class LocationResponsibilityUpdateView(LocationEditView):
    """Its responsible teams: those of the building structure and storage furniture for who may change locations,
    those of containers for who may see contact details (location_responsibility_denied); the change log records them
    (change_log._teams_changed)."""
    form_class = LocationResponsibilityForm
    denied = staticmethod(location_responsibility_denied)
    success_message = _("Responsible teams saved.")
    context_name = "responsibility"

    def has_permission(self):
        return self.request.user.is_authenticated  # the rest by its category (denied)

    def save(self, form, user):
        location = form.save(commit=False)
        form.save_m2m()  # the teams only; the location itself stays as it is
        return location
