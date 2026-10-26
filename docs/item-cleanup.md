# Cleaning up items and categories

Item names, descriptions and categories and the category tree can be cleaned up and standardized outside the
inventory, e.g. with a script or an AI tool, and the result brought back change by change. In the admin:
**Inventory → Cleanup imports**.

1. **Export** (*Export items and categories*, on the list of cleanup imports): one JSON file with the category tree
   (id, name, path, parent, description, keywords, naming, number of items) and every item's texts: name,
   description, kind, category, barcodes, its photos with their descriptions and the text recognized on them (OCR),
   and the descriptions of its documents; photos, barcodes and documents with their ids, so that a proposal can
   name them as its source. It also holds, under `format`, the description of the proposals format with
   examples ([`inventory/cleanup/format.md`](../inventory/cleanup/format.md)), so that the file explains itself to
   whoever processes it.
2. **Proposals**, made outside: one JSON file with operations on the category tree (create, update, move, join,
   split, delete) and changed item fields (name, description, category). Each comes with a reason, a confidence
   (0 to 1), a type (typo, naming, description, category, structure, other) and, for items, the source the reason
   is mainly based on: a photo, barcode or document of the item (`photo:<id>` …), one of its fields, or the
   convention of similar items.
3. **Upload** (*Add cleanup import*): the file is checked and stored; nothing changes yet. Item fields changed since
   the export (the change log after its `exported_at`, not counting cleanup imports) are deferred at first.
4. **Review**: the import's page lists every change. Category operations come first, in their order, in words
   ("Join “Kleber” into “Klebstoffe”", with what moves where), then the items, each changed field with what is
   removed and added marked. Each change and each item field gets a decision of its own (`CleanupImport.decisions`):
   *Yes* (accept, the default), *Later* (defer: not now, still to be decided) or *No* (decline); any decision can be
   changed again, also after applying. A name or description can also be accepted with changes: the reviewer's text
   is applied instead of the proposed one (`CleanupImport.modified`); changing it chooses *Yes*. Each item shows its
   photos (thumbnails, loaded while scrolling), the source of its proposal marked, and what the source says (the
   photo's description and recognized text, the barcode, …); a missing or unknown source is noted. Confidence and
   type stand next to each proposal; uncertain ones (below 50 %) stand out.
   Filters above the lists apply to the category tree and the items alike: field, state (cannot be carried out,
   changed since the export, deferred, declined, accepted with changes), type and a confidence range (two sliders,
   in percent; outside the whole range, changes without a confidence are left out). The buttons *Yes*, *Later* and
   *No* for all changes of a section decide exactly the changes the filters let through, on all pages, e.g. all
   typos above 90 %. Item changes are shown 50 items a page or all on one page and sorted as in the file, by
   confidence (least confident first, or most) or by type. The decisions are saved (also when going to another
   page).
5. **Apply**: the accepted changes, in one transaction: the category operations in their order, then the items. An
   import can be applied again and again: changes deferred and accepted later are carried out then.

The changes are gone through in order on a copy of the tree in memory, before applying (to show them) and when
applying. A change that is in place already shows as *already applied* (a green check, nothing to decide): an
item field with the proposed value (not listed, only counted), a category update or move as proposed, a category
created already (the same name in the same place, ignoring case; later changes referring to its `ref` use it), a
category deleted or joined already (its id is gone), a split done already (its category gone, its parts there).
So an import applied in parts, or a file uploaded again, does not do anything twice. A change applied before that
no longer is in place (changed since, e.g. by a member) is not applied again.

A change that cannot be carried out is shown with the reason and skipped: one that needs a change not accepted
(an item moved into a category whose creation is deferred or declined), a category that no longer exists, a move
into its own subcategory, a split that leaves items in no part, a missing permission.

## Privacy

The export holds only what the public [data export](data-export.md) keeps (`publishable` and `export_filter` in
`inventory/public_export.py`, as for the [search](search.md)): no internal documents, nothing about owners. Text
recognized on photos can still contain names (e.g. "Eigentum von …" on a label); it is in the public data export
too. `export.check_fields()` fails the export if one of its fields is no longer public.

## Changes and the change log

Item changes are saved one by one, so the [change log](change-log.md) records each with the source *Cleanup
import*, who applied it and the proposal's reason as note. This includes items moved by category operations (join,
split, delete), also deleted items. Categories have no change log; the import keeps what was applied
(`CleanupImport.result`).

## Naming of categories

A category's *naming* (`Category.naming`) says how its items are named: a pattern with an example, e.g.
"Holzschraube <Durchmesser> × <Länge> mm, <Kopfform>: Holzschraube 4 × 40 mm, Senkkopf". It is set in the admin,
shown on the category page and in the item form below the chosen category (which comes before the name there, so
that the naming is known when naming the item; `CategorySelect`, `category_select.js`), and exported; proposals can change it (`update`, or with `create` and `split`). The
format asks the processor to derive it from how most of a category's items are named now where it is still empty,
and to name the items by it. Migration `0049_cleanup_import` brings the naming worked out so far for 18 categories of the default
tree (`NAMING`); it fills only categories without a naming.

## Operations

Join adds the keywords of the joined categories to the target's. Delete moves the subcategories to the parent and
the items to `items_to` (default: the parent). Split creates the parts beside the split category unless a part
names its parent; with `keep: false` every item and direct subcategory must be in a part.

## Permissions

Export: `view_item` and `view_category`. Uploading, deciding and applying: the permissions of the cleanup import
model (`add`, `change`). Each change additionally needs the permissions for what it does: create
`add_category`; update and move `change_category`; join and delete `change_category`, `delete_category` and
`change_item`; split `add_category`, `change_category` and `change_item`; item fields `change_item`. Missing ones
are shown on the change, which is then skipped.

## Code

`inventory/cleanup/`: `export.py` (the export), `format.md` (the proposals format, part of the export),
`proposals.py` (reading, planning on the tree in memory, applying), `admin.py` (the admin pages); model
`CleanupImport` (`inventory/models/cleanup.py`); templates `templates/admin/inventory/cleanup/`. Tests:
`inventory/tests/test_cleanup.py`. With all changes on one page (thousands), the page's script sends the decisions
and changed texts as one field each (Django takes at most 1000 fields, `DATA_UPLOAD_MAX_NUMBER_FIELDS`); without
JavaScript, a page of 50 items sends them one by one. Thumbnails come through
`admin/inventory/cleanupimport/photo/<id>/`, which makes one when asked for, so that the page does not wait for
them. With 5,108 items, the export takes about half a second (2.7 MB), planning
0.4 s and applying a change to every item about 8 s (SQLite).
