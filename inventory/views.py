import logging
import mimetypes
from pathlib import PurePath
from urllib.parse import urlencode

import extra_views
from dal import autocomplete
from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import permission_required
from django.contrib.auth.mixins import PermissionRequiredMixin
from django.contrib.auth.views import redirect_to_login
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import IntegrityError, transaction
from django.forms import all_valid
from django.db.models import Prefetch, Q
from django.http import FileResponse, Http404, HttpResponseForbidden, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse, reverse_lazy
from django.utils import timezone
from django.utils.html import format_html, format_html_join
from django.utils.translation import gettext_lazy as _
from django.views import View
from django.views.generic import DetailView, ListView, TemplateView, UpdateView

from . import forms, location_display, models
from .location_lookup import resolve_location_reference
from .permissions import (
    QUICK_ITEM_PERMISSIONS, UNIQUE_ITEM_CREATE_PERMISSIONS, ItemEditorPermissionMixin, location_deletion_denied,
    location_edit_denied, location_purpose_denied,
)
from .stock_change_views import mark_last_stock
from .structure_overview import structure_overview
from .label_ids import services
from .label_ids.lookup import annotate_label_code
from .label_ids.search import LabelIdSearchMixin
from .location_lookup import location_from_reference


logger = logging.getLogger(__name__)

def index(request):
    return render(request, "inventory/index.html")

def filter_locations(qs, query):
    """Locations matching a search; a pasted or scanned label URL or label ID finds its location, too."""
    if not query:
        return qs
    matches = (Q(name__icontains=query) | Q(unique_identifier__icontains=query) |
               Q(purpose__icontains=query) | Q(physical_description__icontains=query) |
               Q(former_codes__code__icontains=query))
    if (referenced := location_from_reference(query.strip())) is not None:
        matches |= Q(pk=referenced.pk)
    return qs.filter(matches).distinct()


class LocationResults:
    """Locations as suggestions: HTML for the frontend's fields (widgets.LocationSelect asks with ?html=1: title,
    name, code chip, and where it is), else text with the path (the admin's fields)."""

    def html(self):
        return bool(self.request.GET.get("html"))

    def get_result_label(self, result):
        return location_display.option_html(result) if self.html() else result.path_with_purpose

    def get_selected_result_label(self, result):
        return location_display.label_html(result) if self.html() else result.path_with_purpose


class LocationAutocomplete(LocationResults, autocomplete.Select2QuerySetView):
    def get_queryset(self):
        qs = models.Location.active.select_related("parent_location")

        # `self.q` is the search term from the user, provided by DAL.
        return filter_locations(qs, self.q)

class PrintableInventoryView(PermissionRequiredMixin, View):
    """Internal: lists everything stored at the selected locations."""

    permission_required = "inventory.print_inventory"

    def get(self, request):
        include_children = request.GET.get("include_children") == "1"
        query = request.GET.get("q", "").strip()
        if "locations" in request.GET:
            form = forms.PrintableInventoryForm(request.GET)
        elif query:
            # Coming from the location list: preselect its search results.
            search = SearchableLocationListView()
            search.setup(request)
            form = forms.PrintableInventoryForm(initial={"locations": list(search.get_queryset().values_list("pk", flat=True))})
        else:
            form = forms.PrintableInventoryForm()
        context = {"form": form, "include_children": include_children, "query": query}
        if form.is_valid():
            selected_locations = list(form.cleaned_data["locations"])
            location_ids = {location.pk for location in selected_locations}
            if include_children:
                # Unique child identifiers need not start with their parent's.
                children = {}
                for pk, parent_id in models.Location.active.order_by().values_list(
                    "pk", "parent_location_id"
                ):
                    children.setdefault(parent_id, []).append(pk)
                pending = list(location_ids)
                while pending:
                    for child_id in children.get(pending.pop(), []):
                        if child_id not in location_ids:
                            location_ids.add(child_id)
                            pending.append(child_id)

            context.update(
                selected_locations=selected_locations,
                generated_at=timezone.now(),
                entries=models.ItemLocation.objects.filter(location_id__in=location_ids, item__is_deleted=False)
                .select_related("location", "item", "item__measurement_unit")
                .prefetch_related("item__itemimage_set")
                .order_by("location__locatable_identifier", "item__name", "item_id"),
                unique_items=annotate_label_code(models.UniqueItem.active.filter(location_id__in=location_ids))
                .select_related("location", "item")
                .order_by("location__locatable_identifier", "item__name", "pk"),
            )
        return render(request, "inventory/inventory_print.html", context)


