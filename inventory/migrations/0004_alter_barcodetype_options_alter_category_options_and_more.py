# Generated by Django 4.0.2 on 2022-02-21 11:04

import django.core.validators
from django.db import migrations, models
import django.db.models.deletion
import inventory.models


class Migration(migrations.Migration):

    dependencies = [
        ("inventory", "0003_alter_category_options_alter_location_options_and_more"),
    ]

    operations = [
        migrations.AlterModelOptions(
            name="barcodetype",
            options={
                "verbose_name": "barcode type",
                "verbose_name_plural": "barcode types",
            },
        ),
        migrations.AlterModelOptions(
            name="category",
            options={
                "ordering": ("full_name",),
                "verbose_name": "category",
                "verbose_name_plural": "categories",
            },
        ),
        migrations.AlterModelOptions(
            name="item",
            options={"verbose_name": "item", "verbose_name_plural": "items"},
        ),
        migrations.AlterModelOptions(
            name="location",
            options={
                "ordering": ("locatable_identifier",),
                "verbose_name": "location",
                "verbose_name_plural": "locations",
            },
        ),
        migrations.AlterModelOptions(
            name="locationlabeltemplate",
            options={"verbose_name": "location label template"},
        ),
        migrations.AlterModelOptions(
            name="locationtype",
            options={
                "verbose_name": "location type",
                "verbose_name_plural": "location types",
            },
        ),
        migrations.AlterModelOptions(
            name="measurementunit",
            options={
                "verbose_name": "measurement unit",
                "verbose_name_plural": "measurement units",
            },
        ),
        migrations.AddField(
            model_name="locationlabeltemplate",
            name="label_height",
            field=models.IntegerField(default=30, verbose_name="Label width (mm)"),
            preserve_default=False,
        ),
        migrations.AddField(
            model_name="locationlabeltemplate",
            name="label_width",
            field=models.IntegerField(default=60, verbose_name="Label width (mm)"),
            preserve_default=False,
        ),
        migrations.AlterField(
            model_name="barcodetype",
            name="name",
            field=models.CharField(max_length=128, unique=True, verbose_name="name"),
        ),
        migrations.AlterField(
            model_name="category",
            name="full_name",
            field=models.CharField(
                editable=False, max_length=1024, verbose_name="full name"
            ),
        ),
        migrations.AlterField(
            model_name="category",
            name="parent_category",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                to="inventory.category",
                verbose_name="parent category",
            ),
        ),
        migrations.AlterField(
            model_name="item",
            name="category",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                to="inventory.category",
                verbose_name="category",
            ),
        ),
        migrations.AlterField(
            model_name="item",
            name="measurement_unit",
            field=models.ForeignKey(
                default=1,
                on_delete=django.db.models.deletion.PROTECT,
                to="inventory.measurementunit",
                verbose_name="measurement unit",
            ),
        ),
        migrations.AlterField(
            model_name="itembarcode",
            name="data",
            field=models.TextField(verbose_name="data"),
        ),
        migrations.AlterField(
            model_name="itembarcode",
            name="item",
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.CASCADE,
                to="inventory.item",
                verbose_name="Item",
            ),
        ),
        migrations.AlterField(
            model_name="itembarcode",
            name="type",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                to="inventory.barcodetype",
                verbose_name="type",
            ),
        ),
        migrations.AlterField(
            model_name="itemfile",
            name="description",
            field=models.CharField(
                blank=True, max_length=512, verbose_name="description"
            ),
        ),
        migrations.AlterField(
            model_name="itemfile",
            name="file",
            field=models.FileField(
                upload_to=inventory.models.get_item_upload_path, verbose_name="file"
            ),
        ),
        migrations.AlterField(
            model_name="itemfile",
            name="item",
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.CASCADE,
                to="inventory.item",
                verbose_name="file",
            ),
        ),
        migrations.AlterField(
            model_name="itemimage",
            name="description",
            field=models.CharField(
                blank=True, max_length=512, verbose_name="description"
            ),
        ),
        migrations.AlterField(
            model_name="itemimage",
            name="image",
            field=models.ImageField(
                upload_to=inventory.models.get_item_upload_path, verbose_name="image"
            ),
        ),
        migrations.AlterField(
            model_name="itemimage",
            name="item",
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.CASCADE,
                to="inventory.item",
                verbose_name="item",
            ),
        ),
        migrations.AlterField(
            model_name="itemlocation",
            name="amount",
            field=models.DecimalField(
                decimal_places=3, max_digits=16, verbose_name="amount"
            ),
        ),
        migrations.AlterField(
            model_name="itemlocation",
            name="item",
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.CASCADE,
                to="inventory.item",
                verbose_name="item",
            ),
        ),
        migrations.AlterField(
            model_name="itemlocation",
            name="location",
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.CASCADE,
                to="inventory.location",
                verbose_name="location",
            ),
        ),
        migrations.AlterField(
            model_name="location",
            name="description",
            field=models.TextField(blank=True, verbose_name="description"),
        ),
        migrations.AlterField(
            model_name="location",
            name="descriptive_identifier",
            field=models.CharField(
                editable=False, max_length=512, verbose_name="descriptive identifier"
            ),
        ),
        migrations.AlterField(
            model_name="location",
            name="label_template",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                to="inventory.locationlabeltemplate",
                verbose_name="name",
            ),
        ),
        migrations.AlterField(
            model_name="location",
            name="last_complete_inventory",
            field=models.DateTimeField(
                blank=True, null=True, verbose_name="last complete inventory"
            ),
        ),
        migrations.AlterField(
            model_name="location",
            name="locatable_identifier",
            field=models.CharField(
                editable=False,
                max_length=512,
                unique=True,
                verbose_name="locatable identifier",
            ),
        ),
        migrations.AlterField(
            model_name="location",
            name="name",
            field=models.CharField(
                max_length=128,
                validators=[
                    django.core.validators.RegexValidator(
                        "[^a-zA-Z0-9 \\-()]*",
                        message="Only numbers, letters and spaces allowed.",
                    )
                ],
                verbose_name="name",
            ),
        ),
        migrations.AlterField(
            model_name="location",
            name="parent_location",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="children",
                to="inventory.location",
                verbose_name="parent location",
            ),
        ),
        migrations.AlterField(
            model_name="location",
            name="short_name",
            field=models.CharField(
                max_length=8,
                validators=[
                    django.core.validators.RegexValidator(
                        "[^a-zA-Z0-9]*", message="Only numbers and letters allowed."
                    )
                ],
                verbose_name="short name",
            ),
        ),
        migrations.AlterField(
            model_name="location",
            name="unique_identifier",
            field=models.CharField(
                editable=False,
                max_length=64,
                unique=True,
                verbose_name="unique identifier",
            ),
        ),
        migrations.AlterField(
            model_name="locationlabeltemplate",
            name="name",
            field=models.CharField(max_length=128, verbose_name="name"),
        ),
        migrations.AlterField(
            model_name="locationlabeltemplate",
            name="zpl_template",
            field=models.TextField(
                help_text="ZPL2 string, where $url, $unique_identifier, $locatable_identifier and $descriptive_identifier will be replaced.",
                verbose_name="ZPL template",
            ),
        ),
        migrations.AlterField(
            model_name="locationtype",
            name="auto_name_prefix",
            field=models.CharField(
                blank=True, default="", max_length=16, verbose_name="name prefix"
            ),
        ),
        migrations.AlterField(
            model_name="locationtype",
            name="auto_sequence",
            field=models.CharField(
                blank=True,
                choices=[
                    ("0123456789", "Numeric (0-9)"),
                    ("abcdefghijklmnopqrstuvwxyz", "Letters lowercase (a-z)"),
                    ("ABCDEFGHIJKLMNOPQRSTUVWXYZ", "Letters lowercase (a-z)"),
                    (
                        "0123456789abcdefghijklmnopqrstuvwxyz",
                        "Alphanumeric lowercase (0-9, a-z)",
                    ),
                    ("0123456789abcdef", "Hexadecimal lowercase (0-9, a-f)"),
                ],
                max_length=128,
                null=True,
                verbose_name="sequence",
            ),
        ),
        migrations.AlterField(
            model_name="locationtype",
            name="auto_short_name_padding_length",
            field=models.IntegerField(default=0, verbose_name="short name pedding"),
        ),
        migrations.AlterField(
            model_name="locationtype",
            name="auto_short_name_prefix",
            field=models.CharField(
                blank=True, default="", max_length=4, verbose_name="short name prefix"
            ),
        ),
        migrations.AlterField(
            model_name="locationtype",
            name="default_label_template",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                to="inventory.locationlabeltemplate",
                verbose_name="default label template",
            ),
        ),
        migrations.AlterField(
            model_name="locationtype",
            name="name",
            field=models.CharField(max_length=64, unique=True, verbose_name="name"),
        ),
        migrations.AlterField(
            model_name="locationtype",
            name="unique",
            field=models.BooleanField(default=False, verbose_name="unique flag"),
        ),
        migrations.AlterField(
            model_name="measurementunit",
            name="description",
            field=models.TextField(blank=True, verbose_name="description"),
        ),
        migrations.AlterField(
            model_name="measurementunit",
            name="name",
            field=models.CharField(max_length=128, unique=True, verbose_name="name"),
        ),
        migrations.AlterField(
            model_name="measurementunit",
            name="short",
            field=models.CharField(
                max_length=8, unique=True, verbose_name="abbreviation"
            ),
        ),
    ]
