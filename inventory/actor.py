"""
Who is acting right now, for records written deep inside model code (signal
handlers, deletions) where no request is passed along.

CurrentActorMiddleware remembers the request for its duration; outside requests
(management commands, tests) use `acting_as(user)`.
"""
from contextlib import contextmanager
from contextvars import ContextVar

_request = ContextVar("acting_request", default=None)
_user = ContextVar("acting_user", default=None)


class CurrentActorMiddleware:
    """Must come after AuthenticationMiddleware."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        token = _request.set(request)
        try:
            return self.get_response(request)
        finally:
            _request.reset(token)


@contextmanager
def acting_as(user):
    """`user` acts inside; None keeps who acts already."""
    if user is None:
        yield
        return
    token = _user.set(user)
    try:
        yield
    finally:
        _user.reset(token)


def current_actor():
    """The logged-in user responsible for the current change, or None."""
    user = _user.get()
    if user is None:
        user = getattr(_request.get(), "user", None)  # request.user stays lazy until needed here
    return user if user is not None and user.is_authenticated else None


def current_request():
    """The request being handled, or None (management commands, Celery tasks)."""
    return _request.get()
