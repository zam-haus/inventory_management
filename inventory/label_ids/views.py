"""Inventory-side views for label IDs: info, claiming and QR images (labels: label_printing)."""
from dal import autocomplete
from django.contrib import messages
from django.contrib.auth.mixins import PermissionRequiredMixin
from django.core.exceptions import PermissionDenied
from django.db import transaction
from django.db.models import Q
from django.http import Http404, HttpResponse, HttpResponseBadRequest
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils.translation import gettext as _
from django.views import View
from django.views.decorators.http import require_safe


from ..models import Item, UniqueItem
from ..models import LabelId
from . import access, core, parsing, qr, services
from .forms import ClaimItemForm, ClaimLocationForm, ClaimUniqueItemForm, NewItemForm, NewUniqueItemForm
from .resolver_views import target_url
from .targets import RELATED_TARGETS


def label_preview_url(lid):
    """The ID's label, drawn from a ZAMid label template (label_printing), or None if there is none."""
    from label_printing.selection import preferred_template

    template = preferred_template("labelid", lid)
    return reverse("label_template_preview", args=[template.pk, "labelid", lid.code]) if template else None


def get_label_id(code):
    try:
        code = parsing.code_from_scan(code)
    except core.InvalidLabelId:
        raise Http404
    return get_object_or_404(LabelId.objects.select_related(*RELATED_TARGETS), pk=code)


class InfoView(PermissionRequiredMixin, View):
    permission_required = "inventory.view_labelid"

    def get(self, request, code):
        lid = get_label_id(code)
        return render(request, "inventory/label_id/info.html", {
            "lid": lid,
            "target_url": target_url(request, lid),
            "label_url": label_preview_url(lid),
            "claimable": lid.status == LabelId.Status.RESERVED,
            "can_claim": request.user.has_perm("inventory.claim_labelid"),
            "accesses": access.latest(lid),
            "can_see_access_user": request.user.has_perm("inventory.view_labelid_access_user"),
        })


class ClaimView(PermissionRequiredMixin, View):
    permission_required = "inventory.claim_labelid"
    forms = {"item": ClaimItemForm, "location": ClaimLocationForm, "new_item": NewItemForm,
             "new_unique_item": NewUniqueItemForm, "unique_item": ClaimUniqueItemForm}
    # Creating something new needs the permission to add it.
    add_permissions = {"new_item": "inventory.add_item", "new_unique_item": "inventory.add_uniqueitem"}

    def render_page(self, request, lid, bound=None):
        context = {"lid": lid, "can_add_item": request.user.has_perm("inventory.add_item"),
                   "can_add_uniqueitem": request.user.has_perm("inventory.add_uniqueitem"),
                   "can_add_location": request.user.is_staff and request.user.has_perm("inventory.add_location"),
                   "unique_items_without_id": UniqueItem.active.exclude(label_ids__status=LabelId.Status.ASSIGNED).exists()}
        for kind, form_class in self.forms.items():
            context[f"{kind}_form"] = (bound or {}).get(kind) or form_class(prefix=kind)
        return render(request, "inventory/label_id/claim.html", context)

    def get(self, request, code):
        lid = get_label_id(code)
        if lid.status != LabelId.Status.RESERVED:
            return redirect(reverse("label_id_resolve", args=[lid.code]))
        return self.render_page(request, lid)

    def post(self, request, code):
        lid = get_label_id(code)
        if lid.status != LabelId.Status.RESERVED:
            return redirect(reverse("label_id_resolve", args=[lid.code]))
        kind = request.POST.get("kind")
        if kind not in self.forms:
            return HttpResponseBadRequest()
        if kind in self.add_permissions and not request.user.has_perm(self.add_permissions[kind]):
            raise PermissionDenied
        form = self.forms[kind](request.POST, prefix=kind)
        form.user = request.user
        if not form.is_valid():
            return self.render_page(request, lid, {kind: form})
        try:
            with transaction.atomic():
                target = form.save() if kind in self.add_permissions else form.cleaned_data[kind]
                services.claim(lid.code, target, request.user)
        except services.LabelIdError as e:
            messages.error(request, str(e))
            return self.render_page(request, lid, {kind: form})
        messages.success(request, _("The ID %(code)s now belongs to %(target)s.") % {"code": lid.display, "target": target})
        if kind == "new_item":
            return redirect("update_item", pk=target.pk)
        if kind == "new_unique_item":
            return redirect("update_unique_item", pk=target.pk)
        return redirect(target)


class ItemAutocomplete(autocomplete.Select2QuerySetView):
    """Items that can still get an ID."""

    def get_queryset(self):
        if not self.request.user.has_perm("inventory.claim_labelid"):
            return Item.objects.none()
        qs = Item.active.exclude(label_ids__status=LabelId.Status.ASSIGNED)
        if self.q:
            condition = Q(name__icontains=self.q) | Q(description__icontains=self.q)
            if self.q.isdigit():
                condition |= Q(pk=int(self.q))
            qs = qs.filter(condition)
        return qs.order_by("name")


def _image(content, content_type):
    response = HttpResponse(content, content_type=content_type)
    response["Cache-Control"] = "public, max-age=86400"
    return response


@require_safe
def qr_svg(request, code):
    return _image(qr.svg(get_label_id(code).code), "image/svg+xml")


@require_safe
def qr_png(request, code):
    return _image(qr.png(get_label_id(code).code), "image/png")
