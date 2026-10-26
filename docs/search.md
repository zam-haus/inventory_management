# Search

One search over locations, items and unique items: the home page (`/`). The page shows only the search
field (the heading is for screen readers); a given query stays in the field with the cursor at its end, to
type on. The magnifier beside the QR scan button in the navbar (on every page, also on narrow screens) leads
there (`navbar.js`): with a mouse and keyboard it goes straight to the search page, which Chrome loads already
while the pointer rests on the magnifier (speculation rules), so that it opens at once. On touch screens it
opens a search field right of it, over the navbar's other items, and Enter shows the results: phones open the
keyboard only for a field tapped on the same page, so a new page would need a second tap. On the search page
the magnifier goes to the page's field. The item and location lists (`/item/`, `/loc/`) keep
their own filters; the print button of the location list builds on the location filter.

## Using it

* **Results while typing:** from two characters on, the results follow the typed words shortly after
  typing stops (`search.js`). Without JavaScript the form is sent as usual.
* **Scanning:** the QR scan buttons beside the field and in the navbar open a scanned label; a scanned
  product barcode (EAN) is searched for ([Camera scanning](camera-scanning.md)).
* **Codes:** Enter on a label ID or a scanned label URL opens what it belongs to (and counts as a web
  form access of the label ID, see [Label IDs](label-ids.md)); while typing, such a code is offered as a
  button. Codes of locations stay search text: `HW` or `WH-1.R303` find that location first.
* **One list:** locations, items and unique items mixed, those whose name (or purpose, or code) matches
  first. An item shows where it is stored with its stock, a unique item its label ID and location, a
  location the path above it. The words are marked; matches elsewhere are named, e.g. "Found in text on
  a photo".
* **Words:** every word must match. A word may match where an entry is, so that *Schraubendreher
  Holzwerkstatt* finds the screwdrivers in the wood workshop and its shelves, but at least one word must
  match the entry itself: *Holzwerkstatt* alone finds the workshop, not everything stored in it.
* **More results while scrolling:** 50 at a time, loaded when the end of the list comes near (without
  JavaScript a "More results" link). After 500 results, more words narrow the search.
* **Keyboard:** the up and down arrow keys move between the results (down from the field to the first, up
  from the first back to it). The current result is marked and its photos open large below it; left and
  right go through them, Escape closes them.
* **Photos:** the photo of a result (with the number of photos when there are more) opens them large below
  it. Swipe sideways through them, up or down to the photos of the next or previous result with photos.
  Items show their own photos, then those of their unique items; locations their overview photo. The
  originals are loaded only when shown.

## What is searched

| Entry | Searched |
|---|---|
| Location | name, purpose, code (short name, unique and locatable identifier, whole), physical description |
| Item | name, description, category, barcodes, its photos (description, recognized text), its documents (description) |
| Unique item | the item's name and category, its own name, notes, its own photos and documents |
| Where it is | the path of a location, of an item's places and of a unique item's location (*words* above) |

Deleted entries, reserved containers and unique items removed from the inventory (with their photos
and documents) are not found.

**Never searched: internal information.** What the search may find follows the rules of the
[data export](data-export.md): a field is searched only if it is listed in
`inventory/search/fields.py` *and* the export keeps it as it is (`public_export.publishable`), in rows
the export keeps (`public_export.export_filter`). So purchase prices, owners (accounts, first names,
contact details), responsible persons and internal documents are never searched, and a field the
export starts to replace drops out of the search, too. A new field is searched only once it is listed
in `fields.py`. Tests: `inventory/tests/test_search.py`.

## How it works

`inventory/search/`:

* `contains.py` finds the hits in the database (`icontains`), for development and small installations
  without a search service. Production will use Meilisearch (planned), with this as fallback. Each kind
  keeps its order (hits on the name first, then by name); `search()` merges them by that, so pages of
  results neither repeat nor skip a hit.
* `render.py` loads what the results show from the database, in a fixed number of queries; a search
  index that is behind never shows what is gone.
* `SearchView` (`inventory/views.py`), templates `search.html`, `search_results.html` (alone with
  `?partial=1`, for searching while typing) and, for further pages (`?offset=`), `search_more.html`.
  `search.js` does the typing, scrolling, keyboard and photos.
