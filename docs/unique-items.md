# Unique items

Terms: an **item** (*Sache*) is either a **bulk item** (*Mengenartikel*),
counted per location, or it is tracked as **unique items** (*Einzelobjekte*):
single physical objects such as fire extinguishers, machines, IT hardware,
anything with a power cord, or special and expensive tools. The item holds what
its unique items share (description, photos, files, default usage level); each
unique item has exactly one location and its own [label ID](label-ids.md). An item never has both
stock entries and unique items; its kind can only change while it has neither.

* **Creating:** a new item tracked as unique items is created together with its
  first unique item (location and label ID), just as a bulk item needs its first
  stock entry; the first unique item's page then shows the label to print.
  A unique item always gets its label ID when it is created, either
  a pre-printed label (scan it: the claim page offers *New unique item*, or enter
  it in the form) or a newly generated ID whose label is then shown on the unique
  item's page for printing. If the item does not exist yet, the item search
  offers *Create new item* as its last entry (requires `inventory.add_item`),
  both in the unique item form and on the claim page; the new item is only
  created when the unique item is saved.
  Creating requires `inventory.add_uniqueitem` and
  `inventory.claim_labelid`; migration `inventory.0023` grants `add`/`change` on
  unique items to the local group (photos and files use the item permissions they
  already have). The admin generates an ID when a
  unique item is added without `?label_id=`.
* **Details:** briefing requirement (*Einweisungspflicht*; empty uses the item's):
  green ✓ free to use, no briefing required; yellow ! use with care, ask if in
  doubt; red ✕ use only after a briefing. Lists show the coloured symbol with
  the explanation on hover, detail pages the explanation itself,
  warranty, notes, responsible team and person, owner, purchase date, price and
  source, files. Without an owner a unique item belongs to the ZAM and no
  ownership is shown. The owner is set when the unique item is created; after
  that only admins or users with `inventory.change_uniqueitem_owner` can change
  it (frontend and admin). Teams (**Admin → Accounts → Teams**) are account groups
  marked as teams; since directory group membership is only ever added, a team
  is a public label, not a permission.
* **Visibility:** pages are public. The team and the *first names* of the owner
  and responsible person are public. Full names, e-mail addresses, the owner's
  contact details and purchase prices (of unique items, and the last purchase
  price of items) are shown, and editable, only with
  `inventory.view_internal_details`; without it those fields are not part of the
  forms. The user search used by these fields requires the same permission.
  Pages still show that such information exists: the hidden part is replaced
  by an *internal* chip.
* **Files and photos** belong to an item, either to the item in general (e.g. a
  manual) or to one of its unique items (e.g. that object's invoice). Both forms
  let you choose: the item form offers its unique items per row, the unique item
  form offers "this unique item" or "the item in general", also for existing
  rows. The item page shows the general ones; a unique item's page shows its own
  first, then the general ones marked *general*. One photo per level can be
  primary; it is shown first. New items start with one photo row; *Add another
  photo/file* adds rows before saving.
* **Internal documents:** files are public unless flagged as *internal
  document*. Internal documents need `inventory.view_internal_details`: without
  it, pages list their name without a link, the download answers 403 (or asks to
  log in), and edit forms leave them out. Files are stored as
  `media/documents/<random UUID>/<file name>` and only served through
  `/item/file/<pk>`; `nginx.conf` denies `/media/documents/` so they cannot be
  fetched directly. Formats that could run in the browser (e.g. HTML, SVG) are
  always downloaded. Migration `inventory.0023` moved existing files there.
* **History:** creation, moves, owner changes and removal are logged
  append-only (`UniqueItemEvent`), including who acted; the user is shown only in
  the admin. Owner entries keep the owner before and after: first names are
  public, accounts and contact details internal, like on the unique item. An
  account that owns a unique item cannot be deleted (`PROTECT`); change the owner
  first, so the hand-over is recorded.
* `manage.py label_id_check --missing` lists unique items whose ID was retired and
  that need a replacement label.
* **Item search:** for items tracked as unique items, the locations column lists
  each unique item's label ID and location; searching for a location name or
  identifier also finds them.
* **URLs:** `/item/unique/<pk>` (with `/update` and `/dispose`) and
  `/item/unique/create?item=<pk>&location=<pk>`; new items take `?kind=bulk` or
  `?kind=unique` on `/item/create`.
