from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.urls import reverse


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
