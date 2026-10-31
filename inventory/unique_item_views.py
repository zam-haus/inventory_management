"""Unique items: single physical objects with a label ID, one location and a history.

Every unique_item is created together with its label ID, either a pre-printed label
or a newly generated one. UniqueItems leave the inventory one by one (dispose);
they are never deleted with their location.
"""
import extra_views
from dal import autocomplete
from django.contrib import messages
from django.contrib.auth import get_user_model
from django.contrib.auth.mixins import PermissionRequiredMixin
from django.core.exceptions import PermissionDenied
from django.db import transaction
from django.db.models import Q
from django.shortcuts import get_object_or_404, redirect, render
from django.utils.translation import gettext as _
from django.views import View
from django.views.generic import DetailView

from . import forms, link_preview
from .models import Item, Location, UniqueItem
from .permissions import UNIQUE_ITEM_CREATE_PERMISSIONS, ItemEditorPermissionMixin
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
        if not self.object.is_disposed and self.request.user.has_perm("inventory.change_uniqueitem"):
            context["move_form"] = forms.MoveUniqueItemForm(instance=self.object)
        return context


class UniqueItemEditorMixin(ItemEditorPermissionMixin):
    model = UniqueItem
    inlines = [forms.UniqueItemImageInline, forms.UniqueItemFileInline]
    template_name = "inventory/unique_item_form.html"


class CreateUniqueItemView(UniqueItemEditorMixin, extra_views.CreateWithInlinesView):
    permission_required = UNIQUE_ITEM_CREATE_PERMISSIONS
    form_class = forms.NewUniqueItemForm

    def get_initial(self):
        initial = super().get_initial()
        for name, queryset in (("item", Item.active.filter(kind=Item.Kind.UNIQUE)), ("location", Location.active)):
            try:
                initial[name] = queryset.get(pk=int(self.request.GET[name]))
            except (KeyError, ValueError, queryset.model.DoesNotExist):
                pass
        return initial

    def get_context_data(self, **kwargs):
        return super().get_context_data(**kwargs, title=_("New unique item"))

    @transaction.atomic
    def forms_valid(self, form, inlines):
        response = super().forms_valid(form, inlines)
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
        return super().get_context_data(**kwargs, title=_("Edit unique item"))

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


class UniqueKindItemAutocomplete(autocomplete.Select2QuerySetView):
    """
    Items tracked as unique items. The last option stands for a new item of the
    typed name; it is only created when the unique item is saved (needs inventory.add_item).
    """

    create_field = "name"  # lets dal decide when to offer the new item
    http_method_names = ["get"]

    def get_queryset(self):
        qs = Item.active.filter(kind=Item.Kind.UNIQUE)
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
