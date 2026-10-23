"""Move the fixed building structure to a new layout described by a dataset (docs/location-structure.md).

The dataset is JSON. It lists the location types, teams and axes and every level, room and area with its
full path. An entry naming an ``old`` location renames and moves that location in place, so it keeps its
pk, URLs, history, label IDs and contents; every other entry creates a location. ``remove`` lists old
locations without successor. Containers such as shelves and boxes are not listed: they move with their
parent.

The same data, read from the dataset or from the database, feeds the building overview
(``manage.py building_overview``).
"""
import json
import re
from dataclasses import dataclass, field

from django.contrib.auth.models import Group
from django.core.exceptions import ValidationError
from django.db import transaction

from accounts.models import Team
from .dissolution import DissolutionPlan
from .models import Location, LocationAxis, LocationLabelTemplate, LocationNumberRange, LocationType

TYPE_FLAGS = ("unique", "moveable", "no_sublocations", "deletable_in_frontend", "admin_only", "area_numbering")
# Optional: set only when the dataset names them, so types keep their automatic naming otherwise.
TYPE_NAMING = ("auto_name_prefix", "auto_short_name_prefix", "auto_short_name_padding_length", "auto_sequence")
LEVEL_CODE = re.compile(r"^(?P<house>[A-Za-z]+)(?P<level>[+-]\d+)$")
CODE = re.compile(r"^[A-Za-z0-9+-]{1,8}$")
COMPUTED = ("unique_identifier", "locatable_identifier", "descriptive_identifier")
STRUCTURES = {choice.value for choice in LocationType.Structure}
CATEGORIES = {choice.value for choice in LocationType.Category}


class DatasetError(Exception):
    """The dataset is invalid or does not fit the database; nothing was changed."""


def _parent_path(path):
    return path.rsplit(".", 1)[0] if "." in path else None


def _code(path):
    return path.rsplit(".", 1)[-1]


def load_dataset(path):
    with open(path, encoding="utf-8") as fh:
        data = json.load(fh)
    errors = validate_dataset(data)
    if errors:
        raise DatasetError("\n".join(errors))
    return data


