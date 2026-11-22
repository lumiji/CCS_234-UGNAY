"""Loopback-only HTTP host for UGNAY's HTML/CSS/JavaScript interface.

Uses only Python's standard library. This is a local application server, not an
internet deployment server. Every privileged API action checks stored permissions.
"""

import argparse
from collections import defaultdict, deque
import getpass
from http.cookies import SimpleCookie, CookieError
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import hmac
import json
import logging
from pathlib import Path
import re
import threading
import time
from urllib.parse import urlsplit

from .auth import AuthError, AuthStore
from .discovery import DiscoveryService
from .connectivity import ConnectivityService
from .dashboard_store import DashboardStore
from .models import Device


ROOT = Path(__file__).resolve().parent.parent
LOGGER = logging.getLogger(__name__)


class WebServer(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, address, database, discovery=None, connectivity=None):
        self.auth = AuthStore(database)
        self.discovery = discovery if discovery is not None else DiscoveryService()
        self.connectivity = connectivity if connectivity is not None else ConnectivityService()
        self.dashboard = DashboardStore(self.auth)
        self.lock = threading.Lock()
        self.attempts = defaultdict(deque)
        self.network = self.dashboard.snapshot() | {"busy": False, "operation": None, "testing_device": None, "error": None}
        super().__init__(address, Handler)

    def throttle(self, address, identifier):
        now = time.monotonic()
        keys = ((f"ip:{address}", 30), (f"name:{identifier.lower()[:254]}", 10))
        with self.lock:
            for key in list(self.attempts):
                while self.attempts[key] and self.attempts[key][0] <= now - 600:
                    self.attempts[key].popleft()
                if not self.attempts[key]:
                    del self.attempts[key]
            if any(len(self.attempts[key]) >= limit for key, limit in keys):
                raise AuthError("Too many attempts. Please try again in 10 minutes.", 429)
            for key, _ in keys:
                self.attempts[key].append(now)

    def reload_dashboard(self):
        """Caller holds self.lock, so publication and metadata changes stay ordered."""
        self.network = self.network | self.dashboard.snapshot()

    def operation_failed(self, kind, error, actor, device_id=None):
        with self.lock:
            # Always restore controls, even if the database itself caused failure.
            self.network = self.network | {"busy": False, "operation": None, "testing_device": None, "error": str(error)}
            try:
                self.dashboard.activity(kind, f"{'Scan' if kind == 'scan_failed' else 'Ping test'} failed: {error}", actor, device_id)
                self.reload_dashboard()
            except Exception:
                LOGGER.exception("Could not persist the failed network operation")

    def start_scan(self, actor="System"):
        with self.lock:
            if self.network["busy"]:
                raise AuthError("A network operation is already running. Please wait.", 409)
            self.network = self.network | {"busy": True, "operation": "scan", "error": None}

        def scan():
            try:
                network = self.discovery.detect_network()
                result = self.discovery.scan_network(network.subnet)
                with self.lock:
                    self.dashboard.save_scan(result, actor)
                    self.reload_dashboard()
                    self.network = self.network | {"busy": False, "operation": None, "error": None}
            except Exception as error:
                LOGGER.exception("Network discovery failed")
                self.operation_failed("scan_failed", error, actor)
        try:
            threading.Thread(target=scan, name="ugnay-web-discovery", daemon=True).start()
        except RuntimeError:
            with self.lock:
                self.network = self.network | {"busy": False, "operation": None, "error": "Could not start discovery. Please try again."}
            raise AuthError("Could not start discovery. Please try again.", 503) from None

    def start_ping(self, identifier, count, actor):
        if type(count) is not int or count not in (4, 10, 20):
            raise AuthError("Ping count must be 4, 10, or 20.")
        with self.lock:
            if self.network["busy"]:
                raise AuthError("A network operation is already running. Please wait.", 409)
            device = next((device for device in self.network["devices"] if device["id"] == identifier), None)
            if device is None:
                raise AuthError("This device is not in the latest scan. Scan again before testing it.", 409)
            self.network = self.network | {"busy": True, "operation": "ping", "testing_device": identifier, "error": None}

        def ping():
            try:
                result = self.connectivity.test_connection(Device(device["ip_address"], device["hostname"]), count)
                if result.ip_address != device["ip_address"]:
                    raise ValueError("Ping service returned a result for a different device.")
                with self.lock:
                    self.dashboard.save_ping(identifier, result, actor)
                    self.reload_dashboard()
                    self.network = self.network | {"busy": False, "operation": None, "testing_device": None, "error": None}
            except Exception as error:
                LOGGER.exception("Ping test failed")
                self.operation_failed("ping_failed", error, actor, identifier)
        try:
            threading.Thread(target=ping, name="ugnay-web-ping", daemon=True).start()
        except RuntimeError:
            with self.lock:
                self.network = self.network | {"busy": False, "operation": None, "testing_device": None}
            raise AuthError("Could not start the ping test. Please try again.", 503) from None


