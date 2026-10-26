"""
Cleanup proposals (format.md): reading the uploaded file, planning and applying the changes.

Each category operation and each changed item field is one Change with a key ("c3": the fourth category
operation, "i4711.name"). plan() goes through the accepted changes in order on a copy of the category tree in
memory (Tree): category operations first, then the item fields. A change that cannot be carried out there (a
category it needs that is deferred or declined, a missing permission …) gets
a `problem` and is skipped; the same plan, made again inside the transaction, is what apply() carries out.
"""
import difflib
import json
import re
from collections import defaultdict
from dataclasses import dataclass, field

from django.db import transaction
from django.utils import timezone
from django.utils.dateparse import parse_datetime
from django.utils.html import format_html, format_html_join
from django.utils.translation import gettext as _, gettext_lazy, ngettext

from ..change_log import change_context
from ..models import Category, ChangeLog, CleanupImport, Item

KIND = "zam-inventory-cleanup-proposals"
VERSION = 1
CATEGORY_OPS = ("create", "update", "move", "join", "split", "delete")
ITEM_FIELDS = ("name", "description", "category")
# The reviewer's decision on a change (CleanupImport.decisions); accepting is the default. Deferred: not now, still
# to be decided (also those changed since the export, at upload).
ACCEPT, DEFER, DECLINE = "accept", "deferred", "declined"
DECISIONS = (ACCEPT, DEFER, DECLINE)
TEXT_FIELDS = ("name", "description")  # item fields the reviewer may accept with changes
CATEGORY_TEXTS = ("description", "keywords", "naming")  # besides the name
# What kind of change a proposal is (format.md); the review sorts and filters by it.
CHANGE_TYPES = ("typo", "naming", "description", "category", "structure", "other")
# What an item proposal's reason is mainly based on (format.md): a photo, barcode or file of the item by id, or
# one of its fields, or how similar items are named.
SOURCES_WITH_ID = ("photo", "barcode", "file")
SOURCES = ("name", "description", "category", "convention")
MAX_NAME = 512


class Invalid(Exception):
    """The file, an operation or a value is not as format.md describes."""


def load(data):
    """The proposals of an uploaded file (bytes) as stored in CleanupImport.proposals."""
    try:
        proposals = json.loads(data.decode("utf-8-sig"))
    except (UnicodeDecodeError, ValueError) as error:
        raise Invalid(_("The file is not JSON: %(error)s") % {"error": error})
    if not isinstance(proposals, dict) or proposals.get("kind") != KIND:
        raise Invalid(_("The file holds no cleanup proposals (\"kind\": \"%(kind)s\" is missing).") % {"kind": KIND})
    if proposals.get("version") != VERSION:
        raise Invalid(_("Only version %(version)s of the format is supported.") % {"version": VERSION})
    for section in ("categories", "items"):
        if not isinstance(proposals.get(section, []), list):
            raise Invalid(_("\"%(section)s\" must be a list.") % {"section": section})
    return {"exported_at": proposals.get("exported_at"), "categories": proposals.get("categories", []),
            "items": proposals.get("items", [])}


def exported_at(proposals):
    value = proposals.get("exported_at")
    moment = parse_datetime(value) if isinstance(value, str) else None
    if moment is not None and timezone.is_naive(moment):
        moment = timezone.make_aware(moment)
    return moment


# The category tree in memory

