"""Which level, and which stacked part, a location is on.

Nothing stores it: a location is on the level it is in (the nearest level above it, by the location tree), and
in the stacked part (e.g. HBB.2) whose parent has `parts_stacked`. Levels of different houses with the same
number lie at about the same height (docs/standortregeln.md), so the map shows them together.
"""
from functools import cached_property

from inventory.models import Location
from inventory.structure_overview import LEVEL_CODE, code_order, level_label

from .models import LocationShape


def level_number(code):
    """The number of a level code ("WH-1" → -1), else None."""
    match = LEVEL_CODE.match(code or "")
    return int(match["level"]) if match else None


class Tree:
    """All active locations from one query, for resolving levels and stacked parts of many at once."""

    def __init__(self):
        self.nodes = {pk: (parent, structure, category, code) for pk, parent, structure, category, code in
                      Location.active.values_list("pk", "parent_location_id", "type__structure", "type__category",
                                                  "unique_identifier")}
        self._levels = {}

    @cached_property
    def stacked(self):
        return set(LocationShape.objects.filter(parts_stacked=True).values_list("location_id", flat=True))

    def parent(self, pk):
        return self.nodes[pk][0] if pk in self.nodes else None

    def code(self, pk):
        return self.nodes[pk][3] if pk in self.nodes else ""

    def category(self, pk):
        return self.nodes[pk][2] if pk in self.nodes else None

    def chain(self, pk):
        """pk and its ancestors, nearest first."""
        seen = set()
        while pk is not None and pk in self.nodes and pk not in seen:
            seen.add(pk)
            yield pk
            pk = self.nodes[pk][0]

    def level(self, pk):
        """pk of the level the location is on (itself, if it is one), else None."""
        if pk not in self._levels:
            self._levels[pk] = next((node for node in self.chain(pk) if self.nodes[node][1] == "level"), None)
        return self._levels[pk]

    def level_number(self, pk):
        level = self.level(pk)
        return level_number(self.code(level)) if level is not None else None

    def stack(self, pk):
        """(group, part): the stacked area the location is in and which of its parts, else None."""
        for node in self.chain(pk):
            parent = self.parent(node)
            if parent in self.stacked:
                return parent, node
        return None

    def depth(self, pk):
        return sum(1 for _node in self.chain(pk))

    def descendants(self, pk):
        """pks below the location (not itself)."""
        children = {}
        for node, (parent, *_rest) in self.nodes.items():
            children.setdefault(parent, []).append(node)
        found, pending = [], list(children.get(pk, ()))
        while pending:
            node = pending.pop()
            found.append(node)
            pending += children.get(node, ())
        return found

    def levels(self):
        """{number: [level pks]} of all levels with a code that tells their number, e.g. WH-1 and HH-1 for -1."""
        numbers = {}
        for pk, (_parent, structure, _category, code) in self.nodes.items():
            number = level_number(code) if structure == "level" else None
            if number is not None:
                numbers.setdefault(number, []).append(pk)
        return {number: sorted(pks, key=lambda pk: code_order(self.code(pk))) for number, pks in sorted(numbers.items())}


def label(number):
    return level_label(number)


def effective_shape(location):
    """(shape, source location, exact): the nearest location from here upwards that has a position; exact if it is
    this location. None if neither it nor anything above has one."""
    chain = list(location._self_and_ancestors())
    shapes = {shape.location_id: shape for shape in
              LocationShape.objects.filter(location__in=chain, geometry__isnull=False)}
    for node in chain:
        if node.pk in shapes:
            return shapes[node.pk], node, node.pk == location.pk
    return None
