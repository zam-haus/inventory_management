# Label printing

Labels for locations and items are printed from the inventory pages on Zebra (ZPL) and
Brother P-touch printers. Printers are reached on the network (raw TCP, port 9100) or, when
connected by USB, through a **print agent** on a computer next to them. Every job is logged with
what the printer reported: printed, failed (and why) or sent without confirmation.

Every label is drawn by the server as an image, dot for dot at the printer's resolution, from a
**label template** written in a small language ([label designs](label-designs.md)). Labels are for
locations, bulk items and unique items (ZAMid); there are templates for each of them on every label
size in use (see [label templates](#label-templates-and-images)).

A Zebra gets the image as `^GFA` in ZPL, with the medium's settings (darkness, speed, offset); a
Brother gets P-touch raster data. The code is in the app `label_printing`.

## Printing

* **Location pages:** the **Label** button in the header opens the print dialog. It offers
  labels, not printers: the active label templates meant for the location, each on its size of labels,
  e.g. "Fester Standort" on 70 × 32 mm labels or "QR-Code, Kennung, Name und Ort" on 12 mm tape.
  Templates whose QR code would be too small to scan at a printer's resolution are not offered on it
  (9 mm tape on the E550W).
  * Which templates are meant for a subject, and which comes first, say the templates' **rules**
    (see [label templates](#label-templates-and-images)): the one of the highest print priority is
    preselected (for a location: the one it was printed with last), the others above priority 0 are
    shown, those of priority 0 under **more labels**, unless none ranks higher.
  * Each choice has a preview and either the printer it would print on or why no printer can
    print it now.
  * The server picks the printer: active, reachable, with these labels and, as far as it
    reported, with them loaded. The default printer comes first.
  * Labels no printer can print now are greyed but can still be previewed. Printing them puts the
    job in a queue (the dialog says so beside the button **Wait for a printer**): it waits up to five
    minutes (`PRINT_WAIT_MAX`) and is printed as soon as a printer can (a print agent back online,
    the right tape loaded, labels of that size put into a printer). Otherwise it expires unprinted.
    The dialog follows the job as long as it waits. Without any active printer nothing waits.
  * **Also its sub-locations** (e.g. a shelf with its compartments) shows an overview instead: a row per
    location, each with the template best for it preselected (the compartment's arrow it was printed with
    last), to change or to leave out.
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
  for unique items ("ZAMid mit Eigentum" for items of another owner) and the label ID templates by its ID
  ("ZAMid"). A unique item without a label ID gets one when it is first printed.
* **Label IDs (ZAMid):** the **Label** button on an ID's info page (`/id/<code>/info/`) prints the ID's
  label. Batches of reserved IDs: the admin action **Print labels** on selected IDs (as above: the label
  decides the printer), or `manage.py label_id_labels --batch NAME --print PRINTER [--tape 12]` (the
  printer's short name), with the label ID template its rules put first on that medium; jobs of at most
  20 labels. An ID's *printed at* is set
  once the printer reports the label printed. The ID's info page and its admin page show its label
  (`label_printing.selection.preferred_template`).
* **After creating** a box, carton, pallet, shelf or compartments (after their purposes, if asked
  for), the location's page opens the dialog right away for whoever may print, with just the labels
  of the new locations checked (`?print=<their pks>`): a new box alone gets the single dialog; a new
  shelf with compartments, compartments added to a shelf, or several containers (on the page of the
  location they were added to) get the overview.
* The previews show the label as the printer gets it, in the tape's colours for Brother tapes
  from the label stock. After printing the dialog follows the job until the printer reports back.
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

1. **Label stock** is the catalog of labels and tapes:
   * Brother P-touch tapes (TZe, HGe) with article number, width, print and background colour,
     kind (laminated, extra strong adhesive, flexible, matte, …) and description, from Brother's
     tape selector (`label_printing/catalog/brother_tapes.json`, loaded by migration `0002`).
     Heat shrink tubes, flags and stencil tape are left out.
   * Zebra labels with width and height, **printing method** (direct thermal, or thermal
     transfer with a **wax**, **wax/resin** or **resin** ribbon) and material. Migration `0002`
     created one per size of the ZPL templates there were; where their printing method and
     material are not known, fill them in.
2. **Printers:** name, short name (used by the print agent), language, model (Brother: E550W,
   P750W, P900, P900W, P950NW; sets the resolution), resolution (Zebra: 203/300/600 dpi), and the
   connection: *network* with host and port, or *print agent*. Leave *reports its status* on
   unless a printer cannot answer status requests. *Ask for its status every* (seconds, default
   60, 0: never): how often the worker checks a network printer between jobs. One printer is the default for the admin's
   print actions. A Zebra cannot tell which labels are in it: set its **loaded labels** (one of its
   media) whenever labels are changed. Only those are printed on, and only while the label length
   the printer measured (`~HS`, after calibration) matches their height within 2 mm; the width
   cannot be checked. The check is made when the dialog lists the labels and again right before a
   job is sent (also by print agents). Brother printers report the tape themselves; they set the
   **cutting**:
   * half cut between the labels of a job (default), a full cut after each label, or no cut;
   * **continuous printing** (default on): the last label stays in the printer and the next job
     goes on from there, saving the tape's leading margin. Cut it off with the printer's cutter
     button. Off, the printer feeds and cuts after every job.
3. **Media** of a printer (inline): choose a label stock, which fills in name, size and tape
   width, or enter them. Labels print in the **print quality** of their template (the medium's is
   only for its test label): *draft (fast)*, *standard*, *high quality (slower)*. Brother: draft printing,
   or high resolution (E550W 180×360, P900 series 360×720 dpi): the label is drawn at twice the
   resolution along the tape, not only printed twice as dense. Zebra: print speed (`^PR6`, the
   printer's own setting, `^PR2`); darkness stays with the medium. Offset and darkness (`^MD`)
   are optional. Media offer the label templates for their labels: of their size, and of their label
   stock, material and colours if a template names them (see [label designs](label-designs.md#where-templates-are-offered)).
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
* The location page shows the location's label: with the template it was printed with last, else the
  one its rules put first.
* **Last labels** (`LastLabel`) remember the template each location was printed with last. Migration
  `label_printing.0002` made the templates chosen before (`Location.label_template`, else the location
  type's `default_label_template`) the locations' last labels, so they keep their labels; the rules decide
  for new locations.

**Label images** (admin → Label printing) are logos, safety signs and tool icons:
* Each image is stored once in its full size and cut down on its page by dragging.
* **Import** takes many images at once, or ZIP archives of them.
* Designs scale the images for each printer and turn them black and white (threshold or dither).

Migration `label_printing.0002` brings the templates as tried out on the development server
(`label_printing/catalog/label_templates.json`: name, size, description, active or not, quality,
labels, rules). The ZPL templates there were become those named by what is on them ("Fester
Standort", also with an arrow up or down, and "Mobil, mit Logo und Eigentum"; `replaces` in the
file names the ZPL template), keeping their IDs, so locations and types keep their labels; their
logo becomes the label image "ZAM Logo"; a template it did not know gets a plain design and its ZPL
as comments. The other templates are for 57 × 32, 60 × 30, 70 × 32 and 105 × 52 mm labels and for
9, 12, 18, 24 and 36 mm tape (as `label_printing.0003` updated them, see below):
* locations: "QR-Code, Kennung, Name und Ort" (QR code, title: purpose, else name, then the code
  inverted, path);
* bulk items: "Name, Preis und QR-Code" (name, the price in a price tag frame as wide as the price,
  an empty one without a price, QR code, on labels also label ID and location; no name: a line to
  write it on; deactivated on 9 mm tape), and "Preisschild" (price with € in a price tag frame,
  unit, name, QR code) on 60 × 30 mm labels and on 12, 18 and 24 mm tape;
* label IDs: "ZAMid" (lettering, QR code, ID in two lines; on tape with a margin of at least
  1 mm at top and bottom);
* unique items: "ZAMid mit Eigentum" (the ZAMid design and the owner's first name).

Migration `label_printing.0003` applies the [location display rule](locations.md#how-locations-are-shown) to
them: the location's title first, its code after it inverted in monospace (also next to the label ID on item
labels, and on "Mobil, mit Logo und Eigentum" 105 × 52 mm). It updates the templates whose description is still
the one `0002` brought (`catalog/location_display_0003.json`, before and after); templates changed since stay
as they are.

Their rules:

| Template | Condition | Priority |
|---|---|---|
| QR-Code, Kennung, Name und Ort | always | 1 |
| Fester Standort | `location.type.category != "container"`; always | 2; 0 |
| Fester Standort, Pfeil hoch / runter | `location.type.category == "storage_unit"`; always | 1; 0 |
| Mobil, mit Logo und Eigentum | `location.type.category == "container"`; always | 2; 0 |
| Name, Preis und QR-Code | `item.kind == "bulk"` | 1 |
| Preisschild | `item.kind == "bulk" and item.sale_price is not None` | 2 |
| ZAMid | always | 2 |
| ZAMid mit Eigentum | `unique_item.has_owner` | 3 |

Fonts:
* Raleway and Roboto Mono (the ZAMid's),
* Roboto Condensed (narrow like Zebra's built-in font),
* OCR-B.

They are in `label_printing/design/fonts/`, with their licences.

### Job log

**Print jobs** lists every job with printer, medium, result and who printed. The filter
**labels out of date** finds printed labels whose location code, item name or price changed
since; the action **Print these labels again** prints them as they are now. Unprinted data is
kept only until a job is finished.

## How jobs travel

```
dialog / admin → services.submit(): renders the labels, builds the printer's bytes,
                 saves PrintJob(status=pending)
  network printer → Celery task label_printing.tasks.process_job (queue label_printing)
  agent printer   → waits until the print agent fetches it (POST /print/api/agent/poll)
both: devices.run.run_job(): status first, then the data, then wait for "printed"
```

* **Status check** before printing: Brother `ESC i S` (no tape, cover open, overheated, and the
  loaded tape width, which must match the medium: "24 mm tape is loaded, but 12 mm was chosen").
  Brother network printers (e.g. PT-P900W) do not answer that on port 9100; their status comes
  over SNMP (UDP 161, community `public`, Brother's status OID), which must be switched on in the
  printer's web interface. Without either, the result is "The printer does not answer"; turning
  off *reports its status* prints without checks;
  Zebra `~HS` (out of labels, paused, head open, ribbon out). If the printer cannot print,
  nothing is sent.
* **After sending:** Brother reports each printed page; a Zebra is polled until its buffer is
  empty. No answer in time: *sent, not confirmed*.
* **Statuses:** waiting → printing → printed / sent, not confirmed / failed / expired. A job
  not picked up within `PRINT_JOB_MAX_AGE` seconds expires (the person has moved on); one
  without result after `PRINT_JOB_LEASE` seconds fails. A printer that cannot be reached is
  tried again a few times; anything else is never repeated, so nothing is printed twice. The
  dialog's request ID makes a repeated submission return the same job.
* The printer's last status is kept and shown in the dialog; for a Brother, the medium with the
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

### USB printers: the print agent

`label_printing/agent.py` runs on a computer next to the printers (e.g. a Raspberry Pi; setting
one up: [ops/raspberry-pi/](../ops/raspberry-pi/README.md)). It needs Python 3.9+ and only
`label_printing/agent.py` and `label_printing/devices/`: no Django, no database. One agent serves
several inventories at the same time (e.g. production and a development server), each with
its own token; jobs of different servers never reach a printer at the same time.

1. **Created by an admin:** **admin → Print agents → add** gives the agent a token, shown once as
   the entry for its configuration (`{"url": …, "token": …}`); **Give a new token** replaces it
   (the old one stops working). Nothing registers itself: every request of an agent carries its
   token, unknown tokens are refused (401), and so are deactivated agents (403), which locks a lost
   Pi out. With each request the agent reports its host name; the admin shows it with its address,
   version and whether it is online.
2. **Printers find themselves:** the agent looks for USB printers of Brother and Zebra every
   10 seconds (kernel driver `usblp`, `/dev/usb/lpN`) and reports them with a stable ID from
   USB vendor, product and serial number (`usb-04f9-2085-A2B3C4D5E6`), so a printer keeps its
   settings on another port or Pi. They appear in **admin → Printers**, inactive, with language,
   model and resolution filled in where known (Brother by USB ID, Zebra by asking it, `~HI`).
   Name them, check the model, **Activate** them and add their labels (media). A printer found
   again (unplugged and plugged in, the agent restarted) stays as it is, active or not; one that
   has moved to another agent moves along and stays active if it was. An agent may report at
   most `PRINT_AGENT_MAX_PRINTERS` new printers.
3. **Status:** every 30 seconds, and after each job, the agent reports what the printers say:
   errors, and what is loaded: Brother tape width, tape and print colour; Zebra label length and
   direct thermal or thermal transfer. The admin and the print dialog show it; for a Brother,
   the dialog preselects the medium of the loaded tape (width and colours).
4. **Jobs:** agents get the jobs of their active printers (`POST /print/api/agent/poll`,
   every 2 seconds) and report each result. A printer whose agent has not asked for 30 seconds
   (`PRINT_AGENT_OFFLINE_AFTER`), or whose agent is deactivated, is offline: the dialog says so.

Configuration: a JSON file, by default `label-agent/config.json` on the Pi's boot partition, else
`/etc/label-agent/config.json`:

```json
{"servers": [{"url": "https://inventar.zam.haus", "token": "…"},
             {"url": "http://192.0.2.10:8000", "token": "…"}],
 "poll_interval": 2, "status_interval": 30, "scan_interval": 10,
 "static_printers": [{"uid": "zebra-lan", "device": "tcp://192.0.2.10:9100", "language": "zpl"}]}
```

`static_printers` adds printers the agent reaches otherwise (e.g. on the network, or a fake
printer); they are reported like USB printers under their `uid`. Trying it out on a laptop:
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
`tcp://localhost:9101`). Error states come from `--zebra-errors paper_out,paused`,
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
| `PRINT_JOB_MAX_AGE` | 120 | seconds a job may wait to be picked up |
| `PRINT_JOB_LEASE` | 180 | seconds a job may be printing without a result |
| `PRINT_AGENT_OFFLINE_AFTER` | 30 | seconds after an agent's last request that its printers count as offline |
| `PRINT_MAX_COPIES` | 20 | most copies per job |
| `PRINT_WAIT_MAX` | 300 | seconds a label no printer can print now may wait for one |
| `PRINT_AGENT_MAX_PRINTERS` | 20 | new printers an agent may report |
| `PRINT_STATUS_TICK` | 15 | seconds between looks for network printers due for a status check (with a broker) |

## Personal data

Labels show only location and item data. The job log records who printed and is visible in the admin
only; printed labels are also entries of the [change log](change-log.md); print jobs, printers, agents and label stock
are left out of the [data export](data-export.md); label templates and images are exported. Only the
simulator sends anything to labelary.com (what it prints, in development).
