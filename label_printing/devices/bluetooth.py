"""
Bluetooth label printers (Brother P-touch …BT) through BlueZ on D-Bus; needs python3-dbus and python3-gi
(ops/raspberry-pi/update.sh installs them).

Every scan_interval seconds the adapter looks for devices for a few seconds. Printers it finds (by their
name, "PT-P710BT6522") are paired: by themselves on a print agent without display, else once someone
confirms on the display (ask). Paired printers are listed like USB printers, reached over RFCOMM
(devices.io.RfcommDevice), with a stable ID from their Bluetooth address ("bt-a1b2c3d4e5f6"). A touch screen
also lists the printers found, searches at once, pairs a printer declined before and unpairs one; after each
pairing and unpairing on_change() is called (the agent has BlueZ's pairings saved: ops/raspberry-pi/).

The pairing agent registered with BlueZ accepts only devices this module asked to pair, never a phone that
tries to pair with the Pi by itself.
"""
import logging
import re
import threading

log = logging.getLogger("label_printing.bluetooth")

BLUEZ = "org.bluez"
AGENT_PATH = "/zam/label_agent/pairing"
# Brother's Bluetooth names: model and the last digits of the serial number ("PT-P710BT6522")
BROTHER_NAME = re.compile(r"^PT-([A-Z]\d{3,4}[A-Z]*?BT)", re.IGNORECASE)
BROTHER_DPI = {"P710BT": 180, "P300BT": 180, "E560BT": 180, "P910BT": 360}
# Class of device: major class imaging (0x06), minor bit printer
IMAGING, PRINTER_BIT = 0x06, 0x80


def model_of(name):
    """The Brother model in a device name, or ""."""
    match = BROTHER_NAME.match(name or "")
    return match.group(1).upper() if match else ""


def is_printer(properties):
    """Whether a BlueZ device (its org.bluez.Device1 properties) is a label printer the agent can print on."""
    name = str(properties.get("Name") or properties.get("Alias") or "")
    device_class = int(properties.get("Class") or 0)
    is_imaging = (device_class >> 8) & 0x1F == IMAGING and device_class & PRINTER_BIT
    return bool(model_of(name)) or bool(is_imaging and name.upper().startswith("PT-"))


def printer_entry(properties, channel=1):
    """The printer as the agent reports it (like devices.usb.find_printers)."""
    address = str(properties["Address"]).upper()
    name = str(properties.get("Name") or properties.get("Alias") or address)
    model = model_of(name)
    printer = {
        "uid": "bt-" + address.replace(":", "").lower(),
        "device": f"bt://{address}/{channel}",
        "language": "ptouch",
        "model": model,
        "manufacturer": "Brother",
        "product": name,
        "bluetooth": address,
    }
    if model in BROTHER_DPI:
        printer["dpi"] = BROTHER_DPI[model]
    return printer


class PairRequest:
    """A printer found that is not paired yet, for someone to confirm on the display."""

    def __init__(self, bluetooth, address, name):
        self.bluetooth, self.address, self.name = bluetooth, address, name

    def accept(self):
        self.bluetooth.pair(self.address)

    def decline(self):
        self.bluetooth.decline(self.address)


