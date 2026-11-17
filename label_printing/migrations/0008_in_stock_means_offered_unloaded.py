"""Label material not on hand is printed on while it is loaded in a printer."""

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("label_printing", "0007_catalog_up_to_date"),
    ]

    operations = [
        migrations.AlterField(
            model_name="labelstock",
            name="in_stock",
            field=models.BooleanField(
                default=False,
                help_text="Material not on hand is offered for printing only while it is loaded in a printer, and not "
                          "waited for.",
                verbose_name="on hand",
            ),
        ),
    ]
