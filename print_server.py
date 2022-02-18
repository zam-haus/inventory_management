#!/usr/bin/env python3
from paho.mqtt import client as mqttc
#import zpl
import subprocess

MQTT_CLIENT_KWARGS = dict(transport="websockets")
MQTT_SERVER_KWARGS = dict(host="mqtt.zam.haus", port=443, keepalive=120)

PRINTER_NAME = "Zebra_GK420t"

def on_message(client, userdata, message):
    # this is searialized
    print(message.topic, message.payload, type(message.payload))
    lpr = subprocess.Popen(['lpr', '-P', PRINTER_NAME, '-o', 'raw'], stdin=subprocess.PIPE)
    lpr.communicate(message.payload)

def run_server():
    c = mqttc.Client(**MQTT_CLIENT_KWARGS)
    c.tls_set()

    def on_connect(client, userdata, flags, rc):
        print("Connected with result code "+str(rc))

        # Subscribing in on_connect() means that if we lose the connection and
        # reconnect then subscriptions will be renewed.
        client.subscribe("im-label-print-queue/#")
    c.on_connect = on_connect
    c.on_message = on_message

    c.connect(**MQTT_SERVER_KWARGS)
    c.loop_forever()


if __name__ == '__main__':
    run_server()
