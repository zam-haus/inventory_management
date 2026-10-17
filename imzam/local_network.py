import ipaddress
import logging
import socket
from time import monotonic

from django.conf import settings
from ipware import get_client_ip

from accounts.groups import remember_local_membership

logger = logging.getLogger(__name__)


class LocalNetworkMiddleware:
    """
    Requests from settings.LOCAL_NETWORK_SOURCES make logged-in users members of the
    local group (settings.LOCAL_GROUP_NAME); anonymous visits are remembered until login.
    """

    def __init__(self, get_response):
        self.get_response = get_response

        self._networks = ()
        self._expires_at = 0

    def get_networks(self):
        if monotonic() >= self._expires_at:
            networks = []
            for source in settings.LOCAL_NETWORK_SOURCES:
                try:
                    networks.append(ipaddress.ip_network(source, strict=False))
                except ValueError:
                    try:
                        # Resolve all IPv4 (A) records, rather than just the first.
                        addresses = socket.gethostbyname_ex(source)[2]
                    except OSError:
                        logger.warning("Could not resolve local network hostname %s", source)
                        continue
                    networks.extend(ipaddress.ip_network(address) for address in addresses)
            # Replace expired results even when DNS fails; stale addresses must
            # not grant membership. Other configured sources still work.
            self._networks = tuple(networks)
            self._expires_at = monotonic() + settings.LOCAL_NETWORK_DNS_CACHE_SECONDS
        return self._networks

    def address_is_local(self, request):
        current_addr, _ = get_client_ip(request)
        try:
            address = ipaddress.ip_address(current_addr)
        except ValueError:
            return False
        return any(address in network for network in self.get_networks())

    def __call__(self, request):
        # This request's network, independent of the user's local group (e.g. for label ID accesses).
        request.from_local_network = self.address_is_local(request)
        # Consume pending state before another network check can overwrite it; "is_zam_local"
        # and "last_seen_remote_addr" are sessions from before the rename.
        was_local = any([request.session.pop("is_local_visit", False), request.session.pop("is_zam_local", False)])
        request.session.pop("last_seen_remote_addr", None)
        user = request.user
        if user.is_authenticated and user.is_local_member:
            return self.get_response(request)

        is_local = was_local or request.from_local_network

        if user.is_authenticated:
            if is_local:
                remember_local_membership(user)
        elif is_local:
            # Keep a pending visit across the login redirect. This grants no access
            # to anonymous users and is consumed once they authenticate.
            request.session["is_local_visit"] = True
        return self.get_response(request)
