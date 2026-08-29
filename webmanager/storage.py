from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import hmac
import json
from pathlib import Path
import secrets
import sqlite3

SCHEMA_VERSION = 5


class Store:
    def __init__(self, path: Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.init()

    def connect(self):
        conn = sqlite3.connect(self.path, timeout=15)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys=ON")
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous=NORMAL")
        conn.execute("PRAGMA busy_timeout=15000")
        return conn

    def init(self):
        db = self.connect()
        try:
            version = int(db.execute("PRAGMA user_version").fetchone()[0])
            if version > SCHEMA_VERSION:
                raise RuntimeError(
                    f"webmanager.db schema {version} is newer than this Web Manager "
                    f"supports ({SCHEMA_VERSION}); refusing unsafe downgrade"
                )
            db.execute("BEGIN IMMEDIATE")
            db.execute(
                "CREATE TABLE IF NOT EXISTS users ("
                "id INTEGER PRIMARY KEY AUTOINCREMENT,"
                "username TEXT NOT NULL UNIQUE COLLATE NOCASE,"
                "display_name TEXT NOT NULL DEFAULT '',"
                "salt TEXT NOT NULL,password_hash TEXT NOT NULL,"
                "role TEXT NOT NULL CHECK(role IN ('superadmin','user')),"
                "active INTEGER NOT NULL DEFAULT 1,created_at TEXT NOT NULL,"
                "created_by INTEGER REFERENCES users(id),"
                "teamtalk_admin_username TEXT NOT NULL DEFAULT '')"
            )
            db.execute(
                "CREATE TABLE IF NOT EXISTS instance_owners ("
                "instance_name TEXT PRIMARY KEY,"
                "owner_user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,"
                "teamtalk_admin_username TEXT NOT NULL DEFAULT '',created_at TEXT NOT NULL)"
            )
            cols = {str(row[1]) for row in db.execute("PRAGMA table_info(users)").fetchall()}
            if "teamtalk_admin_username" not in cols:
                db.execute("ALTER TABLE users ADD COLUMN teamtalk_admin_username TEXT NOT NULL DEFAULT ''")
            db.execute(
                "CREATE TABLE IF NOT EXISTS jobs ("
                "id TEXT PRIMARY KEY,title TEXT NOT NULL,status TEXT NOT NULL,"
                "created REAL NOT NULL,finished REAL,owner_user_id INTEGER,kind TEXT)"
            )
            db.execute("CREATE INDEX IF NOT EXISTS idx_jobs_owner_created ON jobs(owner_user_id,created DESC)")
            db.execute(
                "CREATE TABLE IF NOT EXISTS global_broadcast_messages ("
                "id INTEGER PRIMARY KEY AUTOINCREMENT,message TEXT NOT NULL,"
                "enabled INTEGER NOT NULL DEFAULT 1,position INTEGER NOT NULL DEFAULT 0,"
                "created_at TEXT NOT NULL,updated_at TEXT NOT NULL)"
            )
            db.execute(
                "CREATE INDEX IF NOT EXISTS idx_global_broadcast_active "
                "ON global_broadcast_messages(enabled,position,id)"
            )
            db.execute(
                "CREATE TABLE IF NOT EXISTS global_broadcast_state ("
                "instance_name TEXT PRIMARY KEY,last_sent REAL NOT NULL DEFAULT 0,"
                "last_message_id INTEGER NOT NULL DEFAULT 0,"
                "remaining_ids TEXT NOT NULL DEFAULT '[]',"
                "cycle_ids TEXT NOT NULL DEFAULT '[]')"
            )
            db.execute(
                "CREATE TABLE IF NOT EXISTS system_state ("
                "key TEXT PRIMARY KEY,value TEXT NOT NULL,updated_at TEXT NOT NULL)"
            )
            state_cols = {str(row[1]) for row in db.execute("PRAGMA table_info(global_broadcast_state)").fetchall()}
            if "remaining_ids" not in state_cols:
                db.execute("ALTER TABLE global_broadcast_state ADD COLUMN remaining_ids TEXT NOT NULL DEFAULT '[]'")
            if "cycle_ids" not in state_cols:
                db.execute("ALTER TABLE global_broadcast_state ADD COLUMN cycle_ids TEXT NOT NULL DEFAULT '[]'")
            db.execute(f"PRAGMA user_version={SCHEMA_VERSION}")
            db.execute("COMMIT")
        except Exception:
            if db.in_transaction:
                db.execute("ROLLBACK")
            raise
        finally:
            db.close()

    def upsert_job(self, job):
        safe = (
            str(job.get("id") or ""), str(job.get("title") or ""), str(job.get("status") or "queued"),
            float(job.get("created") or 0),
            float(job["finished"]) if job.get("finished") is not None else None,
            int(job["owner_user_id"]) if job.get("owner_user_id") is not None else None,
            str(job.get("kind")) if job.get("kind") is not None else None,
        )
        with self.connect() as db:
            db.execute(
                "INSERT INTO jobs(id,title,status,created,finished,owner_user_id,kind) VALUES(?,?,?,?,?,?,?) "
                "ON CONFLICT(id) DO UPDATE SET title=excluded.title,status=excluded.status,"
                "finished=excluded.finished,owner_user_id=excluded.owner_user_id,kind=excluded.kind",
                safe,
            )

    def get_job(self, jid):
        with self.connect() as db:
            row = db.execute(
                "SELECT id,title,status,created,finished,owner_user_id,kind FROM jobs WHERE id=?",
                (str(jid),),
            ).fetchone()
        return dict(row) if row else None

    def list_global_broadcast_messages(self, *, enabled_only=False):
        sql = "SELECT id,message,enabled,position,created_at,updated_at FROM global_broadcast_messages"
        if enabled_only:
            sql += " WHERE enabled=1"
        sql += " ORDER BY position,id"
        with self.connect() as db:
            return [dict(row) for row in db.execute(sql).fetchall()]

    def create_global_broadcast_message(self, message: str, *, enabled=True):
        message = str(message or "").strip()
        if not message:
            raise ValueError("message is required")
        if len(message.encode("utf-8")) > 12000:
            raise ValueError("message is too long")
        now = datetime.now(timezone.utc).isoformat()
        with self.connect() as db:
            position = int(db.execute("SELECT COALESCE(MAX(position),0)+1 FROM global_broadcast_messages").fetchone()[0])
            cur = db.execute(
                "INSERT INTO global_broadcast_messages(message,enabled,position,created_at,updated_at) VALUES(?,?,?,?,?)",
                (message, 1 if enabled else 0, position, now, now),
            )
            return int(cur.lastrowid)

    def create_global_broadcast_messages(self, messages, *, enabled=True):
        """Create multiple independent rotation messages in one transaction.

        Each input item becomes its own row.  This is intentionally different
        from a single message containing newlines, so 20+ short announcements
        rotate one by one instead of being sent as one large block.
        """
        cleaned = [str(message or "").strip() for message in messages]
        cleaned = [message for message in cleaned if message]
        if not cleaned:
            raise ValueError("at least one message is required")
        if len(cleaned) > 100:
            raise ValueError("a maximum of 100 messages can be added at once")
        for message in cleaned:
            if len(message.encode("utf-8")) > 12000:
                raise ValueError("one or more messages are too long")
        now = datetime.now(timezone.utc).isoformat()
        ids = []
        with self.connect() as db:
            position = int(db.execute("SELECT COALESCE(MAX(position),0)+1 FROM global_broadcast_messages").fetchone()[0])
            for offset, message in enumerate(cleaned):
                cur = db.execute(
                    "INSERT INTO global_broadcast_messages(message,enabled,position,created_at,updated_at) VALUES(?,?,?,?,?)",
                    (message, 1 if enabled else 0, position + offset, now, now),
                )
                ids.append(int(cur.lastrowid))
        return ids

    def update_global_broadcast_message(self, message_id: int, *, message=None, enabled=None):
        row = None
        with self.connect() as db:
            row = db.execute("SELECT * FROM global_broadcast_messages WHERE id=?", (int(message_id),)).fetchone()
            if not row:
                return False
            new_message = str(row["message"] if message is None else message).strip()
            if not new_message:
                raise ValueError("message is required")
            if len(new_message.encode("utf-8")) > 12000:
                raise ValueError("message is too long")
            new_enabled = int(row["enabled"] if enabled is None else bool(enabled))
            db.execute(
                "UPDATE global_broadcast_messages SET message=?,enabled=?,updated_at=? WHERE id=?",
                (new_message,new_enabled,datetime.now(timezone.utc).isoformat(),int(message_id)),
            )
        return True

    def delete_global_broadcast_message(self, message_id: int):
        with self.connect() as db:
            cur = db.execute("DELETE FROM global_broadcast_messages WHERE id=?", (int(message_id),))
            return cur.rowcount > 0

    @staticmethod
    def _decode_broadcast_ids(raw):
        try:
            values = json.loads(str(raw or "[]"))
        except (TypeError, ValueError, json.JSONDecodeError):
            return []
        if not isinstance(values, list):
            return []
        result = []
        seen = set()
        for value in values:
            try:
                ident = int(value)
            except (TypeError, ValueError):
                continue
            if ident > 0 and ident not in seen:
                seen.add(ident)
                result.append(ident)
        return result

    def global_broadcast_state(self, instance_name: str):
        with self.connect() as db:
            row = db.execute(
                "SELECT instance_name,last_sent,last_message_id,remaining_ids,cycle_ids "
                "FROM global_broadcast_state WHERE instance_name=?",
                (str(instance_name),),
            ).fetchone()
        if not row:
            return {
                "instance_name": str(instance_name), "last_sent": 0.0, "last_message_id": 0,
                "remaining_ids": [], "cycle_ids": [],
            }
        result = dict(row)
        result["remaining_ids"] = self._decode_broadcast_ids(result.get("remaining_ids"))
        result["cycle_ids"] = self._decode_broadcast_ids(result.get("cycle_ids"))
        return result

    def set_global_broadcast_state(
        self, instance_name: str, *, last_sent: float, last_message_id: int,
        remaining_ids=None, cycle_ids=None,
    ):
        name = str(instance_name)
        with self.connect() as db:
            existing = db.execute(
                "SELECT remaining_ids,cycle_ids FROM global_broadcast_state WHERE instance_name=?",
                (name,),
            ).fetchone()
            if remaining_ids is None:
                remaining_ids = self._decode_broadcast_ids(existing["remaining_ids"] if existing else "[]")
            if cycle_ids is None:
                cycle_ids = self._decode_broadcast_ids(existing["cycle_ids"] if existing else "[]")
            remaining_json = json.dumps([int(x) for x in remaining_ids], separators=(",", ":"))
            cycle_json = json.dumps([int(x) for x in cycle_ids], separators=(",", ":"))
            db.execute(
                "INSERT INTO global_broadcast_state(instance_name,last_sent,last_message_id,remaining_ids,cycle_ids) "
                "VALUES(?,?,?,?,?) "
                "ON CONFLICT(instance_name) DO UPDATE SET last_sent=excluded.last_sent,"
                "last_message_id=excluded.last_message_id,remaining_ids=excluded.remaining_ids,cycle_ids=excluded.cycle_ids",
                (name, float(last_sent), int(last_message_id), remaining_json, cycle_json),
            )

    def prepare_random_global_broadcast_message(self, instance_name: str, *, rng=None):
        """Choose one enabled message without replacement for the current cycle.

        The returned bag state is committed only after delivery succeeds.  Each
        instance therefore gets its own persistent random-without-replacement
        cycle: no delivered message repeats until every currently enabled
        message has been delivered once.
        """
        chooser = rng or secrets.SystemRandom()
        state = self.global_broadcast_state(instance_name)
        rows = self.list_global_broadcast_messages(enabled_only=True)
        if not rows:
            return None
        by_id = {int(row["id"]): row for row in rows}
        active_ids = list(by_id)
        active = set(active_ids)

        cycle_ids = [ident for ident in state.get("cycle_ids", []) if ident in active]
        remaining_ids = [ident for ident in state.get("remaining_ids", []) if ident in active]
        cycle_set = set(cycle_ids)
        remaining_set = set(remaining_ids)

        # Messages enabled/created during a cycle join the same central pool and
        # become eligible immediately, without re-adding messages already sent.
        for ident in active_ids:
            if ident not in cycle_set:
                cycle_ids.append(ident)
                cycle_set.add(ident)
                remaining_ids.append(ident)
                remaining_set.add(ident)

        if not remaining_ids:
            # The previous random bag is complete. Start a fresh cycle containing
            # every enabled message. Avoid an immediate boundary repeat when there
            # is more than one choice, while remaining random otherwise.
            cycle_ids = list(active_ids)
            remaining_ids = list(active_ids)
            choices = list(remaining_ids)
            last_id = int(state.get("last_message_id") or 0)
            if len(choices) > 1 and last_id in choices:
                choices.remove(last_id)
        else:
            choices = list(remaining_ids)

        chosen_id = int(chooser.choice(choices))
        remaining_after = [ident for ident in remaining_ids if ident != chosen_id]
        result = dict(by_id[chosen_id])
        result["remaining_ids_after"] = remaining_after
        result["cycle_ids_after"] = cycle_ids
        return result

    def set_system_state(self, key: str, value):
        now = datetime.now(timezone.utc).isoformat()
        payload = json.dumps(value, ensure_ascii=False, separators=(",", ":"))
        with self.connect() as db:
            db.execute(
                "INSERT INTO system_state(key,value,updated_at) VALUES(?,?,?) "
                "ON CONFLICT(key) DO UPDATE SET value=excluded.value,updated_at=excluded.updated_at",
                (str(key), payload, now),
            )

    def get_system_state(self, key: str, default=None):
        with self.connect() as db:
            row = db.execute("SELECT value,updated_at FROM system_state WHERE key=?", (str(key),)).fetchone()
        if not row:
            return default
        try:
            value = json.loads(str(row["value"]))
        except (TypeError, ValueError, json.JSONDecodeError):
            return default
        if isinstance(value, dict):
            value = dict(value)
            value.setdefault("updated_at", str(row["updated_at"]))
        return value

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
