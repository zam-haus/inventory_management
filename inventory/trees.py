"""
The item and location trees (docs/trees.md): items by category at /item/, locations as a tree at /loc/. Each
tree comes from a fixed number of queries and is rendered here instead of by template recursion, which would
be slow for thousands of nodes. Nodes are <details>, so they open and close without JavaScript; icons are
drawn once in a sprite and referenced by every row.
"""
import re
from collections import Counter
from dataclasses import dataclass, field

from django.db.models import Count, IntegerField, OuterRef, Subquery, Value
from django.db.models.functions import Coalesce, Lower
from django.utils.html import format_html, format_html_join
from django.utils.safestring import mark_safe
from django.utils.translation import gettext as _, ngettext

from .icons import _svg
from .label_ids.lookup import annotate_label_code
from .location_display import CATEGORY_ICONS, icon_name, label_html
from .models import Category, Item, ItemLocation, Location, LocationType, UniqueItem
from .search.render import KINDS, UNIQUE_KIND_ICON
from .structure_overview import code_order

OPEN = mark_safe(" open")


@dataclass
class Node:
    obj: object = None
    children: list = field(default_factory=list)  # child nodes
    leaves: list = field(default_factory=list)  # items of a category
    bulk: int = 0  # counted items: stock here (locations) or counted items in the whole subtree (categories)
    unique: int = 0  # unique items here (locations) or in the whole subtree (categories)
    descendants: Counter = field(default_factory=Counter)  # sub-locations in the whole subtree, by icon_name


def sprite(names):
    """The icons as <symbol>s, once per page; rows show them with use_icon()."""
    symbols = []
    for name in sorted(names):
        svg = _svg(name)
        view_box = re.search(r'viewBox="([^"]*)"', svg).group(1)
        inner = svg[svg.index(">") + 1:svg.rindex("</svg>")]
        symbols.append(format_html('<symbol id="tree-icon-{}" viewBox="{}">{}</symbol>', name, view_box, mark_safe(inner)))
    return format_html('<svg class="tree-sprite" aria-hidden="true" focusable="false">{}</svg>',
                       format_html_join("", "{}", ((symbol,) for symbol in symbols)))


def use_icon(name):
    return format_html('<svg class="bi tree-icon" width="1em" height="1em" aria-hidden="true" focusable="false">'
                       '<use href="#tree-icon-{}"/></svg>', name)


def pill(icon, count, text):
    """A count with its icon; the words (e.g. "3 containers") as tooltip and for screen readers."""
    return format_html('<span class="tree-pill" title="{}">{}<span aria-hidden="true">{}</span>'
                       '<span class="visually-hidden">{}</span></span>', text, use_icon(icon), count, text)


def item_pills(node):
    """Counted items, then unique items (the last of the counts, after the locations)."""
    return (pill(KINDS["item"][0], node.bulk, ngettext("%(count)s item", "%(count)s items", node.bulk)
                 % {"count": node.bulk}) if node.bulk else "",
            pill(KINDS["unique"][0], node.unique, ngettext("%(count)s unique item", "%(count)s unique items",
                                                         node.unique) % {"count": node.unique}) if node.unique else "")


def pills(*parts):
    return format_html('<span class="tree-pills">{}</span>', format_html_join("", "{}", ((part,) for part in parts if part)))


def branch(node_id, row, inner, is_open, classes=""):
    return format_html('<li{}{}><details{}><summary>{}</summary><ul>{}</ul></details></li>',
                       format_html(' id="{}"', node_id) if node_id else "",
                       format_html(' class="{}"', classes) if classes else "", OPEN if is_open else "", row, inner)


def leaf(node_id, row):
    return format_html('<li{} class="tree-leaf">{}</li>', format_html(' id="{}"', node_id) if node_id else "", row)


# Locations

# Sub-locations in the counts, by icon_name: building parts and others, storage units, containers.
SUB_LOCATIONS = (
    ("geo-alt", lambda n: ngettext("%(count)s sub-location", "%(count)s sub-locations", n) % {"count": n}),
    ("bookshelf", lambda n: ngettext("%(count)s storage unit", "%(count)s storage units", n) % {"count": n}),
    ("eurobox-open", lambda n: ngettext("%(count)s container", "%(count)s containers", n) % {"count": n}),
)
STORAGE_UNIT, CONTAINER = LocationType.Category.STORAGE_UNIT, LocationType.Category.CONTAINER


