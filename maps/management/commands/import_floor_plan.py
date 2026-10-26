"""Imports a floor plan file for a level or another space, e.g. from a building survey (docs/maps.md)."""
from pathlib import Path

from django.core.files import File
from django.core.management.base import BaseCommand, CommandError

from inventory.models import Location

from ... import plans
from ...levels import Tree
from ...models import FloorPlan


def fractions(value):
    parts = [float(part) for part in value.split(",")]
    if len(parts) != 4:
        raise ValueError
    return parts


class Command(BaseCommand):
    help = "Adds a floor plan (PDF, PNG, JPEG, WebP or SVG) to a level."

    def add_arguments(self, parser):
        parser.add_argument("file")
        where = parser.add_mutually_exclusive_group(required=True)
        where.add_argument("--level", type=int, help="Number of the level, e.g. -1.")
        where.add_argument("--location", help="Code of a level (WH-1: its number) or of a stacked part (HBB.2).")
        parser.add_argument("--name", default="", help="Where the plan comes from.")
        parser.add_argument("--page", type=int, default=1)
        parser.add_argument("--dpi", type=int, default=300)
        parser.add_argument("--crop", type=fractions, help="left,top,right,bottom as fractions of the page.")
        parser.add_argument("--inactive", action="store_true", help="Not shown on the map yet.")
        parser.add_argument("--notes", default="", help="Internal notes, e.g. where the file came from.")

    def handle(self, *args, **options):
        path = Path(options["file"])
        if not path.is_file():
            raise CommandError(f"{path} not found")
        level, location = options["level"], None
        if options["location"]:
            location = Location.active.filter(unique_identifier__iexact=options["location"]).first()
            if location is None:
                raise CommandError(f"no location {options['location']}")
            level = Tree().level_number(location.pk)
            if level is None:
                raise CommandError(f"{location.unique_identifier} is not on a level")
            if location.type.structure == "level":
                location = None  # a plan of the whole level
        plan = FloorPlan(level=level, location=location, name=options["name"] or path.stem, page=options["page"],
                         dpi=options["dpi"], crop=options["crop"], active=not options["inactive"], notes=options["notes"])
        with path.open("rb") as source:
            plan.source.save(path.name, File(source), save=False)
        try:
            plans.save(plan)
        except plans.PlanError as error:
            plan.source.delete(save=False)
            raise CommandError(str(error)) from error
        self.stdout.write(f"level {level:+d}: plan {plan.pk} ({plan.image_width} × {plan.image_height} px)")
