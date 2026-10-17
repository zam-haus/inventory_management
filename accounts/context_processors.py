from django.conf import settings


def local_network(request):
    """The name shown for the local network and its members, e.g. "(ZAM)" next to a user name."""
    return {"local_network_name": settings.LOCAL_NETWORK_NAME}


def login(request):
    """Whether templates link to the OIDC (SSO) login and logout or to Django's own."""
    return {"oidc_enabled": settings.OIDC_ENABLED}
