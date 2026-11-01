# Data export for development

A copy of the real inventory for development databases, without personal data, so that it
can be handed to developers and may also be published.

## Export (production)

```sh
ops/export.sh              # exports/inventory-export-<date>.tar, a few MB
```

Without containers: `./manage.py export_public_data TARGET`; a `TARGET` ending in `.tar` becomes an
archive, any other a new directory.

The export contains:

* `data.json`: the data as a Django fixture
* `export-info.json`: date, rows per model, the excluded models, the code version (migrations)

Photos and documents are not part of it; development systems load them from production (below).

## Import (development)

In an empty database (with SQLite: delete `db.sqlite3`):

```sh
./manage.py migrate
./manage.py import_public_data inventory-export-<date>.tar   # or the unpacked directory
./manage.py createsuperuser
```

The import refuses a database that already holds an inventory, and an export made with
newer code (update your checkout and migrate first).

## Photos and documents

With `MEDIA_REMOTE_URL` set (as in `imzam/local_settings.example_dev.py`, e.g.
`https://inventar.zam.haus/`) and `DEBUG` on, a file missing in `MEDIA_ROOT` (`data/media/`) is loaded
from that installation when a page needs it, and kept there. Files that are here come first.

* Thumbnails come from the installation as well. Where it has none in that size yet, the
  original is loaded and the thumbnail made here; otherwise originals are only loaded when
  opened (e.g. in the photo viewer).
* Only what the installation shows to visitors who are not logged in comes through:
  photos and public documents. Floor plans and internal documents stay missing.
* A file the installation does not have is asked for again after 10 minutes.

To work offline, load all photos and public documents of the imported data at once (rerun
it to continue; files that are here are kept):

```sh
./manage.py download_public_media
```

Without `MEDIA_REMOTE_URL`, the pages work, but images are missing.

The code is in [`inventory/remote_media.py`](../inventory/remote_media.py): the media storage
(`MediaStorage`) loads missing files whenever something opens them or checks whether they exist.
Its class is part of every thumbnail's file name (sorl-thumbnail hashes the storage of the
source); renaming or moving it renames all thumbnails, which are then made anew.

## What is left out or replaced

Kept is what the website shows to visitors who are not logged in, plus internal data
that is not personal, such as the change log without who acted, or location types.

| Data | In the export |
|---|---|
| User accounts (names, emails, directory data, passwords) | left out; developers create their own |
| Who did something (change log, label IDs) | cleared; recorded names become `[redacted]` |
| Owners of unique items | account and contact cleared; the first name becomes `[redacted]`, so "not ZAM property" stays visible |
| Responsible person of unique items | cleared (responsible team kept) |
| Notes in the change log and on label IDs | emptied |
| Owners and internal values in the change log, names of internal documents there | left out, `[redacted]` |
| Purchase prices (internal) | cleared |
| Internal documents | left out |
| Label scans, admin log, sessions, thumbnail cache | left out |
| Cleanup imports (uploaded proposals, who uploaded and applied them) | left out |
| Printers, label media, print agents, print jobs | left out (network addresses, tokens, who printed what) |
| Items, locations, photos, public documents, descriptions, unique item notes | kept (public on the website) |

The rules are in [`inventory/public_export.py`](../inventory/public_export.py): every model is
listed as exported or excluded; of exported models, the fields to replace are listed, and all
others are kept (see [New models and fields](#new-models-and-fields)). The [search](search.md)
follows the same rules: it never finds a field the export replaces or a row it leaves out; so does the
[cleanup export](item-cleanup.md).

## Before publishing

* The export prints a warning for every kept text that contains a user's full name,
  username or email address, e.g. `check inventory.item 1234 description: contains '…'`.
  Look at these texts and edit them in the inventory if they should not be public.
* Free texts (descriptions, notes, text recognized in photos) can still name people in ways
  the check does not find. Everything kept is public on the website already, so
  the export does not reveal more than the website, only in bulk.
* Photos are not part of the export, but development systems load them from the website. They
  keep their metadata (EXIF) there, which can include camera models and GPS coordinates.

## New models and fields

A new model stops the export until it is listed in `inventory/public_export.py`, either in
`EXPORTED_MODELS` or, with the reason, in `EXCLUDED_MODELS`:

```
CommandError: Export stopped, inventory/public_export.py needs a review:
  model inventory.supplier is neither exported nor excluded
```

Of an exported model, every field is exported unless it is listed under `replace` (`cleared`,
`emptied`, `redacted_if(...)`). New fields are therefore public by default. Fields that look
personal stop the export until someone decides: a reference to a user account, or a name with
`owner`, `contact`, `actor`, `note`, `email`, `mail`, `phone`, `user`, `person`, `address`,
`password`, `token` or `secret` in it, or ending in `_by` (`looks_personal`, `PERSONAL_WORDS`):

```
  field inventory.item.supplier_contact looks personal: replace it, or mark it public
```

Replace it, or list it under `public` if visitors who are not logged in see it on the website
anyway. Other new fields with personal or internal data (e.g. a price only staff see) are not
caught: put them under `replace` when adding them. `inventory/tests/test_public_export.py`
fails as well until a stopping model or field is decided.
