"""
One search over locations, categories, items and unique items (docs/search.md). A backend finds the hits
(categories.py finds the categories); render.py loads what they show from the database, so a stale search index
never shows what is no longer there.
"""
from collections import Counter
from dataclasses import dataclass, field

from . import categories, contains, render
from .base import KIND_ORDER, Hit

PAGE = 50  # hits per page; more are loaded while scrolling
MAX_RESULTS = 500  # beyond that, more words narrow the search
MAX_WORDS = 8


@dataclass
class SearchResult:
    words: list
    hits: list = field(default_factory=list)
    next_offset: int = None  # where the next page starts, if there is one
    capped: bool = False  # there are more hits than MAX_RESULTS
    # Hits of each kind, whether shown or not (the summary to filter by): MAX_RESULTS + 1 means more than that.
    counts: dict = field(default_factory=dict)


def search(query, offset=0, limit=PAGE, category=None, kinds=None):
    """A page of hits: locations, categories, items and unique items mixed, hits on the name first. Each kind keeps
    the backend's order, so that pages neither repeat nor skip a hit. With a category, only what is in it or
    below it (its page); with kinds, only those (the others are still counted)."""
    words = query.split()[:MAX_WORDS]
    offset = max(0, min(offset, MAX_RESULTS))
    limit = max(0, min(limit, MAX_RESULTS - offset))
    if not words or not limit:
        return SearchResult(words, capped=bool(words) and offset >= MAX_RESULTS)
    # Every kind up to the cap, so that the summary counts them all; the scan of the table costs the same.
    found = contains.search(words, MAX_RESULTS, scope=category) + categories.search(words, MAX_RESULTS, scope=category)
    counts = dict(Counter(hit.kind for hit in found))
    shown = sorted((hit for hit in found if hit.rank < MAX_RESULTS and (kinds is None or hit.kind in kinds)),
                   key=lambda hit: (-hit.score, KIND_ORDER[hit.kind], hit.rank))
    more = len(shown) > MAX_RESULTS or any(
        n > MAX_RESULTS for kind, n in counts.items() if kinds is None or kind in kinds)
    shown = shown[:MAX_RESULTS]
    end = offset + limit
    return SearchResult(words, shown[offset:end], next_offset=end if end < len(shown) else None,
                        capped=more and end >= len(shown), counts=counts)


__all__ = ["KIND_ORDER", "Hit", "SearchResult", "render", "search"]