class DetailLocationView(DetailView):
    model = models.Location
    queryset = models.Location.active.prefetch_related(
        Prefetch("children", queryset=models.Location.active.select_related("type")),
        Prefetch("itemlocation_set", queryset=models.ItemLocation.objects.filter(item__is_deleted=False).select_related("item__measurement_unit").prefetch_related("item__itemimage_set")),
    )

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        entries = list(self.object.itemlocation_set.all())
        context["quick_entries"] = [entry for entry in entries if entry.is_quick_item]
        context["entries"] = [entry for entry in entries if not entry.is_quick_item]
        context["can_manage_quick_items"] = self.request.user.has_perms(QUICK_ITEM_PERMISSIONS)
        context["dissolve_denied"] = location_deletion_denied(self.request.user, self.object)
        context["edit_denied"] = location_edit_denied(self.request.user, self.object)
        context["purpose_denied"] = location_purpose_denied(self.request.user, self.object)
        if not self.object.type.no_sublocations:
            context["numbering_types"] = [kind.name for kind, _source in self.object.numbering_types()]
            context["container_types"] = [kind.name for kind in self.object.container_types()]
        # One panel per category of sub-locations; without any category a single one, as before.
        # Where storage units or containers can be added, their panel (with its + shortcut) shows even
        # while empty, but only to logged-in users, who see the shortcut at least disabled.
        Category = models.LocationType.Category
        groups = models.LocationType.group_by_category(self.object.children.all())
        if self.request.user.is_authenticated:
            for category, addable, before in ((Category.STORAGE_UNIT, "numbering_types", {Category.SPACE}),
                                              (Category.CONTAINER, "container_types", {Category.SPACE, Category.STORAGE_UNIT})):
                if context.get(addable) and category not in [group[0] for group in groups]:
                    groups.insert(sum(group[0] in before for group in groups),
                                  (category, models.LocationType.CATEGORY_PLURALS[category], []))
        context["child_groups"] = [
            {"category": category, "anchor": f"location-children-{(category or 'other').replace('_', '-')}",
             "title": title, "children": children}
            for category, title, children in groups
        ] if any(category for category, _title, _children in groups) else None
        context["can_add_quick_photos"] = self.request.user.has_perms((*QUICK_ITEM_PERMISSIONS, "inventory.add_itemimage"))
        # Quick-items are listed with the items and counted with them.
        context["items_count"] = len(entries)
        context["unique_items"] = annotate_label_code(
            self.object.unique_items.select_related("item").prefetch_related("images", "item__itemimage_set")
        ).order_by("item__name", "pk")
        if self.request.user.has_perm("inventory.change_stock"):
            mark_last_stock(context["entries"])
            context["stock_change_form"] = forms.StockChangeForm()
        if not context["edit_denied"]:
            context.setdefault("overview_form", forms.LocationOverviewForm(instance=self.object))
            context.setdefault("description_form", forms.LocationDescriptionForm(instance=self.object))
        if not context["purpose_denied"]:
            context.setdefault("purpose_form", forms.LocationPurposeForm(instance=self.object))
        if self.request.user.has_perm("inventory.change_location"):
            if self.object.type.moveable:
                context["move_form"] = forms.LocationMoveForm(instance=self.object, initial={"id": self.object.pk})
            if not self.object.type.no_sublocations:
                context["move_here_form"] = forms.LocationsMoveHereForm(dialog=True)
        return context

    def get(self, request, *args, **kwargs):
        self.object = self.get_object()
        if "unique_identifier" in kwargs and self.object.unique_identifier != kwargs["unique_identifier"]:
            return redirect(self.object)
        context = self.get_context_data(object=self.object)
        return self.render_to_response(context)


