import re

from django.db import migrations

# The templates converted from ZPL (0008), named after their size and use
OLD = {
    "70x32 static": "Fester Standort",
    "70x32 static up": "Fester Standort, Pfeil hoch",
    "70x32 static down": "Fester Standort, Pfeil runter",
    "60x30 mobile": "Mobil, mit Logo und Eigentum",
    "105x52 mobile": "Mobil, mit Logo und Eigentum",
}
# The size at the end of a name: " 70x32", ", Band 12 mm" or " Band 12 mm"
SIZE = re.compile(r",? (?:Band (?P<tape>\d+(?:\.\d+)?) mm|(?P<width>\d+(?:\.\d+)?)x(?P<height>\d+(?:\.\d+)?))$")
# The names 0008, 0009 and 0012 gave, without their size
MADE = {"QR-Code, Kennung und Ort", "Name, Preis und QR-Code", "ZAMid", "ZAMid: QR + ID", "Preisschild"}


def size_matches(match, template):
    """Whether the size in the name is the template's own (else the name says something else)."""
    if match["tape"]:
        return template.label_width is None and float(match["tape"]) == template.label_height
    return (template.label_width, template.label_height) == (float(match["width"]), float(match["height"]))


def rename(apps, schema_editor):
    """Names say what is on a label; its size is shown beside the name (print dialog, admin)."""
    for template in apps.get_model("inventory", "LocationLabelTemplate").objects.all():
        if template.name in OLD:
            name = OLD[template.name]
        elif (match := SIZE.search(template.name)) and size_matches(match, template):
            name = template.name[:match.start()]
        else:
            continue
        template.name = name
        template.save(update_fields=["name"])


def with_size(template):
    if template.label_width is None:
        separator = " " if template.name in ("ZAMid", "Preisschild") else ", "
        return f"{template.name}{separator}Band {template.label_height:g} mm"
    return f"{template.name} {template.label_width:g}x{template.label_height:g}"


def back(apps, schema_editor):
    old = {(new, size): name for name, new in OLD.items() for size in [name.split(" ")[0]]}
    for template in apps.get_model("inventory", "LocationLabelTemplate").objects.filter(
            name__in=MADE | set(OLD.values())):
        size = f"{template.label_width or 0:g}x{template.label_height or 0:g}"
        template.name = old.get((template.name, size)) or with_size(template)
        template.save(update_fields=["name"])


class Migration(migrations.Migration):
    dependencies = [
        ("label_printing", "0012_templates_for_all_labels"),
        ("inventory", "0047_label_template_active"),
    ]

    operations = [migrations.RunPython(rename, back)]
