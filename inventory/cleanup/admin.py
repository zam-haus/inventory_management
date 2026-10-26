"""The cleanup in the admin (docs/item-cleanup.md): Inventory → Cleanup imports. The list offers the export; adding
uploads a proposals file; an import's page lists its changes to accept, defer or decline, and applies the accepted
ones, as often as needed (deferred ones accepted later)."""
import json
from collections import defaultdict
from dataclasses import dataclass, field as dataclass_field
from itertools import groupby

from django import forms
from django.contrib import admin, messages
from django.core.exceptions import PermissionDenied
from django.core.paginator import Paginator
from django.core.serializers.json import DjangoJSONEncoder
from django.http import HttpResponse, HttpResponseRedirect
from django.utils.cache import patch_cache_control
from django.shortcuts import get_object_or_404
from django.template.response import TemplateResponse
from django.urls import path, reverse
from django.utils import timezone
from django.utils.translation import gettext as _, gettext_lazy, ngettext

from sorl.thumbnail import get_thumbnail

from ..models import CleanupImport, Item, ItemBarcode, ItemFile, ItemImage
from . import export, proposals

PAGE = 50
THUMBNAIL = "160x160"  # as in the search results, so that most exist already
EXPORT_PERMISSIONS = ("inventory.view_item", "inventory.view_category")
FIELD_LABELS = {"name": gettext_lazy("Name"), "description": gettext_lazy("Description"),
                "category": gettext_lazy("Category")}


class UploadForm(forms.Form):
    file = forms.FileField(label=gettext_lazy("Proposals file"),
                           help_text=gettext_lazy("The JSON file with the proposals (format: see the export)."))

    def clean_file(self):
        upload = self.cleaned_data["file"]
        try:
            self.cleaned_data["proposals"] = proposals.load(upload.read())
        except proposals.Invalid as error:
            raise forms.ValidationError(str(error))
        return upload


@admin.register(CleanupImport)
class CleanupImportAdmin(admin.ModelAdmin):
    list_display = ("file_name", "created_at", "created_by", "exported_at", "change_count", "applied_at")
    list_display_links = ("file_name",)
    change_list_template = "admin/inventory/cleanup/change_list.html"

    def get_urls(self):
        return [path("export/", self.admin_site.admin_view(self.export_view), name="inventory_cleanupimport_export"),
                path("photo/<int:pk>/", self.admin_site.admin_view(self.photo_view, cacheable=True), name="inventory_cleanupimport_photo"),
                *super().get_urls()]

    @admin.display(description=gettext_lazy("changes"))
    def change_count(self, cleanup):
        return len(cleanup.proposals.get("categories", [])) + len(cleanup.proposals.get("items", []))

    def changelist_view(self, request, extra_context=None):
        return super().changelist_view(request, {**(extra_context or {}),
                                                 "may_export": request.user.has_perms(EXPORT_PERMISSIONS)})

    def export_view(self, request):
        if not request.user.has_perms(EXPORT_PERMISSIONS):
            raise PermissionDenied
        response = HttpResponse(json.dumps(export.build(), cls=DjangoJSONEncoder, ensure_ascii=False, indent=1),
                                content_type="application/json; charset=utf-8")
        name = f"inventory-cleanup-{timezone.localdate():%Y-%m-%d}.json"
        response["Content-Disposition"] = f'attachment; filename="{name}"'
        return response

    def photo_view(self, request, pk):
        """A photo's thumbnail, made when the review page's browser asks for it (lazily, while scrolling), so
        that the page itself does not wait for thousands of thumbnails."""
        if not self.has_view_or_change_permission(request):
            raise PermissionDenied
        image = get_object_or_404(export.rows(ItemImage), pk=pk)
        response = HttpResponseRedirect(get_thumbnail(image.image, THUMBNAIL).url)
        patch_cache_control(response, private=True, max_age=86400)
        return response

    def add_view(self, request, form_url="", extra_context=None):
        if not self.has_add_permission(request):
            raise PermissionDenied
        form = UploadForm(request.POST or None, request.FILES or None)
        if request.method == "POST" and form.is_valid():
            data = form.cleaned_data["proposals"]
            cleanup = CleanupImport(created_by=request.user, file_name=form.cleaned_data["file"].name[:255],
                                    exported_at=proposals.exported_at(data), proposals=data)
            stale = proposals.stale_keys(cleanup)  # changed since the export: to be looked at first
            cleanup.decisions = dict.fromkeys(stale, proposals.DEFER)
            cleanup.save()
            if cleanup.exported_at is None:
                messages.warning(request, _("The file does not say when its export was taken (“exported_at”), so "
                                            "items changed since cannot be recognized."))
            elif stale:
                messages.warning(request, ngettext(
                    "%(count)s item field changed since the export; its proposal is deferred.",
                    "%(count)s item fields changed since the export; their proposals are deferred.",
                    len(stale)) % {"count": len(stale)})
            return HttpResponseRedirect(reverse("admin:inventory_cleanupimport_change", args=[cleanup.pk]))
        return TemplateResponse(request, "admin/inventory/cleanup/upload.html", {
            **self.admin_site.each_context(request), "opts": self.model._meta, "form": form,
            "title": _("Upload cleanup proposals"), "may_export": request.user.has_perms(EXPORT_PERMISSIONS)})

    def change_view(self, request, object_id, form_url="", extra_context=None):
        cleanup = get_object_or_404(CleanupImport, pk=object_id)
        if not self.has_view_or_change_permission(request, cleanup):
            raise PermissionDenied
        editable = self.has_change_permission(request, cleanup)
        if request.method == "POST":
            if not editable:
                raise PermissionDenied
            return self.post(request, cleanup)
        return TemplateResponse(request, "admin/inventory/cleanup/review.html",
                                {**self.admin_site.each_context(request), **review_context(request, cleanup, editable)})

    def post(self, request, cleanup):
        action, _colon, scope = request.POST.get("action", "save").partition(":")  # e.g. "accept_all:items.name"
        url = request.get_full_path()
        if action == "apply":
            save_decisions(request, cleanup)
            try:
                done = proposals.apply(cleanup, request.user)
            except proposals.Invalid as error:
                messages.error(request, str(error))
                return HttpResponseRedirect(url)
            applied = [change for change in done.categories + done.items if change.applies]
            skipped = [change for change in done.categories + done.items if change.accepted and change.problem]
            messages.success(request, _("%(applied)s changes applied, %(skipped)s accepted ones skipped.") % {
                "applied": len(applied), "skipped": len(skipped)})
            return HttpResponseRedirect(reverse("admin:inventory_cleanupimport_change", args=[cleanup.pk]))
        if action in BULK:  # e.g. "defer_all:items.name"
            decisions = dict(cleanup.decisions)
            for key in scope_keys(proposals.plan(cleanup), scope, request):
                decide(decisions, key, BULK[action])
            cleanup.decisions = decisions
            cleanup.save(update_fields=["decisions"])
        else:
            save_decisions(request, cleanup)
        if request.POST.get("goto"):
            url = page_url(request, request.POST["goto"])
        return HttpResponseRedirect(url)


