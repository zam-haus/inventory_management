import os

from django.core.management.base import BaseCommand, CommandError

from inventory.label_ids import labels, services
from inventory.models import LabelId
from label_printing import services as printing
from label_printing.models import Printer


class Command(BaseCommand):
    help = ("Render Brother label PNGs for the reserved IDs of a batch and mark them printed, "
            "or print them on a printer of the inventory (--print).")

    def add_arguments(self, parser):
        parser.add_argument("--batch", required=True)
        parser.add_argument("--printer", choices=labels.PRINTERS, help="PNGs for this printer model")
        parser.add_argument("--tape", type=int, help="PNGs (or with --print: the medium) for this tape width")
        parser.add_argument("--outdir", default="labels")
        parser.add_argument("--print", dest="print_on", metavar="PRINTER",
                            help="print on this printer of the inventory (its short name) instead of writing PNGs")
        parser.add_argument("--all", action="store_true",
                            help="also render IDs of the batch that were printed before")

    def handle(self, *args, batch, printer, tape, outdir, print_on, all, **options):
        if print_on:
            return self.print_batch(batch, print_on, tape, all)
        if not printer or not tape:
            raise CommandError("give --printer and --tape for PNGs, or --print PRINTER")
        if (printer, tape) not in labels.PROFILES:
            raise CommandError(f"PT-{printer} has no profile for {tape} mm tape; "
                               f"choose one of {labels.tapes(printer)}")
        ids = LabelId.objects.filter(batch=batch, status=LabelId.Status.RESERVED).order_by("code")
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

    def unprinted(self, batch, all):
        ids = LabelId.objects.filter(batch=batch, status=LabelId.Status.RESERVED).order_by("code")
        if not all:
            ids = ids.filter(printed_at__isnull=True)
        if not ids.exists():
            raise CommandError(f"no unprinted reserved IDs in batch {batch!r}")
        return ids

    def print_batch(self, batch, slug, tape, all):
        """Print through label_printing; printed_at is set as the printer reports the jobs done."""
        printer = Printer.objects.filter(slug=slug).first()
        if printer is None:
            raise CommandError(f"no printer {slug!r}; short names: {', '.join(Printer.objects.values_list('slug', flat=True))}")
        media = printer.media.order_by("-is_default", "name")
        medium = (media.filter(ptouch_tape=tape) if tape else media).first()
        if medium is None:
            raise CommandError(f"{printer} has no labels{f' with {tape} mm tape' if tape else ''}")
        try:
            jobs = printing.print_label_ids(self.unprinted(batch, all), printer=printer, medium=medium)
        except printing.PrintError as error:
            raise CommandError(str(error)) from None
        for job in jobs:
            job.refresh_from_db()
            self.stdout.write(f"job {job.pk}: {job.pages} labels, {job.message}")