class Tree:
    """The categories (and in which category each active item is) as plan() changes them. Categories created on
    the way get negative ids."""

    def __init__(self):
        self.name, self.parent, self.texts = {}, {}, {}  # texts: {pk: {"description": …, "keywords": …, …}}
        for pk, name, parent, *texts in Category.objects.values_list("pk", "name", "parent_category_id",
                                                                      *CATEGORY_TEXTS):
            self.add(pk, name, parent, dict(zip(CATEGORY_TEXTS, texts)))
        self.category_of = dict(Item.active.values_list("pk", "category_id"))
        self.refs = {}  # ref -> id of the categories created
        self.unavailable = {}  # ref -> why it does not exist (its operation declined or failed)
        self.created = 0

    def add(self, pk, name, parent, texts):
        self.name[pk], self.parent[pk] = name, parent
        self.texts[pk] = {key: texts.get(key, "") for key in CATEGORY_TEXTS}

    def create(self, ref, name, parent, texts):
        self.created += 1
        self.add(-self.created, name, parent, texts)
        self.refs[ref] = -self.created
        return -self.created

    def delete(self, pk):
        for mapping in (self.name, self.parent, self.texts):
            del mapping[pk]

    def resolve(self, value, none=False):
        """The id of the category an operation names: an id from the export, or the ref of one created before."""
        if value is None and none:
            return None
        if isinstance(value, int) and not isinstance(value, bool):
            if value in self.name:
                return value
            raise Invalid(_("There is no category %(id)s (any more).") % {"id": value})
        if isinstance(value, str) and value:
            if value in self.refs and self.refs[value] in self.name:
                return self.refs[value]
            if value in self.unavailable:
                raise Invalid(self.unavailable[value])
            raise Invalid(_("No operation before creates the category “%(ref)s”.") % {"ref": value})
        raise Invalid(_("A category is named by its id (a number) or its ref (a string), not by %(value)s.")
                      % {"value": json.dumps(value, ensure_ascii=False)})

    def gone(self, value):
        """Whether the operation names a category by an id that no longer exists (e.g. deleted or joined by an
        earlier import of the same proposals)."""
        return isinstance(value, int) and not isinstance(value, bool) and value not in self.name

    def find(self, name, parent=None, anywhere=False):
        """A category of that name (ignoring case) below parent, or anywhere; None if there is none."""
        name = name.casefold()
        return next((pk for pk, other in self.name.items() if other.casefold() == name and (
            anywhere or self.parent[pk] == parent)), None)

    def path(self, pk):
        names, seen = [], set()
        while pk is not None and pk not in seen:
            seen.add(pk)
            names.append(self.name[pk])
            pk = self.parent[pk]
        return "/".join(reversed(names))

    def children(self, pk):
        return [child for child, parent in self.parent.items() if parent == pk]

    def items_in(self, pk):
        return [item for item, category in self.category_of.items() if category == pk]

    def subtree(self, pk):
        """pk and every category below it."""
        found, todo = set(), [pk]
        while todo:
            current = todo.pop()
            found.add(current)
            todo.extend(self.children(current))
        return found


# Values

def name_value(value):
    if not isinstance(value, str) or not value.strip():
        raise Invalid(_("A name must be a text that is not empty."))
    value = value.strip()
    if len(value) > MAX_NAME:
        raise Invalid(_("A name may be at most %(max)s characters long.") % {"max": MAX_NAME})
    return value


def category_name(value):
    value = name_value(value)
    if "/" in value:
        raise Invalid(_("A category name must not contain “/”."))
    return value


TEXT_LABELS = {"description": gettext_lazy("The description"), "keywords": gettext_lazy("The keywords"),
               "naming": gettext_lazy("The naming")}
FIELD_NAMES = {"name": gettext_lazy("Name"), "description": gettext_lazy("Description"),
               "keywords": gettext_lazy("Keywords"), "naming": gettext_lazy("Naming")}


def text_value(value, what):
    if not isinstance(value, str):
        raise Invalid(_("%(what)s must be a text.") % {"what": what})
    return value.strip()


def id_list(value, what):
    if value is None:
        return []
    if not isinstance(value, list) or not all(isinstance(v, int) and not isinstance(v, bool) for v in value):
        raise Invalid(_("%(what)s must be a list of ids.") % {"what": what})
    return value


def merged_keywords(*values):
    """Comma-separated keywords, each once (ignoring case), in their order."""
    seen, merged = set(), []
    for value in values:
        for word in (part.strip() for part in (value or "").split(",")):
            if word and word.lower() not in seen:
                seen.add(word.lower())
                merged.append(word)
    return ", ".join(merged)


def category_texts(data):
    """Description, keywords and naming of a category an operation creates."""
    return {key: text_value(data.get(key, ""), TEXT_LABELS[key]) for key in CATEGORY_TEXTS}


def texts_details(texts):
    return [f"{FIELD_NAMES[key]}: {value}" for key, value in texts.items() if value]


def quote(text):
    return _("“%(text)s”") % {"text": text}  # German: „…“


