from dataclasses import dataclass, field

KIND_ORDER = {"location": 0, "item": 1, "unique": 2}
# Hits on these count as hits on the name: they rank first and are visible in the title, not named as source.
NAME_KEYS = {"name", "purpose", "code"}


@dataclass
class Hit:
    kind: str  # location, item or unique (a unique item)
    pk: int
    score: int  # 3: exactly its code; 2: the name (or code) matches; 1: other text
    sources: tuple  # where else the words were found (render.SOURCE_LABELS)
    rank: int = 0  # place among the hits of its kind, in the backend's order
    snippets: dict = field(default_factory=dict)  # source → excerpt, from search services only
