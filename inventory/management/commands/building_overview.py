from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.template.loader import render_to_string
from django.utils import timezone, translation
from django.utils.translation import gettext as _

from inventory.building_structure import DatasetError, load_dataset, overview_from_dataset, overview_from_db


class Command(BaseCommand):
    help = ("Write the levels-and-axes overview of the building structure as a standalone HTML page, "
            "from the database or, with --dataset, from a planned dataset.")

    def add_arguments(self, parser):
        parser.add_argument("--output", "-o", required=True, help="path of the HTML file to write")
        parser.add_argument("--dataset", help="show this JSON dataset instead of the database")
        parser.add_argument("--title", help="page title")

    def handle(self, *args, output, dataset, title, **options):
        with translation.override(settings.LANGUAGE_CODE):
            if dataset:
                try:
                    overview, source = overview_from_dataset(load_dataset(dataset)), _("Planned: %s") % Path(dataset).name
                except (OSError, ValueError, DatasetError) as error:
                    raise CommandError(f"Invalid dataset: {error}")
            else:
                overview, source = overview_from_db(), _("From the inventory")
            labels = {
                "level": _("Level"), "axis": _("Axis"), "noAxis": _("No axis"), "main": _("Main area:"),
                "name": _("Name:"), "old": _("was"), "fire": _("Free of fire load"), "within": _("within"),
                "codes": _("codes"), "parts": _("numbered parts")
            }
            html = render_to_string("inventory/building_overview.html", {
                "title": title or _("Levels and axes"), "source": source, "generated": timezone.now(),
                "overview": overview, "labels": labels,
            })
        Path(output).write_text(html, encoding="utf-8")
        self.stdout.write(f"Wrote {output}")
