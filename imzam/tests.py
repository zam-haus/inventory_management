import socket
from unittest import TestCase
from unittest.mock import patch

from django.contrib.auth.models import AnonymousUser
from django.http import HttpResponse
from django.test import RequestFactory, SimpleTestCase, override_settings

from .settings import parse_bool
from .zam_local import ZAMLocalMiddleware


class EnvironmentBooleanTests(TestCase):
    def test_true_values(self):
        for value in ("y", "yes", "t", "true", "on", "1", "TRUE", "Yes"):
            with self.subTest(value=value):
                self.assertIs(parse_bool(value), True)

    def test_false_values(self):
        for value in ("n", "no", "f", "false", "off", "0", "FALSE", "Off"):
            with self.subTest(value=value):
                self.assertIs(parse_bool(value), False)

    def test_invalid_values_are_rejected(self):
        for value in ("", "invalid", "2", " true "):
            with self.subTest(value=value):
                with self.assertRaises(ValueError):
                    parse_bool(value)


@override_settings(ZAM_LOCAL_SOURCES=["das.zam.haus"], ZAM_LOCAL_DNS_CACHE_SECONDS=60)
class ZAMLocalDNSTests(SimpleTestCase):
    def setUp(self):
        self.middleware = ZAMLocalMiddleware(lambda request: HttpResponse())

    def visit(self, address):
        request = RequestFactory().get("/")
        request.user = AnonymousUser()
        request.session = {}
        with patch("imzam.zam_local.get_client_ip", return_value=(address, False)):
            self.assertEqual(self.middleware(request).status_code, 200)
        return request.session.get("is_zam_local", False)

    @override_settings(ZAM_LOCAL_SOURCES=["das.zam.haus", "other.example.org"])
    def test_all_a_records_from_all_hostnames_match(self):
        with patch("imzam.zam_local.socket.gethostbyname_ex", side_effect=[
            ("das.zam.haus", [], ["192.0.2.1", "192.0.2.2"]),
            ("other.example.org", [], ["198.51.100.3"]),
        ]) as resolve:
            for address in ("192.0.2.1", "192.0.2.2", "198.51.100.3"):
                self.assertTrue(self.visit(address))
            self.assertFalse(self.visit("203.0.113.4"))
            self.assertFalse(self.visit("2001:db8::1"))
        self.assertEqual([call.args for call in resolve.call_args_list], [("das.zam.haus",), ("other.example.org",)])

    @override_settings(ZAM_LOCAL_SOURCES=["192.0.2.5", "198.51.100.0/24", "2001:db8::1", "2001:db8:1::/48"])
    def test_ipv4_and_ipv6_addresses_and_ranges_need_no_dns(self):
        with patch("imzam.zam_local.socket.gethostbyname_ex") as resolve:
            for address in ("192.0.2.5", "198.51.100.0", "198.51.100.255", "2001:db8::1", "2001:db8:1::42"):
                self.assertTrue(self.visit(address), address)
            for address in ("192.0.2.6", "198.51.101.1", "2001:db8::2", "2001:db8:2::1", None, "invalid"):
                self.assertFalse(self.visit(address), address)
        resolve.assert_not_called()

    @override_settings(ZAM_LOCAL_SOURCES=[])
    def test_empty_configuration_disables_network_grants(self):
        with patch("imzam.zam_local.socket.gethostbyname_ex") as resolve:
            self.assertFalse(self.visit("192.0.2.1"))
        resolve.assert_not_called()

    def test_dns_results_refresh_after_cache_expiry(self):
        with patch("imzam.zam_local.monotonic", return_value=100) as now, patch(
            "imzam.zam_local.socket.gethostbyname_ex",
            side_effect=[("das.zam.haus", [], ["192.0.2.1"]), ("das.zam.haus", [], ["192.0.2.2"])],
        ) as resolve:
            self.assertTrue(self.visit("192.0.2.1"))
            now.return_value = 159
            self.assertTrue(self.visit("192.0.2.1"))
            self.assertEqual(resolve.call_count, 1)
            now.return_value = 160
            self.assertTrue(self.visit("192.0.2.2"))
            self.assertFalse(self.visit("192.0.2.1"))
            self.assertEqual(resolve.call_count, 2)

    @override_settings(ZAM_LOCAL_SOURCES=["das.zam.haus", "192.0.2.9"])
    def test_failed_refresh_discards_old_dns_results_but_keeps_literal_sources(self):
        with patch("imzam.zam_local.monotonic", return_value=100) as now, patch(
            "imzam.zam_local.socket.gethostbyname_ex",
            side_effect=[("das.zam.haus", [], ["192.0.2.1"]), socket.gaierror("unavailable")],
        ) as resolve:
            self.assertTrue(self.visit("192.0.2.1"))
            now.return_value = 160
            with self.assertLogs("imzam.zam_local", level="WARNING"):
                self.assertFalse(self.visit("192.0.2.1"))
            self.assertTrue(self.visit("192.0.2.9"))
            self.assertEqual(resolve.call_count, 2)

    @override_settings(ZAM_LOCAL_DNS_CACHE_SECONDS=0)
    def test_cache_can_be_disabled(self):
        with patch("imzam.zam_local.socket.gethostbyname_ex", return_value=("das.zam.haus", [], ["192.0.2.1"])) as resolve:
            self.assertTrue(self.visit("192.0.2.1"))
            self.assertTrue(self.visit("192.0.2.1"))
            self.assertEqual(resolve.call_count, 2)
