from django.db import migrations

TEMPLATES = [
    ("Preisschild 60x30", 60, 30, """# Price tag for bulk items, 60 × 30 mm: name, price, QR code
label 60 x 30  margin 1.5
text {name}  font condensed  bold  lines 2  height 8
row  gap 2  margin 1 0 0 0
  row  border 0.5  shape bulge  padding 0.5 0  justify center
    text "€ {amount}"  font condensed  bold
    text "/ {unit}"  font condensed  size 3.5  margin 0 0 1.5 1  bottom
  qr {qr}  ecc M
"""),
    ("Preisschild Band 12 mm", None, 12, """# Price tag for bulk items on 12 mm tape, as long as the name needs: name, price, QR code
label height 12  margin 0.3
row  gap 1
  text {name}  font condensed  bold  height 55%
  row  border 0.4  shape bulge  padding 0.2 0
    text "€ {amount}"  font condensed  bold
    text "/ {unit}"  font condensed  height 45%  margin 0 0 0 0.5  bottom
  qr {qr}  quiet 1
"""),
    ("Preisschild Band 18 mm", None, 18, """# Price tag for bulk items on 18 mm tape, as long as the name needs: the name, below it price and QR code
label height 18  margin 0.5
text {name}  font condensed  bold  height 30%
row  gap 2  margin 0.5 0 0 0
  row  border 0.5  shape bulge  padding 0.3 0  width auto
    text "€ {amount}"  font condensed  bold
    text "/ {unit}"  font condensed  height 40%  margin 0 0 0 1  bottom
  qr {qr}  ecc M
"""),
    ("Preisschild Band 24 mm", None, 24, """# Price tag for bulk items on 24 mm tape, as long as the name needs: the name, below it price and QR code
label height 24  margin 0.5
text {name}  font condensed  bold  height 30%
row  gap 2  margin 0.5 0 0 0
  row  border 0.5  shape bulge  padding 0.3 0  width auto
    text "€ {amount}"  font condensed  bold
    text "/ {unit}"  font condensed  height 40%  margin 0 0 0 1  bottom
  qr {qr}  ecc M
"""),
]


def create(apps, schema_editor):
    Template = apps.get_model("inventory", "LocationLabelTemplate")
    for name, width, height, description in TEMPLATES:
        Template.objects.get_or_create(name=name, defaults={
            "subject_type": "item", "description": description, "label_width": width, "label_height": height})


def remove(apps, schema_editor):
    apps.get_model("inventory", "LocationLabelTemplate").objects.filter(name__in=[name for name, *_rest in TEMPLATES]).delete()


class Migration(migrations.Migration):
    """Price tags for bulk items: name, the price with € in a price tag frame and its unit, a QR code (name above
    price and QR code where there is room)."""

    dependencies = [("label_printing", "0008_label_designs")]

    operations = [migrations.RunPython(create, remove)]
