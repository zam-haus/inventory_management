from django.db import migrations, models


class Migration(migrations.Migration):
    """The ZPL of label templates, described anew by label_printing.0008."""

    dependencies = [
        ("inventory", "0043_label_designs"),
        ("label_printing", "0008_label_designs"),
    ]

    operations = [
        # With a default first, so that going back adds the field again to templates without ZPL.
        migrations.AlterField(model_name="locationlabeltemplate", name="zpl_template",
                              field=models.TextField(default="", verbose_name="ZPL template")),
        migrations.RemoveField(model_name="locationlabeltemplate", name="zpl_template"),
    ]
