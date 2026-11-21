"""Regression coverage for ICMP helper startup timeouts; no live probes."""

import ctypes
from io import StringIO
from ipaddress import IPv4Address
import json
import struct
import subprocess
import sys
import threading
import unittest
from unittest.mock import Mock, patch

from ugnay import icmp_probe
from ugnay.discovery import DiscoveryService, NetworkScanError, _PROBE_HELPER
from ugnay.models import NetworkInfo


class ProbeProcessTests(unittest.TestCase):
    def setUp(self):
        self.platform = patch("ugnay.discovery.sys.platform", "win32")
        self.platform.start()
        self.addCleanup(self.platform.stop)
        self.flags = patch("ugnay.discovery.subprocess.CREATE_NO_WINDOW", 0, create=True)
        self.flags.start()
        self.addCleanup(self.flags.stop)
        self.service = DiscoveryService()

    @staticmethod
    def reply(status=0, address="192.0.2.1"):
        return subprocess.CompletedProcess(["helper"], 0, json.dumps({"Status": status, "Address": address}), "")

    def test_transient_helper_timeout_recovers_with_one_retry(self):
        expired = subprocess.TimeoutExpired("helper", self.service.process_timeout)
        with patch("ugnay.discovery.subprocess.run", side_effect=[expired, self.reply()]) as run:
            self.assertTrue(self.service._probe_host("192.0.2.1"))
        self.assertEqual(run.call_count, 2)
        for call in run.call_args_list:
            self.assertEqual(call.args[0], [sys.executable, "-I", "-X", "utf8", str(_PROBE_HELPER)])
            self.assertEqual(json.loads(call.kwargs["input"]), {"IPAddress": "192.0.2.1", "TimeoutMs": 1000})
            self.assertEqual(call.kwargs["timeout"], self.service.process_timeout)
            self.assertTrue(call.kwargs["check"])

    def test_repeated_process_timeout_is_still_an_execution_failure(self):
        expired = subprocess.TimeoutExpired("helper", self.service.process_timeout)
        with patch("ugnay.discovery.subprocess.run", side_effect=expired) as run:
            with self.assertRaisesRegex(NetworkScanError, "192.0.2.1.*both attempts") as caught:
                self.service._probe_host("192.0.2.1")
        self.assertEqual(run.call_count, 2)
        self.assertIs(caught.exception.__cause__, expired)

    def test_normal_no_response_does_not_retry_or_fail_the_scan(self):
        for status in (11002, 11003, 11004, 11005, 11010, 11013, 11014, 11040, 11041):
            with self.subTest(status=status), patch("ugnay.discovery.subprocess.run", return_value=self.reply(status, None)) as run:
                self.assertFalse(self.service._probe_host("192.0.2.1"))
                self.assertEqual(run.call_count, 1)

    def test_success_must_come_from_the_requested_address(self):
        with patch("ugnay.discovery.subprocess.run", return_value=self.reply(address="192.0.2.2")):
            self.assertFalse(self.service._probe_host("192.0.2.1"))

    def test_native_backend_errors_are_not_classified_as_absent_devices(self):
        with patch("ugnay.discovery.subprocess.run", return_value=self.reply(5, None)):
            with self.assertRaisesRegex(NetworkScanError, "Windows status 5"):
                self.service._probe_host("192.0.2.1")

    def test_invalid_helper_output_is_not_silently_skipped(self):
        for value in ("not JSON", "[]", '{"Status":true}', '{"Status":0,"Address":"invalid"}'):
            with self.subTest(value=value), patch("ugnay.discovery.subprocess.run", return_value=subprocess.CompletedProcess([], 0, value)):
                with self.assertRaises(NetworkScanError):
                    self.service._probe_host("192.0.2.1")

    def test_helper_execution_error_is_actionable_and_not_retried(self):
        failed = subprocess.CalledProcessError(1, "helper", stderr="Native ICMP probe failed: access denied")
        with patch("ugnay.discovery.subprocess.run", side_effect=failed) as run:
            with self.assertRaisesRegex(NetworkScanError, "access denied"):
                self.service._probe_host("192.0.2.1")
        self.assertEqual(run.call_count, 1)

    def test_scan_finishes_after_one_probe_needs_a_startup_retry(self):
        service = DiscoveryService(max_workers=3)
        service._network = NetworkInfo("192.0.2.4", "192.0.2.0/29")
        attempts = {}
        lock = threading.Lock()

        def execute(command, **kwargs):
            if command[-1] != str(_PROBE_HELPER):
                return subprocess.CompletedProcess(command, 0, json.dumps("test-host"), "")
            address = json.loads(kwargs["input"])["IPAddress"]
            with lock:
                attempts[address] = attempts.get(address, 0) + 1
                attempt = attempts[address]
            if address == "192.0.2.1" and attempt == 1:
                raise subprocess.TimeoutExpired(command, service.process_timeout)
            return self.reply(0 if address in ("192.0.2.1", "192.0.2.4") else 11010, address)

        with patch("ugnay.discovery.subprocess.run", side_effect=execute):
            result = service.scan_network("192.0.2.0/29")
        self.assertEqual([device.ip_address for device in result.devices], ["192.0.2.1", "192.0.2.4"])
        self.assertEqual(attempts["192.0.2.1"], 2)
        self.assertEqual(len(attempts), 6)
        self.assertTrue(all(device.hostname == "test-host" for device in result.devices))


