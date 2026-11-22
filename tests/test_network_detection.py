"""Native Windows adapter detection regressions, without scanning a live LAN."""

import ctypes as c
from io import StringIO
from ipaddress import IPv4Address
import json
import subprocess
import sys
import unittest
from unittest.mock import Mock, patch

from ugnay import windows_network as native
from ugnay.discovery import DiscoveryService, NetworkDetectionError, _NETWORK_HELPER
from ugnay.models import NetworkInfo


def record(**changes):
    return {
        "InterfaceAlias": "Wi-Fi", "InterfaceIndex": 12, "InterfaceType": 71,
        "HardwareInterface": True, "Status": "Up", "InterfaceMetric": 25,
        "IPAddress": "192.0.2.65", "PrefixLength": 26,
        "AddressState": "Preferred", "SkipAsSource": False,
    } | changes


class DetectionProcessTests(unittest.TestCase):
    def setUp(self):
        platform = patch("ugnay.discovery.sys.platform", "win32")
        platform.start()
        self.addCleanup(platform.stop)
        flags = patch("ugnay.discovery.subprocess.CREATE_NO_WINDOW", 0, create=True)
        flags.start()
        self.addCleanup(flags.stop)

    def detect(self, records, service=None):
        result = subprocess.CompletedProcess([], 0, json.dumps(records), "")
        with patch("ugnay.discovery.subprocess.run", return_value=result):
            return (service or DiscoveryService()).detect_network()

    def test_native_helper_replaces_powershell_and_preserves_real_prefix(self):
        result = subprocess.CompletedProcess([], 0, json.dumps([record()]), "")
        with patch("ugnay.discovery.subprocess.run", return_value=result) as run:
            self.assertEqual(DiscoveryService().detect_network(), NetworkInfo("192.0.2.65", "192.0.2.64/26"))
        self.assertEqual(run.call_args.args[0], [sys.executable, "-I", "-X", "utf8", str(_NETWORK_HELPER)])
        self.assertEqual(run.call_args.kwargs["timeout"], 20)
        self.assertTrue(run.call_args.kwargs["check"])

    def test_prefers_physical_lan_then_metric_not_virtual_adapter(self):
        rows = [record(InterfaceAlias="Virtual", HardwareInterface=False, InterfaceMetric=1, IPAddress="198.51.100.1"),
                record(InterfaceAlias="Ethernet", InterfaceType=6, InterfaceMetric=15, IPAddress="192.0.2.1"), record()]
        self.assertEqual(self.detect(rows).local_ip, "192.0.2.1")

    def test_unusable_addresses_and_adapters_are_excluded(self):
        for changes in ({"Status": "Down"}, {"InterfaceType": 24}, {"SkipAsSource": True},
                        {"AddressState": "Unavailable"}, {"IPAddress": "127.0.0.1"},
                        {"IPAddress": "0.0.0.0"}, {"IPAddress": "255.255.255.255"},
                        {"IPAddress": "224.0.0.1"}, {"IPAddress": "::1"}):
            with self.subTest(changes=changes), self.assertRaises(NetworkDetectionError):
                self.detect([record(**changes)])

    def test_explicit_alias_is_literal_case_insensitive_and_never_falls_back(self):
        rows = [record(InterfaceAlias="Ethernet", InterfaceMetric=1, IPAddress="198.51.100.1"), record()]
        self.assertEqual(self.detect(rows, DiscoveryService(interface_alias="wi-FI")).local_ip, "192.0.2.65")
        with self.assertRaisesRegex(NetworkDetectionError, "No connected interface named"):
            self.detect(rows, DiscoveryService(interface_alias="Wi-*"))

    def test_link_local_is_a_valid_fallback_without_a_gateway(self):
        self.assertEqual(self.detect([record(IPAddress="169.254.8.9", PrefixLength=16)]).subnet, "169.254.0.0/16")
        self.assertEqual(self.detect([record(IPAddress="169.254.8.9", PrefixLength=16),
                                      record(IPAddress="192.0.2.1", InterfaceMetric=100)]).local_ip, "192.0.2.1")

    def test_timeout_clears_cached_adapter_and_next_attempt_recovers(self):
        service = DiscoveryService()
        service._network = NetworkInfo("198.51.100.1", "198.51.100.0/24")
        with patch("ugnay.discovery.subprocess.run", side_effect=subprocess.TimeoutExpired("helper", 20)):
            with self.assertRaisesRegex(NetworkDetectionError, "helper timed out"):
                service.detect_network()
        self.assertIsNone(service._network)
        self.assertEqual(self.detect([record()], service).local_ip, "192.0.2.65")

    def test_native_failure_reports_the_backend_error(self):
        error = subprocess.CalledProcessError(1, "helper", stderr="GetAdaptersAddresses failed (Windows status 5).")
        with patch("ugnay.discovery.subprocess.run", side_effect=error):
            with self.assertRaisesRegex(NetworkDetectionError, "Windows status 5"):
                DiscoveryService().detect_network()

    def test_empty_and_malformed_records_cannot_become_a_successful_scan(self):
        for value in ([], None, ["invalid"], [record(PrefixLength=33)], [record(InterfaceMetric=-1)]):
            with self.subTest(value=value), self.assertRaises(NetworkDetectionError):
                self.detect(value)


