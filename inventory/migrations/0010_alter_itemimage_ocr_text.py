# Generated by Django 4.0.2 on 2022-11-23 20:46

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('inventory', '0009_itemimage_ocr_text'),
    ]

    operations = [
        migrations.AlterField(
            model_name='itemimage',
            name='ocr_text',
            field=models.TextField(blank=True, verbose_name='ocr text'),
        ),
    ]
