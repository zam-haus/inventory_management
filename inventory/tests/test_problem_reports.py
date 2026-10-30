import io
import json

from django.contrib.auth import get_user_model
from django.core import mail
from django.core.cache import cache
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.urls import reverse
from PIL import Image


def picture(name="screenshot.jpg"):
    data = io.BytesIO()
    Image.new("RGB", (4, 3), "red").save(data, "JPEG")
    return SimpleUploadedFile(name, data.getvalue(), content_type="image/jpeg")


@override_settings(LANGUAGE_CODE="en", ADMINS=["admin@example.com"], PROBLEM_REPORT_EMAILS=[],
                   PROBLEM_REPORT_LIMIT=3, APP_VERSION="v1.2-3-gabc", EMAIL_SUBJECT_PREFIX="[inv] ")
class ProblemReportTests(TestCase):
    """Reports of technical problems go by mail to the admins, with screenshot and what the browser noticed."""

    @classmethod
    def setUpTestData(cls):
        cls.user = get_user_model().objects.create_user(username="alice")

    def setUp(self):
        cache.clear()

    def report(self, **data):
        fields = {"description": "The save button\ndoes nothing", "url": "http://testserver/loc/7"} | data
        return self.client.post(reverse("problem_report"), fields, HTTP_ACCEPT="application/json")

    def test_every_page_offers_the_dialog(self):
        page = self.client.get(reverse("index")).content.decode()
        self.assertIn("data-problem-report-open", page)
        self.assertIn(f'href="{reverse("problem_report")}?url=/"', page)
        self.assertIn('id="problem-report"', page)
        self.assertIn("modern-screenshot.js", page)
        self.assertIn("problem_report_log.js", page)

    @override_settings(ADMINS=[])
    def test_without_recipients_there_is_nothing_to_report_to(self):
        page = self.client.get(reverse("index")).content.decode()
        self.assertNotIn("data-problem-report-open", page)
        self.assertNotIn('id="problem-report"', page)
        self.assertEqual(self.client.get(reverse("problem_report")).status_code, 404)
        self.assertEqual(self.report().status_code, 404)

    @override_settings(ADMINS=[("Old style", "old@example.com")], PROBLEM_REPORT_EMAILS=["team@example.com"])
    def test_problem_report_emails_go_before_the_admins(self):
        self.report()
        self.assertEqual(mail.outbox[0].to, ["team@example.com"])

    def test_a_report_mails_description_page_user_screenshot_and_browser_details(self):
        self.client.force_login(self.user)
        browser = {"viewport": "390×844", "screenshot": "attached", "log": [
            {"time": "2026-10-30T10:00:00Z", "kind": "error", "page": "/loc/7", "message": "TypeError: x is null",
             "source": "http://testserver/static/a.js:3:9", "stack": "at save (a.js:3:9)\nat click"},
            {"time": "2026-10-30T10:00:01Z", "kind": "request", "page": "/loc/7", "method": "POST",
             "url": "/loc/7/purpose/", "status": 500},
        ]}
        response = self.report(screenshot=picture(), own_picture=picture("phone.jpg"), browser_context=json.dumps(browser))
        self.assertEqual(response.json()["ok"], True)
        message = mail.outbox[0]
        self.assertEqual(message.to, ["admin@example.com"])
        self.assertEqual(message.subject, "[inv] Problem report: The save button does nothing")
        self.assertIn("The save button\ndoes nothing", message.body)
        self.assertIn("Page: http://testserver/loc/7", message.body)
        self.assertIn("Reported by: alice", message.body)
        self.assertIn("Version: v1.2-3-gabc", message.body)
        self.assertIn("viewport: 390×844", message.body)
        self.assertIn("error /loc/7: TypeError: x is null", message.body)
        self.assertIn("    at click", message.body)
        self.assertIn("POST /loc/7/purpose/ → 500", message.body)
        self.assertEqual([attachment.filename for attachment in message.attachments],
                         ["screenshot.jpg", "phone.jpg", "browser.json"])

    def test_guests_report_too_with_contact(self):
        page = self.client.get(reverse("problem_report")).content.decode()
        self.assertIn('name="contact"', page)
        self.report(contact="bob@example.com", browser_context="not json")
        self.assertIn("Reported by: guest (bob@example.com)", mail.outbox[0].body)
        self.assertIn("not json", mail.outbox[0].body)

    def test_users_are_not_asked_for_contact(self):
        self.client.force_login(self.user)
        self.assertNotIn('name="contact"', self.client.get(reverse("problem_report")).content.decode())

    def test_only_pictures_are_attached(self):
        response = self.report(own_picture=SimpleUploadedFile("x.jpg", b"<script>", content_type="image/jpeg"))
        self.assertEqual(response.status_code, 400)
        self.assertIn("own_picture", response.json()["errors"])
        self.assertEqual(mail.outbox, [])

    def test_a_description_is_needed(self):
        self.assertEqual(self.report(description=" ").status_code, 400)
        self.assertEqual(mail.outbox, [])

    def test_bots_filling_the_hidden_field_get_no_mail(self):
        self.assertEqual(self.report(website="http://spam.example").json()["ok"], True)
        self.assertEqual(mail.outbox, [])

    def test_reports_are_limited_per_address(self):
        for _ in range(3):
            self.assertEqual(self.report().status_code, 200)
        response = self.report()
        self.assertEqual(response.status_code, 429)
        self.assertIn("Too many reports", response.json()["error"])
        self.assertEqual(len(mail.outbox), 3)
        # Users count on their own, not with the address they share.
        self.client.force_login(self.user)
        self.assertEqual(self.report().status_code, 200)

    def test_without_javascript_the_page_sends_and_goes_back(self):
        page = self.client.get(reverse("problem_report") + "?url=/loc/7").content.decode()
        self.assertIn('value="http://testserver/loc/7"', page)
        self.assertNotIn("data-problem-report-with-screenshot", page.split('id="problem-report"')[0])
        response = self.client.post(reverse("problem_report"), {"description": "Broken", "url": "http://testserver/loc/7"})
        self.assertRedirects(response, "http://testserver/loc/7", fetch_redirect_response=False)
        self.assertEqual(len(mail.outbox), 1)
        # Never back to another site.
        response = self.client.post(reverse("problem_report"), {"description": "Broken", "url": "https://evil.example/"})
        self.assertRedirects(response, reverse("index"), fetch_redirect_response=False)

    def test_a_failing_mail_server_is_told(self):
        with self.settings(EMAIL_BACKEND="inventory.tests.test_problem_reports.FailingBackend"), \
                self.assertLogs("inventory.problem_reports", "ERROR"):
            response = self.report()
        self.assertEqual(response.status_code, 503)
        self.assertIn("could not be sent", response.json()["error"])


class FailingBackend:
    def __init__(self, *args, **kwargs):
        pass

    def send_messages(self, messages):
        raise OSError("connection refused")
