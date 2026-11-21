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