def validate_dataset(data):
    """Return the problems of a dataset that can be found without the database."""
    errors = []
    types = data.get("types", {})
    for key, spec in types.items():
        if not spec.get("name"):
            errors.append(f"type {key}: name is missing")
        if spec.get("structure", "") not in STRUCTURES | {""}:
            errors.append(f"type {key}: unknown structure {spec.get('structure')!r}")
        if spec.get("category", "") not in CATEGORIES | {""}:
            errors.append(f"type {key}: unknown category {spec.get('category')!r}")
        for flag in TYPE_FLAGS:
            if not isinstance(spec.get(flag, False), bool):
                errors.append(f"type {key}: {flag} must be true or false")
        if spec.get("sublocation_type") and spec["sublocation_type"] not in types:
            errors.append(f"type {key}: unknown sublocation_type {spec['sublocation_type']!r}")
    team_codes = {team.get("code") for team in data.get("teams", [])}
    for team in data.get("teams", []):
        if not team.get("code") or not team.get("group"):
            errors.append(f"team {team!r}: code and group are required")
        if team.get("parent") and team["parent"] not in team_codes:
            errors.append(f"team {team.get('code')}: unknown parent {team['parent']}")
        if team.get("color") and not re.fullmatch(r"#[0-9a-fA-F]{6}", team["color"]):
            errors.append(f"team {team.get('code')}: colour must look like #7d3a2d")
    axes = {axis.get("number") for axis in data.get("axes", [])}

    seen_paths, seen_codes, seen_old, ranges = set(), {}, {}, []
    for entry in data.get("locations", []):
        path = entry.get("path", "")
        where = f"location {path or entry!r}"
        if path in seen_paths:
            errors.append(f"{where}: path appears twice")
        parent = _parent_path(path)
        if parent and parent not in seen_paths:
            errors.append(f"{where}: parent {parent} must be listed before it")
        seen_paths.add(path)
        if not CODE.fullmatch(_code(path)):
            errors.append(f"{where}: code {_code(path)!r} must be 1–8 letters, digits, + or -")
        spec = types.get(entry.get("type"))
        if spec is None:
            errors.append(f"{where}: unknown type {entry.get('type')!r}")
        elif spec.get("unique"):
            if _code(path) in seen_codes:
                errors.append(f"{where}: code {_code(path)} is already used by {seen_codes[_code(path)]}")
            seen_codes[_code(path)] = path
        if not entry.get("name"):
            errors.append(f"{where}: name is missing")
        purpose = entry.get("purpose", "")
        if len(purpose) > 50 or "\n" in purpose:
            errors.append(f"{where}: the purpose must be one line of at most 50 characters")
        if entry.get("axis") is not None and entry["axis"] not in axes:
            errors.append(f"{where}: unknown axis {entry['axis']}")
        for code in entry.get("teams", []):
            if code not in team_codes:
                errors.append(f"{where}: unknown team {code}")
        for number_range in entry.get("number_ranges", []):
            first, last, kind = number_range.get("from"), number_range.get("to"), number_range.get("type")
            if not (isinstance(first, int) and isinstance(last, int) and 0 <= first <= last):
                errors.append(f"{where}: number range {number_range!r} needs from <= to")
                continue
            if not types.get(kind, {}).get("area_numbering"):
                errors.append(f"{where}: number range {first}–{last} needs a type with area_numbering")
                continue
            for other_first, other_last, other_kind, other in ranges:
                if not (first <= other_last and last >= other_first and kind == other_kind):
                    continue
                # A reservation lies wholly within a range of a location above it.
                if path.startswith(other + ".") and other_first <= first and last <= other_last:
                    continue
                if other.startswith(path + ".") and first <= other_first and other_last <= last:
                    continue
                errors.append(f"{where}: number range {first}–{last} overlaps {other}")
            ranges.append((first, last, kind, path))
        if entry.get("old"):
            if entry["old"] in seen_old:
                errors.append(f"{where}: old location {entry['old']} is already taken by {seen_old[entry['old']]}")
            seen_old[entry["old"]] = path

    retired = data.get("retire_types", [])
    if not isinstance(retired, list) or not all(isinstance(name, str) for name in retired):
        errors.append("retire_types must be a list of location type names")
    elif set(retired) & {spec.get("name") for spec in types.values()}:
        errors.append("retire_types must not name a type of the dataset")
    for spec in data.get("moves", []):
        if not isinstance(spec.get("codes"), list) or spec.get("to") not in seen_paths:
            errors.append(f"moves {spec!r}: needs a list of codes and a target path of the dataset")
    for removal in data.get("remove", []):
        if removal.get("old") in seen_old:
            errors.append(f"remove {removal.get('old')}: it is also the predecessor of {seen_old[removal['old']]}")
        if removal.get("move_to") and removal["move_to"] not in seen_paths:
            errors.append(f"remove {removal.get('old')}: unknown target {removal['move_to']}")
    return errors


def _active(identifier):
    return Location.objects.filter(is_deleted=False, locatable_identifier=identifier).first()


@dataclass
class Step:
    entry: dict
    action: str  # "move" (an old location), "create" or "update" (already in place)
    location: Location | None = None
    source: str = ""  # the identifier it was found under when moved


@dataclass
class ContainerMove:
    code: str
    location: Location | None
    target: str
    done: bool = False


@dataclass
class Removal:
    spec: dict
    location: Location | None
    children: list = field(default_factory=list)
    stock: int = 0


@dataclass
class Plan:
    data: dict
    steps: list = field(default_factory=list)
    removals: list = field(default_factory=list)
    retired: list = field(default_factory=list)  # (type name, number of deleted locations purged with it)
    moves: list = field(default_factory=list)
    warnings: list = field(default_factory=list)
    errors: list = field(default_factory=list)


