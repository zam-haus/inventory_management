from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.contrib.auth.models import AnonymousUser, Group, Permission
from django.http import HttpResponse
from django.test import RequestFactory, TestCase, override_settings

from accounts.auth import CustomOidcAuthenticationBackend
from accounts.groups import ZAM_LOCAL_GROUP_NAME
from imzam.zam_local import ZAMLocalMiddleware


@override_settings(ZAM_LOCAL_SOURCES=["192.0.2.0/24"])
class ZAMMembershipTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(username="visitor")
        self.middleware = ZAMLocalMiddleware(lambda request: HttpResponse())

    def visit(self, user=None, session=None, address="198.51.100.1"):
        request = RequestFactory().get("/")
        request.user = user if user is not None else self.user
        request.session = session if session is not None else {}
        with patch("imzam.zam_local.get_client_ip", return_value=(address, False)):
            self.middleware(request)
        return request

    def test_migration_grants_create_and_change_but_no_delete_permissions(self):
        group = Group.objects.get(name=ZAM_LOCAL_GROUP_NAME)
        actual = set(group.permissions.values_list("content_type__app_label", "codename"))
        expected = set(Permission.objects.filter(
            content_type__app_label="inventory",
            codename__regex=r"^(add|change)_",
        ).values_list("content_type__app_label", "codename"))
        self.assertEqual(actual, expected)
        self.assertTrue(actual)

    def test_legacy_session_is_consumed_and_membership_persists(self):
        # Check the permission cache is invalidated in the granting request.
        self.assertFalse(self.user.has_perm("inventory.add_item"))
        request = self.visit(session={"is_zam_local": True, "last_seen_remote_addr": "192.0.2.1"})
        self.assertNotIn("is_zam_local", request.session)
        self.assertNotIn("last_seen_remote_addr", request.session)
        self.assertTrue(self.user.is_zam_local)
        self.assertTrue(self.user.has_perm("inventory.add_item"))
        self.assertFalse(self.user.has_perm("inventory.delete_item"))
        with patch.object(self.middleware, "get_networks") as resolve:
            self.visit(user=get_user_model().objects.get(pk=self.user.pk), address=None)
        resolve.assert_not_called()
        self.assertTrue(get_user_model().objects.get(pk=self.user.pk).is_zam_local)
        self.assertFalse(self.user.is_staff)

    def test_local_network_assigns_membership_without_a_session_flag(self):
        request = self.visit(address="192.0.2.7")
        self.assertTrue(self.user.is_zam_local)
        self.assertNotIn("is_zam_local", request.session)

    def test_remote_users_are_not_assigned_membership(self):
        for address in ("198.51.100.1", None, "invalid"):
            self.visit(address=address)
        self.assertFalse(self.user.is_zam_local)

    def test_anonymous_visit_is_remembered_until_login_without_granting_permissions(self):
        request = self.visit(user=AnonymousUser(), address="192.0.2.7")
        self.assertFalse(request.user.has_perm("inventory.add_item"))
        self.assertFalse(self.user.is_zam_local)
        request = self.visit(session=request.session)
        self.assertTrue(self.user.is_zam_local)
        self.assertNotIn("is_zam_local", request.session)

    def test_sso_cannot_grant_or_remove_local_membership(self):
        # No need to configure an OIDC connection to exercise group mapping.
        backend = object.__new__(CustomOidcAuthenticationBackend)
        backend.update_groups(self.user, {"groups": [ZAM_LOCAL_GROUP_NAME, "SSO team"]})
        self.assertFalse(self.user.is_zam_local)
        self.assertTrue(self.user.groups.filter(name="SSO team").exists())
        self.visit(address="192.0.2.7")
        backend.update_groups(self.user, {"groups": ["Other team"]})
        backend.update_groups(self.user, {})
        self.assertTrue(self.user.is_zam_local)

    @override_settings(ZAM_LOCAL_SOURCES=["das.zam.haus"])
    def test_a_record_match_assigns_persistent_membership(self):
        with patch("imzam.zam_local.socket.gethostbyname_ex", return_value=("das.zam.haus", [], ["198.51.100.1"])):
            self.visit()
        self.assertTrue(self.user.is_zam_local)
        self.assertTrue(self.user.has_perm("inventory.add_item"))
