"""
The labels to start with, from the inventory as it was (location label templates in ZPL):

* the permission to print for the local group;
* label stock: Brother P-touch tapes from Brother's tape selector (catalog/brother_tapes.json) and Zebra labels in
  the sizes of the ZPL templates;
* the ZPL templates described anew in the label description language (docs/label-designs.md), their logo as the
  label image "ZAM Logo"; templates it does not know get a plain design with their ZPL as comments;
* label templates for locations, bulk items and unique items (ZAMid) for the Zebra labels in use and every
  Brother tape width (templates a printer cannot print are not offered on it), and price tags.
"""
import io
import json
import re
from pathlib import Path

from django.conf import settings
from django.core.files.base import ContentFile
from django.db import migrations


def grant_print_label_to_local_group(apps, schema_editor):
    # Members recognized on the local network may print labels from the inventory pages.
    group, _ = apps.get_model("auth", "Group").objects.get_or_create(
        name=getattr(settings, "LOCAL_GROUP_NAME", "ZAM-local"))
    content_type, _ = apps.get_model("contenttypes", "ContentType").objects.get_or_create(
        app_label="label_printing", model="printjob")
    permission, _ = apps.get_model("auth", "Permission").objects.get_or_create(
        content_type=content_type, codename="print_label", defaults={"name": "Can print labels"})
    group.permissions.add(permission)


CATALOG = Path(__file__).resolve().parent.parent / "catalog" / "brother_tapes.json"


def brother_tapes(apps, schema_editor):
    LabelStock = apps.get_model("label_printing", "LabelStock")
    db = LabelStock.objects.using(schema_editor.connection.alias)
    tapes = json.loads(CATALOG.read_text(encoding="utf-8"))["tapes"]
    for tape in tapes:
        description = "\n".join(part for part in (tape["kind"] + (" (Pro Tape)" if tape["pro"] else ""),
                                                  tape["description"]) if part)
        db.update_or_create(code=tape["code"], defaults=dict(
            language="ptouch", name=tape["product"], description=description, tape_mm=tape["tape_mm"],
            background_color=tape["background_color"], print_color=tape["print_color"],
            length_m=tape["length_m"], url=tape["url"],
        ))


# The ZAM's labels in these sizes: (printing method, ribbon, material).
KNOWN_ZEBRA_LABELS = {
    (70, 32): ("transfer", "wax", "Papier"),
    (60, 30): ("transfer", "wax", "Papier"),
    (152, 102): ("transfer", "wax", "Papier"),
    (105, 52): ("transfer", "resin", "Polyester"),
}


# The ZAM's labels in these sizes: (printing method, ribbon, material).
KNOWN_ZEBRA_LABELS = {
    (70, 32): ("transfer", "wax", "Papier"),
    (60, 30): ("transfer", "wax", "Papier"),
    (152, 102): ("transfer", "wax", "Papier"),
    (105, 52): ("transfer", "resin", "Polyester"),
}


def zebra_labels(apps, templates):
    """One stock per size of the ZPL templates; printing method and material where known."""
    LabelStock = apps.get_model("label_printing", "LabelStock")
    sizes = {}
    for template in sorted(templates, key=lambda template: template.name):
        sizes.setdefault((template.label_width, template.label_height), []).append(template.name)
    for (width, height), names in sizes.items():
        method, ribbon, material = KNOWN_ZEBRA_LABELS.get((width, height), ("", "", ""))
        description = f"Aus den ZPL-Vorlagen {', '.join(f'„{name}“' for name in names)} angelegt."
        if not method:
            description += " Druckverfahren (Thermodirekt oder Thermotransfer mit Farbband) und Material bitte ergänzen."
        LabelStock.objects.create(
            language="zpl", name=f"Etikett {width:g} × {height:g} mm{f' {material}' if material else ''}",
            width_mm=round(width), height_mm=round(height), method=method, ribbon=ribbon, material=material,
            description=description)


