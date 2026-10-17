"""Locally managed membership; never granted or removed by the identity provider."""
from django.conf import settings


def local_group_name():
    """Members recognized on the local network (settings.LOCAL_GROUP_NAME, by default "ZAM-local")."""
    return settings.LOCAL_GROUP_NAME


def remember_local_membership(user):
    from django.contrib.auth.models import Group

    group, _ = Group.objects.get_or_create(name=local_group_name())
    user.groups.add(group)
    # Permissions may already have been evaluated earlier in this request.
    for cache in ("_perm_cache", "_user_perm_cache", "_group_perm_cache"):
        user.__dict__.pop(cache, None)
    getattr(user, "_prefetched_objects_cache", {}).pop("groups", None)
