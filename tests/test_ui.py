"""UI contract checks; no network access, report generation, or file export."""

import time
import unittest
from unittest.mock import Mock, patch

from ugnay.app import UgnayApp
from ugnay.demo_data import SAMPLE_NETWORK, SAMPLE_TIME
from ugnay.models import DeviceStatus, DiscoveryResult, PingReply, PingResult


class InterfaceTests(unittest.TestCase):
    def setUp(self):
        self.app = UgnayApp()
        self.app.update()

    def tearDown(self):
        self.app._close()

    def settle_worker(self):
        deadline = time.monotonic() + 4
        while self.app.busy and time.monotonic() < deadline:
            self.app.update()
            time.sleep(.01)
        self.assertFalse(self.app.busy, "Service callback did not return to the UI")

    def test_navigation_and_shared_device_selection(self):
        for name in ("Devices", "Ping tests", "Reports", "Overview"):
            self.app.show_page(name)
            self.app.update()
            self.assertEqual(self.app.current_page, name)
        self.app.select_device("192.168.1.1")
        self.app.update()
        self.assertEqual(self.app.devices_name.cget("text"), "Router")
        self.assertEqual(self.app.ping_device_name.cget("text"), "Router")
        self.assertEqual(self.app.overview_table.tree.selection(), ("192.168.1.1",))
        self.assertEqual(self.app.devices_table.tree.selection(), ("192.168.1.1",))

    def test_untested_device_clears_previous_statistics(self):
        self.app.select_device("192.168.1.35")
        self.app.update()
        self.assertEqual(self.app.devices_name.cget("text"), "Hostname unavailable")
        self.assertEqual([v.get() for v in self.app.ping_stats], ["—", "—", "—"])
        self.assertEqual(self.app.ping_badge.text.cget("text"), "Not tested")

    def test_empty_scan_disables_device_actions(self):
        self.app.apply_discovery_result(DiscoveryResult(SAMPLE_NETWORK, SAMPLE_TIME, ()))
        self.app.update()
        self.assertEqual(self.app.devices_table.tree.get_children(), ())
        self.assertIsNone(self.app.selected_device)
        self.assertEqual(str(self.app.ping_button.cget("state")), "disabled")
        self.assertEqual(str(self.app.generate_button.cget("state")), "disabled")
        self.assertIn("No active devices", self.app.status_text.get())

    def test_all_timeout_result(self):
        result = PingResult("192.168.1.24", SAMPLE_TIME,
                            tuple(PingReply(i, None) for i in range(1, 5)),
                            None, None, 100.0, DeviceStatus.UNREACHABLE)
        self.app.apply_ping_result(result)
        self.app.update()
        self.assertEqual([v.get() for v in self.app.ping_stats], ["—", "—", "100%"])
        self.assertEqual(self.app.ping_badge.text.cget("text"), "Unreachable")
        self.assertEqual(self.app.ping_output.get("1.0", "end").count("Request timed out"), 4)

    def test_stub_buttons_remain_inert(self):
        with patch("ugnay.app.messagebox.showinfo") as notice, \
                patch("ugnay.app.filedialog.asksaveasfilename", return_value="unused-placeholder.txt"):
            for callback in (self.app.on_scan_network, self.app.on_test_connection,
                             self.app.on_generate_report, self.app.on_export_report):
                callback()
                self.settle_worker()
                self.assertIn("Integration pending", self.app.status_text.get())
            self.assertEqual(notice.call_count, 4)

    def test_export_cancel_does_not_invoke_exporter(self):
        self.app.reporting.export_report = Mock()
        with patch("ugnay.app.filedialog.asksaveasfilename", return_value=""):
            self.app.on_export_report()
        self.app.reporting.export_report.assert_not_called()

    def test_ping_count_is_passed_without_rewriting_existing_results(self):
        original = self.app.selected_device.result
        self.app.connectivity.test_connection = Mock(return_value=original)
        self.app.ping_count.set("10")
        self.app.on_test_connection()
        self.settle_worker()
        self.app.connectivity.test_connection.assert_called_once_with(self.app.selected_device, 10)
        self.assertIn("4 requests", self.app.ping_result_subtitle.cget("text"))

    def test_scan_error_keeps_previous_devices(self):
        before = dict(self.app.devices)
        self.app.discovery.detect_network = Mock(side_effect=OSError("Interface unavailable"))
        with patch("ugnay.app.messagebox.showerror") as error:
            self.app.on_scan_network()
            self.settle_worker()
            error.assert_called_once()
        self.assertEqual(self.app.devices, before)
        self.assertIn("Interface unavailable", self.app.status_text.get())

    def test_smaller_window_and_report_preview(self):
        self.app.geometry("1000x720")
        for page in self.app.pages:
            self.app.show_page(page)
            self.app.update()
            self.assertEqual(self.app.winfo_width(), 1000)
        self.assertIn("SAMPLE PREVIEW", self.app.report_output.get("1.0", "end"))
        self.assertEqual(str(self.app.report_output.cget("state")), "disabled")
        self.assertEqual(self.app.report_metrics[2].get(), "5.1 ms")


if __name__ == "__main__":
    unittest.main()