class NativeAdapterTests(unittest.TestCase):
    def setUp(self):
        self.api = Mock()
        loader = patch.object(native.c, "WinDLL", return_value=self.api, create=True)
        loader.start()
        self.addCleanup(loader.stop)
        platform = patch.object(native.sys, "platform", "win32")
        platform.start()
        self.addCleanup(platform.stop)
        self.keep = []

    def fixture(self, *, status=1, kind=71, hardware=True, dad=4, skip=False):
        address = native._SockaddrIn(Family=2, Address=(native.BYTE * 4)(*IPv4Address("192.0.2.65").packed))
        unicast = native._UnicastAddress(Socket=native._SocketAddress(c.addressof(address), c.sizeof(address)))
        adapter = native._AdapterAddresses(
            Length=448, IfIndex=12, FriendlyName="Wi-Fi", FirstUnicastAddress=c.pointer(unicast),
            IfType=kind, OperStatus=status, Ipv4Metric=25,
        )
        self.keep.extend((address, unicast, adapter))

        def adapters(family, flags, reserved, buffer, size):
            self.assertEqual(family, 2)
            self.assertFalse(flags & 1)  # Unicast addresses must be retained.
            c.memmove(buffer, c.byref(adapter), c.sizeof(adapter))
            return 0

        def interface(pointer):
            row = c.cast(pointer, c.POINTER(native._InterfaceRow)).contents
            self.assertEqual(row.Index, 12)
            row.StatusFlags = int(hardware)
            row.OperStatus = status
            return 0

        def unicast_entry(pointer):
            row = c.cast(pointer, c.POINTER(native._UnicastRow)).contents
            self.assertEqual(row.Index, 12)
            self.assertEqual(bytes(row.Address.Ipv4.Address), IPv4Address("192.0.2.65").packed)
            row.PrefixLength, row.SkipAsSource, row.DadState = 26, int(skip), dad
            return 0

        self.api.GetAdaptersAddresses.side_effect = adapters
        self.api.GetIfEntry2.side_effect = interface
        self.api.GetUnicastIpAddressEntry.side_effect = unicast_entry

    def test_structure_layout_matches_windows_sdk_offsets_and_buffer_sizes(self):
        # SDK constants: IF_MAX_STRING_SIZE=256; aliases include a terminator.
        # Golden offsets catch ABI errors that a mock writing the same type misses.
        self.assertEqual(c.sizeof(native._InterfaceRow), 1352)
        self.assertEqual(native._InterfaceRow.StatusFlags.offset, 1152)
        self.assertEqual(native._InterfaceRow.OperStatus.offset, 1156)
        self.assertEqual(native._InterfaceRow.TransmitLinkSpeed.offset, 1192)
        self.assertEqual(c.sizeof(native._UnicastRow), 80)
        self.assertEqual(native._UnicastRow.PrefixLength.offset, 60)
        self.assertEqual(native._UnicastRow.DadState.offset, 64)

    def test_native_addresses_preserve_prefix_metric_hardware_and_alias(self):
        self.fixture()
        self.assertEqual(native.read_ipv4_interfaces(), [record()])

    def test_source_eligibility_and_virtual_hardware_are_not_guessed(self):
        self.fixture(hardware=False, dad=2, skip=True)
        self.assertEqual(native.read_ipv4_interfaces(), [record(HardwareInterface=False, AddressState="Unavailable", SkipAsSource=True)])

    def test_down_and_loopback_adapters_are_not_queried_further(self):
        for status, kind in ((2, 71), (1, 24)):
            with self.subTest(status=status, kind=kind):
                self.fixture(status=status, kind=kind)
                self.assertEqual(native.read_ipv4_interfaces(), [])
        self.api.GetIfEntry2.assert_not_called()

    def test_buffer_growth_is_retried_when_adapter_configuration_changes(self):
        self.fixture()
        successful = self.api.GetAdaptersAddresses.side_effect

        def resize(*args):
            if self.api.GetAdaptersAddresses.call_count == 1:
                c.cast(args[-1], c.POINTER(native.DWORD)).contents.value = 30_000
                return 111
            self.assertEqual(c.sizeof(args[3]), 30_000)
            return successful(*args)

        self.api.GetAdaptersAddresses.side_effect = resize
        self.assertEqual(native.read_ipv4_interfaces(), [record()])
        self.assertEqual(self.api.GetAdaptersAddresses.call_count, 2)

    def test_repeated_buffer_changes_terminate_with_an_actionable_error(self):
        self.api.GetAdaptersAddresses.side_effect = None
        self.api.GetAdaptersAddresses.return_value = 111
        with self.assertRaisesRegex(OSError, "kept changing"):
            native.read_ipv4_interfaces()
        self.assertEqual(self.api.GetAdaptersAddresses.call_count, 3)

    def test_no_addresses_returns_empty_records_but_api_failures_raise(self):
        self.api.GetAdaptersAddresses.return_value = 232
        self.assertEqual(native.read_ipv4_interfaces(), [])
        self.api.GetAdaptersAddresses.return_value = 5
        with self.assertRaisesRegex(OSError, "GetAdaptersAddresses.*status 5"):
            native.read_ipv4_interfaces()

    def test_adapter_or_address_removed_during_detection_is_skipped(self):
        for operation in ("GetIfEntry2", "GetUnicastIpAddressEntry"):
            with self.subTest(operation=operation):
                self.fixture()
                call = getattr(self.api, operation)
                call.side_effect = None
                call.return_value = 1168
                self.assertEqual(native.read_ipv4_interfaces(), [])

    def test_native_cli_failure_returns_nonzero_without_a_traceback(self):
        output, errors = StringIO(), StringIO()
        with patch.object(native, "read_ipv4_interfaces", side_effect=OSError("adapter read failed")), \
             patch("sys.stdout", output), patch("sys.stderr", errors):
            self.assertEqual(native.main(), 1)
        self.assertEqual(output.getvalue(), "")
        self.assertIn("adapter read failed", errors.getvalue())
        self.assertNotIn("Traceback", errors.getvalue())


if __name__ == "__main__":
    unittest.main()
