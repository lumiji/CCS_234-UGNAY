"""Exercise authentication and authorization through a real local HTTP server.

Discovery is a fake service: these tests never probe the local network.
"""

from datetime import datetime, timezone
import hashlib
from http.client import HTTPConnection
import json
from pathlib import Path
import tempfile
import threading
import time
import unittest

from ugnay.auth import AuthError, AuthStore, password_matches
from ugnay.models import Device, DiscoveryResult, NetworkInfo
from ugnay.web_server import WebServer


PASSWORD = "A memorable test password!"


class FakeDiscovery:
    def detect_network(self):
        return NetworkInfo("192.0.2.4", "192.0.2.0/24")

    def scan_network(self, subnet):
        return DiscoveryResult(self.detect_network(), datetime.now(timezone.utc), (Device("192.0.2.4", "test-host"),))


class WebAuthTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temporary = tempfile.TemporaryDirectory()
        cls.path = Path(cls.temporary.name) / "test.sqlite3"
        cls.server = WebServer(("127.0.0.1", 0), cls.path, discovery=FakeDiscovery())
        cls.worker = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.worker.start()
        cls.auth = cls.server.auth
        cls.admin = cls.auth.create_user("administrator", "admin@example.test", PASSWORD, "admin")
        cls.user = cls.auth.create_user("regular", "user@example.test", PASSWORD)

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.worker.join()
        cls.temporary.cleanup()

    def setUp(self):
        self.cookie, self.csrf = "", ""
        with self.server.lock:
            self.server.attempts.clear()

    def request(self, path, data=None, extra=None):
        connection = HTTPConnection("127.0.0.1", self.server.server_port, timeout=10)
        headers = {"Origin": f"http://127.0.0.1:{self.server.server_port}", "Content-Type": "application/json"}
        if self.cookie:
            headers["Cookie"] = self.cookie
        if self.csrf:
            headers["X-CSRF-Token"] = self.csrf
        headers.update(extra or {})
        connection.request("POST" if data is not None else "GET", path, json.dumps(data) if data is not None else None, headers)
        response = connection.getresponse()
        body = response.read()
        result = json.loads(body) if "application/json" in response.getheader("Content-Type", "") else body.decode()
        cookie = response.getheader("Set-Cookie")
        if cookie:
            self.cookie = cookie.split(";", 1)[0]
        if isinstance(result, dict) and "csrf_token" in result:
            self.csrf = result["csrf_token"]
        status, response_headers = response.status, dict(response.getheaders())
        connection.close()
        return status, result, response_headers

    def login(self, username="regular", remember=False):
        status, result, headers = self.request("/api/login", {"identifier": username, "password": PASSWORD, "remember": remember})
        self.assertEqual(status, 200, result)
        return result, headers

    def test_public_assets_and_private_files(self):
        for path in ("/", "/styles.css", "/app.js", "/assets/logo-placeholder.svg"):
            self.assertEqual(self.request(path)[0], 200)
        for path in ("/data/ugnay.sqlite3", "/../ugnay/auth.py", "/assets/../schema.sql"):
            self.assertEqual(self.request(path)[0], 404)

    def test_anonymous_access_denied(self):
        for path in ("/api/session", "/api/network", "/api/admin/users"):
            self.assertEqual(self.request(path)[0], 401)
        self.assertEqual(self.request("/api/network/scan", {})[0], 401)

    def test_signup_cannot_assign_admin_role(self):
        status, result, _ = self.request("/api/signup", {"username": "newperson", "email": "new@example.test", "password": PASSWORD, "confirm_password": PASSWORD, "role": "admin"})
        self.assertEqual(status, 200)
        self.assertEqual(result["user"]["role"], "user")
        self.assertEqual(self.request("/api/admin/users")[0], 403)

    def test_signup_validation_and_duplicates(self):
        base = {"username": "regular", "email": "user@example.test", "password": PASSWORD, "confirm_password": PASSWORD}
        self.assertEqual(self.request("/api/signup", base)[0], 409)
        for changes in ({"password": "short", "confirm_password": "short"}, {"confirm_password": "different"}, {"email": "invalid"}, {"username": "<script>"}):
            self.assertEqual(self.request("/api/signup", base | changes)[0], 400)

    def test_login_case_insensitive_email_and_cookie_policy(self):
        result, headers = self.login("USER@EXAMPLE.TEST", remember=True)
        self.assertEqual(result["user"]["id"], self.user["id"])
        for flag in ("HttpOnly", "SameSite=Strict", "Max-Age=2592000"):
            self.assertIn(flag, headers["Set-Cookie"])
        self.assertNotIn("password_hash", result["user"])
        self.assertEqual(self.request("/api/session")[0], 200)

    def test_invalid_login_and_sql_injection(self):
        for identifier in ("regular", "' OR 1=1 --", "missing"):
            status, result, _ = self.request("/api/login", {"identifier": identifier, "password": "wrong"})
            self.assertEqual(status, 401)
            self.assertEqual(result["error"], "Incorrect username/email or password.")

    def test_session_cookie_without_remember_is_browser_session(self):
        _, headers = self.login()
        self.assertNotIn("Max-Age", headers["Set-Cookie"])

    def test_session_tokens_and_passwords_are_hashed(self):
        self.login()
        raw_token = self.cookie.split("=", 1)[1]
        with self.auth.connect() as db:
            row = db.execute("SELECT password_hash FROM users WHERE id=?", (self.user["id"],)).fetchone()
            self.assertNotEqual(row[0], PASSWORD)
            self.assertTrue(password_matches(PASSWORD, row[0]))
            self.assertIsNone(db.execute("SELECT * FROM sessions WHERE token_hash=?", (raw_token,)).fetchone())
            self.assertIsNotNone(db.execute("SELECT * FROM sessions WHERE token_hash=?", (hashlib.sha256(raw_token.encode()).hexdigest(),)).fetchone())

    def test_guest_can_view_but_cannot_scan_or_manage(self):
        status, result, _ = self.request("/api/guest", {"username": "visitor", "role": "admin", "remember": True})
        self.assertEqual(status, 200)
        self.assertEqual(result["user"]["role"], "guest")
        self.assertEqual(result["user"]["permissions"], ["network.view"])
        self.assertLessEqual(result["expires_at"] - time.time(), 7200)
        self.assertEqual(self.request("/api/network")[0], 200)
        self.assertEqual(self.request("/api/network/scan", {})[0], 403)
        self.assertEqual(self.request("/api/admin/users")[0], 403)
        self.assertEqual(self.request(f"/api/admin/users/{self.user['id']}", {"role": "admin"})[0], 403)

    def test_guest_expiry_and_cleanup(self):
        guest = self.auth.create_guest("temporary")
        token, _, _ = self.auth.new_session(guest)
        with self.auth.connect() as db:
            db.execute("UPDATE users SET expires_at=1 WHERE id=?", (guest["id"],))
        with self.assertRaises(AuthError):
            self.auth.session(token)
        self.auth.create_guest("cleanup")
        with self.auth.connect() as db:
            self.assertIsNone(db.execute("SELECT id FROM users WHERE id=?", (guest["id"],)).fetchone())

    def test_csrf_and_origin_checks(self):
        self.login()
        self.assertEqual(self.request("/api/logout", {}, {"X-CSRF-Token": "incorrect"})[0], 403)
        self.assertEqual(self.request("/api/logout", {}, {"Origin": "https://untrusted.test"})[0], 403)
        self.assertEqual(self.request("/api/login", {}, {"Origin": "null"})[0], 403)
        self.assertEqual(self.request("/api/session", extra={"Host": "untrusted.test"})[0], 403)

    def test_logout_revokes_session(self):
        self.login()
        cookie = self.cookie
        self.assertEqual(self.request("/api/logout", {})[0], 200)
        self.cookie = cookie
        self.assertEqual(self.request("/api/session")[0], 401)

    def test_session_expiry(self):
        self.login()
        token = self.cookie.split("=", 1)[1]
        with self.auth.connect() as db:
            db.execute("UPDATE sessions SET expires_at=1 WHERE token_hash=?", (hashlib.sha256(token.encode()).hexdigest(),))
        self.assertEqual(self.request("/api/session")[0], 401)

    def test_user_scan_reuses_discovery_service(self):
        self.login()
        self.assertEqual(self.request("/api/admin/users")[0], 403)
        self.assertEqual(self.request("/api/network/scan", {})[0], 202)
        deadline = time.monotonic() + 3
        while time.monotonic() < deadline:
            _, network, _ = self.request("/api/network")
            if not network["busy"]:
                break
            time.sleep(.01)
        self.assertEqual(network["devices"][0]["ip_address"], "192.0.2.4")
        self.assertIsNone(network["error"])

    def test_admin_account_changes_revoke_access(self):
        target = self.auth.create_user("managed", "managed@example.test", PASSWORD)
        token, _, _ = self.auth.new_session(target)
        self.login("administrator")
        self.assertEqual(self.request("/api/admin/users")[0], 200)
        self.assertEqual(self.request(f"/api/admin/users/{target['id']}", {"role": "admin"})[0], 200)
        with self.assertRaises(AuthError):
            self.auth.session(token)
        self.assertEqual(self.request(f"/api/admin/users/{target['id']}", {"active": False})[0], 200)
        with self.assertRaises(AuthError):
            self.auth.authenticate("managed", PASSWORD)

    def test_admin_cannot_remove_own_access(self):
        self.login("administrator")
        path = f"/api/admin/users/{self.admin['id']}"
        self.assertEqual(self.request(path, {"role": "user"})[0], 400)
        self.assertEqual(self.request(path, {"active": False})[0], 400)

    def test_admin_password_reset(self):
        target = self.auth.create_user("resetme", "reset@example.test", PASSWORD)
        token, _, _ = self.auth.new_session(target)
        self.login("administrator")
        new_password = "A different strong password!"
        self.assertEqual(self.request(f"/api/admin/users/{target['id']}", {"password": new_password})[0], 200)
        with self.assertRaises(AuthError):
            self.auth.session(token)
        with self.assertRaises(AuthError):
            self.auth.authenticate("resetme", PASSWORD)
        self.assertEqual(self.auth.authenticate("resetme", new_password)["id"], target["id"])

    def test_rate_limit(self):
        with self.server.lock:
            self.server.attempts["name:regular"].extend([time.monotonic()] * 10)
        self.assertEqual(self.request("/api/login", {"identifier": "regular", "password": PASSWORD})[0], 429)

    def test_database_survives_reopening(self):
        reopened = AuthStore(self.path)
        self.assertEqual(reopened.authenticate("regular", PASSWORD)["id"], self.user["id"])


if __name__ == "__main__":
    unittest.main()
