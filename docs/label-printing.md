# Label printing

Labels for locations and items are printed from the inventory pages on Zebra (ZPL) and
Brother P-touch printers. Printers are reached on the network (raw TCP, port 9100) or, when
connected by USB, through a **print agent** on a computer next to them. Every job is logged with
what the printer reported: printed, failed (and why) or sent without confirmation.

Every label is drawn by the server as an image, dot for dot at the printer's resolution, from a
**label template** written in a small language ([label designs](label-designs.md)). Labels are for
locations, bulk items and unique items (ZAMid); there are templates for each of them on every label
size in use (see [label templates](#label-templates-and-images)).

A Zebra gets the image as `^GFA` in ZPL, with the label material's darkness and speed and the printer's offset; a
Brother gets P-touch raster data. The code is in the app `label_printing`.

## Printing

* **Location pages:** the **Label** button in the header opens the print dialog. It offers
  labels, not printers: the active label templates meant for the location, each on its size of labels,
  e.g. "Lagermöbel" on 70 × 32 mm labels or "Ort" on 12 mm tape.
  Templates whose QR code would be too small to scan at a printer's resolution are not offered on it
  (9 mm tape on the E550W).
  * Which templates are meant for a subject, and which comes first, say the templates' **rules**
    (see [label templates](#label-templates-and-images)): the one of the highest print priority is
    preselected (for a location: the one chosen for it, see below), the others above priority 0 are
    shown, those of priority 0 under **more labels**, unless none ranks higher.
  * Each choice has a preview and either the printer it would print on or why no printer can
    print it now.
  * No printer is picked when printing: the job is offered to the printers, and the first one that is free
    and can print it takes it (active, reachable, with these labels loaded as far as it reported). The
    dialog names a printer that can print it now; **Printer** (shown with more than one active printer)
    leaves the job to that printer only ("Any printer with these labels" by default).
  * Labels no printer can print now are greyed but can still be previewed. Printing them puts the
    job in a queue (the dialog says so beside the button **Wait for a printer**): it waits up to five
    minutes (`PRINT_WAIT_MAX`) and is printed as soon as a printer can (a print agent back online,
    the right tape loaded, labels of that size put into a printer). Otherwise it expires unprinted.
    The dialog follows the job as long as it waits. Without any active printer nothing waits.
  * **Preselect from now on** (locations only, off at first): the chosen label becomes the one preselected
    the next time this location is printed, in the overview each printed location's. Without it printing
    changes nothing, so a one-off label (e.g. a temporary tape) does not replace the location's label.
  * **Also its sub-locations** (e.g. a shelf with its compartments) shows an overview instead: a row per
    location, each with the template best for it preselected (the compartment's arrow chosen for it), to
    change or to leave out.
    * Each row starts with its label in its real size (1 mm on the label is 1 mm on the screen, as far
      as the screen reports its size); long tape labels scroll sideways.
    * A tap anywhere on a row (but its template) switches it on or off.
    * The template is chosen from a menu with a preview of each; **use this label for all** (first row)
      gives the first row's label to every row it is meant for.
    * A printer mark beside each label (also on the single dialog's labels): green when it is printed
      now, struck through in red if not. Its text says where it prints, else why not: a suitable printer
      is online but with other labels (or none left), no suitable printer is online (offline, an error), or
      no printer has these labels.
    * Above the button a summary says what waits for what, e.g. "16 at once, 3 waiting for labels
      (TZe-231 …), 3 waiting for a printer (P-touch Werkstatt)"; the button says how many labels are
      queued, **copies per label** counted ("22 labels").
    * Each label is a job of its own; the jobs of one print form a batch that the dialog follows together
      ("12 of 30 labels printed, 2 waiting for a printer").
* **Price tags** (location pages): the same overview with a row per bulk item stored at the location,
  each with its best item template (a price tag for items with a sale price); **only items with a sale
  price** chooses the rows.
* **Item pages** (bulk items): the same, with the location the label is for. Item labels show
  name, price per unit (items for sale) and a QR code.
* **Unique items:** the **Label** button on a unique item's page prints the unique item: with the templates
  for unique items ("ZAMid, Fremdeigentum" for items of another owner) and the label ID templates by its ID
  ("ZAMid"). A unique item without a label ID gets one when it is first printed.
* **Label IDs (ZAMid):** the **Label** button on an ID's info page (`/id/<code>/info/`) prints the ID's
  label. Batches of reserved IDs: the admin action **Print labels** on selected IDs (as above: the label
  decides the printer), or `manage.py label_id_labels --batch NAME --print PRINTER [--tape 12]` (the
  printer's short name), with the label ID template its rules put first on those labels; jobs of at most
  20 labels. An ID's *printed at* is set
  once the printer reports the label printed. The ID's info page and its admin page show its label
  (`label_printing.selection.preferred_template`).
* **After creating** a box, carton, pallet, shelf or compartments (after their purposes, if asked
  for), the location's page opens the dialog right away for whoever may print, with just the labels
  of the new locations checked (`?print=<their pks>`): a new box alone gets the single dialog; a new
  shelf with compartments, compartments added to a shelf, or several containers (on the page of the
  location they were added to) get the overview.
* The previews show the label as the printer gets it, in the tape's colours for Brother tapes
  from the label material. After printing the dialog follows the job until the printer reports back.
* **Waiting jobs** have no printer and no printer data yet. They are drawn for the printer that
  turns out able to print them. Who looks for one:
  * every request of a print agent, for the printers on it;
  * the dialog, while it follows the job; without a broker it also asks network printers for their
    status, at most every 20 seconds;
  * with a broker, a Celery task every ten seconds while jobs wait, which asks the network printers.
* Printing labels is a privilege: it requires `label_printing.print_label`, which migration
  `label_printing.0002` grants to the local group (for now only to it). That holds everywhere: the print
  dialogs and their previews, and in the admin the location actions and **Print label** link, printing
  after reserving containers, the printers' test and calibration labels, reprinting jobs and printing label IDs.
  Without it, logged-in users see the dialog's button disabled; guests do not see it; the admin leaves
  out the actions and fields. With no suitable or reachable printer, the button is disabled with the
  reason.

### What the QR codes hold

* **Locations:** the location's code via the label host, uppercase so the QR code stays small
  (alphanumeric mode): `HTTPS://I.ZAM.HAUS/WH-1.R303.A`. Codes stay with their location
  ([location structure](location-structure.md)); the resolver finds codes and former codes in
  any case ([label IDs](label-ids.md)). In label templates it is `{qr}`.
* **Items:** the item's own label ID (ZAMid), then the code of the location the label is for,
  uppercase so the QR code stays alphanumeric: `HTTPS://I.ZAM.HAUS/K7R4XD/WH-1.R303.A`. The ID is
  claimed for the item when its first label is printed and serves every location (previews use a
  placeholder). The resolver passes the location on to the item's page (`?loc=`; a location code
  that is unknown is left out), which puts **Take out** first there.

### Taking stock out (item pages)

Item pages show **Take out** and **Add stock** first among their actions, beside the title, without
a location: they open the stock change dialog for the location from the label (`?loc=`), which is
also marked in the list; for an item at several locations the dialog offers the others
([stock changes](stock-changes.md)). Actions that do not fit go into the actions menu from the
right, so taking out stays visible longest.

## Setting up (admin → Label printing)

1. **Label material** is the catalog of labels and tapes. A printer always prints on the material loaded in
   it: Brother the tape of the width it reported (of its colours where the catalog has them; a tape missing
   from the catalog is added as "24 mm" etc. with the colours reported), a Zebra its loaded labels (see 2.).
   **On hand** (field, or the list actions **On hand** / **Not on hand**) is for the material that is not
   loaded: only material on hand is offered for printing then, and waited for. Each printer prints on the
   material it takes (see 2.); there is nothing to set up per printer.
   * Brother P-touch tapes (TZe, HGe) with article number, width, print and background colour,
     kind (laminated, extra strong adhesive, flexible, matte, …) and description, from Brother's
     tape selector (`label_printing/catalog/brother_tapes.json`, loaded by migration `0002`), not on hand
     until ticked. Heat shrink tubes, flags and stencil tape are left out. A height is a fixed label length
     (empty: as long as the content).
   * Zebra labels with width and height, roll **core** and **winding** (printed side outside or inside),
     **printing method** (direct thermal, or thermal transfer with a **wax**, **wax/resin** or **resin**
     ribbon), material, background colour and **darkness** (`^MD`, -30 to 30; empty: the printer's setting).
     Migration `0002` creates one per size of the ZPL templates there were (where their printing method and
     material are not known, fill them in), the labels bought from labelident.de (1 inch core) and a leftover
     roll from Greiner (2 × 47 × 24 mm side by side: a template prints only on the left one), all on hand.
     Sizes are whole millimetres (15 × 6.35 mm is 15 × 6; the name keeps the exact size).
   * The **print quality** of material is used unless the label template sets one: *draft (fast)*,
     *standard*, *high quality (slower)*. Brother: draft printing (P900, P900W, P950NW only; the others
     print standard), or high resolution (E550W, P750W, P710BT 180×360, P900, P900W, P950NW 360×720 dpi;
     not the P700 and P910BT): the label is drawn at twice the resolution along the tape, not only printed twice as dense. Zebra: print speed (`^PR6`, the printer's own setting, `^PR2`).
   * Material offers the label templates for its labels: of its size, and of its label material, material
     and colours if a template names them (see [label designs](label-designs.md#where-templates-are-offered)).
   * **Ribbons** (admin → Ribbons) are a catalog of their own: material (wax, wax/resin, resin), width and
     colour, shown as e.g. "Wachsband 110 mm, schwarz". A Zebra prints in the colour of its loaded ribbon
     (unless the labels are direct thermal): label templates that name a print colour are offered by it, and
     previews show it; Zebra labels have no print colour of their own. Without a ribbon set, labels count as
     printing black. Migration `0002` brings the ribbons there are: 110 mm, wax, wax/resin and resin, each
     black and red.
2. **Printers:** name, short name (used by the print agent), language, model (Brother: E550W,
   P700, P750W, P710BT, P900, P900W, P950NW, P910BT; sets the resolution), resolution (Zebra: 203/300/600 dpi), and the
   connection: *network* with host and port, or *print agent*. Leave *reports its status* on
   unless a printer cannot answer status requests. *Ask for its status every* (seconds, default
   60, 0: never): how often the worker checks a network printer between jobs. One printer is the default for the admin's
   print actions.
   * **Labels it takes**, filled in from the model when the printer is added, where not given otherwise (Brother:
     the widest tape of its print head; Zebra: `ZEBRA_MODELS` in `label_printing/models.py`, e.g. GK420t: up to
     108 mm wide, 1 inch core, wound outside, thermal transfer; GK420d: direct thermal only); change them for
     models not known there. Language and model are fixed once the printer exists: another model is another
     printer (delete it and add the new one). A printer takes material of its language that fits: Brother tape its print head
     has and no wider than its widest; Zebra labels no wider than its widest, of its core and winding, and
     thermal transfer labels only if it prints thermal transfer. What is empty is not checked. The printer's
     page lists the material loaded and on hand it takes.
   * **Calibration:** offset x and y in dots, for all its labels (Zebra: label home `^LH`; Brother: offset y
     moves the print across the tape, positive = down, if the top or bottom is cut off: print the calibration
     label to measure).
   * A Zebra cannot tell which labels are in it: set its **loaded labels** (label material it takes)
     whenever labels are changed: on its print agent's display (**Etiketten wählen**; in the admin the field
     is then read-only, as is the ribbon: the agent knows what is in its printers), for a network Zebra in
     the admin. Only those are printed on, and only while the label length
     the printer measured (`~HS`, after calibration) matches their height within 2 mm; the width
     cannot be checked. The check is made when the dialog lists the labels and again right before a
     job is sent (also by print agents). Set its **loaded ribbon** likewise when changing ribbons: its material is
     compared with the ribbon the loaded labels need (thermal transfer only, and only when both are
     known). Labels for wax take wax or wax/resin (resin does not hold on paper), labels for wax/resin take
     wax/resin or resin, labels for resin only resin. A ribbon that does not suit them does not stop printing;
     the printer list's status and the print agent's display warn (there the display blinks until another
     ribbon is set), as does a request to load labels the ribbon does not suit.
   * Brother printers report the tape themselves; they set the **cutting**:
     * half cut between the labels of a job (default), a full cut after each label, or no cut;
     * **continuous printing** (default on): the last label stays in the printer and the next job
       goes on from there, saving the tape's leading margin. Cut it off with the printer's cutter
       button. Off, the printer feeds and cuts after every job.
     * The **P700 and P710BT** cannot half cut (Brother's raster command references): they cut fully,
       and are added with a full cut and continuous printing off. Nor do they cut off the empty start of
       the tape between cutter and print head (24.3 mm, "no precut"), which other models do before a job:
       without continuous printing, every job begins with an empty label of minimum length (24.5 mm),
       cut off, so the first label starts cleanly (it counts as a page of the job). With continuous
       printing, the first label after the cutter button keeps that start. The P700 has no high
       resolution either: high quality prints as standard there.
     * The P900 series needs the last page of a job marked as such in its print information (`ESC i z`
       n9 = 2; 0 the first, 1 the others), or it waits for more pages and hangs until switched off; the
       128-pin models (E550W, P750W, P700, P710BT) print with 0 on every page. For high resolution and draft
       printing on laminated tape it needs the media type 09h there. Brother's raster commands have no print
       speed or darkness (unlike a Zebra's `^PR`/`^MD`).
     * The calibration label's lines are a pin thick per 180 dpi (2 on the P900 series): single pins of a
       360 dpi head print faint and broken.
3. Print jobs record the printer and the label material they were printed on.
4. **Test label** (30 mm on tape) and **Check the printer status** are actions on the printer list.

The admin prints as the print dialog does (`label_printing/admin_printing.py`, `services.print_batch`): the
action **Print location labels**, a location's **Print label** button and the label IDs' **Print labels** ask
for the label (a template on labels of one size, with the printer it would print on or why none can) or
**each the one preselected for it** (as in the dialog: its last one, else by the rules), and the copies.
The server picks the printer as in the dialog; labels no printer can print now wait for one. Subjects no
label is meant for are named and left out; jobs hold at most 20 labels, all in one batch. Printing after
reserving containers works the same way.

### Label templates and images

**Label templates** (admin → Inventory) are for locations, items, unique items or label IDs (ZAMid):
* Each is written in the label description language: [label designs](label-designs.md).
* The name says what is on the label; its size comes from the description and is shown beside the
  name.
* **Rules** (rows below the template) say which subjects it is meant for and how much: a condition as
  in `{% if %}`, with the variables of the labels (`location.type.category == "container"`,
  `item.kind == "bulk" and item.sale_price is not None`, `unique_item.has_owner`; empty: always), and the
  **print priority** while it holds. A template is meant for a subject while one of its rules holds; its
  priority is the highest of those. Without rules it is meant for every subject of its kind, on request
  (priority 0). The list of templates shows the rules.
* The list of templates shows each template's label with a few random records of its kind; with the
  pointer on it, one after another (only records whose labels one may see). Where there are no records,
  a made-up one: every property lorem ipsum, numbers random.
* Templates can be **deactivated** (field or list action): they are then neither offered nor
  printed, not even by waiting jobs or the admin's print actions.
* The page shows the label beside the description while it is typed, with real records (of a saved
  template those its saved rules are meant for) and with the printer it is for chosen or none. Mistakes
  are listed by line, and a template with mistakes is not saved. The list of templates shows each with
  random records it is meant for.
* The location page shows the location's label: with the template chosen for it, else the
  one its rules put first.
* **Last labels** (`LastLabel`) remember the template chosen for each location in the print dialog
  (**preselect from now on**; printing alone does not change it). Migration
  `label_printing.0002` made the templates chosen before (`Location.label_template`, else the location
  type's `default_label_template`) the locations' last labels, so they keep their labels; the rules decide
  for new locations.

**Label images** (admin → Label printing) are logos, safety signs and tool icons:
* Each image is stored once in its full size and cut down on its page by dragging.
* **Import** takes many images at once, or ZIP archives of them.
* Designs scale the images for each printer and turn them black and white (threshold or dither).

Migration `label_printing.0002` brought the templates as tried out on the development server, as first
deployed (`label_printing/catalog/label_templates_0002.json`: name, size, description, active or not, quality,
labels, rules). The ZPL templates there were became templates named by what they are for (`replaces` in the
file names the ZPL template), keeping their IDs, so locations and types keep their labels; their
logo became the label image "ZAM Logo"; a template it did not know got a plain design and its ZPL
as comments. Migration `label_printing.0007` brings them up to date with `label_printing/catalog/label_templates.json`
(the same entries in the same order, then the new ones): a template still as deployed becomes its successor
("Fester Standort" → "Lagermöbel", "Pfeil hoch / runter" → "Regalboden, …", "Mobil, …" → "Kiste"), keeping its
ID; templates changed in the admin are left as they are. A later change to the catalog needs a migration like
0007 (the deployed migrations read the files as they were). They follow the [location display rule](locations.md#how-locations-are-shown): the location's
title first, its code after it inverted in monospace (also next to the label ID on item labels).

They follow the colour rule of the label material: **yellow** (polyester, P-touch tape) for permanent places (boxes,
pallets) and every ZAMid on things, **white on black** for storage units and shelf levels (printed inverted on white
paper or tape, so they need no material of their own; not yellow), **white** paper for cartons, contents and items.
So location, ZAMid and cable templates print on labels of any colour, those for storage units and shelf levels on
tape only on white tape, item labels on white only.

* locations: "Ort" (QR code, title: purpose, else name, then the code inverted, path) on 57 × 32, 60 × 30 and
  70 × 32 mm labels and every tape (deactivated on 105 × 52 mm); for pallet rack slots "Ort, Palettenregal", the same printed inverted, on
  105 × 52 mm (the yellow polyester on hand: yellow on black, while it lasts) and 100 × 50 mm white paper
  (ERT-PP100X050Z1: white on black), on request; "Lagermöbel" (QR code, code, title and where it is: shelves, cabinets, drawers, tables) and
  "Regalboden, Pfeile zum Ausmalen" (both arrows as light areas: the one for the other level is coloured in black,
  the default for shelf levels), "Regalboden, Pfeil hoch" and "Regalboden, Pfeil runter" (the arrow to the shelf
  level it is for), all printed inverted, white on black (the QR code comes out light on dark, which the scanners
  read): the default on 70 × 32 mm paper on hand (shelf boards of 4 cm), on 18 mm white tape (TZe-241) for 2 cm
  boards and where 70 × 32 mm does not fit; their former versions on 55 × 15 mm are deactivated;
  "Kiste" on 18 mm tape (extra strong: TZe-S641; QR code and code, "Eigentum" and the logo upright, centred),
  the successor of 105 × 52 mm (large boxes) and 55 × 15 mm (small boxes: QR code and code, the ZAM logo without its
  wordmark and "Eigentum"), which are printed while they last; also on 60 × 30 mm; "Inhalt" for boxes, cartons and pallets (QR code, the code with the title beside it, the
  date below; who is responsible (its teams; responsible persons and rentals once the inventory has them) and whose
  the contents are, once if one owner's, else marked at each unique item not the ZAM's; then what is right at the
  location: the locations in it, items, unique items with a bullet; on further labels if it does not fit) on
  100 × 150 mm labels, permanent or removable paper (the permanent 4 × 6 in roll on hand takes it: Zebra labels
  up to 2.5 mm larger take a template),
  also across ("Inhalt, quer": the information left, the list right of it; turned by 90°); "Karton" (QR code, title
  and code, no path: cartons move) on 70 × 32 mm; "Palette" (QR code and the code large, right of them a frame for a
  removable 60 × 40 mm label, marks in the corners to staple it; the block's face takes up to 110 × 80 mm) on
  105 × 52 mm, and for its frame "Palette, Feld" (the code and the date, what it is for large, who is responsible
  and whose it is, and the rental large: lines to write it on until the inventory has rentals) on 60 × 40 mm
  removable paper; "Sortimentsfach" (the code alone, for compartments of assortment boxes) on 15 × 6.35 mm,
  deactivated: those labels come six side by side, so they can only be printed in whole rows (pre-printed), not one
  by one;
* bulk items: "Artikel", the item and its price tag in one (QR code, name, the price in a price tag frame as wide as
  the price, an empty one without a price to write it on, and the location; no name: a line to write it on), the
  default on 50 × 18 mm removable paper (ERT-PA050X018Z1: the name in a line at the top, below it the QR code left,
  the price in the middle and the location's code right), and on the 47 × 24 mm removable polyester on hand while it
  lasts (two side by side on the roll: printed one at a time, the other stays blank); also on 57 × 32, 60 × 30,
  70 × 32 and 105 × 52 mm labels and on tape (deactivated on 9 mm tape). The former "Preisschild" templates are
  deactivated;
* label IDs: "ZAMid" (lettering, QR code, ID in two lines; on tape with a margin of at least
  1 mm at top and bottom), on 55 × 15 mm the standard for the ZAM's things, with the ZAM logo (without its wordmark, label image "ZAM Logo ohne Wortmarke") and "Eigentum"
  (deactivated on 105 × 52 mm); **cable wraps** on 18 mm tape (flexible: TZe-FX641), the
  standard for cables (a QR code on a cable does not scan well), one per cable thickness: wound about 1.2 times
  round the class's thickest cable: the lettering, the ID (K7R-4XD), a Code 128 of the ZAMid, the ID, the barcode
  again, the ID and the lettering, the texts upright and the barcode across the tape (the bars run round the cable,
  so it scans along it from every side, also on thin cables). The end covers part of the start, on a thinner cable of the class a
  little more. **Cable flags** on request: laid around the cable and stuck together back to back, a QR code on each
  side of the flag (both halves 17 mm long, so they meet), fold lines, and the ID, the lettering and the ID again, upright, around the cable:

  | Class (template "Kabel, Wickel bis …", "Kabel, Fahne bis …") | Cables (H07RN-F, outer diameter ca.) | Wrap tape | Flag: around the cable | Flag tape |
  |---|---|---|---|---|
  | bis 10,5 mm | 3G1,5 (9.4 mm) and thinner | 39.6 mm | 21 mm | 55 mm |
  | bis 12 mm | 3G2,5 (11.1), 5G1,5 (11.5) | 45.1 mm | 23 mm | 57 mm |
  | bis 14,5 mm | 5G2,5, CEE 16 A (13.5) | 54.7 mm | 26 mm | 60 mm |
  | bis 17 mm | 5G4, CEE 32 A (15.9) | 64.1 mm | 28 mm | 62 mm |
  | bis 19 mm | 5G6, CEE 32 A (17.9) | 71.5 mm | 29 mm | 63 mm |

  Around the cable a flag takes 2 × the largest diameter of the class (the manufacturers' upper tolerance) for the
  thinnest cables, down to 1.5 × for the thickest. Diameters: Faber/Zuhmann datasheet H07RN-F (2016), tolerances
  Dönges (2015).
* label IDs on tape: "ZAMid, ZAM-Eigentum" (the ZAMid design, "Eigentum" and the ZAM logo upright, centred) on 12 and
  18 mm tape, for the ZAM's things (extra strong tape: TZe-S631, TZe-S641), the successor of 55 × 15 mm;
* unique items: "ZAMid, Fremdeigentum" (the ZAMid design, "Fremdeigentum" and the owner's first name; a long name in
  two lines; on 55 × 15 mm and 12 and 18 mm tape "Fremdeigentum" smaller above the name in two lines, in a
  column of fixed width on tape, so a long name does not make the label long).

On 55 × 15 mm labels that start with a QR code the QR code keeps as much room to the left as to the top (2.4 mm
margin left). On Brother tape a label that starts with a QR code keeps 1 mm more margin left, one that ends with text
2 mm more right, clear of the cut (not the cable wraps: their length is set by the cable, and the lettering at both ends keeps
the same narrow margin).

Labels of the Zebra (die-cut) have rounded corners: designs keep a margin of at least 1 mm, which stays clear of
corners up to a radius of about 3.4 mm.

Their rules:

| Template | Condition | Priority |
|---|---|---|
| Ort | always | 1 |
| Ort, Palettenregal | (no rules: on request) | 0 |
| Karton (70 × 32 mm) | `location.type.name == "Karton"`; always | 3; 0 |
| Palette (105 × 52 mm) | `location.type.name == "Palette"`; always | 3; 0 |
| Lagermöbel (70 × 32 mm; 18 mm tape) | `location.type.category == "storage_unit"` (shelves, shelf levels, drawers, cabinets, tables); always | 3 / 2; 0 |
| Regalboden, Pfeile zum Ausmalen (70 × 32 mm; 18 mm tape) | `location.type.name == "Fach"`; always | 4 / 3; 0 |
| Regalboden, Pfeil hoch / runter (70 × 32 mm; 18 mm tape) | `location.type.name == "Fach"`; always | 2 / 1; 0 |
| Kiste | `location.type.name == "Kiste"` (105 × 52 mm and 18 mm tape: 3, 60 × 30 and 55 × 15 mm: 2); always | 3 / 2; 0 |
| Sortimentsfach | always | 0 |
| Inhalt, Inhalt quer | `location.type.name == "Kiste" or … "Karton" or … "Palette"`; always | 1; 0 |
| Palette, Feld (60 × 40 mm) | `location.type.name == "Palette"`; always | 1; 0 |
| Artikel (50 × 18, 47 × 24 mm removable) | `item.kind == "bulk"` | 2 |
| Artikel (other sizes) | `item.kind == "bulk"` | 1 |
| ZAMid | always (55 × 15 mm: 3) | 2 / 3 |
| Kabel, Wickel … | always | 1 |
| Kabel, Fahne … | always | 0 |
| ZAMid, ZAM-Eigentum (12 and 18 mm tape) | always | 3 |
| ZAMid, Fremdeigentum | `unique_item.has_owner` (55 × 15 mm, 12 and 18 mm tape: 4) | 3 / 4 |

Templates for the successor of a label material get the same priority as those for the labels they replace:
among equals the dialog prefers what can be printed now, then labels on hand, then labels no printer has. So
55 × 15 mm stays preselected while it is on hand, and its successors take over once it is marked as not on hand
and they are.

So shelf levels get white on black 70 × 32 mm with arrows to colour in (18 mm white tape for 2 cm boards), shelves,
drawers and cabinets white on black 70 × 32 mm, boxes yellow 18 mm tape (TZe-S641; while they last 105 × 52 mm and for small boxes 55 × 15 mm),
cartons white 70 × 32 mm without the path, pallets yellow 105 × 52 mm with a frame for a removable label, bulk items
50 × 18 mm removable paper with their price, and things their ZAMid on yellow 55 × 15 mm. A location printed before keeps the
template chosen for it as the preselected one.

Fonts:
* Raleway and Roboto Mono (the ZAMid's),
* Roboto Condensed (narrow like Zebra's built-in font),
* OCR-B.

They are in `label_printing/design/fonts/`, with their licences.

### Job log

**Print jobs** lists every job with printer, label material, result and who printed. The filter
**labels out of date** finds printed labels whose location code, item name or price changed
since; the action **Print these labels again** prints them as they are now. Unprinted data is
kept only until a job is finished. **Pause**, **Go on** and **Abort** stop jobs that went wrong: a job
no printer has taken yet is aborted at once; a job a print agent prints gets the command with the agent's
next poll (the list then says "Paused on the print agent."); a network printer's job cannot be stopped.
Pausing a job holds its printer; it stays held also when the job is aborted then. The printers list shows
held printers ("Held on the print agent."), and **Go on (printers held on their print agent)** lets them go
on, whoever held them (also on the agent's display).

## How jobs travel

```
dialog / admin print actions → services.submit_outcome(): PrintJob(status=waiting), the label and its
                 subjects, optionally for one printer; nothing rendered yet
test label, label IDs, reprint → services.submit(): rendered for the given printer and labels at once,
                 PrintJob(status=waiting) for that printer only
a free printer takes the oldest waiting job it can print now (services.take): rendered for it (if not yet),
                 status processing
  agent printer   → with the print agent's poll, one job per free printer (POST /print/api/agent/poll)
  network printer → the dispatcher (services.offer_to_network_printers: when a job comes, when one is done,
                    and every 10 s while jobs wait), printed by the Celery task label_printing.tasks.process_job
both: devices.run.run_job(): status first, then the data, then wait for "printed"
```

The queue is an offering: a job is not bound to a printer before one takes it. So a busy printer's long
queue does not hold up labels another printer with the same labels could print, and a printer that comes
back or gets other labels just takes what it can print.

* **Status check** before printing: Brother `ESC i S` (no tape, cover open, overheated, and the
  loaded tape width, which must match the job's tape: "24 mm tape is loaded, but 12 mm was chosen").
  Brother network printers (e.g. PT-P900W) do not answer that on port 9100; their status comes
  over SNMP (UDP 161, community `public`, Brother's status OID), which must be switched on in the
  printer's web interface. Without either, the result is "The printer does not answer"; turning
  off *reports its status* prints without checks;
  Zebra `~HS` (out of labels, paused, head open, ribbon out). If the printer cannot print,
  nothing is sent.
* **After sending:** Brother reports each printed page; a Zebra is polled until its buffer is
  empty. No answer in time: *sent, not confirmed*.
* **Statuses:** waiting for a printer → printing → printed / sent, not confirmed / failed / expired. A
  job no printer took in time expires (the person has moved on): one of the dialog after
  `PRINT_WAIT_MAX` seconds, one for a given printer after `PRINT_JOB_MAX_AGE`; one without result after
  `PRINT_JOB_LEASE` seconds fails. A printer that cannot be reached is
  tried again a few times; anything else is never repeated, so nothing is printed twice. The
  dialog's request ID makes a repeated submission return the same job.
* The printer's last status is kept and shown in the dialog; for a Brother, the label material with the
  loaded tape width is preselected. It comes from each job, from the print agents (every 30
  seconds), from **Check the printer status** in the admin and, for network printers, from the
  worker's regular check (below).

### Network printers: Celery

`docker-compose.yml` runs Redis as broker and a `worker` service
(`celery -A imzam worker --queues label_printing --concurrency 1 --beat …`), one job at a time. The
worker must reach the printers on port 9100. Without `CELERY_BROKER_URL` (development), the
task runs right away in the request.

**Regular status checks** (with a broker only): the worker's beat starts
`label_printing.tasks.check_network_printers` every `PRINT_STATUS_TICK` seconds (15). It asks
the active network printers that report their status and whose last status is older than their
*ask for its status every* (60 s by default, per printer): whether they answer, their errors and
what is loaded. So a printer switched off, out of labels or with other tape shows as such in the
dialog before anyone prints. A status that a job, the dialog or the admin brought in counts too, so
busy printers are rarely asked. It never gets in the way of printing: the check runs in the
worker's queue, which prints one job at a time; printers with a job being printed are skipped (a
Brother is reset before it is asked), also by the admin's **Check the printer status**; and
with a broker, web requests leave asking the printers to the worker. A tick the worker could not
take in time is dropped, not piled up.

### USB and Bluetooth printers: the print agent

`label_printing/agent.py` runs on a computer next to the printers (e.g. a Raspberry Pi; setting
one up, with Bluetooth, the optional touch screen and a read-only system:
[ops/raspberry-pi/](../ops/raspberry-pi/README.md)). It needs Python 3.9+ and only `label_printing/agent.py`,
`label_printing/station.py`, `label_printing/touch.py` and `label_printing/devices/`: no Django, no database;
the touch screen needs `python3-pygame`, Bluetooth `python3-dbus` and `python3-gi` (without them it runs
without). What the display shows and does is `station.Station`; the touch screen's layout (`touch.py`) is plain
Python, drawn by `devices/screen.py`. An agent serves one inventory: the first server of its configuration
(`agent.Connection`). Others listed there (e.g. a development server) can be chosen on the touch screen's
**Verbindung** tab, for trying things out: the agent then asks the chosen server everything anew, as after a
reboot, until it starts again (not while a printer has jobs). Each printer prints in a thread of its own, so
several print at once. (Agents before version 6 served several servers at once; the PiFace Control & Display
is no longer supported.)

1. **Created by an admin:** **admin → Print agents → add** gives the agent a token, shown once as
   the entry for its configuration (`{"url": …, "token": …}`); **Give a new token** replaces it
   (the old one stops working). Nothing registers itself: every request of an agent carries its
   token, unknown tokens are refused (401), and so are deactivated agents (403), which locks a lost
   Pi out. With each request the agent reports its host name; the admin shows it with its address,
   version and whether it is online.
2. **Printers find themselves:** the agent looks for USB printers of Brother and Zebra every
   10 seconds (kernel driver `usblp`, `/dev/usb/lpN`) and reports them with a stable ID from
   USB vendor, product and serial number (`usb-04f9-2085-A2B3C4D5E6`), so a printer keeps its
   settings on another port or Pi. They appear in **admin → Printers**, inactive, named after maker and
   product as people say them ("Zebra GK420t", not "Zebra Technologies ZTC GK420t"), with language,
   model and resolution filled in where known (Brother by USB ID, Zebra by asking it, `~HI`).
   Brother P-touch printers with Bluetooth (named `PT-…BT`) are paired (by themselves, or confirmed on the
   agent's display) and reported with an ID from their Bluetooth address (`bt-a1b2c3d4e5f6`).
   Name them, check the model and **Activate** them; mark label material that is not in a printer as on hand. A printer found
   again (unplugged and plugged in, the agent restarted) stays as it is, active or not; one that
   has moved to another agent moves along and stays active if it was. An agent may report at
   most `PRINT_AGENT_MAX_PRINTERS` new printers.
3. **Status:** every 30 seconds, and after each job, the agent reports what the printers say:
   errors, and what is loaded: Brother tape width, tape and print colour; Zebra label length and
   direct thermal or thermal transfer. The admin and the print dialog show it; for a Brother,
   the dialog preselects the label material of the loaded tape (width and colours).
4. **Jobs:** with each poll (`POST /print/api/agent/poll`, every 2 seconds) each active printer of the
   agent that is not busy (agents report the busy ones) takes the oldest waiting job it can print now,
   rendered for it; the agent reports each result. A printer whose agent has not asked for 30 seconds
   (`PRINT_AGENT_OFFLINE_AFTER`), or whose agent is deactivated, is offline: the dialog says so.
   Agents before version 6 are refused ("update the print agent", HTTP 426).
5. **Pausing and aborting:** the agent sends the data label by label. Each poll lists the jobs it holds
   and whether they are paused: their lease (`PRINT_JOB_LEASE`) starts again, so a paused job is not taken
   for lost. The answer carries the admin's commands for them (pause, go on, abort), sent until the agent
   reports them done. Paused on the agent's display or in the admin, a printer stops after the label being
   sent (a Zebra after the label it prints, `~PP`) and starts no other job; aborted, the rest is dropped (a
   Zebra's buffer is cleared, `~JA`) and the job fails as "The print was aborted.". A held printer stays held
   until it goes on, whatever becomes of its jobs. Agents since version 5.1 also list their held printers
   (`held`; kept as the printer's `held_at`), and the answer carries `printer_commands` (`{uid: "resume"}`)
   for those an admin let go on. On the display, aborting runs in the background: reporting the dropped jobs
   may take long while the server cannot be reached.
6. **For the display:** the poll's answer also names the agent's printers as in the admin, a Zebra's label material on hand
   and which is loaded, and the labels waiting for one of its printers that is online but has other labels
   loaded (or none left): printer, labels, how many jobs, what is loaded. On the display someone can set a
   Zebra's loaded labels (`POST /print/api/agent/printers/loaded`); jobs waiting for them go out at once.
   A printer active on the server gets **Testetikett drucken** and **Kalibrieretikett drucken** on its page
   of the touch screen (since agent version 5.3): the agent asks for
   the label (`POST /print/api/agent/printers/own-label`, `{"printer": uid, "label": "test"}` or
   `"calibration"`), which is queued like the admin's test print on the labels loaded in it and comes with
   the next poll; a refusal (no label material it takes, printer inactive) is shown with its reason.
   Each job carries its subject's name (`subject`, e.g. the location), which the touch screen lists with the
   printer's jobs.

Configuration: a JSON file, by default `label-agent/config.json` on the Pi's boot partition, else
`/etc/label-agent/config.json`:

```json
{"servers": [{"url": "https://inventar.zam.haus", "token": "…"},
             {"url": "http://192.0.2.10:8000", "token": "…"}],
 "poll_interval": 2, "status_interval": 30, "scan_interval": 10,
 "display": "auto", "backlight_timeout": 600, "screen_rotation": 0, "read_only": true,
 "bluetooth": true, "bluetooth_pairing": "confirm", "bluetooth_scan_interval": 60,
 "bluetooth_pin": "0000", "bluetooth_channel": 1,
 "static_printers": [{"uid": "zebra-lan", "device": "tcp://192.0.2.10:9100", "language": "zpl"}]}
```

`static_printers` adds printers the agent reaches otherwise (e.g. on the network, a Bluetooth printer
on another RFCOMM channel as `bt://AA:BB:CC:DD:EE:FF/2`, or a fake printer); they are reported like USB
printers under their `uid`. Trying it out on a laptop:
`python3 -m label_printing.agent --server http://localhost:8000 --token …` (with
`static_printers`, e.g. the simulator's, in a `--config` file). A server that redirects (e.g. another domain to
`DEFAULT_URL`) is followed. The agent logs job numbers and sizes, not the labels' content.

## Fake printers for development

```
python -m label_printing.simulator --zebra 9101 --brother 9102 --out labels/
```

answers like a Zebra and a Brother PT-E550W on these ports, including status and print
confirmations, and saves what it prints in `labels/`: Brother raster data decoded to PNG, Zebra
ZPL as `.zpl` plus PNG (one label) or PDF (several) rendered by **labelary.com**. That is an
external service with rate limits: use it with test data only, or pass `--no-render`. Set up
printers on `localhost:9101` / `localhost:9102` (or give a print agent `static_printers` with
`tcp://localhost:9101`). The fake Zebra also pauses (`~PP`), goes on (`~PS`) and drops its
buffer (`~JA`) like a real one. Error states come from `--zebra-errors paper_out,paused`,
`--brother-errors cover_open`, `--brother-tape 24`, `--brother-snmp 1161` (status over SNMP only,
like a PT-P900W on the network; set the device's SNMP port accordingly in tests), or at runtime from a JSON file given with
`--state-file`:

```json
{"zebra": {"errors": ["paper_out"]}, "brother": {"tape_mm": 24, "silent": true}}
```

The tests start the simulator on free ports (`label_printing/tests/helpers.py`).

## Settings

| Setting | Default | Meaning |
|---|---|---|
| `CELERY_BROKER_URL` | empty | broker for the worker; empty: jobs run in the request |
| `PRINT_JOB_MAX_AGE` | 120 | seconds a job for a given printer (test label, label IDs, reprint) may wait for it |
| `PRINT_JOB_LEASE` | 180 | seconds a job may be printing without a result |
| `PRINT_AGENT_OFFLINE_AFTER` | 30 | seconds after an agent's last request that its printers count as offline |
| `PRINT_MAX_COPIES` | 20 | most copies per job |
| `PRINT_WAIT_MAX` | 300 | seconds a job of the print dialog may wait for a printer to take it |
| `PRINT_AGENT_MAX_PRINTERS` | 20 | new printers an agent may report |
| `PRINT_STATUS_TICK` | 15 | seconds between looks for network printers due for a status check (with a broker) |

## Personal data

Labels show only location and item data. The job log records who printed and is visible in the admin
only; printed labels are also entries of the [change log](change-log.md); print jobs, printers, agents, label material and ribbons
are left out of the [data export](data-export.md); label templates and images are exported. Only the
simulator sends anything to labelary.com (what it prints, in development).
