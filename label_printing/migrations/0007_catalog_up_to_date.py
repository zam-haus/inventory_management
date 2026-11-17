"""
The catalog brought up to date: ribbons and the Zebra labels bought (labelident.de) or left over (Greiner), the logo cut
down to the mark for small labels ("ZAM Logo ohne Wortmarke"), and the label templates of catalog/label_templates.json:
those 0002 brought (with 0003's changes) and still unchanged become their successors (renamed, e.g. "Fester Standort"
to "Lagermöbel"; same records, so the locations' last labels stay), new ones are added. Templates changed in the admin
are left as they are.
"""
import io
import json
from decimal import Decimal
from pathlib import Path

from django.db import migrations

CATALOG = Path(__file__).resolve().parent.parent / "catalog"
FIELDS = ("name", "subject_type", "label_width", "label_height", "is_active", "quality", "material", "print_color",
          "background_color", "description")

# Ribbons, and the Zebra labels bought (labelident.de) or left over (Greiner), on hand; the price tags are yet to be
# bought.
# 110 mm, every material, red and black
RIBBONS = [{"material": material, "width_mm": 110, "color": color}
           for material in ("wax", "wax_resin", "resin") for color in ("schwarz", "rot")]
STOCK = [
    {"code": "ERT-MP-Z-070X032Z1-ER", "name": "70x32mm Papier permanent", "width_mm": 70, "height_mm": 32,
     "core_mm": Decimal("25.4"), "method": "transfer", "ribbon": "wax", "material": "Papier", "background_color": "weiß",
     "description": "Papier-Etiketten, weiß, permanent klebend, Trägerperforation, 70 x 32 mm, 1 Zoll (25,4 mm) "
                    "Rollenkern, 2100 Etiketten auf 1 Rolle(n)",
     "url": "https://www.labelident.com/ert-mp-z-070x032z1-er.html"},
    {"code": "ERT-PG105X052Z1", "name": "105x52mm Polyester gelb permanent", "width_mm": 105, "height_mm": 52,
     "core_mm": Decimal("25.4"), "method": "transfer", "ribbon": "resin", "material": "Polyester", "background_color": "gelb",
     "description": "Polyester-Etiketten, gelb, permanent klebend, 105 x 52 mm, 1 Zoll (25,4 mm) Rollenkern, "
                    "1000 Etiketten auf 1 Rolle(n)",
     "url": "https://www.labelident.com/ert-pg105x052z1.html"},
    # Sizes are whole millimetres (LabelStock); the exact size is in the name.
    {"code": "ERT-PG015X006Z1", "name": "15x6,35mm Polyester gelb permanent", "width_mm": 15, "height_mm": 6,
     "core_mm": Decimal("25.4"), "method": "transfer", "ribbon": "resin", "material": "Polyester", "background_color": "gelb",
     "description": "Polyester-Etiketten, gelb, permanent klebend, 15 x 6,35 mm, 1 Zoll Kern, 10000 Etiketten auf "
                    "1 Rolle(n)\n6 Etiketten nebeneinander: nur für Vordruck in ganzen Reihen, nicht im Einzeldruck "
                    "(keine einzelnen IDs).",
     "url": "https://www.labelident.com/ert-pg015x006z1.html"},
    {"code": "ERT-PG055X015Z1", "name": "55x15mm Polyester gelb permanent", "width_mm": 55, "height_mm": 15,
     "core_mm": Decimal("25.4"), "method": "transfer", "ribbon": "resin", "material": "Polyester", "background_color": "gelb",
     "description": "Polyester-Etiketten, gelb, permanent klebend, 55 x 15 mm, 1 Zoll Kern, 5000 Etiketten auf "
                    "2 Rolle(n)\nNicht mehr lieferbar (Stand 4.11.2026): danach gelbes 18-mm-Band, extra stark (TZe-S641), an "
                    "Dingen und Kisten; Regale, Fächer, Schränke und Schübe bekommen 70 x 32 mm invertiert (weiß auf schwarz)."},
    {"code": "ERT-PA100X150Z1", "name": "100x150mm Papier ablösbar", "width_mm": 100, "height_mm": 150,
     "core_mm": Decimal("25.4"), "method": "transfer", "ribbon": "wax", "material": "Papier", "background_color": "weiß",
     "description": "Papier-Etiketten, weiß, ablösbar, 100 x 150 mm, 1 Zoll Rollenkern, 1000 Etiketten auf "
                    "2 Rolle(n)"},
    {"code": "ERT-PP-Z-102X152Z1-ER", "name": "101,6x152,4mm Papier permanent", "width_mm": 102, "height_mm": 152,
     "core_mm": Decimal("25.4"), "method": "transfer", "ribbon": "wax", "material": "Papier", "background_color": "weiß",
     "description": "Papier-Etiketten, weiß, permanent klebend, Trägerperforation, 101,6 x 152,4 mm (4 x 6 Zoll), "
                    "1 Zoll Rollenkern, 475 Etiketten auf 1 Rolle(n); formatgleich Zebra 800294-605 "
                    "(Z-Perform 1000T)",
     "url": "https://www.labelident.com/ert-pp-z-102x152z1-er.html"},
    # Pallet rack slots, printed inverted (template "Ort, Palettenregal"): to be bought when the yellow 105 × 52 mm is used up
    {"code": "ERT-PP100X050Z1", "name": "100x50mm Papier permanent", "width_mm": 100, "height_mm": 50,
     "core_mm": Decimal("25.4"), "method": "transfer", "ribbon": "wax", "material": "Papier",
     "background_color": "weiß", "in_stock": False,
     "description": "Papier-Etiketten, weiß, permanent klebend, 100 x 50 mm, 1 Zoll Rollenkern, Außenwicklung, 1000 "
                    "Etiketten auf 1 Rolle(n)",
     "url": "https://www.labelident.com/ert-pp100x050z1.html"},
    # Items and their prices (template "Artikel"), to be bought (not on hand yet): removable, at most 20 mm high
    {"code": "ERT-PA050X018Z1", "name": "50x18mm Papier ablösbar", "width_mm": 50, "height_mm": 18,
     "core_mm": Decimal("25.4"), "method": "transfer", "ribbon": "wax", "material": "Papier",
     "background_color": "weiß", "in_stock": False,
     "description": "Papier-Etiketten, weiß, ablösbar, 50 x 18 mm, 1 Zoll Rollenkern, Außenwicklung, 2500 Etiketten auf "
                    "1 Rolle(n)",
     "url": "https://www.labelident.com/ert-pa050x018z1.html"},
    # Price tags, to be bought (not on hand yet)
    {"code": "ERT-PA060X040Z1", "name": "60x40mm Papier ablösbar", "width_mm": 60, "height_mm": 40,
     "core_mm": Decimal("25.4"), "method": "transfer", "ribbon": "wax", "material": "Papier",
     "background_color": "weiß", "in_stock": False,
     "description": "Papier-Etiketten, weiß, ablösbar, 60 x 40 mm, 1 Zoll Rollenkern, 1000 Etiketten auf 1 Rolle(n)",
     "url": "https://www.labelident.com/ert-pa060x040z1.html"},
]
# Zebra labels have no print colour of their own: the ribbon has (models.Medium.colours).
# Without article number: found by name
LEFTOVERS = [
    {"code": "", "name": "47x24mm Polyester ablösbar, 2 nebeneinander (Greiner)", "width_mm": 47, "height_mm": 24,
     "method": "transfer", "ribbon": "resin", "material": "Polyester",
     "description": "Restbestand von Greiner: Rolle mit 2 Etiketten 47 x 24 mm nebeneinander, 3 mm Abstand "
                    "zwischen den Etiketten. Polyester, rückstandsfrei wiederablösbar, mit Kugelschreiber "
                    "beschriftbar. Farbband-Art nicht bekannt: Harz angenommen (wie für Polyester üblich)."},
]