def quoted(tree, pk):
    return quote(tree.path(pk)) if pk is not None else _("top level")


def place_in(tree, pk):
    return _("in “%(path)s”") % {"path": tree.path(pk)} if pk is not None else _("at the top level")


def place_into(tree, pk):
    return _("into “%(path)s”") % {"path": tree.path(pk)} if pk is not None else _("to the top level")


# Changes

@dataclass
class Change:
    key: str
    op: str  # a category operation (CATEGORY_OPS) or an item field (ITEM_FIELDS)
    data: dict  # the operation, or the item's proposal
    reason: str = ""
    decision: str = ACCEPT
    problem: str = ""  # why it cannot be carried out; empty: it can
    unchanged: bool = False  # an item field proposed as it is
    stale: bool = False  # the item field changed since the export
    text: str = ""  # a category operation in words
    details: list = field(default_factory=list)  # more about a category operation (what moves where)
    args: dict = field(default_factory=dict)  # resolved (Tree ids) for apply()
    item: Item = None
    before: str = ""
    after: str = ""  # what is applied: the proposed value, or the reviewer's (modified)
    proposed: str = ""  # a text field's proposed value
    modified: bool = False  # accepted with changes by the reviewer
    confidence: float = None  # how sure the proposal is (0 to 1), if it says
    types: list = field(default_factory=list)  # what kind of change it is (CHANGE_TYPES)
    notes: list = field(default_factory=list)  # about the proposal (source, confidence, type), not hindering it

    @property
    def accepted(self):
        return self.decision == ACCEPT

    @property
    def applies(self):
        return self.accepted and not self.problem and not self.unchanged

    @property
    def status(self):
        if self.unchanged:
            return "unchanged"
        if not self.accepted:
            return self.decision
        return "problem" if self.problem else "ok"

    @property
    def diff(self):
        """(before, after) as HTML with what was removed and added marked (names and descriptions)."""
        return word_diff(self.before, self.after)


def word_diff(before, after):
    old, new = re.split(r"(\s+)", before or ""), re.split(r"(\s+)", after or "")
    removed, added = [], []
    for tag, i1, i2, j1, j2 in difflib.SequenceMatcher(None, old, new, autojunk=False).get_opcodes():
        if tag == "equal":
            removed.append(("", "".join(old[i1:i2])))
            added.append(("", "".join(new[j1:j2])))
        else:
            if i2 > i1:
                removed.append(("del", "".join(old[i1:i2])))
            if j2 > j1:
                added.append(("ins", "".join(new[j1:j2])))

    def html(parts):
        return format_html_join("", "{}", ((format_html("<{0}>{1}</{0}>", tag, part) if tag else part,)
                                           for tag, part in parts))
    return html(removed), html(added)


@dataclass
class Plan:
    categories: list
    items: list  # Changes of item fields, grouped by item in file order
    errors: list  # proposals that are no changes at all (no id, unknown item …), as texts

    def counts(self, changes):
        counts = defaultdict(int)
        for change in changes:
            counts[change.status] += 1
        return counts


CATEGORY_PERMISSIONS = {
    "create": ("inventory.add_category",),
    "update": ("inventory.change_category",),
    "move": ("inventory.change_category",),
    "join": ("inventory.change_category", "inventory.delete_category", "inventory.change_item"),
    "split": ("inventory.add_category", "inventory.change_category", "inventory.change_item"),
    "delete": ("inventory.change_category", "inventory.delete_category", "inventory.change_item"),
}