# The ZPL templates in use (by name), described anew: (new name, description)
SHELF = """# Fixed locations, 70 × 32 mm paper{note}
label 70 x 32  margin 1
line  thickness 0.15
row  gap 2
  qr {{qr}}  ecc Q
  column
    space{above}
    text {{code}}  font mono  bold  invert  height 11{below}
    space
text {{path}}  font condensed  center  height 3.5
"""
ARROW_UP = "\n    arrow up  width 14  height 6\n    space 1"
ARROW_DOWN = "\n    space 1\n    arrow down  width 14  height 6"
ZPL_DESIGNS = {
    "70x32 static": ("Fester Standort", SHELF.format(note="", above="", below="")),
    "70x32 static up": ("Fester Standort, Pfeil hoch",
                        SHELF.format(note="; arrow up to the shelf", above=ARROW_UP, below="")),
    "70x32 static down": ("Fester Standort, Pfeil runter",
                          SHELF.format(note="; arrow down to the shelf", above="", below=ARROW_DOWN)),
    "60x30 mobile": ("Mobil, mit Logo und Eigentum", """# Mobile locations, 60 × 30 mm paper
label 60 x 30  margin 1
row  gap 2
  qr {qr}  ecc Q
  column  gap 1.5
    text {code}  font mono  bold  invert  height 11
    image "ZAM Logo"
text "Eigentum Betreiberverein Makerspace+ für Erlangen e.V."  font condensed  center  height 2.6
"""),
    "105x52 mobile": ("Mobil, mit Logo und Eigentum", """# Mobile locations, 105 × 52 mm polyester
label 105 x 52  margin 1
row  gap 3
  qr {qr}  ecc Q  max 32
  column  gap 4
    text {code}  font condensed  bold  invert  height 18
    image "ZAM Logo" height 20
text "Eigentum Betreiberverein ZAM e.V."  font condensed  bold  center  height 4.5
"""),
}

FALLBACK = """# Converted from a ZPL template: check it. The ZPL is kept below as comments.
label {width} x {height}  margin 1
row  gap 2
  qr {{qr}}
  column  gap 1
    text {{code}}  font mono  bold  invert
    text {{path}}  font condensed  lines 2
"""
GFA = re.compile(r"\^GFA,\d+,(\d+),(\d+),([^^~]*)")
SMALL = {chr(ord("G") + index): index + 1 for index in range(19)}
LARGE = {chr(ord("g") + index): (index + 1) * 20 for index in range(20)}


def decode(data, total, bytes_per_row):
    """A ^GFA graphic's bytes from ASCII hex, also with Zebra's ASCII compression (as in these templates)."""
    rows, row, previous, count = [], "", "", 0
    width = bytes_per_row * 2
    for char in re.sub(r"\s", "", data):
        if char in SMALL or char in LARGE:
            count += SMALL.get(char) or LARGE[char]
            continue
        if char in ",!:":
            if char == ":":
                rows.append(previous)
            else:
                rows.append((row + ("0" if char == "," else "F") * width)[:width])
                previous = rows[-1]
            row, count = "", 0
            continue
        row += char * (count or 1)
        count = 0
        while len(row) >= width:
            rows.append(row[:width])
            previous, row = rows[-1], row[width:]
    if row:
        rows.append(row.ljust(width, "0"))
    return bytes.fromhex("".join(rows))[:total].ljust(total, b"\x00")


