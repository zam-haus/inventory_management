# Building structure

Locations of the fixed building structure (levels, rooms, areas) carry a few details that
furniture and containers do not: an axis, a fire-load flag, an outdoor flag and responsible
teams. The page *Levels and axes* shows them all at once. The rules ZAM applies to codes and names
are in [Standortregeln](standortregeln.md) (German).

## Model

* **Admin only** (`LocationType.admin_only`): locations of the type are created, changed and
  deleted only in the admin by staff, purpose and description included; on the inventory pages they
  are locked.
  See [Permissions](permissions.md). All building
  structure types use it.
* **Location type → category** (`LocationType.category`): *space* (levels, rooms, areas),
  *storage unit* (furniture for storing things: shelves, cabinets, workbenches with drawers, tool
  trolleys, and their compartments) or *container* (moves with its contents: boxes, cartons,
  pallets); empty for anything else (*Mobil*). Validation fills a missing category from the type
  (building structure → space, number ranges per area → storage unit) and rejects a contradicting
  one. Migration `inventory.0037` made the then moveable types containers; since `inventory.0039` shelves
  and cabinets are moveable, too, so *moveable* no longer tells containers apart.
  The location page lists
  sub-locations in one panel per category (`LocationType.group_by_category`), below the
  full-width “At this location” panel with the items on the left; a page whose sub-locations
  have no category keeps the single panel. Where storage units are numbered, their panel shows
  while empty for logged-in users; its **+** adds one, the containers' panel opens *Move here*.
* **Location type → building structure** (`LocationType.structure`): `level` (building and
  level), `room` or `area`; empty for shelves, boxes and other containers. Together with the
  type's *unique* flag it decides the kind of code: unique types have a building-wide code
  (`TGA3`); non-unique ones are numbered parts of their parent (`SK.2`).
  `LocationType.is_coded_structure` is true for the former.
* **Axis** (`LocationAxis`, *number* and *name*): a vertical column of the site, ordered left to
  right. Set `Location.axis` on locations directly below a level; their parts inherit it
  (`Location.effective_axis`). On a level, the axis says where its main area is drawn.
  Axes are maintained by admins: the local group gets no permissions for them.
* **Free of fire load** (`Location.fire_load_free`): no combustible materials may be stored
  there. It applies to everything inside (`Location.is_fire_load_free`).
* **Outdoors** (`Location.outdoor`): courtyards, roofs, outside stairs.
* **Responsible teams** (`Location.responsible_teams`, one or more `accounts.Team`).
* **Number ranges per area** (`LocationType.area_numbering`): locations of the type get their
  number from a range of the room or area they stand in (`Location.numbering_area()`, also for one
  on a pallet there). Only for storage units with building-wide codes (*unique*), a short name
  prefix and the numeric sequence. They are moveable (migration `inventory.0039`) and keep their
  number when they move, but only into a level, room or area or onto a pallet, never to the top level
  (`LocationType.holds_storage_units`, checked in `Location.clean` and offered by the move
  dialog's search).
* **Number ranges** (`LocationNumberRange`: *from*, *to* and the one *location type* it is for,
  edited inline on the location in the admin). Ranges are hierarchical: a range applies to
  everything below its location (`Location.number_range_source(type)`), and a location below may
  reserve a part of it with a range of its own, which its neighbours then no longer get
  (`Location.free_numbers(type)`). Ranges of one type never overlap otherwise; ranges of
  different types may (`R300` and `S300` both in the wood workshop). A new range in the admin
  starts as `LocationNumberRange.suggest(type, location)`: 20 numbers in the middle of the largest
  free gap, rounded to tens, within the range above if there is one, counting numbers used outside
  of ranges as taken.
* **Creating numbered locations** (`inventory/numbered_location_views.py`, permission
  `add_location`, on levels, rooms and areas and on pallets in them, `Location.numbering_types()`;
  ranges are always reserved for the numbering area, never for the pallet): the location page shows
  a button named after
  the area-numbered types (“Regal / Schrank”). The page first asks which type, then the number:
  a free *reserved* number of the range that applies (`Location.free_numbers(type)`, the next one
  first); a *wished-for* number that no range of the type covers and no code uses
  (`LocationNumberRange.unavailable`), optionally reserving the following ones for this area; or a
  *new* number, which reserves as many as are to be expected (`LocationNumberRange.reserve`:
  behind a used-up range if free, else `suggest`). Name and code come from the type's automatic
  naming (`Regal 301`, `R301`). A drawing on the page shows the order: neighbours left to right,
  compartments from the bottom up, the top of the shelf or cabinet as the last one (if things are put
  on it; the count fields say so too). Only the fields of the chosen way count
  (`NumberedLocationForm.FIELDS_FOR`; `numbered_location.js` hides and disables the others), and
  the wish field shows the type's prefix in front.
* **Creating containers** (`ContainerCreateView` in `inventory/numbered_location_views.py`, permission
  `add_location`, on every location that takes sub-locations, `Location.container_types()`): boxes,
  cartons and pallets (`LocationType.numbered_containers`: containers with building-wide codes, a
  short name prefix and the numeric sequence, not admin-only) get the next number of their type, after
  the highest one (`LocationType.next_free_number`, counting former codes, skipping taken codes;
  codes of other sequences such as `K034c` do not count). There is no number to choose. Up to 50 are
  created at once (`MAX_CONTAINERS`), all or none, each with the next free number and the same
  purpose and description. The location
  page shows a button named after the types (“Karton / Kiste / Palette”) and a **+** at the containers'
  panel, which then shows while empty for logged-in users. Creating them and numbered locations also
  asks for the purpose and the physical description. The physical description of everything but the
  building structure can be changed later on the location page like the purpose
  (`LocationDescriptionUpdateView`, `location_field_editor.js`).
* **Breadcrumbs** of location pages (the location and its sub-pages: move, history, dissolve, adding
  shelves, containers or compartments) show the location's full path from its top-level location,
  without a “Locations” root (`inventory/location_breadcrumb.html`). Item pages have none for now:
  theirs would follow the categories. A unique item's heading links to its item.
* **Sub-locations** (`LocationType.sublocation_type`, e.g. *Fach/Schub* for shelves and
  cabinets): creating such a location asks how many to add inside it and creates them with the
  sub type's naming, with the shelf's or cabinet's name first (`Regal 301 Fach a`, `a`;
  `LocationType.sublocation_name`, “Fach a” if that would be too long). Renaming the shelf renames
  the compartments that still have their default name; migration `inventory.0040` gave existing
  ones with the old default name (“Fach a”) the new one. Its page has a button to add more later
  (`SublocationAddView`, permission `add_location`): they get the next free characters of the
  sequence (`LocationType.free_sublocation_names`, skipping former codes); letters run on like
  spreadsheet columns
  (`z`, `aa`, `ab`), at most 100 at a time. The admin's mass add names sub-locations the same way.
  After adding them, users with `change_location` go on to `SublocationPurposeView`
  (`?codes=a,b`) to give their purposes, listed top down as they sit (`a` at the bottom) next to
  the drawing; skipping it leaves them empty.
