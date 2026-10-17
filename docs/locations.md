# Location purpose and overview photo

Each location can have a **purpose** (one line, up to 50 characters) and one
overview photo. The purpose says what the location is for and is shown with its
name on pages and in lists: "Box 23: Carp project" (`Location.display_name`),
including the location list and search, sub-location lists and the location
choices (autocomplete, with the full path). Printed labels, the stored path
(`descriptive_identifier`) and the admin keep the plain name. The purpose is
included in location searches. Physical descriptions are kept separately.

**✏️** right after the name (and purpose) in the heading of the location page
edits the purpose in a small dialog. **📷** edits the photo in its own dialog:
it sits beside **Overview photo** in the first panel (**At this location …**), or,
while the location has no photo and that section is hidden, beside
**At this location …** itself. Without a photo yet, **📷** opens the camera right
away and the dialog follows with the new photo; with a photo, it opens the dialog,
where **📷 Take or choose a photo** lets the phone offer camera or library. Take an
overview of everything stored at the location and keep neighbouring locations
outside the frame. The optional crop step supports dragging a selection or
adjusting its edges with sliders. You can also rotate the photo clockwise in 90° steps.
Cropping and rotation also work on the current photo without choosing it again;
they happen in the browser, and the edited photo replaces the current one when
saving. Saving without such changes does not upload the photo again.
The detail page shows a thumbnail; the link and the enlarged view use the full photo.
Each dialog saves only its own field.

The photo appears in the first panel, **At this location …**, above the item list.
Item and sub-location lists stay expanded. The physical description appears beside
the location path, with a **Location details** button opening a modal containing
the type, physical description, label preview, and the type's rules for moving,
sub-locations, and unique identifiers.
Its columns stack on small screens.

Editing requires `inventory.change_location`; purpose and photo are public.
The history page requires `inventory.view_locationhistory`, because it shows who
made each change. Its link is currently hidden on the detail page. History
records the changed fields, their previous and new values, the time, and the
user responsible, including changes through the admin.
Replaced and removed photos remain in media storage so historical entries can
still display them. The history format supports additional event types in future.

## Long lists

The location page shows a panel per kind of entry: **At this location …** with
the overview of its contents and the photo, then quick-items, items, unique items and
sub-locations. The overview lists how many of each the location has ("12 items"),
each as a chip linking to its panel. Lists with
more than 10 entries show only the first 5 at first. Clicking the section heading
(marked with a triangle) or **Show all** below the list shows all entries;
clicking the heading again collapses it. This works without JavaScript
(`inventory/static/inventory/list_collapse.css`). Where the browser supports
`hidden="until-found"`, `list_collapse.js` hides the entries that way instead:
find-in-page (and links to a text fragment) then also finds collapsed entries,
and revealing one expands the list. Quick-items are never collapsed, because
their list is edited in place.

## Moving contents and dissolving

**📤 Move contents** and **❌ Dissolve location** open the same plan: choose a
destination, deletion or nothing (keep in place) for each stock entry and
sub-location, optionally including all descendants. The plan ends with two
buttons, **Review and keep location** and **Review and delete location**; the one
matching how the page was opened is highlighted, and keeping comes first, so
pressing Enter never deletes. Deleting stays visible but disabled, saying why,
while unique items are still stored at the location or its type or the user's
permissions do not allow it (see [Permissions](permissions.md)). Nothing changes
until the reviewed plan is confirmed.
