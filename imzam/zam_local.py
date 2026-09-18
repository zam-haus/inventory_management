import ipaddress
import logging
import socket
from time import monotonic

from django.conf import settings
from ipware import get_client_ip

from accounts.groups import remember_zam_membership

logger = logging.getLogger(__name__)


class ZAMLocalMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

        self._networks = ()
        self._expires_at = 0

    def get_networks(self):
        if monotonic() >= self._expires_at:
            networks = []
            for source in settings.ZAM_LOCAL_SOURCES:
                try:
                    networks.append(ipaddress.ip_network(source, strict=False))
                except ValueError:
                    try:
                        # Resolve all IPv4 (A) records, rather than just the first.
                        addresses = socket.gethostbyname_ex(source)[2]
                    except OSError:
                        logger.warning("Could not resolve ZAM-local hostname %s", source)
                        continue
                    networks.extend(ipaddress.ip_network(address) for address in addresses)
            # Replace expired results even when DNS fails; stale addresses must
            # not grant membership. Other configured sources still work.
            self._networks = tuple(networks)
            self._expires_at = monotonic() + settings.ZAM_LOCAL_DNS_CACHE_SECONDS
        return self._networks

    def __call__(self, request):
        # Consume legacy session state before another network check can overwrite it.
        was_local = request.session.pop("is_zam_local", False)
        request.session.pop("last_seen_remote_addr", None)
        user = request.user
        if user.is_authenticated and user.is_zam_local:
            return self.get_response(request)

        is_local = was_local
        if not is_local:
            current_addr, _ = get_client_ip(request)
            try:
                address = ipaddress.ip_address(current_addr)
            except ValueError:
                is_local = False
            else:
                is_local = any(address in network for network in self.get_networks())

        if user.is_authenticated:
            if is_local:
                remember_zam_membership(user)
        elif is_local:
            # Keep a pending visit across the login redirect. This grants no access
            # to anonymous users and is consumed once they authenticate.
            request.session["is_zam_local"] = True
        return self.get_response(request)