def make_plan(data):
    """Compare the dataset with the database. Read-only."""
    plan = Plan(data)
    covered = set(data.get("keep", []))
    for entry in data["locations"]:
        old = entry.get("old")
        location = _active(old) if old else None
        if location is not None:
            # A location whose code does not change (mobil) is in place once moved.
            in_place = old == entry["path"] and location.type.name == entry_type_name(data, entry)
            plan.steps.append(Step(entry, "update" if in_place else "move", location, old))
            covered.add(old)
            for attr, key in (("physical_description", "description"), ("purpose", "purpose")):
                current, new = getattr(location, attr), entry.get(key, "")
                if current and current != new:
                    plan.warnings.append(f"{old} → {entry['path']}: {key} {current!r} is replaced by {new!r}")
            continue
        existing = _active(entry["path"])
        # `was`: paths of earlier versions of the dataset, so that a renamed location is moved, not created again.
        earlier = None if existing else next(
            ((path, found) for path in entry.get("was", []) if (found := _active(path)) is not None), None)
        if earlier:
            plan.steps.append(Step(entry, "move", earlier[1], earlier[0]))
            continue
        if old and existing is None:
            plan.errors.append(f"{entry['path']}: old location {old} does not exist")
            continue
        plan.steps.append(Step(entry, "update" if existing else "create", existing))

    continued = {step.location.pk for step in plan.steps if step.location is not None}
    for spec in data.get("remove", []):
        # `path` finds it again once a previous run has moved its parent.
        location = _active(spec["old"]) or (_active(spec["path"]) if spec.get("path") else None)
        if location is not None and location.pk in continued:
            location = None  # it lives on through an entry (e.g. found by `was`); nothing to remove
        covered.add(spec["old"])
        removal = Removal(spec, location)
        if location is not None:
            removal.children = list(location.children.filter(is_deleted=False))
            removal.stock = location.itemlocation_set.count()
            if location.unique_items.exists():
                plan.errors.append(f"remove {spec['old']}: it still holds unique items; move them first")
            if (removal.children or removal.stock) and not spec.get("move_to"):
                plan.errors.append(f"remove {spec['old']}: it still holds {len(removal.children)} locations and "
                                   f"{removal.stock} stock entries and has no move_to")
        plan.removals.append(removal)

    # Retired types are deleted at the end, together with the deleted locations that still use them.
    moved = {step.location.pk for step in plan.steps if step.location is not None}
    removed = {removal.location.pk for removal in plan.removals if removal.location is not None}
    for old_type in data.get("retire_types", []):
        kind = LocationType.objects.filter(name=old_type).first()
        if kind is None:
            continue
        remaining = Location.objects.filter(type=kind).exclude(pk__in=moved)
        active = remaining.filter(is_deleted=False).exclude(pk__in=removed)
        for location in active.order_by("locatable_identifier"):
            plan.errors.append(f"retire {old_type}: {location.locatable_identifier} still uses it and is not moved or removed")
        plan.retired.append((old_type, remaining.count()))

    # Containers (shelves, boxes) that move into a location of the structure, by their code.
    for spec in data.get("moves", []):
        for code in spec["codes"]:
            location = Location.active.filter(unique_identifier=code).select_related("parent_location").first()
            if location is None:
                plan.errors.append(f"move {code}: no such location")
                continue
            done = location.parent_location is not None and location.parent_location.locatable_identifier == spec["to"]
            plan.moves.append(ContainerMove(code, location, spec["to"], done))

    # Every location of the structure must be in the dataset, so that renamed ones do not stay behind.
    structure_types = [spec["name"] for spec in data["types"].values() if spec.get("structure")]
    handled = ({step.location.pk for step in plan.steps if step.location is not None}
               | {removal.location.pk for removal in plan.removals if removal.location is not None})
    stray = Location.objects.filter(is_deleted=False, type__name__in=structure_types).exclude(pk__in=handled)
    for location in stray.order_by("locatable_identifier"):
        plan.errors.append(f"{location.locatable_identifier} ({location.name}) is not in the dataset; "
                           "list its former path under `was` of its entry or remove it")

    # Every location of a replaced type needs a successor, a removal or an explicit keep.
    replaced = Location.objects.filter(is_deleted=False, type__name__in=data.get("replaces_types", []))
    for location in replaced.order_by("locatable_identifier"):
        if location.locatable_identifier not in covered:
            plan.errors.append(f"{location.locatable_identifier} ({location.name}) is neither moved, removed nor kept")
    return plan


def entry_type_name(data, entry):
    return data["types"][entry["type"]]["name"]


def _purge(locations):
    """Delete deleted locations permanently, with their (deleted) descendants, leaves first."""
    pks, pending = set(), [location.pk for location in locations]
    while pending:
        pk = pending.pop()
        if pk not in pks:
            pks.add(pk)
            pending += list(Location.objects.filter(parent_location_id=pk).values_list("pk", flat=True))
    if Location.objects.filter(pk__in=pks, is_deleted=False).exists():
        raise DatasetError("a location to delete permanently still contains active locations")
    try:
        Location.objects.filter(pk__in=pks).delete()
    except ValidationError as error:
        raise DatasetError("; ".join(error.messages)) from error


