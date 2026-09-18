"""Validate a complete evacuation plan before changing or deleting any records."""
import hashlib
import json

from django.core.exceptions import ValidationError
from django.utils.translation import gettext as _

from .models import ItemLocation, Location


class DissolutionPlan:
    def __init__(self, root, recursive=False, lock=False):
        locations = Location.objects.select_related("type").order_by("pk")
        entries = ItemLocation.objects.select_related("item__measurement_unit", "location").prefetch_related("item__itemimage_set").order_by("pk")
        if lock:
            locations = locations.select_for_update(of=("self",))
            entries = entries.select_for_update(of=("self",))
        self.locations = {location.pk: location for location in locations}
        self.entries = {entry.pk: entry for entry in entries}
        self.root = self.locations.get(root.pk)
        if self.root is None:
            raise ValidationError(_("The inventory changed. Review the plan again."))
        self.recursive = recursive
        descendants, pending = set(), [root.pk]
        children = {}
        for location in self.locations.values():
            children.setdefault(location.parent_location_id, []).append(location.pk)
        while pending:
            for pk in children.get(pending.pop(), []):
                if pk not in descendants:
                    descendants.add(pk)
                    pending.append(pk)
        scope = {root.pk} | descendants if recursive else {root.pk}
        selected_locations = descendants if recursive else set(children.get(root.pk, []))
        self.rows = [
            {"kind": "item", "object": entry, "key": f"item_{entry.pk}"}
            for entry in self.entries.values() if entry.location_id in scope
        ] + [
            {"kind": "location", "object": location, "key": f"location_{location.pk}"}
            for location in self.locations.values() if location.pk in selected_locations
        ]

    def fingerprint(self):
        # Includes quantities, hierarchy and type rules: confirmation must never
        # silently operate on different inventory than the reviewed snapshot.
        state = [
            [(loc.pk, loc.parent_location_id, loc.name, loc.short_name,
              loc.unique_identifier, loc.type_id, loc.type.moveable,
              loc.type.no_sublocations, loc.type.unique) for loc in self.locations.values()],
            [(entry.pk, entry.item_id, entry.location_id, str(entry.amount),
              entry.item.name, entry.item.measurement_unit_id)
             for entry in self.entries.values()],
        ]
        return hashlib.sha256(json.dumps(state).encode()).hexdigest()

    def validate(self, operations):
        expected = {(row["kind"], row["object"].pk) for row in self.rows}
        if len(operations) != len(expected) or {(op[0], op[1]) for op in operations} != expected:
            raise ValidationError(_("The inventory changed. Review the plan again."))
        deleted = {self.root.pk}
        parents = {pk: loc.parent_location_id for pk, loc in self.locations.items()}
        item_locations = {pk: entry.location_id for pk, entry in self.entries.items()}
        moved_locations = set()
        for kind, pk, action, destination in operations:
            if action not in ("move", "delete"):
                raise ValidationError(_("Choose an action for every entry."))
            if action == "delete":
                if kind == "location":
                    deleted.add(pk)
                else:
                    del item_locations[pk]
                continue
            if destination not in self.locations:
                raise ValidationError(_("Choose a destination for every entry to move."))
            if kind == "location":
                if not self.locations[pk].type.moveable:
                    raise ValidationError(_("Moving is disabled for this location type."))
                if self.locations[destination].type.no_sublocations:
                    raise ValidationError(_("This destination cannot contain sub-locations."))
                parents[pk] = destination
                moved_locations.add(pk)
            else:
                item_locations[pk] = destination

        for pk, parent in parents.items():
            if pk in deleted:
                continue
            if parent in deleted:
                raise ValidationError(_("A location selected for deletion still has sub-locations. Move or delete them first."))
            visited = {pk}
            while parent is not None:
                if parent in visited:
                    raise ValidationError(_("Location tree may not contain cycles."))
                visited.add(parent)
                parent = parents[parent]

        occupied = {}
        for pk, destination in item_locations.items():
            if destination in deleted:
                raise ValidationError(_("A location selected for deletion still contains items. Move or delete its stock entries first."))
            key = (self.entries[pk].item_id, destination)
            if key in occupied:
                raise ValidationError(_("The same item would have two stock entries at one destination. Choose another destination; quantities are not merged automatically."))
            occupied[key] = pk

        siblings = {}
        for pk, parent in parents.items():
            if pk in deleted:
                continue
            key = (parent, self.locations[pk].short_name)
            if key in siblings and (pk in moved_locations or siblings[key] in moved_locations):
                raise ValidationError(_("Two sub-locations would have the same short name at the destination."))
            siblings[key] = pk

    def review_rows(self, operations):
        rows = []
        for kind, pk, action, destination in operations:
            rows.append({
                "kind": kind, "object": (self.entries if kind == "item" else self.locations)[pk],
                "action": action, "destination": self.locations.get(destination),
            })
        return rows

    def apply(self, operations):
        """Called only after signed confirmation, inside a locked transaction."""
        self.validate(operations)
        # Remove only stock associations; Item objects are never deleted.
        for kind, pk, action, destination in operations:
            if kind == "item" and action == "delete":
                self.entries[pk].delete()

        # Process stock moves whose targets are free before dependent moves.
        pending_items = [(pk, dest) for kind, pk, action, dest in operations if kind == "item" and action == "move"]
        while pending_items:
            progress = False
            for pk, destination in pending_items[:]:
                entry = ItemLocation.objects.get(pk=pk)
                if ItemLocation.objects.filter(item_id=entry.item_id, location_id=destination).exclude(pk=pk).exists():
                    continue
                entry.location_id = destination
                entry.save()
                pending_items.remove((pk, destination))
                progress = True
            if not progress:
                raise ValidationError(_("These stock moves depend on each other. Choose different destinations."))

        pending_moves = [(pk, dest) for kind, pk, action, dest in operations if kind == "location" and action == "move"]
        pending_deletes = [pk for kind, pk, action, _dest in operations if kind == "location" and action == "delete"]
        while pending_moves or pending_deletes:
            progress = False
            # Empty descendants are deleted before their parents.
            for pk in pending_deletes[:]:
                location = Location.objects.get(pk=pk)
                if not location.children.exists() and not location.itemlocation_set.exists():
                    location.delete()
                    pending_deletes.remove(pk)
                    progress = True
            for pk, destination in pending_moves[:]:
                location = Location.objects.get(pk=pk)
                location.parent_location = Location.objects.get(pk=destination)
                try:
                    location.full_clean(exclude=["unique_identifier", "locatable_identifier", "descriptive_identifier"])
                except ValidationError:
                    continue
                location.save()
                pending_moves.remove((pk, destination))
                progress = True
            if not progress:
                raise ValidationError(_("These location moves or deletions conflict. Review the destinations and empty locations."))

        root = Location.objects.get(pk=self.root.pk)
        if root.children.exists() or root.itemlocation_set.exists():
            raise ValidationError(_("The location is not empty and cannot be deleted."))
        root.delete()
