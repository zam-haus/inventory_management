"""The queue as an offering: no more pending jobs bound to a printer. Those there are wait for their printer, with
their data, as jobs for a given printer do now (services.take); a job without data that waited too long expires."""
from datetime import timedelta

from django.conf import settings
from django.db import migrations, models
from django.db.models import F


def pending_wait(apps, schema_editor):
    PrintJob = apps.get_model("label_printing", "PrintJob")
    PrintJob.objects.filter(status="pending").update(
        status="waiting", expires_at=F("ready_at") + timedelta(seconds=settings.PRINT_JOB_MAX_AGE))


def waiting_pending(apps, schema_editor):
    PrintJob = apps.get_model("label_printing", "PrintJob")
    PrintJob.objects.filter(status="waiting", payload__isnull=False).update(status="pending", expires_at=None)


class Migration(migrations.Migration):

    dependencies = [
        ("label_printing", "0010_material_set_on_the_agent"),
    ]

    operations = [
        migrations.RunPython(pending_wait, waiting_pending),
        migrations.AlterField(
            model_name="printjob",
            name="status",
            field=models.CharField(
                choices=[("waiting", "waiting for a printer"), ("processing", "printing"), ("done", "printed"),
                         ("sent", "sent, not confirmed"), ("failed", "failed"), ("expired", "expired")],
                default="waiting", max_length=16, verbose_name="status"),
        ),
    ]
