import threading
import json
import ipaddress

from ipware import get_client_ip

from accounts.groups import remember_zam_membership

from pymaybe import maybe

from . import settings

from paho.mqtt import client as mqttc


class ZAMLocalMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

        # One-time configuration and initialization.
        self.zam_ips = []

        self.mqtt_thread = threading.Thread(target=self.mqtt_connect_and_loop)
        self.mqtt_thread.start()
    
    def mqtt_connect_and_loop(self):
        c = mqttc.Client(**settings.MQTT_CLIENT_KWARGS)
        if settings.MQTT_ZAMIP_SERVER_SSL:
            c.tls_set()
        c.username_pw_set(**settings.MQTT_ZAMIP_PASSWORD_AUTH)
        c.on_connect = self.on_connect
        c.on_message = self.on_message
        c.connect(**settings.MQTT_ZAMIP_SERVER_KWARGS)
        c.loop_forever()

    def on_connect(self, client, userdata, flags, rc):
        # Subscribing in on_connect() means that if we lose the connection and
        # reconnect then subscriptions will be renewed.
        client.subscribe('locator/#')
        
    def on_message(self, client, userdata, message):
        self.set_current_zam_ips(
            maybe(json.loads(message.payload))['ip_addresses'].or_else([]))
    
    def set_current_zam_ips(self, zam_ips):
        ip_ranges = []
        for ip in zam_ips:
            ip_ranges.append(
                ipaddress.ip_network(ip, strict=False)
            )
        self.zam_ips = ip_ranges

    def __call__(self, request):
        # Consume legacy session state before another network check can overwrite it.
        was_local = request.session.pop("is_zam_local", False)
        request.session.pop("last_seen_remote_addr", None)
        user = request.user
        if user.is_authenticated and user.is_zam_local:
            return self.get_response(request)

        current_addr, _ = get_client_ip(request)
        try:
            address = ipaddress.ip_address(current_addr)
        except ValueError:
            is_local = False
        else:
            is_local = any(address in network for network in self.zam_ips)

        if user.is_authenticated:
            if was_local or is_local:
                remember_zam_membership(user)
        elif was_local or is_local:
            # Keep a pending visit across the login redirect. This grants no access
            # to anonymous users and is consumed once they authenticate.
            request.session["is_zam_local"] = True
        return self.get_response(request)