def location_nodes():
    """The roots of the location tree: locations without an active parent, each with its sub-locations, siblings
    by code (levels by number: WH-1 before WH+0)."""
    stock = ItemLocation.objects.filter(location=OuterRef("pk"), item__is_deleted=False).values("location") \
        .annotate(n=Count("pk")).values("n")
    unique = UniqueItem.active.filter(location=OuterRef("pk")).values("location").annotate(n=Count("pk")).values("n")
    locations = (Location.active.select_related("type")
                 .only("pk", "name", "short_name", "purpose", "unique_identifier", "parent_location_id",
                       "type__category")
                 .annotate(stock=Coalesce(Subquery(stock, output_field=IntegerField()), Value(0)),
                           unique=Coalesce(Subquery(unique, output_field=IntegerField()), Value(0))))
    nodes = {location.pk: Node(location, bulk=location.stock, unique=location.unique) for location in locations}
    roots = []
    for node in nodes.values():
        parent = nodes.get(node.obj.parent_location_id)
        (parent.children if parent else roots).append(node)

    def arrange(node):
        node.children.sort(key=lambda child: code_order(child.obj.short_name))
        for child in node.children:
            node.descendants[icon_name(child.obj)] += 1
            node.descendants.update(arrange(child))
        return node.descendants
    roots.sort(key=lambda root: code_order(root.obj.short_name))
    for root in roots:
        arrange(root)
    return roots


def location_pills(node):
    return pills(*(pill(icon, node.descendants[icon], text(node.descendants[icon]))
                   for icon, text in SUB_LOCATIONS if node.descendants[icon]), *item_pills(node))


def location_html(node, depth=0):
    """A location; below it its building parts and others, then its storage units as a group (open, each of them
    closed), then its containers as a group (closed). A group only where it sets them apart from other
    sub-locations, so that the tree stays flat: none if they are all of one kind, and none for the storage units
    of a storage unit (its compartments). Only the top level is open."""
    location = node.obj
    row = format_html('<span class="tree-row">{}{}{}</span>', use_icon(icon_name(location)),
                      label_html(location, url=location.get_absolute_url(), info=True), location_pills(node))
    node_id = f"loc-{location.pk}"
    if not node.children:
        return leaf(node_id, row)
    category = location.type.category
    kinds = {STORAGE_UNIT: [], CONTAINER: [], None: []}
    for child in node.children:
        kinds[child.obj.type.category if child.obj.type.category in kinds else None].append(child)

    def grouped(kind):
        others = len(node.children) - len(kinds[kind])
        return bool(kinds[kind]) and others > 0 and not (kind == STORAGE_UNIT and category == STORAGE_UNIT)

    plain = [child for child in node.children if child.obj.type.category not in kinds or not grouped(
        child.obj.type.category)]
    inner = format_html("{}{}{}", nodes_html(plain, depth + 1),
                        group_html(node, STORAGE_UNIT, _("Storage units"), kinds[STORAGE_UNIT], True, depth)
                        if grouped(STORAGE_UNIT) else "",
                        group_html(node, CONTAINER, _("Containers"), kinds[CONTAINER], False, depth)
                        if grouped(CONTAINER) else "")
    return branch(node_id, row, inner, depth == 0 and category not in (STORAGE_UNIT, CONTAINER))


def nodes_html(nodes, depth):
    return format_html_join("", "{}", ((location_html(node, depth),) for node in nodes))


def group_html(parent, category, title, nodes, is_open, depth):
    """The storage units or containers of a location, as one node."""
    if not nodes:
        return ""
    icon = "bookshelf" if category == STORAGE_UNIT else "eurobox-open"
    text = dict(SUB_LOCATIONS)[icon](len(nodes))
    row = format_html('<span class="tree-row">{}<span class="tree-name">{}</span>{}</span>', use_icon(icon), title,
                      pills(pill(icon, len(nodes), text)))
    return branch(f"loc-{parent.obj.pk}-{category}", row, nodes_html(nodes, depth + 1), is_open, "tree-group")


