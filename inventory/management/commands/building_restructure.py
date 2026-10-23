from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError

from inventory.building_structure import DatasetError, apply_plan, load_dataset, make_plan


class Command(BaseCommand):
    help = ("Move the building structure (levels, rooms, areas) to the layout of a dataset; "
            "see docs/location-structure.md. Only shows the plan unless --apply is given.")

    def add_arguments(self, parser):
        parser.add_argument("dataset", help="path of the JSON dataset")
        parser.add_argument("--apply", action="store_true", help="write the changes to the database")
        parser.add_argument("--actor", help="username recorded in the location history")

    def handle(self, *args, dataset, apply, actor, **options):
        try:
            data = load_dataset(dataset)
        except (OSError, ValueError, DatasetError) as error:
            raise CommandError(f"Invalid dataset: {error}")
        user = None
        if actor:
            user = get_user_model().objects.filter(username=actor).first()
            if user is None:
                raise CommandError(f"Unknown user {actor}")

        plan = make_plan(data)
        for step in plan.steps:
            source = step.source if step.action == "move" else ""
            self.stdout.write(f"{step.action:<7}{source or '':<10} → {step.entry['path']:<14} {step.entry['name']}")
        for removal in plan.removals:
            if removal.location is None:
                self.stdout.write(f"{'done':<7}{removal.spec['old']:<10}   already removed")
                continue
            target = removal.spec.get("move_to") or "?"
            contents = [f"{len(removal.children)} locations"] if removal.children else []
            contents += [f"{removal.stock} stock entries"] if removal.stock else []
            moved = f", {' and '.join(contents)} to {target}" if contents else ""
            permanently = " (permanently)" if removal.spec.get("permanent") else ""
            self.stdout.write(f"{'remove':<7}{removal.spec['old']:<10}   {removal.location.name}{moved}{permanently}")
        for move in plan.moves:
            self.stdout.write(f"{'done' if move.done else 'move':<7}{move.code:<10} → {move.target}")
        for old_type, count in plan.retired:
            self.stdout.write(f"{'retire':<7}{old_type}: type and its {count} deleted locations are deleted permanently")
        for warning in plan.warnings:
            self.stdout.write(self.style.WARNING(f"Note: {warning}"))
        if plan.errors:
            raise CommandError("The dataset does not fit the database:\n" + "\n".join(plan.errors))

        counts = {action: sum(step.action == action for step in plan.steps) for action in ("move", "create", "update")}
        removed = sum(removal.location is not None for removal in plan.removals)
        moved_in = sum(not move.done for move in plan.moves)
        summary = (f"{counts['move']} moved, {counts['create']} created, {counts['update']} already in place, "
                   f"{removed} removed, {len(plan.retired)} types retired, {moved_in} containers moved in")
        if not apply:
            self.stdout.write(f"Dry run ({summary}). Nothing changed; run again with --apply.")
            return
        try:
            apply_plan(plan, actor=user)
        except DatasetError as error:
            raise CommandError(f"Nothing changed: {error}")
        self.stdout.write(self.style.SUCCESS(f"Applied: {summary}."))
