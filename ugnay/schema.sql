PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS roles (
    name TEXT PRIMARY KEY CHECK (name IN ('admin', 'user', 'guest')),
    description TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS role_permissions (
    role TEXT NOT NULL REFERENCES roles(name),
    permission TEXT NOT NULL,
    PRIMARY KEY (role, permission)
);
CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    username TEXT NOT NULL COLLATE NOCASE UNIQUE,
    email TEXT COLLATE NOCASE UNIQUE,
    password_hash TEXT,
    role TEXT NOT NULL DEFAULT 'user' REFERENCES roles(name),
    active INTEGER NOT NULL DEFAULT 1 CHECK (active IN (0, 1)),
    created_at INTEGER NOT NULL,
    expires_at INTEGER,
    CHECK (role = 'guest' OR (email IS NOT NULL AND password_hash IS NOT NULL))
);
CREATE TABLE IF NOT EXISTS sessions (
    token_hash TEXT PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    csrf_token TEXT NOT NULL,
    created_at INTEGER NOT NULL,
    expires_at INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS sessions_user ON sessions(user_id);
CREATE INDEX IF NOT EXISTS sessions_expiry ON sessions(expires_at);

INSERT OR IGNORE INTO roles VALUES
    ('admin', 'View results, run discovery, and manage accounts'),
    ('user', 'View results and run discovery'),
    ('guest', 'View results during a temporary read-only session');
INSERT OR IGNORE INTO role_permissions VALUES
    ('admin', 'network.view'), ('admin', 'network.scan'), ('admin', 'users.manage'),
    ('user', 'network.view'), ('user', 'network.scan'), ('guest', 'network.view');

INSERT OR IGNORE INTO role_permissions VALUES
    ('admin', 'dashboard.view'), ('admin', 'devices.manage'), ('admin', 'network.test'), ('user', 'network.test');

DELETE FROM role_permissions WHERE permission='dashboard.view' AND role!='admin';

CREATE TABLE IF NOT EXISTS discovered_devices (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    subnet TEXT NOT NULL,
    ip_address TEXT NOT NULL,
    hostname TEXT,
    label TEXT NOT NULL DEFAULT '',
    trust TEXT NOT NULL DEFAULT 'review' CHECK (trust IN ('trusted','review','flagged')),
    first_seen TEXT NOT NULL,
    last_seen TEXT NOT NULL,
    UNIQUE (subnet, ip_address)
);
CREATE TABLE IF NOT EXISTS network_scans (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    scanned_at TEXT NOT NULL,
    subnet TEXT NOT NULL,
    snapshot TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS device_ping_tests (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    device_id INTEGER NOT NULL REFERENCES discovered_devices(id),
    tested_at TEXT NOT NULL,
    result TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS device_ping_latest ON device_ping_tests(device_id, id DESC);
CREATE TABLE IF NOT EXISTS network_activity (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    at TEXT NOT NULL,
    kind TEXT NOT NULL,
    message TEXT NOT NULL,
    actor TEXT,
    device_id INTEGER REFERENCES discovered_devices(id)
);