def plan(cleanup, user=None):
    """The changes of a cleanup import, gone through in order on the tree in memory."""
    decisions = cleanup.decisions
    tree = Tree()
    categories = []
    for index, data in enumerate(cleanup.proposals.get("categories", [])):
        change = Change(f"c{index}", data.get("op", "") if isinstance(data, dict) else "", data if isinstance(
            data, dict) else {}, reason=reason_of(data),
            decision=decisions.get(f"c{index}", ACCEPT))
        categories.append(change)
        meta(change)
        refs = created_refs(change)
        try:
            if not isinstance(data, dict) or change.op not in CATEGORY_OPS:
                raise Invalid(_("Unknown operation; one of: %(ops)s.") % {"ops": ", ".join(CATEGORY_OPS)})
            OPERATIONS[change.op](tree, change, refs)
            if not change.unchanged and user is not None and not user.has_perms(CATEGORY_PERMISSIONS[change.op]):
                raise Invalid(_("You lack the permission for this."))
        except Invalid as error:
            change.problem = str(error)
            change.text = change.text or json.dumps(change.data, ensure_ascii=False)[:300]
        if change.applies or change.unchanged and not change.problem and "do" in change.args:
            change.args["do"]()  # carried out; already applied: only its refs, to the existing categories
        elif not change.unchanged:
            why = {DEFER: _("Its creation is deferred."), DECLINE: _("Its creation was declined.")}.get(
                change.decision, _("Its creation cannot be carried out."))
            for ref in refs:
                tree.unavailable.setdefault(ref, why)
        change.args.pop("do", None)
    items, errors = item_changes(cleanup, tree, decisions, user)
    applied = set(cleanup.result.get("applied", []))
    for change in categories + items:
        if change.key in applied and not change.unchanged and not change.problem:
            # Applied before, but not so any more: changed since, which is not undone.
            change.problem = _("Applied before and changed since; it is not applied again.")
    return Plan(categories, items, errors)


def meta(change):
    """Confidence and types of the change's proposal; what is wrong with them as notes."""
    value = change.data.get("confidence")
    if value is not None:
        if isinstance(value, (int, float)) and not isinstance(value, bool) and 0 <= value <= 1:
            change.confidence = float(value)
        else:
            change.notes.append(_("The confidence must be a number from 0 to 1, not %(value)s.") % {
                "value": json.dumps(value, ensure_ascii=False)})
    value = change.data.get("type")
    values = value if isinstance(value, list) else [] if value is None else [value]
    change.types = [kind for kind in values if isinstance(kind, str) and kind in CHANGE_TYPES]
    unknown = [kind for kind in values if kind not in change.types]
    if unknown:
        change.notes.append(_("Unknown type %(value)s; one of: %(types)s.") % {
            "value": json.dumps(unknown, ensure_ascii=False), "types": ", ".join(CHANGE_TYPES)})


def source_of(data):
    """(kind, id or None) of an item proposal's source; None if it gives none."""
    value = data.get("source")
    if value is None or value == "":
        return None
    if isinstance(value, str):
        kind, _colon, number = value.strip().partition(":")
        if kind in SOURCES and not number:
            return kind, None
        if kind in SOURCES_WITH_ID and number.strip().isdigit():
            return kind, int(number)
    raise Invalid(_("Unknown source %(value)s; one of: %(sources)s.") % {
        "value": json.dumps(value, ensure_ascii=False),
        "sources": ", ".join([f"{kind}:<id>" for kind in SOURCES_WITH_ID] + list(SOURCES))})


def reason_of(data):
    reason = data.get("reason") if isinstance(data, dict) else None
    return reason.strip() if isinstance(reason, str) else ""


def created_refs(change):
    if change.op == "create":
        return [change.data.get("ref")] if isinstance(change.data.get("ref"), str) else []
    if change.op == "split" and isinstance(change.data.get("parts"), list):
        return [part.get("ref") for part in change.data["parts"] if isinstance(part, dict) and isinstance(
            part.get("ref"), str)]
    return []


def new_ref(tree, value, refs_here):
    if not isinstance(value, str) or not value.strip() or value.isdigit():
        raise Invalid(_("A new category needs a “ref”: a text you choose, unique within the file."))
    if value in tree.refs or value in tree.unavailable or refs_here.count(value) > 1:
        raise Invalid(_("The ref “%(ref)s” is used twice.") % {"ref": value})
    return value


# Each operation checks the change on the tree, describes it (text, details) and leaves in args["do"] how to carry
# it out on the tree, and in args what apply() needs.

