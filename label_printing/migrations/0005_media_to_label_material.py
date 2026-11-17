"""What the label media held moves on (see 0004): a migration of its own, as PostgreSQL alters no table with rows
changed in the same transaction (0004's indexes are made at its end)."""
from django.db import migrations


def convert_media(apps, schema_editor):
    Medium = apps.get_model("label_printing", "LabelMedium")
    Stock = apps.get_model("label_printing", "LabelStock")
    Printer = apps.get_model("label_printing", "Printer")
    PrintJob = apps.get_model("label_printing", "PrintJob")
    Stock.objects.filter(language="zpl").update(in_stock=True)  # the Zebra labels of the templates in use (0002)
    stock_of = {}
    for medium in Medium.objects.select_related("printer").order_by("-is_default", "pk"):  # the default one first
        stock_id = medium.stock_id or Stock.objects.get_or_create(
            language=medium.printer.language, code="",
            name=medium.name or f"{medium.width_mm or medium.ptouch_tape} × {medium.height_mm or '…'} mm",
            defaults={"width_mm": medium.width_mm, "height_mm": medium.height_mm, "tape_mm": medium.ptouch_tape},
        )[0].pk
        stock_of[medium.pk] = stock_id
        Stock.objects.filter(pk=stock_id).update(in_stock=True)
        if medium.zpl_darkness is not None:
            Stock.objects.filter(pk=stock_id, zpl_darkness=None).update(zpl_darkness=medium.zpl_darkness)
        Stock.objects.filter(pk=stock_id, quality="standard").update(quality=medium.quality)
        if medium.offset_x or medium.offset_y:
            Printer.objects.filter(pk=medium.printer_id, offset_x=0, offset_y=0).update(
                offset_x=medium.offset_x, offset_y=medium.offset_y)
    for medium_id, stock_id in stock_of.items():
        Printer.objects.filter(loaded_medium_id=medium_id).update(loaded_stock_id=stock_id)
        PrintJob.objects.filter(medium_id=medium_id).update(stock_id=stock_id)


class Migration(migrations.Migration):

    dependencies = [
        ("label_printing", "0004_media_become_label_material"),
    ]

    operations = [
        migrations.RunPython(convert_media, migrations.RunPython.noop),
    ]
