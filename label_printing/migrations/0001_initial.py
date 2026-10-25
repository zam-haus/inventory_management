
import django.db.models.deletion
import django.utils.timezone
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    initial = True

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="LabelImage",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                (
                    "name",
                    models.CharField(
                        help_text='Designs use it by this name: image "ZAM Logo".',
                        max_length=64,
                        unique=True,
                        verbose_name="name",
                    ),
                ),
                (
                    "image",
                    models.ImageField(
                        help_text="PNG, GIF, JPEG or WebP, best large: designs scale it down.",
                        upload_to="label_images/",
                        verbose_name="original",
                    ),
                ),
                (
                    "crop_left",
                    models.PositiveIntegerField(default=0, verbose_name="cut off left"),
                ),
                (
                    "crop_top",
                    models.PositiveIntegerField(default=0, verbose_name="cut off top"),
                ),
                (
                    "crop_right",
                    models.PositiveIntegerField(
                        default=0, verbose_name="cut off right"
                    ),
                ),
                (
                    "crop_bottom",
                    models.PositiveIntegerField(
                        default=0, verbose_name="cut off bottom"
                    ),
                ),
            ],
            options={
                "verbose_name": "label image",
                "verbose_name_plural": "label images",
                "ordering": ("name",),
            },
        ),
        migrations.CreateModel(
            name="PrintAgent",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                (
                    "name",
                    models.CharField(max_length=64, unique=True, verbose_name="name"),
                ),
                (
                    "is_active",
                    models.BooleanField(
                        default=True,
                        help_text="Only active agents are let in; deactivate one to lock it out.",
                        verbose_name="active",
                    ),
                ),
                (
                    "token_hash",
                    models.CharField(editable=False, max_length=64, unique=True),
                ),
                (
                    "hostname",
                    models.CharField(
                        blank=True,
                        editable=False,
                        max_length=255,
                        verbose_name="host name",
                    ),
                ),
                (
                    "address",
                    models.GenericIPAddressField(
                        blank=True, editable=False, null=True, verbose_name="address"
                    ),
                ),
                (
                    "last_seen",
                    models.DateTimeField(
                        blank=True, editable=False, null=True, verbose_name="last seen"
                    ),
                ),
                (
                    "version",
                    models.CharField(
                        blank=True,
                        editable=False,
                        max_length=32,
                        verbose_name="version",
                    ),
                ),
            ],
            options={
                "verbose_name": "print agent",
                "verbose_name_plural": "print agents",
            },
        ),
        migrations.CreateModel(
            name="LabelStock",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                (
                    "language",
                    models.CharField(
                        choices=[("zpl", "Zebra (ZPL)"), ("ptouch", "Brother P-touch")],
                        max_length=16,
                        verbose_name="printer language",
                    ),
                ),
                (
                    "code",
                    models.CharField(
                        blank=True, max_length=64, verbose_name="article number"
                    ),
                ),
                ("name", models.CharField(max_length=128, verbose_name="name")),
                (
                    "description",
                    models.TextField(blank=True, verbose_name="description"),
                ),
                (
                    "tape_mm",
                    models.PositiveSmallIntegerField(
                        blank=True,
                        choices=[
                            (4, "3.5 mm"),
                            (6, "6 mm"),
                            (9, "9 mm"),
                            (12, "12 mm"),
                            (18, "18 mm"),
                            (24, "24 mm"),
                            (36, "36 mm"),
                        ],
                        null=True,
                        verbose_name="tape width",
                    ),
                ),
                (
                    "background_color",
                    models.CharField(
                        blank=True, max_length=64, verbose_name="background colour"
                    ),
                ),
                (
                    "print_color",
                    models.CharField(
                        blank=True, max_length=64, verbose_name="print colour"
                    ),
                ),
                (
                    "length_m",
                    models.DecimalField(
                        blank=True,
                        decimal_places=2,
                        max_digits=6,
                        null=True,
                        verbose_name="length (m)",
                    ),
                ),
                (
                    "width_mm",
                    models.PositiveSmallIntegerField(
                        blank=True, null=True, verbose_name="width (mm)"
                    ),
                ),
                (
                    "height_mm",
                    models.PositiveSmallIntegerField(
                        blank=True, null=True, verbose_name="height (mm)"
                    ),
                ),
                (
                    "method",
                    models.CharField(
                        blank=True,
                        choices=[
                            ("direct", "direct thermal"),
                            ("transfer", "thermal transfer"),
                        ],
                        help_text="Zebra: direct thermal labels need no ribbon. Empty: not known.",
                        max_length=16,
                        verbose_name="printing method",
                    ),
                ),
                (
                    "ribbon",
                    models.CharField(
                        blank=True,
                        choices=[
                            ("wax", "wax ribbon"),
                            ("wax_resin", "wax/resin ribbon"),
                            ("resin", "resin ribbon"),
                        ],
                        help_text="Thermal transfer: the ribbon the material needs.",
                        max_length=16,
                        verbose_name="ribbon",
                    ),
                ),
                (
                    "material",
                    models.CharField(
                        blank=True,
                        help_text="e.g. paper, polypropylene, polyester",
                        max_length=64,
                        verbose_name="material",
                    ),
                ),
                ("url", models.URLField(blank=True, verbose_name="product page")),
            ],
            options={
                "verbose_name": "label stock",
                "verbose_name_plural": "label stock",
                "ordering": (
                    "language",
                    "tape_mm",
                    "width_mm",
                    "height_mm",
                    "code",
                    "name",
                ),
            },
        ),
        migrations.CreateModel(
            name="LabelMedium",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                (
                    "name",
                    models.CharField(blank=True, max_length=128, verbose_name="name"),
                ),
                (
                    "width_mm",
                    models.PositiveSmallIntegerField(
                        blank=True,
                        help_text="Zebra: the label width.",
                        null=True,
                        verbose_name="width (mm)",
                    ),
                ),
                (
                    "height_mm",
                    models.PositiveSmallIntegerField(
                        blank=True,
                        help_text="Zebra: the label height. Brother: a fixed label length; empty for as long as the content.",
                        null=True,
                        verbose_name="height / length (mm)",
                    ),
                ),
                (
                    "ptouch_tape",
                    models.PositiveSmallIntegerField(
                        blank=True,
                        choices=[
                            (4, "3.5 mm"),
                            (6, "6 mm"),
                            (9, "9 mm"),
                            (12, "12 mm"),
                            (18, "18 mm"),
                            (24, "24 mm"),
                            (36, "36 mm"),
                        ],
                        help_text="Brother only.",
                        null=True,
                        verbose_name="tape width",
                    ),
                ),
                (
                    "offset_x",
                    models.SmallIntegerField(
                        default=0,
                        help_text="Zebra: label home (^LH).",
                        verbose_name="offset x (dots)",
                    ),
                ),
                (
                    "offset_y",
                    models.SmallIntegerField(
                        default=0,
                        help_text="Zebra: label home (^LH). Brother: moves the print across the tape, positive = down, if the top or bottom is cut off (print the calibration label to measure).",
                        verbose_name="offset y (dots)",
                    ),
                ),
                (
                    "zpl_darkness",
                    models.SmallIntegerField(
                        blank=True,
                        help_text="Zebra: -30 to 30 (^MD); empty for the printer's setting.",
                        null=True,
                        verbose_name="darkness",
                    ),
                ),
                (
                    "quality",
                    models.CharField(
                        choices=[
                            ("draft", "draft (fast)"),
                            ("standard", "standard"),
                            ("high", "high quality (slower)"),
                        ],
                        default="standard",
                        help_text="Preselected in the print dialog. Brother: draft printing or high resolution; Zebra: print speed.",
                        max_length=16,
                        verbose_name="print quality",
                    ),
                ),
                (
                    "is_default",
                    models.BooleanField(default=False, verbose_name="default medium"),
                ),
                (
                    "stock",
                    models.ForeignKey(
                        blank=True,
                        help_text="Fills in name, size and tape; colours and material come from it.",
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="media",
                        to="label_printing.labelstock",
                        verbose_name="label stock",
                    ),
                ),
            ],
            options={
                "verbose_name": "label medium",
                "verbose_name_plural": "label media",
                "ordering": ("printer", "name"),
            },
        ),
        migrations.CreateModel(
            name="Printer",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                ("name", models.CharField(max_length=64, verbose_name="name")),
                (
                    "slug",
                    models.SlugField(
                        help_text="Names the printer, e.g. for a print agent's static printers.",
                        unique=True,
                        verbose_name="short name",
                    ),
                ),
                (
                    "uid",
                    models.CharField(
                        blank=True,
                        editable=False,
                        help_text="Reported by the print agent the printer is connected to (USB IDs and serial number).",
                        max_length=128,
                        null=True,
                        unique=True,
                        verbose_name="printer ID",
                    ),
                ),
                (
                    "info",
                    models.JSONField(
                        blank=True,
                        editable=False,
                        null=True,
                        verbose_name="reported details",
                    ),
                ),
                (
                    "discovered_at",
                    models.DateTimeField(
                        blank=True,
                        editable=False,
                        null=True,
                        verbose_name="discovered at",
                    ),
                ),
                (
                    "language",
                    models.CharField(
                        choices=[("zpl", "Zebra (ZPL)"), ("ptouch", "Brother P-touch")],
                        max_length=16,
                        verbose_name="printer language",
                    ),
                ),
                (
                    "model",
                    models.CharField(
                        blank=True,
                        help_text="Brother: E550W, P750W, P900, P900W or P950NW. Zebra: for information only.",
                        max_length=32,
                        verbose_name="model",
                    ),
                ),
                (
                    "dpi",
                    models.PositiveSmallIntegerField(
                        default=203,
                        help_text="Zebra: 203, 300 or 600. Brother: set by the model.",
                        verbose_name="resolution (dpi)",
                    ),
                ),
                (
                    "transport",
                    models.CharField(
                        choices=[
                            ("network", "Network (TCP, port 9100)"),
                            ("agent", "Print agent (USB)"),
                        ],
                        default="network",
                        max_length=16,
                        verbose_name="connection",
                    ),
                ),
                (
                    "host",
                    models.CharField(
                        blank=True,
                        help_text="Network printers: name or IP address.",
                        max_length=255,
                        verbose_name="host",
                    ),
                ),
                (
                    "port",
                    models.PositiveIntegerField(default=9100, verbose_name="port"),
                ),
                (
                    "reports_status",
                    models.BooleanField(
                        default=True,
                        help_text="Check paper, tape and errors before printing and wait until the printer reports the labels printed. Turn off only for printers that cannot answer.",
                        verbose_name="reports its status",
                    ),
                ),
                (
                    "cut",
                    models.CharField(
                        choices=[
                            ("half", "half cut between labels"),
                            ("full", "full cut after each label"),
                            ("none", "no cut between labels"),
                        ],
                        default="half",
                        help_text="Brother: between the labels of a job.",
                        max_length=8,
                        verbose_name="cutting",
                    ),
                ),
                (
                    "chain_printing",
                    models.BooleanField(
                        default=True,
                        help_text="Brother: the last label stays in the printer and the next job goes on from there, which saves tape; cut it off with the printer's cutter button. Off: the printer feeds and cuts after every job.",
                        verbose_name="continuous printing",
                    ),
                ),
                ("is_active", models.BooleanField(default=True, verbose_name="active")),
                (
                    "is_default",
                    models.BooleanField(
                        default=False,
                        help_text="Used by the print actions in the admin.",
                        verbose_name="default printer",
                    ),
                ),
                (
                    "last_status",
                    models.JSONField(
                        blank=True,
                        editable=False,
                        null=True,
                        verbose_name="last status",
                    ),
                ),
                (
                    "last_status_at",
                    models.DateTimeField(
                        blank=True,
                        editable=False,
                        null=True,
                        verbose_name="last status at",
                    ),
                ),
                (
                    "agent",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="printers",
                        to="label_printing.printagent",
                        verbose_name="print agent",
                    ),
                ),
                (
                    "loaded_medium",
                    models.ForeignKey(
                        blank=True,
                        help_text="Zebra: the labels in the printer now; set it when changing labels. Only these are printed, after comparing their height with the label length the printer measured (it cannot tell their width).",
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="+",
                        to="label_printing.labelmedium",
                        verbose_name="loaded labels",
                    ),
                ),
            ],
            options={
                "verbose_name": "printer",
                "verbose_name_plural": "printers",
                "ordering": ("name",),
            },
        ),
        migrations.AddField(
            model_name="labelmedium",
            name="printer",
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.CASCADE,
                related_name="media",
                to="label_printing.printer",
                verbose_name="printer",
            ),
        ),
        migrations.CreateModel(
            name="PrintJob",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                ("layout_key", models.CharField(max_length=64, verbose_name="layout")),
                (
                    "subject_type",
                    models.CharField(max_length=32, verbose_name="subject type"),
                ),
                (
                    "subject_id",
                    models.PositiveBigIntegerField(
                        blank=True, null=True, verbose_name="subject ID"
                    ),
                ),
                (
                    "subject_label",
                    models.CharField(
                        blank=True, max_length=255, verbose_name="subject"
                    ),
                ),
                (
                    "label_code",
                    models.CharField(
                        blank=True, max_length=64, verbose_name="code in the QR code"
                    ),
                ),
                (
                    "snapshot",
                    models.JSONField(
                        blank=True, default=list, verbose_name="printed content"
                    ),
                ),
                (
                    "copies",
                    models.PositiveSmallIntegerField(default=1, verbose_name="copies"),
                ),
                (
                    "pages",
                    models.PositiveSmallIntegerField(default=1, verbose_name="labels"),
                ),
                (
                    "quality",
                    models.CharField(
                        choices=[
                            ("draft", "draft (fast)"),
                            ("standard", "standard"),
                            ("high", "high quality (slower)"),
                        ],
                        default="standard",
                        max_length=16,
                        verbose_name="print quality",
                    ),
                ),
                ("payload", models.BinaryField(blank=True, null=True)),
                (
                    "status",
                    models.CharField(
                        choices=[
                            ("waiting", "waiting for a printer"),
                            ("pending", "waiting"),
                            ("processing", "printing"),
                            ("done", "printed"),
                            ("sent", "sent, not confirmed"),
                            ("failed", "failed"),
                            ("expired", "expired"),
                        ],
                        default="pending",
                        max_length=16,
                        verbose_name="status",
                    ),
                ),
                (
                    "code",
                    models.CharField(blank=True, max_length=64, verbose_name="result"),
                ),
                ("detail", models.JSONField(blank=True, default=dict)),
                (
                    "printer_status",
                    models.JSONField(
                        blank=True, null=True, verbose_name="printer status"
                    ),
                ),
                (
                    "claimed_by",
                    models.CharField(
                        blank=True, max_length=64, verbose_name="processed by"
                    ),
                ),
                (
                    "request_id",
                    models.UUIDField(
                        blank=True, editable=False, null=True, unique=True
                    ),
                ),
                (
                    "outcome",
                    models.CharField(blank=True, max_length=96, verbose_name="label"),
                ),
                ("request", models.JSONField(blank=True, default=dict, editable=False)),
                (
                    "expires_at",
                    models.DateTimeField(
                        blank=True, null=True, verbose_name="waits until"
                    ),
                ),
                (
                    "created_at",
                    models.DateTimeField(auto_now_add=True, verbose_name="created at"),
                ),
                (
                    "ready_at",
                    models.DateTimeField(
                        default=django.utils.timezone.now, editable=False
                    ),
                ),
                (
                    "claimed_at",
                    models.DateTimeField(
                        blank=True, null=True, verbose_name="picked up at"
                    ),
                ),
                (
                    "finished_at",
                    models.DateTimeField(
                        blank=True, null=True, verbose_name="finished at"
                    ),
                ),
                (
                    "agent",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="+",
                        to="label_printing.printagent",
                        verbose_name="print agent",
                    ),
                ),
                (
                    "medium",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="+",
                        to="label_printing.labelmedium",
                        verbose_name="label medium",
                    ),
                ),
                (
                    "printer",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="jobs",
                        to="label_printing.printer",
                        verbose_name="printer",
                    ),
                ),
                (
                    "user",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="+",
                        to=settings.AUTH_USER_MODEL,
                        verbose_name="user",
                    ),
                ),
            ],
            options={
                "verbose_name": "print job",
                "verbose_name_plural": "print jobs",
                "ordering": ("-created_at",),
                "permissions": [("print_label", "Can print labels")],
            },
        ),
        migrations.AddConstraint(
            model_name="labelstock",
            constraint=models.UniqueConstraint(
                condition=models.Q(("code", ""), _negated=True),
                fields=("code",),
                name="label_stock_unique_code",
            ),
        ),
        migrations.AddIndex(
            model_name="printjob",
            index=models.Index(
                fields=["printer", "status", "created_at"],
                name="label_print_printer_ae3fd3_idx",
            ),
        ),
        migrations.AddField(
            model_name="printjob",
            name="batch",
            field=models.UUIDField(
                blank=True,
                db_index=True,
                editable=False,
                null=True,
                verbose_name="batch",
            ),
        ),
        migrations.CreateModel(
            name="LastLabel",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                (
                    "subject_type",
                    models.CharField(max_length=32, verbose_name="subject type"),
                ),
                ("subject_pk", models.CharField(max_length=64, verbose_name="subject")),
                (
                    "printed_at",
                    models.DateTimeField(
                        default=django.utils.timezone.now, verbose_name="printed at"
                    ),
                ),
                ("layout_key", models.CharField(max_length=64, verbose_name="layout")),
            ],
            options={
                "verbose_name": "last label",
                "verbose_name_plural": "last labels",
                "constraints": [
                    models.UniqueConstraint(
                        fields=("subject_type", "subject_pk"),
                        name="last_label_per_subject",
                    )
                ],
            },
        ),
    ]
