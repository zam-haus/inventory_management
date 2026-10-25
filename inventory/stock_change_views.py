"""Remove or add stock of one item at one location, e.g. after a sale or purchase.

The dialog on the item and location pages posts here; without JavaScript, the
same form is shown as a page. Every change is logged in the change log, with its reason.
Removing the last stock of an item soft-deletes the item.
"""

from collections import Counter
from urllib.parse import urlsplit
from uuid import uuid4

from django.contrib import messages
from django.contrib.auth.mixins import PermissionRequiredMixin
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import Resolver404, resolve, reverse
from django.utils.http import url_has_allowed_host_and_scheme
from django.utils.translation import gettext as _
from django.views import View

from .change_log import change_context, record_stock
from .forms import StockChangeForm
from .models import FEW, ChangeLog, Item, ItemLocation, format_amount


def has_other_stock(entry):
    # Entries with a precise zero hold no stock; an unknown amount might.
    return ItemLocation.objects.filter(item_id=entry.item_id).exclude(pk=entry.pk).exclude(amount=0).exists()


def mark_last_stock(entries):
    """Set `is_last_stock` on each entry, so the dialog can warn before deleting its item."""
    stocked = Counter(ItemLocation.objects.filter(
        item_id__in={entry.item_id for entry in entries},
    ).exclude(amount=0).values_list("item_id", flat=True))
    for entry in entries:
        entry.is_last_stock = stocked[entry.item_id] <= (0 if entry.amount == 0 else 1)
    return entries


def change_stock(entry, data):
    """Apply a validated `StockChangeForm`; return the log entry and whether the item was deleted."""
    before = after = entry.amount
    pk = entry.pk  # gone once the entry is deleted
    increase = data["direction"] == ChangeLog.Direction.INCREASE
    # The change is logged below, with the reason and amount the user chose.
    with change_context(source=ChangeLog.Source.DIALOG, log_stock=False):
        if data["complete"]:
            entry.delete()
            after = None
        elif entry.amount_kind == "precise":
            entry.amount = after = before + data["amount"] if increase else before - data["amount"]
            entry.save(update_fields=["amount"])
        elif entry.amount_kind == "estimate":
            # An estimate stays one (stored negative); if nothing would be
            # left without removing everything, a few remain. "Few", "many"
            # and unknown amounts stay unchanged.
            estimate = -before + data["amount"] if increase else -before - data["amount"]
            entry.amount = after = -estimate if estimate > 0 else FEW
            entry.save(update_fields=["amount"])
        log = record_stock(
            ("itemlocation", pk), item=entry.item, location=entry.location, before=before, after=after, removed=data["complete"],
            change=(data["direction"], data["amount"], data["estimated"]), reason=data["reason"], note=data["note"],
            request_id=data["request_id"], force=True,
        )
        item_deleted = data["complete"] and not has_other_stock(entry)
        if item_deleted:
            entry.item.delete()
    return log, item_deleted


class StockChangeView(PermissionRequiredMixin, View):
    permission_required = "inventory.change_stock"

    @staticmethod
    def get_entry(pk, lock=False):
        entries = ItemLocation.objects.select_related("item__measurement_unit", "location")
        if lock:
            entries = entries.select_for_update(of=("self",))
        # Quick-items are removed or given an amount on the location page instead.
        return get_object_or_404(
            entries, pk=pk, item__is_deleted=False, location__is_deleted=False, amount__isnull=False,
        )

    @staticmethod
    def requested_next_url(request):
        url = request.POST.get("next") or request.GET.get("next")
        if url and url_has_allowed_host_and_scheme(url, {request.get_host()}, require_https=request.is_secure()):
            return url
        return None

    def get_next_url(self, request, entry):
        return self.requested_next_url(request) or entry.item.get_absolute_url()

    def next_url_after_deletion(self, request):
        """Return to the page the dialog was opened from, unless it showed the deleted item."""
        url = self.requested_next_url(request)
        if url is None:
            return reverse("index_items")
        try:
            match = resolve(urlsplit(url).path)
        except Resolver404:
            return url
        if match.url_name == "view_item" and not Item.active.filter(pk=match.kwargs["pk"]).exists():
            return reverse("index_items")
        return url

    def render_page(self, request, entry, form, status=200):
        return render(request, "inventory/stock_change.html", {
            "entry": entry, "form": form, "next": self.get_next_url(request, entry),
            "is_last_stock": not has_other_stock(entry),
        }, status=status)

    def get(self, request, pk):
        entry = self.get_entry(pk)
        return self.render_page(request, entry, StockChangeForm(entry=entry, initial={"request_id": uuid4()}))

    def respond(self, request, url, wants_json):
        if wants_json:
            return JsonResponse({"ok": True, "url": url})
        return redirect(url)

    def already_saved(self, request, pk, wants_json):
        # The response to an earlier submission got lost, e.g. on a flaky connection.
        messages.info(request, _("This stock change was already saved."))
        entry = ItemLocation.objects.filter(pk=pk, item__is_deleted=False).select_related("item").first()
        if entry is None:
            # Possibly removed completely; the item page could no longer exist.
            return self.respond(request, self.next_url_after_deletion(request), wants_json)
        return self.respond(request, self.get_next_url(request, entry), wants_json)

    def post(self, request, pk):
        wants_json = "application/json" in request.headers.get("Accept", "")
        try:
            request_id = StockChangeForm.base_fields["request_id"].clean(request.POST.get("request_id"))
        except ValidationError:
            request_id = None  # Reported by the form.
        if request_id and ChangeLog.objects.filter(request_id=request_id).exists():
            return self.already_saved(request, pk, wants_json)
        try:
            with transaction.atomic():
                entry = self.get_entry(pk, lock=True)
                form = StockChangeForm(request.POST, entry=entry)
                if form.is_valid():
                    log, item_deleted = change_stock(entry, form.cleaned_data)
        except IntegrityError:
            if request_id and ChangeLog.objects.filter(request_id=request_id).exists():
                return self.already_saved(request, pk, wants_json)
            raise
        if not form.is_valid():
            if wants_json:
                return JsonResponse({"ok": False, "errors": form.errors.get_json_data()}, status=400)
            return self.render_page(request, entry, form, status=400)

        names = {"item": log.subject_label, "location": entry.location.title_with_code}
        amount = form.cleaned_data["amount"]
        if amount is None:
            message = _("Removed everything of “%(item)s” from %(location)s.") % names
        else:
            names["amount"] = ("~" if form.cleaned_data["estimated"] else "") + format_amount(amount, log.details["unit"])
            if log.is_increase:
                message = _("Added %(amount)s of “%(item)s” to %(location)s.") % names
            else:
                message = _("Removed %(amount)s of “%(item)s” from %(location)s.") % names
        if item_deleted:
            messages.info(request, message + " " + _("No stock is left, so “%(item)s” was deleted.") % names)
            url = self.next_url_after_deletion(request)
        else:
            messages.success(request, message)
            url = self.get_next_url(request, entry)
        return self.respond(request, url, wants_json)
