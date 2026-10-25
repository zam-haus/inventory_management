# Label IDs

Label IDs are short, permanent IDs on labels such as `K7R-4XD` (spec:
[`inventory/label_ids/LABEL-ID-SPEC.md`](../inventory/label_ids/LABEL-ID-SPEC.md)). The model is `inventory/models/label_id.py`;
everything else is in `inventory/label_ids/`. Each one is printed as a QR code for `HTTPS://I.ZAM.HAUS/K7R4XD`
plus text on a Brother P-touch label.

Users see them under the name in `LABEL_ID_NAME` (default `ZAMid`): page
titles, texts, the admin and the logo on printed labels. Code, database and
settings always say "label ID", so another organization only changes that
setting (and the hosts below).

## Codes: what counts where

Two kinds of codes lead somewhere: a **location's code** (`unique_identifier`: `K0525`, `R303`, `R303.a`; on
location labels) and a **label ID** (ZAMid, on the labels of items and unique items, and of the few locations
that got one). Everywhere they are read by one function, `inventory/codes.py` `resolve_code`: the resolver
behind the QR codes (`i.zam.haus/…`, `/id/…`, the lookup `/id/?q=`), `?q=` of the location and item lists,
the location fields (scan button, `/loc/lookup`) and *Move here*. In this order:

1. an inventory location URL (`/loc/<pk>/…`), by its number;
2. a location's code in any case, also as a label URL (`HTTPS://I.ZAM.HAUS/R303.A`), then a former code;
3. a reserved container's code: it opens the container's activation;
4. the full short-name path (`HH-1.SK.K0520`), still accepted, no longer shown;
5. a label ID, with or without the dash and with look-alikes (`O`/`0`, `I`/`1`), also with the location of an
   item label after it (`K7R4XD/WH-1.R303.A`, passed on as `?loc=`);
6. in location fields, a number as the location's database ID;

and, if nothing matched, the same input as typed by a scanner with another keyboard layout. A label ID
in a location field must belong to a location. The item search keeps a typed location code as search text
(short codes such as `LAS` are words, too); scanned label URLs and label IDs lead to their target there as
well.

Codes and label IDs never collide: new label IDs are never drawn equal to a location code
(`services.is_location_code`), and a location code or former code that reads as an issued label ID is refused
(`Location._validate_codes`, `LocationFormerCode.clean`). `manage.py label_id_check --collisions` lists
codes that collide anyway (created around these checks).

## Resolver and accesses

* **Resolver:** `i.zam.haus/<id>`, `id.zam.haus/<id>` and `inventar.zam.haus/id/<id>`
  behave identically. Locally, use `localhost:8000/id/<id>`. The resolver
  accepts any typed or scanned form (`k7r 4xd`, lookalikes such as `O`/`0`) and
  responds as follows:
  * Assigned IDs redirect to their item, location, unique item or URL.
  * Reserved IDs open the claim page.
  * Retired IDs, and IDs whose target was deleted, show an explanation (HTTP 410).
  * Typos list existing IDs that are likely meant.
  * Location codes come first (see [Codes: what counts where](#codes-what-counts-where)): location labels
    hold `HTTPS://I.ZAM.HAUS/<code>` (uppercase for the QR code's alphanumeric mode). Codes and former codes
    are found in any case and redirect to the location; they never differ only in case
    ([location structure](location-structure.md)).
  * More than 30 misses from one client within 10 minutes are answered with 429.
* **Last accesses:** the last label scans and web form entries (lookup form,
  inventory search box) of each ID, five by default (`LABEL_ID_ACCESS_KEEP`), are
  shown on `/id/<code>/info/` and in the admin, with time, method and whether it
  came from the local network (`LOCAL_NETWORK_SOURCES`, by address, not by the
  user's local group; the column says "at ZAM" per `LOCAL_NETWORK_NAME`). The user is shown only with the permission
  `inventory.view_labelid_access_user`; it is personal data and no group has it by
  default. Label scans first redirect from the resolver host to
  `/id/<code>?via=label_scan` on the inventory host, where the login is known.
  Clicking links inside the inventory is not recorded.
* **Hosts:** `LABEL_ID_RESOLVER_HOSTS` lists the hosts served by the resolver only;
  they must also be in `ALLOWED_HOSTS`. `LABEL_ID_BASE_URL` (default
  `https://i.zam.haus/`) is the URL in QR codes and labels; for local testing set
  it to `http://i.localhost:8000/` (larger QR codes). `LABEL_ID_INVENTORY_BASE` sets where they
  redirect to and defaults to `DEFAULT_URL`. `LABEL_ID_RESOLVER_URL` (default
  `https://id.zam.haus/`) is the main resolver address: the other resolver hosts
  redirect there, keeping the path, except label scans (`/<CODE>` exactly as in a QR
  code), which go straight on to `/id/<code>?via=label_scan` on the inventory, so
  they are recorded without an extra hop. The inventory's own `/id/` URLs stay on the
  inventory: sending them to the resolver would record link clicks as scans. See
  [Domains](../README.md#domains).
* **Invalid stored codes:** IDs that are no longer valid, e.g. created under an
  earlier alphabet, stay accessible in the admin. The list marks them "invalid" with a warning triangle
  and has a *validity* filter; their page explains why and shows no label or
  resolver link.
* **Lifecycle:** reserved → assigned → retired.
  * Only the admin (*Generate IDs*) and `manage.py label_id_generate` create IDs.
  * Members with `inventory.claim_labelid` claim a reserved ID by scanning it: the
    resolver opens the claim page, which links it to an existing or new item,
    location or unique item. Migration `inventory.0022` grants this permission to the local group.
  * Only the admin (`assign_url_labelid`) can link an ID to an arbitrary URL.
  * The resolver also takes location codes; that of a reserved container (labels printed in advance,
    see [Building structure](location-structure.md)) opens its activation.
  * A claimed ID is never relinked or deleted. Retiring keeps the link.
  * Soft-deleting an item or location leaves its ID assigned; the resolver then
    says it is no longer in the inventory. Deleting it permanently retires its
    IDs, unlinks them and adds its name and number to their note.
  * Triggers in the database enforce this as well.
* **Lookup:** `item.label_ids` / `location.label_ids` / `uniqueitem.label_ids` (indexed). `inventory.label_ids.lookup`
  provides `active_code(obj)` and `annotate_label_code(queryset)`, which add no
  extra queries per row.
* **Labels** are drawn from the ZAMid label templates and printed on a printer of the inventory: the
  **Label** button on the unique item's and the ID's page, the admin action *Print labels*, or
  `label_id_labels --batch NAME --print PRINTER [--tape 12]` ([label printing](label-printing.md)).
  The ID's info and admin page show its label; the image is public for assigned IDs and needs
  `inventory.view_labelid` or `label_printing.print_label` otherwise. (The pixel-exact PNG labels
  of `idlabel.py` are gone.)
* **Other commands:** `label_id_check <input>…`, `label_id_check --missing` and
  `label_id_retire <code>`.
