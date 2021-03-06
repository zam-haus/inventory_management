# Generated by Django 4.0.2 on 2022-03-20 19:26

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('inventory', '0006_alter_item_description_alter_location_label_template'),
    ]

    operations = [
        migrations.AlterField(
            model_name='itemlocation',
            name='amount',
            field=models.DecimalField(decimal_places=3, help_text="positive numbers are precise, negative numbers are rough estimates. -1 is 'few' and -9999 is 'many'.", max_digits=16, verbose_name='amount'),
        ),
    ]
