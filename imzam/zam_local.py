import threading
import json
import ipaddress

from ipware import get_client_ip

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
        ips = list(map(ipaddress.ip_address, zam_ips))
        self.zam_ips = ips

    def __call__(self, request):
        # Code to be executed for each request before
        # the view (and later middleware) are called.

        s = request.session
        current_addr, _ = get_client_ip(request)

        # If request ip changed
        if current_addr is not None and \
                current_addr != s.get('last_seen_remote_addr'):
            # recheck locality, set zam_local accordingly
            s.last_seen_remote_addr = current_addr
            for ip in self.zam_ips:
                if ipaddress.ip_address(current_addr) == ip:
                    s['is_zam_local'] = True
                    break
            else:
                s['is_zam_local'] = False

        #print("is_zam_local", s.is_zam_local)
        #print("current_addr", current_addr)

        response = self.get_response(request)

        # Code to be executed for each request/response after
        # the view is called.

        return response