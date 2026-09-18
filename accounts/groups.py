"""Locally managed membership; never granted or removed by the identity provider."""

ZAM_LOCAL_GROUP_NAME = "ZAM-local"


def remember_zam_membership(user):
    from django.contrib.auth.models import Group

    group, _ = Group.objects.get_or_create(name=ZAM_LOCAL_GROUP_NAME)
    user.groups.add(group)
    # Permissions may already have been evaluated earlier in this request.
    for cache in ("_perm_cache", "_user_perm_cache", "_group_perm_cache"):
        user.__dict__.pop(cache, None)
    getattr(user, "_prefetched_objects_cache", {}).pop("groups", None)