def location_tree():
    """(sprite, the tree's <li>s) for /loc/."""
    roots = location_nodes()
    return sprite({"geo-alt", KINDS["item"][0], KINDS["unique"][0], *CATEGORY_ICONS.values()}), nodes_html(roots, 0)


# Items

def item_nodes():
    """(roots of the category tree, items without a category). Items are sorted by name; an item tracked as unique
    items has those still in the inventory as `units`, by name and label ID."""
    nodes = {category.pk: Node(category) for category in
             Category.objects.only("pk", "name", "full_name", "parent_category_id")}
    roots = []
    for node in nodes.values():  # in the model's order (full_name), so siblings are sorted by name
        parent = nodes.get(node.obj.parent_category_id)
        (parent.children if parent else roots).append(node)
    uncategorized = []
    items = Item.active.only("pk", "name", "kind", "category_id").order_by(Lower(Coalesce("name", Value(""))), "pk")
    by_pk = {}
    for item in items:
        node = nodes.get(item.category_id)
        (node.leaves if node else uncategorized).append(item)
        item.units = []
        by_pk[item.pk] = item
    for unit in annotate_label_code(UniqueItem.active.only("pk", "name", "item_id")).order_by(
            Lower("name"), "label_code", "pk"):
        item = by_pk.get(unit.item_id)
        if item is not None:
            unit.item = item  # named with it, without a query each
            item.units.append(unit)

    def count(node):
        node.bulk, node.unique = leaf_counts(node.leaves)
        for child in node.children:
            count(child)
            node.bulk += child.bulk
            node.unique += child.unique
    for root in roots:
        count(root)
    return roots, uncategorized


def leaf_counts(items):
    """(counted items, unique items) among `items`."""
    bulk = sum(item.kind != Item.Kind.UNIQUE for item in items)
    return bulk, sum(len(item.units) for item in items)


def item_row(item):
    """An item; one tracked as unique items is a branch with them (closed), each named as everywhere."""
    if item.kind != Item.Kind.UNIQUE:
        return leaf(None, format_html('<span class="tree-row">{}<a href="{}">{}</a></span>',
                                      use_icon(KINDS["item"][0]), item.get_absolute_url(), item))
    row = format_html('<span class="tree-row">{}<a href="{}">{}</a>{}</span>', use_icon(UNIQUE_KIND_ICON),
                      item.get_absolute_url(), item, pills(*item_pills(Node(unique=len(item.units)))))
    if not item.units:
        return leaf(None, row)
    return branch(None, row, format_html_join("", "{}", ((leaf(None, format_html(
        '<span class="tree-row">{}<a href="{}">{}</a></span>', use_icon(KINDS["unique"][0]), unit.get_absolute_url(),
        unit.name_html)),) for unit in item.units)), False)


def category_row(node, name, url=None):
    """A category: its name, linked to its page (all its items), and its counts."""
    name = format_html('<a class="tree-name" href="{}">{}</a>', url, name) if url else \
        format_html('<span class="tree-name">{}</span>', name)
    return format_html('<span class="tree-row">{}{}{}</span>', use_icon("folder"), name, pills(*item_pills(node)))


def category_html(node):
    row = category_row(node, node.obj.name, node.obj.get_absolute_url())
    if not node.children and not node.leaves:
        return leaf(f"cat-{node.obj.pk}", row)
    inner = format_html("{}{}", format_html_join("", "{}", ((category_html(child),) for child in node.children)),
                        format_html_join("", "{}", ((item_row(item),) for item in node.leaves)))
    return branch(f"cat-{node.obj.pk}", row, inner, False)


def item_tree():
    """(sprite, the tree's <li>s) for /item/: categories, then the items without one."""
    roots, uncategorized = item_nodes()
    html = format_html_join("", "{}", ((category_html(root),) for root in roots))
    if uncategorized:
        bulk, unique = leaf_counts(uncategorized)
        none = Node(bulk=bulk, unique=unique)
        html = format_html("{}{}", html, branch(
            "cat-none", category_row(none, _("Without category")),
            format_html_join("", "{}", ((item_row(item),) for item in uncategorized)), False))
    return sprite({"folder", KINDS["item"][0], KINDS["unique"][0], UNIQUE_KIND_ICON}), html
