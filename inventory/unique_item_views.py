"""Unique items: single physical objects with a label ID, one location and a history.

Every unique_item is created together with its label ID, either a pre-printed label
or a newly generated one. UniqueItems leave the inventory one by one (dispose);
they are never deleted with their location.
"""
import uuid

import extra_views
from dal import autocomplete
from django.contrib import messages
from django.contrib.auth import get_user_model
from django.contrib.auth.mixins import PermissionRequiredMixin
from django.core.exceptions import PermissionDenied
from django.db import transaction
from django.db.models import Q
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils.http import url_has_allowed_host_and_scheme
from django.utils.translation import gettext as _
from django.views import View
from django.views.generic import DetailView

from . import forms, link_preview
from .change_log import change_context
from .models import Category, ChangeLog, Item, ItemFile, ItemImage, Location, UniqueItem
from .permissions import (
    ITEM_CONVERSION_PERMISSIONS, UNIQUE_ITEM_CREATE_PERMISSIONS, ItemEditorPermissionMixin, item_conversion_unavailable,
)
from .label_ids import services
from .widgets import NEW_ITEM_PREFIX
from .label_ids.lookup import active_id, annotate_label_code


class DetailUniqueItemView(DetailView):
    model = UniqueItem
    queryset = UniqueItem.objects.select_related(
        "item", "location", "responsible_team__group", "responsible_user", "owner_user",
    ).prefetch_related("images", "item__itemimage_set", "files")
    template_name = "inventory/unique_item_detail.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        lid = active_id(self.object)
        self.object.label_code = lid.code if lid else None
        # This object's own photos and files come first, then those of the item in general.
        images = self.object.item.general_images
        own_images = list(self.object.images.all())
        context.update(
            lid=lid,
            own_images=own_images, images=images, item_images_count=len(images),
            link_preview=link_preview.for_unique_item(self.object, own_images, images),
            files=list(self.object.files.all()),
            general_files=list(self.object.item.itemfile_set.filter(unique_item__isnull=True)),
            general_files_count=self.object.item.itemfile_set.filter(unique_item__isnull=True).count(),
            can_view_internal=self.request.user.has_perm(forms.INTERNAL_DETAILS_PERMISSION),
        )
        # Its notes, edited in a dialog (unique_item_notes_editor.html), for whoever may change it.
        if not self.object.is_disposed and self.request.user.has_perm("inventory.change_uniqueitem"):
            context.setdefault("notes_form", forms.UniqueItemNotesForm(instance=self.object))
        if not self.object.is_disposed and self.request.user.has_perm("inventory.change_uniqueitem"):
            context["move_form"] = forms.MoveUniqueItemForm(instance=self.object)
        return context


class UniqueItemNotesUpdateView(PermissionRequiredMixin, View):
    """Saves the notes of a unique item from the dialog on its page; then back to the page."""
    permission_required = "inventory.change_uniqueitem"
    http_method_names = ["post"]

    def post(self, request, pk):
        with transaction.atomic():
            unique_item = get_object_or_404(UniqueItem.active.select_for_update(of=("self",)), pk=pk)
            form = forms.UniqueItemNotesForm(request.POST, instance=unique_item)
            if form.is_valid():
                form.save(commit=False).save(actor=request.user, update_fields=["notes"])
                messages.success(request, _("Notes saved."))
                return redirect(unique_item)
        # Kept on its page with the dialog open and what was entered.
        detail = DetailUniqueItemView()
        detail.setup(request, pk=pk)
        detail.object = detail.get_object()
        context = detail.get_context_data(notes_form=form, notes_editor_open=True)
        return detail.render_to_response(context, status=400)


class UniqueItemEditorMixin(ItemEditorPermissionMixin):
    model = UniqueItem
    inlines = [forms.UniqueItemImageInline, forms.UniqueItemFileInline]
    template_name = "inventory/unique_item_form.html"


# New items chosen in step 1 of a new unique item, kept until it is saved in step 2: {token: draft}.
NEW_ITEMS_SESSION_KEY = "unique_item_new_items"


