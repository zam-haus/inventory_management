# Label designs

Label templates (admin → Inventory → Label templates) are written in a small language. The server draws them
for each printer, dot for dot at its resolution. A Zebra gets the result as an image in ZPL; a Brother gets it
as P-touch raster data. While a template is being written, the preview beside it shows the label with real
records, and lists mistakes by line.

```
# Mobile locations, 105 × 52 mm polyester
label 105 x 52  margin 1
row  gap 3
  qr {{ qr }}  ecc Q  max 32
  column  gap 3
    text {{ location.unique_identifier }}  font mono  bold  invert  height 18
    image "ZAM Logo"
text "Eigentum Betreiberverein ZAM e.V."  font condensed  bold  center  height 4.5
```

## The rules

* **The first line gives the size:**
  * `label 105 x 52` is width × height in mm.
  * `label height 12` is a label as long as its content, for Brother tape: the height is the tape
    width, and the printer cuts after each label.
* **Then one element per line:** a keyword, its content, then options in any order. `#` starts a
  comment; commas and extra spaces are allowed.
* **Indentation:** elements indented below a `row` or `column` are laid out in it. Use spaces; in
  the admin, Tab indents by two.
* **Lengths are in mm** (`3`, `2.5`, `2.5mm`). Some sizes may also be a percentage of the row or
  column (`50%`), `fill` or `auto`.
* **Content** is text in quotes, e.g. `"Ort: {{ location.descriptive_identifier }}"`, or a variable
  alone: `{{ location.unique_identifier }}`. Texts and QR codes are [Django templates](#texts-are-django-templates).

## The label

| | |
|---|---|
| `label W x H` | fixed size, width × height in mm |
| `label height H` | as long as the content (Brother tape) |
| `margin M` | white border: `margin 1` on all sides, `margin 1 2` top and bottom, left and right, `margin 1 2 1 0` top, right, bottom, left |
| `min L`, `max L` | shortest and longest length of a label without width |
| `rotate 180` | print upside down |
| `invert` | printed inverted: the whole label in its colour on black (yellow polyester: yellow on black); QR codes come out light on dark, which the scanners read |
| `rotate 90`, `270` | laid out across, printed turned clockwise by 90° (or 270°) on labels of height × width: `label 150 x 100  rotate 90` prints on 100 × 150 mm labels (a Zebra prints at most 104 mm wide); not on tape |

The label itself lays out its elements like a column, from top to bottom.

## Layout: row and column

`row` lays its elements out from left to right; `column` from top to bottom.

* **Along a row or column**, an element takes one of these sizes:
  * what is given: `width 20` in a row, `height 8` in a column, also `50%`;
  * what its content needs (`auto`), the default for text with a `size`, QR codes, images and lines;
  * a share of what is left (`fill`), the default otherwise. Several fill elements share equally. On a
    label without width, fill means auto.
* **Text** in a row is as wide as it needs at the height it gets (shrinking if the row is too short);
  in a column, texts without a size share the height.
* **Across**, an element fills the row or column unless its width or height is given; the row or
  column then places it by its `align`. **`auto`** across (`width auto` in a column, `height auto` in
  a row) makes it only as large as its content: a price tag frame or an inverted text below a long name
  is then as wide as the price, not as the name.
* **A row or column that shows nothing** is left out, frame and all, as if it were not there: all its
  texts came out as nothing at all and it holds nothing else but spaces. So a price frame disappears
  for items without a price if its texts are `"{% if item.sale_price is not None %}…{% endif %}"`.
  Blanks keep their room: with `{% else %}{{ ''|ljust:10 }}` the frame stays, empty and about as wide
  as a price. A frame around just spaces stays too.
* **`at X Y`** places an element X mm from the left and Y mm from the top of its row or column (or of
  the label), outside the flow. It takes its `width` and `height`, else what its content needs.
* **`space`** takes room: `space 2`, or `space` alone to share what is left (to centre something,
  put a space before and after it).

| Option | Row | Column |
|---|---|---|
| `gap G` | space between the elements | space between the elements |
| `align …` | across: `top`, `middle` (default), `bottom` | across: `left`, `center` (default), `right` |
| `justify …` | along, if there is room left: `start` (default), `center`, `end` | the same |
| `padding P` | white inside, 1, 2 or 4 lengths like `margin` | the same |
| `border B` | a frame of this thickness | the same |
| `shape …` | of the frame: `rect` (default), `round` (`radius R`), `bulge` (left and right side arched outwards like a price tag; `bulge D` how far, default a fifth of the height) | the same |
| `width`, `height` | its own size within its parent | its own size within its parent |

Every element, and rows and columns too, takes **`margin`**: white around its content, inside the room the
element takes, like CSS. `margin 1` adds 1 mm on all sides; `margin 1 2` adds 1 mm at top and bottom and
2 mm left and right; `margin 1 2 1 0` gives top, right, bottom and left. A given `width` or `height` is the
content's: `image "Logo"  height 6  margin 1` takes 8 mm. (`padding` of a row or column is white inside its
border, around all its elements.)

