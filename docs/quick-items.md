# Quick-items

Quick-items are items known only by name, stored at one location with an
unknown amount. On the location detail page they are listed first in the
**Bulk items** panel, above the regular items, and count as items there and in the
overview at the top. They are edited right in the list:

* Type a name in the empty field at the end of the list and press Enter to add
  it; the cursor stays in a new empty field for the next one.
* Edit a name in place; it is saved when you press Enter or leave the field.
  Emptying a name and leaving the field (or pressing Enter) deletes the item.
* **Add a photo** (camera) takes or chooses a single photo, uploaded right away and shown as a
  thumbnail (it opens in the lightbox); another photo replaces it. More photos
  are added on the item page. Needs `inventory.add_itemimage` as well.
* The cross at the end of the row deletes after five seconds, during which **Undo** takes its place and keeps
  the item. Leaving the page sends pending deletions immediately.
* The row keeps room for a name like "VW Käfer (new beatle) foo bar"; what else stays in it depends on the room
  the list has (`location_quick_items.js`, `data-room`), the rest are entries in the actions menu (three dots):
  1. camera, **Edit details** with its words, menu (converting), cross
  2. camera, pencil, menu (editing, converting), cross
  3. camera, menu (editing, converting), cross
  4. menu (photo, editing, converting), cross
* **Edit details** (pencil) opens the item's form. Entering an amount there turns the quick-item into
  a regular item, which can no longer return to an unknown amount. Without `inventory.change_item` it is
  disabled and says why.
* **Convert into a unique item** (the unique item's icon) makes the quick-item a serialized item
  with one unique item at the location and a label ID, as on a bulk item's page with one piece
  ([unique items](unique-items.md)); cancelling goes back to the location. It is disabled, with the reason,
  while the item has another place, and without the permissions.

Quick-items are found by the regular item search. Managing them requires
`inventory.add_item` and `inventory.add_itemlocation` (granted to the local
group). Deletion is permanent, but only while an item is still a quick-item:
a single photo is deleted with the item, but items with an amount, more than
one photo, files, barcodes or a second location are never deleted from this
list. Without JavaScript, the list still works through plain form submissions
(the photo then needs a click on **Upload**).
