# Concepts

* Items are either bulk items, counted per location, or tracked as unique items,
  single objects with their own label ID (see [Unique items](unique-items.md))
* Bulk items can be at multiple locations
* Item images are the main source of truth during data collection
* Every change is logged (see [Change log](change-log.md)), stock changes with their reason (see [Stock changes](stock-changes.md))
* Item descriptions and notes of unique items support Markdown (links, lists, emphasis);
  raw HTML is removed
* Locations are hierarchically structured (tree)
* Labels are printed on Zebra (ZPL) and Brother P-touch printers, on the network or by USB
  through a print agent (see [Label printing](label-printing.md))

## Initial data collection

1. Define and label all (storage) locations
2. Scan location QR-code and add items to location, by:
3. Take pictures and count of items in storage locations
   using `/item/create` (i.e., `create_item`, `inventory.views.CreateItemView`) view
4. Annotate items with name, description, category and other metadata.