BULK = {"accept_all": proposals.ACCEPT, "defer_all": proposals.DEFER, "decline_all": proposals.DECLINE}


def decide(decisions, key, decision):
    if decision == proposals.ACCEPT:
        decisions.pop(key, None)
    else:
        decisions[key] = decision


def save_decisions(request, cleanup):
    """The decisions on the changes shown on the page ("shown": their keys): accept, defer or decline each. The
    page's script sends those other than accepting as one JSON field ("decisions"), as Django takes at most 1000
    fields (DATA_UPLOAD_MAX_NUMBER_FIELDS) and all changes on one page can be many more; without it, one field
    each ("decide:<key>")."""
    shown = request.POST.get("shown", "").split()
    if "decisions" in request.POST:
        try:
            posted = json.loads(request.POST["decisions"])
        except ValueError:
            posted = None
        if not isinstance(posted, dict):
            return
    else:
        posted = {key: request.POST[f"decide:{key}"] for key in shown if f"decide:{key}" in request.POST}
    decisions = dict(cleanup.decisions)
    for key in shown:
        decision = posted.get(key, proposals.ACCEPT)
        decide(decisions, key, decision if decision in proposals.DECISIONS else proposals.ACCEPT)
    cleanup.decisions = decisions
    cleanup.modified = modifications(request, cleanup, set(shown))
    cleanup.save(update_fields=["decisions", "modified"])


def modifications(request, cleanup, shown):
    """CleanupImport.modified with the text fields shown on the page: a value other than the proposed one is
    kept (accepted with changes), the proposed one drops it. The script sends the changed ones as one JSON field
    ("modified"); without it each field comes on its own ("modify:<key>")."""
    proposed = {f"i{data['id']}.{name}": data[name] for data in cleanup.proposals.get("items", [])
                if isinstance(data, dict) and isinstance(data.get("id"), int)
                for name in proposals.TEXT_FIELDS if isinstance(data.get(name), str)}
    keys = [key for key in shown if key in proposed]
    if "modified" in request.POST:
        try:
            posted = json.loads(request.POST["modified"])
        except ValueError:
            posted = {}
        values = {key: posted.get(key, proposed[key]) for key in keys} if isinstance(posted, dict) else {}
    else:
        values = {key: request.POST[f"modify:{key}"] for key in keys if f"modify:{key}" in request.POST}
    modified = dict(cleanup.modified)
    for key, value in values.items():
        value = str(value).replace("\r\n", "\n").strip()
        if value == proposed[key].strip():
            modified.pop(key, None)
        else:
            modified[key] = value
    return modified


