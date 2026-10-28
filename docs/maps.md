# Maps

Floor plans of the levels on a background map, with the positions of building parts and storage units on them (the
`maps` app). The map gives orientation when searching ("On the map" in the results), in the location window (a
location's code chip: a small map with it, or the place it is in, highlighted; Leaflet is loaded only then) and on
the pages of locations:
**Position** opens a small map of where it is, with "Show on the map" to the large map. Whoever may place it switches
to **Edit** there first, so that nothing is moved by accident; others see "Edit" disabled with the reason (guests do
not see it).

Maps are optional. Small installations leave them off and run on plain SQLite or PostgreSQL; nothing of the
inventory depends on them.

## Turning them on

`MAPS_ENABLED=1` adds the app and switches the database engine to its spatial variant: SQLite to SpatiaLite,
PostgreSQL to PostGIS (`imzam/settings.py`). GeoDjango needs GDAL, GEOS and PROJ; PDF plans need poppler
(`pdftoppm`).

- **Server:** `MAPS_ENABLED=1` in `.env`. The scripts in `ops/` then also use `docker-compose.maps.yml`: the
  database image becomes `postgis/postgis:18-3.6` (same PostgreSQL version and data directory, so the existing
  database stays), and the app images are built with `MAPS=1` (GDAL and poppler). `migrate` creates the PostGIS
  extension on the next start. After setting it, run `ops/update.sh` so the images are rebuilt; a plain restart
  keeps the images without GDAL, and the app stops with "MAPS_ENABLED is set, but GDAL is missing". By hand,
  without `ops/`: `COMPOSE_FILE=docker-compose.yml:docker-compose.maps.yml`; Docker Compose also reads that line
  from `.env`, so plain `docker compose …` commands then use the maps images too.
- **Development (macOS, MacPorts):** `sudo port install gdal geos proj9 spatialite` (and `pg17-postgis` for the
  PostgreSQL test cluster). In `imzam/local_settings.py`:

  ```python
  MAPS_ENABLED = True
  GDAL_LIBRARY_PATH = "/opt/local/lib/libgdal.dylib"
  GEOS_LIBRARY_PATH = "/opt/local/lib/libgeos_c.dylib"
  SPATIALITE_LIBRARY_PATH = "/opt/local/lib/mod_spatialite.so"  # the loadable module, not libspatialite.dylib
  ```

  The first `migrate` with SpatiaLite adds its metadata tables to the existing `db.sqlite3`.
- **Turning them off again** leaves the `maps_*` tables in the database, unused.

The tests of the app run only when it is on (`maps/tests/__init__.py`); run the suite both ways
(`MAPS_ENABLED=0 manage.py test` when the local settings turn it on).

## Background map

Under the plans lies a background map: by default the aerial photo of Erlangen of 2018, switchable to the Bavarian
aerial photo (DOP20), OpenStreetMap in the osm.de style or none (the layer button; each browser remembers its
choice). The tiles come from the [RRZE tile server](https://osm.rrze.fau.de) of the FAU; their licences ask for the
attribution shown in the corner. This is the only thing the pages load from a third party: visitors of a map send
their IP address to that server.

Which layers are offered, from which tile servers, and which one is shown first is set in the admin: *Maps →
Background layers* (tile URL with `{z}`, `{x}`, `{y}`, over HTTPS; attribution; the highest zoom of the tiles;
included; default; order). Without included layers the maps show the plans only. `MAPS_START` (`imzam/settings.py`)
is where an empty map starts.

The background also helps to place the first plan: click a building corner on the aerial photo instead of typing its
coordinates.

## How positions work

- Positions are stored in WGS84 (longitude, latitude). Sizes, rotations and the alignment of plans are computed in
  metres in `MAPS_LOCAL_SRID` (default EPSG:25832, ETRS89 / UTM 32N) (`maps/geo.py`).
- **Vertically**, a position belongs to the level its location is in, by the location tree; nothing stores the level.
  Levels with the same number in different houses lie at about the same height and share one map
  (`/map/+1/` shows WH+1 and HH+1).
- **Stacked parts:** a room or area whose parts lie on top of each other (the platforms `HBB.1` below and `HBB.2`
  above) gets "parts stacked" (admin: *Location shapes*). The map then offers a switch "HBB: all / .1 / .2".
- **Shapes:** by default levels, rooms and areas are areas (polygons), storage units and containers points or
  rectangles; a type's map settings can allow others (the placing dialog then offers a choice, "New" on the map only
  lists locations whose type allows the drawn shape). **Storage units** (shelves, cabinets) as points or rectangles:
  the dialog asks for width and depth in cm (filled in with the usual size of their type); the middle handle moves
  it, the outer one turns it.
- **Snapping:** while placing, a corner of the rectangle (or the point) snaps to a corner of the rooms, areas and
  storage units around it within 12 pixels, else onto their edges; turning snaps parallel or at right angles to the
  edges nearby and to the plan's walls, within 4°. Drawing an area snaps its corners to the corners and edges of the
  others (Leaflet-Geoman). Alt while dragging: no snapping.
- **Which location types are placeable, and as what** is set in the admin, on each location type's page (section
  *Map*: placeable on the map; as point, as rectangle, as area; usual width and depth), or for all at once under *Maps → Map settings of location types*. For now
  containers (pallets, boxes) are not placed, nor the parts of storage units (compartments and drawers), which are
  where their storage unit is. A type without settings follows that rule: levels, rooms, areas and storage units, but
  no type that is another type's sublocation type. Unique items get points of their own only with
  `MAPS_PLACE_UNIQUE_ITEMS` (`imzam/settings.py`).
