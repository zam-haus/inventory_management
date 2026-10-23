from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand
from django.template.loader import render_to_string
from django.utils import timezone, translation
from django.utils.translation import gettext as _

from inventory.structure_overview import overview_from_db


class Command(BaseCommand):
    help = "Write the levels-and-axes overview of the building structure as a standalone HTML page."

    def add_arguments(self, parser):
        parser.add_argument("--output", "-o", required=True, help="path of the HTML file to write")
        parser.add_argument("--title", help="page title")

    def handle(self, *args, output, title, **options):
        with translation.override(settings.LANGUAGE_CODE):
            labels = {
                "level": _("Level"), "axis": _("Axis"), "noAxis": _("No axis"), "main": _("Main area:"),
                "name": _("Name:"), "fire": _("Free of fire load"), "within": _("within"),
                "codes": _("codes"), "parts": _("numbered parts")
            }
            html = render_to_string("inventory/building_overview.html", {
                "title": title or _("Levels and axes"), "source": _("From the inventory"),
                "generated": timezone.now(), "overview": overview_from_db(), "labels": labels,
            })
        Path(output).write_text(html, encoding="utf-8")
        self.stdout.write(f"Wrote {output}")
