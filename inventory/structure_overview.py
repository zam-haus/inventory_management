"""The levels-and-axes overview of the fixed building structure (``/loc/structure/``).

Levels run across, axes down; each level, room and area is shown with its code, purpose or name,
description, team badges and the fire-load mark. Containers such as shelves and boxes are left out.
"""
import re
from dataclasses import dataclass, field

from accounts.models import Team
from .models import Location, LocationAxis

LEVEL_CODE = re.compile(r"^(?P<house>[A-Za-z]+)(?P<level>[+-]\d+)$")
# "Werkhaus -1" → "Werkhaus"
LEVEL_NUMBER = re.compile(r"\s+[+-]?\d+$")
# Columns with more rooms and areas than this in one level show them in two columns.
WIDE = 5


def _natural(code):
    """Sort key: LAG2 before LAG10."""
    return [int(part) if part.isdigit() else part for part in re.split(r"(\d+)", code)]


def code_order(code):
    """Sort key of codes among siblings: numbers by value (LAG2 before LAG10), levels by their number (WH-1 before
    WH+0, as + sorts before - as text)."""
    match = LEVEL_CODE.match(code)
    if match:
        return [match["house"].upper(), int(match["level"]), ""]
    return _natural(code.upper())


def level_label(number):
    return f"+{number}" if number >= 0 else str(number)


@dataclass
class Part:
    """A room or area below a room or area; numbered parts get their code relative to it (``.1``)."""
    location: Location
    code: str
    coded: bool


@dataclass
class Node:
    location: Location
    parts: list = field(default_factory=list)

    @property
    def kind(self):
        if self.location.outdoor:
            return "outdoor"
        return "area" if self.location.type.structure == "area" else "room"


@dataclass
class Cell:
    present: bool
    wide: bool = False
    mains: list = field(default_factory=list)  # levels whose main area is drawn in this axis
    nodes: list = field(default_factory=list)


def _parts(children, location, prefix=""):
    parts = []
    for child in sorted(children.get(location.pk, []), key=lambda c: _natural(c.short_name)):
        code = child.short_name if child.type.unique else f"{prefix}{child.short_name}"
        parts.append(Part(child, code, child.type.unique))
        parts += _parts(children, child, f"{code}.")
    return parts


def structure_overview():
    """Houses, axes and levels of the building structure, arranged as rows (levels) and columns (axes)."""
    structure = Location.active.exclude(type__structure="").select_related("type", "axis").prefetch_related(
        "responsible_teams__group", "responsible_teams__parent")
    children = {}
    for location in structure:
        children.setdefault(location.parent_location_id, []).append(location)

    houses, levels, nodes = {}, [], []
    for level in children.get(None, []):
        match = LEVEL_CODE.match(level.short_name)
        if level.type.structure != "level" or not match:
            continue
        house, number = match["house"], int(match["level"])
        houses.setdefault(house, {"code": house, "name": LEVEL_NUMBER.sub("", level.name), "levels": set()})
        houses[house]["levels"].add(number)
        levels.append((house, number, level))
        for child in children.get(level.pk, []):
            nodes.append((house, number, Node(child, _parts(children, child))))

    # Columns: the axes in use, in their order, then one for rooms without an axis.
    used = {node.location.axis_id for _house, _number, node in nodes} | {
        level.axis_id for _house, _number, level in levels}
    axes = [axis for axis in LocationAxis.objects.all() if axis.pk in used]
    columns = [{"axis": axis, "key": axis.pk} for axis in axes]
    if None in {node.location.axis_id for _house, _number, node in nodes}:
        columns.append({"axis": None, "key": None})
    for column in columns:
        in_column = {house for house, _number, node in nodes if node.location.axis_id == column["key"]}
        column["house"] = in_column.pop() if len(in_column) == 1 else ""

    numbers = sorted({number for _house, number, _level in levels}, reverse=True)
    rows = []
    for number in numbers:
        cells = []
        for column in columns:
            present = not column["house"] or number in houses[column["house"]]["levels"]
            cell = Cell(present)
            cell.nodes = sorted((node for _house, n, node in nodes if n == number
                                 and node.location.axis_id == column["key"]),
                                key=lambda node: _natural(node.location.short_name))
            cell.wide = len(cell.nodes) > WIDE
            cells.append(cell)
        rows.append({"number": number, "label": level_label(number), "cells": cells})
    # A level's own (main) area is drawn in its axis, else in the first column of its house.
    for house, number, level in levels:
        index = next((i for i, c in enumerate(columns) if c["key"] == level.axis_id and level.axis_id), None)
        if index is None:
            index = next((i for i, c in enumerate(columns) if c["house"] == house), 0)
        if columns:
            rows[numbers.index(number)]["cells"][index].mains.append(level)

    # Header: consecutive columns of one house share its name.
    groups = []
    for column in columns:
        if groups and groups[-1]["house"] == column["house"]:
            groups[-1]["span"] += 1
        else:
            groups.append({"house": column["house"], "name": houses.get(column["house"], {}).get("name", ""),
                           "span": 1})
    for column in columns:
        column["wide"] = any(row["cells"][columns.index(column)].wide for row in rows)

    parts = [part for _house, _number, node in nodes for part in node.parts]
    return {
        "groups": groups, "columns": columns, "rows": rows,
        "teams": Team.objects.select_related("group", "parent").exclude(code="").order_by("code"),
        "coded": len(levels) + len(nodes) + sum(part.coded for part in parts),
        "numbered": sum(not part.coded for part in parts),
    }