- Something without a position of its own is shown by the nearest location above it that has one ("is in HBB.2;
  its own position is not known"). "Position" and "On the map" appear only where there is something to show (or,
  for "Position", for whoever may place it).

### Edit mode of the map

Map editors (all staff, and whoever has `maps.edit_map`) switch the map page (`/map/`) to **Edit**: a click selects
a building part, storage unit (or unique item, if they are placed) and a bar at the bottom shows what can be done.
Areas: drag the corners, or with "Move as a whole" the area; rectangles: the middle handle moves, the outer one turns;
points: the handle. Snapping as when placing. "Save" saves it (what is on or in it moves along), "Discard" or Esc
forgets the change, "Remove position" removes it. Rectangles show their width and depth there, to change them.

**New** (point, rectangle, area) makes a position on the map first: a click for a point or rectangle, the corners for
an area. Then the bar offers the locations of this level that are placeable but have no position yet (building
parts for an area, storage units for a point or rectangle); choosing one and saving gives it the position. A
rectangle takes the usual size of the chosen location's type, unless a size was entered.

Map editors may place everything that is placeable on the map,
building parts too; others logged in see "Edit" disabled with the reason.

### Look and labels

Locations are labelled as everywhere: purpose or name, the code chip (its full code, e.g. `ATR0.2`) in the line
below. Labels do not overlap. Parents come before their parts (by depth in the location tree; the smaller first
among the same depth): a room's label pushes out its parts', not the other way round. Storage units are labelled in
their middle; an area's label stays where it was while that still fits (labels do not jump when zooming), else goes to
the free place nearest its middle that lies wholly inside its outline (better off the areas inside it). One that fits
nowhere stays in the middle if that is free, else it is hidden until one zooms in.

The map page is the map alone, below the navbar (which marks the section of each page: items, locations, map): the
levels at the left below the zoom buttons, "Edit" and "Floor plans" at the bottom right.

