"""Error pages (inventory/errors.py): 403, 404 and the form check with the navigation; 400, 500 and the resolver hosts'
pages standalone."""
from django.contrib.auth import get_user_model
from django.core.exceptions import PermissionDenied, SuspiciousOperation
from django.test import Client, RequestFactory, TestCase, override_settings
from django.urls import path, reverse

from imzam import urls as root

from .. import errors


def denied(request):
    raise PermissionDenied


def denied_with_reason(request):
    raise PermissionDenied("This location cannot contain sub-locations.")


def suspicious(request):
    raise SuspiciousOperation("odd request")


def broken(request):
    raise RuntimeError("boom")


urlpatterns = [
    path("denied/", denied),
    path("denied/reason/", denied_with_reason),
    path("suspicious/", suspicious),
    path("broken/", broken),
    *root.urlpatterns,
]
handler400, handler403, handler404, handler500 = root.handler400, root.handler403, root.handler404, root.handler500


@override_settings(LANGUAGE_CODE="en", ROOT_URLCONF=__name__, ADMINS=[], PROBLEM_REPORT_EMAILS=[])
class ErrorPageTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = get_user_model().objects.create_user(username="alice")

    def test_not_found_offers_the_search(self):
        response = self.client.get("/location/nowhere/x")
        self.assertContains(response, "<title>Page not found</title>", status_code=404, html=False)
        self.assertContains(response, "Error 404", status_code=404)
        self.assertContains(response, f'action="{reverse("index")}" role="search"', status_code=404)
        self.assertContains(response, 'id="navbar-search"', status_code=404)  # the inventory's navigation

    def test_no_access_asks_guests_to_log_in(self):
        response = self.client.get("/denied/")
        self.assertContains(response, "No access", status_code=403)
        self.assertContains(response, "Log in to open this page.", status_code=403)
        self.assertContains(response, "?next=/denied/", status_code=403)
        self.client.force_login(self.user)
        response = self.client.get("/denied/")
        self.assertContains(response, "Ask an inventory admin for the permission.", status_code=403)
        self.assertNotContains(response, "Log in to open this page.", status_code=403)

    def test_no_access_names_the_reason(self):
        response = self.client.get("/denied/reason/")
        self.assertContains(response, "This location cannot contain sub-locations.", status_code=403)
        self.assertNotContains(response, "Log in to open this page.", status_code=403)

    def test_an_expired_form_leads_back(self):
        client = Client(enforce_csrf_checks=True)
        response = client.post(reverse("problem_report"), {})
        self.assertContains(response, "Form expired", status_code=403)
        self.assertContains(response, "Allow cookies for this site.", status_code=403)
        self.assertNotContains(response, "Back to the form", status_code=403)
        client.cookies["csrftoken"] = "x" * 32
        response = client.post(reverse("problem_report"), {}, headers={"referer": "http://testserver/problem/?url=/"})
        self.assertContains(response, 'href="http://testserver/problem/?url=/"', status_code=403)
        self.assertNotContains(response, "Allow cookies for this site.", status_code=403)
        response = client.post(reverse("problem_report"), {}, headers={"referer": "https://elsewhere.example/"})
        self.assertNotContains(response, "Back to the form", status_code=403)

    @override_settings(ADMINS=["admin@example.com"])
    def test_server_error_stands_alone(self):
        client = Client(raise_request_exception=False)
        with self.assertLogs("django.request", "ERROR"):
            response = client.get("/broken/?x=1")
        self.assertContains(response, "Something went wrong", status_code=500)
        self.assertContains(response, "The inventory admins have been notified.", status_code=500)
        self.assertContains(response, "<svg", status_code=500)  # the logo inline
        self.assertNotContains(response, 'id="navbar-search"', status_code=500)
        self.assertContains(response, f'href="{reverse("problem_report")}?url=%2Fbroken%2F%3Fx%3D1"', status_code=500)

    def test_server_error_needs_no_database(self):
        with self.assertNumQueries(0):
            response = errors.server_error(RequestFactory().get("/broken/"))
        self.assertEqual(response.status_code, 500)
        self.assertNotIn("have been notified", response.content.decode())  # no ADMINS
        self.assertNotIn("Report a problem", response.content.decode())

    def test_bad_request(self):
        with self.assertLogs("django.security", "ERROR"):
            response = self.client.get("/suspicious/")
        self.assertContains(response, "Bad request", status_code=400)
        self.assertContains(response, 'href="/"', status_code=400)

    def test_resolver_hosts_stand_alone(self):
        response = self.client.get("/%2Fx", headers={"host": "i.zam.haus"})
        self.assertContains(response, "Page not found", status_code=404)
        self.assertNotContains(response, 'id="navbar-search"', status_code=404)