def op_create(tree, change, refs):
    data = change.data
    name = category_name(data.get("name"))
    parent = tree.resolve(data.get("parent"), none=True)
    ref = new_ref(tree, data.get("ref"), refs)
    texts = category_texts(data)
    change.text = _("Create “%(name)s” %(place)s") % {"name": name, "place": place_in(tree, parent)}
    change.details = texts_details(texts)
    change.args.update(ref=ref, name=name, parent=parent, texts=texts)
    existing = tree.find(name, parent)
    if existing is not None:  # created already (an earlier import of these proposals): later changes refer to it
        change.unchanged = True
        change.args["do"] = lambda: tree.refs.__setitem__(ref, existing)
        return

    def do():
        change.args["new"] = tree.create(ref, name, parent, texts)
    change.args["do"] = do


def op_update(tree, change, refs):
    data = change.data
    pk = tree.resolve(data.get("id"))
    values = {}
    if "name" in data:
        values["name"] = category_name(data["name"])
    for key in CATEGORY_TEXTS:
        if key in data:
            values[key] = text_value(data[key], TEXT_LABELS[key])
    current = {"name": tree.name[pk], **tree.texts[pk]}
    values = {key: value for key, value in values.items() if value != current[key]}
    change.text = _("Change %(category)s") % {"category": quoted(tree, pk)}
    if not values:  # as proposed already
        change.unchanged = True
        return
    change.details = [f"{FIELD_NAMES[key]}: {current[key] or '–'} → {value or '–'}" for key, value in values.items()]
    change.args.update(id=pk, values=values)

    def do():
        tree.name[pk] = values.get("name", tree.name[pk])
        tree.texts[pk].update({key: value for key, value in values.items() if key != "name"})
    change.args["do"] = do


def op_move(tree, change, refs):
    pk = tree.resolve(change.data.get("id"))
    parent = tree.resolve(change.data.get("parent"), none=True)
    change.text = _("Move %(category)s %(place)s") % {"category": quoted(tree, pk), "place": place_into(tree, parent)}
    if parent in tree.subtree(pk):
        raise Invalid(_("A category cannot move into itself or one of its subcategories."))
    if parent == tree.parent[pk]:  # there already
        change.unchanged = True
        return
    change.args.update(id=pk, parent=parent)
    change.args["do"] = lambda: tree.parent.__setitem__(pk, parent)


def op_join(tree, change, refs):
    data = change.data
    if not isinstance(data.get("ids"), list) or not data["ids"]:
        raise Invalid(_("“ids” must list the categories to join."))
    into = tree.resolve(data.get("into"))
    sources = []
    for value in data["ids"]:
        if tree.gone(value):  # joined already
            continue
        pk = tree.resolve(value)
        if pk != into and pk not in sources:
            sources.append(pk)
    if not sources:
        if any(tree.gone(value) for value in data["ids"]):
            change.text = _("Join into %(into)s") % {"into": quoted(tree, into)}
            change.unchanged = True
            return
        raise Invalid(_("Nothing to join: only the target is listed."))
    change.text = _("Join %(categories)s into %(into)s") % {
        "categories": ", ".join(quoted(tree, pk) for pk in sources), "into": quoted(tree, into)}
    for pk in sources:
        if into in tree.subtree(pk):
            raise Invalid(_("%(into)s is inside %(category)s, which would be deleted.") % {
                "into": quoted(tree, into), "category": quoted(tree, pk)})
    items = sum(len(tree.items_in(pk)) for pk in sources)
    children = sum(len(tree.children(pk)) for pk in sources)
    change.details = [move_counts(items, children, quoted(tree, into))]
    change.args.update(sources=sources, into=into)

    def do():
        for pk in sources:
            for item in tree.items_in(pk):
                tree.category_of[item] = into
            for child in tree.children(pk):
                tree.parent[child] = into
            tree.texts[into]["keywords"] = merged_keywords(tree.texts[into]["keywords"], tree.texts[pk]["keywords"])
            tree.delete(pk)
    change.args["do"] = do


def move_counts(items, children, target):
    parts = [ngettext("%(count)s item", "%(count)s items", items) % {"count": items}] if items else []
    if children:
        parts.append(ngettext("%(count)s subcategory", "%(count)s subcategories", children) % {"count": children})
    return f"{_(' and ').join(parts)} → {target}" if parts \
        else _("Nothing in it moves.")


