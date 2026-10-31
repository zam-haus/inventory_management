# Icons and action buttons

The interface uses [Bootstrap Icons](https://icons.getbootstrap.com) (MIT, version
1.11.3) instead of emojis, which look different on every device and are easy to
confuse (the old outbox and inbox trays for moving contents out and in). Only the
icons in use are vendored, in
`inventory/static/inventory/vendor/bootstrap-icons/icons/`; `{% icon "camera" %}`
(`{% load icons %}`, `inventory/icons.py`) inlines one, sized like the text and
hidden from screen readers, so the button keeps its own label (`aria-label` or
text). Scripts get icons from `templates/script_templates.html` (included in
`base.html`) through `window.appIcon(name)` (`actions.js`); add a `<template>`
there for each icon a script needs. To add an icon, copy its SVG from the
Bootstrap Icons site into that folder; unknown names raise an error (see
`inventory/tests/test_icons.py`).

Three icons are our own, drawn in the style of Bootstrap Icons and kept in the same folder: `box-star`
(Bootstrap's `box` with a star on its side: one single, individually tracked object, next to the
`boxes` of counted items), `box-star-stack` (a smaller `box-star` with a plain box behind it: an item tracked
as unique items, several of them; the back box is drawn as lines that stop short of the front one, so the icon
needs no mask and no `id`) and `eurobox-open` (a Euro container with its lid open, on a 64 grid, its
lines thickened to match the others at 16 px).

Agreed meaning of each icon, so the same action always looks the same. *Reserved*
icons are agreed but not shown yet (those places have text buttons); vendor them
when they are first used:

