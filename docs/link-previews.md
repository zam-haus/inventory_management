# Link previews

A link to the inventory shared in Signal, Matrix (Element), Telegram, WhatsApp, Slack and the like shows a
preview: the chat fetches the page without a login and reads its OpenGraph tags (`og:title`, `og:description`,
`og:image`, …). Every page has them (`{% link_preview_tags %}` in `templates/app_head.html`,
`inventory/templatetags/link_preview.py`); a page names what it shows by putting a `Preview` into its context as
`link_preview` (`inventory/link_preview.py`).

| Page | Title | Description | Picture |
|---|---|---|---|
| Item | its name | its description as plain text (200 characters), else its category | its first photo |
| Unique item | item, own name, label ID | the item's description; "Disposed." before it if disposed | its own first photo, else the item's |
| Location | purpose or name · code | the path above it, its physical description | its overview photo |
| Category | its name | the first line of its description, else its path | – |
| Map with a target | the marking's text, the location or the unique item | the room it is in, the level; an area's size | the map around it |
| Map | – (the page's title, "Map, level …") | – | the whole level |
| Everything else | – (the page's title) | – | – |

Without a title the bots take the page's `<title>`. Without a picture the logo shows
(`favicon/icon-maskable-512.png`) as a small card; a photo or map as a large one (`twitter:card`).

## Nothing about people

Previews are kept in chats outside the inventory. They show only what guests see anyway, and less: never notes
of unique items, responsible teams or people, owners, reasons of disposal, procurement sources, prices or text
recognised on photos. Photos are thumbnails (640×480, the gallery's size), never the original file with its name.

## Addresses

`og:url` and the pictures are absolute addresses on `DEFAULT_URL`: behind the proxy a request may not know it
came by https.

## Label links

Opening a label link counts as a label scan (`/id/<code>?via=label_scan`, [label IDs](label-ids.md)), and only
the last few are kept. Preview bots (recognised by their user agent, `PREVIEW_AGENTS`: Signal sends WhatsApp's)
are sent on as usual but not recorded.

## Map links

What a map link shows is in its query, where the server sees it (`?p=loc:<pk>`, `?p=item:<pk>`,
`?m=<lat>,<lng>`, `?a=<lat>,<lng>;…`, `&t=<text>`; [maps](maps.md#sharing-a-view)). `maps/preview.py` checks it
(a feature of that level; a marking within 200 m of the level's plans and positions, at most 100 corners; a text of
at most 60 characters) and draws `/map/level/<n>/preview.png` with the same query: 1200×630, the level's active
plans from their web images (never the uploaded file, whose PDF may name people in its metadata or notes; SVG
plans are left out), the positions in the map's colours, room names, and the target highlighted: the location or
unique item in pink with its name, a pin or the marked area with its text. Of a stacked area only the part the
target is in. No background map: the server asks no other server.

Pictures of locations, unique items and whole levels are kept in `MEDIA_ROOT/map_previews/<level>/` named
`<target>-<hash>.png`, the hash taken from everything drawn (plans, positions, styles, the target,
`RENDER_VERSION`): a change gives a new name, and writing one removes the older ones of the same target. Once a
day (at the next picture written) the pictures of locations gone or without position and of unique items disposed
go, and every picture not written for 90 days. Markings (any coordinates) are drawn for each request and not kept.
Browsers and chats keep a picture for a day (`Cache-Control`).