def scope_keys(plan, scope, request):
    """Keys of the changes an "accept all", "defer all" or "decline all" covers: those of the category tree or the
    items that the page's filters let through (all pages)."""
    chosen = Filters(request.GET)
    changes = {"categories": plan.categories, "items": plan.items}.get(scope, [])
    return {change.key for change in changes if chosen.decidable(change)}


class Filters:
    """The review page's filters (its query string): which changes it lists, and which the bulk decisions cover.
    Field, state, type and a confidence range (in percent); outside the full range, changes without a confidence
    are left out."""

    def __init__(self, query):
        self.field, self.show, self.type = query.get("field", ""), query.get("show", ""), query.get("type", "")
        self.low, self.high = percent(query.get("min"), 0), percent(query.get("max"), 100)

    @property
    def active(self):
        return bool(self.field or self.show or self.type) or (self.low, self.high) != (0, 100)

    def match(self, change):
        if self.field and change.op != self.field:
            return False
        if self.show and not (self.show == "problems" and change.problem or self.show == "stale" and change.stale or
                              self.show == change.decision != proposals.ACCEPT or
                              self.show == "modified" and change.modified):
            return False
        if self.type and self.type not in change.types:
            return False
        if (self.low, self.high) != (0, 100) and (
                change.confidence is None or not self.low <= round(change.confidence * 100) <= self.high):
            return False
        return True

    def decidable(self, change):
        return not change.unchanged and self.match(change)

    def listed(self, change):
        """Category operations applied already are listed while nothing is filtered; item fields never."""
        return self.decidable(change) or change.unchanged and change.item is None and not self.active


def percent(value, default):
    try:
        return min(100, max(0, int(value)))
    except (TypeError, ValueError):
        return default


def page_url(request, page):
    query = request.GET.copy()
    query["page"] = page
    return f"{request.path}?{query.urlencode()}"


SORTS = {
    "": gettext_lazy("as in the file"),
    "confidence": gettext_lazy("least confident first"),
    "-confidence": gettext_lazy("most confident first"),
    "type": gettext_lazy("by type"),
}
TYPE_LABELS = {"typo": gettext_lazy("typo"), "naming": gettext_lazy("naming"),
               "description": gettext_lazy("description"), "category": gettext_lazy("category"),
               "structure": gettext_lazy("structure"), "other": gettext_lazy("other")}


def sort_key(sort):
    """For sorting ItemRows-to-be ((item, changes)): by the proposal's confidence or type; those without last."""
    def confidence(row):
        value = row[1][0].confidence
        return (value is None, value if sort == "confidence" else -(value or 0))

    def kind(row):
        types = row[1][0].types
        return (not types, proposals.CHANGE_TYPES.index(types[0]) if types else 0)
    return {"confidence": confidence, "-confidence": confidence, "type": kind}.get(sort)


FILTERS = {
    "": gettext_lazy("all"),
    "problems": gettext_lazy("cannot be carried out"),
    "stale": gettext_lazy("changed since the export"),
    "deferred": gettext_lazy("deferred"),
    "declined": gettext_lazy("declined"),
    "modified": gettext_lazy("accepted with changes"),
}


@dataclass
class ItemRow:
    """An item on the review page: its changed fields, its photos, and the source its proposal is based on."""
    item: Item
    changes: list
    photos: list = dataclass_field(default_factory=list)
    source_photo: int = None  # the photo that is the source
    source_label: str = ""
    evidence: str = ""  # what the source says (e.g. the text on the photo)
    source_problem: str = ""


SOURCE_LABELS = {"name": gettext_lazy("its name"), "description": gettext_lazy("its description"),
                 "category": gettext_lazy("its category"),
                 "convention": gettext_lazy("how similar items are named or sorted")}