@permission_required("inventory.change_location", raise_exception=True)
def update_location(request, pk, unique_identifier):
    return redirect("location_move", pk=pk)

class LocationMoveView(PermissionRequiredMixin, UpdateView):
    permission_required = "inventory.change_location"
    template_name = 'inventory/location_move.html'
    form_class = forms.LocationMoveForm
    model = models.Location
    queryset = models.Location.active.all()

    def get(self, request, *args, **kwargs):
        if not self.get_object().type.moveable:
            return HttpResponseForbidden(_("Moving is disabled for this location type."))
        return super().get(request, *args, **kwargs)
    def post(self, request, *args, **kwargs):
        if not self.get_object().type.moveable:
            return HttpResponseForbidden(_("Moving is disabled for this location type."))
        return super().post(request, *args, **kwargs)

class LocationsMoveHereView(PermissionRequiredMixin, View):
    permission_required = "inventory.change_location"

    def get_parent(self, pk):
        parent = get_object_or_404(models.Location.active.select_related("type"), pk=pk)
        if parent.type.no_sublocations:
            raise PermissionDenied(_("This location cannot contain sub-locations."))
        return parent

    def get(self, request, pk):
        parent = self.get_parent(pk)
        form = forms.LocationsMoveHereForm(initial={"identifiers": request.GET.get("identifiers", "")})
        return render(request, "inventory/locations_move_here.html", {"object": parent, "form": form})

    def post(self, request, pk):
        parent = self.get_parent(pk)
        form = forms.LocationsMoveHereForm(request.POST)
        if not form.is_valid():
            return render(request, "inventory/locations_move_here.html", {"object": parent, "form": form})

        pending, failures, seen = [], [], set()
        # Resolve the entire batch before moving anything changes identifiers.
        for value in form.cleaned_data["identifiers"]:
            try:
                location = resolve_location_reference(value)
            except ValidationError as error:
                failures.append((value, " ".join(error.messages)))
            else:
                if location.pk not in seen:
                    pending.append((value, location.pk))
                    seen.add(location.pk)

        successes = 0
        for value, location_pk in pending:
            try:
                with transaction.atomic():
                    location = models.Location.active.select_for_update().get(pk=location_pk)
                    if not location.type.moveable:
                        raise ValidationError(_("Moving is disabled for this location type."))
                    location.parent_location = parent
                    # Computed identifiers are refreshed by save(), including descendants.
                    location.full_clean(exclude=[
                        "unique_identifier", "locatable_identifier", "descriptive_identifier",
                    ])
                    location.save()
            except ValidationError as error:
                failures.append((value, " ".join(error.messages)))
            except models.Location.DoesNotExist:
                failures.append((value, _("Location not found.")))
            except IntegrityError:
                failures.append((value, _("Moving would create conflicting location identifiers.")))
            else:
                successes += 1

        summary = _("Locations moved: %(successes)d. Errors: %(errors)d.") % {
            "successes": successes, "errors": len(failures),
        }
        if failures:
            move_url = reverse("locations_move_here", kwargs={"pk": parent.pk})

            def retry_url(values):
                return move_url + "?" + urlencode({"identifiers": "\n".join(values)})

            failed_entries = format_html_join(
                "", '<li><a href="{}">{}</a>: {}</li>',
                ((retry_url([value]), value, reason) for value, reason in failures),
            )
            messages.warning(request, format_html(
                '{}<ul class="mb-2">{}</ul><a href="{}">{}</a>',
                summary, failed_entries, retry_url([value for value, _reason in failures]),
                _("Edit and retry failed entries"),
            ))
        else:
            messages.success(request, summary)
        return redirect(parent)


