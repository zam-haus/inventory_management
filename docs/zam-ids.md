# ZAM IDs

ZAM IDs are short, permanent label IDs such as `K7Q-4XD` (spec:
[`inventory/zamid/ZAM-ID-SPEC.md`](../inventory/zamid/ZAM-ID-SPEC.md)). The model is `inventory/models/zamid.py`;
everything else is in `inventory/zamid/`. Each one is printed as a QR code for `HTTPS://I.ZAM.HAUS/K7Q4XD`
plus text on a Brother P-touch label.

* **Resolver:** `i.zam.haus/<id>`, `id.zam.haus/<id>` and `inv.zam.haus/id/<id>`
  behave identically. Locally, use `localhost:8000/id/<id>`. The resolver
  accepts any typed or scanned form (`k7q 4xd`, lookalikes such as `O`/`0`) and
  responds as follows:
  * Assigned IDs redirect to their item, location, unique item or URL.
  * Reserved IDs open the claim page.
  * Retired IDs, and IDs whose target was deleted, show an explanation (HTTP 410).
  * Typos list existing IDs that are likely meant.
  * More than 30 misses from one client within 10 minutes are answered with 429.
* **Hosts:** `ZAMID_RESOLVER_HOSTS` lists the hosts served by the resolver only;
  they must also be in `ALLOWED_HOSTS`. `ZAMID_INVENTORY_BASE` sets where they
  redirect to and defaults to `DEFAULT_DOMAIN`.
* **Lifecycle:** reserved → assigned → retired.
  * Only the admin (*Generate IDs*) and `manage.py zamid_generate` create IDs.
  * Members with `inventory.claim_zamid` claim a reserved ID by scanning it: the
    resolver opens the claim page, which links it to an existing or new item,
    location or unique item. Migration `inventory.0022` grants this permission to ZAM-local.
  * Only the admin (`assign_url_zamid`) can link an ID to an arbitrary URL.
  * A claimed ID is never relinked or deleted. Retiring keeps the link.
  * Soft-deleting an item or location leaves its ID assigned; the resolver then
    says it is no longer in the inventory. Deleting it permanently retires its
    IDs, unlinks them and adds its name and number to their note.
  * Triggers in the database enforce this as well.
* **Lookup:** `item.zam_ids` / `location.zam_ids` / `uniqueitem.zam_ids` (indexed). `inventory.zamid.lookup`
  provides `active_code(obj)` and `annotate_zam_code(queryset)`, which add no
  extra queries per row.
* **Labels:** `/id/<code>/label.png?printer=P900&tape=24` is public for assigned
  IDs (the unique item's page shows it) and requires `inventory.view_zamid` otherwise.
  For batches, use the admin action *Download labels (ZIP)*, or run
  `manage.py zamid_labels --batch NAME --printer E550W --tape 12`. Print the PNGs
  in **standard** resolution, without scaling. Fonts (OFL) are in
  `inventory/zamid/labels/fonts/`.
* **Other commands:** `zamid_check <input>…`, `zamid_check --missing` and
  `zamid_retire <code>`.