| Use | Icon | Status |
|---|---|---|
| Take or replace a photo | `camera` | done |
| Scan a QR code | `qr-code-scan` | done |
| Scan a barcode (EAN) | `upc-scan` | done |
| Move contents out of a location | `box-arrow-up` | done |
| Move locations into a location | `box-arrow-in-down` | done |
| Dissolve or delete a location, deleted flag in the admin | `trash3` | done |
| Remove a unique item from the inventory | `archive` | done |
| Sort ascending / descending | `sort-down` / `sort-up` | done |
| Change stock | `cart` | done |
| More / less stock | `arrow-up` / `arrow-down` | done |
| Info or help tooltip | `info-circle` | done |
| Help page (menu entry, “More about this” links) | `question-circle` | done |
| Admin only (location type facts on the help page) | `shield-exclamation` | done |
| Report a problem (menu entry) | `bug` | done |
| Yes / no (location type facts on the help page) | `check-lg` / `x-lg` | done |
| Print (labels; a label's printer mark in the print dialog) | `printer` | done |
| Levels-and-axes overview of the building | `grid-3x3` | done |
| Search | `search` | done |
| Item (counted, *Sache*) | `boxes` | done |
| Item tracked as unique items (*Sache mit Einzelobjekten*) | `box-star-stack` (own) | done |
| Unique item (*Einzelobjekt*) | `box-star` (own) | done |
| Category (item tree, search results) | `folder` | done |
| Location: building part (level, room, area) and others | `geo-alt` | done |
| Location: storage unit (*Lagermöbel*: shelf, cabinet, …) | `bookshelf` | done |
| Location: container (*Behälter*: Euro box, carton, …) | `eurobox-open` (own) | done |
| Edit (item, unique item, purpose) | `pencil` | done |
| Add | `plus-lg` | done |
| Move a location or unique item | `arrows-move` | done |
| Delete an entry (quick-item) | `x-lg` | done |
| Open details, next entry | `chevron-right` | done |
| Previous photo | `chevron-left` | done |
| Actions menu | `three-dots-vertical` | done |
| Rotate photo | `arrow-clockwise` | done |
| Crop photo | `crop` | reserved |
| Primary photo | `star-fill` | done |
| From → to | `arrow-right` | done |
| Warning, invalid | `exclamation-triangle` | done |
| Briefing green / yellow / red | `check-lg` / `exclamation-lg` / `x-lg` | done |
| Label ID, QR code | `qr-code` | reserved |
| History | `clock-history` | reserved |

The kind icons (item, item tracked as unique items, unique item, category, the three location kinds) also stand before the title of a location,
item or unique item page, before the names in the search results and trees, and before *Items* (`boxes`) and
*Locations* (`geo-alt`) in the navbar; up to 767px wide the navbar shows those two (and *Map*, *Help*) as icons
only, with their names as tooltips; on narrow screens their names are also in its menu (`three-dots-vertical`).

Every change of where something is, a location, a unique item, stock or the contents of a location, is
called **Move** (German **Bewegen**: „Bewegen“, „Hierher bewegen“, „Inhalt bewegen“), never „verschieben“ or
„verlegen“.

## Action buttons

Colours say what a button does. They follow Bootstrap's semantic button variants
(the framework this app uses) rather than a scheme of our own; general design
systems such as Material, Apple's guidelines or GOV.UK use one accent colour plus
red for destructive actions and do not distinguish creating from changing.

| Colour | Bootstrap class | Meaning | Examples |
|---|---|---|---|
| Green | `btn-success` | creates something | add item, photo or file (+), the first overview photo, *Create New Item*, *Save* on a new item, *Add photo* |
| Yellow | `btn-warning` | changes something | edit, move, *Move contents*, purpose, replacing the overview photo, stock (cart), *Save* on an existing item |
| Red | `btn-danger` | destroys or removes | dissolve, remove from inventory, delete a quick-item |
| Blue | `btn-info` | shows or finds | print, *Location details*, quick-item details, search, *Scan QR code* on the home page |
| Grey | `btn-secondary` | neutral | cancel, back, actions menu, undo, scanning into a field, photo tools |

The stock dialog colours its direction instead: red removes, green adds stock. The QR
scanner beside the logo is a grey (neutral) button with a white icon, as tall as the logo.
Usable buttons are **filled**; unavailable ones show **only the outline** (and say
why, see [Permissions](permissions.md)). Templates give buttons the filled classes,
also for `{% disabled_action %}`; `actions.css` draws any disabled filled button as
its outline, so buttons that scripts enable later turn filled by themselves. Of two
equal choices, the suggested one gets a ring (`action-suggested`, e.g. keeping or
deleting on the dissolve page).

An icon gets a short text where it alone is not clear in its place: move, print, move
here, move contents, dissolve, edit and purpose (pencil), overview photo (camera beside
*At this location …*), remove from inventory (archive) and quick-item details
(chevron). Icons stay alone where the place says it all: +
beside a list heading, the camera beside *Overview photo* and in quick-item rows,
× to delete a quick-item, the cart for stock changes, arrows in the photo viewer, sorting, help (i) and the
actions menu. `{% disabled_action icon label=_("…") %}` adds the text to unavailable
buttons; the tooltip can keep the longer name.

Where actions share a row with a title (`data-action-row` on the row,
`data-action-group` on the buttons; the title comes first), they stand right-aligned beside the
title. When they do not fit there on one line, on narrow screens or with a long title, an
**actions menu** (three dots) at the right end takes them in this order, until the rest fits:
first the **unavailable** ones, one by one from the right; then the usable ones show their **icon
only** (all at once, so the row stays alike) and are listed in the menu as well; last the usable
ones **move** into the menu, from the right. With none left, the menu alone stays beside the
title. **Important actions** (`data-action-primary`) never move while usable: at most they show
their icon only. They are taking stock out on a bulk item's page, moving a container,
"move here" on a storage unit (shelf, cabinet) and moving a unique item. The menu lists the moved
actions with their icon and name; unavailable ones are greyed out with their reason. Its entries
click the hidden original buttons, so dialogs and scripts work as before. Without JavaScript the
buttons wrap below the title. Used on the location, item and unique item pages; quick-items have their own
menu (see [Quick-items](quick-items.md)).
