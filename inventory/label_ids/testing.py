from django.contrib.auth.models import Group
from django.core.cache import cache

from accounts.groups import local_group_name
from ..models import Item, Location, LocationType, MeasurementUnit

from inventory.label_ids import core
from ..models import LabelId

MIDDLEWARE = [
    "inventory.label_ids.middleware.ResolverHostMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "inventory.actor.CurrentActorMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
]
SETTINGS = dict(
    MIDDLEWARE=MIDDLEWARE,
    LANGUAGE_CODE="en",
    ALLOWED_HOSTS=["testserver", "inv.zam.haus", "i.zam.haus", "id.zam.haus"],
    LABEL_ID_RESOLVER_HOSTS=["i.zam.haus", "id.zam.haus"],
    DEFAULT_DOMAIN="https://inv.zam.haus",
    LABEL_ID_INVENTORY_BASE=None,
    LABEL_ID_BASE_URL="https://i.zam.haus/",
    LABEL_ID_NAME="ZAMid",
)


def code(payload):
    return payload + core.check_symbol(payload)


def make_id(payload, **fields):
    return LabelId.objects.create(code=code(payload), **fields)


def local_group():
    return Group.objects.get(name=local_group_name())


class InventoryFixture:
    @classmethod
    def create_inventory(cls):
        cls.unit, _ = MeasurementUnit.objects.get_or_create(pk=1, defaults={"name": "Piece", "short": "pc"})
        cls.kind = LocationType.objects.create(name="Room", unique=True, moveable=True)
        cls.location = Location.objects.create(name="Workshop", short_name="WS", type=cls.kind)
        cls.item = Item.objects.create(name="Drill", measurement_unit=cls.unit)
        cls.other_item = Item.objects.create(name="Saw", measurement_unit=cls.unit)

    def setUp(self):
        super().setUp()
        cache.clear()
