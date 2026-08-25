from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import hmac
from pathlib import Path
import secrets
import sqlite3


class Store:
    def __init__(self, path: Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.init()

    def connect(self):
        conn = sqlite3.connect(self.path, timeout=15)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys=ON")
        return conn

    def init(self):
        with self.connect() as db:
            db.executescript(
                """
                CREATE TABLE IF NOT EXISTS users (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    username TEXT NOT NULL UNIQUE COLLATE NOCASE,
                    display_name TEXT NOT NULL DEFAULT '',
                    salt TEXT NOT NULL,
                    password_hash TEXT NOT NULL,
                    role TEXT NOT NULL CHECK(role IN ('superadmin','user')),
                    active INTEGER NOT NULL DEFAULT 1,
                    created_at TEXT NOT NULL,
                    created_by INTEGER REFERENCES users(id),
                    teamtalk_admin_username TEXT NOT NULL DEFAULT ''
                );
                CREATE TABLE IF NOT EXISTS instance_owners (
                    instance_name TEXT PRIMARY KEY,
                    owner_user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                    teamtalk_admin_username TEXT NOT NULL DEFAULT '',
                    created_at TEXT NOT NULL
                );
                """
            )
            # Schema migration for Web Manager <= 1.1.5. Keep the field as an
            # optional TeamTalk username prefill. 1.1.7+ proves ownership with a
            # one-shot username/password login instead of trusting this mapping.
            cols = {str(row[1]) for row in db.execute("PRAGMA table_info(users)").fetchall()}
            if "teamtalk_admin_username" not in cols:
                db.execute("ALTER TABLE users ADD COLUMN teamtalk_admin_username TEXT NOT NULL DEFAULT ''")

    @staticmethod
    def _hash(password: str, salt: bytes) -> bytes:
        return hashlib.scrypt(password.encode("utf-8"), salt=salt, n=2**14, r=8, p=1, dklen=32)

    def user_count(self) -> int:
        with self.connect() as db:
            return int(db.execute("SELECT COUNT(*) FROM users").fetchone()[0])

    def create_first_superadmin(self, username: str, password: str, *, display_name: str = ""):
        """Atomically create the one first-run superadmin.

        BEGIN IMMEDIATE prevents two concurrent first-visit requests from both
        observing an empty users table and creating multiple superadmins.
        """
        username = username.strip()
        if len(password) < 10:
            raise ValueError("password must be at least 10 characters")
        salt = secrets.token_bytes(16)
        digest = self._hash(password, salt)
        now = datetime.now(timezone.utc).isoformat()
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            if int(db.execute("SELECT COUNT(*) FROM users").fetchone()[0]) != 0:
                raise ValueError("initial setup is already complete")
            cur = db.execute(
                "INSERT INTO users(username,display_name,salt,password_hash,role,active,created_at,created_by) VALUES(?,?,?,?,?,1,?,NULL)",
                (username, display_name.strip(), salt.hex(), digest.hex(), "superadmin", now),
            )
            row = db.execute("SELECT * FROM users WHERE id=?", (int(cur.lastrowid),)).fetchone()
            return dict(row) if row else None

    def create_user(self, username: str, password: str, *, role: str = "user", display_name: str = "", teamtalk_admin_username: str = "", created_by=None):
        username = username.strip()
        if role not in ("superadmin", "user"):
            raise ValueError("invalid role")
        if len(password) < 10:
            raise ValueError("password must be at least 10 characters")
        salt = secrets.token_bytes(16)
        digest = self._hash(password, salt)
        now = datetime.now(timezone.utc).isoformat()
        with self.connect() as db:
            cur = db.execute(
                "INSERT INTO users(username,display_name,salt,password_hash,role,active,created_at,created_by,teamtalk_admin_username) VALUES(?,?,?,?,?,1,?,?,?)",
                (username, display_name.strip(), salt.hex(), digest.hex(), role, now, created_by, teamtalk_admin_username.strip()),
            )
            # Read the row through the same transaction. Opening a second SQLite
            # connection here can race the commit and return None on first-run setup.
            row = db.execute("SELECT * FROM users WHERE id=?", (int(cur.lastrowid),)).fetchone()
            return dict(row) if row else None

    def get_user(self, user_id: int):
        with self.connect() as db:
            row = db.execute("SELECT * FROM users WHERE id=?", (int(user_id),)).fetchone()
            return dict(row) if row else None

    def get_user_by_username(self, username: str):
        with self.connect() as db:
            row = db.execute("SELECT * FROM users WHERE username=? COLLATE NOCASE", (username.strip(),)).fetchone()
            return dict(row) if row else None

    def verify(self, username: str, password: str):
        user = self.get_user_by_username(username)
        if not user or not user.get("active"):
            return None
        try:
            actual = self._hash(password, bytes.fromhex(user["salt"]))
            expected = bytes.fromhex(user["password_hash"])
        except Exception:
            return None
        return user if hmac.compare_digest(actual, expected) else None

    def list_users(self):
        with self.connect() as db:
            rows = db.execute("SELECT id,username,display_name,role,active,created_at,teamtalk_admin_username FROM users ORDER BY username COLLATE NOCASE").fetchall()
            return [dict(x) for x in rows]

    def set_password(self, user_id: int, password: str):
        if len(password) < 10:
            raise ValueError("password must be at least 10 characters")
        salt = secrets.token_bytes(16)
        digest = self._hash(password, salt)
        with self.connect() as db:
            db.execute("UPDATE users SET salt=?, password_hash=? WHERE id=?", (salt.hex(), digest.hex(), int(user_id)))


    def set_teamtalk_admin_username(self, user_id: int, username: str):
        with self.connect() as db:
            db.execute("UPDATE users SET teamtalk_admin_username=? WHERE id=?", (username.strip(), int(user_id)))

    def set_active(self, user_id: int, active: bool):
        with self.connect() as db:
            db.execute("UPDATE users SET active=? WHERE id=?", (1 if active else 0, int(user_id)))

    def owner(self, instance_name: str):
        with self.connect() as db:
            row = db.execute(
                "SELECT io.*,u.username,u.display_name FROM instance_owners io JOIN users u ON u.id=io.owner_user_id WHERE io.instance_name=?",
                (instance_name,),
            ).fetchone()
            return dict(row) if row else None

    def owners_map(self, instance_names):
        names = [str(x) for x in instance_names if str(x)]
        if not names:
            return {}
        marks = ",".join("?" for _ in names)
        with self.connect() as db:
            rows = db.execute(
                f"SELECT io.*,u.username,u.display_name FROM instance_owners io JOIN users u ON u.id=io.owner_user_id WHERE io.instance_name IN ({marks})",
                names,
            ).fetchall()
            return {str(row["instance_name"]): dict(row) for row in rows}

    def set_owner(self, instance_name: str, owner_user_id: int, teamtalk_admin_username: str = ""):
        now = datetime.now(timezone.utc).isoformat()
        with self.connect() as db:
            db.execute(
                "INSERT INTO instance_owners(instance_name,owner_user_id,teamtalk_admin_username,created_at) VALUES(?,?,?,?) "
                "ON CONFLICT(instance_name) DO UPDATE SET owner_user_id=excluded.owner_user_id,teamtalk_admin_username=excluded.teamtalk_admin_username",
                (instance_name, int(owner_user_id), teamtalk_admin_username.strip(), now),
            )

    def delete_owner(self, instance_name: str):
        with self.connect() as db:
            db.execute("DELETE FROM instance_owners WHERE instance_name=?", (instance_name,))

    def owned_names(self, user_id: int):
        with self.connect() as db:
            rows = db.execute("SELECT instance_name FROM instance_owners WHERE owner_user_id=?", (int(user_id),)).fetchall()
            return {str(x[0]) for x in rows}

    def claim_unowned(self, instance_names, owner_user_id: int):
        for name in instance_names:
            if not self.owner(name):
                self.set_owner(name, owner_user_id, "")
