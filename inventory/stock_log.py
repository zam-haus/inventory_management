"""Context for logging stock changes.

Every changed amount and every removed stock entry is logged as a
`StockChange`; quick-items (unknown amount) are not stock and never logged. The
stock dialog logs explicitly, with the direction and reason the user chose. All
other paths (item form, admin, dissolution) are logged automatically by
`ItemLocation`; `stock_changes()` tells it who made the change, why, and through
which part of the application. Increases without a given reason count as found
during a recount.
"""

from contextlib import contextmanager
from contextvars import ContextVar

_current = ContextVar("stock_changes", default=None)


@contextmanager
def stock_changes(*, actor=None, source, decrease_reason=None, increase_reason=None, note="", log=True):
    """Attribute automatically logged changes; `log=False` suppresses them."""
    token = _current.set({
        "actor": actor if actor is not None and actor.is_authenticated else None,
        "source": source, "decrease_reason": decrease_reason, "increase_reason": increase_reason,
        "note": note, "log": log,
    })
    try:
        yield
    finally:
        _current.reset(token)


def current_stock_changes():
    return _current.get()
