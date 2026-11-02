from unittest.mock import patch

from django.contrib.auth import BACKEND_SESSION_KEY, get_user_model
from django.contrib.sessions.backends.db import SessionStore
from django.http import HttpResponse
from django.test import RequestFactory, TestCase, override_settings
from django.urls import reverse

from accounts.auth import NavigationSessionRefresh


class DjangoLoginTests(TestCase):
    @override_settings(OIDC_ENABLED=False, LOGIN_URL="login")
    def test_without_oidc_the_login_is_djangos_own(self):
        page = self.client.get("/")
        self.assertContains(page, f'href="{reverse("login")}?next=/"')
        self.assertNotContains(page, reverse("oidc_authentication_init"))
        form = self.client.get(reverse("login"), {"next": "/item/"})
        self.assertContains(form, 'name="password"')
        self.assertNotContains(form, "ZAM SSO")
        get_user_model().objects.create_user(username="ada", password="correct horse")
        response = self.client.post(reverse("login"), {"username": "ada", "password": "correct horse", "next": "/item/"})
        self.assertRedirects(response, "/item/", fetch_redirect_response=False)
        self.assertContains(self.client.get("/"), f'action="{reverse("logout")}"')

    @override_settings(OIDC_ENABLED=True)
    def test_with_oidc_links_go_to_the_sso(self):
        self.assertContains(self.client.get("/"), f'href="{reverse("oidc_authentication_init")}?next=/"')
        self.assertContains(self.client.get(reverse("admin:login")), "Login via ZAM SSO")
        self.assertContains(self.client.get(reverse("login")), "Login via ZAM SSO")
        self.client.force_login(get_user_model().objects.create_user(username="ada"))
        self.assertContains(self.client.get("/"), f'action="{reverse("oidc_logout")}"')

    @override_settings(OIDC_ENABLED=False)
    def test_admin_login_has_no_sso_link_without_oidc(self):
        self.assertNotContains(self.client.get(reverse("admin:login")), "ZAM SSO")


@override_settings(OIDC_ENABLED=True)
class OidcRefreshTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(username="ada")
        self.middleware = NavigationSessionRefresh(lambda request: HttpResponse())

    def visit(self, **headers):
        request = RequestFactory().get("/item/", headers=headers)
        request.user = self.user
        request.session = SessionStore()
        request.session[BACKEND_SESSION_KEY] = "accounts.auth.CustomOidcAuthenticationBackend"
        return self.middleware(request), request.session

    def test_navigations_renew_the_expired_login(self):
        response, session = self.visit(sec_fetch_mode="navigate", sec_fetch_dest="document")
        self.assertEqual(response.status_code, 302)
        self.assertEqual(len(session["oidc_states"]), 1)
        response, session = self.visit()
        self.assertEqual(response.status_code, 302)

    def test_background_requests_leave_the_session_alone(self):
        for headers in [
            {"sec_fetch_mode": "cors", "sec_fetch_dest": "empty"},
            {"sec_fetch_mode": "navigate", "sec_fetch_dest": "iframe"},
            {"sec_fetch_mode": "navigate", "sec_fetch_dest": "document", "sec_purpose": "prefetch;prerender"},
        ]:
            with self.subTest(headers=headers):
                response, session = self.visit(**headers)
                self.assertEqual(response.status_code, 200)
                self.assertNotIn("oidc_states", session)

    def callback(self, states):
        session = self.client.session
        session["oidc_states"] = states
        session["oidc_login_next"] = "/item/"
        session.save()
        with patch("mozilla_django_oidc.views.auth.authenticate", return_value=None) as authenticate:
            response = self.client.get(reverse("oidc_authentication_callback"), {"code": "c", "state": "lost"})
        return response, authenticate

    def test_logged_in_user_continues_after_an_unknown_state(self):
        self.client.force_login(self.user)
        response, authenticate = self.callback({})
        self.assertRedirects(response, "/item/", fetch_redirect_response=False)
        authenticate.assert_not_called()

    def test_guest_is_asked_to_log_in_again_after_an_unknown_state(self):
        response, authenticate = self.callback({"other": {"nonce": "n", "added_on": 0}})
        self.assertRedirects(response, "/", fetch_redirect_response=False)
        authenticate.assert_not_called()
        self.assertIn("erneut an", str(list(response.wsgi_request._messages)[0]))

    def test_known_state_still_logs_in(self):
        response, authenticate = self.callback({"lost": {"nonce": "n", "code_verifier": None, "added_on": 0}})
        authenticate.assert_called_once()
        self.assertEqual(authenticate.call_args.kwargs["nonce"], "n")
