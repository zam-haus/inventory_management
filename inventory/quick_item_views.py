"""Quick-items: items known only by title, managed inline on the location page.

A quick-item is an item whose only storage entry has an unknown amount. Anyone
who may create items can rename or hard-delete it while it is still a quick-item;
once it has an amount or other details, the regular item views apply.
"""

from django.contrib import messages
from django.contrib.auth.mixins import PermissionRequiredMixin
from django.db import transaction
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect
from django.urls import reverse
from django.utils.translation import gettext as _
from django.views import View

from .models import Item, ItemLocation, Location
from .permissions import QUICK_ITEM_PERMISSIONS
from .soft_delete import SoftDeleteModel

NAME_MAX_LENGTH = Item._meta.get_field("name").max_length


class QuickItemError(Exception):
    def __init__(self, message, status=409):
        super().__init__(message)
        self.status = status


class QuickItemView(PermissionRequiredMixin, View):
    permission_required = QUICK_ITEM_PERMISSIONS
    raise_exception = True
    http_method_names = ["post", "options"]

    def post(self, request, pk):
        # Deletions sent with navigator.sendBeacon cannot set an Accept header.
        wants_json = "application/json" in request.headers.get("Accept", "") or request.POST.get("format") == "json"
        try:
            with transaction.atomic():
                location, payload, message = self.perform(request, pk)
        except QuickItemError as error:
            if wants_json:
                return JsonResponse({"ok": False, "error": str(error)}, status=error.status)
            messages.error(request, str(error))
            location = self.error_location(pk)
            return redirect(f"{location.get_absolute_url()}#location-quick-items-heading")
        if wants_json:
            return JsonResponse({"ok": True, **payload})
        if message:
            messages.success(request, message)
        return redirect(f"{location.get_absolute_url()}#location-quick-items-heading")

    @staticmethod
    def clean_name(request):
        name = " ".join(request.POST.get("name", "").split())
        if len(name) > NAME_MAX_LENGTH:
            raise QuickItemError(
                _("Item names can have at most %(max)d characters.") % {"max": NAME_MAX_LENGTH}, status=400,
            )
        return name

    @staticmethod
    def get_entry(pk):
        entry = get_object_or_404(
            ItemLocation.objects.select_for_update(of=("self",)).select_related("item", "location"),
            pk=pk, item__is_deleted=False, location__is_deleted=False,
        )
        if not entry.is_quick_item:
            raise QuickItemError(_("This item now has an amount. Open its details to change it."))
        return entry

    def error_location(self, pk):
        return get_object_or_404(Location.active, itemlocation=pk)

    @staticmethod
    def serialize(entry):
        return {
            "id": entry.pk,
            "name": entry.item.name,
            "item_url": entry.item.get_absolute_url(),
            "update_url": reverse("quick_item_update", args=[entry.pk]),
            "delete_url": reverse("quick_item_delete", args=[entry.pk]),
        }


def hard_delete(entry):
    item = entry.item
    if (
        ItemLocation.objects.filter(item=item).exclude(pk=entry.pk).exists()
        or item.itemimage_set.exists() or item.itemfile_set.exists() or item.itembarcode_set.exists()
    ):
        raise QuickItemError(_("This item has more details now. Open it to delete it."))
    # Bypass the soft delete: a quick-item carries nothing worth keeping.
    super(SoftDeleteModel, item).delete()


class QuickItemCreateView(QuickItemView):
    def perform(self, request, pk):
        location = get_object_or_404(Location.active.select_for_update(), pk=pk)
        name = self.clean_name(request)
        if not name:
            raise QuickItemError(_("Enter a name for the quick-item."), status=400)
        item = Item.objects.create(name=name)
        entry = ItemLocation.objects.create(item=item, location=location, amount=None)
        return location, {"entry": self.serialize(entry)}, None

    def error_location(self, pk):
        return get_object_or_404(Location.active, pk=pk)


class QuickItemUpdateView(QuickItemView):
    def perform(self, request, pk):
        entry = self.get_entry(pk)
        name = self.clean_name(request)
        if not name:
            # Clearing a line removes it, also without JavaScript.
            hard_delete(entry)
            return entry.location, {"deleted": True}, _("Quick-item “%(name)s” deleted.") % {"name": entry.item.name}
        if name != entry.item.name:
            Item.objects.filter(pk=entry.item_id).update(name=name)
            entry.item.name = name
        return entry.location, {"entry": self.serialize(entry)}, None


class QuickItemDeleteView(QuickItemView):
    def perform(self, request, pk):
        entry = self.get_entry(pk)
        hard_delete(entry)
        return entry.location, {"deleted": True}, _("Quick-item “%(name)s” deleted.") % {"name": entry.item.name}
