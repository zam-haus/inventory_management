"""
One search over locations, items and unique items (docs/search.md). A backend finds the hits; render.py
loads what they show from the database, so a stale search index never shows what is no longer there.
"""
from dataclasses import dataclass, field

from . import contains, render
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


def search(query, offset=0, limit=PAGE):
    """A page of hits: locations, items and unique items mixed, hits on the name first. Each kind keeps the
    backend's order, so that pages neither repeat nor skip a hit."""
    words = query.split()[:MAX_WORDS]
    offset = max(0, min(offset, MAX_RESULTS))
    limit = max(0, min(limit, MAX_RESULTS - offset))
    if not words or not limit:
        return SearchResult(words, capped=bool(words) and offset >= MAX_RESULTS)
    hits, more = contains.search(words, offset + limit)
    hits.sort(key=lambda hit: (-hit.score, KIND_ORDER[hit.kind], hit.rank))
    more = more or len(hits) > offset + limit
    end = offset + limit
    return SearchResult(words, hits[offset:end], next_offset=end if more and end < MAX_RESULTS else None,
                        capped=more and end >= MAX_RESULTS)


__all__ = ["Hit", "SearchResult", "render", "search"]
