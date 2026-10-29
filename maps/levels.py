"""Which level, and which stacked part, a location is on.

Nothing stores it: a location is on the level it is in (the nearest level above it, by the location tree), and
in the stacked part (e.g. HBB.2) whose parent has `parts_stacked`. Levels of different houses with the same
number lie at about the same height (docs/standortregeln.md), so the map shows them together.
"""
from functools import cached_property

from django.core.exceptions import EmptyResultSet
from django.db import connection
from django.db.models import QuerySet

from inventory.models import Location, LocationType
from inventory.structure_overview import LEVEL_CODE, code_order, level_label

from .models import LocationShape


def level_number(code):
    """The number of a level code ("WH-1" → -1), else None."""
    match = LEVEL_CODE.match(code or "")
    return int(match["level"]) if match else None


class Tree:
    """Where active locations are in the location tree, loaded as needed: a location with everything above it, in one
    query for many (load), instead of the whole tree (a million locations took seconds and hundreds of MB)."""

    CHUNK = 900  # ids per query (SQLite allows 999 parameters)
    FEW = 50  # up to this many at once: one recursive query; for more, one query per step up the tree (the
    # recursive query then hashed the whole location table in each step)

    def __init__(self):
        self.nodes = {}  # pk: (parent, structure, category, code) of the locations loaded so far
        self._absent = set()  # asked for, but not active
        self._levels = {}

    def load(self, pks):
        """Loads these locations and those above them: pks, or a queryset of location ids."""
        if isinstance(pks, QuerySet):
            try:
                sql, params = pks.query.sql_with_params()
            except EmptyResultSet:  # e.g. pk__in=[]
                return
            self._climb(self._rows(f"l.id IN ({sql})", params))
            return
        missing = [pk for pk in dict.fromkeys(pks) if pk is not None and pk not in self.nodes and pk not in self._absent]
        if len(missing) > self.FEW:
            self._climb(missing)
            return
        if missing:
            self._ancestors(missing)
            self._absent.update(pk for pk in missing if pk not in self.nodes)

    def _columns(self):
        location, kind = Location._meta, LocationType._meta
        parent = location.get_field("parent_location").column
        return (f"SELECT l.id, l.{parent}, t.structure, t.category, l.unique_identifier FROM {location.db_table} l "
                f"JOIN {kind.db_table} t ON t.id = l.{location.get_field('type').column} "
                f"WHERE NOT l.is_deleted AND NOT l.is_reserved")

    def _store(self, cursor):
        parents = []
        for pk, parent_pk, structure, category, code in cursor.fetchall():
            self.nodes[pk] = (parent_pk, structure, category, code)
            parents.append(parent_pk)
        return parents

    def _rows(self, condition, params):
        """Loads the active locations matching an SQL condition on l; their parents' pks."""
        with connection.cursor() as cursor:
            cursor.execute(f"{self._columns()} AND {condition}", params)
            return self._store(cursor)

    def _climb(self, pks):
        """Loads these locations, then their parents, and so on up: one query per step (and per CHUNK)."""
        while pks:
            pending = [pk for pk in dict.fromkeys(pks) if pk is not None and pk not in self.nodes
                       and pk not in self._absent]
            pks = []
            for start in range(0, len(pending), self.CHUNK):
                chunk = pending[start:start + self.CHUNK]
                pks += self._rows(f"l.id IN ({', '.join(['%s'] * len(chunk))})", chunk)
            self._absent.update(pk for pk in pending if pk not in self.nodes)

    def _ancestors(self, pks):
        """Loads a few locations with everything above them in one recursive query."""
        location = Location._meta
        parent = location.get_field("parent_location").column
        seed = f"SELECT id FROM {location.db_table} WHERE id IN ({', '.join(['%s'] * len(pks))})"
        with connection.cursor() as cursor:
            cursor.execute(f"WITH RECURSIVE up(id) AS ({seed} UNION SELECT l.{parent} FROM {location.db_table} l "
                           f"JOIN up ON l.id = up.id WHERE l.{parent} IS NOT NULL) "
                           f"{self._columns()} AND l.id IN (SELECT id FROM up)", pks)
            self._store(cursor)

    def _node(self, pk):
        if pk is not None and pk not in self.nodes and pk not in self._absent:
            self.load([pk])
        return self.nodes.get(pk)

    @cached_property
    def stacked(self):
        return set(LocationShape.objects.filter(parts_stacked=True).values_list("location_id", flat=True))

    def parent(self, pk):
        node = self._node(pk)
        return node[0] if node else None

    def code(self, pk):
        node = self._node(pk)
        return node[3] if node else ""

    def category(self, pk):
        node = self._node(pk)
        return node[2] if node else None

    def chain(self, pk):
        """pk and its ancestors, nearest first."""
        self._node(pk)  # loads the whole chain at once
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

    def children(self, pk):
        """pks of the active locations right below it, by code."""
        return list(Location.active.filter(parent_location=pk).order_by("unique_identifier").values_list("pk", flat=True))

    def descendants(self, pk):
        """pks below the location (not itself), through active locations only."""
        location = Location._meta
        parent = location.get_field("parent_location").column
        active = "NOT l.is_deleted AND NOT l.is_reserved"
        with connection.cursor() as cursor:
            cursor.execute(f"WITH RECURSIVE down(id) AS (SELECT l.id FROM {location.db_table} l WHERE l.{parent} = %s "
                           f"AND {active} UNION SELECT l.id FROM {location.db_table} l JOIN down ON l.{parent} = down.id "
                           f"WHERE {active}) SELECT id FROM down", [pk])
            return [row[0] for row in cursor.fetchall()]

    def levels(self):
        """{number: [level pks]} of all levels with a code that tells their number, e.g. WH-1 and HH-1 for -1."""
        numbers = {}
        for pk, code in Location.active.filter(type__structure="level").values_list("pk", "unique_identifier"):
            number = level_number(code)
            if number is not None:
                numbers.setdefault(number, []).append(pk)
        self.load(pk for pks in numbers.values() for pk in pks)
        return {number: sorted(pks, key=lambda pk: code_order(self.code(pk))) for number, pks in sorted(numbers.items())}

    def on_level(self, pks, number):
        """Those of the pks (or of a queryset of location ids) that are on the level with this number."""
        if not isinstance(pks, QuerySet):
            pks = list(pks)
        self.load(pks)  # a queryset in one query
        return [pk for pk in pks if self.level_number(pk) == number]


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