def new_item_draft(request, token):
    """A new item from step 1 (UniqueItemItemForm.draft), unsaved, or None."""
    data = request.session.get(NEW_ITEMS_SESSION_KEY, {}).get(token or "")
    if not data:
        return None
    return Item(kind=Item.Kind.SERIALIZED, name=data["name"], description=data["description"],
                usage_level=data["usage_level"], category=Category.objects.filter(pk=data["category"]).first())


def with_location(url, request):
    """The URL, keeping the location a new unique item was started at (?location=)."""
    location = request.GET.get("location", "")
    return f"{url}&location={location}" if location.isdigit() else url


class UniqueItemItemStepView(PermissionRequiredMixin, View):
    """Step 1 of a new unique item: its item (UniqueItemItemForm); then step 2 with it (?item= or, for a new
    one, ?new=: kept in the session, created with the unique item)."""
    permission_required = UNIQUE_ITEM_CREATE_PERMISSIONS
    template_name = "inventory/unique_item_item_step.html"
    # A page that creates a unique item: the navbar's Admin link leads to adding one (admin_links).
    model, object = UniqueItem, None

    def render(self, request, form):
        return render(request, self.template_name, {"form": form, "title": _("New unique item"), "view": self})

    def get(self, request):
        return self.render(request, forms.UniqueItemItemForm(user=request.user))

    def post(self, request):
        form = forms.UniqueItemItemForm(request.POST, user=request.user)
        if not form.is_valid():
            return self.render(request, form)
        draft = form.draft()
        if draft is None:
            return redirect(with_location(f"{reverse('create_unique_item')}?item={form.cleaned_data['item'].pk}",
                                          request))
        token = uuid.uuid4().hex[:16]
        request.session[NEW_ITEMS_SESSION_KEY] = {**request.session.get(NEW_ITEMS_SESSION_KEY, {}), token: draft}
        return redirect(with_location(f"{reverse('create_unique_item')}?new={token}", request))


class CreateUniqueItemView(UniqueItemEditorMixin, extra_views.CreateWithInlinesView):
    """Step 2 of a new unique item: the unique item, its item chosen in step 1 (?item=, or ?new= for a new one).
    Without either, step 1 comes first; a form sent without them still names its item itself."""
    permission_required = UNIQUE_ITEM_CREATE_PERMISSIONS
    form_class = forms.NewUniqueItemForm

    def chosen_item(self):
        if not hasattr(self, "_chosen_item"):
            item = None
            if self.request.GET.get("item", "").isdigit():
                item = Item.active.filter(kind=Item.Kind.SERIALIZED, pk=self.request.GET["item"]).first()
            elif self.request.GET.get("new"):
                item = new_item_draft(self.request, self.request.GET["new"])
            self._chosen_item = item
        return self._chosen_item

    def get(self, request, *args, **kwargs):
        if self.chosen_item() is None:
            step = reverse("create_unique_item_item")
            location = request.GET.get("location", "")
            return redirect(f"{step}?location={location}" if location.isdigit() else step)
        return super().get(request, *args, **kwargs)

    def get_form_kwargs(self):
        return {**super().get_form_kwargs(), "item": self.chosen_item()}

    def get_initial(self):
        initial = super().get_initial()
        try:
            initial["location"] = Location.active.get(pk=int(self.request.GET["location"]))
        except (KeyError, ValueError, Location.DoesNotExist):
            pass
        return initial

    def get_context_data(self, **kwargs):
        item = self.chosen_item()
        location = self.request.GET.get("location", "")
        step = reverse("create_unique_item_item") + (f"?location={location}" if location.isdigit() else "")
        return super().get_context_data(
            **kwargs, title=_("New unique item"), item=item, step_one_url=step,
            item_barcodes=list(item.itembarcode_set.select_related("type")) if item is not None and item.pk else [],
            item_images_count=len(item.general_images) if item is not None and item.pk else 0,
            item_files_count=item.itemfile_set.filter(unique_item__isnull=True).count() if item is not None and item.pk else 0,
        )

    @transaction.atomic
    def forms_valid(self, form, inlines):
        response = super().forms_valid(form, inlines)
        # The new item from step 1 is saved now: no longer kept.
        drafts = self.request.session.get(NEW_ITEMS_SESSION_KEY, {})
        if self.request.GET.get("new") in drafts:
            drafts.pop(self.request.GET["new"])
            self.request.session[NEW_ITEMS_SESSION_KEY] = drafts
        # The unique item and its ID are saved together, or not at all.
        code = form.cleaned_data.get("label_code")
        if code:
            lid = services.claim(code, self.object, self.request.user)
        else:
            lid = services.generate_and_claim(self.object, self.request.user)
        messages.success(self.request, _("The ID %(code)s now belongs to %(target)s.") % {
            "code": lid.display, "target": getattr(self.object, "title_with_code", self.object)})
        return response

    def post(self, request, *args, **kwargs):
        try:
            return super().post(request, *args, **kwargs)
        except services.LabelIdError as error:
            # Someone claimed the label in the meantime; nothing was saved.
            messages.error(request, str(error))
            return redirect(request.get_full_path())

    def get_success_url(self):
        return self.object.get_absolute_url()


