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
  labels, not printers: each active label template, with its size, e.g. "Preisschild" on
  60 × 30 mm labels or "QR-Code, Kennung, Name und Ort" on 12 mm tape. Templates whose QR code would be
  too small to scan at a printer's resolution are not offered on it (9 mm tape on the E550W).
  * Each choice has a preview and either the printer it would print on or why no printer can
    print it now.
  * The server picks the printer: active, reachable, with these labels and, as far as it
    reported, with them loaded. The default printer comes first.
  * Labels no printer can print now are greyed but can still be previewed. Printing them puts the
    job in a queue (the dialog says so beside the button **Wait for a printer**): it waits up to five
    minutes (`PRINT_WAIT_MAX`) and is printed as soon as a printer can (a print agent back online,
    the right tape loaded, labels of that size put into a printer). Otherwise it expires unprinted.
    The dialog follows the job as long as it waits. Without any active printer nothing waits.
  * A location with sub-locations (e.g. a shelf with compartments) can print theirs in the same
    job. The dialog remembers the label chosen last for each kind.
  * More than ten labels at once (`PRINT_CONFIRM_LABELS`, sub-locations and copies counted) must
    be confirmed; more than 50 (`PRINT_MAX_LABELS`) are refused.
* **Price tags** (location pages): a label of each bulk item stored at the location, with the item
  templates; by default only of the items with a sale price.
* **Item pages** (bulk items): the same, with the location the label is for. Item labels show
  name, price per unit (items for sale) and a QR code.
* **Unique items (ZAMid):** the **Label** button on a unique item's page and on an ID's info page
  (`/id/<code>/info/`) prints the ID's label: "ZAMid" (lettering, QR code, ID) or "ZAMid: QR + ID".
  Batches: the admin action **Print labels** on selected IDs, or `manage.py label_id_labels --batch
  NAME --print PRINTER [--tape 12]` (the printer's short name), with the medium's first ZAMid
  template; jobs of at most 20 labels. An ID's *printed at* is set once the printer reports the
  label printed. The ID's info page and its admin page show its label drawn from a ZAMid template
  (`label_printing.outcomes.preview_template`); unique item pages have no label section of their own.
* **After creating** a box, carton, pallet, shelf or compartments, the new location's page opens
  the dialog right away (`?print=1`) for whoever may print.
* The previews show the label as the printer gets it, in the tape's colours for Brother tapes
  from the label stock. After printing the dialog follows the job until the printer reports back.
* **Waiting jobs** have no printer and no printer data yet. They are drawn for the printer that
  turns out able to print them. Who looks for one:
  * every request of a print agent, for the printers on it;
  * the dialog, while it follows the job; this also asks network printers for their status, at
    most every 20 seconds;
  * with a broker, a Celery task every ten seconds while jobs wait.
* Printing requires `label_printing.print_label`, which migration `label_printing.0002` grants
  to the local group. Without it, logged-in users see the button disabled; guests do not see it.
  With no suitable or reachable printer, the button is disabled with the reason.

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

Item pages show a large **Take out** button per location, which opens the stock change dialog
for removing. The location from the label (`?loc=`) comes first and is marked in the list.

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
   unless a printer cannot answer status requests. One printer is the default for the admin's
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
   are optional. Media offer the label templates of their size; if templates are chosen for the
   medium (or its stock), only those of the kind being printed.
4. **Test label** (30 mm on tape) and **Check the printer status** are actions on the printer list.

The location admin's print actions, its **Print label** button and printing after mass creation
use the default printer and its default medium (a Zebra: its loaded labels), with the location's
own template or its type's if the medium offers it.

### Label templates and images

**Label templates** (admin → Inventory) are for locations, bulk items or unique items (ZAMid):
* Each is written in the label description language: [label designs](label-designs.md).
* The name says what is on the label; its size comes from the description and is shown beside the
  name.
* Templates can be **deactivated** (field or list action): they are then neither offered nor
  printed, not even by waiting jobs or the admin's print actions.
* The page shows the label beside the description while it is typed, with real records and with
  the printer it is for chosen or none. Mistakes are listed by line, and a template with mistakes
  is not saved.
* The location page shows the location's label (its template, else its type's).

**Label images** (admin → Label printing) are logos, safety signs and tool icons:
* Each image is stored once in its full size and cut down on its page by dragging.
* **Import** takes many images at once, or ZIP archives of them.
* Designs scale the images for each printer and turn them black and white (threshold or dither).

