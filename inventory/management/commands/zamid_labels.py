import os

from django.core.management.base import BaseCommand, CommandError

from inventory.zamid import labels, services
from inventory.models import ZamId


class Command(BaseCommand):
    help = "Render Brother label PNGs for the reserved IDs of a batch and mark them printed."

    def add_arguments(self, parser):
        parser.add_argument("--batch", required=True)
        parser.add_argument("--printer", choices=labels.PRINTERS, required=True)
        parser.add_argument("--tape", type=int, required=True)
        parser.add_argument("--outdir", default="labels")
        parser.add_argument("--all", action="store_true",
                            help="also render IDs of the batch that were printed before")

    def handle(self, *args, batch, printer, tape, outdir, all, **options):
        if (printer, tape) not in labels.PROFILES:
            raise CommandError(f"PT-{printer} has no profile for {tape} mm tape; "
                               f"choose one of {labels.tapes(printer)}")
        ids = ZamId.objects.filter(batch=batch, status=ZamId.Status.RESERVED).order_by("code")
        if not all:
            ids = ids.filter(printed_at__isnull=True)
        codes = list(ids.values_list("code", flat=True))
        if not codes:
            raise CommandError(f"no unprinted reserved IDs in batch {batch!r}")
        os.makedirs(outdir, exist_ok=True)
        for code in codes:
            path = os.path.join(outdir, labels.filename(code, printer, tape))
            with open(path, "wb") as f:
                f.write(labels.render(code, printer, tape))
            self.stdout.write(path)
        services.mark_printed(codes)
        self.stdout.write(self.style.SUCCESS(
            f"{len(codes)} labels written. Print them as raster in standard resolution, without scaling."))
