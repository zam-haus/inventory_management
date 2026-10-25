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
    text {{ location.unique_identifier }}  font condensed  bold  invert  height 18
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
  side of a shelf a label is for.

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
| `qr` the code via the label host | `qr` its label ID and the location's code (`…/K7R4XD/WH-1.R303.A`), leading to the item there | `qr` the ID via the label host |

Locations on labels follow the rule of the pages ([how locations are shown](locations.md#how-locations-are-shown)):
what it is called first, `location.title`, its code after or below it, inverted in monospace
(`font mono  bold  invert`, with `width auto` in a column: as wide as the code). A text that comes out as nothing
at all takes no room and draws nothing, not even its inverted box (e.g. the code of an item stored nowhere).

Templates for **unique items** have `unique_item` (e.g. `unique_item.owner_first_name_display`, its owner's
first name if it is not the ZAM's; `unique_item.has_owner`), `item` (what it is), `location`, `label_id` (its
label ID) and `qr` (the ID via the label host).

All labels also have `label_id_name`, what label IDs are called (ZAMid). The template page lists the variables
too.

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
* Zebra labels of its width and height, within a millimetre (labels of unknown size: none);
* Brother tape as wide as its height. Endless tape takes templates of any length; a medium with a
  label length only templates of that length;
* and only where its QR codes come out big enough to scan at the printer's resolution, tried with a
  made-up record (every property two words of lorem ipsum): 9 mm tape templates, for example, are not
  offered on the E550W (180 dpi).

A template may also say which labels of its size it is for (admin: **Labels**):
* a **label stock**: only media of exactly that stock;
* else **material** (e.g. Polyester; empty: any) and **print and background colour** as label stock names
  them (default black on white; empty: any). Label stock without colours (Zebra labels) and media without
  label stock count as black on white; media without label stock have no known material, so templates that
  name one are not offered on them.

Media offer the fitting active templates of the kind being printed; the template decides, so label printing
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

A price tag for bulk items on 24 mm tape (template "Preisschild Band 24 mm"): the name, below it the price
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

A bulk item on 57 × 32 mm labels (template "Name, Preis und QR-Code"): the price in a price tag frame
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