On a touchpad, a pinch zooms and a two-finger swipe pans. A pinch scales the map at once, as Leaflet's pinch on
touch screens: the background tiles of another zoom level load only when the fingers rest, without fading in; the
address is written at most every 300 ms (browsers limit changes of the history). The map settings of a location type (admin, on the location type's page, in
the sections *Shapes*, *Look* and *Label*) also give the **look** of its locations: line colour, fill colour, fill
opacity and line width (empty: as usual for its category), and **more style options** as JSON with Leaflet's drawing
options, e.g. `{"dashArray": "6 4", "lineJoin": "round", "fill": false}` (only `color`, `fillColor`, `weight`,
`opacity`, `fillOpacity`, `radius`, `dashArray`, `dashOffset`, `lineCap`, `lineJoin`, `fill`, `stroke`; the fields
come first when filled in); by default rooms are solid blue, areas (no walls of their own) dashed amber, as their
boundaries are loosely defined, levels a thick dark outline; every area has a white halo under its outline, so it
shows on photos, plans and other areas; the **label's first line**: a template with `{code}` (the full code), `{short}` (its own part),
`{name}`, `{purpose}` and `{title}` (purpose, else name), empty for purpose or name, `-` for no label; and the
**zoom from which labels show** (by default rooms and areas from 18, their parts from 19, shelves and cabinets from
20; empty: always); and the label's **size, colour and boldness**.

### Measuring

*Measure* (bottom right, for everyone; `map_measure.js`) measures a **distance** along a line (click its points,
the last one again to finish), an **area** with its perimeter (click its corners, the first one again to finish)
and a **radius** around a point, with the circle's area (click the centre, then a point on the circle). Clicks go
through what is drawn, so no popup opens; the points can be dragged afterwards. Areas are computed on a plane, which
at the size of a site is exact to well under a per mille. Nothing is saved: *Done* removes the measurements. The
edit mode ends measuring.

### Sharing a view

The "On the map" links lead to the level with `#p=loc:<pk>` (or `item:`): the map shows that location, or the
place it is in, highlighted with its popup open. The small map in the location window shows that popup too.

The map page keeps its view in the address: `#z=<zoom>&b=<south>,<west>,<north>,<east>`, and `&p=loc:<pk>` while a
location's popup is open. Such a link shows the same rectangle (and opens the popup); switching the level keeps it.
Switching the level does not load the page anew: the map draws the other level's data in place (the background,
the view and measurements stay; the plans shown so far stay until the new ones are loaded), and the address
changes, so the browser's back button returns to the level before. In the edit mode the level buttons load the page.
Without `z` and `b` the map shows what `p` names.

### When things move

- **Placed on the map again:** what is on or in it moves along, turned with it (the boxes on a pallet).
- **Moved to another location** (any move: dialogs, "Move here", the admin): its position, and those of what is on
  or in it, are cleared, unless the move dialog's "Mark the new place on the map" gave a new one. Then the new place
  is set and the things on it move along.
- **Building parts** keep their areas when they get another parent; that is restructuring.
- Every change is in the change log of the location or unique item ("Position on the map").

The inventory does not know the maps app: it sends `inventory.signals.moved` and renders template slots
(`inventory/slots.py`, `{% slot %}`) that the app fills (`maps/apps.py`).

## Floor plans

