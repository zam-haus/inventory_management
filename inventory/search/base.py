from dataclasses import dataclass, field

# Categories are broader than items: at the same score they come before the items they hold.
KIND_ORDER = {"location": 0, "category": 1, "item": 2, "unique": 3}
# Hits on these count as hits on the name: they rank first and are visible in the title, not named as source.
NAME_KEYS = {"name", "purpose", "code"}


@dataclass
class Hit:
    kind: str  # location, category, item or unique (a unique item)
    pk: int
    score: int  # 3: exactly its code; 2: the name (or code) matches; 1: other text
    sources: tuple  # where else the words were found (render.SOURCE_LABELS)
    rank: int = 0  # place among the hits of its kind, in the backend's order
    snippets: dict = field(default_factory=dict)  # source → what matched there (a category's keywords, excerpts)