class DocumentView(View):
    """Serves an attached file; internal documents need inventory.view_internal_details."""

    model = None
    # Shown in the browser; anything else, e.g. HTML or SVG, is downloaded so it cannot run here.
    INLINE_TYPES = {"application/pdf", "image/png", "image/jpeg", "image/gif", "image/webp", "text/plain"}

    def get(self, request, pk):
        document = get_object_or_404(self.model, pk=pk)
        if document.internal and not request.user.has_perm(forms.INTERNAL_DETAILS_PERMISSION):
            if not request.user.is_authenticated:
                return redirect_to_login(request.get_full_path())
            raise PermissionDenied
        try:
            handle = document.file.open("rb")
        except FileNotFoundError:
            raise Http404
        name = PurePath(document.file.name).name
        content_type, _encoding = mimetypes.guess_type(name)
        response = FileResponse(handle, filename=name, as_attachment=content_type not in self.INLINE_TYPES)
        response["Content-Security-Policy"] = "sandbox"
        response["Cache-Control"] = "private, no-store" if document.internal else "public, max-age=3600"
        return response


class ItemDocumentView(DocumentView):
    model = models.ItemFile


class DetailItemView(DetailView):
    model = models.Item
    queryset = models.Item.active.prefetch_related(Prefetch(
        "itemlocation_set", queryset=models.ItemLocation.objects.filter(location__is_deleted=False).select_related("location"),
    ))

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        # The item page shows what applies to the item in general.
        context["files"] = self.object.itemfile_set.filter(unique_item__isnull=True)
        if self.object.tracks_unique_items:
            context["unique_items"] = annotate_label_code(
                self.object.unique_items(manager="active").select_related("location", "responsible_team__group")
            ).order_by("location__locatable_identifier", "pk")
            context["disposed_count"] = self.object.unique_items.filter(disposed_at__isnull=False).count()
            return context
        context["entries"] = list(self.object.itemlocation_set.all())
        if self.request.user.has_perm("inventory.change_stock"):
            mark_last_stock(context["entries"])
            context["stock_change_form"] = forms.StockChangeForm()
        # Item labels lead here with ?loc=<location>: that location comes first and is marked.
        take = [entry for entry in context["entries"] if not entry.is_quick_item]
        location = self.request.GET.get("loc", "")
        current = next((entry for entry in take if str(entry.location_id) == location), None)
        if current is not None:
            take.remove(current)
            take.insert(0, current)
            context["take_location"] = current.location
        context["take_entries"] = take
        # The stock change dialog of "Take out" and "Add stock" offers the item's locations (stock_change.js).
        next_url = self.request.get_full_path()
        context["take_choices"] = [{
            "url": f"{reverse('stock_change', args=[entry.pk])}?{urlencode({'next': next_url})}",
            "item": str(entry.item), "location": entry.location.unique_identifier, "locationTitle": entry.location.title,
            "label": entry.location.title_with_code, "amount": "" if entry.amount is None else str(entry.amount),
            "kind": entry.amount_kind, "amountText": entry.amount_text, "unit": entry.item.measurement_unit.short,
            "price": "" if entry.item.sale_price is None else str(entry.item.sale_price),
            "lastStock": "true" if getattr(entry, "is_last_stock", False) else "false",
        } for entry in take]
        return context


def category_json(request, pk):
    c = models.Category.objects.get(pk=pk)
    return JsonResponse({
        'name': c.name,
        'full_name': c.full_name,
        'description': c.description,
        'parent_category': c.parent_category.pk if c.parent_category else None,
    })

class ItemKindMixin:
    """Bulk items and items tracked as unique items have their own form and inlines."""

    INLINES = {
        # Photos and files together, then where the item is.
        models.Item.Kind.BULK: [forms.ItemImageInline, forms.ItemFileInline, forms.ItemLocationInline],
        models.Item.Kind.UNIQUE: [forms.ItemImageInline, forms.ItemFileInline],
    }

    def get_kind(self):
        return self.object.kind

    def get_form_class(self):
        return forms.ITEM_FORMS[self.get_kind()]

    def get_inlines(self):
        return self.INLINES[self.get_kind()]

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs, kind=self.get_kind())
        # Scripts and styles of the form and all sections, each included once.
        context["page_media"] = sum((inline.media for inline in context.get("inlines", [])), context["form"].media)
        return context


