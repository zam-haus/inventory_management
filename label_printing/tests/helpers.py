from django.contrib.auth import get_user_model

from inventory.models import LocationLabelTemplate
from .. import simulator
from ..models import LabelMedium, Printer

SETTINGS = dict(LANGUAGE_CODE="en", DEFAULT_URL="https://inv.zam.haus", LABEL_ID_BASE_URL="https://i.zam.haus/",
                PRINT_JOB_MAX_AGE=120, PRINT_JOB_LEASE=180, PRINT_AGENT_OFFLINE_AFTER=30,
                PRINT_MAX_COPIES=20, PRINT_CONFIRM_LABELS=10, PRINT_MAX_LABELS=50, CELERY_TASK_ALWAYS_EAGER=True)


class SimulatedPrinters:
    """Fake Zebra and Brother printers on local ports for the test class (ZPL is not rendered)."""

    @classmethod
    def setUpClass(cls):
        # Before super(), whose setUpTestData creates printers on these ports.
        cls.zebra_state = simulator.PrinterState(name="zebra")
        cls.zebra_output = simulator.Output()
        cls.zebra_server = simulator.start("zebra", state=cls.zebra_state, output=cls.zebra_output, render=None,
                                           seconds_per_label=0.05)
        cls.brother_state = simulator.PrinterState(name="brother", tape_mm=12)
        cls.brother_output = simulator.Output()
        cls.brother_server = simulator.start("brother", state=cls.brother_state, output=cls.brother_output)
        cls.addClassCleanup(cls.zebra_server.stop)
        cls.addClassCleanup(cls.brother_server.stop)
        super().setUpClass()

    def setUp(self):
        super().setUp()
        for state in (self.zebra_state, self.brother_state):
            state.errors, state.silent = [], False
        self.brother_state.tape_mm = 12
        self.zebra_output.printed.clear()
        self.brother_output.printed.clear()


def create_printers(zebra_port=9100, brother_port=9100):
    """A Zebra with 57 × 32 mm labels (loaded) and a Brother PT-E550W with 12 mm tape, both network printers."""
    zebra = Printer.objects.create(name="Zebra Lager", slug="zebra", language="zpl", dpi=203,
                                   host="127.0.0.1", port=zebra_port, is_default=True)
    zebra_labels = LabelMedium.objects.create(printer=zebra, name="57 × 32 mm", width_mm=57, height_mm=32,
                                              is_default=True)
    zebra.loaded_medium = zebra_labels
    zebra.save()
    brother = Printer.objects.create(name="P-touch Werkstatt", slug="ptouch", language="ptouch", model="E550W",
                                     dpi=180, host="127.0.0.1", port=brother_port)
    brother_tape = LabelMedium.objects.create(printer=brother, name="12 mm", ptouch_tape=12, is_default=True)
    return zebra, zebra_labels, brother, brother_tape


def create_user(username="printer-user", *permissions):
    from django.contrib.auth.models import Permission

    user = get_user_model().objects.create_user(username=username, password="pw")
    for codename in permissions:
        app_label, codename = codename.split(".")
        user.user_permissions.add(Permission.objects.get(content_type__app_label=app_label, codename=codename))
    return user


# The label templates the migrations make for every label size (label_printing 0002)
GENERATED = {
    "location": "QR-Code, Kennung, Name und Ort",
    "item": "Name, Preis und QR-Code",
    "labelid": "ZAMid",
    "labelid_plain": "ZAMid: QR + ID",
}


def generated(kind, size):
    """A template of GENERATED for a size key, e.g. generated("location", "tape12") or ("item", "57x32")."""
    if size.startswith("tape"):
        width, height = None, float(size.removeprefix("tape"))
    else:
        width, height = (float(part) for part in size.split("x"))
    return LocationLabelTemplate.objects.get(name=GENERATED[kind], label_width=width, label_height=height)


def outcome_key(kind, size):
    """The print dialog's key of a generated template on labels of that size, e.g. "design:7@tape12"."""
    return f"design:{generated(kind, size).pk}@{size}"
