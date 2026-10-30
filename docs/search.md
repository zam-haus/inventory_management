# Search

One search over locations, categories, items and unique items: the home page (`/`). The page shows only the search
field (the heading is for screen readers); a given query stays in the field with the cursor at its end, to
type on. The magnifier beside the QR scan button in the navbar (on every page, also on narrow screens) leads
there (`navbar.js`): with a mouse and keyboard it goes straight to the search page, which Chrome loads already
while the pointer rests on the magnifier (speculation rules), so that it opens at once. On touch screens it
opens a search field right of it, over the navbar's other items, and Enter shows the results: phones open the
keyboard only for a field tapped on the same page, so a new page would need a second tap. On the search page
the magnifier goes to the page's field. To browse instead, *Items* and *Locations* in the navbar show
[trees](trees.md); an old link with a search there (`/item/?q=`, `/loc/?q=`) comes here.

## Using it

* **The field stays at hand:** below the navbar, it slides away with it while scrolling down and comes back
  with it on scrolling up.
* **Results while typing:** from two characters on, the results follow the typed words shortly after
  typing stops (`live_search.js`). Without JavaScript the form is sent as usual.
* **Scanning:** the QR scan buttons beside the field and in the navbar open a scanned label; a scanned
  product barcode (EAN) is searched for ([Camera scanning](camera-scanning.md)).
* **Codes:** Enter on a label ID, a scanned label URL or a location's code (`HW`, `WH-1.R303`, also a former
  one) opens what it belongs to (a label ID counts as a web form access, see [Label IDs](label-ids.md)); while
  typing, such a code is offered as a button. Part of a label
  ID (from three symbols, with or without the dash: `K7R`, `k7r-4`) finds what it belongs to.
* **Location codes from their start:** a word finds the codes that start with it, or one of whose parts does
  (after a dot): *R006* finds R006, R006.a, R006.b, *R00* finds R000 to R009 with their compartments, *R3*
  also HW.R3. The location with exactly that code comes first. A single symbol matches a code only whole.