def op_split(tree, change, refs):
    data = change.data
    if tree.gone(data.get("id")) and isinstance(data.get("parts"), list) and data["parts"] and all(
            isinstance(part, dict) and isinstance(part.get("name"), str) and tree.find(part["name"], anywhere=True)
            for part in data["parts"]):  # split already: later changes refer to its parts
        found = {part.get("ref"): tree.find(part["name"], anywhere=True) for part in data["parts"]}
        change.text = _("Split into %(parts)s") % {"parts": ", ".join(quote(part["name"]) for part in data["parts"])}
        change.unchanged = True
        change.args["do"] = lambda: tree.refs.update({ref: pk for ref, pk in found.items() if isinstance(ref, str)})
        return
    pk = tree.resolve(data.get("id"))
    keep = data.get("keep", False)
    if not isinstance(keep, bool):
        raise Invalid(_("“keep” must be true or false."))
    if not isinstance(data.get("parts"), list) or not data["parts"]:
        raise Invalid(_("“parts” must list the new categories."))
    items_here, children_here = set(tree.items_in(pk)), set(tree.children(pk))
    names = dict(Item.objects.filter(pk__in=items_here).values_list("pk", "name"))
    parts, taken_items, taken_children = [], set(), set()
    for part in data["parts"]:
        if not isinstance(part, dict):
            raise Invalid(_("Each part is an object with ref, name, items and categories."))
        ref = new_ref(tree, part.get("ref"), refs)
        name = category_name(part.get("name"))
        parent = tree.resolve(part.get("parent"), none=True) if "parent" in part else tree.parent[pk]
        items = id_list(part.get("items"), _("“items” of a part"))
        children = [tree.resolve(value) for value in id_list(part.get("categories"), _("“categories” of a part"))]
        for item in items:
            if item not in items_here:
                raise Invalid(_("Item %(id)s is not directly in %(category)s.") % {"id": item,
                                                                                 "category": quoted(tree, pk)})
            if item in taken_items:
                raise Invalid(_("Item %(id)s is listed in two parts.") % {"id": item})
        for child in children:
            if child not in children_here:
                raise Invalid(_("%(child)s is not directly below %(category)s.") % {
                    "child": quoted(tree, child), "category": quoted(tree, pk)})
            if child in taken_children:
                raise Invalid(_("%(child)s is listed in two parts.") % {"child": quoted(tree, child)})
        taken_items.update(items)
        taken_children.update(children)
        parts.append({"ref": ref, "name": name, "parent": parent, "items": items, "categories": children,
                      "texts": category_texts(part)})
    for part in parts:
        if part["parent"] is not None and (part["parent"] == pk and not keep or any(
                part["parent"] in tree.subtree(child) for child in taken_children)):
            raise Invalid(_("Part “%(name)s” would be inside a category that is deleted or moved into it.")
                          % {"name": part["name"]})
    if not keep and (items_here - taken_items or children_here - taken_children):
        raise Invalid(_("%(category)s is deleted, but these are in no part: %(left)s. List them, or set “keep”: true.") % {
            "category": quoted(tree, pk), "left": _(" and ").join(filter(None, [
                ngettext("%(count)s item", "%(count)s items", len(items_here - taken_items)) % {
                    "count": len(items_here - taken_items)} if items_here - taken_items else "",
                ngettext("%(count)s subcategory", "%(count)s subcategories", len(children_here - taken_children)) % {
                    "count": len(children_here - taken_children)} if children_here - taken_children else ""]))})
    change.text = (_("Split %(category)s into %(parts)s") if not keep else
                   _("Split %(parts)s off %(category)s")) % {
        "category": quoted(tree, pk), "parts": ", ".join(quote(part["name"]) for part in parts)}
    for part in parts:
        listed = [names.get(item) or f"#{item}" for item in part["items"]] + [
            f"{tree.path(child)}/" for child in part["categories"]]
        change.details.append(f"{part['name']} ({quoted(tree, part['parent'])}): {', '.join(listed) or '–'}")
    if keep:
        left = len(items_here - taken_items) + len(children_here - taken_children)
        change.details.append(ngettext("%(count)s entry stays in %(category)s.", "%(count)s entries stay in %(category)s.",
                                       left) % {"count": left, "category": quoted(tree, pk)})
    change.args.update(id=pk, parts=parts, keep=keep)

    def do():
        for part in parts:
            new = tree.create(part["ref"], part["name"], part["parent"], part["texts"])
            part["new"] = new
            for item in part["items"]:
                tree.category_of[item] = new
            for child in part["categories"]:
                tree.parent[child] = new
        if not keep:
            tree.delete(pk)
    change.args["do"] = do