def add_material(apps, schema_editor):
    ribbons = apps.get_model("label_printing", "Ribbon").objects
    for entry in RIBBONS:
        ribbons.get_or_create(**entry)
    stock = apps.get_model("label_printing", "LabelStock").objects
    for entry in STOCK:
        stock.get_or_create(code=entry["code"], defaults={"language": "zpl", "in_stock": True, **entry})
    for entry in LEFTOVERS:
        stock.get_or_create(code="", name=entry["name"], defaults={"language": "zpl", "in_stock": True, **entry})


def wordmark_cut(png):
    """How many rows to cut off the logo's bottom to leave the mark without the wordmark below it ("Zentrum für
    Austausch und Machen"): down to the first white row below the mark; 0 if there is none."""
    from PIL import Image

    with Image.open(io.BytesIO(png)) as image:
        image = image.convert("1")
        rows = [any(image.getpixel((x, y)) == 0 for x in range(image.width)) for y in range(image.height)]
    gap = next((y for y in range(1, len(rows)) if rows[y - 1] and not rows[y]), None)
    return image.height - gap if gap is not None and any(rows[gap:]) else 0


def add_mark(apps, schema_editor):
    LabelImage = apps.get_model("label_printing", "LabelImage")
    logo = LabelImage.objects.filter(name="ZAM Logo").first()
    if logo is None or LabelImage.objects.filter(name="ZAM Logo ohne Wortmarke").exists():
        return
    try:
        with logo.image.open("rb") as file:
            cut = wordmark_cut(file.read())
    except (OSError, ValueError):  # the file is missing: the whole logo
        cut = 0
    LabelImage.objects.create(name="ZAM Logo ohne Wortmarke", image=logo.image.name, crop_bottom=cut)