class UpdateUniqueItemView(UniqueItemEditorMixin, extra_views.UpdateWithInlinesView):
    permission_required = "inventory.change_uniqueitem"
    form_class = forms.UniqueItemForm
    queryset = UniqueItem.active.select_related("item")

    def get_context_data(self, **kwargs):
        # What its item says for all of its unique items, shown read only (unique_item_item_info.html).
        item = self.object.item
        return super().get_context_data(
            **kwargs, title=_("Edit unique item"), item=item,
            item_barcodes=list(item.itembarcode_set.select_related("type")),
            item_images_count=len(item.general_images),
            item_files_count=item.itemfile_set.filter(unique_item__isnull=True).count(),
        )

    def get_success_url(self):
        return self.object.get_absolute_url()


class DisposeUniqueItemView(PermissionRequiredMixin, View):
    permission_required = "inventory.dispose_uniqueitem"
    template_name = "inventory/unique_item_dispose.html"

    def get_unique_item(self, pk, lock=False):
        queryset = UniqueItem.active.select_related("item", "location")
        if lock:
            queryset = queryset.select_for_update(of=("self",))
        return get_object_or_404(queryset, pk=pk)

    def get(self, request, pk):
        return render(request, self.template_name, {"object": self.get_unique_item(pk), "form": forms.DisposeUniqueItemForm()})

    def post(self, request, pk):
        form = forms.DisposeUniqueItemForm(request.POST)
        with transaction.atomic():
            unique_item = self.get_unique_item(pk, lock=True)
            if not form.is_valid():
                return render(request, self.template_name, {"object": unique_item, "form": form})
            location = unique_item.location
            unique_item.dispose(form.cleaned_data["reason"], form.cleaned_data["note"], actor=request.user)
        messages.success(request, _("%(unique_item)s was removed from the inventory.") % {"unique_item": unique_item})
        return redirect(location if location is not None else unique_item)


def serialize(item, *, actor, label_code=None):
    """Turns a bulk item with one piece at one location (permissions.item_conversion_unavailable) into a serialized
    item with one unique item there: the stock entry goes, the item is no longer for sale, the unique item gets the
    item's purchase details, its photos and files, and a label ID (`label_code`: a pre-printed one, else a new one).
    Each step is in the change log. Returns the unique item; raises services.LabelIdError."""
    entry = item.itemlocation_set.select_for_update().select_related("location").get()
    with change_context(decrease_reason=ChangeLog.Reason.OTHER, note=_("Became a unique item")):
        entry.delete()
    item.kind, item.for_sale, item.sale_price = Item.Kind.SERIALIZED, None, None
    item.save()
    unique_item = UniqueItem(item=item, location=entry.location, purchase_date=item.last_purchase_date,
                             purchase_price=item.last_purchase_price, procurement_source=item.procurement_source)
    unique_item.save(actor=actor)
    for model in (ItemImage, ItemFile):
        model.objects.filter(item=item, unique_item__isnull=True).update(unique_item=unique_item)
    if label_code:
        services.claim(label_code, unique_item, actor)
    else:
        services.generate_and_claim(unique_item, actor)
    return unique_item


