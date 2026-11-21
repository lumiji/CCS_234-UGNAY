"""Persistent discovery snapshots, administrator trust decisions, and measurements.

Device identity is scoped to the scanned subnet and IP. ICMP does not establish
hardware identity or physical topology; trust here is an administrator label.
"""

from datetime import datetime, timezone
import json

from .auth import AuthError


def timestamp(value=None):
    value = value or datetime.now(timezone.utc)
    return value.astimezone().isoformat()


class DashboardStore:
    def __init__(self, auth):
        self.auth = auth

    @staticmethod
    def _activity(db, kind, message, actor=None, device_id=None):
        db.execute("INSERT INTO network_activity (at,kind,message,actor,device_id) VALUES (?,?,?,?,?)",
                   (timestamp(), kind, message, actor, device_id))
        db.execute("DELETE FROM network_activity WHERE id NOT IN (SELECT id FROM network_activity ORDER BY id DESC LIMIT 1000)")

    def activity(self, kind, message, actor=None, device_id=None):
        with self.auth.connect() as db:
            self._activity(db, kind, message, actor, device_id)

    def save_scan(self, result, actor):
        at = timestamp(result.scanned_at)
        subnet = result.network.subnet
        with self.auth.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            previous = db.execute("SELECT snapshot FROM network_scans WHERE subnet=? ORDER BY id DESC LIMIT 1", (subnet,)).fetchone()
            previous_ids = set(json.loads(previous[0])["device_ids"]) if previous else set()
            device_ids = []
            for device in result.devices:
                existing = db.execute("SELECT id FROM discovered_devices WHERE subnet=? AND ip_address=?", (subnet, device.ip_address)).fetchone()
                db.execute("""INSERT INTO discovered_devices (subnet,ip_address,hostname,first_seen,last_seen)
                    VALUES (?,?,?,?,?) ON CONFLICT(subnet,ip_address) DO UPDATE SET hostname=excluded.hostname,last_seen=excluded.last_seen""",
                    (subnet, device.ip_address, device.hostname, at, timestamp(device.last_seen) if device.last_seen else at))
                identifier = db.execute("SELECT id FROM discovered_devices WHERE subnet=? AND ip_address=?", (subnet, device.ip_address)).fetchone()[0]
                device_ids.append(identifier)
                if existing is None:
                    self._activity(db, "device_new", f"New device detected: {device.hostname or device.ip_address}", actor, identifier)
                elif identifier not in previous_ids:
                    self._activity(db, "device_returned", f"Device responded again: {device.hostname or device.ip_address}", actor, identifier)
            for identifier in previous_ids - set(device_ids):
                row = db.execute("SELECT label,hostname,ip_address FROM discovered_devices WHERE id=?", (identifier,)).fetchone()
                self._activity(db, "device_absent", f"No longer responding in scan: {row['label'] or row['hostname'] or row['ip_address']}", actor, identifier)
            snapshot = {"network": {"local_ip": result.network.local_ip, "subnet": subnet}, "device_ids": device_ids, "scanned_at": at}
            db.execute("INSERT INTO network_scans (scanned_at,subnet,snapshot) VALUES (?,?,?)", (at, subnet, json.dumps(snapshot)))
            self._activity(db, "scan_completed", f"Scan completed · {len(device_ids)} responding devices", actor)
            db.execute("DELETE FROM network_scans WHERE id NOT IN (SELECT id FROM network_scans ORDER BY id DESC LIMIT 100)")

    @staticmethod
    def _device(db, row):
        device = dict(row)
        latest = db.execute("SELECT result FROM device_ping_tests WHERE device_id=? ORDER BY id DESC LIMIT 1", (device["id"],)).fetchone()
        device["ping"] = json.loads(latest[0]) if latest else None
        device["name"] = device["label"] or device["hostname"] or "Unnamed device"
        device["status"] = device["ping"]["status"] if latest else "Not tested"
        device["parent_id"] = f"subnet:{device['subnet']}"
        return device

    def snapshot(self):
        with self.auth.connect() as db:
            scan = db.execute("SELECT snapshot FROM network_scans ORDER BY id DESC LIMIT 1").fetchone()
            saved = json.loads(scan[0]) if scan else {"network": None, "device_ids": [], "scanned_at": None}
            devices = []
            for identifier in saved["device_ids"]:
                row = db.execute("SELECT * FROM discovered_devices WHERE id=?", (identifier,)).fetchone()
                if row:
                    devices.append(self._device(db, row))
            activity = [dict(row) for row in db.execute("SELECT * FROM network_activity ORDER BY id DESC LIMIT 50")]
            history = []
            for row in db.execute("SELECT id,scanned_at,subnet,snapshot FROM network_scans ORDER BY id DESC LIMIT 30"):
                history.append({"id": row["id"], "scanned_at": row["scanned_at"], "subnet": row["subnet"],
                                "device_count": len(json.loads(row["snapshot"])["device_ids"])})
            tests = [{"id": row["id"], "device_id": row["device_id"], "name": row["label"] or row["hostname"] or row["ip_address"],
                      "ip_address": row["ip_address"], **json.loads(row["result"])} for row in db.execute(
                """SELECT p.*,d.label,d.hostname,d.ip_address FROM device_ping_tests p
                JOIN discovered_devices d ON p.device_id=d.id ORDER BY p.id DESC LIMIT 30""")]
        replies = [reply for device in devices if device["ping"] for reply in device["ping"]["replies"]]
        responded = [reply["latency_ms"] for reply in replies if reply["latency_ms"] is not None]
        return {"network": saved["network"], "scanned_at": saved["scanned_at"], "devices": devices,
                "topology": {"type": "subnet_membership", "physical_links_known": False},
                "metrics": {"average_latency_ms": sum(responded) / len(responded) if responded else None,
                            "packet_loss_percent": (len(replies) - len(responded)) / len(replies) * 100 if replies else None,
                            "tested_devices": sum(device["ping"] is not None for device in devices)},
                "activities": activity, "scan_history": history, "test_history": tests}

    def get_device(self, identifier):
        with self.auth.connect() as db:
            row = db.execute("SELECT * FROM discovered_devices WHERE id=?", (identifier,)).fetchone()
            if not row:
                raise AuthError("Device not found. Run a discovery scan first.", 404)
            return self._device(db, row)

    def update_device(self, identifier, changes, actor):
        if not changes or set(changes) - {"label", "trust"}:
            raise AuthError("Choose a device label or trust status.")
        if "label" in changes and (not isinstance(changes["label"], str) or len(changes["label"].strip()) > 64
                                   or any(ord(char) < 32 for char in changes["label"])):
            raise AuthError("Device labels must be at most 64 characters without control characters.")
        if "trust" in changes and changes["trust"] not in ("trusted", "review", "flagged"):
            raise AuthError("Trust must be trusted, review, or flagged.")
        with self.auth.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT * FROM discovered_devices WHERE id=?", (identifier,)).fetchone()
            if not row:
                raise AuthError("Device not found.", 404)
            for field, value in changes.items():
                value = value.strip() if field == "label" else value
                if value == row[field]:
                    continue
                db.execute(f"UPDATE discovered_devices SET {field}=? WHERE id=?", (value, identifier))
                name = row["label"] or row["hostname"] or row["ip_address"]
                description = f"Device label updated: {value or row['ip_address']}" if field == "label" else f"{name} marked {value}"
                self._activity(db, f"device_{field}", description, actor, identifier)
        return self.get_device(identifier)

    def save_ping(self, identifier, result, actor):
        value = {"tested_at": timestamp(result.tested_at), "status": result.status.value,
                 "average_latency_ms": result.average_latency_ms, "maximum_latency_ms": result.maximum_latency_ms,
                 "packet_loss_percent": result.packet_loss_percent,
                 "replies": [{"sequence": reply.sequence, "latency_ms": reply.latency_ms} for reply in result.replies]}
        with self.auth.connect() as db:
            db.execute("INSERT INTO device_ping_tests (device_id,tested_at,result) VALUES (?,?,?)", (identifier, value["tested_at"], json.dumps(value)))
            self._activity(db, "ping_completed", f"Ping test completed · {result.ip_address} · {result.packet_loss_percent:g}% loss", actor, identifier)
            db.execute("DELETE FROM device_ping_tests WHERE id NOT IN (SELECT id FROM device_ping_tests ORDER BY id DESC LIMIT 1000)")
