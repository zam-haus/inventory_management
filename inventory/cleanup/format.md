# Cleanup proposals for the ZAM inventory

This file is an export of the inventory of the ZAM, a makerspace: its category tree (`categories`) and the texts of
all its items (`items`). Its purpose: propose changes that clean up and standardize the item names, descriptions
and categories and the category tree. A person reviews every proposed change and accepts or declines it; nothing
changes without that.

## What the export holds

* `exported_at`: when it was taken. Copy it into the proposals.
* `categories`: every category with `id`, `name`, `path` (the names from the top down, separated by `/`),
  `parent` (the `id` of the category above it, `null` at the top level), `description`, `keywords` (further words
  the category is found by, separated by commas), `naming` (how its items are named: a pattern with an example,
  e.g. `Holzschraube <Durchmesser> × <Länge> mm, <Kopfform>: Holzschraube 4 × 40 mm, Senkkopf`; often still
  empty) and `items` (how many items are directly in it).
* `items`: every item with `id`, `kind` (`bulk`: counted, e.g. screws; `unique`: tracked as single objects, each
  with its own label, e.g. a drill press), `name`, `description` (Markdown), `category` (an `id` or `null`),
  `category_path`, `barcodes` (`id`, `data` and `type`), `photos` (each with its `id`, `description` and `text`,
  the text recognized on the photo by OCR, often noisy and incomplete, empty for photos without text) and `files`
  (`id` and `description` of attached documents).

## Guidelines

* The texts are German; keep them German.
* Propose only changes: leave out items and fields that stay as they are.
* Base changes on what the export says (name, description, barcodes, the text on photos). Do not invent facts:
  no dimensions, brands or models that are not clearly there. OCR text is noisy; use only what is clearly legible.
* Keep names short: what the item is and what sets it apart from similar items (e.g. size, material). Details
  beyond that go into the `description`: manufacturer and vendor details, model or article number, variant, the
  list of included parts. Move such details out of a name into the description rather than dropping them.
* Follow the conventions most items already follow, so that similar items are named alike. Where a category has
  no `naming` yet, derive it from how most of its items are named now and propose it (an `update` with `naming`);
  then name its items by it. Propose a better `naming` where the current one does not fit its items.
* Give a `reason`, short and in German; the reviewer sees it, and it is kept in the change log.
* Give the `source` of every item proposal: what its reason is mainly based on, so that the reviewer can check it
  (see below).
* Give every operation and item proposal a `confidence`: how sure you are that it is right, from `0` (a guess) to
  `1` (certain). The reviewer goes through the uncertain ones first.
* Give every operation and item proposal a `type`, what kind of change it is (one of them, or a list):
  `"typo"` (a spelling mistake fixed), `"naming"` (a name brought in line with the naming of its category or of
  similar items), `"description"` (a description completed or cleaned up), `"category"` (an item put into another
  category), `"structure"` (the category tree changed) or `"other"`.
* Every category operation and every item field is accepted or declined on its own. Keep operations independent
  where you can. A change that depends on a declined one (e.g. an item moved into a category whose creation was
  declined) is skipped.

## The proposals file

One JSON object:

```json
{
  "kind": "zam-inventory-cleanup-proposals",
  "version": 1,
  "exported_at": "<exported_at of the export>",
  "categories": [],
  "items": []
}
```

`categories` holds operations on the category tree. They are carried out in their order, all before the item
proposals. An operation refers to a category by its `id` from the export (a number) or, if an earlier operation
in this file creates it, by its `ref` (a string you choose, unique within the file, e.g. `"neu-akkuwerkzeug"`).
Category names are at most 512 characters long and must not contain `/`. Every operation has a `reason`, a
`confidence` and a `type` (usually `"structure"`, or `"naming"` for a new `naming`).

* **create**: a new category. `parent` is where it goes (`null`: at the top level); `description`, `keywords` and
  `naming` are optional.
  `{"op": "create", "ref": "neu-akkuwerkzeug", "name": "Akkuwerkzeuge", "parent": 7, "description": "…", "keywords": "…", "reason": "…"}`
* **update**: changes the name, description, keywords or naming of a category; only the given fields change.
  `{"op": "update", "id": 12, "name": "Klebebänder", "reason": "…", "confidence": 0.9, "type": "typo"}`
  `{"op": "update", "id": 13, "naming": "Holzschraube <Durchmesser> × <Länge> mm, <Kopfform>: Holzschraube 4 × 40 mm, Senkkopf", "reason": "so heißen 41 von 52 Sachen", "confidence": 0.8, "type": "naming"}`
* **move**: moves a category, with its subcategories and items, below another one (`null`: to the top level),
  not into itself or one of its subcategories.
  `{"op": "move", "id": 12, "parent": 3, "reason": "…"}`
* **join**: joins categories: the items and subcategories of those in `ids` go to `into`, and they are deleted
  (`into` stays, also if it is listed in `ids`). Their keywords are added to those of `into`.
  `{"op": "join", "ids": [14, 15], "into": 13, "reason": "…"}`
* **split**: splits a category into new ones (`parts`), each with the items and direct subcategories listed in it.
  A part goes where the split category is (beside it, below the same parent) unless it gives a `parent`.
  `description`, `keywords` and `naming` of a part are optional. With `"keep": false` (the default) the split category is
  deleted, so every item directly in it and every direct subcategory must be listed in a part; with
  `"keep": true` it stays with what is not listed.
  `{"op": "split", "id": 20, "parts": [{"ref": "neu-holzleim", "name": "Holzleim", "items": [101, 102], "categories": []}, {"ref": "neu-sekundenkleber", "name": "Sekundenkleber", "items": [103], "categories": [21]}], "keep": false, "reason": "…"}`
* **delete**: deletes a category. Its subcategories move to its parent; its items to `items_to`, by default to
  its parent (at the top level: they have no category then).
  `{"op": "delete", "id": 30, "items_to": 13, "reason": "…"}`

`items` holds one proposal per item: its `id`, the fields that change, a `reason`, a `source`, a `confidence`
and a `type`. `name` must
not be empty (at most 512 characters); `description` is Markdown; `category` is an `id`, a `ref` of a category
created above, or `null` (no category). It refers to the tree after the category operations.

`source` names the one piece of the item's data the reason is mainly based on; the reviewer is shown it next to
the proposal:

* `"photo:<id>"`: a photo of the item (`photos`), its picture, description or recognized text
* `"barcode:<id>"`: one of its barcodes
* `"file:<id>"`: the description of one of its documents
* `"name"`, `"description"`, `"category"`: what the item has now in that field
* `"convention"`: no data of the item, but how similar items are named or sorted

```json
{"id": 4711, "name": "Holzschraube 4 × 40 mm", "description": "Senkkopf, Torx T20, verzinkt.", "category": 13, "reason": "Maße und Kopfform vom Foto der Packung", "source": "photo:9021", "confidence": 0.85, "type": ["naming", "category"]}
```