class Handler(BaseHTTPRequestHandler):
    server_version = "UGNAY"

    def log_message(self, format, *args):
        # Request paths only; credentials, bodies, and cookies are never logged.
        LOGGER.info("%s %s", self.client_address[0], format % args)

    def send(self, status, body, content_type="application/json; charset=utf-8", cookie=None):
        encoded = json.dumps(body).encode() if content_type.startswith("application/json") else body
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(encoded)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("X-Frame-Options", "DENY")
        self.send_header("Referrer-Policy", "same-origin")
        self.send_header("Content-Security-Policy", "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; connect-src 'self'; object-src 'none'; base-uri 'none'; frame-ancestors 'none'; form-action 'self'")
        if cookie:
            self.send_header("Set-Cookie", cookie)
        self.end_headers()
        self.wfile.write(encoded)

    def check_host(self):
        port = self.server.server_port
        if self.headers.get("Host") not in (f"127.0.0.1:{port}", f"localhost:{port}"):
            raise AuthError("This application accepts local requests only.", 403)

    def token(self):
        cookie = SimpleCookie()
        try:
            cookie.load(self.headers.get("Cookie", ""))
            return cookie["ugnay_session"].value if "ugnay_session" in cookie else ""
        except CookieError:
            return ""

    def require(self, permission=None, mutation=False):
        user, csrf, expires = self.server.auth.session(self.token())
        if mutation and not hmac.compare_digest(self.headers.get("X-CSRF-Token", ""), csrf):
            raise AuthError("Your security token has changed. Refresh the page and try again.", 403)
        if permission and permission not in user["permissions"]:
            raise AuthError("Your account does not have permission for this action.", 403)
        return user, csrf, expires

    def body(self):
        try:
            length = int(self.headers.get("Content-Length", "0"))
            if not 0 < length <= 16384:
                raise AuthError("Request is too large or empty.", 413)
            # Consume the bounded body before rejecting headers. Closing a socket
            # with unread request bytes can discard the error response on Windows.
            raw = self.rfile.read(length)
            host = self.headers.get("Host")
            if self.headers.get("Origin") != f"http://{host}":
                raise AuthError("Request origin is not allowed.", 403)
            if self.headers.get("Content-Type", "").split(";")[0].strip() != "application/json":
                raise AuthError("Send an application/json request.", 415)
            value = json.loads(raw)
            if not isinstance(value, dict):
                raise ValueError
            return value
        except AuthError:
            raise
        except (ValueError, UnicodeError):
            raise AuthError("Invalid JSON request.") from None

    def do_GET(self):
        self.dispatch(False)

    def do_POST(self):
        self.dispatch(True)

    def dispatch(self, mutation):
        try:
            self.check_host()
            path = urlsplit(self.path).path
            if mutation:
                self.mutate(path, self.body())
            elif path == "/api/session":
                user, csrf, expires = self.require()
                self.send(200, {"user": user, "csrf_token": csrf, "expires_at": expires})
            elif path == "/api/network":
                self.require("network.view")
                with self.server.lock:
                    current = self.server.network
                    # Basic network access never exposes administrator labels,
                    # trust decisions, activity, topology, or historical reports.
                    state = {key: current[key] for key in (
                        "busy", "operation", "testing_device", "error", "network", "scanned_at", "metrics")}
                    state["devices"] = [{key: device[key] for key in (
                        "id", "ip_address", "hostname", "status", "ping")} for device in current["devices"]]
                self.send(200, state)
            elif path == "/api/admin/dashboard":
                user, _, _ = self.require("dashboard.view")
                if user["role"] != "admin":
                    raise AuthError("Administrator access is required for this dashboard.", 403)
                with self.server.lock:
                    state = self.server.network.copy()
                self.send(200, state)
            elif re.fullmatch(r"/api/admin/devices/\d+", path):
                user, _, _ = self.require("dashboard.view")
                if user["role"] != "admin":
                    raise AuthError("Administrator access is required for device details.", 403)
                self.send(200, {"device": self.server.dashboard.device_detail(int(path.rsplit("/", 1)[1]))})
            elif path == "/api/admin/users":
                self.require("users.manage")
                self.send(200, {"users": self.server.auth.list_users()})
            elif path.startswith("/api/"):
                raise AuthError("Endpoint not found.", 404)
            else:
                self.static(path)
        except AuthError as error:
            self.send(error.status, {"error": str(error)})
        except (BrokenPipeError, ConnectionResetError):
            pass
        except Exception:
            LOGGER.exception("Request failed")
            self.send(500, {"error": "The request could not be completed. Please try again."})

    def static(self, path):
        files = {"/": ("index.html", "text/html"), "/index.html": ("index.html", "text/html"),
                 "/styles.css": ("styles.css", "text/css"), "/app.js": ("app.js", "text/javascript"),
                 "/dashboard.css": ("dashboard.css", "text/css"), "/dashboard.js": ("dashboard.js", "text/javascript")}
        if path in files:
            filename, mime = files[path]
            target = ROOT / "web" / filename
        elif re.fullmatch(r"/assets/[a-zA-Z0-9_.-]+\.(svg|png|jpg|jpeg|webp|ico)", path):
            target = ROOT / "web" / path.lstrip("/")
            mime = {".svg": "image/svg+xml", ".png": "image/png", ".jpg": "image/jpeg",
                    ".jpeg": "image/jpeg", ".webp": "image/webp", ".ico": "image/x-icon"}[target.suffix]
        else:
            raise AuthError("Page not found.", 404)
        if not target.is_file():
            raise AuthError("Asset not found.", 404)
        self.send(200, target.read_bytes(), f"{mime}; charset=utf-8")

    def mutate(self, path, data):
        if path in ("/api/login", "/api/signup", "/api/guest"):
            # Throttle all public account/session creation, including guest sessions.
            identifier = data.get("identifier", data.get("username", ""))
            self.server.throttle(self.client_address[0], str(identifier))
            if path == "/api/signup":
                if data.get("password") != data.get("confirm_password"):
                    raise AuthError("Your passwords do not match.")
                # Public requests can never choose their role, even with an injected role field.
                user = self.server.auth.create_user(data.get("username"), data.get("email"), data.get("password"))
            elif path == "/api/login":
                user = self.server.auth.authenticate(data.get("identifier"), data.get("password"))
            else:
                user = self.server.auth.create_guest(data.get("username", ""))
            if self.token():
                self.server.auth.logout(self.token())
            remember = data.get("remember") is True and user["role"] != "guest"
            token, csrf, lifetime = self.server.auth.new_session(user, remember)
            cookie = f"ugnay_session={token}; Path=/; HttpOnly; SameSite=Strict"
            if remember:
                cookie += f"; Max-Age={lifetime}"
            self.send(200, {"user": user, "csrf_token": csrf, "expires_at": int(time.time()) + lifetime}, cookie=cookie)
        elif path == "/api/logout":
            self.require(mutation=True)
            self.server.auth.logout(self.token())
            self.send(200, {"ok": True}, cookie="ugnay_session=; Path=/; Max-Age=0; HttpOnly; SameSite=Strict")
        elif path == "/api/network/scan":
            actor, _, _ = self.require("network.scan", mutation=True)
            self.server.start_scan(actor["username"])
            self.send(202, {"ok": True})
        elif re.fullmatch(r"/api/devices/\d+/ping", path):
            actor, _, _ = self.require("network.test", mutation=True)
            self.server.start_ping(int(path.split("/")[3]), data.get("count", 4), actor["username"])
            self.send(202, {"ok": True})
        elif re.fullmatch(r"/api/devices/\d+", path):
            actor, _, _ = self.require("devices.manage", mutation=True)
            with self.server.lock:
                device = self.server.dashboard.update_device(int(path.rsplit("/", 1)[1]), data, actor["username"])
                self.server.reload_dashboard()
            self.send(200, {"device": device})
        elif re.fullmatch(r"/api/admin/users/\d+", path):
            actor, _, _ = self.require("users.manage", mutation=True)
            user = self.server.auth.update_user(actor["id"], int(path.rsplit("/", 1)[1]), data)
            self.send(200, {"user": user})
        else:
            raise AuthError("Endpoint not found.", 404)


