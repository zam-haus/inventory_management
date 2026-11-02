# Location purpose and overview photo

Each location can have a **purpose** (one line, up to 50 characters) and one
overview photo. The purpose says what the location is for. Its description (what it looks like; `Location.description`, called physical description up to migration
inventory 0053) is kept separately.
The purpose is included in location searches.

**Dimensions:** width, depth and height in cm, each optional (`Location.width_cm`, `depth_cm`, `height_cm`), in the
grey box of its page and edited there (*Dimensions*, as the description). A compartment or drawer (a part
of the shelf's or cabinet's `sublocation_type`) without width and depth of its own has those of its shelf or
cabinet, not its height (`Location.footprint_cm`, `footprint_source`). On the map a location's rectangle has that
size ([maps](maps.md)).

## How locations are shown

A UX rule for every page, list and dialog (`inventory/location_display.py`, `{% load locations %}`):

* **The icon of its type comes first** (`geo-alt`, `bookshelf`, `eurobox-open`), also for each location in a path and
  in a sentence ([icons](icons.md)).
* **Then what people call it:** its purpose, else its name (`Location.title`). Next to a
  purpose the name follows, smaller and grey (`Location.subtitle`): "Schrauben M4 *Regal 301 Fach a*".
* **The code comes after it** (the code, `unique_identifier`; a part's own short name where it stands
  under its parent, e.g. in breadcrumbs), **always alike:** white monospace on a muted grey chip (class `loc-code`,
  `inventory/static/inventory/locations.css`). Template tags: `{% location_label location %}`
  (title, name, code; `code="…"` for another code or `""` for none, `subtitle=False` without the name),
  `{% location_path location %}` (where it is: each location above it with icon, title and short name, ›
  between them), `{% location_name location %}` (in a sentence: icon and title), `{% location_code code %}`.
* **Plain text** (page titles, messages, tooltips, select options) reads "Schrauben M4 · WH-1.R301.a"
  (`Location.title_with_code`).
* Location fields (`widgets.LocationSelect`) show their suggestions the same way, with the whole path above it
  below (each location with its icon and short name, without links, as a click chooses; `option_html`, the paths of
  a page of suggestions in one query); their autocompletes give HTML only to them (`?html=1`), the admin's fields
  get the path as text. The breadcrumb shows the path with each location's title and short name.
* **In brief:** a location's code chip opens it in a window (`location_info.js`, `/location/<id>/info/`; click,
  Enter or space): the path with the titles and short names of the locations above it, its title and code,
  overview photo and description, and *Open location*. Its name still leads to its page. Closing the window
  returns the focus to the chip. Chips in the suggestions of location fields only show the code, as a click
  there chooses the location (`label_html(info=False)`).

Label templates follow the rule too: `{{ location.title }}` first, the code after or below it inverted in
monospace ([label designs](label-designs.md)). The stored path (`descriptive_identifier`, "Halle [HAL] Regal 301
[R301] …") and the admin keep the plain names; pages show the path with icons (`{% location_path %}`): in the
breadcrumb, the location in brief, the **Location details**, moving and dissolving, the result rows.

**Purpose** (pencil) right after the title in the heading of the location page
edits the purpose in a small dialog. The camera button edits the photo in its own dialog:
it sits beside **Overview photo** in the first panel (**At this location …**), or,
while the location has no photo and that section is hidden, beside
**At this location …** itself. Without a photo yet, the camera button opens the camera right
away and the dialog follows with the new photo; with a photo, it opens the dialog,
where **Take or choose a photo** lets the phone offer camera or library. Take an
overview of everything stored at the location and keep neighbouring locations
outside the frame. The optional crop step supports dragging a selection or
adjusting its edges with sliders. You can also rotate the photo clockwise in 90° steps.
Cropping and rotation also work on the current photo without choosing it again;
they happen in the browser, and the edited photo replaces the current one when
saving. Saving without such changes does not upload the photo again.
The detail page shows a thumbnail; the link and the enlarged view use the full photo.
Each dialog saves only its own field.

The photo appears in the first panel, **At this location …**, above the item list.
Item and sub-location lists stay expanded. The heading shows the title and the code below it, the
actions to the right (those that do not fit go into the actions menu, see [icons](icons.md)). Below
it a grey box, like the item page's, holds the description, the responsible teams (its
own, else those of the location above it) and, where it applies, **Free of fire load** (marked red,
with the location it comes from); its (i) at the top right opens **Location details**: the location
path, where the responsible teams come from (own, taken over from the location it is in,
`Location.responsible_teams_source`, or none; rooms, areas and levels with their own code never take
them over), the type, former codes, description, and the type's rules for moving, sub-locations, and unique identifiers. Its columns stack
on small screens.

