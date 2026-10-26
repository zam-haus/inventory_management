import json
from datetime import timedelta

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone, translation

from ..cleanup import export, proposals
from ..models import (BarcodeType, Category, ChangeLog, CleanupImport, Item, ItemBarcode, ItemFile, ItemImage,
                      MeasurementUnit)
from .test_documents_and_photos import MediaMixin, png


def proposal_file(categories=(), items=(), exported_at=None):
    return {"kind": proposals.KIND, "version": 1, "exported_at": exported_at or timezone.now().isoformat(),
            "categories": list(categories), "items": list(items)}


class CleanupTests(MediaMixin, TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.admin = get_user_model().objects.create_superuser("chief", password="x")
        unit, _ = MeasurementUnit.objects.get_or_create(pk=1, defaults={"name": "Piece", "short": "pc"})
        cls.tools = Category.objects.create(name="Testwerkzeug", keywords="Werkzeug")
        cls.hand = Category.objects.create(name="Hand", parent_category=cls.tools)
        cls.glue = Category.objects.create(name="Testkleber", keywords="Leim, Kleber")
        cls.paste = Category.objects.create(name="Testpaste", keywords="kleber, Paste")
        cls.pliers = Item.objects.create(name="Zange", category=cls.hand, measurement_unit=unit)
        cls.saw = Item.objects.create(name="Säge", category=cls.tools, measurement_unit=unit, description="alt")
        cls.wood_glue = Item.objects.create(name="Holzleim", category=cls.glue, measurement_unit=unit)
        cls.super_glue = Item.objects.create(name="Sekundenkleber", category=cls.glue, measurement_unit=unit)
        cls.gone = Item.objects.create(name="Weg", category=cls.glue, measurement_unit=unit)
        cls.gone.delete()

    def setUp(self):
        super().setUp()  # photos and files in a temporary folder
        self.client.force_login(self.admin)
        self.enterContext(translation.override("en"))

    def make(self, categories=(), items=(), decisions=None, **kwargs):
        data = proposals.load(json.dumps(proposal_file(categories, items, **kwargs)).encode())
        return CleanupImport.objects.create(proposals=data, exported_at=proposals.exported_at(data),
                                            decisions=decisions or {}, file_name="p.json")

    # Export

    def test_export_holds_the_tree_and_the_items_texts(self):
        barcode = ItemBarcode.objects.create(item=self.saw, data="4006381333931",
                                             type=BarcodeType.objects.create(name="EAN"))
        image = ItemImage.objects.create(item=self.saw, image=png(), description="Packung", ocr_text="  BAHCO 300 mm ")
        bare = ItemImage.objects.create(item=self.saw, image=png("blue"))
        manual = ItemFile.objects.create(item=self.saw, file=SimpleUploadedFile("a.pdf", b"%PDF"),
                                         description="Anleitung")
        ItemFile.objects.create(item=self.saw, file=SimpleUploadedFile("b.pdf", b"%PDF"), description="Rechnung",
                                internal=True)
        self.assertEqual(export.check_fields(), [])
        data = export.build()
        self.assertEqual(data["kind"], export.KIND)
        self.assertIn('"op": "split"', data["format"])  # the proposals format, with examples
        hand = next(category for category in data["categories"] if category["id"] == self.hand.pk)
        self.assertEqual(hand, {"id": self.hand.pk, "name": "Hand", "path": "Testwerkzeug/Hand",
                                "parent": self.tools.pk, "description": "", "keywords": "", "naming": "", "items": 1})
        saw = next(item for item in data["items"] if item["id"] == self.saw.pk)
        self.assertEqual(saw["barcodes"], [{"id": barcode.pk, "data": "4006381333931", "type": "EAN"}])
        # Ids, so that a proposal can name its source; photos without text too (their picture can be the source).
        self.assertEqual(saw["photos"], [{"id": image.pk, "description": "Packung", "text": "BAHCO 300 mm"},
                                         {"id": bare.pk, "description": "", "text": ""}])
        self.assertEqual(saw["files"], [{"id": manual.pk, "description": "Anleitung"}])  # not the internal invoice
        self.assertIn('"source": "photo:', data["format"])
        self.assertEqual((saw["category"], saw["category_path"], saw["kind"]), (self.tools.pk, "Testwerkzeug", "bulk"))
        self.assertNotIn(self.gone.pk, [item["id"] for item in data["items"]])

    def test_export_needs_permission(self):
        url = reverse("admin:inventory_cleanupimport_export")
        response = self.client.get(url)
        self.assertEqual(response["Content-Type"], "application/json; charset=utf-8")
        self.assertIn("attachment;", response["Content-Disposition"])
        staff = get_user_model().objects.create_user("staff", is_staff=True)
        staff.user_permissions.add(Permission.objects.get(codename="view_cleanupimport"))
        self.client.force_login(staff)
        self.assertEqual(self.client.get(url).status_code, 403)

    # Reading the file

    def test_files_that_hold_no_proposals(self):
        for data, message in ((b"{", "not JSON"), (b'{"kind": "x"}', "no cleanup proposals"),
                              (json.dumps({**proposal_file(), "version": 2}).encode(), "version 1"),
                              (json.dumps({**proposal_file(), "items": {}}).encode(), "must be a list")):
            with self.subTest(message), self.assertRaisesMessage(proposals.Invalid, message):
                proposals.load(data)

    # Planning and applying

    def test_operations_in_their_order_then_items(self):
        cleanup = self.make(categories=[
            {"op": "create", "ref": "neu", "name": "Kleben", "parent": None, "keywords": "Kleber", "reason": "Ordnung"},
            {"op": "move", "id": self.glue.pk, "parent": "neu"},
            {"op": "join", "ids": [self.paste.pk], "into": self.glue.pk, "reason": "doppelt"},
            {"op": "update", "id": self.hand.pk, "name": "Handwerkzeug", "description": "Ohne Strom"},
        ], items=[
            {"id": self.saw.pk, "name": "Säge, Fuchsschwanz", "category": self.hand.pk, "reason": "einheitlich"},
            {"id": self.pliers.pk, "category": "neu"},
        ])
        plan = proposals.plan(cleanup, self.admin)
        self.assertEqual([change.problem for change in plan.categories + plan.items], [""] * 7)
        self.assertEqual(plan.categories[1].text, "Move “Testkleber” into “Kleben”")  # names as they are by then
        self.assertEqual(plan.categories[2].details, ["Nothing in it moves."])
        self.assertEqual(plan.items[1].after, "Testwerkzeug/Handwerkzeug")
        proposals.apply(cleanup, self.admin)

        self.glue.refresh_from_db()
        self.assertEqual(self.glue.full_name, "Kleben/Testkleber")
        self.assertEqual(self.glue.keywords, "Leim, Kleber, Paste")  # joined, each word once
        self.assertFalse(Category.objects.filter(pk=self.paste.pk).exists())
        self.assertEqual(Category.objects.get(pk=self.hand.pk).full_name, "Testwerkzeug/Handwerkzeug")
        self.saw.refresh_from_db()
        self.assertEqual((self.saw.name, self.saw.category), ("Säge, Fuchsschwanz", self.hand))
        self.assertEqual(Item.objects.get(pk=self.pliers.pk).category.name, "Kleben")
        entry = ChangeLog.objects.filter(item=self.saw).latest("created_at")
        self.assertEqual((entry.source, entry.actor, entry.note), (ChangeLog.Source.CLEANUP, self.admin, "einheitlich"))
        self.assertEqual({change["field"] for change in entry.changes}, {"name", "category"})
        cleanup.refresh_from_db()
        self.assertIsNotNone(cleanup.applied_at)
        self.assertEqual(len(cleanup.result["applied"]), 7)
        # Again: everything is applied already, nothing happens.
        plan = proposals.plan(cleanup)
        self.assertEqual([change.status for change in plan.categories + plan.items], ["unchanged"] * 7)
        entries = ChangeLog.objects.count()
        proposals.apply(cleanup, self.admin)
        self.assertEqual(ChangeLog.objects.count(), entries)

    def test_a_declined_creation_skips_what_needs_it(self):
        cleanup = self.make(categories=[
            {"op": "create", "ref": "neu", "name": "Kleben", "parent": None},
            {"op": "move", "id": self.glue.pk, "parent": "neu"},
        ], items=[{"id": self.pliers.pk, "category": "neu"}], decisions={"c0": "declined"})
        plan = proposals.plan(cleanup)
        self.assertEqual(plan.categories[0].status, "declined")
        self.assertEqual(plan.categories[1].problem, "Its creation was declined.")
        self.assertEqual(plan.items[0].problem, "Its creation was declined.")
        proposals.apply(cleanup, self.admin)
        self.assertFalse(Category.objects.filter(name="Kleben").exists())
        self.assertEqual(Item.objects.get(pk=self.pliers.pk).category, self.hand)
        cleanup.refresh_from_db()
        self.assertEqual(cleanup.result, {"applied": [], "last": [], "skipped": {
            "c1": "Its creation was declined.", f"i{self.pliers.pk}.category": "Its creation was declined."}})
        # Deferred instead: decided later, then applied.
        cleanup.decisions = {"c0": "deferred"}
        cleanup.save()
        self.assertEqual(proposals.plan(cleanup).items[0].problem, "Its creation is deferred.")
        cleanup.decisions = {}
        cleanup.save()
        proposals.apply(cleanup, self.admin)
        self.assertEqual(Item.objects.get(pk=self.pliers.pk).category.name, "Kleben")

    def test_split(self):
        part = {"ref": "holz", "name": "Holzleim", "items": [self.wood_glue.pk], "categories": []}
        other = {"ref": "sek", "name": "Sekundenkleber", "items": [self.super_glue.pk]}
        incomplete = self.make(categories=[{"op": "split", "id": self.glue.pk, "parts": [part]}])
        self.assertEqual(proposals.plan(incomplete).categories[0].problem,
                         "“Testkleber” is deleted, but these are in no part: 1 item. List them, or set “keep”: true.")
        kept = self.make(categories=[{"op": "split", "id": self.glue.pk, "parts": [{**part, "parent": self.glue.pk}],
                                      "keep": True}])
        self.assertEqual(proposals.plan(kept).categories[0].problem, "")
        cleanup = self.make(categories=[{"op": "split", "id": self.glue.pk, "parts": [part, other]}],
                            items=[{"id": self.super_glue.pk, "name": "Sekundenkleber 20 g"}])
        change = proposals.plan(cleanup).categories[0]
        self.assertEqual(change.text, "Split “Testkleber” into “Holzleim”, “Sekundenkleber”")
        self.assertEqual(change.details, ["Holzleim (top level): Holzleim",
                                          "Sekundenkleber (top level): Sekundenkleber"])
        proposals.apply(cleanup, self.admin)
        self.assertFalse(Category.objects.filter(pk=self.glue.pk).exists())
        self.assertEqual(Item.objects.get(pk=self.wood_glue.pk).category.name, "Holzleim")
        glue = Item.objects.get(pk=self.super_glue.pk)
        self.assertEqual((glue.name, glue.category.name), ("Sekundenkleber 20 g", "Sekundenkleber"))
        self.assertIsNone(Item.objects.get(pk=self.gone.pk).category)  # deleted items lose it

    def test_delete(self):
        cleanup = self.make(categories=[{"op": "delete", "id": self.tools.pk}])
        change = proposals.plan(cleanup).categories[0]
        self.assertEqual(change.details, ["1 item → no category", "1 subcategory → top level"])
        proposals.apply(cleanup, self.admin)
        self.assertIsNone(Item.objects.get(pk=self.saw.pk).category)
        self.assertEqual(Category.objects.get(pk=self.hand.pk).full_name, "Hand")
        cleanup = self.make(categories=[{"op": "delete", "id": self.paste.pk, "items_to": self.glue.pk}])
        self.assertEqual(proposals.plan(cleanup).categories[0].problem, "")

    def test_what_cannot_be_carried_out(self):
        cases = [
            ({"op": "move", "id": self.tools.pk, "parent": self.hand.pk}, "cannot move into itself"),
            ({"op": "create", "ref": "x", "name": "A/B"}, "must not contain “/”"),
            ({"op": "create", "name": "Ohne ref"}, "needs a “ref”"),
            ({"op": "join", "ids": [self.tools.pk], "into": self.hand.pk}, "which would be deleted"),
            ({"op": "move", "id": 999999, "parent": None}, "There is no category 999999"),
            ({"op": "rename", "id": self.hand.pk}, "Unknown operation"),
        ]
        cleanup = self.make(categories=[case for case, _message in cases])
        for change, (_case, message) in zip(proposals.plan(cleanup).categories, cases):
            with self.subTest(message):
                self.assertIn(message, change.problem)

    def test_item_proposals(self):
        cleanup = self.make(items=[
            {"id": self.saw.pk, "name": "Säge", "description": "neu"},  # the name as it is
            {"id": self.pliers.pk, "name": " "},
            {"id": self.gone.pk, "name": "Wieder da"},
            {"id": self.saw.pk, "name": "Doppelt"},
            {"name": "Ohne id"},
        ])
        plan = proposals.plan(cleanup)
        self.assertEqual([(change.key, change.status) for change in plan.items], [
            (f"i{self.saw.pk}.name", "unchanged"), (f"i{self.saw.pk}.description", "ok"),
            (f"i{self.pliers.pk}.name", "problem")])
        self.assertEqual(plan.items[1].diff, ("<del>alt</del>", "<ins>neu</ins>"))
        self.assertEqual(plan.errors, [f"Item {self.saw.pk} is proposed twice; only the first proposal counts.",
                                       "Item proposal 5 has no id.", f"There is no item {self.gone.pk} (any more)."])

    def test_permissions_per_change(self):
        editor = get_user_model().objects.create_user("editor", is_staff=True)
        editor.user_permissions.add(*Permission.objects.filter(codename__in=["change_category", "add_category"]))
        cleanup = self.make(categories=[{"op": "delete", "id": self.paste.pk},
                                        {"op": "update", "id": self.paste.pk, "name": "Pasten"}],
                            items=[{"id": self.saw.pk, "name": "Bügelsäge"}])
        plan = proposals.plan(cleanup, editor)
        self.assertEqual([change.problem for change in plan.categories + plan.items],
                         ["You lack the permission for this.", "", "You lack the permission for this."])

    # The admin pages

    def upload(self, data):
        return self.client.post(reverse("admin:inventory_cleanupimport_add"), {
            "file": SimpleUploadedFile("vorschlag.json", json.dumps(data).encode(), "application/json")})

    def test_upload_declines_items_changed_since_the_export(self):
        exported = (timezone.now() - timedelta(hours=1)).isoformat()
        self.saw.name = "Neue Säge"
        self.saw.save()
        response = self.upload(proposal_file(items=[{"id": self.saw.pk, "name": "Säge, alt", "description": "x"}],
                                             exported_at=exported))
        cleanup = CleanupImport.objects.get()
        self.assertRedirects(response, reverse("admin:inventory_cleanupimport_change", args=[cleanup.pk]))
        self.assertEqual((cleanup.created_by, cleanup.file_name), (self.admin, "vorschlag.json"))
        self.assertEqual(cleanup.decisions, {f"i{self.saw.pk}.name": "deferred"})  # to be looked at
        page = self.client.get(response.url).content.decode()
        self.assertIn("Seit dem Export geändert", page)  # the admin speaks German
        response = self.upload({"kind": "x"})
        self.assertContains(response, "enthält keine Aufräum-Vorschläge")

    def test_review_decisions_and_apply(self):
        cleanup = self.make(categories=[{"op": "update", "id": self.paste.pk, "name": "Pasten", "reason": "Plural"}],
                            items=[{"id": self.saw.pk, "name": "Bügelsäge", "description": "neu"}])
        url = reverse("admin:inventory_cleanupimport_change", args=[cleanup.pk])
        content = self.client.get(url).content.decode()
        self.assertIn("„Testpaste“ ändern", content)  # the admin speaks German
        self.assertIn("Name: Testpaste → Pasten", content)
        self.assertIn("<ins>Bügelsäge</ins>", content)
        self.assertIn('<th scope="col">Entscheidung</th>', content)  # yes, later, no; not a state text
        self.assertNotIn("Angenommen", content)
        name, description = f"i{self.saw.pk}.name", f"i{self.saw.pk}.description"
        self.assertIn(f'name="decide:{name}" value="accept" id="accept-{name}" checked', content)
        shown = f"c0 {name} {description}"
        # Without the script: one field each.
        self.client.post(url, {"shown": shown, "decide:c0": "accept", f"decide:{name}": "deferred",
                               f"decide:{description}": "declined"})
        cleanup.refresh_from_db()
        self.assertEqual(cleanup.decisions, {name: "deferred", description: "declined"})
        # For all filtered changes (all pages): here the descriptions.
        self.client.post(f"{url}?field=description", {"action": "accept_all:items"})
        cleanup.refresh_from_db()
        self.assertEqual(cleanup.decisions, {name: "deferred"})
        self.client.post(url, {"action": "defer_all:categories"})
        cleanup.refresh_from_db()
        self.assertEqual(cleanup.decisions, {name: "deferred", "c0": "deferred"})
        # Applying saves the page's decisions first (with the script: one JSON field).
        response = self.client.post(url, {"action": "apply", "shown": shown,
                                          "decisions": json.dumps({description: "deferred"})})
        self.assertRedirects(response, url)
        self.saw.refresh_from_db()
        self.assertEqual((self.saw.name, self.saw.description), ("Bügelsäge", "alt"))
        self.assertEqual(Category.objects.get(pk=self.paste.pk).name, "Pasten")
        content = self.client.get(url).content.decode()
        self.assertIn("2 Änderungen wurden übernommen.", content)
        self.assertIn("Bereits angewendet", content)  # the category change
        # The deferred description, accepted later, is applied then.
        self.client.post(url, {"action": "apply", "shown": shown, "decisions": "{}"})
        self.saw.refresh_from_db()
        self.assertEqual(self.saw.description, "neu")
        # What was applied and changed since is not applied again.
        self.saw.name = "Säge von Hand"
        self.saw.save()
        with translation.override("en"):
            change = proposals.plan(CleanupImport.objects.get(pk=cleanup.pk)).items[0]
        self.assertEqual(change.problem, "Applied before and changed since; it is not applied again.")

    def test_already_applied_category_operations(self):
        Category.objects.create(name="Kleben")
        cleanup = self.make(categories=[
            {"op": "update", "id": self.hand.pk, "name": "Hand"},
            {"op": "move", "id": self.hand.pk, "parent": self.tools.pk},
            {"op": "create", "ref": "neu", "name": "kleben", "parent": None},  # there already (ignoring case)
            {"op": "delete", "id": 999999},
            {"op": "join", "ids": [999998], "into": self.glue.pk},
        ], items=[{"id": self.pliers.pk, "category": "neu"}])
        plan = proposals.plan(cleanup, self.admin)
        self.assertEqual([change.status for change in plan.categories], ["unchanged"] * 5)
        self.assertEqual(plan.items[0].after, "Kleben")  # the ref names the existing category
        proposals.apply(cleanup, self.admin)
        self.assertEqual(Category.objects.filter(name__iexact="kleben").count(), 1)
        self.assertEqual(Item.objects.get(pk=self.pliers.pk).category.name, "Kleben")
        page = self.client.get(reverse("admin:inventory_cleanupimport_change", args=[cleanup.pk])).content.decode()
        self.assertIn('<span class="cleanup-done" title="Bereits angewendet">', page)
        self.assertNotIn("Nicht ausführbar", page)

    def test_confidence_range_and_bulk_decisions(self):
        cleanup = self.make(categories=[{"op": "update", "id": self.paste.pk, "name": "Pasten", "confidence": 0.9}],
                            items=[{"id": self.saw.pk, "name": "Bügelsäge", "confidence": 0.95},
                                   {"id": self.pliers.pk, "name": "Kombizange", "confidence": 0.3},
                                   {"id": self.wood_glue.pk, "name": "Holzleim D3"}])  # without confidence
        url = reverse("admin:inventory_cleanupimport_change", args=[cleanup.pk])
        response = self.client.get(url, {"min": 80})
        self.assertEqual([row.item for row in response.context["rows"]], [self.saw])
        self.assertEqual([change.key for change in response.context["categories"]], ["c0"])
        self.assertContains(response, 'name="min" min="0" max="100" step="5" value="80"')
        self.assertEqual([row.item for row in self.client.get(url, {"max": 50}).context["rows"]], [self.pliers])
        self.assertEqual(len(self.client.get(url).context["rows"]), 3)  # the whole range: also those without
        # The bulk decisions cover the filtered changes only.
        self.client.post(f"{url}?max=50", {"action": "decline_all:items"})
        self.client.post(f"{url}?min=80", {"action": "defer_all:items"})
        cleanup.refresh_from_db()
        self.assertEqual(cleanup.decisions, {f"i{self.pliers.pk}.name": "declined", f"i{self.saw.pk}.name": "deferred"})

    # Sources and photos on the review page

    def test_sources(self):
        for value, expected in (("photo:12", ("photo", 12)), ("convention", ("convention", None)), (None, None)):
            self.assertEqual(proposals.source_of({"source": value}), expected)
        for value in ("photo", "photo:x", "image:3", 5):
            with self.subTest(value), self.assertRaisesMessage(proposals.Invalid, "Unknown source"):
                proposals.source_of({"source": value})

    def test_photos_and_the_source_on_the_review_page(self):
        box = ItemImage.objects.create(item=self.saw, image=png(), description="Packung", ocr_text="BAHCO 300 mm")
        other = ItemImage.objects.create(item=self.saw, image=png("blue"), is_primary=True)
        foreign = ItemImage.objects.create(item=self.pliers, image=png())
        cleanup = self.make(items=[
            {"id": self.saw.pk, "name": "Bügelsäge 300 mm", "reason": "Länge von der Packung", "source": f"photo:{box.pk}"},
            {"id": self.pliers.pk, "name": "Kombizange", "source": f"photo:{box.pk}"},  # not its photo
            {"id": self.wood_glue.pk, "name": "Holzleim D3"},  # no source
            {"id": self.super_glue.pk, "name": "Sekundenkleber Gel", "source": "name"},
        ])
        url = reverse("admin:inventory_cleanupimport_change", args=[cleanup.pk])
        page = self.client.get(url).content.decode()
        saw = page[page.index(f"#{self.saw.pk}</span>"):page.index(f"#{self.pliers.pk}</span>")]
        thumbnail = reverse("admin:inventory_cleanupimport_photo", args=[box.pk])
        # All its photos (the primary one first), the source marked, with what it says.
        self.assertLess(saw.index(reverse("admin:inventory_cleanupimport_photo", args=[other.pk])), saw.index(thumbnail))
        self.assertIn(f'class="cleanup-source-photo" title="Packung"><img src="{thumbnail}"', saw)
        self.assertIn('loading="lazy"', saw)
        self.assertIn("Quelle: Foto 2 von 2", saw)  # the admin speaks German
        self.assertIn('<div class="cleanup-evidence">Packung\n\nBAHCO 300 mm</div>', saw)
        self.assertIn(f"Die Sache hat kein Foto {box.pk}.", page)
        self.assertIn("Keine Quelle angegeben.", page)
        self.assertIn('Quelle: ihr Name</span>\n                            <div class="cleanup-evidence">Sekundenkleber</div>',
                      page)
        self.assertNotIn(reverse("admin:inventory_cleanupimport_photo", args=[foreign.pk]), saw)
        # The thumbnail, made when asked for.
        response = self.client.get(thumbnail)
        self.assertEqual(response.status_code, 302)
        self.assertTrue(response["Location"].endswith(".png") or response["Location"].endswith(".jpg"))
        self.assertIn("max-age=86400", response["Cache-Control"])

    def test_all_changes_on_one_page(self):
        unit = MeasurementUnit.objects.get(pk=1)
        many = Item.objects.bulk_create([Item(name=f"Schraube {n}", measurement_unit=unit) for n in range(60)])
        cleanup = self.make(items=[{"id": item.pk, "name": f"{item.name} verzinkt", "source": "convention"}
                                   for item in many])
        url = reverse("admin:inventory_cleanupimport_change", args=[cleanup.pk])
        self.assertEqual(len(self.client.get(url).context["rows"]), 50)
        everything = self.client.get(url, {"page": "all"})
        self.assertEqual(len(everything.context["rows"]), 60)
        shown = everything.context["shown_keys"]
        self.assertEqual(len(shown.split()), 60)
        # The script sends the decisions as one field: one declined among 60.
        declined = f"i{many[7].pk}.name"
        response = self.client.post(f"{url}?page=all", {"shown": shown, "decisions": json.dumps({declined: "declined"})})
        self.assertRedirects(response, f"{url}?page=all")
        cleanup.refresh_from_db()
        self.assertEqual(cleanup.decisions, {declined: "declined"})

    # Confidence, types, naming, accepting with changes

    def test_confidence_and_types(self):
        cleanup = self.make(categories=[{"op": "update", "id": self.paste.pk, "name": "Pasten", "confidence": 0.4,
                                         "type": "typo"}],
                            items=[{"id": self.saw.pk, "name": "Bügelsäge", "confidence": 0.9, "type": ["naming", "x"]},
                                   {"id": self.pliers.pk, "name": "Kombizange", "confidence": 7},
                                   {"id": self.wood_glue.pk, "name": "Holzleim D3", "confidence": 0.2, "type": "typo"}])
        plan = proposals.plan(cleanup)
        self.assertEqual((plan.categories[0].confidence, plan.categories[0].types), (0.4, ["typo"]))
        saw, pliers, glue = plan.items
        self.assertEqual((saw.confidence, saw.types), (0.9, ["naming"]))
        self.assertEqual(saw.notes, ['Unknown type ["x"]; one of: typo, naming, description, category, structure, other.'])
        self.assertEqual(pliers.notes, ["The confidence must be a number from 0 to 1, not 7."])
        self.assertEqual(saw.problem, "")  # notes do not hinder it
        url = reverse("admin:inventory_cleanupimport_change", args=[cleanup.pk])
        rows = self.client.get(url, {"sort": "confidence"}).context["rows"]
        self.assertEqual([row.item for row in rows], [self.wood_glue, self.saw, self.pliers])  # without one: last
        rows = self.client.get(url, {"sort": "-confidence"}).context["rows"]
        self.assertEqual([row.item for row in rows], [self.saw, self.wood_glue, self.pliers])
        rows = self.client.get(url, {"sort": "type"}).context["rows"]
        self.assertEqual([row.item for row in rows], [self.wood_glue, self.saw, self.pliers])
        self.assertEqual([row.item for row in self.client.get(url, {"type": "typo"}).context["rows"]], [self.wood_glue])
        page = self.client.get(url, {"sort": "confidence", "page": "all"}).content.decode()
        self.assertIn('class="cleanup-badge is-uncertain" title="Wie sicher der Vorschlag ist">Konfidenz 20 %</span>', page)
        self.assertIn('href="?sort=-confidence&amp;page=all"', page)  # links keep "all on one page"

    def test_naming_of_categories(self):
        self.glue.naming = "Kleber <Art>: Kleber Holz"
        self.glue.save()
        self.assertEqual(next(category["naming"] for category in export.build()["categories"]
                              if category["id"] == self.glue.pk), "Kleber <Art>: Kleber Holz")
        cleanup = self.make(categories=[
            {"op": "update", "id": self.glue.pk, "naming": "Klebstoff <Art>, <Menge>: Holzleim, 750 g"},
            {"op": "create", "ref": "neu", "name": "Bänder", "parent": None, "naming": "<Art>band <Breite> mm"}])
        plan = proposals.plan(cleanup)
        self.assertEqual(plan.categories[0].details, ["Naming: Kleber <Art>: Kleber Holz → Klebstoff <Art>, <Menge>: "
                                                      "Holzleim, 750 g"])
        self.assertEqual(plan.categories[1].details, ["Naming: <Art>band <Breite> mm"])
        proposals.apply(cleanup, self.admin)
        self.assertEqual(Category.objects.get(pk=self.glue.pk).naming, "Klebstoff <Art>, <Menge>: Holzleim, 750 g")
        self.assertEqual(Category.objects.get(name="Bänder").naming, "<Art>band <Breite> mm")
        self.assertContains(self.client.get(self.glue.get_absolute_url()), "Klebstoff &lt;Art&gt;, &lt;Menge&gt;")

    def test_accept_with_changes(self):
        cleanup = self.make(items=[{"id": self.saw.pk, "name": "Bügelsäge", "description": "neu", "category": None},
                                   {"id": self.pliers.pk, "name": "Kombizange"}])
        url = reverse("admin:inventory_cleanupimport_change", args=[cleanup.pk])
        page = self.client.get(url).content.decode()
        name, description, category = (f"i{self.saw.pk}.{field}" for field in ("name", "description", "category"))
        self.assertIn(f'name="modify:{name}" value="Bügelsäge"', page)
        self.assertNotIn(f'name="modify:{category}"', page)  # not for categories
        shown = f"{name} {description} {category} i{self.pliers.pk}.name"
        # Without the script: each field; the proposed value as it is changes nothing.
        self.client.post(url, {"shown": shown, f"modify:{name}": " Bügelsäge 300 mm ",
                               f"modify:{description}": "neu", f"modify:i{self.pliers.pk}.name": "Kombizange"})
        cleanup.refresh_from_db()
        self.assertEqual(cleanup.modified, {name: "Bügelsäge 300 mm"})
        plan = proposals.plan(cleanup)
        self.assertEqual((plan.items[0].after, plan.items[0].proposed, plan.items[0].modified),
                         ("Bügelsäge 300 mm", "Bügelsäge", True))
        self.assertContains(self.client.get(url, {"show": "modified"}), "Mit Änderungen angenommen; vorgeschlagen war: Bügelsäge")
        # With the script: the changed ones as JSON; one left out goes back to the proposal.
        self.client.post(url, {"shown": shown, "decisions": "{}", "modified": json.dumps({description: "Neu, 300 mm"})})
        cleanup.refresh_from_db()
        self.assertEqual(cleanup.modified, {description: "Neu, 300 mm"})
        self.client.post(url, {"shown": shown, "decisions": "{}", "modified": json.dumps({name: "  "})})
        with translation.override("en"):  # the request before switched to German
            self.assertEqual(proposals.plan(CleanupImport.objects.get(pk=cleanup.pk)).items[0].problem,
                             "A name must be a text that is not empty.")
        self.client.post(url, {"shown": shown, "decisions": "{}", "modified": json.dumps({name: "Säge, Bügel-"}),
                               "action": "apply"})
        self.saw.refresh_from_db()
        self.assertEqual((self.saw.name, self.saw.description, self.saw.category), ("Säge, Bügel-", "neu", None))
