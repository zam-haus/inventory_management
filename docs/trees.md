# Item and location trees

The navbar's *Items* and *Locations* lead to two trees to browse; finding something by words is the
[search](search.md) on the home page. In the navbar both carry the icon of their kind ([icons](icons.md)); *Admin*
(staff) and the user menu with *Logout* stand at the right. On narrow screens the two show their icons only, and
a menu at the right end (`three-dots-vertical`) holds their names, *Admin*, the user and *Logout* (`base.html`,
styles in `actions.css`).

* **Items** (`/item/`): the categories as a tree, each with its subcategories first, then its items by name.
  An item tracked as unique items (`box-star-stack`) opens to those still in the inventory (`box-star`), by
  name, each named as everywhere (item, own name, label ID, [unique items](unique-items.md)), and counts them.
  Items without a category come last, under *Without category*. A category's counts include its
  subcategories: counted items (`boxes`), then unique items (`box-star`). Its name leads to
  its page (`/category/<id>/`): all its items, those right in it first, then those of its subcategories by
  subcategory (each by name), 50 a page, shown like search results; above them its path and subcategories.
  Item and unique item pages show the item's category path above the title: *Items* (the tree, opened at
  the category), then each category down to its own, each linked to its page.
* **Locations** (`/loc/`): every location below its parent, in the order of their codes, numbers by value
  (R2 before R10) and levels by number (WH-1 before WH+0); the top level is open. Below a location come its
  building parts and other sub-locations, then its storage units as one group (open, each storage unit
  closed), then its containers as one group (closed). A group only where it sets them apart from other
  sub-locations, so that the tree stays flat: none if they are all of one kind, and none for the storage
  units of a storage unit (its compartments). Each location shows the icon of its kind (building
  part, storage unit, container, [icons](icons.md)), its title and code as everywhere
  ([locations](locations.md)), and counts with icons, in this order: its sub-locations in all by kind
  (building parts and others, storage units, containers), then the items stored right there, counted ones
  and unique items; the words are in the tooltip.
  Reserved containers and deleted locations are left out. *Levels and axes* (`/loc/structure/`) is linked at
  the top.

Both load whole: every node is a `<details>`, so it opens and closes without JavaScript, and the browser's
find (Ctrl+F) opens the nodes it finds something in (Chrome, Edge). `tree.js` adds *Open all* and *Close
all*, and opens the way to a node named in the address: `/loc/#loc-<id>`, `/item/#cat-<id>`. The keyboard:
the first arrow key starts at the first row; the pointer over a row moves the focus there, and the focused
row is marked the same way, so mouse and keys go on from one row; up and down move through the visible rows, right opens a branch, left closes it (on a closed branch or a leaf: the branch
it is in, going there), space opens or closes it, Enter opens the page of the location or category itself.
A location's name leads to its page, its code chip opens it in brief ([locations](locations.md)). *Create New
Item* and *Levels and axes* stand at the right.

An old link with a search (`/item/?q=…`, `/loc/?q=…`) goes to the search with those words.

## How it works

`inventory/trees.py` builds each tree in memory from a fixed number of queries (locations with their item
counts as subqueries; categories and items) and renders it with `format_html`, which escapes, instead of
template recursion, which would be slow for thousands of nodes. The icons are drawn once per page as
`<symbol>`s and each row refers to one (`<use>`), which keeps the pages small. Views: `ItemTreeView`,
`LocationTreeView`, `CategoryView` (`inventory/views.py`); templates `item_tree.html`, `location_tree.html`,
`category_detail.html`; styles
`tree.css`. Tests: `inventory/tests/test_trees.py`.
