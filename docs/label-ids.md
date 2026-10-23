# Label IDs

Label IDs are short, permanent IDs on labels such as `K7R-4XD` (spec:
[`inventory/label_ids/LABEL-ID-SPEC.md`](../inventory/label_ids/LABEL-ID-SPEC.md)). The model is `inventory/models/label_id.py`;
everything else is in `inventory/label_ids/`. Each one is printed as a QR code for `HTTPS://I.ZAM.HAUS/K7R4XD`
plus text on a Brother P-touch label.

Users see them under the name in `LABEL_ID_NAME` (default `ZAMid`): page
titles, texts, the admin and the logo on printed labels. Code, database and
settings always say "label ID", so another organization only changes that
setting (and the hosts below).

* **Resolver:** `i.zam.haus/<id>`, `id.zam.haus/<id>` and `inventar.zam.haus/id/<id>`
  behave identically. Locally, use `localhost:8000/id/<id>`. The resolver
  accepts any typed or scanned form (`k7r 4xd`, lookalikes such as `O`/`0`) and
  responds as follows:
  * Assigned IDs redirect to their item, location, unique item or URL.
  * Reserved IDs open the claim page.
  * Retired IDs, and IDs whose target was deleted, show an explanation (HTTP 410).
  * Typos list existing IDs that are likely meant.
  * Location codes come first: location labels hold `HTTPS://I.ZAM.HAUS/<code>` (uppercase
    for the QR code's alphanumeric mode). Codes and former codes are found in any case and
    redirect to the location; codes of several locations that differ only in case offer a
    choice. New IDs are never drawn equal to a location code (`services.is_location_code`).
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
  * A claimed ID is never relinked or deleted. Retiring keeps the link.
  * Soft-deleting an item or location leaves its ID assigned; the resolver then
    says it is no longer in the inventory. Deleting it permanently retires its
    IDs, unlinks them and adds its name and number to their note.
  * Triggers in the database enforce this as well.
* **Lookup:** `item.label_ids` / `location.label_ids` / `uniqueitem.label_ids` (indexed). `inventory.label_ids.lookup`
  provides `active_code(obj)` and `annotate_label_code(queryset)`, which add no
  extra queries per row.
* **Labels:** `/id/<code>/label.png?printer=P900&tape=24` is public for assigned
  IDs (the unique item's page shows it) and requires `inventory.view_labelid` otherwise.
  For batches, use the admin action *Download labels (ZIP)*, or run
  `manage.py label_id_labels --batch NAME --printer E550W --tape 12`. Print the PNGs
  in **standard** resolution, without scaling. Printing them directly on a printer of the
  inventory: the **Label** button on the unique item's and the ID's page, the admin action
  *Print labels*, or `label_id_labels --batch NAME --print PRINTER` ([label printing](label-printing.md)). Fonts (OFL) are in
  `inventory/label_ids/labels/fonts/`.
* **Other commands:** `label_id_check <input>…`, `label_id_check --missing` and
  `label_id_retire <code>`.
