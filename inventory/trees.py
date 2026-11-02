"""
The item and location trees (docs/trees.md): items by category at /item/, locations as a tree at /location/. Each
tree comes from a fixed number of queries and is rendered here instead of by template recursion, which would
be slow for thousands of nodes. Nodes are <details>, so they open and close without JavaScript; icons are
drawn once in a sprite and referenced by every row.
"""
from collections import Counter
from dataclasses import dataclass, field

from django.db.models import Count, IntegerField, OuterRef, Subquery, Value
from django.db.models.functions import Coalesce
from django.utils.html import format_html, format_html_join
from django.utils.safestring import mark_safe
from django.urls import reverse
from django.utils.translation import gettext as _, ngettext

from . import icons
from .location_display import CATEGORY_ICONS, icon_name, label_html
from .models import Category, Item, ItemLocation, Location, LocationType, UniqueItem
from .search.render import KINDS, SUB_LOCATIONS, count_text
from .structure_overview import code_order

OPEN = mark_safe(" open")


@dataclass
class Node:
    obj: object = None
    children: list = field(default_factory=list)  # child nodes
    own: int = 0  # items right in a category (the item tree loads their rows when it is opened)
    bulk: int = 0  # counted items: stock here (locations) or counted items in the whole subtree (categories)
    unique: int = 0  # unique items here (locations) or in the whole subtree (categories)
    descendants: Counter = field(default_factory=Counter)  # sub-locations in the whole subtree, by icon_name


def sprite(names):
    """The icons as <symbol>s, once per page; rows show them with use_icon()."""
    return icons.sprite(names, "tree-icon", "tree-sprite")


def use_icon(name):
    return icons.use(name, "tree-icon", "bi tree-icon")


def pill(icon, count, text):
    """A count with its icon; the words (e.g. "3 containers") as tooltip and for screen readers."""
    return format_html('<span class="tree-pill" title="{}">{}<span aria-hidden="true">{}</span>'
                       '<span class="visually-hidden">{}</span></span>', text, use_icon(icon), count, text)


def item_pills(node):
    """Counted items, then unique items (the last of the counts, after the locations)."""
    return (pill(KINDS["item"][0], node.bulk, count_text("item", node.bulk)) if node.bulk else "",
            pill(KINDS["unique"][0], node.unique, count_text("unique", node.unique)) if node.unique else "")


def pills(*parts):
    return format_html('<span class="tree-pills">{}</span>', format_html_join("", "{}", ((part,) for part in parts if part)))


def branch(node_id, row, inner, is_open, classes=""):
    return format_html('<li{}{}><details{}><summary>{}</summary><ul>{}</ul></details></li>',
                       format_html(' id="{}"', node_id) if node_id else "",
                       format_html(' class="{}"', classes) if classes else "", OPEN if is_open else "", row, inner)


def leaf(node_id, row):
    return format_html('<li{} class="tree-leaf">{}</li>', format_html(' id="{}"', node_id) if node_id else "", row)


# Locations

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
                      label_html(location, url=location.get_absolute_url(), info=True, icon=False), location_pills(node))
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
    """(sprite, the tree's <li>s) for /location/."""
    roots = location_nodes()
    return sprite({"geo-alt", KINDS["item"][0], KINDS["unique"][0], *CATEGORY_ICONS.values()}), nodes_html(roots, 0)


# Items

def item_nodes():
    """(roots of the category tree, the node of the items without a category). Each node knows how many items are
    right in it (`own`; their rows are loaded when it is opened, tree.js) and, with its subcategories, the counted
    items and the unique items still in the inventory."""
    nodes = {category.pk: Node(category) for category in
             Category.objects.only("pk", "name", "full_name", "parent_category_id")}
    roots = []
    for node in nodes.values():  # in the model's order (full_name), so siblings are sorted by name
        parent = nodes.get(node.obj.parent_category_id)
        (parent.children if parent else roots).append(node)
    none = Node()

    def per_category(queryset, key):
        return dict(queryset.values(key).annotate(n=Count("pk")).values_list(key, "n"))
    own = per_category(Item.active.all(), "category")
    bulk = per_category(Item.active.exclude(kind=Item.Kind.SERIALIZED), "category")
    unique = per_category(UniqueItem.active.filter(item__is_deleted=False), "item__category")
    for pk, node in [*nodes.items(), (None, none)]:
        node.own, node.bulk, node.unique = own.get(pk, 0), bulk.get(pk, 0), unique.get(pk, 0)

    def count(node):
        for child in node.children:
            count(child)
            node.bulk += child.bulk
            node.unique += child.unique
    for root in roots:
        count(root)
    return roots, none


def items_html(node, key, url):
    """Where the items right in a category come as result rows once it is opened (tree.js loads them from
    /item/rows/, 50 at a time, more while scrolling); a link to them, which tree.js loads there too."""
    rows = f"{reverse('item_tree_rows')}?category={key}"
    text = ngettext("Show %(count)s item", "Show %(count)s items", node.own) % {"count": node.own}
    return format_html('<li class="tree-items" data-tree-items="{}"><a class="tree-items-load" href="{}" '
                       'data-tree-items-load>{}</a></li>', rows, url or rows, text)


def category_row(node, name, url=None):
    """A category: its name, linked to its page (all its items), and its counts."""
    name = format_html('<a class="tree-name" href="{}">{}</a>', url, name) if url else \
        format_html('<span class="tree-name">{}</span>', name)
    return format_html('<span class="tree-row">{}{}{}</span>', use_icon(KINDS["category"][0]), name,
                       pills(*item_pills(node)))


def category_html(node):
    url = node.obj.get_absolute_url()
    row = category_row(node, node.obj.name, url)
    if not node.children and not node.own:
        return leaf(f"cat-{node.obj.pk}", row)
    inner = format_html("{}{}", format_html_join("", "{}", ((category_html(child),) for child in node.children)),
                        items_html(node, node.obj.pk, url) if node.own else "")
    return branch(f"cat-{node.obj.pk}", row, inner, False)


def item_tree():
    """(sprite, the tree's <li>s) for /item/: categories, then the items without one."""
    roots, none = item_nodes()
    html = format_html_join("", "{}", ((category_html(root),) for root in roots))
    if none.own:
        html = format_html("{}{}", html, branch("cat-none", category_row(none, _("Without category")),
                                                items_html(none, "none", None), False))
    return sprite({KINDS["category"][0], KINDS["item"][0], KINDS["unique"][0]}), html
