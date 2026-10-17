# Quick-items

Quick-items are items known only by name, stored at one location with an
unknown amount. On the location detail page they are listed first in the
**Items** panel, above the regular items, and count as items there and in the
overview at the top. They are edited right in the list:

* Type a name in the empty field at the end of the list and press Enter to add
  it; the cursor stays in a new empty field for the next one.
* Edit a name in place; it is saved when you press Enter or leave the field.
  Emptying a name and leaving the field (or pressing Enter) deletes the item.
* **📷** takes or chooses a single photo, uploaded right away and shown as a
  thumbnail (it opens in the lightbox); another photo replaces it. More photos
  are added on the item page. Needs `inventory.add_itemimage` as well.
* **×** deletes after five seconds, during which **Undo** keeps the item.
  Leaving the page sends pending deletions immediately.
* On narrow screens, 📷, **i** and **×** are entries in the **⋯** menu of each row;
  **Undo** still appears in the row.
* **i** opens the item page. Entering an amount there turns the quick-item into
  a regular item, which can no longer return to an unknown amount.

Quick-items are found by the regular item search. Managing them requires
`inventory.add_item` and `inventory.add_itemlocation` (granted to the local
group). Deletion is permanent, but only while an item is still a quick-item:
a single photo is deleted with the item, but items with an amount, more than
one photo, files, barcodes or a second location are never deleted from this
list. Without JavaScript, the list still works through plain form submissions
(the photo then needs a click on **Upload**).
