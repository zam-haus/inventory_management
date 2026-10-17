"""Quick actions on item and unique item pages: add a photo or file, move a unique item."""
from django.contrib import messages
from django.contrib.auth.mixins import PermissionRequiredMixin
from django.core.exceptions import ValidationError
from django.db import transaction
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect
from django.utils.translation import gettext as _
from django.views import View

from . import forms
from .location_lookup import resolve_location_reference
from .models import Item, ItemImage, Location, UniqueItem, LabelId
from .label_ids import core as label_id_core, parsing as label_id_parsing


class QuickAddView(PermissionRequiredMixin, View):
    """
    Adds one photo or file from the detail page; it belongs to the item in general
    (item page) or to the unique item (unique item page).
    """

    http_method_names = ["post"]
    form_class = None
    unique = False

    def get_target(self, pk):
        if self.unique:
            unique_item = get_object_or_404(UniqueItem.active.select_related("item"), pk=pk)
            return unique_item.item, unique_item, unique_item.get_absolute_url()
        item = get_object_or_404(Item.active, pk=pk)
        return item, None, item.get_absolute_url()

    def post(self, request, pk):
        item, unique_item, page = self.get_target(pk)
        form = self.form_class(request.POST, request.FILES)
        if not form.is_valid():
            for errors in form.errors.values():
                for error in errors:
                    messages.error(request, error)
            return redirect(page)
        with transaction.atomic():
            attachment = form.save(commit=False)
            attachment.item, attachment.unique_item = item, unique_item
            if getattr(attachment, "is_primary", False):
                # One primary photo per level: this one replaces the previous one.
                ItemImage.objects.filter(item=item, unique_item=unique_item, is_primary=True).update(is_primary=False)
            attachment.save()
        messages.success(request, self.success_message % {"name": attachment.description or _("without description")})
        return redirect(page)


class QuickPhotoView(QuickAddView):
    permission_required = "inventory.add_itemimage"
    form_class = forms.QuickPhotoForm
    success_message = _("Photo added (%(name)s).")


class QuickFileView(QuickAddView):
    permission_required = "inventory.add_itemfile"
    form_class = forms.QuickFileForm
    success_message = _("File added (%(name)s).")


class MoveUniqueItemView(PermissionRequiredMixin, View):
    permission_required = "inventory.change_uniqueitem"
    http_method_names = ["post"]

    def post(self, request, pk):
        with transaction.atomic():
            unique_item = get_object_or_404(UniqueItem.active.select_for_update(of=("self",)), pk=pk)
            form = forms.MoveUniqueItemForm(request.POST, instance=unique_item)
            if form.is_valid():
                unique_item = form.save(commit=False)
                unique_item.save(actor=request.user)
                messages.success(request, _("Moved to %(location)s.") % {"location": unique_item.location})
            else:
                for errors in form.errors.values():
                    for error in errors:
                        messages.error(request, error)
        return redirect(unique_item)


def location_lookup(request):
    """A typed or scanned location reference (label ID, label URL or identifier) as JSON for the move dialog."""
    raw = request.GET.get("q", "").strip()
    location = None
    try:
        lid = LabelId.objects.select_related("location").filter(pk=label_id_parsing.code_from_scan(raw)).first()
        if lid is not None and lid.status == LabelId.Status.ASSIGNED and lid.location and not lid.location.is_deleted:
            location = lid.location
    except label_id_core.InvalidLabelId:
        pass
    if location is None:
        try:
            location = resolve_location_reference(raw)
        except ValidationError as error:
            return JsonResponse({"error": " ".join(error.messages)}, status=404)
    return JsonResponse({"id": location.pk, "text": str(location)})
