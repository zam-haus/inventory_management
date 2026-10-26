# Stock changes

The cart button beside each amount (on the item page, one per location) and to
the right of the photos in a location's item list opens a dialog for one item at
one location. First choose **Remove stock** (red, arrow down) or **Add stock**
(green, arrow up), then enter the counted amount, a reason and an optional note. The
dialog shows the sale value of the changed amount as you type, or says it is
unknown; it is marked as an estimate when based on an estimated amount.

A bulk item's page also has **Take out** and **Add stock** first among its actions, without a
location: they open the dialog removing or adding, for the location from the label (`?loc=`), else
the first one. For an item at several locations the dialog offers them in a choice instead of naming
one; another location brings its stock, keeping direction and amount (`take_choices`, `stock_change.js`).

* Reasons for removing: sale, ZAM's own use, recount (lost or correction),
  destruction, other. Reasons for adding: purchase, donation, recount (found or
  unknown origin).
* Precise amounts are reduced or increased. Estimates change by the counted
  amount and remain estimates; a removal that would leave nothing (without
  **Remove everything**) leaves "few". "Few", "many" and unknown amounts stay
  unchanged; only the change is logged.
* **Remove everything stored at this location** prefills the stored amount
  (or the estimate, which can be replaced by a counted amount) and removes the
  item from the location, also when the amount is only an estimate. If no stock
  of the item is left anywhere, the item is deleted. You stay on the location
  page; from the item's own page, you are taken to the [items](trees.md).
* After saving, the page reloads in place. Each dialog submission carries an ID,
  so a retry after a lost connection is applied only once.

Every change of stock is logged in the [change log](change-log.md) ("Stock changed"): the user
account, date, direction, reason, note, amounts before and after, changed amount, unit price and
sale value. Changes made elsewhere are logged as well: amounts edited in the item form or admin as a
recount (increases as "found") and stock deleted while dissolving a location as "other". New stock
entries are logged as stored there, moves of stock between locations as moves. Quick-items are not
stock yet: they have no cart button and are only deleted from their list or given an (estimated)
amount, which turns them into regular items; both are logged without a reason or sale value. The item
and location pages show the last changes to those allowed to see them; the admin (**Change log**,
filtered by action "Stock changed" or reason) shows all, with the sale value. Using the dialog
requires `inventory.change_stock`, which migration `inventory.0046_change_log` grants to the local
group (and to everyone who had the former `add_stockchange`).
