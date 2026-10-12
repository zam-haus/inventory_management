# Concepts

* Items are either bulk items, counted per location, or tracked as unique items,
  single objects with their own ZAM ID (see [Unique items](unique-items.md))
* Bulk items can be at multiple locations
* Item images are the main source of truth during data collection
* Stock changes are logged (see [Stock changes](stock-changes.md))
* Item descriptions and notes of unique items support Markdown (links, lists, emphasis);
  raw HTML is removed
* Locations are hierarchically structured (tree)
* Label printing relies on Zebra ZPL compatible printers

## Initial data collection

1. Define and label all (storage) locations
2. Scan location QR-code and add items to location, by:
3. Take pictures and count of items in storage locations
   using `/item/create` (i.e., `create_item`, `inventory.views.CreateItemView`) view
4. Annotate items with name, description, category and other metadata.
