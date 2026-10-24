import io
import re

from django.core.files.base import ContentFile
from django.db import migrations, models

# The ZPL templates in use, described anew (docs/label-designs.md).
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
DESIGNS = {
    "70x32 static": SHELF.format(note="", above="", below=""),
    "70x32 static up": SHELF.format(note="; arrow up to the shelf", above=ARROW_UP, below=""),
    "70x32 static down": SHELF.format(note="; arrow down to the shelf", above="", below=ARROW_DOWN),
    "60x30 mobile": """# Mobile locations, 60 × 30 mm paper
label 60 x 30  margin 1
row  gap 2
  qr {qr}  ecc Q
  column  gap 1.5
    text {code}  font mono  bold  invert  height 11
    image "ZAM Logo"
text "Eigentum Betreiberverein Makerspace+ für Erlangen e.V."  font condensed  center  height 2.6
""",
    "105x52 mobile": """# Mobile locations, 105 × 52 mm polyester
label 105 x 52  margin 1
row  gap 3
  qr {qr}  ecc Q  max 32
  column  gap 3
    text {code}  font condensed  bold  invert  height 18
    image "ZAM Logo"
text "Eigentum Betreiberverein ZAM e.V."  font condensed  bold  center  height 4.5
""",
}
ZAMID = """# Label IDs, like the Brother design
label {width} x {height}  margin 1.5
row  gap 1.5
  text {{idname}}  rotate 270  font sans  weight 800
  qr {{qr}}
  column
    text {{id1}}  font mono  bold  center
    line  thickness {line}  width 40%
    text {{id2}}  font mono  bold  center
"""
NEW = [
    ("ZAMid 70x32", "labelid", ZAMID.format(width=70, height=32, line=0.8)),
    ("ZAMid 60x30", "labelid", ZAMID.format(width=60, height=30, line=0.8)),
    ("ZAMid 105x52", "labelid", ZAMID.format(width=105, height=52, line=1.2)),
    ("Standort Band 12 mm", "location", """# Locations on 12 mm tape, as long as the path needs
label height 12  margin 0.5
row  gap 1
  qr {qr}
  column  gap 0.5
    text {code}  font mono  bold  invert
    text {path}  font condensed
"""),
]
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


def convert(apps, schema_editor):
    Template = apps.get_model("inventory", "LocationLabelTemplate")
    LabelImage = apps.get_model("label_printing", "LabelImage")
    templates = list(Template.objects.all())
    png = logo_png(templates)
    if png and not LabelImage.objects.filter(name="ZAM Logo").exists():
        logo = LabelImage(name="ZAM Logo")
        logo.image.save("zam-logo.png", ContentFile(png), save=False)
        logo.save()
    for template in templates:
        if template.name in DESIGNS:
            template.description = DESIGNS[template.name]
        else:
            template.description = (FALLBACK.format(width=template.label_width or 57, height=template.label_height or 32)
                                    + "\n" + as_comment(template.zpl_template))
        template.save()
    for name, subject_type, description in NEW:
        size = re.match(r"(?:#.*\n)*label (?:height (\d+)|(\d+) x (\d+))", description)
        width, height = (None, float(size.group(1))) if size.group(1) else (float(size.group(2)), float(size.group(3)))
        Template.objects.get_or_create(name=name, defaults={
            "subject_type": subject_type, "description": description, "label_width": width, "label_height": height})


def delete_templates(apps, schema_editor, templates):
    """By ids and without Django's cascade: rolled back across apps, the related models may be of an older state."""
    ids = list(templates.values_list("pk", flat=True))
    apps.get_model("inventory", "LocationType").objects.filter(default_label_template_id__in=ids).update(
        default_label_template=None)
    apps.get_model("inventory", "Location").objects.filter(label_template_id__in=ids).update(label_template=None)
    for model in ("LabelStock", "LabelMedium"):
        for field in apps.get_model("label_printing", model)._meta.many_to_many:
            if field.related_model._meta.model_name == "locationlabeltemplate":
                field.remote_field.through.objects.filter(locationlabeltemplate_id__in=ids).delete()
    templates._raw_delete(schema_editor.connection.alias)


def back(apps, schema_editor):
    """Going back: without the templates made here; sizes the integer fields of before can hold."""
    Template = apps.get_model("inventory", "LocationLabelTemplate")
    delete_templates(apps, schema_editor, Template.objects.filter(name__in=[name for name, _kind, _description in NEW]))
    Template.objects.filter(label_width__isnull=True).update(label_width=0)
    Template.objects.filter(label_height__isnull=True).update(label_height=0)


class Migration(migrations.Migration):
    """Label images; the label templates' ZPL described in the label description language, their logo as a
    label image; label ID and tape templates."""

    dependencies = [
        ("inventory", "0043_label_designs"),
        ("label_printing", "0007_medium_offset_help"),
    ]

    operations = [
        migrations.CreateModel(
            name="LabelImage",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("name", models.CharField(help_text='Designs use it by this name: image "ZAM Logo".', max_length=64,
                                          unique=True, verbose_name="name")),
                ("image", models.ImageField(help_text="PNG, GIF, JPEG or WebP, best large: designs scale it down.",
                                            upload_to="label_images/", verbose_name="original")),
                ("crop_left", models.PositiveIntegerField(default=0, verbose_name="cut off left")),
                ("crop_top", models.PositiveIntegerField(default=0, verbose_name="cut off top")),
                ("crop_right", models.PositiveIntegerField(default=0, verbose_name="cut off right")),
                ("crop_bottom", models.PositiveIntegerField(default=0, verbose_name="cut off bottom")),
            ],
            options={"verbose_name": "label image", "verbose_name_plural": "label images", "ordering": ("name",)},
        ),
        migrations.RenameField(model_name="labelstock", old_name="zpl_templates", new_name="label_templates"),
        migrations.RenameField(model_name="labelmedium", old_name="zpl_templates", new_name="label_templates"),
        migrations.AlterField(
            model_name="labelstock",
            name="label_templates",
            field=models.ManyToManyField(
                blank=True, related_name="stock", to="inventory.locationlabeltemplate", verbose_name="label templates",
                help_text="Only these of their kind for these labels; none: every template of the labels' size."),
        ),
        migrations.AlterField(
            model_name="labelmedium",
            name="label_templates",
            field=models.ManyToManyField(
                blank=True, related_name="media", to="inventory.locationlabeltemplate", verbose_name="label templates",
                help_text="Only these of their kind for this medium (else those chosen for its label stock); none: "
                          "every template of the medium's size."),
        ),
        migrations.RunPython(convert, back),
    ]