* **One list:** locations, categories, items and unique items mixed, those whose name (or purpose, or code,
  or label ID, or a category's keyword) matches first; at the same rank locations first, then categories, then
  items and unique items; locations by code. Each shows the icon of its kind before its name (an item tracked as
  unique items `box-star-stack`, a category `folder`, [icons](icons.md)). A category shows the categories above it,
  what belongs there (the first line of its description) and, as in the item tree, its counted and unique items,
  those below it included; it leads to its page, where the search goes on within it ([trees](trees.md)). An item shows where it is stored with its stock or its unique items (named as
  everywhere: item, own name, label ID), a unique item its label ID after its name and its location, a location
  the path above it and, as in the location tree, its sub-locations by kind (whole subtree) and the items and unique
  items right there ([trees](trees.md)). A unique item's name leads to that unique item; a place's name leads to it, its code chip opens it in brief
  ([locations](locations.md)). The words are marked; matches elsewhere are named, e.g. "Found in text on a
  photo".
* **By kind:** below the field, how many hits there are of each kind ("3 locations", "12 items", "500+ unique
  items" beyond the cap). With none chosen all are shown; a click chooses a kind, so the first shows only that kind,
  further ones add theirs, and a click on a chosen one leaves it out again (none, or all, chosen is the same). The
  choice stays for the next words and on Enter (`?kinds=item,unique`); a chosen kind without hits stays in the
  summary to leave it out again. All kinds are counted up to the cap whatever is shown (the backend fetches up to 500 of each;
  scanning the table costs the same). The same on a category's page, without locations. Without JavaScript the
  kinds are links.
* **Copying:** only the title, the places and the code chips can be clicked, so the text can be selected and
  copied. A click elsewhere in a row opens the result, unless text was selected.
* **Words:** every word must match. A word may match where an entry is, so that *Schraubendreher
  Holzwerkstatt* finds the screwdrivers in the wood workshop and its shelves, but at least one word must
  match the entry itself: *Holzwerkstatt* alone finds the workshop, not everything stored in it.
* **More results while scrolling:** 50 at a time, loaded when the end of the list comes near (without
  JavaScript a "More results" link). After 500 results, more words narrow the search.
* **Keyboard:** the up and down arrow keys move between the results (down from the field to the first, up
  from the first back to it). The current result is marked and its photos open large below it; left and
  right go through them, Escape closes them. Enter and space open the result.
* **Photos:** the photo of a result (with the number of photos when there are more) opens them large below
  it. Swipe sideways through them, up or down to the photos of the next or previous result with photos.
  Items show their own photos, then those of their unique items; locations their overview photo. The
  originals are loaded only when shown.

## What is searched

| Entry | Searched |
|---|---|
| Location | name, purpose, code (short name, unique and locatable identifier, whole), physical description |
| Item | name, description, category (with the categories above it), barcodes, its photos (description, recognized text), its documents (description) |
| Unique item | the item's name and category (with the categories above it), its own name, notes, its own photos and documents |
| Category | its name, its keywords (synonyms, so they rank like the name; the matching ones are named: "Found in keywords: Spax") and the first line of its description (the next lines say what belongs elsewhere, "Nicht hier: …", and are not searched) |
| Where it is | the path of a location, of an item's places and of a unique item's location, the categories above a category (*words* above) |

Items are found by their category's name (and those above it), not by its keywords: a keyword such as *Akku*
would list hundreds of items; the category itself is the hit, and its page lists them.

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
  without a search service. `categories.py` finds the categories: a few hundred, matched in Python, whatever
  finds the rest. Production will use Meilisearch (planned), with this as fallback. Each kind
  keeps its order (hits on the name first, then by name); `search()` merges them by that, so pages of
  results neither repeat nor skip a hit.
* `render.py` loads what the results show from the database, in a fixed number of queries; a search
  index that is behind never shows what is gone. `listed()` makes the same rows for lists that are no search.
* `SearchView` (`inventory/views.py`), templates `search.html`, `search_results.html` (alone with
  `?partial=1`, for searching while typing) and, for further pages (`?offset=`), `results/more.html`.
  `live_search.js` does the typing; the rows are result rows (below).

## Result rows

The search results and every other list of locations, categories, items and unique items show the same rows and
behave the same: a category's items ([trees](trees.md)), a location's items, unique items and sub-locations
([locations](locations.md)), an item's places and unique items. Each row: the photo (or the icon of its kind),
the title with the kind's icon, a location's code chip, where it is, then what the list adds beside it (an amount
with the stock button, a usage level, what is in a location or category as in the trees) and below it (a description, a sale value). What the
search found is marked only in the search. In a location's own lists, places at that location are left out, and so
is "On the map".

* A click on a row outside its links, buttons and chips opens it, unless text was selected there.
* The photo opens the row's photos large below it; swipe sideways through them, up or down to the photos of
  the next or previous row with photos in the same list.
* The up and down arrow keys move between the rows of one list (Tab goes on to the next list); from a search
  field down to the first row and back up. Left and right go through the open photos, Escape closes them,
  Enter or space opens the row. A row in a collapsed list ([locations](locations.md#long-lists)) opens the list.
* Long lists that come in pages (search, a category's items) load the next rows when their end comes near;
  without JavaScript a link leads there.

`search/render.py` (`Entry`), templates `results/entries.html` (a row; per list `here`, `row_aside`,
`row_details` with the templates in `results/rows/`), `results/list.html`, `results/more.html`,
`results/next.html`; `results.css` on every page. The kinds' icons are drawn once per page as `<symbol>`s that each
row refers to (`result_icon`, as in the [trees](trees.md)): a busy location's page of 850 rows had 2.8 MB of
inline icons otherwise. The sprite, the photo viewer (`results/viewer.html`) and `results.js` come only with pages
that show rows or get them while typing (`{% result_rows %}`, added by `base.html` at its end). Optional apps add to a row through the slots `result_entry.place` and `result_entries.start` (maps: "On the
map", and where the rows' locations are, loaded at once). Tests: `inventory/tests/test_result_lists.py`.