def _ensure_types(data):
    types = {}
    for key, spec in data["types"].items():
        kind, _ = LocationType.objects.get_or_create(name=spec["name"])
        for flag in TYPE_FLAGS:
            setattr(kind, flag, spec.get(flag, False))
        for attr in TYPE_NAMING:
            if attr in spec:
                setattr(kind, attr, spec[attr])
        kind.structure = spec.get("structure", "")
        kind.category = spec.get("category", "")
        kind.description = spec.get("description", "")
        if spec.get("label_template"):
            kind.default_label_template = LocationLabelTemplate.objects.filter(name=spec["label_template"]).first()
        try:
            kind.full_clean()
        except ValidationError as error:
            raise DatasetError(f"type {key}: {'; '.join(error.messages)}") from error
        kind.save()
        types[key] = kind
    for key, spec in data["types"].items():
        types[key].sublocation_type = types.get(spec.get("sublocation_type"))
        types[key].save(update_fields=["sublocation_type"])
    return types


def _ensure_axes(data):
    """The axes of the dataset; axes it no longer lists are deleted (their locations get theirs from the dataset)."""
    axes = {}
    for spec in data.get("axes", []):
        axis, _ = LocationAxis.objects.update_or_create(number=spec["number"], defaults={"name": spec["name"]})
        axes[spec["number"]] = axis
    LocationAxis.objects.exclude(number__in=axes).delete()
    return axes


def _ensure_teams(data):
    teams = {}
    for spec in data.get("teams", []):
        group, _ = Group.objects.get_or_create(name=spec["group"])
        team, _ = Team.objects.get_or_create(group=group)
        team.code, team.color = spec["code"], spec.get("color", "")
        teams[spec["code"]] = team
    for spec in data.get("teams", []):
        team = teams[spec["code"]]
        team.parent = teams.get(spec.get("parent"))
        team.full_clean()
        team.save()
    return teams


@transaction.atomic
def apply_plan(plan, actor=None):
    """Write the plan to the database in one transaction. Returns the locations by path."""
    if plan.errors:
        raise DatasetError("\n".join(plan.errors))
    data = plan.data
    types, axes, teams = _ensure_types(data), _ensure_axes(data), _ensure_teams(data)
    by_path = {}
    for step in plan.steps:
        entry = step.entry
        location = step.location or Location()
        parent = _parent_path(entry["path"])
        location.parent_location = by_path[parent] if parent else None
        location.type = types[entry["type"]]
        location.short_name = _code(entry["path"])
        location.name = entry["name"]
        location.purpose = entry.get("purpose", "")
        location.physical_description = entry.get("description", "")
        location.axis = axes.get(entry.get("axis"))
        location.fire_load_free = bool(entry.get("fire_load_free"))
        location.outdoor = bool(entry.get("outdoor"))
        try:
            location.clean_fields(exclude=COMPUTED + ("overview_photo",))
            location.clean()
            location.save(actor=actor)
        except ValidationError as error:
            raise DatasetError(f"{entry['path']}: {'; '.join(error.messages)}") from error
        location.refresh_from_db()
        if location.locatable_identifier != entry["path"]:
            raise DatasetError(f"{entry['path']}: ended up as {location.locatable_identifier}")
        location.responsible_teams.set([teams[code] for code in entry.get("teams", [])])
        location.number_ranges.all().delete()
        by_path[entry["path"]] = location
    # Ranges after all locations, so that moving one range between locations does not overlap on the way.
    for entry in data["locations"]:
        for spec in entry.get("number_ranges", []):
            kind = types[spec["type"]]
            error = LocationNumberRange.overlap_error(spec["from"], spec["to"], kind, by_path[entry["path"]])
            if error:
                raise DatasetError(f"{entry['path']}: {'; '.join(error.messages)}")
            LocationNumberRange.objects.create(location=by_path[entry["path"]], type=kind,
                                               first=spec["from"], last=spec["to"])

    for move in plan.moves:
        if not move.done:
            move.location.parent_location = by_path[move.target]
            move.location.save(actor=actor)

    for removal in plan.removals:
        if removal.location is None:
            continue
        # The same plan as "Move contents" on the inventory pages: sub-locations and stock move, then it is deleted.
        dissolution = DissolutionPlan(removal.location, lock=True)
        target = by_path.get(removal.spec.get("move_to"))
        operations = [(row["kind"], row["object"].pk, "move", target.pk if target else None)
                      for row in dissolution.rows]
        try:
            dissolution.apply(operations)
        except ValidationError as error:
            raise DatasetError(f"remove {removal.spec['old']}: {'; '.join(error.messages)}") from error
        if removal.spec.get("permanent"):
            _purge([removal.location])

    for old_type in data.get("retire_types", []):
        kind = LocationType.objects.filter(name=old_type).first()
        if kind is None:
            continue
        remaining = list(Location.objects.filter(type=kind))
        if any(not location.is_deleted for location in remaining):
            raise DatasetError(f"retire {old_type}: active locations still use it")
        _purge(remaining)
        kind.delete()
    return by_path


