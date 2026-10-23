"""
Label stock to start with: Brother P-touch tapes from Brother's tape selector (catalog/brother_tapes.json),
and Zebra labels in the sizes of the existing location label templates, linked to those templates.
"""
import json
from pathlib import Path

from django.db import migrations

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


def zebra_labels_of_templates(apps, schema_editor):
    """One stock per size of the location label templates; printing method and material where known."""
    alias = schema_editor.connection.alias
    LabelStock = apps.get_model("label_printing", "LabelStock")
    Template = apps.get_model("inventory", "LocationLabelTemplate")
    sizes = {}
    for template in Template.objects.using(alias).order_by("name"):
        sizes.setdefault((template.label_width, template.label_height), []).append(template)
    for (width, height), templates in sizes.items():
        names = ", ".join(f"„{template.name}“" for template in templates)
        method, ribbon, material = KNOWN_ZEBRA_LABELS.get((width, height), ("", "", ""))
        description = f"Aus den ZPL-Vorlagen {names} angelegt."
        if not method:
            description += " Druckverfahren (Thermodirekt oder Thermotransfer mit Farbband) und Material bitte ergänzen."
        stock = LabelStock.objects.using(alias).create(
            language="zpl", name=f"Etikett {width} × {height} mm{f' {material}' if material else ''}",
            width_mm=width, height_mm=height, method=method, ribbon=ribbon, material=material,
            description=description,
        )
        stock.zpl_templates.set(templates)


class Migration(migrations.Migration):

    dependencies = [
        ("label_printing", "0003_label_stock"),
        ("inventory", "0042_location_label_url"),
    ]

    operations = [
        migrations.RunPython(brother_tapes, migrations.RunPython.noop),
        migrations.RunPython(zebra_labels_of_templates, migrations.RunPython.noop),
    ]
