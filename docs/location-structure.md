# Building structure

Locations of the fixed building structure (levels, rooms, areas) carry a few details that
furniture and containers do not: an axis, a fire-load flag, an outdoor flag and responsible
teams. A dataset describes the whole structure; one command moves the database to it, another
draws the levels-and-axes overview. The rules ZAM applies to codes and names are in
[Standortregeln](standortregeln.md) (German).

## Model

* **Admin only** (`LocationType.admin_only`): locations of the type are created, changed and
  deleted only in the admin by staff; on the inventory pages only their purpose can be changed.
  See [Permissions](permissions.md). All building
  structure types use it.
* **Location type → category** (`LocationType.category`): *space* (levels, rooms, areas),
  *storage unit* (furniture for storing things: shelves, cabinets, workbenches with drawers, tool
  trolleys, and their compartments) or *container* (moves with its contents: boxes, cartons,
  pallets); empty for anything else (*Mobil*). Validation fills a missing category from the type
  (building structure → space, number ranges per area → storage unit) and rejects a contradicting
  one. Migration `inventory.0036` makes moveable types containers; the dataset sets the others.
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
  number from a range of the room or area they stand in. Only for types with building-wide codes
  (*unique*) that are not *moveable* (boxes wander through the house), with a short name prefix
  and the numeric sequence.
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
  `add_location`, on levels, rooms and areas only): the location page shows a button named after
  the area-numbered types (“Regal / Schrank”). The page first asks which type, then the number:
  a free *reserved* number of the range that applies (`Location.free_numbers(type)`, the next one
  first); a *wished-for* number that no range of the type covers and no code uses
  (`LocationNumberRange.unavailable`), optionally reserving the following ones for this area; or a
  *new* number, which reserves as many as are to be expected (`LocationNumberRange.reserve`:
  behind a used-up range if free, else `suggest`). Name and code come from the type's automatic
  naming (`Regal 301`, `R301`). A drawing on the page shows the order: neighbours left to right,
  compartments from the bottom up. Only the fields of the chosen way count
  (`NumberedLocationForm.FIELDS_FOR`; `numbered_location.js` hides and disables the others), and
  the wish field shows the type's prefix in front.
* **Sub-locations** (`LocationType.sublocation_type`, e.g. *Fach/Schub* for shelves and
  cabinets): creating such a location asks how many to add inside it and creates them with the
  sub type's naming (`Fach a`, `a`). Its page has a button to add more later
  (`SublocationAddView`, permission `add_location`): they get the next free characters of the
  sequence (`LocationType.free_sublocation_names`); letters run on like spreadsheet columns
  (`z`, `aa`, `ab`), at most 100 at a time. The admin's mass add names sub-locations the same way.
  After adding them, users with `change_location` go on to `SublocationPurposeView`
  (`?codes=a,b`) to give their purposes, listed top down as they sit (`a` at the bottom) next to
  the drawing; skipping it leaves them empty.
* **Sequences** (`LocationType.auto_sequence`) are digits only or letters only. Migration
  `inventory.0036` moved types with a mixed sequence (hexadecimal boxes, alphanumeric pallets) to
  digits; their existing codes stay. Creating several locations in the admin skips codes that are
  taken (`LocationType.free_names`) and accepts only start values from the type's sequence.
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

## Dataset

JSON, for example [`standortstruktur.json`](standortstruktur.json):

```json
{
  "types": {"level": {"name": "Haus+Ebene", "description": "Eine Ebene eines Hauses …",
                      "structure": "level", "unique": true, "moveable": false,
                      "no_sublocations": false, "deletable_in_frontend": false,
                      "label_template": "70x32 static"}},
  "teams": [{"code": "H", "group": "Werkstattgruppe Holz", "color": "#7d3a2d"},
            {"code": "B", "group": "Werkstattgruppe Bio", "parent": "A"}],
  "axes": [{"number": 1, "name": "Treppenhaus 1"}],
  "replaces_types": ["Haus+Etage", "Raum/Bereich"],
  "retire_types": ["Haus+Etage", "Raum/Bereich"],
  "locations": [
    {"path": "WH-1", "type": "level", "name": "Werkhaus -1", "old": "N0",
     "purpose": "Holzwerkstatt", "description": "Halle", "teams": ["H"], "axis": 2},
    {"path": "WH-1.HBB.1", "type": "subarea", "name": "Holzbaubühne unten", "purpose": "CNC-Fräse"}
  ],
  "remove": [{"old": "S2.IWL", "reason": "aufgelöst", "move_to": "HH+1", "permanent": true}]
}
```

* `path` is the full `locatable_identifier`; its last part is the code. Parents come first.
* `was` lists former paths from earlier versions of the dataset: a location found there is renamed
  and moved like an `old` one, so a dataset can evolve after it has been applied. Every active
  location of a structure type of the dataset must appear in it (by path, `old` or `was`) or be
  removed, otherwise nothing happens.
* `moves` puts containers into the structure by code: `{"codes": ["R003", …], "to": "WH+1.GSL"}`.
* `old` names an existing location (by its current `locatable_identifier`). It is renamed,
  retyped and moved in place, so its pk, URLs, history, photo, label IDs and contents stay.
  Entries without `old` are created.
* `name`, `purpose`, `description`, `axis`, `fire_load_free`, `outdoor` and `teams` are
  authoritative: a missing key clears the field. The dry run lists every non-empty purpose or
  description that would be replaced.
* Types are created or updated by name. Their flags `unique`, `moveable`, `no_sublocations`,
  `deletable_in_frontend`, `admin_only` and `area_numbering` are authoritative (missing means false), as are `structure` and
  `description`;
  `label_template` names the default label template.
* Axes and teams are created or updated by number and code; axes missing from the dataset are
  deleted. Teams are created
  together with their group when it does not exist yet.
* `number_ranges` on a location: a list of `{"type": "shelf", "from": 300, "to": 399}`, each for
  one dataset type with `area_numbering`; authoritative like the other fields. A range may lie within
  a range of a location above it.
* Types may name a `sublocation_type` (a dataset type key) and set `auto_name_prefix`, `auto_short_name_prefix`,
  `auto_short_name_padding_length` and `auto_sequence`; without them the type keeps its values.
* `remove` lists old locations without successor, by `old` and, once its parent has moved, by
  `path`. Sub-locations and stock entries inside move to `move_to` the way *Move contents* does on
  the location page; unique items must have been moved before. With `permanent` the location is
  then deleted for good (history included) instead of staying in the trash.
* Every active location of a type in `replaces_types` must be moved, removed or listed in `keep`,
  otherwise nothing happens.
* `retire_types` names old location types to delete at the end. Deleted locations that still use
  them are deleted permanently with their deleted contents; an active one stops the run.

## Commands

```sh
python manage.py building_restructure docs/standortstruktur.json            # plan only
python manage.py building_restructure docs/standortstruktur.json --apply --actor admin
python manage.py building_overview -o overview.html                        # from the database
python manage.py building_overview --dataset docs/standortstruktur.json -o plan.html
```

`building_restructure` prints one line per location (`move`, `create`, `update`, `remove`) and
writes nothing without `--apply`. With `--apply` it runs in one transaction; any error leaves
the database unchanged. Running it again reports everything as already in place.
`--actor` attributes the purpose changes in the location history.

`building_overview` writes a standalone HTML page: levels across, axes down, each level, room
and area with code, purpose (or name), description, team badges and the fire-load mark.
Containers are left out. With `--dataset` it shows the planned state, including the old
identifiers.

Code: `inventory/building_structure.py`; tests: `inventory/tests/test_building_structure.py`.
