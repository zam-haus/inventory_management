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

* **What people call it comes first:** its purpose, else its name (`Location.title`). Next to a
  purpose the name follows, smaller and grey (`Location.subtitle`): "Schrauben M4 *Regal 301 Fach a*".
* **The code comes after it** (the code, `unique_identifier`; a part's own short name where it stands
  under its parent, e.g. in breadcrumbs), **always alike:** white monospace on a muted grey chip (class `loc-code`,
  `inventory/static/inventory/locations.css`). Template tags: `{% location_label location %}`
  (title, name, code; `code="…"` for another code or `""` for none, `subtitle=False` without the name),
  `{% location_code code %}`.
* **Plain text** (page titles, messages, tooltips, select options) reads "Schrauben M4 · WH-1.R301.a"
  (`Location.title_with_code`).
* Location fields (`widgets.LocationSelect`) show their suggestions the same way, with the parent
  below; their autocompletes give HTML only to them (`?html=1`), the admin's fields get the path as
  text. The breadcrumb shows the path with each location's title and short name.
* **In brief:** a location's code chip opens it in a window (`location_info.js`, `/location/<id>/info/`; click,
  Enter or space): the path with the titles and short names of the locations above it, its title and code,
  overview photo and description, and *Open location*. Its name still leads to its page. Closing the window
  returns the focus to the chip. Chips in the suggestions of location fields only show the code, as a click
  there chooses the location (`label_html(info=False)`).

Label templates follow the rule too: `{{ location.title }}` first, the code after or below it inverted in
monospace ([label designs](label-designs.md)). The stored path (`descriptive_identifier`, "Halle [HAL] Regal 301
[R301] …") and the admin keep the plain names; the path appears in the breadcrumb, and as text in the
**Location details**.

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
the overview of its contents and the photo, then quick-items, items, unique items and
sub-locations; the items panel is called **Bulk items** there, as serialized items are listed as their unique
items. The overview lists how many of each the location has ("12 bulk items"), each with the icon of its
kind and linking to its panel; the panel's heading shows the same icon. Lists come 50 rows at a time: the next
rows load while scrolling towards the end of the list (`location_rows`, `/location/<id>/rows/<part>/`, as the
search's further pages, `results.js`). Quick-items all show at once, as their list is edited in place.

Once scrolled down at all, a column of round buttons at the bottom right leads back
to the top and to each panel, with the icons of the overview (`page_jump_links` in `location_detail.html`); the buttons of the
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
