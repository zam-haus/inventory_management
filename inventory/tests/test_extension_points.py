"""Optional apps (e.g. maps) plug into the inventory through template slots and the `moved` signal."""
import ast
from pathlib import Path

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.template import Context, Template
from django.test import TestCase, override_settings
from django.urls import reverse

from .. import slots
from ..models import Item, Location, LocationType, MeasurementUnit, UniqueItem
from ..signals import moved


@override_settings(TEMPLATES=[{
    "BACKEND": "django.template.backends.django.DjangoTemplates",
    "OPTIONS": {"loaders": [("django.template.loaders.locmem.Loader",
                             {"part.html": "part {{ name }} in {{ slot_name }}\n"})]},
}])
class SlotTests(TestCase):
    def render(self, **context):
        return Template('{% load slots %}[{% slot "test.place" %}]').render(Context(context))

    def test_an_empty_slot_renders_nothing(self):
        self.assertEqual(self.render(), "[]")

    def test_registered_templates_render_with_the_context(self):
        slots.register("test.place", "part.html")
        self.addCleanup(slots.unregister, "test.place", "part.html")
        slots.register("test.place", "part.html")  # once only
        self.assertEqual(self.render(name="<b>x</b>"), "[part &lt;b&gt;x&lt;/b&gt; in test.place\n]")


@override_settings(LANGUAGE_CODE="en")
class MovedSignalTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        room = LocationType.objects.create(name="Raum", unique=True, structure="room", category="space")
        pallet = LocationType.objects.create(name="Palette", unique=True, moveable=True, category="container")
        cls.hall = Location.objects.create(type=room, name="Halle", short_name="HAL")
        cls.store = Location.objects.create(type=room, name="Lager", short_name="LAG")
        cls.pallet = Location.objects.create(type=pallet, name="Palette 1", short_name="P1", parent_location=cls.hall)
        unit = MeasurementUnit.objects.create(name="Piece", short="pc")
        cls.item = Item.objects.create(name="Saw", kind=Item.Kind.UNIQUE, measurement_unit=unit)
        cls.saw = UniqueItem.objects.create(item=cls.item, location=cls.hall)
        cls.member = get_user_model().objects.create_user(username="member")
        cls.member.user_permissions.add(*Permission.objects.filter(
            content_type__app_label="inventory", codename__in=["change_location", "change_uniqueitem"]))

    def setUp(self):
        self.calls = []

        def listener(sender, instance, old_parent, context, **kwargs):
            self.calls.append((sender, instance.pk, old_parent, context))

        moved.connect(listener)
        self.addCleanup(moved.disconnect, listener)

    def test_a_location_with_a_new_parent(self):
        self.pallet.name = "Palette eins"
        self.pallet.save()
        self.assertEqual(self.calls, [])
        self.pallet.parent_location = self.store
        self.pallet.move_context = {"extra": "1"}
        self.pallet.save()
        self.assertEqual(self.calls, [(Location, self.pallet.pk, self.hall.pk, {"extra": "1"})])
        self.pallet.save()  # the context is used up
        self.assertEqual(len(self.calls), 1)

    def test_a_unique_item_moved_and_disposed(self):
        self.saw.location = self.store
        self.saw.save()
        self.saw.dispose(UniqueItem.DisposalReason.SOLD)
        self.assertEqual(self.calls, [(UniqueItem, self.saw.pk, self.hall.pk, {}),
                                      (UniqueItem, self.saw.pk, self.store.pk, {})])

    def test_the_move_dialogs_pass_what_they_got(self):
        self.client.force_login(self.member)
        self.client.post(reverse("location_move", args=[self.pallet.pk]),
                         {"parent_location": self.store.pk, "extra": "a"})
        self.client.post(reverse("move_unique_item", args=[self.saw.pk]), {"location": self.store.pk, "extra": "b"})
        self.assertEqual([(sender, pk, old, context.get("extra")) for sender, pk, old, context in self.calls],
                         [(Location, self.pallet.pk, self.hall.pk, "a"), (UniqueItem, self.saw.pk, self.hall.pk, "b")])


class IndependenceTests(TestCase):
    def test_inventory_never_imports_the_maps_app(self):
        for path in Path(__file__).resolve().parents[1].rglob("*.py"):
            for node in ast.walk(ast.parse(path.read_text(), str(path))):
                names = [alias.name for alias in node.names] if isinstance(node, ast.Import) else \
                    [node.module or ""] if isinstance(node, ast.ImportFrom) and not node.level else []
                for name in names:
                    self.assertNotEqual(name.split(".")[0], "maps", f"{path} imports {name}")
