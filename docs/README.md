# Documentation

How the ZAM inventory works, feature by feature. Setup is covered in the
[project README](../README.md), running the production server in [ops/README.md](../ops/README.md).

* [Concepts](concepts.md): bulk items vs. unique items, locations, initial data collection
* [Location purpose and photo](locations.md): purpose shown with the name, overview photo and change history
* [Building structure](location-structure.md): levels, rooms and areas, axes, fire load, responsible teams, categories, number ranges; overview command
* [Standortregeln](standortregeln.md) (deutsch): wie das ZAM Häuser, Ebenen, Räume und Bereiche codiert und benennt
* [Quick-items](quick-items.md): items known only by name, edited in the location list
* [Stock changes](stock-changes.md): the stock change (cart) dialog and the stock change log
* [Unique items](unique-items.md): single objects (*Einzelobjekte*) with their own label ID, owner and history
* [Label IDs](label-ids.md): permanent IDs on labels (shown as *ZAMid*), resolver, lifecycle and label PNGs
* [Camera scanning](camera-scanning.md): QR and barcode scanning in the browser
* [Permissions](permissions.md): model permissions, the local group and network detection
* [Label printing](label-printing.md): printers, label media, the print queue, print agent and simulator;
  a Raspberry Pi as print agent: [ops/raspberry-pi/](../ops/raspberry-pi/README.md)
* [Installable app](installable-app.md): manifest, offline page and its service worker
* [Logo and icons](branding/README.md): source design and how the served icons are derived
* [Icons and action buttons](icons.md): Bootstrap Icons instead of emojis, the agreed meaning of each icon, filled vs. outlined actions and the actions menu
* [Data export](data-export.md): a copy of the inventory without personal data for development databases
