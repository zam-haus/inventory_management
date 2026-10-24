from django.core.management.base import BaseCommand, CommandError

from inventory.models import LabelId
from label_printing import services as printing
from label_printing.models import Printer


class Command(BaseCommand):
    help = ("Print the reserved IDs of a batch on a printer of the inventory, with the medium's first ZAMid label "
            "template; their printed at is set as the printer reports the jobs done.")

    def add_arguments(self, parser):
        parser.add_argument("--batch", required=True)
        parser.add_argument("--print", dest="print_on", metavar="PRINTER", required=True,
                            help="the printer's short name")
        parser.add_argument("--tape", type=int, help="the medium with this tape width (else the default medium)")
        parser.add_argument("--all", action="store_true", help="also IDs of the batch that were printed before")

    def handle(self, *args, batch, print_on, tape, all, **options):
        printer = Printer.objects.filter(slug=print_on).first()
        if printer is None:
            raise CommandError(f"no printer {print_on!r}; short names: {', '.join(Printer.objects.values_list('slug', flat=True))}")
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

    def unprinted(self, batch, all):
        ids = LabelId.objects.filter(batch=batch, status=LabelId.Status.RESERVED).order_by("code")
        if not all:
            ids = ids.filter(printed_at__isnull=True)
        if not ids.exists():
            raise CommandError(f"no unprinted reserved IDs in batch {batch!r}")
        return ids
