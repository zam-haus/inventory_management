"""Inventory-side views for ZAM IDs: info, claiming, QR images and labels."""
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

from inventory.models import Item

from . import core, labels, parsing, qr, services
from .forms import ClaimCodeForm, ClaimItemForm, ClaimLocationForm, LabelForm, NewItemForm
from .models import ZamId
from .resolver_views import target_url
from .targets import CLAIMABLE_FIELDS


def get_zam_id(code):
    try:
        code = parsing.code_from_scan(code)
    except core.InvalidZamId:
        raise Http404
    return get_object_or_404(ZamId.objects.select_related("item", "location"), pk=code)


class InfoView(PermissionRequiredMixin, View):
    permission_required = "zamid.view_zamid"

    def get(self, request, code):
        zid = get_zam_id(code)
        return render(request, "zamid/info.html", {
            "zid": zid,
            "target_url": target_url(request, zid),
            "label_profiles": sorted(labels.PROFILES),
            "can_claim": zid.status == ZamId.Status.RESERVED and request.user.has_perm("zamid.claim_zamid"),
        })


class ClaimView(PermissionRequiredMixin, View):
    permission_required = "zamid.claim_zamid"
    forms = {"item": ClaimItemForm, "location": ClaimLocationForm, "new_item": NewItemForm}

    def render_page(self, request, zid, bound=None):
        context = {"zid": zid, "can_add_item": request.user.has_perm("inventory.add_item"),
                   "can_add_location": request.user.is_staff and request.user.has_perm("inventory.add_location")}
        for kind, form_class in self.forms.items():
            context[f"{kind}_form"] = (bound or {}).get(kind) or form_class(prefix=kind)
        return render(request, "zamid/claim.html", context)

    def get(self, request, code):
        zid = get_zam_id(code)
        if zid.status != ZamId.Status.RESERVED:
            return redirect(reverse("zamid_resolve", args=[zid.code]))
        return self.render_page(request, zid)

    def post(self, request, code):
        zid = get_zam_id(code)
        if zid.status != ZamId.Status.RESERVED:
            return redirect(reverse("zamid_resolve", args=[zid.code]))
        kind = request.POST.get("kind")
        if kind not in self.forms:
            return HttpResponseBadRequest()
        if kind == "new_item" and not request.user.has_perm("inventory.add_item"):
            raise PermissionDenied
        form = self.forms[kind](request.POST, prefix=kind)
        if not form.is_valid():
            return self.render_page(request, zid, {kind: form})
        try:
            with transaction.atomic():
                target = form.save() if kind == "new_item" else form.cleaned_data[kind]
                services.claim(zid.code, target, request.user)
        except services.ZamIdError as e:
            messages.error(request, str(e))
            return self.render_page(request, zid, {kind: form})
        messages.success(request, _("The ID %(code)s now belongs to %(target)s.") % {"code": zid.display, "target": target})
        if kind == "new_item":
            return redirect("update_item", pk=target.pk)
        return redirect(target)


class ClaimForView(PermissionRequiredMixin, View):
    """Claim a typed or scanned ID from an item or location page."""
    permission_required = "zamid.claim_zamid"

    def post(self, request, kind, pk):
        if kind not in CLAIMABLE_FIELDS:
            raise Http404
        model = ZamId._meta.get_field(kind).related_model
        target = get_object_or_404(model.active, pk=pk)
        form = ClaimCodeForm(request.POST)
        if not form.is_valid():
            messages.error(request, form.errors["code"][0])
            return redirect(target)
        try:
            zid = services.claim(form.cleaned_data["code"], target, request.user)
        except services.ZamIdError as e:
            messages.error(request, str(e))
        else:
            messages.success(request, _("The ID %(code)s now belongs to %(target)s.") % {"code": zid.display, "target": target})
        return redirect(target)


class ItemAutocomplete(autocomplete.Select2QuerySetView):
    """Items that can still get an ID."""

    def get_queryset(self):
        if not self.request.user.has_perm("zamid.claim_zamid"):
            return Item.objects.none()
        qs = Item.active.exclude(zam_ids__status=ZamId.Status.ASSIGNED)
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
    return _image(qr.svg(get_zam_id(code).code), "image/svg+xml")


@require_safe
def qr_png(request, code):
    return _image(qr.png(get_zam_id(code).code), "image/png")


class LabelView(PermissionRequiredMixin, View):
    permission_required = "zamid.view_zamid"

    def get(self, request, code):
        zid = get_zam_id(code)
        form = LabelForm(request.GET)
        if not form.is_valid():
            return HttpResponseBadRequest(form.errors.as_text())
        printer, tape = form.cleaned_data["printer"], form.cleaned_data["tape"]
        response = HttpResponse(labels.render(zid.code, printer, tape), content_type="image/png")
        response["Content-Disposition"] = f'inline; filename="{labels.filename(zid.code, printer, tape)}"'
        return response