class CreateItemView(ItemEditorPermissionMixin, ItemKindMixin, extra_views.CreateWithInlinesView):
    permission_required = "inventory.add_item"
    model = models.Item
    template_name = "inventory/item_formset.html"
    extra_context = {"title": _("Create Item")}
    # A new item comes with its first stock entry or its first unique item. Both are on
    # the page so switching the kind keeps what was entered; only the chosen one is saved.
    KIND_INLINES = {
        models.Item.Kind.BULK: forms.ItemLocationInline,
        models.Item.Kind.UNIQUE: forms.FirstUniqueItemInline,
    }
    INLINES = dict.fromkeys(models.Item.Kind.values, [forms.ItemImageInline, forms.ItemFileInline, *KIND_INLINES.values()])

    def get_kind(self):
        # The choice in the form, else the one the page was opened with.
        kind = self.request.POST.get("kind") or self.request.GET.get("kind")
        return kind if kind in models.Item.Kind.values else models.Item.Kind.BULK

    def allow_unique(self):
        return self.request.user.has_perms(UNIQUE_ITEM_CREATE_PERMISSIONS)

    def get_permission_required(self):
        if self.request.method == "POST" and self.get_kind() == models.Item.Kind.UNIQUE:
            return (self.permission_required, *UNIQUE_ITEM_CREATE_PERMISSIONS)
        return (self.permission_required,)

    def get_form_class(self):
        return forms.NewItemForm

    def get_form_kwargs(self):
        return {**super().get_form_kwargs(), "allow_unique": self.allow_unique()}

    def get_initial(self):
        kind = self.get_kind() if self.allow_unique() else models.Item.Kind.BULK
        return {**super().get_initial(), "kind": kind}

    def post(self, request, *args, **kwargs):
        try:
            return self.process(request)
        except services.LabelIdError as error:
            # Someone claimed the label in the meantime; nothing was saved.
            messages.error(request, str(error))
            return redirect(request.get_full_path())

    def process(self, request):
        """Like extra_views' post, but only the chosen kind's part is validated and saved."""
        self.object = None
        form = self.get_form(self.get_form_class())
        form_validated = form.is_valid()
        if form_validated:
            self.object = form.save(commit=False)
        inlines = self.construct_inlines()
        other = self.KIND_INLINES[models.Item.Kind.UNIQUE if self.get_kind() == models.Item.Kind.BULK else models.Item.Kind.BULK]
        chosen = [formset for formset in inlines if formset.model is not other.model]
        if form_validated and all_valid(chosen):
            return self.forms_valid(form, chosen)
        self.object = None
        return self.forms_invalid(form, inlines)

    @transaction.atomic
    def forms_valid(self, form, inlines):
        response = super().forms_valid(form, inlines)
        # The first unique item and its ID are saved together with the item, or nothing is.
        for formset in inlines:
            if formset.model is models.UniqueItem:
                for unique_form in formset.forms:
                    code = unique_form.cleaned_data.get("label_code")
                    if code:
                        services.claim(code, unique_form.instance, self.request.user)
                    else:
                        services.generate_and_claim(unique_form.instance, self.request.user)
        # extra_views chose the redirect before the inlines were saved.
        return redirect(self.get_success_url()) if self.object.tracks_unique_items else response

    def get_success_url(self):
        if self.object.tracks_unique_items:
            # The first unique item's page shows the label to print.
            first = self.object.unique_items.order_by("pk").first()
            return first.get_absolute_url() if first else self.object.get_absolute_url()
        # Back to the location the item was added from, else to the new item.
        location = self._get_location()
        return (location or self.object).get_absolute_url()

    def _get_location(self):
        if "location_id" in self.request.GET:
            location_id = self.request.GET.get("location_id")
            try:
                location_id = int(location_id)
                return models.Location.active.get(pk=location_id)
            except (ValueError, models.Location.DoesNotExist):
                pass
        return None

    def get_context_data(self, **kwargs):
        ctxt = super().get_context_data(**kwargs)
        location = self._get_location()
        if location is not None:
            ctxt['location'] = location
        return ctxt

    def construct_inlines(self):
        location = self._get_location()
        if location is not None:
            self.kwargs["initial"] = [{"location": location}]
        return super().construct_inlines()


