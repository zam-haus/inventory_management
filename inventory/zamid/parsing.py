"""Turn whatever a person typed or a scanner read into a canonical ZAM ID."""
import re

from . import core

# Scanned labels contain the full resolver URL; the inventory also serves it under /id/.
_URL_PREFIX = re.compile(
    r"^\s*(?:https?://)?(?:(?:i|id)\.zam\.haus/|inv\.zam\.haus/id/)",
    re.IGNORECASE,
)


def strip_url(raw: str) -> str:
    return _URL_PREFIX.sub("", raw).rstrip("/ \t\r\n")


def code_from_scan(raw: str) -> str:
    """Return the canonical ID for typed or scanned input, or raise core.InvalidZamId."""
    return core.normalize(strip_url(raw))


def suggestions_for_scan(raw: str) -> list[str]:
    return core.suggestions(strip_url(raw))