*Map → Floor plans* (`/map/plans/`, with `maps.manage_floorplans`, which only superusers have until it is
given), or
`manage.py import_floor_plan <file> --level -1 [--page N] [--dpi 300] [--crop l,t,r,b] [--name …] [--notes …] [--inactive]`
(`--location WH-1` gives the level by a level's code, `--location HBB.2` makes it a plan of that stacked part).

1. **Upload** a PDF, PNG, JPEG, WebP or SVG for a level number. A level can have several plans: one per house
   (WH+0 and HH+0 share level 0), or several sheets. A plan that shows only a stacked part (HBB.2) names it and is
   shown when that part is chosen. PDFs are rendered at the
   given resolution (by default 300 dpi: 8.5 mm per pixel at 1:100) **without their annotations** — notes and stamps added in a
   PDF viewer, which can carry names. The rendered plan (at most 16 000 pixels wide or high; an A1 sheet at 300 dpi
   is about 9900) is cut into tiles of 2048 pixels, WebP without metadata, which the map places side by side (they
   overlap by 2 pixels; the opacity applies to the whole plan). Rendering an A1 sheet at 300 dpi takes about
   10 seconds.
2. **Place** it with control points: click a point on the plan, then the same point on the map (the aerial photo,
   or the plans already placed) — or type its coordinates (latitude, longitude), or take a **surveyed point**
   (a place with known coordinates, e.g. a building corner: picked in the list or clicked as a green dot on the map;
   the table names it). Surveyed points are kept in the admin (*Maps → Surveyed points*: name, latitude, longitude,
   offered, order); ZAM's building corners come with the migration. Or **copy** the control points of another
   placed plan (e.g. another sheet of the same survey): they come at the same places on the page (also with another
   crop or resolution) and are then corrected by dragging; nothing is saved before "Place plan". The points show as reticles and
   can be dragged on both sides to correct them. Two points place a plan drawn to scale (shift, turn, one scale);
   more points show the largest deviation. Uneven scaling is only for distorted scans. Once placed, the map on the
   right shows the plan on top, with an opacity slider that is only for looking (the opacity on the map is saved
   below the plan).
3. **Crop** it to the drawing (once it is placed): room tables, title block (names, phone numbers) and dimension
   chains stay off the map. The crop is drawn on the whole page (rendered once at 100 dpi, at most 4000 pixels,
   next to the source and like it for staff only), with the current outline on it: draw a new rectangle (two
   opposite corners) or outline (corner by corner), copy the outline of another plan (e.g. another sheet of the same
   survey), or take the whole page. The corners can be dragged, added between two, and removed with a double click
   (also while drawing); the preview darkens what is cut off; then "Apply crop". Outside an outline the plan is
   transparent. Cropping keeps the plan where it is: the control points stay at their places on the page, including
   points dragged since placing.
   **Remove the background** (below the plan) makes the white paper transparent, so that the aerial photo shows
   through; lines keep their colour.

A plan keeps the name of its uploaded file (shown and used when downloading it) and has internal notes, e.g. where
the file came from; neither is shown on the map. The source file is visible to staff only; everyone sees the cropped image (served with `Content-Security-Policy:
sandbox`, so an uploaded SVG cannot run scripts). Each plan is a layer of its own in the layer selection:
**shown at first**, or only available there (e.g. an older survey, switched on when needed). Plans that are no longer
wanted are made inactive and stay for reference. Positions do not depend on plans: a new plan of the same level shows them where they were.

### DWG files

The app does not read DWG. Convert them first, e.g. with the ODA File Converter (free, closed source) to DXF or PDF,
or with LibreDWG (`dwg2dxf`), then print the DXF to PDF or SVG. If a survey's drawings are in real coordinates
(eastings around 6xx xxx and northings around 5 4xx xxx in UTM 32N), all its plans can be placed without manual
control points; this is not built yet.

### Survey "Bauaufnahme 02.2023"

The plans of the 2022/2023 building survey (project 2022-042, 1:100) are kept outside the repository. Haus Nord is
the Werkhaus (WH), Haus Süd und West the Haupthaus (HH). The ground floor of Haus Nord is cut at 275.40 m, that of
Haus Süd at 278.90 m: one level apart, as WH−1 and HH+0.

## Editing with QGIS

PostGIS and SpatiaLite are both readable and writable by QGIS: the tables `maps_locationshape` (areas of building
parts, in EPSG:4326) and `maps_floorplan` can be edited there, e.g. to trace many rooms at once. Changes made that
way bypass the change log.

## Permissions

| What | Needs |
|---|---|
| See the map and plans | nothing (public, as location pages) |
| Place storage units (and other types placed on the map) | `inventory.change_location` |
| Place unique items (if turned on) | `inventory.change_uniqueitem` |
| Draw levels, rooms and areas | `maps.change_building_shape` |
| Edit mode of the map: edit and move everything placed | `maps.edit_map`, or being staff |
| Floor plans: upload, crop, place, download source files (`/map/plans/`) | `maps.manage_floorplans` (for now only superusers) |

Members on the local network (ZAM-local) can place storage units; plans and building shapes are for staff.
