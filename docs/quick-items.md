# Quick-items

Quick-items are items known only by name, stored at one location with an
unknown amount. They have their own panel on the location detail page, above
the regular items, and are edited right there:

* Type a name in the empty field at the end of the list and press Enter to add
  it; the cursor stays in a new empty field for the next one.
* Edit a name in place; it is saved when you press Enter or leave the field.
  Emptying a name and leaving the field (or pressing Enter) deletes the item.
* **×** deletes after five seconds, during which **Undo** keeps the item.
  Leaving the page sends pending deletions immediately.
* **i** opens the item page. Entering an amount there turns the quick-item into
  a regular item, which can no longer return to an unknown amount.

Quick-items are found by the regular item search. Managing them requires
`inventory.add_item` and `inventory.add_itemlocation` (granted to the local
group). Deletion is permanent, but only while an item is still a quick-item:
items with an amount, photos, files, barcodes or a second location are never
deleted from this list. Without JavaScript, the list still works through plain
form submissions.