def op_delete(tree, change, refs):
    if tree.gone(change.data.get("id")):  # deleted already
        change.text = _("Delete category %(id)s") % {"id": change.data["id"]}
        change.unchanged = True
        return
    pk = tree.resolve(change.data.get("id"))
    change.text = _("Delete %(category)s") % {"category": quoted(tree, pk)}
    parent = tree.parent[pk]
    target = tree.resolve(change.data["items_to"], none=True) if "items_to" in change.data else parent
    if target == pk:
        raise Invalid(_("Its items cannot go to the category itself."))
    items, children = tree.items_in(pk), tree.children(pk)
    if items:
        change.details.append(move_counts(len(items), 0, quoted(tree, target) if target is not None
                                          else _("no category")))
    if children:
        change.details.append(move_counts(0, len(children), quoted(tree, parent)))
    change.args.update(id=pk, items_to=target)

    def do():
        for item in items:
            tree.category_of[item] = target
        for child in children:
            tree.parent[child] = parent
        tree.delete(pk)
    change.args["do"] = do


OPERATIONS = {"create": op_create, "update": op_update, "move": op_move, "join": op_join, "split": op_split,
              "delete": op_delete}


def item_changes(cleanup, tree, decisions, user):
    proposals = cleanup.proposals.get("items", [])
    errors, wanted = [], []
    for index, data in enumerate(proposals):
        pk = data.get("id") if isinstance(data, dict) else None
        if not isinstance(pk, int) or isinstance(pk, bool):
            errors.append(_("Item proposal %(number)s has no id.") % {"number": index + 1})
        elif pk in {entry["id"] for entry in wanted}:
            errors.append(_("Item %(id)s is proposed twice; only the first proposal counts.") % {"id": pk})
        elif not any(key in data for key in ITEM_FIELDS):
            errors.append(_("Item %(id)s: nothing to change.") % {"id": pk})
        else:
            wanted.append(data)
    items = Item.active.select_related("category").in_bulk([data["id"] for data in wanted])
    stale = changed_since(cleanup.exported_at, items)
    may = user is None or user.has_perm("inventory.change_item")
    changes = []
    for data in wanted:
        item = items.get(data["id"])
        if item is None:
            errors.append(_("There is no item %(id)s (any more).") % {"id": data["id"]})
            continue
        for name in ITEM_FIELDS:
            if name not in data:
                continue
            key = f"i{item.pk}.{name}"
            change = Change(key, name, data, reason=reason_of(data), decision=decisions.get(key, ACCEPT), item=item,
                            stale=(item.pk, name) in stale)
            meta(change)
            try:
                if name == "category":
                    target = tree.resolve(data[name], none=True)
                    current = tree.category_of.get(item.pk)
                    change.before = item.category.full_name if item.category else ""
                    change.after = tree.path(target) if target is not None else ""
                    change.unchanged = target == current
                    change.args["category"] = target
                else:
                    change.before = getattr(item, name) or ""
                    change.proposed = change.after = data[name] if isinstance(data[name], str) else ""
                    value = cleanup.modified.get(key, data[name])
                    change.modified = key in cleanup.modified
                    value = name_value(value) if name == "name" else text_value(value, _("The description"))
                    change.after = value
                    change.unchanged = value == change.before and not change.modified
                    change.args[name] = value
                if not may:
                    raise Invalid(_("You lack the permission for this."))
            except Invalid as error:
                change.problem = str(error)
                change.after = change.after or json.dumps(data[name], ensure_ascii=False)
            changes.append(change)
    return changes, errors


def changed_since(moment, items):
    """(item id, field) of the item fields changed after the export (the change log)."""
    if moment is None or not items:
        return set()
    changed = set()
    # Changes by cleanup imports (e.g. this one, applied in parts) do not count.
    for item_id, entries in ChangeLog.objects.filter(item_id__in=list(items), created_at__gt=moment).exclude(
            source=ChangeLog.Source.CLEANUP).values_list("item_id", "changes"):
        for entry in entries or []:
            if isinstance(entry, dict) and entry.get("field") in ITEM_FIELDS:
                changed.add((item_id, entry["field"]))
    return changed


