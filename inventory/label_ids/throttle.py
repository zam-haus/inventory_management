"""
Light rate limiting for the resolver. Only misses count: IDs are random and not
secret, but enumerating them should be unattractive. Hits are never limited.
"""
from django.conf import settings
from django.core.cache import cache
from ipware import get_client_ip


def _limit():
    return getattr(settings, "LABEL_ID_MISS_LIMIT", 30)


def _window():
    return getattr(settings, "LABEL_ID_MISS_WINDOW", 600)


def _key(request):
    address, _routable = get_client_ip(request)
    return f"label_id:miss:{address or 'unknown'}"


def blocked(request):
    return cache.get(_key(request), 0) >= _limit()


def hit(request):
    key = _key(request)
    if cache.add(key, 1, _window()):
        return
    try:
        cache.incr(key)
    except ValueError:  # expired between add() and incr()
        cache.set(key, 1, _window())