def catalog(name):
    with open(CATALOG / name, encoding="utf-8") as file:
        return json.load(file)


def successions():
    """[(the template as 0002 and 0003 left it, its successor)]: the catalog's entries in the same order; new ones
    without a predecessor."""
    before = catalog("label_templates_0002.json")
    changed = {(change["name"], change["subject_type"], change["label_width"], change["label_height"]): change["after"]
               for change in catalog("location_display_0003.json")}
    for entry in before:
        entry["description"] = changed.get(
            (entry["name"], entry["subject_type"], entry["label_width"], entry["label_height"]), entry["description"])
    after = catalog("label_templates.json")
    assert all((old["subject_type"], old["label_width"], old["label_height"])
               == (new["subject_type"], new["label_width"], new["label_height"]) for old, new in zip(before, after))
    return list(zip(before, after)) + [(None, new) for new in after[len(before):]]


def replace_templates(apps, pairs):
    """Each (old, new): the template still as `old` becomes `new`; without `old`, `new` is added; without `new`, the
    template still as `old` goes."""
    Template = apps.get_model("inventory", "LocationLabelTemplate")
    Rule = apps.get_model("inventory", "LabelTemplateRule")

    def unchanged(entry):
        template = Template.objects.filter(**{field: entry[field] for field in FIELDS}).first()
        rules = sorted(Rule.objects.filter(template=template).values_list("condition", "priority")) if template else []
        return template if template and rules == sorted(map(tuple, entry["rules"])) else None

    for old, new in pairs:
        template = unchanged(old) if old else None
        if old and template is None:
            continue  # changed in the admin, or gone
        if new is None:
            template.delete()
            continue
        if template is None:
            if Template.objects.filter(name=new["name"], subject_type=new["subject_type"],
                                       label_width=new["label_width"], label_height=new["label_height"]).exists():
                continue
            template = Template()
        for field in FIELDS:
            setattr(template, field, new[field])
        template.save()
        Rule.objects.filter(template=template).delete()
        Rule.objects.bulk_create([Rule(template=template, condition=condition, priority=priority)
                                  for condition, priority in new["rules"]])


def forwards(apps, schema_editor):
    replace_templates(apps, successions())


def backwards(apps, schema_editor):
    replace_templates(apps, [(new, old) for old, new in successions()])


class Migration(migrations.Migration):

    dependencies = [
        ("label_printing", "0006_remove_label_media"),
    ]

    operations = [
        migrations.RunPython(add_material, migrations.RunPython.noop),
        migrations.RunPython(add_mark, migrations.RunPython.noop),
        migrations.RunPython(forwards, backwards),
    ]
