from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.contrib.auth.models import AnonymousUser, Group, Permission
from django.http import HttpResponse
from django.test import RequestFactory, TestCase, override_settings

from accounts.auth import CustomOidcAuthenticationBackend
from accounts.groups import local_group_name
from imzam.local_network import LocalNetworkMiddleware


@override_settings(LOCAL_NETWORK_SOURCES=["192.0.2.0/24"])
class LocalMembershipTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(username="visitor")
        self.middleware = LocalNetworkMiddleware(lambda request: HttpResponse())

    def visit(self, user=None, session=None, address="198.51.100.1"):
        request = RequestFactory().get("/")
        request.user = user if user is not None else self.user
        request.session = session if session is not None else {}
        with patch("imzam.local_network.get_client_ip", return_value=(address, False)):
            self.middleware(request)
        return request

    def test_migration_grants_create_and_change_but_no_delete_permissions(self):
        group = Group.objects.get(name=local_group_name())
        actual = set(group.permissions.values_list("content_type__app_label", "codename"))
        expected = set(Permission.objects.filter(
            content_type__app_label="inventory",
            codename__regex=r"^(add|change)_",
        ).exclude(content_type__model="labelid").values_list("content_type__app_label", "codename"))
        # Unique item events are written by the inventory itself (inventory/models/unique_item.py).
        expected.discard(("inventory", "add_uniqueitemevent"))
        # Changing a unique item's owner after creation is for admins (inventory/models/unique_item.py).
        expected.discard(("inventory", "change_uniqueitem_owner"))
        # Axes and number ranges belong to the building structure, which admins maintain (docs/location-structure.md).
        expected -= {("inventory", "add_locationaxis"), ("inventory", "change_locationaxis"),
                     ("inventory", "add_locationnumberrange"), ("inventory", "change_locationnumberrange")}
        # The rules of label templates are part of the label setup in the admin (docs/label-printing.md).
        expected -= {("inventory", "add_labeltemplaterule"), ("inventory", "change_labeltemplaterule")}
        # Former codes stay blocked; only admins add or remove them (docs/location-structure.md).
        expected -= {("inventory", "add_locationformercode"), ("inventory", "change_locationformercode")}
        # The printable inventory is internal (inventory/migrations/0029_print_inventory_permission).
        expected.add(("inventory", "print_inventory"))
        # ZAM IDs: only claiming (inventory/migrations/0022_zamid_triggers_and_claim)
        expected.add(("inventory", "claim_labelid"))
        # Label printing: printing only (label_printing/migrations/0002_grant_print_label)
        expected.add(("label_printing", "print_label"))
        self.assertEqual(actual, expected)
        self.assertTrue(actual)

    def test_legacy_session_is_consumed_and_membership_persists(self):
        # Check the permission cache is invalidated in the granting request.
        self.assertFalse(self.user.has_perm("inventory.add_item"))
        request = self.visit(session={"is_local_visit": True, "last_seen_remote_addr": "192.0.2.1"})
        self.assertNotIn("is_local_visit", request.session)
        self.assertNotIn("last_seen_remote_addr", request.session)
        self.assertTrue(self.user.is_local_member)
        self.assertTrue(self.user.has_perm("inventory.add_item"))
        self.assertFalse(self.user.has_perm("inventory.delete_item"))
        with patch.object(self.middleware, "get_networks") as resolve:
            self.visit(user=get_user_model().objects.get(pk=self.user.pk), address=None)
        resolve.assert_not_called()
        self.assertTrue(get_user_model().objects.get(pk=self.user.pk).is_local_member)
        self.assertFalse(self.user.is_staff)

    def test_local_network_assigns_membership_without_a_session_flag(self):
        request = self.visit(address="192.0.2.7")
        self.assertTrue(self.user.is_local_member)
        self.assertNotIn("is_local_visit", request.session)

    def test_remote_users_are_not_assigned_membership(self):
        for address in ("198.51.100.1", None, "invalid"):
            self.visit(address=address)
        self.assertFalse(self.user.is_local_member)

    def test_anonymous_visit_is_remembered_until_login_without_granting_permissions(self):
        request = self.visit(user=AnonymousUser(), address="192.0.2.7")
        self.assertFalse(request.user.has_perm("inventory.add_item"))
        self.assertFalse(self.user.is_local_member)
        request = self.visit(session=request.session)
        self.assertTrue(self.user.is_local_member)
        self.assertNotIn("is_local_visit", request.session)

    def test_sso_cannot_grant_or_remove_local_membership(self):
        # No need to configure an OIDC connection to exercise group mapping.
        backend = object.__new__(CustomOidcAuthenticationBackend)
        backend.update_groups(self.user, {"groups": [local_group_name(), "SSO team"]})
        self.assertFalse(self.user.is_local_member)
        self.assertTrue(self.user.groups.filter(name="SSO team").exists())
        self.visit(address="192.0.2.7")
        backend.update_groups(self.user, {"groups": ["Other team"]})
        backend.update_groups(self.user, {})
        self.assertTrue(self.user.is_local_member)

    @override_settings(LOCAL_NETWORK_SOURCES=["das.zam.haus"])
    def test_a_record_match_assigns_persistent_membership(self):
        with patch("imzam.local_network.socket.gethostbyname_ex", return_value=("das.zam.haus", [], ["198.51.100.1"])):
            self.visit()
        self.assertTrue(self.user.is_local_member)
        self.assertTrue(self.user.has_perm("inventory.add_item"))


