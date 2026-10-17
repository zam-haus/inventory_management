from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.db import IntegrityError, connection, transaction
from django.test import TestCase

from inventory.models import Item, ItemLocation, Location, UniqueItem
from inventory.quick_item_views import QuickItemError, hard_delete
from inventory.actor import acting_as

from inventory.label_ids import lookup, services
from inventory.models import LabelId, LabelIdImmutable

from ..label_ids.testing import InventoryFixture, code, make_id


class LifecycleTests(InventoryFixture, TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.create_inventory()
        cls.reserved = make_id("K7R4X")
        cls.spare = make_id("12345")
        cls.third = make_id("ABCDE")

    def claimed(self):
        return services.claim(self.reserved.code, self.item, None)

    def test_generate_batch(self):
        created = services.generate_batch(5, "roll-1")
        self.assertEqual(len({lid.code for lid in created}), 5)
        for lid in created:
            lid.refresh_from_db()
            self.assertEqual((lid.status, lid.batch, lid.target), (LabelId.Status.RESERVED, "roll-1", None))
        with self.assertRaises(services.LabelIdError):
            services.generate_batch(0)

    def test_claim_assigns_permanently(self):
        lid = self.claimed()
        lid.refresh_from_db()
        self.assertEqual((lid.status, lid.item, lid.target_field), (LabelId.Status.ASSIGNED, self.item, "item"))
        self.assertIsNotNone(lid.assigned_at)
        with self.assertRaises(services.LabelIdError):
            services.claim(lid.code, self.other_item, None)
        with self.assertRaises(services.LabelIdError):
            services.claim(self.spare.code, self.item, None)  # one active ID per target

    def test_retire_keeps_target_and_frees_it(self):
        self.claimed()
        lid = services.retire(self.reserved.code, None, "label damaged")
        self.assertEqual((lid.status, lid.item, lid.note), (LabelId.Status.RETIRED, self.item, "label damaged"))
        services.claim(self.spare.code, self.item, None)
        with self.assertRaises(services.LabelIdError):
            services.retire(self.reserved.code, None)
        with self.assertRaises(services.LabelIdError):
            services.claim(self.reserved.code, self.other_item, None)

    def test_unused_label_can_be_voided(self):
        lid = services.retire(self.spare.code, None)
        self.assertEqual((lid.status, lid.target), (LabelId.Status.RETIRED, None))

    def test_url_targets(self):
        lid = services.assign_url(self.spare.code, "https://wiki.zam.haus/Laser", None)
        self.assertEqual((lid.status, lid.target_field), (LabelId.Status.ASSIGNED, "url"))
        for bad in ("javascript:alert(1)", "ftp://zam.haus/x", "not a url"):
            with self.subTest(bad), self.assertRaises(services.LabelIdError):
                services.assign_url(self.third.code, bad, None)

    def test_deleted_targets_cannot_claim(self):
        self.other_item.delete()
        with self.assertRaises(services.LabelIdError):
            services.claim(self.reserved.code, self.other_item, None)

    def test_unknown_code(self):
        with self.assertRaises(services.LabelIdError):
            services.claim(code("YYYYY"), self.item, None)


class ConstraintTests(InventoryFixture, TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.create_inventory()

    def assertRejected(self, **fields):
        with self.assertRaises(IntegrityError), transaction.atomic():
            make_id("K7R4X", **fields)

    def test_status_must_match_targets(self):
        self.assertRejected(status="reserved", item=self.item)
        self.assertRejected(status="assigned")
        self.assertRejected(status="assigned", item=self.item, location=self.location)
        self.assertRejected(status="assigned", item=self.item, url="https://zam.haus")
        self.assertRejected(status="retired", item=self.item, location=self.location)

    def test_one_active_id_per_target(self):
        make_id("12345", status="assigned", item=self.item)
        self.assertRejected(status="assigned", item=self.item)
        make_id("K7R4X", status="retired", item=self.item)  # history is fine

    def test_codes_must_be_canonical(self):
        with self.assertRaises(ValueError):
            LabelId.objects.create(code="K7R4XR")


class ImmutabilityTests(InventoryFixture, TestCase):
    """The database itself refuses relinking and deletion (triggers.py)."""

    @classmethod
    def setUpTestData(cls):
        cls.create_inventory()
        cls.lid = make_id("K7R4X")
        services.claim(cls.lid.code, cls.item, None)

    def raw(self, sql, params):
        with self.assertRaises(IntegrityError), transaction.atomic(), connection.cursor() as cursor:
            cursor.execute(sql, params)

    def test_no_deletion(self):
        with self.assertRaises(LabelIdImmutable):
            LabelId.objects.get(pk=self.lid.pk).delete()
        with self.assertRaises(LabelIdImmutable):
            LabelId.objects.all().delete()
        self.raw("DELETE FROM inventory_labelid WHERE code = %s", [self.lid.code])
        reserved = make_id("12345")
        self.raw("DELETE FROM inventory_labelid WHERE code = %s", [reserved.code])

    def test_no_relinking(self):
        self.raw("UPDATE inventory_labelid SET item_id = %s WHERE code = %s", [self.other_item.pk, self.lid.code])
        self.raw("UPDATE inventory_labelid SET item_id = NULL, location_id = %s WHERE code = %s",
                 [self.location.pk, self.lid.code])
        with self.assertRaises(IntegrityError), transaction.atomic():
            LabelId.objects.filter(pk=self.lid.pk).update(item=self.other_item)
        lid = LabelId.objects.get(pk=self.lid.pk)
        lid.item = self.other_item
        with self.assertRaises(LabelIdImmutable):
            lid.save()

    def test_no_relinking_to_unique_items(self):
        unique_item = UniqueItem.objects.create(item=Item.objects.create(name="Saw", kind=Item.Kind.UNIQUE, measurement_unit=self.unit),
                                     location=self.location)
        self.raw("UPDATE inventory_labelid SET item_id = NULL, unique_item_id = %s WHERE code = %s", [unique_item.pk, self.lid.code])
        assigned = services.claim(make_id("ABCDE").code, unique_item, None)
        self.raw("UPDATE inventory_labelid SET unique_item_id = NULL, item_id = %s WHERE code = %s", [self.other_item.pk, assigned.code])

    def test_retired_target_is_frozen(self):
        services.retire(self.lid.code, None)
        self.raw("UPDATE inventory_labelid SET item_id = %s WHERE code = %s", [self.other_item.pk, self.lid.code])
        voided = make_id("12345")
        services.retire(voided.code, None)
        self.raw("UPDATE inventory_labelid SET url = 'https://zam.haus' WHERE code = %s", [voided.code])

    def test_lifecycle_only_moves_forward(self):
        self.raw("UPDATE inventory_labelid SET status = 'reserved', item_id = NULL WHERE code = %s", [self.lid.code])
        services.retire(self.lid.code, None)
        self.raw("UPDATE inventory_labelid SET status = 'assigned' WHERE code = %s", [self.lid.code])
        lid = LabelId.objects.get(pk=self.lid.pk)
        lid.status = LabelId.Status.ASSIGNED
        with self.assertRaises(LabelIdImmutable):
            lid.save()

    def test_code_cannot_change(self):
        self.raw("UPDATE inventory_labelid SET code = %s WHERE code = %s", [code("12345"), self.lid.code])
        lid = LabelId.objects.get(pk=self.lid.pk)
        lid.code = code("12345")
        with self.assertRaises(LabelIdImmutable):
            lid.save()

    def test_unlinking_only_together_with_retirement(self):
        self.raw("UPDATE inventory_labelid SET item_id = NULL WHERE code = %s", [self.lid.code])
        with transaction.atomic(), connection.cursor() as cursor:
            cursor.execute("UPDATE inventory_labelid SET status = 'retired', item_id = NULL WHERE code = %s",
                           [self.lid.code])
        self.raw("UPDATE inventory_labelid SET item_id = %s WHERE code = %s", [self.item.pk, self.lid.code])

    def test_metadata_stays_editable(self):
        LabelId.objects.filter(pk=self.lid.pk).update(note="on the left side", batch="roll-2")
        lid = LabelId.objects.get(pk=self.lid.pk)
        lid.note = "moved"
        lid.save()
        self.assertEqual(LabelId.objects.get(pk=self.lid.pk).note, "moved")


class TargetDeletionTests(InventoryFixture, TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.create_inventory()
        cls.user = get_user_model().objects.create_user(username="admin")
        cls.for_item = services.claim(make_id("K7R4X").code, cls.item, None)
        cls.for_location = services.claim(make_id("12345").code, cls.location, None)

    def test_soft_delete_keeps_the_id(self):
        self.item.delete()
        lid = LabelId.objects.get(pk=self.for_item.pk)
        self.assertEqual((lid.status, lid.item), (LabelId.Status.ASSIGNED, self.item))

    def test_hard_delete_retires_and_unlinks(self):
        pk = self.item.pk
        self.item.delete()
        with acting_as(self.user):
            Item.objects.get(pk=pk).delete()
        self.assertFalse(Item.objects.filter(pk=pk).exists())
        lid = LabelId.objects.get(pk=self.for_item.pk)
        self.assertEqual((lid.status, lid.target, lid.retired_by), (LabelId.Status.RETIRED, None, self.user))
        for part in ("Drill", f"(#{pk})", str(Item._meta.verbose_name)):
            self.assertIn(part, lid.note)

    def test_already_retired_id_keeps_its_history(self):
        retired = services.retire(self.for_item.code, None, "label damaged")
        services.claim(make_id("ABCDE").code, self.item, None)
        pk = self.item.pk
        self.item.delete()
        Item.objects.get(pk=pk).delete()
        for lid in LabelId.objects.filter(pk__in=[retired.pk, "ABCDEM"]):
            self.assertEqual((lid.status, lid.target), (LabelId.Status.RETIRED, None))
            self.assertIn(f"(#{pk})", lid.note)
        old = LabelId.objects.get(pk=retired.pk)
        self.assertEqual(old.retired_at, retired.retired_at)
        self.assertTrue(old.note.startswith("label damaged\n"))

    def test_hard_delete_of_unique_item(self):
        unique_item = UniqueItem.objects.create(item=Item.objects.create(name="Saw", kind=Item.Kind.UNIQUE, measurement_unit=self.unit),
                                     location=self.location)
        lid = services.claim(make_id("ABCDE").code, unique_item, None)
        unique_item.events.all()._raw_delete(unique_item.events.db)  # the history protects unique items otherwise
        unique_item.delete()
        lid = LabelId.objects.get(pk=lid.pk)
        self.assertEqual((lid.status, lid.target), (LabelId.Status.RETIRED, None))
        self.assertIn("Saw", lid.note)

    def test_hard_delete_of_location(self):
        pk = self.location.pk
        self.location.delete()
        Location.objects.get(pk=pk).delete()
        lid = LabelId.objects.get(pk=self.for_location.pk)
        self.assertEqual((lid.status, lid.target), (LabelId.Status.RETIRED, None))
        self.assertIn(f"(#{pk})", lid.note)

    def test_failed_delete_leaves_the_id_alone(self):
        self.location.delete()
        ItemLocation.objects.create(item=self.other_item, location=self.location, amount=1)
        with self.assertRaises(ValidationError):  # not empty
            Location.objects.get(pk=self.location.pk).delete()
        self.assertEqual(LabelId.objects.get(pk=self.for_location.pk).status, LabelId.Status.ASSIGNED)

    def test_quick_items_with_ids_need_the_item_page(self):
        entry = ItemLocation.objects.create(item=self.item, location=self.location, amount=None)
        with self.assertRaises(QuickItemError):
            hard_delete(entry)


class LookupTests(InventoryFixture, TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.create_inventory()
        cls.lid = services.claim(make_id("K7R4X").code, cls.item, None)

    def test_active_code(self):
        with self.assertNumQueries(1):
            self.assertEqual(lookup.active_code(self.item), "K7R4XD")
        self.assertIsNone(lookup.active_code(self.other_item))
        self.assertEqual(lookup.active_id(self.item), self.lid)

    def test_annotation_needs_one_query(self):
        with self.assertNumQueries(1):
            codes = dict(lookup.annotate_label_code(Item.objects.all()).values_list("pk", "label_code"))
        self.assertEqual(codes, {self.item.pk: "K7R4XD", self.other_item.pk: None})
        services.retire(self.lid.code, None)
        self.assertIsNone(lookup.active_code(self.item))
