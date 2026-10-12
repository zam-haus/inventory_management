# Location summaries

Each location can have one overview photo and a summary (one line, up to 50
characters). The summary is included in location searches.
Existing physical descriptions are preserved separately.

Use the **📷** button beside **Summary** under **Stored here** on the location detail page to edit both fields in an
in-page dialog. On iOS and Android, the photo input opens the browser's camera
flow; **Choose from photo library** offers an existing picture instead. Take an
overview of everything stored at the location and keep neighbouring locations
outside the frame. The optional crop step supports dragging a selection or
adjusting its edges with sliders. You can also rotate the photo clockwise in 90° steps.
Cropping and rotation also work on the current photo without choosing it again;
they happen in the browser, and the edited photo replaces the current one when
saving. Saving without such changes does not upload the photo again.
The detail page shows a thumbnail; the link and the enlarged view use the full photo.
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