class SerializeItemView(PermissionRequiredMixin, View):
    """"Make it a serialized item" on a bulk item's page and on a quick-item of a location: what happens, the label
    ID as for a new unique item. Cancelling goes back to `next` (the location of the quick-item), else the item."""
    permission_required = ITEM_CONVERSION_PERMISSIONS
    template_name = "inventory/item_serialize.html"

    def get_item(self, pk, lock=False):
        queryset = Item.active.all()
        if lock:
            queryset = queryset.select_for_update()
        item = get_object_or_404(queryset, pk=pk)
        if item_conversion_unavailable(item):
            raise PermissionDenied(item_conversion_unavailable(item))
        return item

    def next_url(self, request):
        url = request.POST.get("next") or request.GET.get("next")
        if url and url_has_allowed_host_and_scheme(url, {request.get_host()}, require_https=request.is_secure()):
            return url
        return None

    def render_form(self, request, item, form, status=200):
        entry = item.itemlocation_set.select_related("location").get()
        return render(request, self.template_name, {
            "object": item, "form": form, "location": entry.location, "next": self.next_url(request),
            "general_images": len(item.general_images),
            "general_files": item.itemfile_set.filter(unique_item__isnull=True).count(),
        }, status=status)

    def get(self, request, pk):
        return self.render_form(request, self.get_item(pk), forms.LabelIdChoiceForm())

    def post(self, request, pk):
        form = forms.LabelIdChoiceForm(request.POST)
        try:
            with transaction.atomic():
                item = self.get_item(pk, lock=True)
                if not form.is_valid():
                    return self.render_form(request, item, form, status=400)
                unique_item = serialize(item, actor=request.user, label_code=form.cleaned_data.get("label_code"))
        except services.LabelIdError as error:
            messages.error(request, str(error))
            return redirect("serialize_item", pk=pk)
        messages.success(request, _("%(item)s is a serialized item now; this is its unique item.") % {"item": item})
        return redirect(unique_item)


class SerializedItemAutocomplete(autocomplete.Select2QuerySetView):
    """
    Serialized items. The last option stands for a new item of the
    typed name; it is only created when the unique item is saved (needs inventory.add_item).
    """

    create_field = "name"  # lets dal decide when to offer the new item
    http_method_names = ["get"]

    def get_queryset(self):
        qs = Item.active.filter(kind=Item.Kind.SERIALIZED)
        if self.q:
            qs = qs.filter(Q(name__icontains=self.q) | Q(description__icontains=self.q))
        return qs.order_by("name")

    def get_create_option(self, context, q):
        if not self._should_show_create(context, q):
            return []
        return [{"id": NEW_ITEM_PREFIX + q, "text": _("Create new item “%(name)s”") % {"name": q}}]


class UserAutocomplete(autocomplete.Select2QuerySetView):
    """Lists full names, so only for those who may see owner and responsible details."""

    def dispatch(self, request, *args, **kwargs):
        if not request.user.has_perms(("inventory.change_uniqueitem", forms.INTERNAL_DETAILS_PERMISSION)):
            raise PermissionDenied
        return super().dispatch(request, *args, **kwargs)

    def get_queryset(self):
        qs = get_user_model().objects.filter(is_active=True)
        if self.q:
            qs = qs.filter(Q(username__icontains=self.q) | Q(first_name__icontains=self.q)
                           | Q(last_name__icontains=self.q) | Q(email__icontains=self.q))
        return qs.order_by("first_name", "last_name", "username")

    def get_result_label(self, result):
        return forms.user_label(result)


class UniqueItemWithoutIdAutocomplete(autocomplete.Select2QuerySetView):
    """Unique items in the inventory whose ID was retired: the only ones that can get a new label."""

    def get_queryset(self):
        if not self.request.user.has_perm("inventory.claim_labelid"):
            return UniqueItem.objects.none()
        qs = annotate_label_code(UniqueItem.active.select_related("item")).filter(label_code__isnull=True)
        if self.q:
            condition = Q(item__name__icontains=self.q)
            if self.q.isdigit():
                condition |= Q(pk=int(self.q))
            qs = qs.filter(condition)
        return qs
