import importlib
import re

from django.db import migrations

# The labels that used to be drawn in code, and the ZAMid design, as label templates: for each size of Zebra
# labels in use and each Brother tape width (templates a printer cannot print are not offered on it).
TAPES = [9, 12, 18, 24, 36]
CARDS = [(57, 32), (60, 30), (70, 32), (105, 52)]


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


def templates():
    """[(name, subject type, description)]"""
    found = []
    for width, height in CARDS:
        found += [(f"QR-Code, Kennung und Ort {width}x{height}", "location", location_card(width, height)),
                  (f"Name, Preis und QR-Code {width}x{height}", "item", item_card(width, height)),
                  (f"ZAMid {width}x{height}", "labelid", zamid_card(width, height)),
                  (f"ZAMid: QR + ID {width}x{height}", "labelid", plain_card(width, height))]
    for tape in TAPES:
        found += [(f"QR-Code, Kennung und Ort, Band {tape} mm", "location", location_tape(tape)),
                  (f"Name, Preis und QR-Code, Band {tape} mm", "item", item_tape(tape)),
                  (f"ZAMid Band {tape} mm", "labelid", zamid_tape(tape)),
                  (f"ZAMid: QR + ID, Band {tape} mm", "labelid", plain_tape(tape))]
    return found


def size_of(description):
    size = re.search(r"^label (?:height (\d+)|(\d+) x (\d+))", description, re.M)
    return (None, float(size.group(1))) if size.group(1) else (float(size.group(2)), float(size.group(3)))


def create(apps, schema_editor):
    Template = apps.get_model("inventory", "LocationLabelTemplate")
    before = importlib.import_module("label_printing.migrations.0008_label_designs")
    untouched = {name: description for name, _kind, description in before.NEW}
    # The tape location template of 0008 is one of these now
    Template.objects.filter(name="Standort Band 12 mm", description=untouched["Standort Band 12 mm"]).delete()
    for name, subject_type, description in templates():
        width, height = size_of(description)
        template = Template.objects.filter(name=name).first()
        if template is None:
            Template.objects.create(name=name, subject_type=subject_type, description=description,
                                    label_width=width, label_height=height)
        elif template.description == untouched.get(name):  # as 0008 made it: the design of all sizes now
            template.description = description
            template.save(update_fields=["description"])


def remove(apps, schema_editor):
    # By ids and without Django's cascade: rolled back across apps, the related models may be of an older state.
    Template = apps.get_model("inventory", "LocationLabelTemplate")
    templates_ = Template.objects.filter(name__in=[name for name, _kind, _description in templates()]).exclude(
        name__in=["ZAMid 70x32", "ZAMid 60x30", "ZAMid 105x52"])
    ids = list(templates_.values_list("pk", flat=True))
    apps.get_model("inventory", "LocationType").objects.filter(default_label_template_id__in=ids).update(
        default_label_template=None)
    apps.get_model("inventory", "Location").objects.filter(label_template_id__in=ids).update(label_template=None)
    for model in ("LabelStock", "LabelMedium"):
        apps.get_model("label_printing", model).label_templates.through.objects.filter(
            locationlabeltemplate_id__in=ids).delete()
    templates_._raw_delete(schema_editor.connection.alias)


class Migration(migrations.Migration):
    """Templates for every label: locations (QR code, code and path), bulk items (name, price and QR code) and
    unique items (ZAMid, ZAMid: QR + ID), for the Zebra labels in use and every Brother tape width."""

    dependencies = [
        ("label_printing", "0011_brother_cutting"),
        ("inventory", "0046_label_template_kinds"),
    ]

    operations = [migrations.RunPython(create, remove)]