def stale_keys(cleanup):
    """Keys of the item fields changed since the export: deferred at upload (to be looked at first)."""
    return [change.key for change in plan(cleanup).items if change.stale]


# Applying

def apply(cleanup, user):
    """Carry out the accepted changes that can be carried out, all in one transaction; return the plan."""
    with transaction.atomic(), change_context(source=ChangeLog.Source.CLEANUP, actor=user):
        cleanup = CleanupImport.objects.select_for_update().get(pk=cleanup.pk)
        done = plan(cleanup, user)
        ids = {}  # Tree id -> database id

        def db(pk):
            return None if pk is None else ids.get(pk, pk)
        for change in done.categories:
            if change.applies:
                with change_context(note=change.reason):
                    APPLY[change.op](change.args, db, ids)
        by_item = defaultdict(list)
        for change in done.items:
            if change.applies:
                by_item[change.item.pk].append(change)
        for changes in by_item.values():
            item = Item.objects.get(pk=changes[0].item.pk)
            for change in changes:
                if change.op == "category":
                    item.category_id = db(change.args["category"])
                else:
                    setattr(item, change.op, change.args[change.op])
            with change_context(note=changes[0].reason):
                item.save()
        # An import can be applied again and again: deferred changes accepted later are carried out then, those
        # applied before are applied already (unchanged).
        everything = done.categories + done.items
        applied = [change.key for change in everything if change.applies]
        cleanup.applied_at, cleanup.applied_by = timezone.now(), user
        cleanup.result = {"applied": sorted(set(cleanup.result.get("applied", [])) | set(applied)),
                          "last": applied,
                          "skipped": {change.key: change.problem for change in everything
                                      if change.accepted and change.problem}}
        cleanup.save()
    return done


def move_items(source, target):
    """The items of a category (deleted ones too) to another (None: no category), each saved for the change log."""
    for item in Item.objects.filter(category_id=source):
        item.category_id = target
        item.save()


def move_children(source, target):
    for child in Category.objects.filter(parent_category_id=source):
        child.parent_category_id = target
        child.save()


def apply_create(args, db, ids):
    category = Category.objects.create(name=args["name"], parent_category_id=db(args["parent"]), **args["texts"])
    ids[args["new"]] = category.pk


def apply_update(args, db, ids):
    category = Category.objects.get(pk=db(args["id"]))
    for key, value in args["values"].items():
        setattr(category, key, value)
    category.save()


def apply_move(args, db, ids):
    category = Category.objects.get(pk=db(args["id"]))
    category.parent_category_id = db(args["parent"])
    category.save()


def apply_join(args, db, ids):
    into = Category.objects.get(pk=db(args["into"]))
    for pk in args["sources"]:
        source = Category.objects.get(pk=db(pk))
        move_items(source.pk, into.pk)
        move_children(source.pk, into.pk)
        into.keywords = merged_keywords(into.keywords, source.keywords)
        source.delete()
    into.save()


def apply_split(args, db, ids):
    source = Category.objects.get(pk=db(args["id"]))
    for part in args["parts"]:
        new = Category.objects.create(name=part["name"], parent_category_id=db(part["parent"]), **part["texts"])
        ids[part["new"]] = new.pk
        for item in Item.active.filter(pk__in=part["items"], category=source):
            item.category = new
            item.save()
        for child in Category.objects.filter(pk__in=[db(pk) for pk in part["categories"]]):
            child.parent_category = new
            child.save()
    if not args["keep"]:
        move_items(source.pk, None)  # deleted items only: the active ones are all in parts
        source.delete()


def apply_delete(args, db, ids):
    category = Category.objects.get(pk=db(args["id"]))
    move_items(category.pk, db(args["items_to"]))
    move_children(category.pk, category.parent_category_id)
    category.delete()


APPLY = {"create": apply_create, "update": apply_update, "move": apply_move, "join": apply_join,
         "split": apply_split, "delete": apply_delete}
