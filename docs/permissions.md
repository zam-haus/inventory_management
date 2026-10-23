# Permissions

Frontend lists, details, searches and autocomplete are public. The printable
inventory (`/inventory/print/`, the printer button on location pages and, only after a search, on
the location list, where it preselects the locations found) is internal: it requires
`inventory.print_inventory`, which migration `inventory.0023` grants to the local group.
Printing labels from location and item pages requires `label_printing.print_label`, which
migration `label_printing.0002` grants to the local group (see [Label printing](label-printing.md)).
Editing requires login and Django's `add`, `change` or `delete` permission for the
relevant model. Assign permissions to groups in **Admin → Authentication and
Authorization → Groups**, then assign users to those groups. Superusers retain
full access; being logged in or being staff alone does not grant inventory editing.

For logged-in users, buttons for actions they may not perform stay visible but
disabled, shown only as an outline (usable actions are filled, see
[Icons and action buttons](icons.md#action-buttons)). Hovering, focusing or tapping one says why ("ask an inventory admin"
for a missing permission). Guests do not see actions they lack the permission for; technical reasons (no
JavaScript, no camera) are explained to them like to everyone else. Templates
render these buttons with `{% disabled_action %}`
(`inventory/templatetags/actions.py`), which also takes other reasons, such as a
location type that cannot be moved, and renders nothing for guests.

Item metadata, photos, barcodes and stock entries have separate model permissions.
For example, creating an item at a location requires `add_item` and
`add_itemlocation`. Unique items are covered in [Unique items](unique-items.md), including
`view_internal_details` and `dispose_uniqueitem`. Moving locations requires `change_location`. Moving a
location's contents (all or some of them) requires `change_location` / `change_itemlocation`
for the moved sub-locations and stock entries and `delete_location` / `delete_itemlocation`
for deleted ones; entries kept in place need nothing. Dissolving the location, i.e. also
deleting it once empty, additionally requires `delete_location`. Permissions are checked
again when confirming the plan. Changing the deleted flag in admin also
requires the corresponding delete permission.

On the inventory pages, `delete_location` covers only locations whose location type
is **deletable outside the admin** (`LocationType.deletable_in_frontend`, set in admin);
this applies to staff too. Locations of other types can only be deleted in the admin.
Migration `inventory.0034` allows it for *Regal*, *Fach/Schub*, *Karton*, *Palette* and
*Schrank*; *Kiste*, *Haus+Etage*, *Raum/Bereich* and new types are admin-only. The
delete options stay visible but disabled, saying why
(`inventory.permissions.location_deletion_denied`); the location details list the
property with the other location type properties.

Location types marked **admin only** (`LocationType.admin_only`, used for the building
structure, see [Building structure](location-structure.md)) go further: their locations are
created, changed and deleted only in the admin, which requires staff status, their purpose
included. On the inventory pages the buttons for purpose, physical description and overview photo
stay visible but locked, saying why (`inventory.permissions.location_edit_denied`), and their
endpoints answer 403. Where the purpose or description is empty, its locked button is left out, as
there is nothing to show. Such a type
can be neither moveable nor deletable outside the admin. What these locations contain (shelves,
boxes, stock) can still be moved as before.

Locations of types with *number ranges per area* (shelves, cabinets) are created on the location
page of the room or area they stand in, or of a pallet there, which requires `add_location`. So are
boxes, cartons and pallets, on any location that takes sub-locations; they get the next number of
their type. Only the free numbers of
the number range that applies there are offered. The first one of a type in an area reserves the
numbers for it, so `add_location` also lets members reserve numbers that way; changing ranges
otherwise is for admins. See [Building structure](location-structure.md).

Of a location's own details, the inventory pages change the purpose, the physical description and the
overview photo (`change_location`, each in its own dialog), except for admin-only types (the building
structure); changes of all three are recorded in the location history. Name and short name are
changed in the admin. Short names stay fixed: a changed one is kept as a **former code**
(`LocationFormerCode`), which only admins add or remove; the local group gets no permissions for
them.

Migration `accounts.0002_zam_local_group` creates the reserved **local group**
(`LOCAL_GROUP_NAME`, by default `ZAM-local`) with add and change permissions for
inventory models, but no delete permissions. Its permissions can subsequently be
adjusted in admin. A logged-in user joins this group after detection on the local
network (`imzam/local_network.py`) or when carrying a pending local visit in the
session; that flag is then consumed. Anonymous local visits can be remembered through
the login redirect, but do not permit anonymous editing. Membership belongs to the
user and persists across logins and network changes. SSO claims cannot assign this
reserved group, and SSO updates never remove it. The indicator next to the user name,
`(LOCAL_NETWORK_NAME)` (by default `(ZAM)`), reads group membership rather than
session state.

Local detection matches the client IP against all DNS A records of `das.zam.haus`
by default. Configure `LOCAL_NETWORK_SOURCES` as a list in local settings, for example:

```python
LOCAL_NETWORK_SOURCES = ["das.zam.haus", "another.example.org", "192.0.2.5", "198.51.100.0/24", "2001:db8::/32"]
```

Alternatively, set the `LOCAL_NETWORK_SOURCES` environment variable to a comma-separated
list (the former name `ZAM_LOCAL_SOURCES` still works). Literal addresses and CIDR
ranges support IPv4 and IPv6; hostname lookups use IPv4 A records. An empty list
disables new network-based grants. DNS results are cached per worker for
`LOCAL_NETWORK_DNS_CACHE_SECONDS` (default: 60 seconds; 0 disables caching; formerly
`ZAM_LOCAL_DNS_CACHE_SECONDS`). Failed lookups do not match clients or retain expired
addresses; other configured sources still work. Every request is checked, also for
existing members, because label ID accesses record whether they came from the local
network.