class NativeIcmpTests(unittest.TestCase):
    def setUp(self):
        self.api = Mock()
        self.api.IcmpCreateFile.return_value = 42
        self.loader = patch.object(icmp_probe.ctypes, "WinDLL", return_value=self.api, create=True)
        self.loader.start()
        self.addCleanup(self.loader.stop)
        self.platform = patch("ugnay.icmp_probe.sys.platform", "win32")
        self.platform.start()
        self.addCleanup(self.platform.stop)

    def test_reply_header_and_network_byte_order(self):
        def echo(handle, destination, payload, payload_size, options, reply, size, timeout):
            self.assertEqual(handle, 42)
            self.assertEqual(destination, int.from_bytes(IPv4Address("192.0.2.1").packed, "little"))
            self.assertEqual(timeout, 1000)
            self.assertGreaterEqual(size, 64 + payload_size + 8)
            header = IPv4Address("192.0.2.1").packed + struct.pack("<IIHH", 0, 3, payload_size, 0)
            ctypes.memmove(reply, header, len(header))
            return 1

        self.api.IcmpSendEcho.side_effect = echo
        self.assertEqual(icmp_probe.probe("192.0.2.1", 1000), {"Status": 0, "Address": "192.0.2.1"})
        self.api.IcmpCloseHandle.assert_called_once_with(42)

    def test_no_reply_returns_windows_status_and_closes_handle(self):
        self.api.IcmpSendEcho.return_value = 0
        with patch.object(icmp_probe.ctypes, "get_last_error", return_value=11010, create=True):
            self.assertEqual(icmp_probe.probe("192.0.2.1", 1000), {"Status": 11010, "Address": None})
        self.api.IcmpCloseHandle.assert_called_once_with(42)

    def test_native_call_failure_always_closes_handle(self):
        self.api.IcmpSendEcho.side_effect = OSError("native call failed")
        with self.assertRaises(OSError):
            icmp_probe.probe("192.0.2.1", 1000)
        self.api.IcmpCloseHandle.assert_called_once_with(42)

    def test_zero_error_without_reply_is_an_execution_failure(self):
        self.api.IcmpSendEcho.return_value = 0
        with patch.object(icmp_probe.ctypes, "get_last_error", return_value=0, create=True):
            with self.assertRaisesRegex(OSError, "no Windows error status"):
                icmp_probe.probe("192.0.2.1", 1000)

    def test_invalid_input_never_opens_an_icmp_handle(self):
        for address, timeout in (("not-an-ip", 1000), ("192.0.2.1", 0), ("192.0.2.1", True), ("192.0.2.1", 2**31)):
            with self.subTest(address=address, timeout=timeout), self.assertRaises(ValueError):
                icmp_probe.probe(address, timeout)
        self.api.IcmpCreateFile.assert_not_called()

    def test_helper_cli_reports_invalid_request_without_a_traceback(self):
        output, errors = StringIO(), StringIO()
        with patch("sys.stdin", StringIO('{"IPAddress":"invalid","TimeoutMs":1000}')), \
             patch("sys.stdout", output), patch("sys.stderr", errors):
            self.assertEqual(icmp_probe.main(), 1)
        self.assertEqual(output.getvalue(), "")
        self.assertIn("Native ICMP probe failed", errors.getvalue())
        self.assertNotIn("Traceback", errors.getvalue())


if __name__ == "__main__":
    unittest.main()
