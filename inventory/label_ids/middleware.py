from django.conf import settings
from django.http.request import split_domain_port

RESOLVER_URLCONF = "inventory.label_ids.urls_resolver"


class ResolverHostMiddleware:
    """
    Serve the permanent resolver hosts (i.zam.haus, id.zam.haus) from their own
    URLconf. Must come before CommonMiddleware so APPEND_SLASH uses that URLconf.
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        domain, _port = split_domain_port(request.get_host())
        hosts = {host.lower() for host in settings.LABEL_ID_RESOLVER_HOSTS}
        request.label_id_resolver_host = domain.lower() in hosts
        if request.label_id_resolver_host:
            request.urlconf = RESOLVER_URLCONF
        return self.get_response(request)