class OidcProfileTests(TestCase):
    @override_settings(OIDC_ADMIN_GROUPS=["admins"], OIDC_STAFF_GROUPS=["staff"])
    def test_profile_groups_and_roles_set_and_clear_admin_flags(self):
        user = get_user_model().objects.create_user(username="profile")
        backend = object.__new__(CustomOidcAuthenticationBackend)
        claims = {"email": "profile@example.org", "given_name": "Test", "family_name": "User"}
        backend.update_profile(user, {**claims, "groups": ["admins"], "roles": ["staff"]})
        user.refresh_from_db()
        self.assertTrue(user.is_superuser)
        self.assertTrue(user.is_staff)
        backend.update_profile(user, claims)
        user.refresh_from_db()
        self.assertFalse(user.is_superuser)
        self.assertFalse(user.is_staff)

    def test_groups_missing_from_claim_are_removed(self):
        user = get_user_model().objects.create_user(username="member")
        backend = object.__new__(CustomOidcAuthenticationBackend)
        backend.update_groups(user, {"groups": ["team a", "team b"]})
        backend.update_groups(user, {"groups": ["team b", "team c"]})
        self.assertEqual(set(user.groups.values_list("name", flat=True)), {"team b", "team c"})
        backend.update_groups(user, {})
        self.assertFalse(user.groups.exists())
        self.assertTrue(Group.objects.filter(name="team a").exists())

    @override_settings(OIDC_CLAIM_REFERENCE_KEY="directory_id")
    def test_missing_claim_does_not_match_local_users(self):
        user = get_user_model().objects.create_user(username="local")
        backend = object.__new__(CustomOidcAuthenticationBackend)
        self.assertFalse(backend.filter_users_by_claims({}).exists())
        user.directory_reference = "directory-123"
        user.save()
        self.assertEqual(list(backend.filter_users_by_claims({"directory_id": "directory-123"})), [user])


class LocalNetworkNamingTests(TestCase):
    @override_settings(LOCAL_NETWORK_NAME="Werkstatt", LOCAL_GROUP_NAME="Werkstatt-lokal",
                       LOCAL_NETWORK_SOURCES=["192.0.2.0/24"])
    def test_group_and_badge_follow_the_settings(self):
        user = get_user_model().objects.create_user(username="ada")
        request = RequestFactory().get("/")
        request.user, request.session = user, {}
        with patch("imzam.local_network.get_client_ip", return_value=("192.0.2.7", False)):
            LocalNetworkMiddleware(lambda request: HttpResponse())(request)
        self.assertTrue(user.groups.filter(name="Werkstatt-lokal").exists())
        self.assertTrue(user.is_local_member)
        self.client.force_login(user)
        self.assertContains(self.client.get("/"), "(Werkstatt)")

    def test_sessions_from_before_the_rename_still_count(self):
        user = get_user_model().objects.create_user(username="ada")
        request = RequestFactory().get("/")
        request.user, request.session = user, {"is_zam_local": True}
        with patch("imzam.local_network.get_client_ip", return_value=("198.51.100.1", False)):
            LocalNetworkMiddleware(lambda request: HttpResponse())(request)
        self.assertTrue(user.is_local_member)
        self.assertEqual(request.session, {})
