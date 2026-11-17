"""Brother PT-P700 and PT-P710BT cannot half cut: those set to it cut fully (as they printed since: drivers.cutting)."""
from django.db import migrations, models

WITHOUT_HALF_CUT = ("P700", "P710BT")


def full_cut(apps, schema_editor):
    apps.get_model("label_printing", "Printer").objects.filter(
        language="ptouch", model__in=WITHOUT_HALF_CUT, cut="half").update(cut="full")


class Migration(migrations.Migration):

    dependencies = [
        ("label_printing", "0008_in_stock_means_offered_unloaded"),
    ]

    operations = [
        migrations.AlterField(
            model_name="printer",
            name="chain_printing",
            field=models.BooleanField(
                default=True, verbose_name="continuous printing",
                help_text="Brother: the last label stays in the printer and the next job goes on from there, which "
                          "saves tape; cut it off with the printer's cutter button. Off: the printer feeds and cuts "
                          "after every job. P700 and P710BT do not cut off the empty start of the tape themselves: "
                          "off, it is cut off before every job; on, the first label after the button keeps it."),
        ),
        migrations.AlterField(
            model_name="printer",
            name="cut",
            field=models.CharField(
                choices=[("half", "half cut between labels"), ("full", "full cut after each label"),
                         ("none", "no cut between labels")],
                default="half", max_length=8, verbose_name="cutting",
                help_text="Brother: between the labels of a job. P700 and P710BT: no half cut."),
        ),
        migrations.RunPython(full_cut, migrations.RunPython.noop),
    ]