Editing requires `inventory.change_location`; purpose and photo are public.
Every change of a location, including those through the admin, is recorded in the
[change log](change-log.md); the page shows the last ones, together with those of what is stored
there and of the locations inside it, to those allowed to see them. Replaced and removed photos remain
in media storage.

## Addresses

A location's page is **`/location/<code>`** (its code, `unique_identifier`: `/location/R303.a`, not the full path
`HH+0.MSL.R303.a`; `Location.get_absolute_url`). Codes stay: a moveable type has building-wide codes (validation of
the location type), so moving a location never changes its code; only changing a short name in the admin does
(also for the compartments below it), or hanging a compartment or part of a room elsewhere in the admin. Former
codes stay blocked for good (`LocationFormerCode`), so a link never leads to another location.

A **short name** has letters, numbers, + and - only (levels: `HH+0`, `HH-1`; `Location.short_name`). No dot: it
separates the short names in the full path (`locatable_identifier`, `HH+0.MSL.R303.a`), which is always the path of
the location above it, a dot and its short name, also where a type has codes of its own (a box `K12` at
`HH+0.MSL.R303.K12`). Lists, counts and the search below a location find what is below it by that path.

* Another spelling of the code (`/location/r303.A`) goes on to the page (301).
* A former code goes on to the location's current code (301) with a notice: the link names the former code,
  a label with it should be printed anew.
* **Earlier addresses** live on under `/loc/` and go on to the new ones: **`/loc/<pk>/<code>`** is in the QR
  code of every label printed before (`views.legacy_location`); it leads to the location by its number, which
  never changes, and gives the notice above if the code in it is not the current one. `/loc/` and
  `/loc/structure/` go to `/location/…`; `/loc/<pk>` without a code leads to the location by its number, too.
* A reserved container's code leads to **Activate container**.
* **Deleted:** status 404 with what is known: an archived location by its title, code and the location it was
  in; one deleted for good (its code kept as a former code without location) with the date; else that there is
  no location with that code (`location_gone.html`).
* The other pages of a location keep its number: `/location/<id>/info/`, `/purpose/`, `/activate/`, …
  (`inventory/urls.py`). No code may equal one of the fixed words beside them (`RESERVED_CODES`).

## Long lists