class UpdateItemView(ItemEditorPermissionMixin, ItemKindMixin, extra_views.UpdateWithInlinesView):
    permission_required = "inventory.change_item"
    model = models.Item
    queryset = models.Item.active.all()
    template_name = "inventory/item_formset.html"
    extra_context = {"title": _("Update Item")}

    def get_success_url(self):
        return self.object.get_absolute_url()


class SearchableItemListView(LabelIdSearchMixin, ListView):
    model = models.Item
    queryset = models.Item.active.all()
    paginate_by = 25
    template_name = "inventory/item_list.html"

    def get_queryset(self):
        try:
            queryset = super().get_queryset().prefetch_related(Prefetch(
                "itemlocation_set", queryset=models.ItemLocation.objects.filter(location__is_deleted=False).select_related("location"),
            ), Prefetch(
                "itemimage_set", queryset=models.ItemImage.objects.select_related("unique_item"),
            ), Prefetch(
                "unique_items", to_attr="active_unique_items",
                queryset=annotate_label_code(models.UniqueItem.active.select_related("location"))
                .order_by("location__locatable_identifier", "pk"),
            ))
            query = self.request.GET.get('q')
            if query:
                in_inventory = Q(unique_items__disposed_at__isnull=True)
                queryset = queryset.filter(
                    Q(name__icontains=query) |
                    Q(description__icontains=query) |
                    Q(category__name__icontains=query) |
                    Q(itemlocation__location__is_deleted=False, itemlocation__location__unique_identifier__icontains=query) |
                    Q(itemlocation__location__is_deleted=False, itemlocation__location__name__icontains=query) |
                    in_inventory & Q(unique_items__location__unique_identifier__icontains=query) |
                    in_inventory & Q(unique_items__location__name__icontains=query) |
                    in_inventory & Q(unique_items__name__icontains=query) |
                    Q(itemimage__ocr_text__icontains=query)
                ).distinct()
            return queryset
        except Exception:
            logger.exception("Failed to search inventory items")
            return self.model.objects.none()


class SearchableLocationListView(
        LabelIdSearchMixin,
        extra_views.SearchableListMixin,
        extra_views.SortableListMixin,
        ListView):
    search_fields = [
        "locatable_identifier", "name", "descriptive_identifier",
        "purpose", "physical_description", "former_codes__code",
    ]
    search_date_fields = []
    sort_fields = ["unique_identifier"]
    model = models.Location
    queryset = models.Location.active.prefetch_related(Prefetch(
        "itemlocation_set", queryset=models.ItemLocation.objects.filter(item__is_deleted=False),
    ))
    paginate_by = 100


class StructureOverviewView(TemplateView):
    """Levels and axes: the building structure on one page, from the inventory (docs/location-structure.md)."""
    template_name = "inventory/structure_overview.html"

    def get_context_data(self, **kwargs):
        return super().get_context_data(overview=structure_overview(), **kwargs)


class ParentLocationAutocompleteView(LocationResults, autocomplete.Select2QuerySetView):
    def get_queryset(self):
        queryset = models.Location.active.filter(type__no_sublocations=False).select_related("parent_location")
        try:
            moved = models.Location.objects.select_related("type").get(pk=int(self.forwarded.get("id")))
        except (TypeError, ValueError, models.Location.DoesNotExist):
            moved = None
        # Shelves and cabinets go into a level, room or area, or onto a pallet (Location.clean).
        if moved is not None and moved.type.area_numbering:
            queryset = queryset.filter(models.LocationType.holding_storage_units())
        return filter_locations(queryset, self.q)

    def get_results(self, context):
        try:
            self_id = int(self.forwarded.get('id'))
        except (TypeError, ValueError):
            return super().get_results(context)
        if self_id == 0:
            return super().get_results(context)
        sorted_out = {self_id}
        while True:
            old_count = len(sorted_out)
            sorted_out.update(
                location.pk for location in context['object_list']
                if location.parent_location_id in sorted_out
            )
            if len(sorted_out) == old_count:
                break
        context['object_list'] = [x for x in context['object_list'] if x.pk not in sorted_out]
        return super().get_results(context)
