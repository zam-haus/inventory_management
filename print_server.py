#!/usr/bin/env python3
from paho.mqtt import client as mqttc

# import zpl
import subprocess
import random
import copy
import string

from imzam import settings

LPR_PRINTER_NAME = "Zebra_GK420t"


def on_message(client, userdata, message):
    # this is searialized
    print(message.topic, message.payload, type(message.payload))
    lpr = subprocess.Popen(
        ["lpr", "-P", LPR_PRINTER_NAME, "-o", "raw"], stdin=subprocess.PIPE
    )
    lpr.communicate(message.payload)


def run_server():
    client_kwargs = copy.copy(settings.MQTT_CLIENT_KWARGS)
    # Randomize client id
    client_kwargs['client_id'] += '_' + \
        "".join(random.choices(string.ascii_letters + string.digits, k=8))
    c = mqttc.Client(**client_kwargs)
    c.tls_set()

    def on_connect(client, userdata, flags, rc):
        print("Connected with result code " + str(rc))

        # Subscribing in on_connect() means that if we lose the connection and
        # reconnect then subscriptions will be renewed.
        client.subscribe(settings.MQTT_PRINTER_TOPIC + "#")

    c.on_connect = on_connect
    c.on_message = on_message

    c.connect(**settings.MQTT_SERVER_KWARGS)
    c.loop_forever()


if __name__ == "__main__":
    run_server()
