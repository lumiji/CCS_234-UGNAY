"""Ping timeout settings and measured response regressions; no live probes."""

import subprocess
import unittest
from unittest.mock import patch

from ugnay.connectivity import ConnectivityService
from ugnay.models import Device


class ConnectivityTimeoutTests(unittest.TestCase):
    def test_selected_timeout_controls_ping_and_process_deadline(self):
        service = ConnectivityService()
        reply = subprocess.CompletedProcess([], 0, "Reply from 192.0.2.1: bytes=32 time=7ms TTL=64", "")
        for timeout in (1, 2, 5):
            with self.subTest(timeout=timeout), patch("ugnay.connectivity.subprocess.run", return_value=reply) as run:
                result = service.test_connection(Device("192.0.2.1"), 4, timeout_seconds=timeout)
                self.assertEqual(run.call_count, 4)
                command = run.call_args.args[0]
                self.assertEqual(command[command.index("-w") + 1], str(timeout * 1000))
                self.assertGreater(run.call_args.kwargs["timeout"], timeout)
                self.assertEqual(result.average_latency_ms, 7.)
                self.assertEqual(result.packet_loss_percent, 0.)

    def test_existing_callers_retain_default_timeout(self):
        reply = subprocess.CompletedProcess([], 1, "Request timed out.", "")
        with patch("ugnay.connectivity.subprocess.run", return_value=reply) as run:
            result = ConnectivityService().test_connection(Device("192.0.2.1"), 4)
        self.assertEqual(run.call_args.args[0][5], "1000")
        self.assertIsNone(result.average_latency_ms)
        self.assertEqual(result.packet_loss_percent, 100.)

    def test_invalid_timeout_never_starts_ping(self):
        with patch("ugnay.connectivity.subprocess.run") as run:
            for timeout in (0, -1, True, "2", 2.0, 3, 1000):
                with self.subTest(timeout=timeout), self.assertRaises(ValueError):
                    ConnectivityService().test_connection(Device("192.0.2.1"), 4, timeout_seconds=timeout)
        run.assert_not_called()


if __name__ == "__main__":
    unittest.main()
