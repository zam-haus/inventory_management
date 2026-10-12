from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.db import IntegrityError, connection, transaction
from django.test import TestCase

from inventory.models import Item, ItemLocation, Location, UniqueItem
from inventory.quick_item_views import QuickItemError, hard_delete
from inventory.actor import acting_as

from inventory.zamid import lookup, services
from inventory.models import ZamId, ZamIdImmutable

from ..zamid.testing import InventoryFixture, code, make_id


class LifecycleTests(InventoryFixture, TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.create_inventory()
        cls.reserved = make_id("K7Q4X")
        cls.spare = make_id("12345")
        cls.third = make_id("ABCDE")

    def claimed(self):
        return services.claim(self.reserved.code, self.item, None)

    def test_generate_batch(self):
        created = services.generate_batch(5, "roll-1")
        self.assertEqual(len({zid.code for zid in created}), 5)
        for zid in created:
            zid.refresh_from_db()
            self.assertEqual((zid.status, zid.batch, zid.target), (ZamId.Status.RESERVED, "roll-1", None))
        with self.assertRaises(services.ZamIdError):
            services.generate_batch(0)

    def test_claim_assigns_permanently(self):
        zid = self.claimed()
        zid.refresh_from_db()
        self.assertEqual((zid.status, zid.item, zid.target_field), (ZamId.Status.ASSIGNED, self.item, "item"))
        self.assertIsNotNone(zid.assigned_at)
        with self.assertRaises(services.ZamIdError):
            services.claim(zid.code, self.other_item, None)
        with self.assertRaises(services.ZamIdError):
            services.claim(self.spare.code, self.item, None)  # one active ID per target

    def test_retire_keeps_target_and_frees_it(self):
        self.claimed()
        zid = services.retire(self.reserved.code, None, "label damaged")
        self.assertEqual((zid.status, zid.item, zid.note), (ZamId.Status.RETIRED, self.item, "label damaged"))
        services.claim(self.spare.code, self.item, None)
        with self.assertRaises(services.ZamIdError):
            services.retire(self.reserved.code, None)
        with self.assertRaises(services.ZamIdError):
            services.claim(self.reserved.code, self.other_item, None)

    def test_unused_label_can_be_voided(self):
        zid = services.retire(self.spare.code, None)
        self.assertEqual((zid.status, zid.target), (ZamId.Status.RETIRED, None))

    def test_url_targets(self):
        zid = services.assign_url(self.spare.code, "https://wiki.zam.haus/Laser", None)
        self.assertEqual((zid.status, zid.target_field), (ZamId.Status.ASSIGNED, "url"))
        for bad in ("javascript:alert(1)", "ftp://zam.haus/x", "not a url"):
            with self.subTest(bad), self.assertRaises(services.ZamIdError):
                services.assign_url(self.third.code, bad, None)

    def test_deleted_targets_cannot_claim(self):
        self.other_item.delete()
        with self.assertRaises(services.ZamIdError):
            services.claim(self.reserved.code, self.other_item, None)

    def test_unknown_code(self):
        with self.assertRaises(services.ZamIdError):
            services.claim(code("YYYYY"), self.item, None)


class ConstraintTests(InventoryFixture, TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.create_inventory()

    def assertRejected(self, **fields):
        with self.assertRaises(IntegrityError), transaction.atomic():
            make_id("K7Q4X", **fields)

    def test_status_must_match_targets(self):
        self.assertRejected(status="reserved", item=self.item)
        self.assertRejected(status="assigned")
        self.assertRejected(status="assigned", item=self.item, location=self.location)
        self.assertRejected(status="assigned", item=self.item, url="https://zam.haus")
        self.assertRejected(status="retired", item=self.item, location=self.location)

    def test_one_active_id_per_target(self):
        make_id("12345", status="assigned", item=self.item)
        self.assertRejected(status="assigned", item=self.item)
        make_id("K7Q4X", status="retired", item=self.item)  # history is fine

    def test_codes_must_be_canonical(self):
        with self.assertRaises(ValueError):
            ZamId.objects.create(code="K7Q4XR")


class ImmutabilityTests(InventoryFixture, TestCase):
    """The database itself refuses relinking and deletion (triggers.py)."""

    @classmethod
    def setUpTestData(cls):
        cls.create_inventory()
        cls.zid = make_id("K7Q4X")
        services.claim(cls.zid.code, cls.item, None)

    def raw(self, sql, params):
        with self.assertRaises(IntegrityError), transaction.atomic(), connection.cursor() as cursor:
            cursor.execute(sql, params)

    def test_no_deletion(self):
        with self.assertRaises(ZamIdImmutable):
            ZamId.objects.get(pk=self.zid.pk).delete()
        with self.assertRaises(ZamIdImmutable):
            ZamId.objects.all().delete()
        self.raw("DELETE FROM inventory_zamid WHERE code = %s", [self.zid.code])
        reserved = make_id("12345")
        self.raw("DELETE FROM inventory_zamid WHERE code = %s", [reserved.code])

    def test_no_relinking(self):
        self.raw("UPDATE inventory_zamid SET item_id = %s WHERE code = %s", [self.other_item.pk, self.zid.code])
        self.raw("UPDATE inventory_zamid SET item_id = NULL, location_id = %s WHERE code = %s",
                 [self.location.pk, self.zid.code])
        with self.assertRaises(IntegrityError), transaction.atomic():
            ZamId.objects.filter(pk=self.zid.pk).update(item=self.other_item)
        zid = ZamId.objects.get(pk=self.zid.pk)
        zid.item = self.other_item
        with self.assertRaises(ZamIdImmutable):
            zid.save()

    def test_no_relinking_to_unique_items(self):
        unique_item = UniqueItem.objects.create(item=Item.objects.create(name="Saw", kind=Item.Kind.UNIQUE, measurement_unit=self.unit),
                                     location=self.location)
        self.raw("UPDATE inventory_zamid SET item_id = NULL, unique_item_id = %s WHERE code = %s", [unique_item.pk, self.zid.code])
        assigned = services.claim(make_id("ABCDE").code, unique_item, None)
        self.raw("UPDATE inventory_zamid SET unique_item_id = NULL, item_id = %s WHERE code = %s", [self.other_item.pk, assigned.code])

    def test_retired_target_is_frozen(self):
        services.retire(self.zid.code, None)
        self.raw("UPDATE inventory_zamid SET item_id = %s WHERE code = %s", [self.other_item.pk, self.zid.code])
        voided = make_id("12345")
        services.retire(voided.code, None)
        self.raw("UPDATE inventory_zamid SET url = 'https://zam.haus' WHERE code = %s", [voided.code])

    def test_lifecycle_only_moves_forward(self):
        self.raw("UPDATE inventory_zamid SET status = 'reserved', item_id = NULL WHERE code = %s", [self.zid.code])
        services.retire(self.zid.code, None)
        self.raw("UPDATE inventory_zamid SET status = 'assigned' WHERE code = %s", [self.zid.code])
        zid = ZamId.objects.get(pk=self.zid.pk)
        zid.status = ZamId.Status.ASSIGNED
        with self.assertRaises(ZamIdImmutable):
            zid.save()

    def test_code_cannot_change(self):
        self.raw("UPDATE inventory_zamid SET code = %s WHERE code = %s", [code("12345"), self.zid.code])
        zid = ZamId.objects.get(pk=self.zid.pk)
        zid.code = code("12345")
        with self.assertRaises(ZamIdImmutable):
            zid.save()

    def test_unlinking_only_together_with_retirement(self):
        self.raw("UPDATE inventory_zamid SET item_id = NULL WHERE code = %s", [self.zid.code])
        with transaction.atomic(), connection.cursor() as cursor:
            cursor.execute("UPDATE inventory_zamid SET status = 'retired', item_id = NULL WHERE code = %s",
                           [self.zid.code])
        self.raw("UPDATE inventory_zamid SET item_id = %s WHERE code = %s", [self.item.pk, self.zid.code])

    def test_metadata_stays_editable(self):
        ZamId.objects.filter(pk=self.zid.pk).update(note="on the left side", batch="roll-2")
        zid = ZamId.objects.get(pk=self.zid.pk)
        zid.note = "moved"
        zid.save()
        self.assertEqual(ZamId.objects.get(pk=self.zid.pk).note, "moved")


class TargetDeletionTests(InventoryFixture, TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.create_inventory()
        cls.user = get_user_model().objects.create_user(username="admin")
        cls.for_item = services.claim(make_id("K7Q4X").code, cls.item, None)
        cls.for_location = services.claim(make_id("12345").code, cls.location, None)

    def test_soft_delete_keeps_the_id(self):
        self.item.delete()
        zid = ZamId.objects.get(pk=self.for_item.pk)
        self.assertEqual((zid.status, zid.item), (ZamId.Status.ASSIGNED, self.item))

    def test_hard_delete_retires_and_unlinks(self):
        pk = self.item.pk
        self.item.delete()
        with acting_as(self.user):
            Item.objects.get(pk=pk).delete()
        self.assertFalse(Item.objects.filter(pk=pk).exists())
        zid = ZamId.objects.get(pk=self.for_item.pk)
        self.assertEqual((zid.status, zid.target, zid.retired_by), (ZamId.Status.RETIRED, None, self.user))
        for part in ("Drill", f"(#{pk})", str(Item._meta.verbose_name)):
            self.assertIn(part, zid.note)

    def test_already_retired_id_keeps_its_history(self):
        retired = services.retire(self.for_item.code, None, "label damaged")
        services.claim(make_id("ABCDE").code, self.item, None)
        pk = self.item.pk
        self.item.delete()
        Item.objects.get(pk=pk).delete()
        for zid in ZamId.objects.filter(pk__in=[retired.pk, "ABCDEM"]):
            self.assertEqual((zid.status, zid.target), (ZamId.Status.RETIRED, None))
            self.assertIn(f"(#{pk})", zid.note)
        old = ZamId.objects.get(pk=retired.pk)
        self.assertEqual(old.retired_at, retired.retired_at)
        self.assertTrue(old.note.startswith("label damaged\n"))

    def test_hard_delete_of_unique_item(self):
        unique_item = UniqueItem.objects.create(item=Item.objects.create(name="Saw", kind=Item.Kind.UNIQUE, measurement_unit=self.unit),
                                     location=self.location)
        zid = services.claim(make_id("ABCDE").code, unique_item, None)
        unique_item.events.all()._raw_delete(unique_item.events.db)  # the history protects unique items otherwise
        unique_item.delete()
        zid = ZamId.objects.get(pk=zid.pk)
        self.assertEqual((zid.status, zid.target), (ZamId.Status.RETIRED, None))
        self.assertIn("Saw", zid.note)

    def test_hard_delete_of_location(self):
        pk = self.location.pk
        self.location.delete()
        Location.objects.get(pk=pk).delete()
        zid = ZamId.objects.get(pk=self.for_location.pk)
        self.assertEqual((zid.status, zid.target), (ZamId.Status.RETIRED, None))
        self.assertIn(f"(#{pk})", zid.note)

    def test_failed_delete_leaves_the_id_alone(self):
        self.location.delete()
        ItemLocation.objects.create(item=self.other_item, location=self.location, amount=1)
        with self.assertRaises(ValidationError):  # not empty
            Location.objects.get(pk=self.location.pk).delete()
        self.assertEqual(ZamId.objects.get(pk=self.for_location.pk).status, ZamId.Status.ASSIGNED)

    def test_quick_items_with_ids_need_the_item_page(self):
        entry = ItemLocation.objects.create(item=self.item, location=self.location, amount=None)
        with self.assertRaises(QuickItemError):
            hard_delete(entry)


class LookupTests(InventoryFixture, TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.create_inventory()
        cls.zid = services.claim(make_id("K7Q4X").code, cls.item, None)

    def test_active_code(self):
        with self.assertNumQueries(1):
            self.assertEqual(lookup.active_code(self.item), "K7Q4XD")
        self.assertIsNone(lookup.active_code(self.other_item))
        self.assertEqual(lookup.active_id(self.item), self.zid)

    def test_annotation_needs_one_query(self):
        with self.assertNumQueries(1):
            codes = dict(lookup.annotate_zam_code(Item.objects.all()).values_list("pk", "zam_code"))
        self.assertEqual(codes, {self.item.pk: "K7Q4XD", self.other_item.pk: None})
        services.retire(self.zid.code, None)
        self.assertIsNone(lookup.active_code(self.item))
