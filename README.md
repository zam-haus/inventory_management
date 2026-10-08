# ZAM Inventory Managment

This is a basic inventory managment system, with a focus on quick and easy data collection without any previous knowledge about the items in inventory.

To be found at https://inv.zam.haus

Implemented with Django.

## Initial Data Collection
1. Define and label all (storage) location
2. Take pictures and count of items in storage locations
   using `/item/create` (i.e., `create_item`, `inventory.views.CreateItemView`) view
3. Annotate items with name, description, category and other metadata.

## Concepts/Features/Requirements/Restrictions
* Items can be at multiple locations
* Item images are the main source of truth during data collection
* Stock changes are not tracked (at the moment)
* Locations are hierarchically structred (tree)
* Label printing relies on Zebra ZPL compatible printers

## Location summaries

Each location can have one overview photo and a summary (one line, up to 50
characters). The summary is included in location searches.
Existing physical descriptions are preserved separately.

Use the **📷** button beside **Summary** under **Stored here** on the location detail page to edit both fields in an
in-page dialog. On iOS and Android, the photo input opens the browser's camera
flow; **Choose from photo library** offers an existing picture instead. Take an
overview of everything stored at the location and keep neighbouring locations
outside the frame. The optional crop step supports dragging a selection or
adjusting its edges with sliders. You can also rotate the photo clockwise in 90° steps.
Cropping and rotation happen in the browser before the photo is uploaded.
Saving applies the photo and the summary together.

Both appear above the item list under their shared **Stored here** heading,
with the summary first, followed by the photo.
Item and sub-location lists stay expanded. The physical description appears beside
the location path, with a **Location details** button opening a modal containing
the type, physical description, label preview, and the type's rules for moving,
sub-locations, and unique identifiers.
Its columns stack on small screens.

Editing requires `inventory.change_location`; summaries are public.
The history page requires `inventory.view_locationhistory`, because it shows who
made each change. Its link is currently hidden on the detail page. History
records the changed fields, their previous and new values, the time, and the
user responsible, including changes through the admin.
Replaced and removed photos remain in media storage so historical entries can
still display them. The history format supports additional event types in future.

When deploying, run `python manage.py migrate`. The migration preserves the existing physical
description while adding the new overview fields and history table.

## Quick-items

Quick-items are items known only by name, stored at one location with an
unknown amount. They are listed above the regular items under **Stored here**
on the location detail page and are edited right there:

* Type a name in the empty field at the end of the list and press Enter to add
  it; the cursor stays in a new empty field for the next one.
* Edit a name in place; it is saved when you press Enter or leave the field.
  Emptying a name and leaving the field (or pressing Enter) deletes the item.
* **×** deletes after five seconds, during which **Undo** keeps the item.
  Leaving the page sends pending deletions immediately.
* **i** opens the item page. Entering an amount there turns the quick-item into
  a regular item, which can no longer return to an unknown amount.

Quick-items are found by the regular item search. Managing them requires
`inventory.add_item` and `inventory.add_itemlocation` (granted to ZAM-local
users). Deletion is permanent, but only while an item is still a quick-item:
items with an amount, photos, files, barcodes or a second location are never
deleted from this list. Without JavaScript, the list still works through plain
form submissions.

## Development Setup
To get started do the following:
1. checkout this git repo
    `git clone git@github.com:zam-haus/inventory_management.git`
2. create and edit local settings file
    `imzam/local_settings.py`
    Here is a usable template:
    ```
    # Example local_settings.py for development usage
    # INSECURE, DO NOT USE IN PRODUCTION!
    from pathlib import Path

    DEBUG = True
    TEMPLATE_DEBUG = True
    ALLOWED_HOSTS = ['localhost', '127.0.0.1', '192.168.178.10', '10.233.1.123']
    SECRET_KEY="REPLACE ME!!!!!"

    MQTT_PASSWORD_AUTH = dict(username="im.zam.haus-django", password='...')

    BASE_DIR = Path(__file__).resolve().parent.parent
    DATABASES = {
        "default": {
            "ENGINE": "django.db.backends.sqlite3",
            "NAME": BASE_DIR / "db.sqlite3",
        }
    }
    ```
    for secure deployment: make sure to disable `DEBUG` and set `SECRET_KEY` to a random string and consult https://docs.djangoproject.com/en/4.0/howto/deployment/checklist/.
