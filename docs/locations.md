# Location purpose and overview photo

Each location can have a **purpose** (one line, up to 50 characters) and one
overview photo. The purpose says what the location is for. Physical descriptions are kept separately.
The purpose is included in location searches.

## How locations are shown

A UX rule for every page, list and dialog (`inventory/location_display.py`, `{% load locations %}`):

* **What people call it comes first:** its purpose, else its name (`Location.title`). Next to a
  purpose the name follows, smaller and grey (`Location.subtitle`): "Schrauben M4 *Regal 301 Fach a*".
* **The code comes after it** (short name, unique or locatable identifier, whichever the place
  shows), **always alike:** white monospace on a muted grey chip (class `loc-code`,
  `inventory/static/inventory/locations.css`). Template tags: `{% location_label location %}`
  (title, name, code; `code="…"` for another code or `""` for none, `subtitle=False` without the name),
  `{% location_code code %}`.
* **Plain text** (page titles, messages, tooltips, select options) reads "Schrauben M4 · WH-1.R301.a"
  (`Location.title_with_code`).
* Location fields (`widgets.LocationSelect`) show their suggestions the same way, with the parent
  below; their autocompletes give HTML only to them (`?html=1`), the admin's fields get the path as
  text. The breadcrumb shows the path with each location's title and short name.

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
it a grey box, like the item page's, holds the physical description, the responsible teams (its
own, else those of the location above it) and, where it applies, **Free of fire load** (marked red,
with the location it comes from); its (i) at the top right opens **Location details**: the location
path, where the responsible teams come from (own, taken over from the location it is in,
`Location.responsible_teams_source`, or none; rooms, areas and levels with their own code never take
them over), the type, former codes, physical description, and the type's rules for moving, sub-locations, and unique identifiers. Its columns stack
on small screens.

Editing requires `inventory.change_location`; purpose and photo are public.
The history page requires `inventory.view_locationhistory`, because it shows who
made each change. Its link is currently hidden on the detail page. History
records the changed fields, their previous and new values, the time, and the
user responsible, including changes through the admin.
Replaced and removed photos remain in media storage so historical entries can
still display them. The history format supports additional event types in future.

## Long lists

The location page shows a panel per kind of entry: **At this location …** with
the overview of its contents and the photo, then quick-items, items, unique items and
sub-locations. The overview lists how many of each the location has ("12 items"),
each as a chip linking to its panel. Lists with
more than 10 entries show only the first 5 at first. Clicking the section heading
(marked with a triangle) or **Show all** below the list shows all entries;
clicking the heading again collapses it. This works without JavaScript
(`inventory/static/inventory/list_collapse.css`). Where the browser supports
`hidden="until-found"`, `list_collapse.js` hides the entries that way instead:
find-in-page (and links to a text fragment) then also finds collapsed entries,
and revealing one expands the list. Quick-items are never collapsed, because
their list is edited in place.

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
