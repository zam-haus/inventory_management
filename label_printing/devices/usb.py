"""
Finding USB label printers on Linux: printers the kernel's usblp driver serves as /dev/usb/lpN,
with vendor, product and serial number from sysfs. The ID ("usb-04f9-2085-A2B3C4D5E6") stays
the same when the printer is plugged into another port or computer.
"""
import glob
import os

BROTHER, ZEBRA = 0x04F9, 0x0A5F
LANGUAGES = {BROTHER: "ptouch", ZEBRA: "zpl"}
# USB product IDs of the P-touch models the inventory prints on (as in the ptouch library).
BROTHER_MODELS = {0x2060: "E550W", 0x2065: "P750W", 0x2083: "P900", 0x2085: "P900W", 0x2086: "P950NW"}
BROTHER_DPI = {"E550W": 180, "P750W": 180, "P900": 360, "P900W": 360, "P950NW": 360}


def read(path):
    try:
        with open(path, encoding="utf-8", errors="replace") as file:
            return file.read().strip()
    except OSError:
        return ""


def find_printers(sysfs="/sys/class/usbmisc", dev="/dev/usb"):
    """USB printers of Brother and Zebra: [{"uid", "device", "language", "model", "manufacturer", …}]."""
    printers = []
    for entry in sorted(glob.glob(os.path.join(sysfs, "lp*"))):
        # lpN/device is the USB interface; its parent directory is the USB device.
        usb = os.path.dirname(os.path.realpath(os.path.join(entry, "device")))
        vendor, product = read(os.path.join(usb, "idVendor")), read(os.path.join(usb, "idProduct"))
        if not vendor or not product:
            continue
        vendor_id, product_id = int(vendor, 16), int(product, 16)
        language = LANGUAGES.get(vendor_id)
        if language is None:
            continue
        serial = read(os.path.join(usb, "serial"))
        model = BROTHER_MODELS.get(product_id, "") if vendor_id == BROTHER else ""
        printer = {
            "uid": f"usb-{vendor}-{product}-{serial or os.path.basename(usb)}",
            "device": os.path.join(dev, os.path.basename(entry)),
            "language": language,
            "model": model,
            "manufacturer": read(os.path.join(usb, "manufacturer")),
            "product": read(os.path.join(usb, "product")),
            "serial": serial,
            "usb_id": f"{vendor}:{product}",
            "usb_port": os.path.basename(usb),
        }
        if model in BROTHER_DPI:
            printer["dpi"] = BROTHER_DPI[model]
        printers.append(printer)
    return printers