## Elements

### text

`text "Fixed text"` or `text {{ variable }}`, also both: `text "{{ item.measurement_unit.short }} / Stück"`.

| Option | |
|---|---|
| `size S` | font size in mm (about 1.4 × the height of capital letters). Without it the text fits its box. |
| `fit` | fit the box, with `size` as the largest size |
| `lines N` | wrap into at most N lines (default 1), between words, a smaller size rather than a word split; text that does not fit ends with "…" |
| `font F` | `sans` (Raleway, as in the ZAMid lettering), `mono` (Roboto Mono, the ZAMid's ID), `condensed` (Roboto Condensed, narrow like Zebra's built-in font), `ocr` (OCR-B, readable by people and machines) |
| `bold`, `weight W` | weight 100 to 900 (bold is 700); OCR-B has one weight only |
| `left`, `center`, `right` | justification (default left; inverted text centred) |
| `top`, `middle`, `bottom` | vertical position in its box (default middle) |
| `invert` | white on black; with `padding P` around the text (default an eighth of the height) |
| `rotate 90`, `180`, `270` | turned clockwise; in a row a text turned 270° reads from bottom to top |

### qr

`qr {{ qr }}` is a QR code with whole printer dots per module, so it stays sharp.

| Option | |
|---|---|
| `size S` | edge length in mm, or `fill` (as large as fits, the default) |
| `max M` | at most this large |
| `ecc L`, `M`, `Q`, `H` | error correction (default L: smallest code) |
| `quiet N` | white border in modules (default 2) |
| `left` … `bottom` | position in its box (default centred) |

If the QR code cannot get at least two dots per module, the label is refused as too small.

### barcode

`barcode {{ label_id.code }}` is a Code 128 barcode (letters, digits and signs; set C for an even number of digits),
with whole printer dots per bar, at least 0.13 mm (2 dots at 360 dpi, 1 at 180 or 203 dpi), centred with its quiet
zone. It fills its box: the bars as long as the box is high.

| Option | |
|---|---|
| `rotate 90`, `270` | across its row: on tape across the tape, the bars along it (cable wraps: the bars run round the cable, so it scans along the cable from every side); 180 and 270 read from the other end |
| `quiet N` | white before and after the bars in modules (default 10); on tape the unprinted edges add to it |

If the bars cannot get 0.13 mm, the label is refused as too small. The navbar's scanner opens what a scanned
label ID's Code 128 belongs to, as a label's QR code does.

### list

`list {{ contents }}` lists what is at a location, one entry per line: first the locations in it (a pallet's
cartons) with their code, then items with their amount right-aligned in a column of its own ("12 Stk", "~5 Stk";
none for quick items) and unique items with a bullet there and their label ID right after the name in bold monospace and, where the
owners differ, whose they are if not the ZAM's, on a line of their own below the name ("Fremdeigentum: Erika"; one
owner: `owner`, said once). It fills what is left of its row or column. **What does not fit goes on on further
labels:** the whole design is drawn again for the next entries, so a heading with the QR code repeats; `page` and
`pages` number the labels (`"{% if pages > 1 %}{{ page }}/{{ pages }}{% endif %}"`), 1 and 1 on a label without
more. At most 20 labels; one list per design.

| Option | |
|---|---|
| `size S` | font size in mm (default 3) |
| `lines N` | a long name wraps into at most N lines (default 1), the last cut short with "…" |
| `font F`, `bold`, `weight W` | as for text |
| `gap G` | space between the entries (default a sixth of a line) |

In previews all labels show one below the other.

### image

`image "ZAM Logo"` shows a label image (admin → Label printing → Label images) by its name. The original
is cropped there, scaled here to fit the element's box while keeping its proportions, and turned black
and white for the printer.

| Option | |
|---|---|
| `width`, `height` | its box; without them it is as large as its row or column allows |
| `threshold T` | black where darker than T, 1 to 254 (default 128) |
| `dither` | shades as dot patterns, for photos and grey logos |
| `invert` | black and white swapped |
| `rotate 90`, `180`, `270` | turned clockwise |
| `left` … `bottom` | position in its box (default centred) |

### box, line, arrow

* `box` is a black rectangle filling its box; `box border 0.5` is just the frame.
* `line` is a line across its row or column, upright in a row, flat in a column. `thickness T`
  defaults to 0.25 mm, at least one dot.
