"""The levels-and-axes overview of the fixed building structure (``manage.py building_overview``).

Levels run across, axes down; each level, room and area is shown with its code, purpose or name,
description, team badges and the fire-load mark. Containers such as shelves and boxes are left out.
"""
import re

from accounts.models import Team
from .models import Location, LocationAxis

LEVEL_CODE = re.compile(r"^(?P<house>[A-Za-z]+)(?P<level>[+-]\d+)$")
# "Werkhaus -1" → "Werkhaus"
LEVEL_NUMBER = re.compile(r"\s+[+-]?\d+$")


def _team_badges(teams):
    return [team.code or team.group.name for team in teams]


def _team_legend(teams):
    legend = {}
    for team in teams:
        if not team.code:
            continue
        legend[team.code] = {
            "n": team.group.name, "c": team.badge_color, "t": team.badge_text_color,
            "parent": team.parent.code if team.parent_id and team.parent.code else "",
        }
    return legend


def _kind(structure, outdoor):
    return "o" if outdoor else "b" if structure == "area" else ""


def _flatten(children_of, parent_key, prefix=""):
    """The parts below a node as one list; numbered parts get their code relative to the node."""
    kids = []
    for child in children_of(parent_key):
        relative = child["code"] if child["global"] else f"{prefix}{child['code']}"
        kids.append({**child["kid"], "c": relative, "g": child["global"]})
        kids += _flatten(children_of, child["key"], f"{relative}.")
    return kids


def _finish(houses, axes, nodes, mains, teams):
    """Arrange the collected nodes for the overview template."""
    used = {(n["a"] or 0) for n in nodes} | {(m["a"] or 0) for m in mains}
    columns = [a for a in axes if a["n"] in used]
    if 0 in used:
        columns.append({"n": 0, "name": ""})
    for column in columns:
        in_axis = [n for n in nodes if (n["a"] or 0) == column["n"]]
        column["h"] = next(iter({n["h"] for n in in_axis}), "") if len({n["h"] for n in in_axis}) == 1 else ""
        per_cell = {}
        for n in in_axis:
            per_cell[(n["h"], n["l"])] = per_cell.get((n["h"], n["l"]), 0) + 1
        column["wide"] = max(per_cell.values(), default=0) > 5
    for n in nodes:
        n["a"] = n["a"] or 0
    for m in mains:
        m["a"] = m["a"] or next((c["n"] for c in columns if c["h"] == m["h"]), 0)
    levels = sorted({lvl for house in houses.values() for lvl in house["levels"]}, reverse=True)
    return {"houses": houses, "axes": columns, "levels": levels, "nodes": nodes, "mains": mains, "teams": teams}


def overview_from_db():
    houses, nodes, mains = {}, [], []
    axes = [{"n": axis.number, "name": axis.name} for axis in LocationAxis.objects.all()]
    structure = Location.objects.filter(is_deleted=False).exclude(type__structure="").select_related(
        "type", "axis").prefetch_related("responsible_teams__group")
    by_parent = {}
    for location in structure:
        by_parent.setdefault(location.parent_location_id, []).append(location)

    def kid(location):
        return {"code": location.short_name, "global": location.type.unique, "key": location.pk, "kid": {
            "n": location.name, "z": location.purpose, "d": location.physical_description,
            "t": _team_badges(location.responsible_teams.all()), "bf": location.fire_load_free}}

    def children_of(pk):
        return [kid(child) for child in sorted(by_parent.get(pk, []), key=lambda c: c.short_name)]

    for level in by_parent.get(None, []):
        match = LEVEL_CODE.match(level.short_name)
        if level.type.structure != "level" or not match:
            continue
        house, number = match["house"], int(match["level"])
        info = houses.setdefault(house, {"name": LEVEL_NUMBER.sub("", level.name), "levels": []})
        info["levels"].append(number)
        mains.append({"h": house, "l": number, "a": level.axis.number if level.axis else None, "n": level.name,
                      "z": level.purpose, "d": level.physical_description,
                      "t": _team_badges(level.responsible_teams.all()), "bf": level.fire_load_free})
        for child in by_parent.get(level.pk, []):
            nodes.append({
                "h": house, "l": number, "a": child.axis.number if child.axis else None, "c": child.short_name,
                "n": child.name, "k": _kind(child.type.structure, child.outdoor), "z": child.purpose,
                "d": child.physical_description, "t": _team_badges(child.responsible_teams.all()),
                "bf": child.fire_load_free, "kids": _flatten(children_of, child.pk),
            })
    teams = _team_legend(Team.objects.select_related("group", "parent").exclude(code=""))
    return _finish(houses, axes, nodes, mains, teams)
