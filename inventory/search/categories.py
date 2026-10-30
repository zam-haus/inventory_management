"""
Categories as hits (docs/search.md). There are only a few hundred, so they are matched here in Python, whatever
finds the other hits. A category is found by its name, its keywords (synonyms, so they count like the name) and
the first line of its description (Category.summary); the categories above it are its path, as a location's.
Every word must match the category or its path, at least one the category itself, as in contains.py.
"""
from ..models import Category
from .base import Hit
from .fields import exported_rows, searchable


def texts(category):
    """{source key: [texts]} of what the search may read of the category itself."""
    own = {}
    if searchable(Category, "name"):
        own["name"] = [category.name]
    if searchable(Category, "keywords"):
        own["keywords"] = [word.strip() for word in category.keywords.split(",") if word.strip()]
    if searchable(Category, "description"):
        own["description"] = [category.summary]
    return own


def search(words, limit, scope=None):
    """The first `limit` hits (on the name or a keyword first, then by path), and one more if there are more. With
    `scope`, only the categories below that one."""
    words = [word.casefold() for word in words]
    with_path = searchable(Category, "full_name")
    categories = Category.objects.filter(exported_rows(Category)).only("name", "full_name", "keywords", "description")
    if scope is not None:
        categories = categories.filter(full_name__startswith=f"{scope.full_name}/")
    found = []
    for category in categories:
        own = texts(category)
        matched = {key: {word for word in words if any(word in text.casefold() for text in values)}
                   for key, values in own.items()}
        hit_words = set().union(*matched.values())
        path = category.full_name.rpartition("/")[0].casefold() if with_path else ""
        if not hit_words or not all(word in hit_words or word in path for word in words):
            continue
        named = bool(matched.get("name") or matched.get("keywords"))
        sources = tuple(key for key in ("keywords", "description") if matched.get(key))
        # The keywords that matched, named in the result ("Found in keywords: Spax"): the title does not show them.
        keywords = [keyword for keyword in own.get("keywords", [])
                    if any(word in keyword.casefold() for word in matched.get("keywords", ()))]
        snippets = {"keywords": ", ".join(keywords)} if keywords else {}
        found.append((not named, category.full_name.casefold(), category.pk, sources, snippets))
    found.sort(key=lambda row: row[:3])
    hits = [Hit("category", pk, 1 if unnamed else 2, sources, rank, snippets)
            for rank, (unnamed, _path, pk, sources, snippets) in enumerate(found[:limit + 1])]
    return hits