class Bluetooth:
    """Looks for, pairs and lists Bluetooth printers; runs BlueZ's D-Bus calls in a thread of its own (GLib)."""

    def __init__(self, scan_interval=60, scan_seconds=10, channel=1, pin="0000", ask=None, on_change=None):
        self.scan_interval, self.scan_seconds, self.channel, self.pin = scan_interval, scan_seconds, channel, pin
        self.ask = ask  # ask(PairRequest) on a display, None: pair by itself
        self.on_change = on_change  # after pairing or unpairing: the pairings to keep changed
        self.paired = {}  # address → printer entry
        self.seen = {}  # address → name of printers found, not paired
        self.searching = False
        self.asked, self.declined, self.pairing = set(), set(), set()
        self.status = "starting"  # then "ready", or why not: "no_library", "no_bluez", "no_adapter"
        self.problem = ""  # the error behind it, for the display
        self.lock = threading.Lock()
        self.bus = self.adapter = self.loop = None

    # ------------------------------------------------------------ for the other threads

    def printers(self):
        with self.lock:
            return list(self.paired.values())

    def pair(self, address):
        with self.lock:
            self.declined.discard(address)  # also one declined before: asked for now
        self.call_soon(self._pair, address)

    def unpair(self, address):
        self.call_soon(self._unpair, address)

    def search(self):
        """Look for printers now (else every scan_interval seconds)."""
        self.call_soon(self.scan)

    def found(self):
        """The printers paired and found, for a touch screen: [{"address", "name", "state"}], state "paired",
        "pairing", "declined" or "new"; by name."""
        with self.lock:
            entries = [{"address": address, "name": printer["product"], "state": "paired"}
                       for address, printer in self.paired.items()]
            for address, name in self.seen.items():
                if address not in self.paired:
                    state = ("pairing" if address in self.pairing else "declined" if address in self.declined
                             else "new")
                    entries.append({"address": address, "name": name, "state": state})
        return sorted(entries, key=lambda entry: (entry["name"].lower(), entry["address"]))

    def decline(self, address):
        with self.lock:
            self.declined.add(address)
        log.info("%s: not paired (declined on the display)", address)

    def call_soon(self, function, *args):
        from gi.repository import GLib

        GLib.idle_add(lambda: function(*args) and False)

    # ------------------------------------------------------------ the GLib thread

    def start(self):
        """Connect to BlueZ and run; False (and logs why) if Bluetooth is not available."""
        try:
            import dbus
            import dbus.mainloop.glib
            from gi.repository import GLib
        except ImportError as error:
            log.warning("no Bluetooth: %s (install python3-dbus and python3-gi)", error)
            self.status, self.problem = "no_library", str(error)
            return False
        dbus.mainloop.glib.DBusGMainLoop(set_as_default=True)
        try:
            self.bus = dbus.SystemBus()
            path = self.find_adapter()
        except dbus.DBusException as error:
            log.warning("no Bluetooth: %s", error)
            self.status, self.problem = "no_bluez", str(error.get_dbus_message() or error)
            return False
        if path is None:
            log.warning("no Bluetooth adapter")
            self.status = "no_adapter"
            return False
        self.adapter = dbus.Interface(self.bus.get_object(BLUEZ, path), "org.bluez.Adapter1")
        properties = dbus.Interface(self.bus.get_object(BLUEZ, path), "org.freedesktop.DBus.Properties")
        try:
            properties.Set("org.bluez.Adapter1", "Powered", dbus.Boolean(True))
            self.adapter.SetDiscoveryFilter({"Transport": "bredr"})
        except dbus.DBusException as error:
            log.warning("Bluetooth adapter: %s", error)
        self.register_agent()
        self.loop = GLib.MainLoop()
        threading.Thread(target=self.loop.run, name="bluetooth", daemon=True).start()
        self.status = "ready"
        self.refresh()
        self.call_soon(self.scan)
        GLib.timeout_add_seconds(max(self.scan_interval, self.scan_seconds + 5), lambda: self.scan() or True)
        log.info("Bluetooth on %s: looking for printers every %d s", path, self.scan_interval)
        return True

    def find_adapter(self):
        import dbus

        manager = dbus.Interface(self.bus.get_object(BLUEZ, "/"), "org.freedesktop.DBus.ObjectManager")
        for path, interfaces in manager.GetManagedObjects().items():
            if "org.bluez.Adapter1" in interfaces:
                return str(path)
        return None

    def register_agent(self):
        import dbus
        import dbus.service

        bluetooth = self

        class PairingAgent(dbus.service.Object):
            """Accepts pairing only for the printers this agent asked to pair (BlueZ's org.bluez.Agent1)."""

            def allowed(self, device):
                address = str(bluetooth.bus.get_object(BLUEZ, device).Get(
                    "org.bluez.Device1", "Address", dbus_interface="org.freedesktop.DBus.Properties")).upper()
                with bluetooth.lock:
                    if address not in bluetooth.pairing:
                        log.warning("refused pairing with %s: not asked for", address)
                        raise dbus.DBusException("org.bluez.Error.Rejected", "not asked for")

            @dbus.service.method("org.bluez.Agent1", in_signature="", out_signature="")
            def Release(self):
                pass

            @dbus.service.method("org.bluez.Agent1", in_signature="", out_signature="")
            def Cancel(self):
                pass

            @dbus.service.method("org.bluez.Agent1", in_signature="o", out_signature="s")
            def RequestPinCode(self, device):
                self.allowed(device)
                return bluetooth.pin

            @dbus.service.method("org.bluez.Agent1", in_signature="o", out_signature="u")
            def RequestPasskey(self, device):
                self.allowed(device)
                return dbus.UInt32(int(bluetooth.pin))

            @dbus.service.method("org.bluez.Agent1", in_signature="ou", out_signature="")
            def RequestConfirmation(self, device, passkey):
                self.allowed(device)

            @dbus.service.method("org.bluez.Agent1", in_signature="o", out_signature="")
            def RequestAuthorization(self, device):
                self.allowed(device)

            @dbus.service.method("org.bluez.Agent1", in_signature="os", out_signature="")
            def AuthorizeService(self, device, uuid):
                self.allowed(device)

            @dbus.service.method("org.bluez.Agent1", in_signature="ou", out_signature="")
            def DisplayPasskey(self, device, passkey):
                pass

            @dbus.service.method("org.bluez.Agent1", in_signature="os", out_signature="")
            def DisplayPinCode(self, device, pincode):
                pass

        self.agent = PairingAgent(self.bus, AGENT_PATH)
        manager = dbus.Interface(self.bus.get_object(BLUEZ, "/org/bluez"), "org.bluez.AgentManager1")
        try:
            manager.RegisterAgent(AGENT_PATH, "NoInputNoOutput")
        except dbus.DBusException as error:
            log.warning("Bluetooth pairing agent: %s", error)

    def devices(self):
        """{address: Device1 properties} of the devices BlueZ knows."""
        import dbus

        manager = dbus.Interface(self.bus.get_object(BLUEZ, "/"), "org.freedesktop.DBus.ObjectManager")
        found = {}
        for path, interfaces in manager.GetManagedObjects().items():
            properties = interfaces.get("org.bluez.Device1")
            if properties and "Address" in properties:
                found[str(properties["Address"]).upper()] = dict(properties, path=str(path))
        return found

    def refresh(self):
        """The paired printers as printers; offers the others for pairing."""
        try:
            devices = self.devices()
        except Exception as error:  # D-Bus errors of any kind: try again with the next scan
            log.warning("Bluetooth devices: %s", error)
            return
        paired = {address: printer_entry(properties, self.channel) for address, properties in devices.items()
                  if is_printer(properties) and properties.get("Paired")}
        with self.lock:
            for address in set(paired) - set(self.paired):
                log.info("Bluetooth printer: %s (%s)", paired[address]["product"], address)
            self.paired = paired
            self.seen = {address: str(properties.get("Name") or properties.get("Alias") or address)
                         for address, properties in devices.items()
                         if is_printer(properties) and not properties.get("Paired")}
            new = [(address, properties) for address, properties in devices.items()
                   if is_printer(properties) and not properties.get("Paired") and address not in self.declined
                   and address not in self.asked and address not in self.pairing]
        for address, properties in new:
            name = str(properties.get("Name") or properties.get("Alias") or address)
            if self.ask is None:
                self._pair(address)
            else:
                with self.lock:
                    self.asked.add(address)
                self.ask(PairRequest(self, address, name))

    def scan(self):
        from gi.repository import GLib

        if self.searching:
            return
        try:
            self.adapter.StartDiscovery()
        except Exception as error:
            log.debug("Bluetooth discovery: %s", error)
            return
        self.searching = True
        GLib.timeout_add_seconds(self.scan_seconds, self.end_scan)

    def end_scan(self):
        try:
            self.adapter.StopDiscovery()
        except Exception as error:
            log.debug("Bluetooth discovery: %s", error)
        self.searching = False
        self.refresh()
        return False

    def changed(self):
        if self.on_change is not None:
            try:
                self.on_change()
            except Exception:  # keeping the pairings must not break Bluetooth
                log.exception("Bluetooth pairings not kept")

    def _unpair(self, address):
        devices = self.devices()
        if address not in devices:
            return
        try:
            self.adapter.RemoveDevice(devices[address]["path"])
        except Exception as error:
            log.warning("unpairing %s failed: %s", address, error)
            return
        with self.lock:
            self.declined.add(address)  # not asked again until the agent restarts or it is paired on the display
        log.info("unpaired %s", address)
        self.refresh()
        self.changed()

    def _pair(self, address):
        import dbus

        devices = self.devices()
        if address not in devices:
            return
        path = devices[address]["path"]
        with self.lock:
            self.pairing.add(address)
            self.asked.discard(address)
        device = dbus.Interface(self.bus.get_object(BLUEZ, path), "org.bluez.Device1")
        log.info("pairing with %s (%s)", devices[address].get("Name", ""), address)

        def done():
            properties = dbus.Interface(self.bus.get_object(BLUEZ, path), "org.freedesktop.DBus.Properties")
            properties.Set("org.bluez.Device1", "Trusted", dbus.Boolean(True))
            with self.lock:
                self.pairing.discard(address)
            log.info("paired with %s", address)
            self.refresh()
            self.changed()

        def failed(error):
            with self.lock:
                self.pairing.discard(address)
                self.declined.add(address)  # not again until the agent restarts
            log.warning("pairing with %s failed: %s", address, error)

        device.Pair(reply_handler=done, error_handler=failed, timeout=60)
