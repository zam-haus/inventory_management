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
| Print inventory | `printer` | done |
| Search | `search` | done |
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

The stock dialog colours its direction instead: red removes, green adds stock.
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
`data-action-group` on the buttons; the title comes first), `actions.js` moves
them into an **actions menu** (three dots) beside the title as soon as they would
not fit beside the title on one line, on narrow screens or with a long title. The
menu lists each action with its icon and name; unavailable ones are greyed out
with their reason. Its entries click the hidden original buttons, so dialogs and
scripts work as before. Without JavaScript the buttons wrap below the title. Used
on the location, item and unique item pages; quick-items have their own menu (see
[Quick-items](quick-items.md)).
