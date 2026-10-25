# Change log

One log (`inventory.ChangeLog`) records every change of items, unique items, stock and locations,
whether it was made on the website, in a dialog, in the admin or by a command, and every printed
label. The item, unique item and location pages show the last entries; the admin shows all of them.
It replaced the stock change log, the unique item history and the location history; their entries
were not carried over (migration `inventory.0046_change_log`).

## What is recorded

Each entry has the time, who acted (the account and its user name at the time), through which part
of the application (stock dialog, website, admin, location dissolution, label printing, other), the
action and what it is about. Changed fields are kept with their values before and after, as people
read them (names of related records, dates and prices formatted, choices by their label).

| Action | When |
|---|---|
| Created | an item, unique item or location is created (also a reserved container, in the admin only) |
| Activated | a reserved container is taken into use; also shown on the page of the location it is in |
| Changed | fields change, e.g. name, description, price, purpose, responsible teams, owner |
| Moved | a location gets another parent, a unique item or a stock entry another location |
| Deleted / restored | an item or location is deleted (also permanently) or restored in the admin |
| Removed from the inventory | a unique item is disposed, with the reason and note |
| Stock changed | an amount changes, a stock entry is added or removed (see [Stock changes](stock-changes.md)) |
| Attachment added / removed | photos, files and barcodes of an item or unique item |
| Label ID | a label ID is assigned or retired |
| Label printed | a print job was printed (done or sent): template, printer, copies |

Fields are listed per model in `TRACKED` (`inventory/change_log.py`); computed codes (unique and
locatable identifiers) are not. Entries keep values as text, so they stay readable when fields or
choices change; only field labels come from the current models. When a tracked field is removed or
renamed, remove it from `TRACKED` and add its label to `FORMER_FIELDS` (older entries otherwise show
its bare name). A field in `TRACKED` that no longer exists is not logged, with a warning in the log
and from `manage.py check` (`inventory.W001`); a test fails on it. Internal fields (purchase prices, owner accounts and contacts,
responsible person) are marked as internal.

Entries are shown on the pages they concern, so one change can appear on several pages: a move on
the pages of both locations, a new location on that of the location it is in, a stock change on the
item's and the location's page, a printed item label on both as well. Entries keep a label of their
subject, so they stay readable after it is deleted; deleted records are not linked.

## How it is recorded

Signal handlers write the entries on every save and deletion of the tracked models
(`inventory/change_log.py`, connected in `InventoryConfig.ready`), so new views need no code of their
own. The handlers compare the stored values before and after saving; saving without changes writes
nothing. Changes that bypass `save()` are logged explicitly: soft deletions
(`soft_delete.soft_deleted`), label IDs (`label_ids/services.py`), the stock dialog (`record_stock`)
and finished print jobs (`label_printing/services.finish` → `record_print`). Avoid `QuerySet.update()`
for tracked fields; it is not logged.

Who acted comes from the request (`inventory.actor.CurrentActorMiddleware`), or `acting_as(user)`
outside requests. `change_context()` sets the source and, for stock changes, the reasons; with
`log=False` nothing is logged inside it.

## Who sees what

| Who | Sees |
|---|---|
| Visitors and users without permission | no changes |
| Local group (`inventory.view_changelog`) | the changes, without who made them |
| `CHANGE_LOG_ACTOR_GROUP` (default „Aktive“, `inventory.view_changelog_actor`) | also who: „Vorname N. (benutzername)“ |
| `inventory.view_internal_details` | also internal values; others see “changed” with an internal chip |
| Staff in the admin (**Change log**, and on the pages of items, unique items and locations) | everything, including accounts and notes |

Migration `inventory.0046_change_log` grants `view_changelog` to the local group, both permissions to
the `CHANGE_LOG_ACTOR_GROUP` group (created if missing; its members come from the SSO groups), and
the permissions of the old logs' successors to whoever held those. The log is append-only: nobody can
add, change or delete entries in the admin.

## Settings

| Setting | Default | |
|---|---|---|
| `CHANGE_LOG_SHOWN` | 5 | how many of the last changes the pages show; 0 hides the panel |
| `CHANGE_LOG_ACTOR_GROUP` | `Aktive` | the group that sees who made a change (used by the migration) |

The [data export](data-export.md) keeps the entries without who acted, notes, owners and internal
values.