def main():
    parser = argparse.ArgumentParser(description="UGNAY local web interface")
    parser.add_argument("--desktop", action="store_true", help="Launch the original Tkinter interface")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--database", type=Path, default=ROOT / "data" / "ugnay.sqlite3")
    parser.add_argument("--create-admin", action="store_true", help="Create an administrator interactively")
    parser.add_argument("--reset-password", metavar="USERNAME", help="Reset a local account password interactively")
    args = parser.parse_args()
    if args.desktop:
        from .app import UgnayApp
        UgnayApp(demo=False).mainloop()
        return
    if args.create_admin or args.reset_password:
        auth = AuthStore(args.database)
        try:
            username = input("Administrator username: ").strip() if args.create_admin else args.reset_password
            email = input("Administrator email: ").strip() if args.create_admin else None
            password = getpass.getpass("New password (12–128 characters): ")
            if password != getpass.getpass("Confirm password: "):
                raise AuthError("Passwords do not match.")
            if args.create_admin:
                auth.create_user(username, email, password, role="admin")
            else:
                auth.reset_password(username, password)
            print("Administrator created." if args.create_admin else "Password updated; existing sessions revoked.")
        except AuthError as error:
            parser.exit(1, f"{error}\n")
        return
    if not 1 <= args.port <= 65535:
        parser.error("Port must be between 1 and 65535.")
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    with WebServer(("127.0.0.1", args.port), args.database) as server:
        print(f"UGNAY is running at http://127.0.0.1:{server.server_port}", flush=True)
        print("Press Ctrl+C to stop. Use --create-admin to create an administrator.", flush=True)
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            print("\nUGNAY stopped.")


if __name__ == "__main__":
    main()
