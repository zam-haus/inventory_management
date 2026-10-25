"""
The labels to start with, from the inventory as it was (location label templates in ZPL):

* the permission to print for the local group;
* label stock: Brother P-touch tapes from Brother's tape selector (catalog/brother_tapes.json) and Zebra labels in
  the sizes of the ZPL templates;
* the label templates in the label description language (docs/label-designs.md), with their rules (which subjects
  they are meant for, with their print priority), as tried out on the development server (catalog/
  label_templates.json): for locations, items, unique items and label IDs (ZAMid) on the Zebra labels in use and
  every Brother tape width, and price tags. The ZPL templates in use become those that replace them (by name), so
  locations and types keep theirs; the logo in them becomes the label image "ZAM Logo"; templates it does not know
  get a plain design with their ZPL as comments;
* each location's chosen template (else its type's) as the label it was printed with last (LastLabel).
"""
import io
import json
import re
from pathlib import Path

from django.conf import settings
from django.core.files.base import ContentFile
from django.db import migrations
from django.db.models import Q


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


TEMPLATES = Path(__file__).resolve().parent.parent / "catalog" / "label_templates.json"
QR = "{{ qr }}"
CODE = "{{ location.unique_identifier }}"
PATH = "{{ location.descriptive_identifier }}"


def fallback(width, height):
    return f"""# Converted from a ZPL template: check it. The ZPL is kept below as comments.
label {width:g} x {height:g}  margin 1
row  gap 2
  qr {QR}
  column  gap 1
    text {CODE}  font mono  bold  invert
    text {PATH}  font condensed  lines 2
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



def templates_to_start_with():
    """[{name, replaces (the ZPL template's name), subject_type, label_width, label_height, is_active, quality,
    label_stock (its code), material, print_color, background_color, rules: [[condition, priority]],
    description}]"""
    with open(TEMPLATES, encoding="utf-8") as file:
        return json.load(file)


def labels_to_start_with(apps, schema_editor):
    Template = apps.get_model("inventory", "LocationLabelTemplate")
    Rule = apps.get_model("inventory", "LabelTemplateRule")
    LabelImage = apps.get_model("label_printing", "LabelImage")
    LabelStock = apps.get_model("label_printing", "LabelStock")
    templates = list(Template.objects.all())
    png = logo_png(templates)
    if png:
        logo = LabelImage(name="ZAM Logo")
        logo.image.save("zam-logo.png", ContentFile(png), save=False)
        logo.save()
    zebra_labels(apps, templates)
    zpl = {template.name: template for template in templates}
    for entry in templates_to_start_with():
        template = zpl.pop(entry.get("replaces"), None) or Template()
        for field in ("name", "subject_type", "label_width", "label_height", "is_active", "quality", "material",
                      "print_color", "background_color", "description"):
            setattr(template, field, entry[field])
        template.label_stock = LabelStock.objects.filter(code=entry["label_stock"]).first() if entry["label_stock"] \
            else None
        template.save()
        Rule.objects.bulk_create([Rule(template=template, condition=condition, priority=priority)
                                  for condition, priority in entry["rules"]])
    for template in zpl.values():  # unknown: a plain design, offered last
        template.description = (fallback(template.label_width or 57, template.label_height or 32)
                                + "\n" + as_comment(template.zpl_template))
        template.save()
        Rule.objects.create(template=template, condition="", priority=0)
    # The template chosen for a location (else for its type) is preselected when it is printed again: existing
    # locations keep their labels; the rules decide for new ones.
    LastLabel = apps.get_model("label_printing", "LastLabel")
    LastLabel.objects.bulk_create([
        LastLabel(subject_type="location", subject_pk=str(pk), layout_key=f"design:{own or of_type}")
        for pk, own, of_type in apps.get_model("inventory", "Location").objects.values_list(
            "pk", "label_template_id", "type__default_label_template_id") if own or of_type])


def back(apps, schema_editor):
    """Going back: without the templates made here (those without ZPL); sizes the integer fields of before can
    hold."""
    Template = apps.get_model("inventory", "LocationLabelTemplate")
    made = Template.objects.filter(Q(zpl_template="") | Q(zpl_template__isnull=True))
    ids = list(made.values_list("pk", flat=True))
    apps.get_model("label_printing", "LastLabel").objects.all().delete()
    apps.get_model("inventory", "LabelTemplateRule").objects.all().delete()
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