The location page shows a panel per kind of entry: **At this location …** with
its search field, the overview of its contents and the photo, then quick-items, items, unique items and
sub-locations; the items panel is called **Bulk items** there, as serialized items are listed as their unique
items. The overview lists how many of each the location has ("12 bulk items"), each with the icon of its
kind and linking to its panel; the panel's heading shows the same icon. Each list first shows 10 rows
(`LOCATION_FIRST_ROWS`) and then one more row **Load more** to click, so that a long list does not push the next panels far
down; once clicked, that list loads 50 rows at a time while scrolling towards its end (`location_rows`,
`/location/<id>/rows/<part>/`, as the search's further pages, `results.js`). While searching, the lists load while
scrolling from the start. Quick-items all show at once, as their list is edited in place. Sub-locations are listed as they are arranged
(`structure_overview.physical_order`, as in the [tree](trees.md)): by code, numbers by value, and the compartments of a
storage unit from the top down, the top one first and *a*, the lowest, last. Narrow screens show
*Add overview photo* beside the heading only as its camera, so that the row does not wrap. Last come the changes
(heading and jump button with `clock-history`, [change log](change-log.md)).

**Searching and the locations below.** Above the overview (whose counts follow what it leaves) a field searches the location's lists as you type
(`live_search.js`), with the [search](search.md) of everything, but only within the location: each list shows what
it finds of its kind, the best match first (items without category headings, each with its stock entries there;
the sub-locations found by kind), and emptied, all of them again. Beside the heading **At this location …** a
checkbox **Include all sub-locations** (on narrow screens *with sub-locations*), checked by default: the items and
unique items of all locations below come with those right here, the items still by category; a row at a location
below names it, with its code. Unchecked, only those right here (`?depth=0`, in the address only, so a link keeps it;
the box belongs to the search form, `form=`, and a hidden field before it sends `depth=0` without JavaScript too;
earlier addresses with a number of levels show all below). The sub-locations follow the box, too, in a panel per
kind (spaces, storage units, containers; `LocationLists.sub_locations`): all below it in the order of the tree, each
after its parent, a row below the first level naming where it is; unchecked, those right below it; while searching,
what is found, the best first, still by kind. The overview, the counts and the jump buttons follow (`location_contents.html`, alone with
`?partial=1`; `location_detail.js` puts the quick-items, which only show those right here and not while searching,
back in their place). `LocationLists` (`views.py`) makes all lists, a page at a time, cut in the database: the
locations below by their code path (`Location.in_tree`, `locatable_identifier`). The magnifier in the navbar and
Ctrl+F go to the field, a jump button at the bottom right too ([search](search.md)).

Once scrolled down at all, a column of round buttons at the bottom right leads back
to the top and to each panel, with the icons of the overview, last the changes (`clock-history`, only where the page
shows them; `page_jump_links` in `location_detail.html`); the buttons of the
panels at the top of the page are marked, one per column on wide screens. The top button is on every page
(`base.html`, `page_jump.js`); the map leaves it out. Going to a panel, by
these buttons, the overview or a link with its `#anchor`, jumps there without smooth scrolling, so that the lists
on the way do not load their further rows, and holds the panel in place while rows above it still load, until
the reader scrolls (`location_detail.js`).

The headings of the items, unique items and sub-locations stay at the top while their rows scroll past. Hovering
over a row marks it, as the arrow keys do; the keys go on from the end of one list into the next.

Items, unique items and sub-locations are [result rows](search.md#result-rows), as in the search: an
item with its amount here and the stock button beside it, its description and price below it, and its other
places; a unique item with its usage level and notes; a sub-location with its code chip and its counts as in the
[location tree](trees.md). Their photos open below
the row.

The items are grouped by category, sorted by its path and within it by name, those without one last ("Without
category"); a heading names each category (`search.render.group_by_category`), so the rows do not repeat it. The
headings stay at the top while their rows scroll past (`results.css` `.result-group`, as on a category's page,
there below the search field), below the panel's heading. A further page of rows goes on with the category of
the row before it: a heading only where the category changes. Unique items are not grouped; each names its
category.

## Moving contents and dissolving

**Move contents** and **Dissolve** open the same plan: choose a
destination, deletion or nothing (keep in place) for each stock entry and
sub-location, optionally including all descendants. The plan ends with two
buttons, **Review and keep location** and **Review and delete location**; the one
matching how the page was opened is highlighted, and keeping comes first, so
pressing Enter never deletes. Deleting stays visible but disabled, saying why,
while unique items are still stored at the location or its type or the user's
permissions do not allow it (see [Permissions](permissions.md)). Nothing changes
until the reviewed plan is confirmed.