Migration `label_printing.0002` described the ZPL templates there were in the language, named by
what is on them ("Fester Standort", also with an arrow up or down, and "Mobil, mit Logo und
Eigentum"), and stored their logo as the label image "ZAM Logo"; a template it did not know gets a
plain design and its ZPL as comments. It also added templates for 57 × 32, 60 × 30, 70 × 32 and
105 × 52 mm labels and for 9, 12, 18, 24 and 36 mm tape:
* locations: "QR-Code, Kennung, Name und Ort" (QR code, code, name, path);
* bulk items: "Name, Preis und QR-Code", and "Preisschild" (price with € in a price tag frame, unit,
  name, QR code) on 60 × 30 mm labels and on 12, 18 and 24 mm tape;
* unique items: "ZAMid" (lettering, QR code, ID in two lines; on tape with a margin of at least
  1 mm at top and bottom) and "ZAMid: QR + ID".

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
  loaded tape width is preselected.

### Network printers: Celery

`docker-compose.yml` runs Redis as broker and a `worker` service
(`celery -A imzam worker --queues label_printing --concurrency 1`), one job at a time. The
worker must reach the printers on port 9100. Without `CELERY_BROKER_URL` (development), the
task runs right away in the request.

### USB printers: the print agent

`label_printing/agent.py` runs on a computer next to the printers (e.g. a Raspberry Pi; setting
one up: [ops/raspberry-pi/](../ops/raspberry-pi/README.md)). It needs Python 3.9+ and only
`label_printing/agent.py` and `label_printing/devices/`: no Django, no database. One agent serves
several inventories at the same time (e.g. production and a development server), each with
its own registration; jobs of different servers never reach a printer at the same time.

1. **Registration:** the agent makes up its ID (from the computer's machine-id) and one token per
   server, and registers (`POST /print/api/agent/register`). It appears in **admin → Print
   agents**, inactive, named after its host. **Activate** it (and rename it if you like).
   Waiting agents are limited (`PRINT_AGENT_MAX_PENDING`); an agent that registered again with
   another token (e.g. a new SD card) is refused until its old entry is deleted.
2. **Printers find themselves:** the agent looks for USB printers of Brother and Zebra every
   10 seconds (kernel driver `usblp`, `/dev/usb/lpN`) and reports them with a stable ID from
   USB vendor, product and serial number (`usb-04f9-2085-A2B3C4D5E6`), so a printer keeps its
   settings on another port or Pi. They appear in **admin → Printers**, inactive, with language,
   model and resolution filled in where known (Brother by USB ID, Zebra by asking it, `~HI`).
   Name them, check the model, **Activate** them and add their labels (media).
3. **Status:** every 30 seconds, and after each job, the agent reports what the printers say:
   errors, and what is loaded: Brother tape width, tape and print colour; Zebra label length and
   direct thermal or thermal transfer. The admin and the print dialog show it; for a Brother,
   the dialog preselects the medium of the loaded tape (width and colours).
4. **Jobs:** active agents get the jobs of their active printers (`POST /print/api/agent/poll`,
   every 2 seconds) and report each result. A printer whose agent has not asked for 30 seconds
   (`PRINT_AGENT_OFFLINE_AFTER`), or whose agent is inactive, is offline: the dialog says so.

Configuration: a JSON file, by default `label-agent/config.json` on the Pi's boot partition, else
`/etc/label-agent/config.json`:

```json
{"servers": ["https://inventar.zam.haus", "http://192.0.2.10:8000"],
 "poll_interval": 2, "status_interval": 30, "scan_interval": 10,
 "static_printers": [{"uid": "zebra-lan", "device": "tcp://192.0.2.10:9100", "language": "zpl"}]}
```

`static_printers` adds printers the agent reaches otherwise (e.g. on the network, or a fake
printer); they register like USB printers under their `uid`. The agent keeps its ID and tokens
in `state.json` (readable by it only) in its state directory: as a service the one systemd gives
it (`/var/lib/label-agent`), else `~/.local/state/label-agent`; `--state-dir` or `"state_dir"` in
the configuration choose another. Trying it out on a laptop:
`python3 -m label_printing.agent --server http://localhost:8000` (with `static_printers`, e.g.
the simulator's, in a `--config` file). A server that redirects (e.g. another domain to
`DEFAULT_URL`) is followed. The agent logs job numbers and sizes, not the labels' content.

Admin-created agents still work: **Give a new token** shows a token once, for the agent's
`state.json` (`"tokens": {"<server>": "<token>"}`).

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
| `PRINT_CONFIRM_LABELS` | 10 | more labels at once must be confirmed in the dialog |
| `PRINT_MAX_LABELS` | 50 | most labels the dialog prints at once |
| `PRINT_WAIT_MAX` | 300 | seconds a label no printer can print now may wait for one |
| `PRINT_AGENT_MAX_PENDING` | 20 | agents that may wait for activation |
| `PRINT_AGENT_MAX_PRINTERS` | 20 | printers an agent may register |

## Personal data

Labels show only location and item data. The job log records who printed (like the actor of a
stock change) and is visible in the admin only; print jobs, printers, agents and label stock
are left out of the [data export](data-export.md); label templates and images are exported. Only the
simulator sends anything to labelary.com (what it prints, in development).
