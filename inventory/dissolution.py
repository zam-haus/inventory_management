"""Validate a plan that moves, deletes or keeps a location's contents, optionally deleting the location itself."""
import hashlib
import json

from django.core.exceptions import ValidationError
from django.utils.translation import gettext as _

from .models import ItemLocation, Location, UniqueItem
from .label_ids.lookup import annotate_label_code


class DissolutionPlan:
    """Loads the location's part of the tree, not the whole inventory: the location with its sub-locations (all
    below it when recursive, else two levels for the checks), what is stored there, the locations above it and,
    once a plan names them, its destinations (validate)."""

    def __init__(self, root, recursive=False, lock=False, delete_root=True):
        self.lock = lock
        self.locations, self.entries = {}, {}
        self.complete = set()  # locations whose sub-locations and stock entries are loaded
        self.root = next(iter(self._load_locations(pk=root.pk)), None)
        if self.root is None:
            raise ValidationError(_("The inventory changed. Review the plan again."))
        self.recursive = recursive
        self.delete_root = delete_root
        self._load_ancestors([root.pk])
        descendants, pending, depth = set(), [root.pk], 0
        # Without recursion, the sub-locations' own sub-locations show whether deleting one would orphan them.
        while pending and (recursive or depth < 2):
            pending = [location.pk for location in self._load_locations(parent_location_id__in=pending)]
            descendants.update(pending)
            depth += 1
        children = [pk for pk in descendants if self.locations[pk].parent_location_id == root.pk]
        scope = {root.pk} | descendants if recursive else {root.pk}
        selected_locations = descendants if recursive else set(children)
        # Stock and unique items only matter where the plan may delete a location: the root and the rows.
        self._load_entries(scope | selected_locations)
        self.complete |= scope | selected_locations
        # Unique items are never dissolved with a location; each one is moved or disposed on its own.
        self.unique_item_locations = dict(UniqueItem.active.filter(
            location_id__in=scope | selected_locations).values_list("pk", "location_id"))
        # Unique items only block deleting the root; they may stay in a location that is kept.
        self.root_unique_items = annotate_label_code(
            UniqueItem.active.filter(location_id=root.pk).select_related("item", "location")
        ).order_by("item__name", "pk")
        self.blocking_unique_items = self.root_unique_items if delete_root else UniqueItem.active.none()
        self.rows = [
            {"kind": "item", "object": entry, "key": f"item_{entry.pk}"}
            for entry in sorted(self.entries.values(), key=lambda entry: entry.pk) if entry.location_id in scope
        ] + [
            {"kind": "location", "object": location, "key": f"location_{location.pk}"}
            for location in sorted(self.locations.values(), key=lambda location: location.pk)
            if location.pk in selected_locations
        ]
    def _load_locations(self, **filters):
        """Loads the active locations matching the filters that are not loaded yet; returns them."""
        locations = Location.active.filter(**filters).select_related("type").order_by("pk")
        if self.lock:
            locations = locations.select_for_update(of=("self",))
        found = [location for location in locations if location.pk not in self.locations]
        self.locations.update((location.pk, location) for location in found)
        return found

    def _load_ancestors(self, pks):
        """Loads the locations above these, so that a cycle shows when walking up from a moved location."""
        pending = {self.locations[pk].parent_location_id for pk in pks if pk in self.locations}
        while pending := {pk for pk in pending if pk is not None and pk not in self.locations}:
            pending = {location.parent_location_id for location in self._load_locations(pk__in=pending)}

    def _load_entries(self, location_pks):
        entries = ItemLocation.objects.filter(location_id__in=location_pks).select_related(
            "item__measurement_unit", "location").prefetch_related("item__itemimage_set").order_by("pk")
        if self.lock:
            entries = entries.select_for_update(of=("self",))
        self.entries.update((entry.pk, entry) for entry in entries)

    def _load_destinations(self, operations):
        """Loads the destinations with what the checks need: the locations above them, their sub-locations (short
        names) and their stock entries (one per item and location)."""
        pks = {destination for _kind, _pk, action, destination in operations
               if action == "move" and destination is not None} - self.complete
        if not pks:
            return
        self._load_locations(pk__in=pks)
        self._load_ancestors(pks)
        self._load_locations(parent_location_id__in=pks)
        self._load_entries(pks)
        self.complete |= pks

    def fingerprint(self, operations):
        # Includes quantities, hierarchy and type rules: confirmation must never
        # silently operate on different inventory than the reviewed snapshot. Its part of the inventory: the
        # location's (see __init__) and that of the plan's destinations.
        self._load_destinations(operations)
        state = [
            [(loc.pk, loc.parent_location_id, loc.name, loc.short_name,
              loc.unique_identifier, loc.type_id, loc.type.moveable,
              loc.type.no_sublocations, loc.type.unique)
             for loc in sorted(self.locations.values(), key=lambda loc: loc.pk)],
            [(entry.pk, entry.item_id, entry.location_id, str(entry.amount),
              entry.item.name, entry.item.measurement_unit_id, entry.item.is_deleted)
             for entry in sorted(self.entries.values(), key=lambda entry: entry.pk)],
            sorted(self.unique_item_locations.items()),
        ]
        return hashlib.sha256(json.dumps(state).encode()).hexdigest()

    def validate(self, operations):
        if self.delete_root and self.root.pk in self.unique_item_locations.values():
            raise ValidationError(_("Unique items are still stored here. Move them or remove them from the inventory first."))
        expected = {(row["kind"], row["object"].pk) for row in self.rows}
        if len(operations) != len(expected) or {(op[0], op[1]) for op in operations} != expected:
            raise ValidationError(_("The inventory changed. Review the plan again."))
        self._load_destinations(operations)
        if not self.delete_root and all(op[2] == "keep" for op in operations):
            raise ValidationError(_("Nothing to do. Choose a destination or deletion for at least one entry."))
        deleted = {self.root.pk} if self.delete_root else set()
        parents = {pk: loc.parent_location_id for pk, loc in self.locations.items()}
        item_locations = {pk: entry.location_id for pk, entry in self.entries.items()}
        moved_locations = set()
        for kind, pk, action, destination in operations:
            if action not in ("move", "delete", "keep"):
                raise ValidationError(_("Choose an action for every entry."))
            if action == "keep":
                continue
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

        if deleted & set(self.unique_item_locations.values()):
            raise ValidationError(_("A location selected for deletion still contains unique items. Move them or remove them from the inventory first."))

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
                parent = parents.get(parent)  # above the loaded locations nothing moves

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

    def deleted_locations(self, operations):
        """Locations the plan deletes, including the root when it is dissolved."""
        deleted = {pk for kind, pk, action, _dest in operations if kind == "location" and action == "delete"}
        return (deleted | {self.root.pk}) if self.delete_root else deleted

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
                location = Location.active.get(pk=pk)
                if not location.children.filter(is_deleted=False).exists() and not location.itemlocation_set.exists():
                    location.delete()
                    pending_deletes.remove(pk)
                    progress = True
            for pk, destination in pending_moves[:]:
                location = Location.active.get(pk=pk)
                location.parent_location = Location.active.get(pk=destination)
                try:
                    location.full_clean(exclude=["unique_identifier", "locatable_identifier", "descriptive_identifier"])
                except ValidationError:
                    continue
                location.save()
                pending_moves.remove((pk, destination))
                progress = True
            if not progress:
                raise ValidationError(_("These location moves or deletions conflict. Review the destinations and empty locations."))

        if not self.delete_root:
            return
        root = Location.active.get(pk=self.root.pk)
        if root.children.filter(is_deleted=False).exists() or root.itemlocation_set.exists():
            raise ValidationError(_("The location is not empty and cannot be deleted."))
        root.delete()