def item_rows(rows):
    """ItemRows for (item, changes) with the item's photos, barcodes and files (those the export holds)."""
    items = [item for item, _changes in rows]
    photos, barcodes, files = defaultdict(list), {}, {}
    for image in export.rows(ItemImage).filter(item__in=items).order_by("-is_primary", "pk"):
        photos[image.item_id].append(image)
    for barcode in export.rows(ItemBarcode).filter(item__in=items):
        barcodes[barcode.pk] = barcode
    for file in export.rows(ItemFile).filter(item__in=items):
        files[file.pk] = file
    result = []
    for item, changes in rows:
        row = ItemRow(item, changes, photos[item.pk])
        try:
            source = proposals.source_of(changes[0].data)
        except proposals.Invalid as error:
            row.source_problem = str(error)
            source = ()
        if source is None:
            row.source_problem = _("No source given.")
        elif source:
            describe_source(row, *source, barcodes, files)
        result.append(row)
    return result


def describe_source(row, kind, pk, barcodes, files):
    item = row.item
    if kind == "photo":
        numbers = {image.pk: number for number, image in enumerate(row.photos, 1)}
        if pk not in numbers:
            row.source_problem = _("The item has no photo %(id)s.") % {"id": pk}
            return
        image = row.photos[numbers[pk] - 1]
        row.source_photo = pk
        row.source_label = _("photo %(number)s of %(count)s") % {"number": numbers[pk], "count": len(row.photos)}
        row.evidence = "\n\n".join(part for part in ((image.description or "").strip(), (image.ocr_text or "").strip())
                                    if part)
    elif kind in ("barcode", "file"):
        found = (barcodes if kind == "barcode" else files).get(pk)
        if found is None or found.item_id != item.pk:
            row.source_problem = (_("The item has no barcode %(id)s.") if kind == "barcode" else
                                  _("The item has no document %(id)s.")) % {"id": pk}
            return
        row.source_label = _("barcode") if kind == "barcode" else _("document")
        row.evidence = found.data if kind == "barcode" else found.description
    else:
        row.source_label = SOURCE_LABELS[kind]
        row.evidence = {"name": item.name or "", "description": item.description,
                        "category": item.category.full_name if item.category else _("no category"),
                        "convention": ""}[kind]


def links(request, name, options):
    """(label, URL, selected) for each option of a filter or sorting, keeping the others (and "all on one page")."""
    current = request.GET.get(name, "")
    result = []
    for value, label in options:
        query = request.GET.copy()
        query[name] = value
        if query.get("page") != "all":
            query.pop("page", None)
        result.append((label, f"?{query.urlencode()}", value == current))
    return result


def review_context(request, cleanup, editable):
    plan = proposals.plan(cleanup, request.user)
    chosen = Filters(request.GET)
    sort = request.GET.get("sort", "") if request.GET.get("sort", "") in SORTS else ""
    categories = [change for change in plan.categories if chosen.listed(change)]
    changes = [change for change in plan.items if chosen.listed(change)]
    for change in categories + changes:
        change.label = FIELD_LABELS.get(change.op, "")
        change.type_labels = [TYPE_LABELS[value] for value in change.types]
    rows = [(item, list(group)) for item, group in groupby(changes, key=lambda change: change.item)]
    if sort:
        rows.sort(key=sort_key(sort))
    everything = request.GET.get("page") == "all"
    page = None if everything else Paginator(rows, PAGE).get_page(request.GET.get("page"))
    rows = item_rows(rows if everything else page.object_list)
    category_counts, item_counts = plan.counts(plan.categories), plan.counts(plan.items)
    shown_keys = [change.key for change in categories] + [change.key for row in rows for change in row.changes]
    keep = {name: value for name, value in request.GET.items() if name not in ("min", "max") and (
        name != "page" or value == "all")}
    return {
        "opts": CleanupImport._meta, "cleanup": cleanup, "title": str(cleanup), "editable": editable,
        "plan": plan, "categories": categories, "page": page, "rows": rows, "everything": everything,
        "shown_keys": " ".join(shown_keys), "filters": chosen, "keep": keep,
        "category_scope": sum(chosen.decidable(change) for change in plan.categories),
        "item_scope": sum(chosen.decidable(change) for change in plan.items),
        "field": chosen.field, "link_groups": [
            links(request, "field", [("", _("all fields"))] + list(FIELD_LABELS.items())),
            links(request, "show", list(FILTERS.items())),
            links(request, "type", [("", _("all types"))] + list(TYPE_LABELS.items())),
            links(request, "sort", list(SORTS.items()))],
        "field_label": FIELD_LABELS.get(chosen.field, ""), "category_counts": category_counts, "item_counts": item_counts,
        "applying": category_counts["ok"] + item_counts["ok"],
        "result": cleanup.result if cleanup.applied_at else None,
    }