# --- Overview ---------------------------------------------------------------------------------------

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


def _node(path, house, level, axis, name, kind, purpose="", description="", teams=(), fire=False, old=""):
    return {"h": house, "l": level, "a": axis, "c": _code(path), "n": name, "k": kind, "z": purpose,
            "d": description, "t": list(teams), "bf": fire, "o": old}


def _kind(structure, outdoor):
    return "o" if outdoor else "b" if structure == "area" else ""


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


def _flatten(children_of, parent_key, prefix=""):
    """The parts below a node as one list; numbered parts get their code relative to the node."""
    kids = []
    for child in children_of(parent_key):
        relative = child["code"] if child["global"] else f"{prefix}{child['code']}"
        kids.append({**child["kid"], "c": relative, "g": child["global"]})
        kids += _flatten(children_of, child["key"], f"{relative}.")
    return kids


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
        info = houses.setdefault(house, {"name": level.name.split(" Ebene")[0], "levels": []})
        info["levels"].append(number)
        mains.append({"h": house, "l": number, "a": level.axis.number if level.axis else None, "n": level.name,
                      "z": level.purpose, "d": level.physical_description,
                      "t": _team_badges(level.responsible_teams.all()), "bf": level.fire_load_free})
        for child in by_parent.get(level.pk, []):
            node = _node(child.short_name, house, number, child.axis.number if child.axis else None, child.name,
                         _kind(child.type.structure, child.outdoor), child.purpose, child.physical_description,
                         _team_badges(child.responsible_teams.all()), child.fire_load_free)
            node["kids"] = _flatten(children_of, child.pk)
            nodes.append(node)
    teams = _team_legend(Team.objects.select_related("group", "parent").exclude(code=""))
    return _finish(houses, axes, nodes, mains, teams)


def overview_from_dataset(data):
    """The overview of the planned structure, before it is applied."""
    types, houses, nodes, mains = data["types"], {}, [], []
    by_parent = {}
    for entry in data["locations"]:
        by_parent.setdefault(_parent_path(entry["path"]), []).append(entry)

    def kid(entry):
        return {"code": _code(entry["path"]), "global": bool(types[entry["type"]].get("unique")),
                "key": entry["path"], "kid": {"n": entry["name"], "z": entry.get("purpose", ""),
                                               "d": entry.get("description", ""), "t": entry.get("teams", []),
                                               "bf": bool(entry.get("fire_load_free")), "o": entry.get("old", "")}}

    def children_of(path):
        return [kid(child) for child in by_parent.get(path, [])]

    for entry in by_parent.get(None, []):
        match = LEVEL_CODE.match(entry["path"])
        if types[entry["type"]].get("structure") != "level" or not match:
            continue
        house, number = match["house"], int(match["level"])
        info = houses.setdefault(house, {"name": entry["name"].split(" Ebene")[0], "levels": []})
        info["levels"].append(number)
        mains.append({"h": house, "l": number, "a": entry.get("axis"), "n": entry["name"],
                      "z": entry.get("purpose", ""), "d": entry.get("description", ""),
                      "t": entry.get("teams", []), "bf": bool(entry.get("fire_load_free")), "o": entry.get("old", "")})
        for child in by_parent.get(entry["path"], []):
            spec = types[child["type"]]
            node = _node(child["path"], house, number, child.get("axis"), child["name"],
                         _kind(spec.get("structure", ""), child.get("outdoor")), child.get("purpose", ""),
                         child.get("description", ""), child.get("teams", []), bool(child.get("fire_load_free")),
                         child.get("old", ""))
            node["kids"] = _flatten(children_of, child["path"])
            nodes.append(node)
    teams = {}
    by_code = {spec["code"]: spec for spec in data.get("teams", [])}
    for code, spec in by_code.items():
        team = Team(color=spec.get("color", ""))
        parent = by_code.get(spec.get("parent"))
        if not team.color and parent:
            team.color = parent.get("color", "")
        teams[code] = {"n": spec["group"], "c": team.badge_color, "t": team.badge_text_color,
                       "parent": spec.get("parent", "")}
    axes = [{"n": axis["number"], "name": axis["name"]} for axis in data.get("axes", [])]
    return _finish(houses, axes, nodes, mains, teams)