3. install all python requirements (asuming current python and pip installation is availible)
    `pip install -r requirements.dev.txt`
4. initialize database
    `python manage.py migrate`
5. create superuser account
    `python manage.py createsuperuser`
6. load basic dataset
    `python manage.py loaddata initial_inventory`
7. start local server
    `python manage.py runserver`
8. You can now login through the admin interface at `/admin`. This will also log you in to the frontend. The frontend login link will not work (as it relies on a working OIDC setup).

## Permissions

Frontend lists, details, searches, autocomplete and printable inventories are public.
Editing requires login and Django's `add`, `change` or `delete` permission for the
relevant model. Assign permissions to groups in **Admin → Authentication and
Authorization → Groups**, then assign users to those groups. Superusers retain
full access; being logged in or being staff alone does not grant inventory editing.

Item metadata, photos, barcodes and stock entries have separate model permissions.
For example, creating an item at a location requires `add_item` and
`add_itemlocation`. Moving locations requires `change_location`. Dissolving a
location requires `delete_location`, plus `change_location` / `change_itemlocation`
for moves and `delete_itemlocation` for stock removal. Permissions are checked
again when confirming a dissolution. Changing the deleted flag in admin also
requires the corresponding delete permission.

Migration `accounts.0002_zam_local_group` creates the reserved **ZAM-local** group
with add and change permissions for inventory models, but no delete permissions.
Its permissions can subsequently be adjusted in admin. A logged-in user joins this
group after detection on the ZAM network or when carrying an existing
`is_zam_local` session flag; that flag is then consumed. Anonymous local visits can
be remembered through the login redirect, but do not permit anonymous editing.
Membership belongs to the user and persists across logins and network changes.
SSO claims cannot assign this reserved group, and SSO updates never remove it.
The `(ZAM)` indicator reads group membership rather than session state.

Local detection matches the client IP against all DNS A records of `das.zam.haus`
by default. Configure `ZAM_LOCAL_SOURCES` as a list in local settings, for example:

```python
ZAM_LOCAL_SOURCES = ["das.zam.haus", "another.example.org", "192.0.2.5", "198.51.100.0/24", "2001:db8::/32"]
```

Alternatively, set the `ZAM_LOCAL_SOURCES` environment variable to a comma-separated
list. Literal addresses and CIDR ranges support IPv4 and IPv6; hostname lookups use
IPv4 A records. An empty list disables new network-based grants. DNS results are
cached per worker for `ZAM_LOCAL_DNS_CACHE_SECONDS` (default: 60 seconds; 0 disables
caching). Failed lookups do not match clients or retain expired addresses; other
configured sources still work. Existing group members need no DNS lookup.

Apply migrations with `python manage.py migrate` when deploying this change.

## Label Printing
Print jobs are passed to the printer via MQTT. A simple print server, listening to a (currently) hard-coded topic on mqtt.zam.haus and passing them onto a (currently) hard-coded printer is implemented by `print_server.py`. A more flexible (and complex) solution is planned.


## Deployment

1. clone git repo
2. copy .env.example to .env and edit (atleast) the following variables:
   * `ALLOWED_HOSTS`, set to a domain to be used to access the interface
   * `SECRET_KEY`, set to a long random string
   * `POSTGRES_PASSWORD`, set to a random string
   * `MQTT_PASSWORD`, set to the appropriate password (only needed for printing)
2. import initial data
    ```
    docker-compose run web ./manage.py loaddata initial_inventory
    ```
4. create superuser
    ```
    docker-compose run web ./manage.py createsuperuser
    ```
5. start
    ```
    docker-compose up
    ```