* `arrow up` (or `down`, `left`, `right`) is a filled triangle pointing that way, e.g. to say which
  side of a shelf a label is for; `arrow up  border 0.35` is just its outline (e.g. to colour in by hand the
  one a label is for).

## Texts are Django templates

The content of `text` and `qr` is a [Django template](https://docs.djangoproject.com/en/stable/ref/templates/language/),
rendered with the label's subject: `{{ location.name }}` shows a property, filters change it
(`{{ location.name|upper }}`, `{{ item.sale_price|floatformat:2 }}`), and tags decide
(`"{% if location.purpose %}{{ location.purpose }}{% else %}–{% endif %}"`). Any field or property of the
objects may be used, also along relations: `{{ location.parent_location.name }}`.

| Locations | Items | Label IDs |
|---|---|---|
| `location` the location | `item` the item | `label_id` the label ID, as printed: K7R-4XD |
| `location.title` what it is called first: its purpose, else its name | `item.name` | `label_id.code|slice:":3"` K7R, `label_id.code|slice:"3:"` 4XD |
| `location.unique_identifier` WH-1.R303.a | `item.sale_price|floatformat:2` 0,15 (empty if not for sale) | `label_id.target` what it belongs to |
| `location.name` | `item.measurement_unit.short` Stk | |
| `location.descriptive_identifier` where it is, with codes | | |
| `location.locatable_identifier` code within its area | `location` where it is stored (the first location; may be none) | |
| `location.purpose` | `label_id` its label ID as printed | |
| `contents` for `list`: what is right at the location (numbers sorted by value) | | |
| `responsible` the teams responsible for it, also from a location above it | | |
| `owned` whether anything right at it has an owner (items or unique items, not just locations in it) | | |
| `owner` whose it all is, if one owner's other than the ZAM: the first name; empty for the ZAM's | | |
| `owners_differ` whether it belongs to different owners (then `contents` marks the unique items) | | |
| `qr` the code via the label host | `qr` its label ID and the location's code (`…/K7R4XD/WH-1.R303.A`), leading to the item there | `qr` the ID via the label host |

Locations on labels follow the rule of the pages ([how locations are shown](locations.md#how-locations-are-shown)):
what it is called first, `location.title`, its code after or below it, inverted in monospace
(`font mono  bold  invert`, with `width auto` in a column: as wide as the code). A text that comes out as nothing
at all takes no room and draws nothing, not even its inverted box (e.g. the code of an item stored nowhere).

Templates for **unique items** have `unique_item` (e.g. `unique_item.name`, its own name if it has one;
`unique_item.owner_first_name_display`, its owner's
first name if it is not the ZAM's; `unique_item.has_owner`), `item` (what it is), `location`, `label_id` (its
label ID) and `qr` (the ID via the label host).

All labels also have `label_id_name`, what label IDs are called (ZAMid), and `page` and `pages` (see
[list](#list)). The template page lists the variables too.

* A variable alone needs no quotes; anything more is quoted. Quotes inside a template take the other kind:
  `text '{{ location.name|default:"–" }}'`.
* What has no value prints as nothing. The preview names such variables for the record shown ("There is no
  “location.nmae”, at least not for this record"). Mistakes in the template's syntax are listed like other
  mistakes, and a template with mistakes is not printed.
* An empty field that is stored as nothing (None) prints as "None"; `|default_if_none:""` leaves it out.
* Nothing is escaped: a label is not HTML.
* Underscores in a row (`__________`) print as one unbroken line to write on, whatever the font: the generated
  item templates show one for an item without a name (`{{ item.name|default:'_______________' }}`).

A template also sets the **print quality** its labels are printed in (draft, standard, high), on its admin
page.

## Where templates are offered

A template is designed for a label size and prints only on labels of that size, on any printer (there is
no resolution in a template):
* Zebra labels of its width and height, within a millimetre or up to 2.5 mm larger, drawn to the labels' size (a
  100 × 150 mm template prints on 101.6 × 152.4 mm labels; labels of unknown size: none);
* Brother tape as wide as its height. Endless tape takes templates of any length; tape with a
  label length (its label material's height) only templates of that length;
* and only where its QR codes come out big enough to scan at the printer's resolution, tried with a
  made-up record (every property two words of lorem ipsum): 9 mm tape templates, for example, are not
  offered on the E550W (180 dpi).

A template may also say which labels of its size it is for (admin: **Labels**):
* a **label material**: only that label material;
* else **material** (e.g. Polyester; empty: any) and **print and background colour** as the label material
  names them (default black on white; empty: any). Label material without colours counts as black on white;
  a Zebra prints in the colour of its loaded ribbon.

Label material on hand offers the fitting active templates of the kind being printed; the template decides, so label printing
needs nothing of the inventory's templates. Deactivated templates are neither offered nor printed.

Which of them are meant for a subject, and in which order, say the template's **rules**: conditions with the
same variables as in `{% if %}`, each with a print priority ([label printing](label-printing.md#label-templates-and-images)).
A unique item is also offered the label ID templates, by its label ID.

## Examples

A location label on 12 mm tape, as long as the path needs:

```
label height 12  margin 0.5
row  gap 1
  qr {{ qr }}
  column  gap 0.5
    text {{ location.unique_identifier }}  font mono  bold  invert
    text {{ location.descriptive_identifier }}  font condensed
```

A label ID, like the Brother design:

```
label 70 x 32  margin 1.5
row  gap 1.5
  text {{ label_id_name }}  rotate 270  font sans  weight 800
  qr {{ qr }}
  column
    text {{ label_id.code|slice:":3" }}  font mono  bold  center
    line  thickness 0.8  width 40%
    text {{ label_id.code|slice:"3:" }}  font mono  bold  center
```

A price tag for bulk items on 24 mm tape (the former template "Preisschild"): the name, below it the price
and the QR code.

```
label height 24  margin 0.5
text {{ item.name }}  font condensed  bold  height 30%
row  gap 2  margin 0.5 0 0 0
  row  border 0.5  shape bulge  padding 0.3 0  width auto
    text "€ {{ item.sale_price|floatformat:2 }}"  font condensed  bold
    text "/ {{ item.measurement_unit.short }}"  font condensed  height 40%  margin 0 0 0 1  bottom
  qr {{ qr }}  ecc M
```

A bulk item on 57 × 32 mm labels (template "Artikel"): the price in a price tag frame
as wide as the price, below the name; for items without a price the frame is empty.

```
label 57 x 32  margin 1.5
row  gap 2
  column  gap 0.5  align left
    text {{ item.name }}  bold  lines 3  height 50%
    row  border 0.4  shape bulge  padding 0.2 0  width auto  height 25%
      text "{% if item.sale_price is not None %}€ {{ item.sale_price|floatformat:2 }}{% else %}{{ ''|ljust:10 }}{% endif %}"  font condensed  bold
      text "{% if item.sale_price is not None %}/ {{ item.measurement_unit.short }}{% endif %}"  font condensed  height 45%  margin 0 0 0 0.5  bottom
    text "{{ label_id }}  {{ location.unique_identifier }}"  font mono  height 15%  bottom
  qr {{ qr }}  max 22.8
```

A fixed shelf label with an arrow pointing up to the shelf:

```
label 70 x 32  margin 1
row  gap 2
  qr {{ qr }}  ecc Q
  column
    space
    arrow up  width 14  height 6
    space 1
    text {{ location.unique_identifier }}  font mono  bold  invert  height 11
    space
text {{ location.descriptive_identifier }}  font condensed  center  height 3.5
```

The contents of a box, carton or pallet on 100 × 150 mm paper (template "Inhalt", on permanent or removable paper;
across as "Inhalt, quer" with `rotate 90`): the code with the title beside it, the date below; who is
responsible, and whose it is if it is all one owner's (else the list marks it); then the list, which goes on on
further labels if it does not fit. `height auto` keeps those lines only as high as they need, so the list gets the
rest:

```
# Changing contents of boxes, 100 × 150 mm removable paper: QR code, the code with the title right of it, below them
# the date; then who is responsible, and whose it is if it is all one owner's (else the list says it at each unique
# item that is not the ZAM's); below that what is right at the location; what does not fit goes on on further labels
label 100 x 150  margin 2.5
row  gap 3  height 22
  qr {{ qr }}  ecc M
  column  gap 1.5  align left  justify center
    row  gap 2  height 9
      text {{ location.unique_identifier }}  font mono  bold  invert  width auto
      text {{ location.title }}  font condensed  bold
    text "Inhalt, Stand {% now 'd.m.Y' %}{% if pages > 1 %} · {{ page }}/{{ pages }}{% endif %}"  font condensed  size 3.8
column  gap 0.8  align left  height auto  margin 2 0 0 0
  text "{% if responsible %}Zuständig: {{ responsible }}{% endif %}"  font condensed  size 3.8  lines 2
  text "{% if owned and not owners_differ %}Eigentum: {{ owner|default:'Betreiberverein ZAM e.V.' }}{% endif %}"  font condensed  size 3.8
line  thickness 0.3  margin 2 0 1.5 0
list {{ contents }}  font condensed  size 3.8  lines 2
```
