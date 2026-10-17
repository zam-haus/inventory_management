import io
import zipfile

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.test import TestCase, override_settings
from django.urls import reverse

from inventory.label_ids import services
from inventory.models import Item, LabelId

from ..label_ids.testing import SETTINGS, InventoryFixture, make_id


@override_settings(**SETTINGS)
class AdminTests(InventoryFixture, TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.create_inventory()
        cls.admin = get_user_model().objects.create_superuser(username="admin")
        cls.lid = make_id("K7R4X")
        cls.claimed = services.claim(make_id("12345").code, cls.item, None)

    def setUp(self):
        super().setUp()
        self.client.force_login(self.admin)

    def change_url(self, lid):
        return reverse("admin:inventory_labelid_change", args=[lid.code])

    def test_no_add_or_delete(self):
        self.assertEqual(self.client.get(reverse("admin:inventory_labelid_add")).status_code, 403)
        self.assertEqual(self.client.get(reverse("admin:inventory_labelid_delete", args=[self.lid.code])).status_code, 403)
        response = self.client.get(reverse("admin:inventory_labelid_changelist"))
        self.assertContains(response, "K7R-4XD")
        self.assertNotContains(response, 'value="delete_selected"')

    def test_search_normalizes(self):
        response = self.client.get(reverse("admin:inventory_labelid_changelist"), {"q": "k7r-4xd"})
        self.assertContains(response, "K7R-4XD")
        self.assertNotContains(response, "123-45V")

    def test_generate(self):
        response = self.client.post(reverse("admin:inventory_labelid_generate"), {"count": 3, "batch": "roll-7"})
        self.assertEqual(response.status_code, 302)
        self.assertEqual(LabelId.objects.filter(batch="roll-7", status="reserved").count(), 3)
        staff = get_user_model().objects.create_user(username="staff", is_staff=True)
        staff.user_permissions.add(Permission.objects.get(codename="view_labelid"))
        self.client.force_login(staff)
        self.assertEqual(self.client.get(reverse("admin:inventory_labelid_generate")).status_code, 403)

    def test_url_only_on_reserved(self):
        response = self.client.post(self.change_url(self.lid), {"url": "https://wiki.zam.haus/X", "batch": "b", "note": ""})
        self.assertEqual(response.status_code, 302)
        lid = LabelId.objects.get(pk=self.lid.pk)
        self.assertEqual((lid.status, lid.url, lid.batch), ("assigned", "https://wiki.zam.haus/X", "b"))
        self.client.post(self.change_url(self.claimed), {"url": "https://evil.example", "batch": "", "note": "n"})
        claimed = LabelId.objects.get(pk=self.claimed.pk)
        self.assertEqual((claimed.url, claimed.item, claimed.note), (None, self.item, "n"))

    def test_url_needs_permission(self):
        staff = get_user_model().objects.create_user(username="staff", is_staff=True)
        staff.user_permissions.add(*Permission.objects.filter(codename__in=["view_labelid", "change_labelid"]))
        self.client.force_login(staff)
        self.client.post(self.change_url(self.lid), {"url": "https://wiki.zam.haus/X", "batch": "", "note": ""})
        self.assertEqual(LabelId.objects.get(pk=self.lid.pk).status, "reserved")

    def action(self, name, codes, **data):
        return self.client.post(reverse("admin:inventory_labelid_changelist"), {
            "action": name, "_selected_action": codes, "index": 0, **data})

    def test_retire_action(self):
        response = self.action("retire_action", [self.claimed.code])
        self.assertContains(response, "123-45V")  # confirmation page
        self.action("retire_action", [self.claimed.code], apply=1, note="peeled off")
        claimed = LabelId.objects.get(pk=self.claimed.pk)
        self.assertEqual((claimed.status, claimed.note, claimed.retired_by), ("retired", "peeled off", self.admin))

    def test_download_labels_action(self):
        response = self.action("download_labels_action", [self.lid.code], apply=1, printer="E550W", tape=12)
        self.assertEqual(response["Content-Type"], "application/zip")
        names = zipfile.ZipFile(io.BytesIO(response.content)).namelist()
        self.assertEqual(names, ["K7R4XD_E550W_12mm.png"])
        self.assertIsNotNone(LabelId.objects.get(pk=self.lid.pk).printed_at)
        response = self.action("download_labels_action", [self.lid.code], apply=1, printer="E550W", tape=36)
        self.assertContains(response, "does not support")

    def test_admin_hard_delete_of_item_retires_its_id(self):
        url = reverse("admin:inventory_item_delete", args=[self.item.pk])
        self.client.post(url, {"post": "yes"})  # first deletion is soft
        self.assertEqual(LabelId.objects.get(pk=self.claimed.pk).status, "assigned")
        response = self.client.post(url, {"post": "yes"})
        self.assertEqual(response.status_code, 302)
        self.assertFalse(Item.objects.filter(pk=self.item.pk).exists())
        claimed = LabelId.objects.get(pk=self.claimed.pk)
        self.assertEqual((claimed.status, claimed.item, claimed.retired_by), ("retired", None, self.admin))
        self.assertIn(f"“Drill” (#{self.item.pk})", claimed.note)
        response = self.client.get(self.change_url(claimed))
        self.assertContains(response, f"(#{self.item.pk})")

    def test_admin_hard_delete_of_location_records_who(self):
        location = LabelId.objects.get(pk=services.claim(make_id("ABCDE").code, self.location, None).pk)
        url = reverse("admin:inventory_location_delete", args=[self.location.pk])
        self.client.post(url, {"post": "yes"})
        self.client.post(url, {"post": "yes"})
        location.refresh_from_db()
        self.assertEqual((location.status, location.location, location.retired_by), ("retired", None, self.admin))

    def test_admin_bulk_hard_delete_records_who(self):
        changelist = reverse("admin:inventory_item_changelist")
        for _ in range(2):
            self.client.post(changelist + "?is_deleted__exact=all", {
                "action": "delete_selected", "_selected_action": [self.item.pk], "post": "yes"})
        self.assertFalse(Item.objects.filter(pk=self.item.pk).exists())
        self.assertEqual(LabelId.objects.get(pk=self.claimed.pk).retired_by, self.admin)

    def test_change_page_shows_label_and_link(self):
        label = reverse("label_id_label", args=[self.lid.code]) + "?printer=P900&amp;tape=24"
        response = self.client.get(self.change_url(self.lid))
        self.assertContains(response, label)
        self.assertContains(response, f'href="{reverse("label_id_claim", args=[self.lid.code])}"')
        response = self.client.get(self.change_url(self.claimed))
        self.assertContains(response, '<a href="/id/12345V">/id/12345V</a>', html=True)
        self.assertContains(response, f'href="{reverse("admin:inventory_item_change", args=[self.item.pk])}"')
        response = self.client.get(reverse("admin:inventory_labelid_changelist"))
        self.assertContains(response, f'href="{reverse("admin:inventory_item_change", args=[self.item.pk])}"')
        self.assertNotContains(response, reverse("label_id_claim", args=[self.claimed.code]))

    def test_info_label_and_qr(self):
        response = self.client.get(reverse("label_id_info", args=["k7r-4xd"]))
        self.assertContains(response, "K7R-4XD")
        self.assertContains(response, reverse("label_id_label", args=[self.lid.code]) + "?printer=P900&amp;tape=24")
        self.assertNotContains(response, "qr.svg")
        response = self.client.get(reverse("label_id_label", args=[self.lid.code]), {"printer": "P900", "tape": 24})
        self.assertEqual(response["Content-Type"], "image/png")
        self.client.logout()
        self.assertEqual(self.client.get(reverse("label_id_info", args=[self.lid.code])).status_code, 302)
        self.assertEqual(self.client.get(reverse("label_id_label", args=[self.lid.code])).status_code, 302)
        response = self.client.get(reverse("label_id_qr_svg", args=[self.lid.code]))
        self.assertEqual(response["Content-Type"], "image/svg+xml")
        self.assertEqual(self.client.get(reverse("label_id_qr_png", args=["YYYYYJ"])).status_code, 404)