def logo_png(templates):
    """The largest graphic in the templates (the ZAM logo) as a PNG, or None."""
    from PIL import Image

    found = [match for template in templates for match in GFA.finditer(template.zpl_template)]
    if not found:
        return None
    match = max(found, key=lambda match: int(match.group(1)))
    total, bytes_per_row = int(match.group(1)), int(match.group(2))
    raw = decode(match.group(3), total, bytes_per_row)
    image = Image.frombytes("1", (bytes_per_row * 8, total // bytes_per_row), bytes(byte ^ 0xFF for byte in raw))
    out = io.BytesIO()
    image.save(out, format="PNG")
    return out.getvalue()


def as_comment(zpl):
    zpl = GFA.sub(lambda match: match.group(0)[:20] + "…", zpl)
    return "".join(f"# {line}\n" for line in zpl.splitlines() if line.strip())



def mm(value):
    return f"{value:.2f}".rstrip("0").rstrip(".")


def zamid_tape(tape):
    return f"""# ZAMid on {tape} mm tape, like the Brother design: the name turned, the QR code, the ID in two lines
label height {tape}  margin 1
row  gap {mm(tape * 0.08)}
  text {{idname}}  rotate 270  font sans  weight 800
  qr {{qr}}  quiet 1
  column
    text {{id1}}  font mono  bold  center
    line  thickness {mm(max(0.2, tape * 0.025))}  width {mm(tape * 0.22)}
    text {{id2}}  font mono  bold  center
"""


def zamid_card(width, height):
    return f"""# ZAMid on {width} × {height} mm labels, like the Brother design
label {width} x {height}  margin 1.5
row  gap 1.5
  text {{idname}}  rotate 270  font sans  weight 800
  qr {{qr}}  quiet 1
  column
    text {{id1}}  font mono  bold  center
    line  thickness {mm(height * 0.025)}  width {mm(height * 0.3)}
    text {{id2}}  font mono  bold  center
"""


def plain_tape(tape):
    return f"""# ZAMid on {tape} mm tape: QR code and ID
label height {tape}  margin 1
row  gap {mm(tape * 0.1)}
  qr {{qr}}  quiet 1
  text {{id}}  font mono  bold  height 60%
"""


def plain_card(width, height):
    return f"""# ZAMid on {width} × {height} mm labels: QR code and ID
label {width} x {height}  margin 1.5
row  gap 2
  qr {{qr}}
  column
    text {{idname}}  height 30%  bottom
    text {{id}}  font mono  bold  height 45%
    space
"""


def location_tape(tape):
    return f"""# Locations on {tape} mm tape, as long as the path needs: QR code, code and path
label height {tape}  margin 1 0.5
row  gap 1
  qr {{qr}}  quiet 1
  column  gap 0.5
    text {{code}}  font mono  bold  invert
    text {{path}}  font condensed
"""


def location_card(width, height):
    return f"""# Locations on {width} × {height} mm labels: QR code, code and path
label {width} x {height}  margin 1.5
row  gap 2
  qr {{qr}}  max {mm(width * 0.45)}
  column  gap 1
    text {{code}}  font mono  bold  invert  height 40%
    text {{path}}  font condensed  lines 4
"""


def item_tape(tape):
    return f"""# Bulk items on {tape} mm tape, as long as the name needs: QR code, name, price, ID and location
label height {tape}  margin 1 0.5
row  gap 1
  qr {{qr}}  quiet 1
  column  align left
    text {{name}}  bold  height 55%
    text "{{price}}  {{id}} {{location}}"  height 40%  bottom
"""


def item_card(width, height):
    return f"""# Bulk items on {width} × {height} mm labels: name, price, ID and location, QR code
label {width} x {height}  margin 1.5
row  gap 2
  column  gap 0.5
    text {{name}}  bold  lines 3  height 50%
    text {{price}}  bold  height 25%
    text "{{id}}  {{location}}"  font mono  height 15%  bottom
  qr {{qr}}  max {mm(width * 0.4)}
"""


PRICE_TAGS = [
    ("""# Price tag for bulk items, 60 × 30 mm: name, price, QR code
label 60 x 30  margin 1.5
text {name}  font condensed  bold  lines 2  height 8
row  gap 2  margin 1 0 0 0
  row  border 0.5  shape bulge  padding 0.5 0  justify center
    text "€ {amount}"  font condensed  bold
    text "/ {unit}"  font condensed  size 3.5  margin 0 0 1.5 1  bottom
  qr {qr}  ecc M
"""),
    ("""# Price tag for bulk items on 12 mm tape, as long as the name needs: name, price, QR code
label height 12  margin 0.3
row  gap 1
  text {name}  font condensed  bold  height 55%
  row  border 0.4  shape bulge  padding 0.2 0
    text "€ {amount}"  font condensed  bold
    text "/ {unit}"  font condensed  height 45%  margin 0 0 0 0.5  bottom
  qr {qr}  quiet 1
"""),
    ("""# Price tag for bulk items on 18 mm tape, as long as the name needs: the name, below it price and QR code
label height 18  margin 0.5
text {name}  font condensed  bold  height 30%
row  gap 2  margin 0.5 0 0 0
  row  border 0.5  shape bulge  padding 0.3 0  width auto
    text "€ {amount}"  font condensed  bold
    text "/ {unit}"  font condensed  height 40%  margin 0 0 0 1  bottom
  qr {qr}  ecc M
"""),
    ("""# Price tag for bulk items on 24 mm tape, as long as the name needs: the name, below it price and QR code
label height 24  margin 0.5
text {name}  font condensed  bold  height 30%
row  gap 2  margin 0.5 0 0 0
  row  border 0.5  shape bulge  padding 0.3 0  width auto
    text "€ {amount}"  font condensed  bold
    text "/ {unit}"  font condensed  height 40%  margin 0 0 0 1  bottom
  qr {qr}  ecc M
"""),
]


TAPES = [9, 12, 18, 24, 36]
CARDS = [(57, 32), (60, 30), (70, 32), (105, 52)]


def new_templates():
    """[(name, subject type, description)]"""
    found = []
    for width, height in CARDS:
        found += [("QR-Code, Kennung und Ort", "location", location_card(width, height)),
                  ("Name, Preis und QR-Code", "item", item_card(width, height)),
                  ("ZAMid", "labelid", zamid_card(width, height)),
                  ("ZAMid: QR + ID", "labelid", plain_card(width, height))]
    for tape in TAPES:
        found += [("QR-Code, Kennung und Ort", "location", location_tape(tape)),
                  ("Name, Preis und QR-Code", "item", item_tape(tape)),
                  ("ZAMid", "labelid", zamid_tape(tape)),
                  ("ZAMid: QR + ID", "labelid", plain_tape(tape))]
    return found + [("Preisschild", "item", description) for description in PRICE_TAGS]


def size_of(description):
    size = re.search(r"^label (?:height (\d+)|(\d+) x (\d+))", description, re.M)
    return (None, float(size.group(1))) if size.group(1) else (float(size.group(2)), float(size.group(3)))


def labels_to_start_with(apps, schema_editor):
    Template = apps.get_model("inventory", "LocationLabelTemplate")
    LabelImage = apps.get_model("label_printing", "LabelImage")
    templates = list(Template.objects.all())
    png = logo_png(templates)
    if png:
        logo = LabelImage(name="ZAM Logo")
        logo.image.save("zam-logo.png", ContentFile(png), save=False)
        logo.save()
    for template in templates:
        if template.name in ZPL_DESIGNS:
            template.name, template.description = ZPL_DESIGNS[template.name]
        else:
            template.description = (FALLBACK.format(width=template.label_width or 57, height=template.label_height or 32)
                                    + "\n" + as_comment(template.zpl_template))
        template.save()
    zebra_labels(apps, templates)
    for name, subject_type, description in new_templates():
        width, height = size_of(description)
        Template.objects.create(name=name, subject_type=subject_type, description=description, label_width=width,
                                label_height=height)


def back(apps, schema_editor):
    """Going back: without the templates made here; sizes the integer fields of before can hold."""
    Template = apps.get_model("inventory", "LocationLabelTemplate")
    made = Template.objects.filter(name__in={name for name, _kind, _description in new_templates()})
    ids = list(made.values_list("pk", flat=True))
    apps.get_model("inventory", "LocationType").objects.filter(default_label_template_id__in=ids).update(
        default_label_template=None)
    apps.get_model("inventory", "Location").objects.filter(label_template_id__in=ids).update(label_template=None)
    made._raw_delete(schema_editor.connection.alias)  # the label stock and media linking them go with label_printing
    Template.objects.filter(label_width__isnull=True).update(label_width=0)
    Template.objects.filter(label_height__isnull=True).update(label_height=0)


class Migration(migrations.Migration):
    dependencies = [
        ("label_printing", "0001_initial"),
        ("accounts", "0002_zam_local_group"),
        ("inventory", "0042_label_designs"),
    ]

    operations = [
        migrations.RunPython(grant_print_label_to_local_group, migrations.RunPython.noop),
        migrations.RunPython(brother_tapes, migrations.RunPython.noop),
        migrations.RunPython(labels_to_start_with, back),
    ]