* **Sequences** (`LocationType.auto_sequence`) are digits only or letters only. Migration
  `inventory.0037` moved types with a mixed sequence (hexadecimal boxes, alphanumeric pallets) to
  digits; their existing codes stay. Creating several locations in the admin skips codes that are
  taken (`LocationType.free_names`) and accepts only start values from the type's sequence.
* **Former codes** (`LocationFormerCode`: *code*, *location*, *note*). Codes are meant to stay, so
  that labels and links can name a location by its code for good. Only the admin changes a short
  name. When a location's `unique_identifier` changes (a new short name, or a new parent of a part
  such as `R301.a`), `Location.save` keeps the old code of the location and of every part that
  includes it; deleting a location for good keeps its code without a location. Former codes are
  never given again (`taken_location_codes`, `Location.clean`, free numbers and letters) and still
  find their location (`location_lookup`, location search, the location details list them); a
  location that gets one of its own former codes back uses it again. Admins edit them inline on
  the location and in their own list (filter: without location); removing one frees the code. The
  local group gets no permissions for them.
* **Capital and small letters:** codes are found ignoring case (labels hold them in capitals), so
  codes and former codes must differ in more than that: `R301.A` always leads to `R301.a`.
  `Location.clean` refuses a short name whose code (or a code of the parts that change with it)
  differs from another location's code or a former code only in case, and so do sibling and
  unique-type short names; unique indexes on the uppercase codes (`inventory.0044`) make sure in
  the database. Changing only the case of a code keeps no former code. Migration `0044` stops with
  a list if codes differ only in case; rename them first.
* **Team** got a *code* (shown as a badge, never resolved as an ID; unique when set; any
  characters but spaces, e.g. `⌂`), a *colour*
  (`#rrggbb`) and a *parent team*. `Team.badge_color` falls back to the parent's colour,
  `Team.badge_text_color` picks black or white by WCAG contrast.

### Inheritance

Purpose and responsible teams are inherited by containers and numbered parts, but not by
another room, area or level with its own code: a shelf in the wood workshop's hall
(`WH-1`) is the wood workshop's, the WC on the same level is not.

* `Location.effective_responsible_teams`
* `Location.purpose_context`: the purpose to show with the location (its own or the inherited
  one), meant for labels and short forms.

Axis and fire load are inherited without that stop. Nothing in the inventory pages uses these
properties yet; the admin shows and filters the new fields.

## Overview

*Levels and axes* (`/loc/structure/`, `StructureOverviewView`, linked from the location list,
public like the other location pages) draws the structure from the database: levels across, axes
down, grouped by house. Each level, room and area shows its purpose (or name), then its code
(linked to its page), description, team badges and the fire-load mark; rooms, areas and outdoor
places are told apart by their frame. Numbered parts are listed with their code relative to their
room (`.1`). A level's main area is drawn in its axis. Containers are left out. The table scrolls
sideways, the level column stays in view.

**Printing** (the **Print** button, or the browser's): landscape pages with the whole table, its
columns as wide as their contents need, a smaller font, colours kept, the axes repeated on every
page; navigation and buttons are left out (`@media print` in `structure_overview.css`). A3 fits
the building on two pages, A4 on about four.

Code: `inventory/structure_overview.py`, `inventory/templates/inventory/structure_overview.html`,
`inventory/static/inventory/structure_overview.css` and `.js`;
tests: `inventory/tests/test_building_structure.py`.
