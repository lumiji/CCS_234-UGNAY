"""Dashboard API integration tests. All discovery and ping operations are fake."""

from dataclasses import replace
from datetime import datetime, timedelta, timezone
from http.client import HTTPConnection
import json
from pathlib import Path
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

from ugnay.auth import AuthStore
from ugnay.dashboard_store import DashboardStore
from ugnay.models import Device, DeviceStatus, DiscoveryResult, NetworkInfo, PingReply, PingResult
from ugnay.web_server import WebServer


class Discovery:
    def __init__(self):
        self.network = NetworkInfo("192.0.2.4", "192.0.2.0/24")
        self.devices = (Device("192.0.2.4", "Workstation"), Device("192.0.2.8", "Phone"))
        self.error = None
        self.release = threading.Event()
        self.release.set()
        self.calls = []

    def detect_network(self):
        self.calls.append("detect")
        return self.network

    def scan_network(self, subnet):
        self.calls.append(("scan", subnet))
        self.release.wait(5)
        if self.error:
            raise RuntimeError(self.error)
        return DiscoveryResult(self.network, datetime.now(timezone.utc), self.devices)


class Connectivity:
    def __init__(self):
        self.error = None
        self.all_timeout = False
        self.calls = []
        self.release = threading.Event()
        self.release.set()
        self.timeouts = []

    def test_connection(self, device, count, *, timeout_seconds=None):
        self.calls.append((device.ip_address, count))
        self.timeouts.append(timeout_seconds)
        self.release.wait(5)
        if self.error:
            raise RuntimeError(self.error)
        values = [None] * count if self.all_timeout else [2., 4., None, 6.] * (count // 4) + [2.] * (count % 4)
        received = [value for value in values if value is not None]
        return PingResult(device.ip_address, datetime.now(timezone.utc),
                          tuple(PingReply(i + 1, value) for i, value in enumerate(values)),
                          sum(received) / len(received) if received else None, max(received) if received else None,
                          (count - len(received)) / count * 100,
                          DeviceStatus.PACKET_LOSS if received else DeviceStatus.UNREACHABLE)


class DashboardTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory()
        cls.path = Path(cls.temp.name) / "dashboard.sqlite3"
        cls.auth = AuthStore(cls.path)
        cls.accounts = {role: cls.auth.create_user(f"{role}-account", f"{role}@example.test", "A dashboard test password!", role)
                        for role in ("admin", "user")}
        cls.accounts["guest"] = cls.auth.create_guest("testguest")

    @classmethod
    def tearDownClass(cls):
        cls.temp.cleanup()

    def setUp(self):
        with self.auth.connect() as db:
            for table in ("network_activity", "device_ping_tests", "network_scans", "discovered_devices"):
                db.execute(f"DELETE FROM {table}")
        self.discovery, self.connectivity = Discovery(), Connectivity()
        self.server = WebServer(("127.0.0.1", 0), self.path, self.discovery, self.connectivity)
        self.worker = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.worker.start()

    def tearDown(self):
        self.discovery.release.set()
        self.connectivity.release.set()
        self.idle()
        self.server.shutdown()
        self.server.server_close()
        self.worker.join()

    def request(self, path, data=None, role="admin", csrf=True):
        token, security_token, _ = self.auth.new_session(self.accounts[role])
        client = HTTPConnection("127.0.0.1", self.server.server_port, timeout=5)
        headers = {"Origin": f"http://127.0.0.1:{self.server.server_port}", "Content-Type": "application/json", "Cookie": f"ugnay_session={token}"}
        if csrf:
            headers["X-CSRF-Token"] = security_token
        client.request("POST" if data is not None else "GET", path, json.dumps(data) if data is not None else None, headers)
        response = client.getresponse()
        status, value = response.status, json.loads(response.read())
        client.close()
        return status, value

    def idle(self):
        deadline = time.monotonic() + 6
        while self.server.network["busy"] and time.monotonic() < deadline:
            time.sleep(.01)
        self.assertFalse(self.server.network["busy"], "Background operation failed to finish")

    def scan(self):
        status, value = self.request("/api/network/scan", {}, role="user")
        self.assertEqual(status, 202, value)
        self.idle()
        return self.request("/api/admin/dashboard")[1]

    def test_scan_calls_same_service_and_publishes_subnet_membership(self):
        result = self.scan()
        self.assertEqual(self.discovery.calls, ["detect", ("scan", "192.0.2.0/24")])
        self.assertEqual(len(result["devices"]), 2)
        self.assertIsNone(result["metrics"]["average_latency_ms"])
        self.assertIsNone(result["metrics"]["packet_loss_percent"])
        self.assertFalse(result["topology"]["physical_links_known"])
        for device in result["devices"]:
            self.assertEqual(device["trust"], "review")
            self.assertEqual(device["parent_id"], "subnet:192.0.2.0/24")
        self.assertEqual(result["activities"][0]["kind"], "scan_completed")

    def test_admin_labels_and_trust_survive_rescan_and_reopen(self):
        device = self.scan()["devices"][0]
        path = f"/api/devices/{device['id']}"
        status, updated = self.request(path, {"label": "Jessie’s PC", "trust": "trusted"})
        self.assertEqual(status, 200)
        self.assertEqual(updated["device"]["name"], "Jessie’s PC")
        again = self.scan()["devices"][0]
        self.assertEqual(again["id"], device["id"])
        self.assertEqual(again["trust"], "trusted")
        reopened = DashboardStore(AuthStore(self.path)).snapshot()
        self.assertEqual(reopened["devices"][0]["name"], "Jessie’s PC")
        self.assertEqual(len(reopened["scan_history"]), 2)

    def test_trust_is_scoped_to_subnet(self):
        first = self.scan()["devices"][0]
        self.request(f"/api/devices/{first['id']}", {"trust": "trusted"})
        self.discovery.network = NetworkInfo("192.0.2.4", "192.0.2.0/25")
        second = self.scan()["devices"][0]
        self.assertNotEqual(first["id"], second["id"])
        self.assertEqual(second["trust"], "review")

    def test_guest_and_user_cannot_change_device_recognition(self):
        device = self.scan()["devices"][0]
        for role in ("guest", "user"):
            self.assertEqual(self.request(f"/api/devices/{device['id']}", {"trust": "trusted"}, role)[0], 403)
        self.assertEqual(self.request(f"/api/devices/{device['id']}/ping", {"count": 4}, "guest")[0], 403)
        self.assertEqual(self.request(f"/api/devices/{device['id']}", {"trust": "trusted"}, csrf=False)[0], 403)

    def test_measured_ping_results_and_metrics(self):
        device = self.scan()["devices"][0]
        self.assertEqual(self.request(f"/api/devices/{device['id']}/ping", {"count": 4}, "user")[0], 202)
        self.idle()
        snapshot = self.request("/api/admin/dashboard")[1]
        self.assertEqual(self.connectivity.calls, [(device["ip_address"], 4)])
        self.assertEqual(snapshot["metrics"]["average_latency_ms"], 4.)
        self.assertEqual(snapshot["metrics"]["packet_loss_percent"], 25.)
        self.assertEqual(snapshot["metrics"]["tested_devices"], 1)
        self.assertEqual(snapshot["devices"][0]["ping"]["replies"][2]["latency_ms"], None)
        self.assertEqual(snapshot["activities"][0]["kind"], "ping_completed")

    def test_all_ping_timeouts_have_no_latency_and_full_loss(self):
        device = self.scan()["devices"][0]
        self.connectivity.all_timeout = True
        self.request(f"/api/devices/{device['id']}/ping", {"count": 4})
        self.idle()
        snapshot = self.request("/api/admin/dashboard")[1]
        self.assertIsNone(snapshot["metrics"]["average_latency_ms"])
        self.assertEqual(snapshot["metrics"]["packet_loss_percent"], 100.)

    def test_selected_ping_timeout_reaches_connectivity_service(self):
        device = self.scan()["devices"][0]
        self.assertEqual(self.request(f"/api/devices/{device['id']}/ping", {"count": 4, "timeout_seconds": 2})[0], 202)
        self.idle()
        self.assertEqual(self.connectivity.timeouts, [2])
        self.assertEqual(self.connectivity.calls, [(device["ip_address"], 4)])

    def test_invalid_ping_timeout_is_rejected_before_operation_starts(self):
        device = self.scan()["devices"][0]
        for timeout in (0, -1, True, "2", 2.0, 3, 99999):
            with self.subTest(timeout=timeout):
                self.assertEqual(self.request(f"/api/devices/{device['id']}/ping", {"count": 4, "timeout_seconds": timeout})[0], 400)
                self.assertFalse(self.request("/api/admin/dashboard")[1]["busy"])
        self.assertFalse(self.connectivity.calls)

    def test_invalid_test_targets_counts_and_metadata_rejected(self):
        device = self.scan()["devices"][0]
        for count in (0, -1, "4", True, 1000):
            self.assertEqual(self.request(f"/api/devices/{device['id']}/ping", {"count": count})[0], 400)
        self.assertEqual(self.request("/api/devices/99999/ping", {"count": 4})[0], 409)
        for changes in ({"trust": "admin"}, {"label": "x" * 65}, {"label": "line\nbreak"}, {"ip_address": "8.8.8.8"}):
            self.assertEqual(self.request(f"/api/devices/{device['id']}", changes)[0], 400)

    def test_duplicate_operations_rejected_without_blocking_reads(self):
        self.discovery.release.clear()
        self.assertEqual(self.request("/api/network/scan", {})[0], 202)
        self.assertEqual(self.request("/api/network/scan", {})[0], 409)
        self.assertTrue(self.request("/api/admin/dashboard")[1]["busy"])
        self.discovery.release.set()

    def test_failed_scan_preserves_previous_result(self):
        before = self.scan()
        self.discovery.error = "Adapter unavailable"
        with self.assertLogs("ugnay.web_server", level="ERROR"):
            self.scan()
        after = self.request("/api/admin/dashboard")[1]
        self.assertEqual(before["devices"], after["devices"])
        self.assertEqual(before["scanned_at"], after["scanned_at"])
        self.assertEqual(after["error"], "Adapter unavailable")
        self.assertEqual(after["activities"][0]["kind"], "scan_failed")

    def test_empty_scan_clears_latest_devices_and_metrics(self):
        self.scan()
        self.discovery.devices = ()
        snapshot = self.scan()
        self.assertEqual(snapshot["devices"], [])
        self.assertIsNone(snapshot["metrics"]["packet_loss_percent"])
        self.assertTrue(any(activity["kind"] == "device_absent" for activity in snapshot["activities"]))

    def test_failed_ping_does_not_claim_successful_measurements(self):
        device = self.scan()["devices"][0]
        self.connectivity.error = "Ping utility unavailable"
        with self.assertLogs("ugnay.web_server", level="ERROR"):
            self.request(f"/api/devices/{device['id']}/ping", {"count": 4})
            self.idle()
        snapshot = self.request("/api/admin/dashboard")[1]
        self.assertEqual(snapshot["error"], "Ping utility unavailable")
        self.assertIsNone(snapshot["devices"][0]["ping"])
        self.assertEqual(snapshot["activities"][0]["kind"], "ping_failed")

    def test_ping_busy_state_prevents_a_simultaneous_scan(self):
        device = self.scan()["devices"][0]
        self.connectivity.release.clear()
        self.assertEqual(self.request(f"/api/devices/{device['id']}/ping", {"count": 4})[0], 202)
        self.assertEqual(self.request("/api/network/scan", {})[0], 409)
        self.assertEqual(self.request("/api/admin/dashboard")[1]["testing_device"], device["id"])
        self.connectivity.release.set()

    def test_database_failure_always_restores_busy_controls(self):
        before = self.scan()
        with patch.object(self.server.dashboard, "save_scan", side_effect=OSError("Database unavailable")), \
             patch.object(self.server.dashboard, "activity", side_effect=OSError("Database unavailable")), \
             self.assertLogs("ugnay.web_server", level="ERROR"):
            self.request("/api/network/scan", {})
            self.idle()
        after = self.request("/api/admin/dashboard")[1]
        self.assertFalse(after["busy"])
        self.assertEqual(after["devices"], before["devices"])
        self.assertEqual(after["error"], "Database unavailable")

    def test_dashboard_api_is_admin_only(self):
        self.scan()
        for role in ("guest", "user"):
            self.assertEqual(self.request("/api/admin/dashboard", role=role)[0], 403)
        status, dashboard = self.request("/api/admin/dashboard")
        self.assertEqual(status, 200)
        self.assertIn("activities", dashboard)
        self.assertIn("topology", dashboard)
        self.assertIn("trust", dashboard["devices"][0])

    def test_device_details_include_only_selected_device_history(self):
        first, second = self.scan()["devices"]
        self.request(f"/api/devices/{first['id']}", {"label": "Selected workstation"})
        self.request(f"/api/devices/{second['id']}", {"trust": "trusted"})
        self.request(f"/api/devices/{first['id']}/ping", {"count": 4})
        self.idle()
        # Global feed retention must not hide this device's own recent history.
        for index in range(55):
            self.server.dashboard.activity("unrelated", f"Other activity {index}", "Test", second["id"])
        status, response = self.request(f"/api/admin/devices/{first['id']}")
        self.assertEqual(status, 200)
        device = response["device"]
        self.assertEqual(device["label"], "Selected workstation")
        self.assertTrue(device["activities"])
        self.assertTrue(all(activity["device_id"] == first["id"] for activity in device["activities"]))
        self.assertEqual({activity["kind"] for activity in device["activities"]}, {"device_new", "device_label", "ping_completed"})
        self.assertEqual(len(device["ping_history"]), 1)
        self.assertIsNone(device["ping_history"][0]["replies"][2]["latency_ms"])

    def test_device_detail_is_admin_only_and_rejects_unknown_devices(self):
        device = self.scan()["devices"][0]
        for role in ("guest", "user"):
            self.assertEqual(self.request(f"/api/admin/devices/{device['id']}", role=role)[0], 403)
        self.assertEqual(self.request("/api/admin/devices/99999")[0], 404)

    def test_device_detail_bounds_and_orders_history(self):
        device = self.scan()["devices"][0]
        result = self.connectivity.test_connection(Device(device["ip_address"]), 4)
        for _ in range(5):
            self.server.dashboard.save_ping(device["id"], result, "Test")
        for index in range(25):
            self.server.dashboard.activity("device_note", f"Device event {index}", "Test", device["id"])
        detail = self.request(f"/api/admin/devices/{device['id']}")[1]["device"]
        self.assertEqual(len(detail["activities"]), 20)
        self.assertEqual(detail["activities"][0]["message"], "Device event 24")
        self.assertEqual(len(detail["ping_history"]), 3)
        self.assertEqual([test["id"] for test in detail["ping_history"]], sorted((test["id"] for test in detail["ping_history"]), reverse=True))

    def test_scan_report_uses_historical_membership_and_scan_test_interval(self):
        start = datetime(2026, 11, 22, 6, tzinfo=timezone.utc)
        first_scan = DiscoveryResult(network=self.discovery.network, devices=self.discovery.devices, scanned_at=start)
        self.server.dashboard.save_scan(first_scan, "Test")
        snapshot = self.server.dashboard.snapshot()
        first_id = snapshot["scan_history"][0]["id"]
        first, second = snapshot["devices"]
        ping = self.connectivity.test_connection(Device(first["ip_address"]), 4)
        # Before the scan is excluded; the start boundary is inclusive, even
        # when an equivalent timestamp uses a different UTC offset.
        for at in (start - timedelta(seconds=1), start.astimezone(timezone(timedelta(hours=8))), start + timedelta(minutes=59)):
            self.server.dashboard.save_ping(first["id"], replace(ping, tested_at=at), "Test")
        self.server.dashboard.save_scan(replace(first_scan, devices=(self.discovery.devices[1],), scanned_at=start + timedelta(hours=1)), "Test")
        second_id = self.server.dashboard.snapshot()["scan_history"][0]["id"]
        self.server.dashboard.save_ping(first["id"], replace(ping, tested_at=start + timedelta(hours=1)), "Test")
        self.server.dashboard.save_ping(second["id"], replace(ping, tested_at=start + timedelta(hours=1, minutes=1)), "Test")
        report = self.request(f"/api/admin/reports/{first_id}")[1]["report"]
        self.assertEqual({item["id"] for item in report["devices"]}, {first["id"], second["id"]})
        self.assertEqual(len(report["devices"][0]["ping_history"]), 2)
        self.assertFalse(report["devices"][1]["ping_history"])
        self.assertIsNotNone(report["ended_at"])
        latest = self.request(f"/api/admin/reports/{second_id}")[1]["report"]
        self.assertEqual([item["id"] for item in latest["devices"]], [second["id"]])
        self.assertEqual(len(latest["devices"][0]["ping_history"]), 1)
        self.assertIsNone(latest["ended_at"])

    def test_scan_report_includes_history_beyond_global_dashboard_feed(self):
        snapshot = self.scan()
        device = snapshot["devices"][0]
        ping = self.connectivity.test_connection(Device(device["ip_address"]), 4)
        for _ in range(35):
            self.server.dashboard.save_ping(device["id"], ping, "Test")
        report = self.request(f"/api/admin/reports/{snapshot['scan_history'][0]['id']}")[1]["report"]
        history = report["devices"][0]["ping_history"]
        self.assertEqual(len(history), 35)
        self.assertEqual([test["id"] for test in history], sorted((test["id"] for test in history), reverse=True))

    def test_scan_report_is_admin_only_and_rejects_unknown_scans(self):
        scan_id = self.scan()["scan_history"][0]["id"]
        for role in ("guest", "user"):
            self.assertEqual(self.request(f"/api/admin/reports/{scan_id}", role=role)[0], 403)
        self.assertEqual(self.request("/api/admin/reports/99999")[0], 404)

    def test_empty_scan_report_has_no_invented_results(self):
        self.discovery.devices = ()
        scan_id = self.scan()["scan_history"][0]["id"]
        status, result = self.request(f"/api/admin/reports/{scan_id}")
        self.assertEqual(status, 200)
        self.assertEqual(result["report"]["devices"], [])

    def test_basic_network_view_excludes_admin_data(self):
        device = self.scan()["devices"][0]
        self.request(f"/api/devices/{device['id']}", {"label": "Private admin label", "trust": "flagged"})
        for role in ("guest", "user"):
            status, overview = self.request("/api/network", role=role)
            self.assertEqual(status, 200)
            for private in ("activities", "topology", "scan_history", "test_history"):
                self.assertNotIn(private, overview)
            for private in ("trust", "label", "first_seen", "last_seen", "parent_id"):
                self.assertNotIn(private, overview["devices"][0])
            self.assertNotIn("Private admin label", json.dumps(overview))
            self.assertEqual(overview["devices"][0]["ip_address"], device["ip_address"])

    def test_dashboard_also_checks_admin_role(self):
        with self.auth.connect() as db:
            db.execute("INSERT INTO role_permissions VALUES ('user','dashboard.view')")
        try:
            self.assertEqual(self.request("/api/admin/dashboard", role="user")[0], 403)
            self.assertEqual(self.request("/api/admin/devices/1", role="user")[0], 403)
            self.assertEqual(self.request("/api/admin/reports/1", role="user")[0], 403)
        finally:
            with self.auth.connect() as db:
                db.execute("DELETE FROM role_permissions WHERE role='user' AND permission='dashboard.view'")


if __name__ == "__main__":
    unittest.main()
