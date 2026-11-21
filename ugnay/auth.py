"""SQLite accounts and opaque, revocable sessions for the local web app."""

from contextlib import contextmanager
import hashlib
import hmac
from pathlib import Path
import re
import secrets
import sqlite3
import time


class AuthError(ValueError):
    def __init__(self, message, status=400):
        super().__init__(message)
        self.status = status


def password_hash(password):
    salt = secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), 600_000)
    return f"pbkdf2_sha256$600000${salt}${digest.hex()}"


def password_matches(password, encoded):
    try:
        algorithm, rounds, salt, expected = encoded.split("$")
        if algorithm != "pbkdf2_sha256":
            return False
        digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), int(rounds))
        return hmac.compare_digest(digest.hex(), expected)
    except (ValueError, AttributeError):
        return False


def validate_password(password):
    if not isinstance(password, str) or not 12 <= len(password) <= 128:
        raise AuthError("Use a password between 12 and 128 characters.")


class AuthStore:
    def __init__(self, path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as db:
            db.execute("PRAGMA journal_mode=WAL")
            db.executescript(Path(__file__).with_name("schema.sql").read_text(encoding="utf-8"))
        self.dummy_hash = password_hash(secrets.token_urlsafe(24))

    @contextmanager
    def connect(self):
        db = sqlite3.connect(self.path, timeout=10)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA foreign_keys=ON")
        try:
            with db:
                yield db
        finally:
            db.close()

    @staticmethod
    def public_user(row, db):
        permissions = [r[0] for r in db.execute(
            "SELECT permission FROM role_permissions WHERE role=? ORDER BY permission", (row["role"],))]
        return {key: row[key] for key in (
            "id", "username", "email", "role", "active", "created_at", "expires_at"
        )} | {"permissions": permissions}

    def create_user(self, username, email, password, role="user"):
        if not isinstance(username, str) or not re.fullmatch(r"[A-Za-z0-9_.-]{3,32}", username.strip()):
            raise AuthError("Use 3–32 letters, numbers, dots, underscores, or hyphens for your username.")
        if not isinstance(email, str) or len(email) > 254 or not re.fullmatch(r"[^\s@]+@[^\s@]+\.[^\s@]+", email.strip()):
            raise AuthError("Enter a valid email address.")
        if role not in ("admin", "user"):
            raise AuthError("Invalid account role.")
        validate_password(password)
        try:
            with self.connect() as db:
                cursor = db.execute(
                    "INSERT INTO users (username,email,password_hash,role,created_at) VALUES (?,?,?,?,?)",
                    (username.strip(), email.strip().lower(), password_hash(password), role, int(time.time())))
                return self.public_user(db.execute("SELECT * FROM users WHERE id=?", (cursor.lastrowid,)).fetchone(), db)
        except sqlite3.IntegrityError:
            raise AuthError("That username or email is already registered.", 409) from None

    def authenticate(self, identifier, password, guest_only=False):
        if not isinstance(identifier, str) or not isinstance(password, str) or len(identifier) > 254 or len(password) > 128:
            raise AuthError("Incorrect username/email or password.", 401)
        with self.connect() as db:
            row = db.execute("SELECT * FROM users WHERE username=? COLLATE NOCASE OR email=? COLLATE NOCASE",
                             (identifier.strip(), identifier.strip())).fetchone()
            valid = password_matches(password, row["password_hash"] if row and row["password_hash"] else self.dummy_hash)
            if not valid or not row or not row["active"] or (row["expires_at"] and row["expires_at"] <= time.time()) or (guest_only and row["role"] != "guest"):
                raise AuthError("Incorrect username/email or password.", 401)
            return self.public_user(row, db)

    def create_guest(self, username):
        if not isinstance(username, str):
            raise AuthError("Enter a valid guest name.")
        name = username.strip() or "visitor"
        if not re.fullmatch(r"[A-Za-z0-9_.-]{3,24}", name):
            raise AuthError("Use 3–24 letters, numbers, dots, underscores, or hyphens for your guest name.")
        now = int(time.time())
        with self.connect() as db:
            db.execute("DELETE FROM sessions WHERE expires_at<=?", (now,))
            db.execute("DELETE FROM users WHERE role='guest' AND expires_at<=?", (now,))
            cursor = db.execute("INSERT INTO users (username,role,created_at,expires_at) VALUES (?,'guest',?,?)",
                                (f"{name}-{secrets.token_hex(4)}", now, now + 7200))
            return self.public_user(db.execute("SELECT * FROM users WHERE id=?", (cursor.lastrowid,)).fetchone(), db)

    def new_session(self, user, remember=False):
        now = int(time.time())
        lifetime = 7200 if user["role"] == "guest" else (30 * 86400 if remember else 8 * 3600)
        token, csrf = secrets.token_urlsafe(32), secrets.token_urlsafe(32)
        with self.connect() as db:
            db.execute("DELETE FROM sessions WHERE expires_at<=?", (now,))
            db.execute("INSERT INTO sessions VALUES (?,?,?,?,?)", (
                hashlib.sha256(token.encode()).hexdigest(), user["id"], csrf, now, now + lifetime))
        return token, csrf, lifetime

    def session(self, token):
        if not token or len(token) > 128:
            raise AuthError("Please log in to continue.", 401)
        now = int(time.time())
        with self.connect() as db:
            row = db.execute("""SELECT users.*, sessions.csrf_token, sessions.expires_at AS session_expiry
                FROM sessions JOIN users ON users.id=sessions.user_id
                WHERE token_hash=? AND sessions.expires_at>? AND active=1
                AND (users.expires_at IS NULL OR users.expires_at>?)""",
                (hashlib.sha256(token.encode()).hexdigest(), now, now)).fetchone()
            if row is None:
                raise AuthError("Your session has ended. Please log in again.", 401)
            return self.public_user(row, db), row["csrf_token"], row["session_expiry"]

    def logout(self, token):
        with self.connect() as db:
            db.execute("DELETE FROM sessions WHERE token_hash=?", (hashlib.sha256(token.encode()).hexdigest(),))

    def list_users(self):
        with self.connect() as db:
            return [self.public_user(row, db) for row in db.execute(
                "SELECT * FROM users WHERE expires_at IS NULL OR expires_at>? ORDER BY created_at DESC,id DESC", (int(time.time()),))]

    def update_user(self, actor_id, user_id, changes):
        if not changes or set(changes) - {"role", "active", "password"}:
            raise AuthError("Choose a role, account status, or new password.")
        if "role" in changes and changes["role"] not in ("user", "admin", "guest"):
            raise AuthError("Invalid account role.")
        if "active" in changes and type(changes["active"]) is not bool:
            raise AuthError("Active must be true or false.")
        if "password" in changes:
            validate_password(changes["password"])
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT * FROM users WHERE id=?", (user_id,)).fetchone()
            if not row:
                raise AuthError("Account not found.", 404)
            if row["role"] == "guest" and "role" in changes and changes["role"] != "guest":
                raise AuthError("Temporary guests must sign up for a permanent account.")
            if row["role"] != "guest" and changes.get("role") == "guest":
                raise AuthError("Use Disable for a permanent account; guest sessions are temporary.")
            if row["role"] == "guest" and "password" in changes:
                raise AuthError("Guests use temporary password-free sessions.")
            if user_id == actor_id and (changes.get("role", "admin") != "admin" or changes.get("active") is False):
                raise AuthError("You cannot remove your own administrator access.")
            if row["role"] == "admin" and (changes.get("role", "admin") != "admin" or changes.get("active") is False):
                count = db.execute("SELECT COUNT(*) FROM users WHERE role='admin' AND active=1").fetchone()[0]
                if row["active"] and count <= 1:
                    raise AuthError("At least one active administrator is required.")
            for field, value in changes.items():
                column = "password_hash" if field == "password" else field
                db.execute(f"UPDATE users SET {column}=? WHERE id=?", (password_hash(value) if field == "password" else value, user_id))
            db.execute("DELETE FROM sessions WHERE user_id=?", (user_id,))
            return self.public_user(db.execute("SELECT * FROM users WHERE id=?", (user_id,)).fetchone(), db)

    def reset_password(self, identifier, password):
        validate_password(password)
        with self.connect() as db:
            row = db.execute("SELECT id FROM users WHERE (username=? COLLATE NOCASE OR email=? COLLATE NOCASE) AND role!='guest'", (identifier, identifier)).fetchone()
            if not row:
                raise AuthError("Account not found.", 404)
            db.execute("UPDATE users SET password_hash=? WHERE id=?", (password_hash(password), row["id"]))
            db.execute("DELETE FROM sessions WHERE user_id=?", (row["id"],))
