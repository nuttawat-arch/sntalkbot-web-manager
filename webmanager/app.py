from __future__ import annotations

import asyncio
import configparser
import concurrent.futures
from datetime import datetime, timezone
import hashlib
import hmac
import json
import logging
import os
from pathlib import Path
import re
import secrets
import shutil
import subprocess
import tempfile
import threading
import time
import urllib.parse
import urllib.request
import uuid
import zipfile

from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import HTMLResponse, RedirectResponse, PlainTextResponse, StreamingResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.middleware.sessions import SessionMiddleware

from webmanager.storage import Store

APP_ROOT = Path(__file__).resolve().parents[1]
VERSION = (APP_ROOT / "VERSION").read_text(encoding="utf-8").strip()
DATA_DIR = Path(os.getenv("SNWEB_DATA_DIR", "/var/lib/sntalkbot-web-manager"))
SESSION_SECRET_FILE = Path(os.getenv("SNWEB_SESSION_SECRET_FILE", "/etc/sntalkbot-web-manager/session_secret"))
GITHUB_WEBHOOK_SECRET_FILE = Path(os.getenv("SNWEB_GITHUB_WEBHOOK_SECRET_FILE", "/etc/sntalkbot-web-manager/github_webhook_secret"))
DB_FILE = Path(os.getenv("SNWEB_DB_FILE", str(DATA_DIR / "webmanager.db")))
ROOT_BRIDGE = Path(os.getenv("SNWEB_ROOT_BRIDGE", "/usr/local/lib/sntalkbot-web-manager/snweb-root"))
TTU_CONFIG = Path(os.getenv("TTU_HELPER_CONFIG", "/etc/default/ttuhelper"))
DEFAULT_BOTS_ROOT = Path("/opt/sntalkbot-bots")
TTU_SOURCE = Path(os.getenv("SNWEB_TTU_SOURCE", "/opt/ttuhelper"))
TTU_REPO = os.getenv("SNWEB_TTU_REPO", "https://github.com/nuttawat-arch/ttuhelper.git")
WEB_REPO = os.getenv("SNWEB_WEB_REPO", "https://github.com/nuttawat-arch/sntalkbot-web-manager.git")
GITHUB_REPOSITORY = os.getenv("SNWEB_GITHUB_REPOSITORY", "nuttawat-arch/sntalkbot").strip().lower()
IMAGE_REPO_DEFAULT = os.getenv("TTU_IMAGE_REPO", "nuttawat0295/sntalkbot")
IMAGE_TAG_DEFAULT = os.getenv("TTU_TAG", "latest")
SECRET_KEYS = ("password", "token", "api_key", "license_key", "secret")
# Normal tenant users may tune the bot they own, but they cannot change the
# TeamTalk server/login identity after ownership was verified. Otherwise a user
# could verify against an allowed server and then silently repoint the bot.
TENANT_LOCKED_CONFIG_KEYS = {
    ("server", "address"),
    ("server", "tcp_port"),
    ("server", "udp_port"),
    ("server", "encrypted"),
    ("server", "username"),
    ("server", "password"),
}
BOT_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,62}$")
NEW_BOT_NAME_RE = re.compile(r"^[a-z0-9][a-z0-9_.-]{0,62}$")
WEB_USERNAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{2,63}$")

DATA_DIR.mkdir(parents=True, exist_ok=True)
(DATA_DIR / "jobs").mkdir(parents=True, exist_ok=True)
STORE = Store(DB_FILE)
_LOGIN_LOCK = threading.Lock()
_LOGIN_FAILURES = {}
LOGIN_WINDOW = 300
LOGIN_MAX_FAILURES = 8
PROCESS_STARTED_EPOCH = time.time()
PROCESS_GENERATION = uuid.uuid4().hex
LOGGER = logging.getLogger("sntalkbot.webmanager")

def _session_secret():
    env = os.getenv("SNWEB_SESSION_SECRET", "").strip()
    if env:
        return env
    if SESSION_SECRET_FILE.is_file():
        return SESSION_SECRET_FILE.read_text(encoding="utf-8").strip()
    # Development/fallback only. Production install.sh creates a root-owned secret.
    path = DATA_DIR / "session_secret"
    if path.is_file():
        return path.read_text(encoding="utf-8").strip()
    secret = secrets.token_urlsafe(64)
    path.write_text(secret + "\n", encoding="utf-8")
    os.chmod(path, 0o600)
    return secret

SESSION_SECRET = _session_secret()

def _static_revision():
    digest = hashlib.sha256()
    for name in ("app.js", "style.css"):
        path = APP_ROOT / "static" / name
        digest.update(name.encode("utf-8"))
        digest.update(path.read_bytes() if path.is_file() else b"")
    return digest.hexdigest()[:16]

STATIC_REV = _static_revision()


def _last_resort_error_html(request_id: str) -> str:
    # Deliberately static: this fallback must not depend on Jinja, SQLite,
    # instance config, sessions, Guardian state, or any other component that may
    # itself be the source of the failure.
    return f"""<!doctype html><html lang="th"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>เกิดข้อผิดพลาด — SNTalkBot Web Manager</title></head><body><main><h1>SNTalkBot Web Manager</h1><h2>หน้าเว็บพบข้อผิดพลาด</h2><p role="alert">Web Manager ไม่สามารถสร้างหน้านี้ได้ แต่บอตและ Docker ไม่ได้ถูกหยุดโดยข้อความนี้</p><p>ลองเปิด <a href="/">แดชบอร์ด</a> อีกครั้ง หากเกิดซ้ำให้แจ้ง Request ID นี้โดยไม่ต้องส่งรหัสผ่านหรือ token</p><p>Request ID: <code>{request_id}</code></p></main></body></html>"""


class LastResortErrorMiddleware:
    """Catch failures outside FastAPI's normal ExceptionMiddleware.

    Session/user middleware and an exception handler that fails while rendering
    can otherwise fall back to Starlette's bare ``Internal Server Error`` body.
    Keep this pure ASGI so SSE/job streaming is passed through without buffering.
    """
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope.get("type") != "http":
            await self.app(scope, receive, send)
            return
        started = False

        async def tracked_send(message):
            nonlocal started
            if message.get("type") == "http.response.start":
                started = True
            await send(message)

        try:
            await self.app(scope, receive, tracked_send)
        except Exception:
            request_id = uuid.uuid4().hex[:12]
            LOGGER.exception("Last-resort Web Manager error request_id=%s path=%s", request_id, scope.get("path", "?"))
            if started:
                raise
            body = _last_resort_error_html(request_id).encode("utf-8")
            await send({"type": "http.response.start", "status": 500, "headers": [(b"content-type", b"text/html; charset=utf-8"), (b"content-length", str(len(body)).encode("ascii")), (b"x-sntalkbot-request-id", request_id.encode("ascii"))]})
            await send({"type": "http.response.body", "body": body})


app = FastAPI(title="SNTalkBot Web Manager", docs_url=None, redoc_url=None)
# Ten-year persistent browser session. It remains invalid if the account is disabled
# or the server-side session secret is deliberately rotated.
app.add_middleware(SessionMiddleware, secret_key=SESSION_SECRET, same_site="lax", https_only=os.getenv("SNWEB_COOKIE_SECURE", "false").strip().lower() in ("1","true","yes","on"), max_age=10 * 365 * 24 * 3600)
# Added after SessionMiddleware so it is the outer user middleware and can catch
# session/middleware failures as well as errors re-raised by inner handlers.
app.add_middleware(LastResortErrorMiddleware)
app.mount("/static", StaticFiles(directory=APP_ROOT / "static"), name="static")
templates = Jinja2Templates(directory=APP_ROOT / "templates")
templates.env.globals["process_generation"] = PROCESS_GENERATION
templates.env.globals["static_rev"] = STATIC_REV

@app.middleware("http")
async def no_store_html(request: Request, call_next):
    response = await call_next(request)
    content_type = str(response.headers.get("content-type") or "").lower()
    if "text/html" in content_type:
        response.headers["Cache-Control"] = "no-store, max-age=0"
        response.headers["Pragma"] = "no-cache"
    return response

def current_user(request: Request):
    user_id = request.session.get("user_id")
    if not user_id:
        return None
    user = STORE.get_user(int(user_id))
    if not user or not user.get("active"):
        request.session.clear()
        return None
    return user

def require_login(request: Request):
    user = current_user(request)
    if not user:
        raise HTTPException(status_code=303, headers={"Location": "/login"})
    return user

def require_superadmin(request: Request):
    user = require_login(request)
    if user.get("role") != "superadmin":
        raise HTTPException(status_code=403, detail="Super Admin only")
    return user

def setup_required():
    return STORE.user_count() == 0

def csrf_token(request: Request):
    token = request.session.get("csrf")
    if not token:
        token = secrets.token_urlsafe(32)
        request.session["csrf"] = token
    return token


def check_csrf(request: Request, token: str):
    expected = request.session.get("csrf", "")
    if not expected or not hmac.compare_digest(expected, token or ""):
        raise HTTPException(status_code=400, detail="CSRF token mismatch")


def run(args, *, timeout=120, check=False, cwd=None, env=None):
    proc = subprocess.run(
        [str(x) for x in args],
        cwd=str(cwd) if cwd else None,
        env=env,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        timeout=timeout,
        check=False,
    )
    if check and proc.returncode != 0:
        raise RuntimeError(proc.stdout.strip() or f"Command failed: {args}")
    return proc.returncode, proc.stdout


def root_run(args, *, timeout=120, check=False):
    cmd = ["sudo", "-n", str(ROOT_BRIDGE), *[str(x) for x in args]]
    return run(cmd, timeout=timeout, check=check)


def root_run_stdin(args, payload: dict, *, timeout=45, check=False):
    """Call the privileged bridge with secret-bearing JSON on stdin only.

    TeamTalk verification passwords and central Telegram tokens use this path so
    secrets never enter argv or persisted Web Manager job metadata/output.
    """
    cmd = ["sudo", "-n", str(ROOT_BRIDGE), *[str(x) for x in args]]
    proc = subprocess.run(
        cmd, input=json.dumps(payload, ensure_ascii=False), text=True,
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=timeout, check=False,
    )
    if check and proc.returncode != 0:
        try:
            data=json.loads((proc.stdout or "").strip().splitlines()[-1])
            message=str(data.get("error") or "TeamTalk verification failed")
        except Exception:
            message="TeamTalk verification failed"
        raise RuntimeError(message)
    return proc.returncode, proc.stdout


def read_instance_meta(path: Path):
    data = {}
    p = path / "instance.conf"
    if p.is_file():
        for raw in p.read_text(encoding="utf-8", errors="replace").splitlines():
            if "=" in raw:
                k, v = raw.split("=", 1)
                data[k.strip()] = v.strip()
    return data


def _safe_int(value, default=0):
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _safe_float(value, default=0.0):
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _activity_payload(value):
    row = value if isinstance(value, dict) else {}
    return {key: _safe_int(row.get(key), 0) for key in ("speaking", "media", "video", "desktop")}


def normalize_live_payload(data):
    """Normalize old/new/partial realtime payloads before templates see them.

    A single malformed or mid-update runtime field must never take down the whole
    dashboard.  Older SNTalkBot snapshots used users_online as a server total;
    new snapshots use a room-scoped count and explicit server totals.
    """
    if not isinstance(data, dict):
        return None
    data = dict(data)
    legacy = "room_users_online" not in data

    channel = data.get("channel") if isinstance(data.get("channel"), dict) else {}
    data["channel"] = {"id": _safe_int(channel.get("id"), 0), "name": str(channel.get("name") or "")}
    data["teamtalk_activity"] = _activity_payload(data.get("teamtalk_activity"))
    data["server_teamtalk_activity"] = _activity_payload(
        data.get("server_teamtalk_activity") if not legacy else data.get("teamtalk_activity")
    )

    if legacy:
        data["server_users_online"] = data.get("server_users_online", data.get("users_online"))
        data["room_users_online"] = None
        data["admins_in_room_count"] = None
    else:
        data["room_users_online"] = _safe_int(data.get("room_users_online"), 0)
        data["admins_in_room_count"] = _safe_int(data.get("admins_in_room_count"), 0)
    if data.get("server_users_online") is not None:
        data["server_users_online"] = _safe_int(data.get("server_users_online"), 0)
    data["admins_online_count"] = _safe_int(data.get("admins_online_count"), 0)
    data["uptime_seconds"] = _safe_int(data.get("uptime_seconds"), 0)

    room_users=[]
    for raw in data.get("room_users") if isinstance(data.get("room_users"), list) else []:
        if not isinstance(raw, dict):
            continue
        row=dict(raw)
        row["state"]={key: bool((raw.get("state") or {}).get(key)) for key in ("speaking","media","video","desktop")} if isinstance(raw.get("state"), dict) else {key:False for key in ("speaking","media","video","desktop")}
        room_users.append(row)
    data["room_users"] = room_users
    data["admins_online"] = [dict(x) for x in data.get("admins_online", []) if isinstance(x, dict)] if isinstance(data.get("admins_online"), list) else []

    player=data.get("player")
    if isinstance(player, dict):
        player=dict(player)
        player["queue_count"]=_safe_int(player.get("queue_count"), 0)
        player["play_mode"]=_safe_int(player.get("play_mode"), 0)
        player["volume"]=_safe_int(player.get("volume"), 0)
        player["speed"]=_safe_float(player.get("speed"), 1.0)
        player["queue"]=[dict(x) for x in player.get("queue", []) if isinstance(x, dict)] if isinstance(player.get("queue"), list) else []
        data["player"]=player
    else:
        data["player"]=None
    data["manager"] = dict(data["manager"]) if isinstance(data.get("manager"), dict) else None
    return data


_SNAPSHOT_LOCK = threading.Lock()
_SNAPSHOT_CACHE = {}


def _cached_snapshot(key: str, ttl: float, loader, default):
    now = time.monotonic()
    with _SNAPSHOT_LOCK:
        item = _SNAPSHOT_CACHE.get(key)
        if item and now - item[0] < ttl:
            return item[1]
    try:
        value = loader()
    except Exception:
        LOGGER.exception("snapshot loader failed: %s", key)
        value = default
    with _SNAPSHOT_LOCK:
        _SNAPSHOT_CACHE[key] = (now, value)
    return value


def _local_instance_snapshot():
    root = bots_root()
    rows = []
    if not root.is_dir():
        return rows
    try:
        paths = sorted(root.iterdir(), key=lambda p: p.name.lower())
    except OSError:
        return rows
    for path in paths:
        if not path.is_dir() or not BOT_NAME_RE.fullmatch(path.name) or not (path / "config.ini").is_file():
            continue
        warning = ""
        try:
            cfg = read_config(path / "config.ini")
        except Exception as exc:
            cfg = configparser.ConfigParser(interpolation=None)
            warning = type(exc).__name__
        try:
            role = read_instance_role(path, cfg)
        except Exception:
            role = "unknown"
        meta = read_instance_meta(path)
        rows.append({
            "name": path.name,
            "role": role,
            "nickname": cfg.get("bot", "nickname", fallback=path.name),
            "server": cfg.get("server", "address", fallback=""),
            "channel": cfg.get("bot", "default_channel", fallback="/"),
            "created_at": meta.get("created") or "",
            "config_warning": warning,
        })
    return rows


def root_instance_snapshot(force=False):
    def load():
        rc, out = root_run(["instances-snapshot"], timeout=10)
        if rc == 0 and (out or "").strip():
            try:
                data = json.loads(out)
                return [dict(x) for x in data if isinstance(x, dict) and BOT_NAME_RE.fullmatch(str(x.get("name") or ""))]
            except Exception:
                LOGGER.exception("invalid instances-snapshot payload; using compatibility fallback")
        # Compatibility during rolling upgrade and for old bridge/test harnesses.
        return _local_instance_snapshot()
    if force:
        with _SNAPSHOT_LOCK:
            _SNAPSHOT_CACHE.pop("instances", None)
    return _cached_snapshot("instances", 2.0, load, [])


def docker_containers_snapshot(force=False):
    def load():
        rc, out = root_run(["docker-list-managed"], timeout=10)
        if rc != 0 or not (out or "").strip():
            # Rolling-upgrade/old-bridge compatibility; list_instances falls back
            # to per-instance docker-inspect only while this batch action is absent.
            return {}
        data = json.loads(out)
        return {str(k): dict(v) for k, v in data.items() if isinstance(v, dict)} if isinstance(data, dict) else {}
    if force:
        with _SNAPSHOT_LOCK:
            _SNAPSHOT_CACHE.pop("containers", None)
    return _cached_snapshot("containers", 1.0, load, {})


def bot_api_status(path: Path):
    meta = read_instance_meta(path)
    try:
        port = int(meta.get("api_port") or 0)
    except ValueError:
        port = 0
    token = meta.get("api_token", "")
    if not port or not token:
        return None
    req = urllib.request.Request(
        f"http://127.0.0.1:{port}/v1/status",
        headers={"Authorization": f"Bearer {token}", "Accept": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=0.4) as resp:
            data = json.loads(resp.read(1024 * 1024).decode("utf-8", "replace"))
            data["transport"] = "http-api"
            data["stale"] = False
            data["age_seconds"] = 0
            return normalize_live_payload(data)
    except Exception:
        return None


def bot_api_release_event(path: Path, payload: dict):
    meta = read_instance_meta(path)
    try:
        port = int(meta.get("api_port") or 0)
    except ValueError:
        port = 0
    token = meta.get("api_token", "")
    if not port or not token:
        return False
    body = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    req = urllib.request.Request(
        f"http://127.0.0.1:{port}/v1/events/release",
        data=body, method="POST",
        headers={
            "Authorization": f"Bearer {token}",
            "Accept": "application/json",
            "Content-Type": "application/json",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=1.0) as resp:
            return 200 <= int(resp.status) < 300
    except Exception:
        return False


def bot_api_global_broadcast(path: Path, message: str):
    meta = read_instance_meta(path)
    try:
        port = int(meta.get("api_port") or 0)
    except ValueError:
        port = 0
    token = meta.get("api_token", "")
    if not port or not token:
        return False
    body = json.dumps({"message": str(message)}, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    req = urllib.request.Request(
        f"http://127.0.0.1:{port}/v1/events/global-broadcast",
        data=body, method="POST",
        headers={
            "Authorization": f"Bearer {token}",
            "Accept": "application/json",
            "Content-Type": "application/json",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=1.0) as resp:
            return 200 <= int(resp.status) < 300
    except Exception:
        return False


def _fanout_release_event(payload: dict):
    rows = root_instance_snapshot(force=True)
    containers = docker_containers_snapshot(force=True)
    attempted = delivered = 0
    for row in rows:
        name = str(row.get("name") or "")
        if not BOT_NAME_RE.fullmatch(name):
            continue
        state = containers.get(name) if isinstance(containers, dict) else None
        if state is None:
            state = docker_container(name) or {}
        if not bool(state.get("running")):
            continue
        attempted += 1
        if bot_api_release_event(bots_root() / name, payload):
            delivered += 1
    return attempted, delivered


_GLOBAL_BROADCAST_STOP = threading.Event()
_GLOBAL_BROADCAST_THREAD = None
_GLOBAL_BROADCAST_RETRY_AFTER = {}


def _global_broadcast_tick(now=None):
    """Deliver due central messages without writing per-second runtime state."""
    now = float(time.time() if now is None else now)
    root = bots_root()
    if not root.is_dir():
        return 0
    delivered = 0
    try:
        paths = list(root.iterdir())
    except OSError:
        return 0
    for path in paths:
        if not path.is_dir() or not BOT_NAME_RE.fullmatch(path.name) or not (path / "config.ini").is_file():
            continue
        retry_at = float(_GLOBAL_BROADCAST_RETRY_AFTER.get(path.name, 0.0) or 0.0)
        if now < retry_at:
            continue
        try:
            cfg = read_config(path / "config.ini")
            if not cfg.getboolean("features", "server_management_enabled", fallback=True):
                continue
            if not cfg.getboolean("global_broadcast", "enabled", fallback=False):
                continue
            interval = max(1, min(10080, cfg.getint("global_broadcast", "interval_minutes", fallback=60)))
        except Exception:
            LOGGER.exception("Invalid global broadcast config for %s", path.name)
            continue
        state = STORE.global_broadcast_state(path.name)
        if now - float(state.get("last_sent") or 0.0) < interval * 60:
            continue
        message = STORE.prepare_random_global_broadcast_message(path.name)
        if not message:
            continue
        if bot_api_global_broadcast(path, message["message"]):
            STORE.set_global_broadcast_state(
                path.name, last_sent=now, last_message_id=int(message["id"]),
                remaining_ids=message["remaining_ids_after"],
                cycle_ids=message["cycle_ids_after"],
            )
            _GLOBAL_BROADCAST_RETRY_AFTER.pop(path.name, None)
            delivered += 1
        else:
            # A stopped/restarting bot is not a reason to advance the schedule.
            # Back off API retries so the scheduler remains cheap.
            _GLOBAL_BROADCAST_RETRY_AFTER[path.name] = now + 30.0
    return delivered


def _global_broadcast_scheduler_loop():
    while not _GLOBAL_BROADCAST_STOP.wait(5.0):
        try:
            _global_broadcast_tick()
        except Exception:
            LOGGER.exception("Central global broadcast scheduler failed")


@app.on_event("startup")
def _start_global_broadcast_scheduler():
    global _GLOBAL_BROADCAST_THREAD
    if _GLOBAL_BROADCAST_THREAD and _GLOBAL_BROADCAST_THREAD.is_alive():
        return
    _GLOBAL_BROADCAST_STOP.clear()
    _GLOBAL_BROADCAST_THREAD = threading.Thread(
        target=_global_broadcast_scheduler_loop, name="snweb-global-broadcast", daemon=True
    )
    _GLOBAL_BROADCAST_THREAD.start()


@app.on_event("shutdown")
def _stop_global_broadcast_scheduler():
    _GLOBAL_BROADCAST_STOP.set()


def live_state(path: Path, *, running: bool = True):
    # Realtime has exactly one source: the bot's loopback Bearer API. A stopped
    # or unreachable bot is reported unavailable instead of serving stale files.
    if not running:
        return None
    return bot_api_status(path)


def helper_settings():
    settings = {"TTU_IMAGE_REPO": IMAGE_REPO_DEFAULT, "TTU_TAG": IMAGE_TAG_DEFAULT, "TTU_BOTS_ROOT": str(DEFAULT_BOTS_ROOT)}
    if TTU_CONFIG.is_file():
        for raw in TTU_CONFIG.read_text(encoding="utf-8", errors="replace").splitlines():
            raw = raw.strip()
            if not raw or raw.startswith("#") or "=" not in raw:
                continue
            k, v = raw.split("=", 1)
            settings[k.strip()] = v.strip().strip('"').strip("'")
    return settings


def bots_root():
    return Path(helper_settings().get("TTU_BOTS_ROOT") or DEFAULT_BOTS_ROOT)


def image_name():
    s = helper_settings()
    return f"{s.get('TTU_IMAGE_REPO', IMAGE_REPO_DEFAULT)}:{s.get('TTU_TAG', IMAGE_TAG_DEFAULT)}"


def helper_installed():
    return shutil.which("ttuhelper") is not None


def docker_installed():
    return shutil.which("docker") is not None


def helper_version():
    if not helper_installed():
        return None
    rc, out = run(["ttuhelper", "version"], timeout=10)
    if rc == 0:
        m = re.search(r"([0-9]+(?:\.[0-9]+){1,3})", out)
        return m.group(1) if m else out.strip()
    return None


def source_version(path: Path):
    p = path / "VERSION"
    return p.read_text(encoding="utf-8").strip() if p.is_file() else None


def remote_version(repo: str):
    if not repo.endswith(".git"):
        return None
    url = repo[:-4].replace("https://github.com/", "https://raw.githubusercontent.com/") + "/main/VERSION"
    try:
        with urllib.request.urlopen(url, timeout=5) as resp:
            return resp.read(100).decode("utf-8", "replace").strip()
    except Exception:
        return None


def docker_container(name: str):
    if not docker_installed():
        return None
    rc, out = root_run(["docker-inspect", name], timeout=10)
    if rc != 0:
        return None
    try:
        data = json.loads(out)[0]
    except Exception:
        return None
    state = data.get("State") or {}
    config = data.get("Config") or {}
    return {
        "exists": True,
        "running": bool(state.get("Running")),
        "status": state.get("Status") or "unknown",
        "started_at": state.get("StartedAt"),
        "image": config.get("Image") or "",
        "restart_count": data.get("RestartCount", 0),
    }


def read_instance_role(path: Path, cfg=None):
    conf = path / "instance.conf"
    if conf.is_file():
        for line in conf.read_text(encoding="utf-8", errors="replace").splitlines():
            if line.startswith("mode="):
                value = line.split("=", 1)[1].strip().lower()
                if value in ("full", "player", "manager"):
                    return value
    cfg = cfg or read_config(path / "config.ini")
    p = cfg.getboolean("features", "player_enabled", fallback=True)
    m = cfg.getboolean("features", "server_management_enabled", fallback=True)
    return "full" if p and m else ("player" if p else "manager")


def read_config(path: Path):
    cfg = configparser.ConfigParser(interpolation=None)
    if path.is_file():
        cfg.read(path, encoding="utf-8")
    return cfg


def list_instances(user=None, *, include_live=True, force_snapshot=False):
    """Return visible instances from one privileged snapshot plus one Docker snapshot.

    The authoritative root-side metadata scan prevents a Web service group/permission
    drift from making Super Admin see an empty dashboard.  Live API reads are optional
    so the first HTML render never waits on every bot one-by-one.
    """
    meta_rows = root_instance_snapshot(force=force_snapshot)
    names = [str(row.get("name")) for row in meta_rows]
    if user and user.get("role") == "superadmin":
        # Any real pre-existing instance without a Web owner belongs to the first/
        # current Super Admin. Existing tenant mappings are never overwritten.
        STORE.claim_unowned(names, int(user["id"]))
    allowed = None
    if user and user.get("role") != "superadmin":
        allowed = STORE.owned_names(int(user["id"]))
    owners = STORE.owners_map(names)
    containers = docker_containers_snapshot(force=force_snapshot)
    batch_container_snapshot_available = bool(containers)
    result = []
    for meta in meta_rows:
        name = str(meta.get("name") or "")
        if allowed is not None and name not in allowed:
            continue
        cont = containers.get(name)
        if cont is None and not batch_container_snapshot_available:
            # Old root bridge compatibility only. Production 1.1.13 normally uses
            # one docker-list-managed call for the whole dashboard.
            try:
                cont = docker_container(name)
            except Exception:
                cont = None
        warnings = []
        if meta.get("config_warning"):
            warnings.append(f"อ่าน config ไม่สมบูรณ์ ({meta['config_warning']})")
        live = None
        if include_live and cont and cont.get("running"):
            try:
                live = live_state(bots_root() / name, running=True)
            except Exception as exc:
                LOGGER.exception("realtime status read failed: %s", name)
                warnings.append(f"อ่านข้อมูลสดไม่สำเร็จ ({type(exc).__name__})")
        result.append({
            "name": name,
            "path": str(bots_root() / name),
            "role": meta.get("role") or "unknown",
            "nickname": meta.get("nickname") or name,
            "server": meta.get("server") or "",
            "channel": meta.get("channel") or "/",
            "created_at": meta.get("created_at") or (owners.get(name) or {}).get("created_at") or "ไม่ทราบ",
            "container": cont,
            "running": bool(cont and cont.get("running")),
            "runtime": live,
            "owner": owners.get(name),
            "warnings": warnings,
        })
    return result


def can_manage_instance(user, name: str):
    if not user:
        return False
    if user.get("role") == "superadmin":
        return True
    owner = STORE.owner(name)
    return bool(owner and int(owner["owner_user_id"]) == int(user["id"]))


def instance_or_404(name: str, user=None):
    if not BOT_NAME_RE.match(name):
        raise HTTPException(status_code=404)
    path = bots_root() / name
    if not path.is_dir() or not (path / "config.ini").is_file():
        raise HTTPException(status_code=404)
    if user is not None and not can_manage_instance(user, name):
        # Do not reveal existence of another tenant's instance.
        raise HTTPException(status_code=404)
    return path


class JobManager:
    def __init__(self):
        self.lock = threading.Lock()
        self.cond = threading.Condition(self.lock)
        self.jobs = {}

    def _log_path(self, jid):
        return DATA_DIR / "jobs" / f"{jid}.txt"

    def _persist_meta(self, job):
        try:
            STORE.upsert_job(job)
        except Exception:
            logging.exception("Unable to persist Web Manager job metadata")

    def create(self, title, func, *args, owner_user_id=None, kind=None, **kwargs):
        jid = uuid.uuid4().hex[:12]
        job = {
            "id": jid, "title": title, "status": "queued", "created": time.time(),
            "finished": None, "output": "",
            "owner_user_id": int(owner_user_id) if owner_user_id is not None else None,
            "kind": kind,
        }
        with self.cond:
            self.jobs[jid] = job
            self._persist_meta(job)
            self.cond.notify_all()
        thread = threading.Thread(target=self._run, args=(jid, func, args, kwargs), daemon=True)
        thread.start()
        return jid

    def append(self, jid, text):
        text = str(text or "")
        if not text:
            return
        with self.cond:
            job = self.jobs.get(jid)
            if not job:
                return
            job["output"] += text
            self.cond.notify_all()
        try:
            path = self._log_path(jid)
            with path.open("a", encoding="utf-8") as f:
                f.write(text)
            os.chmod(path, 0o600)
        except Exception:
            pass

    def _run(self, jid, func, args, kwargs):
        with self.cond:
            self.jobs[jid]["status"] = "running"
            self._persist_meta(self.jobs[jid])
            self.cond.notify_all()
        _JOB_LOCAL.jid = jid
        try:
            result = func(*args, **kwargs)
            if result:
                self.append(jid, str(result) + ("" if str(result).endswith("\n") else "\n"))
            elif not self.get(jid).get("output"):
                self.append(jid, "เสร็จสิ้น\n")
            status = "success"
        except Exception as exc:
            self.append(jid, f"ERROR: {exc}\n")
            status = "failed"
        finally:
            _JOB_LOCAL.jid = None
        with self.cond:
            self.jobs[jid]["status"] = status
            self.jobs[jid]["finished"] = time.time()
            self._persist_meta(self.jobs[jid])
            self.cond.notify_all()

    def get(self, jid):
        with self.lock:
            live = self.jobs.get(jid)
            if live:
                return dict(live)
        log = self._log_path(jid)
        try:
            job = STORE.get_job(jid)
            if not job:
                return {}
            job["output"] = log.read_text(encoding="utf-8", errors="replace") if log.is_file() else ""
            return job
        except Exception:
            return {}

    def wait_change(self, jid, old_output_len, timeout=10):
        with self.cond:
            self.cond.wait_for(
                lambda: jid not in self.jobs or len(self.jobs[jid]["output"]) != old_output_len or self.jobs[jid]["status"] in ("success", "failed"),
                timeout=timeout,
            )
            return dict(self.jobs.get(jid) or {})


_JOB_LOCAL = threading.local()


def job_emit(text):
    jid = getattr(_JOB_LOCAL, "jid", None)
    if jid:
        jobs.append(jid, str(text) + ("" if str(text).endswith("\n") else "\n"))


def stream_command(args, *, timeout=1800, cwd=None):
    proc = subprocess.Popen(
        [str(x) for x in args],
        cwd=str(cwd) if cwd else None,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        bufsize=1,
    )
    started = time.time()
    assert proc.stdout is not None
    for line in proc.stdout:
        job_emit(line.rstrip("\n"))
        if time.time() - started > timeout:
            proc.kill()
            raise RuntimeError(f"Command timed out after {timeout}s")
    rc = proc.wait()
    if rc != 0:
        raise RuntimeError(f"Command failed with exit code {rc}: {' '.join(str(x) for x in args[:3])}")
    return rc


def stream_root(args, *, timeout=1800):
    return stream_command(["sudo", "-n", str(ROOT_BRIDGE), *[str(x) for x in args]], timeout=timeout)


jobs = JobManager()


def can_view_job(user, job):
    if not user or not job:
        return False
    if user.get("role") == "superadmin":
        return True
    owner = job.get("owner_user_id")
    return owner is not None and int(owner) == int(user["id"])


def _safe_return_to(value: str | None, fallback="/"):
    value=(value or "").strip()
    if not value.startswith("/") or value.startswith("//") or "\r" in value or "\n" in value:
        return fallback
    return value[:2048]


def job_created_response(request: Request, jid: str, fallback="/"):
    return_to=_safe_return_to(request.headers.get("X-SNTalkBot-Return-To"), fallback)
    if request.headers.get("X-SNTalkBot-Job-Dialog") == "1":
        job=jobs.get(jid)
        return JSONResponse({"ok":True,"job_id":jid,"job_url":f"/jobs/{jid}","stream_url":f"/jobs/{jid}/stream","return_to":return_to,"kind":job.get("kind"),"process_generation":PROCESS_GENERATION}, status_code=202)
    return RedirectResponse(f"/jobs/{jid}?return_to={urllib.parse.quote(return_to, safe='')}", status_code=303)


def job_install_stack():
    job_emit("Preflight: checking git/curl/python3/Docker before installing anything")
    stream_root(["install-stack"], timeout=1800)
    job_emit("Core Stack installation/repair complete")


def job_update_helper():
    job_emit("Updating TTUHelper from configured official repository")
    stream_root(["update-helper"], timeout=1800)


def job_update_web():
    job_emit("Updating Web Manager; the web service will restart at the end")
    stream_root(["update-web"], timeout=1200)


def job_helper_action(action, name=None):
    allowed = {"run", "stop", "restart", "delete", "start-all", "stop-all", "pull", "update", "doctor"}
    if action not in allowed:
        raise RuntimeError("Action is not allowed")
    args = ["helper", action]
    if name:
        if not BOT_NAME_RE.match(name):
            raise RuntimeError("Invalid instance name")
        args.append(name)
    stream_root(args, timeout=1800)



def get_config_template():
    rc, out = root_run(["bot-config-template"], timeout=60)
    if rc == 0 and "[server]" in out and "[bot]" in out:
        return out
    raise RuntimeError("ไม่สามารถอ่าน config_default.ini จาก SNTalkBot Docker image ได้ กรุณา Pull image แล้วลองใหม่")


def bot_image_version():
    if not docker_installed():
        return None
    rc, out = root_run(["bot-image-version"], timeout=60)
    if rc != 0:
        return None
    value = out.strip().splitlines()[-1] if out.strip() else ""
    return value if re.fullmatch(r"[0-9]+(?:\.[0-9]+){1,3}", value) else None


def create_instance(values: dict):
    name = str(values["name"]).strip()
    if not BOT_NAME_RE.match(name):
        raise RuntimeError("ชื่อ instance ไม่ถูกต้อง")
    root = bots_root()
    root.mkdir(parents=True, exist_ok=True)
    path = root / name
    if path.exists():
        raise RuntimeError(f"Instance {name} มีอยู่แล้ว")
    rc, out = root_run(["container-name-check", name], timeout=15)
    if rc != 0:
        raise RuntimeError(out.strip() or f"ชื่อ {name} ชนกับ Docker container ที่มีอยู่แล้ว กรุณาใช้ชื่อ instance อื่น")
    role = values.get("role", "full")
    if role not in ("full", "player", "manager"):
        raise RuntimeError("Bot role ไม่ถูกต้อง")
    player = role in ("full", "player")
    manager = role in ("full", "manager")
    cfg = configparser.ConfigParser(interpolation=None)
    cfg.read_string(get_config_template())
    def setv(section, key, value):
        if not cfg.has_section(section):
            cfg.add_section(section)
        cfg.set(section, key, str(value))
    setv("server", "address", values["hostname"])
    setv("server", "tcp_port", int(values.get("tcp_port") or 10333))
    setv("server", "udp_port", int(values.get("udp_port") or 10333))
    setv("server", "encrypted", "True" if values.get("encrypted") else "False")
    setv("server", "username", values.get("username", ""))
    setv("server", "password", values.get("password", ""))
    setv("bot", "language", values.get("language") or "th")
    setv("bot", "nickname", values.get("nickname") or "SN TalkBot")
    setv("bot", "default_channel", values.get("channel") or "/")
    setv("bot", "channel_password", values.get("channel_password", ""))
    setv("bot", "status_message", values.get("status_message") or "auto")
    setv("accounts", "authorized_users", values.get("authorized_users", ""))
    setv("accounts", "detect_server_admins", "True")
    setv("features", "player_enabled", "True" if player else "False")
    setv("features", "server_management_enabled", "True" if manager else "False")
    if not manager:
        setv("bot", "intercept_channel_messages", "False")
        setv("bot", "welcome_broadcast", "False")
        setv("bot", "welcome_mode", "0")
        setv("bot", "profanity_filter_enabled", "False")
    setv("playback", "cookiefile_path", "/app/data/cookies.txt")
    tmp = Path(tempfile.mkdtemp(prefix="snweb-new-"))
    try:
        cpath = tmp / "config.ini"
        with cpath.open("w", encoding="utf-8") as f:
            cfg.write(f)
        path.mkdir(mode=0o2770)
        shutil.copy2(cpath, path / "config.ini")
        (path / "instance.conf").write_text(
            f"image={image_name()}\ncreated={datetime.now(timezone.utc).isoformat()}\nmode={role}\n"
            f"player_enabled={'True' if player else 'False'}\nserver_management_enabled={'True' if manager else 'False'}\n",
            encoding="utf-8",
        )
        os.chmod(path / "config.ini", 0o660)
        os.chmod(path / "instance.conf", 0o640)
        try:
            os.chown(path, 10001, 10001)
            os.chown(path / "config.ini", 10001, 10001)
            os.chown(path / "instance.conf", 10001, 10001)
        except PermissionError:
            pass
        # Intentionally do not create cookies.txt. The bot image bootstraps its
        # bundled project default on first start; a future TTUHelper cks replaces it.
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    with _SNAPSHOT_LOCK:
        _SNAPSHOT_CACHE.pop("instances", None)
        _SNAPSHOT_CACHE.pop("containers", None)
    return path


CONFIG_ENUMS = {
    ("bot", "language"): [("ไทย", "th"), ("English", "en"), ("العربية", "ar"), ("العربية - مصر", "ar_EG"), ("Português", "pt")],
    ("bot", "welcome_mode"): [("ปิด", "0"), ("เปิด", "1")],
    ("bot", "gender"): [("ชาย", "0"), ("หญิง", "256"), ("เป็นกลาง", "4096")],
    ("bot", "char_limit_mode"): [("Kick ผู้ใช้", "1"), ("Ban ผู้ใช้", "2")],
    ("bot", "blacklist_mode"): [("Kick ผู้ใช้", "1"), ("Ban ผู้ใช้", "2")],
    ("playback", "channel_messages_mode"): [("ส่ง Private message", "private"), ("ไม่ส่งข้อความ", "silent")],
    ("playback", "audio_quality"): [("Low", "Low"), ("Medium", "Medium"), ("High", "High")],
    ("playback", "play_mode"): [("M1 — เล่นรายการเดียว", "1"), ("M2 — เล่นต่อ/Autoplay", "2"), ("M3 — เล่นเพลงเดิมซ้ำ", "3")],
    ("playback", "announcement_tts_mode"): [("Microsoft Edge TTS", "microsoft"), ("Google standard gTTS", "google")],
    ("tts", "mode"): [("Microsoft Edge TTS", "microsoft"), ("Google standard gTTS", "google")],
    ("accounts", "detection_mode"): [("Guest accounts only", "1"), ("All new accounts", "2"), ("Specific username", "3")],
    ("logging", "level"): [("DEBUG", "DEBUG"), ("INFO", "INFO"), ("WARNING", "WARNING"), ("ERROR", "ERROR"), ("CRITICAL", "CRITICAL")],
}

CONFIG_LABELS = {
    "default_channel": "Channel ID หรือ Channel path",
    "player_enabled": "เปิดฟังก์ชัน Player",
    "server_management_enabled": "เปิดฟังก์ชัน Server Manager",
    "persist_queue": "เก็บคิวข้าม Restart/Update",
    "resume_queue_on_start": "เล่นคิวต่ออัตโนมัติหลัง Restart",
    "queue_mode": "เปิด Queue Mode",
    "welcome_mode": "ต้อนรับเมื่อผู้ใช้เข้าห้องของบอต",
    "welcome_broadcast": "Global login welcome broadcast",
    "profanity_filter_enabled": "เปิดตัวกรองคำ",
    "channel_input_enabled": "รับคำสั่งจากข้อความในห้อง",
    "intercept_channel_messages": "ตรวจข้อความใน Channel ทั้งเซิร์ฟเวอร์",
    "tts_enabled": "เปิด Text-to-Speech",
    "vpn_detection": "ตรวจ VPN/Proxy",
    "prevent_noname": "ป้องกันชื่อ NoName",
    "enabled": "เปิดใช้งาน",
    "broadcast_enabled": "แจ้งเวอร์ชันผ่าน TeamTalk Global Broadcast",
    "telegram_enabled": "แจ้งเวอร์ชันผ่าน Telegram",
    "polling_fallback": "ใช้การตรวจ GitHub แบบ polling เป็น fallback",
    "interval_minutes": "ช่วงเวลาส่ง Global Broadcast (นาที)",
    "is_stereo_wide": "Stereo 3D 1 — Stereo Widen",
    "is_stereo_echo": "Stereo 3D 2 — Extra Stereo",
    "is_bass_boosted": "Bass Boost",
}


CONFIG_DESCRIPTIONS = {
    ("bot", "default_channel"): "ใส่ TeamTalk Channel ID เช่น 8 หรือค่าที่คัดลอกจาก gcid/cid ได้โดยตรง; หากใช้ชื่อห้องให้ใช้พาธแบบเดิม เช่น /music",
    ("playback", "persist_queue"): "คิวถูกเก็บใน SQLite/WAL และไม่มีเพดานจำนวนรายการระดับแอปพลิเคชัน จึงยังอยู่หลัง restart/update",
    ("playback", "resume_queue_on_start"): "ถ้าเปิด บอตจะเริ่มรายการคิวที่ค้างไว้หลังเปิดโปรแกรม; ถ้าปิด คิวยังอยู่แต่รอคำสั่ง p",
    ("playback", "queue_mode"): "เมื่อเปิด เพลงหรือรายการใหม่จะต่อท้าย FIFO queue แทนการแทรกการเล่นปัจจุบัน",
    ("playback", "play_mode"): "เลือกลักษณะการเล่นเมื่อไม่อยู่ใน Queue Mode",
    ("bot", "welcome_mode"): "ส่งข้อความต้อนรับเฉพาะ genuine join ในห้องเดียวกับบอต",
    ("bot", "welcome_broadcast"): "ส่งข้อความต้อนรับแบบ Global เมื่อผู้ใช้ login; แยกจากการต้อนรับในห้อง",
    ("bot", "profanity_filter_enabled"): "สวิตช์หลักของตัวกรอง blacklist หลายภาษา ทั้งข้อความ ชื่อ/สถานะ และ metadata ที่รองรับ",
    ("tts", "mode"): "เลือก engine TTS หลักของบอต โดยไม่ต้องจำค่าดิบใน config.ini",
    ("playback", "announcement_tts_mode"): "เลือก engine TTS สำหรับเสียงประกาศของ Player แยกจาก TTS หลัก",
    ("accounts", "detection_mode"): "กำหนดกลุ่มบัญชีที่ระบบตรวจจับ/automation ของ Manager จะนำไปใช้",
    ("account_requests", "enabled"): "เปิด workflow ขอสร้าง TeamTalk account และยืนยัน OTP ผ่าน Telegram",
    ("updates", "enabled"): "เปิดระบบแจ้งเตือนเมื่อ GitHub มี SNTalkBot release ใหม่ โดยไม่ติดตั้งให้อัตโนมัติ",
    ("updates", "polling_fallback"): "ปิดไว้เป็นค่าเริ่มต้นเมื่อใช้ GitHub webhook; เปิดเฉพาะเครื่องที่รับ webhook ไม่ได้",
    ("global_broadcast", "enabled"): "Manager/Full เท่านั้น: เปิดรับข้อความส่วนกลางจากฐานข้อมูล Web Manager; ค่าเริ่มต้นปิด",
    ("global_broadcast", "interval_minutes"): "กำหนดความถี่ของบอตนี้ 1-10080 นาที; ข้อความส่วนกลางแก้ไขได้จากเมนู Global Broadcast",
    ("global_broadcast", "tts_enabled"): "ใช้ข้อความ Central Global Broadcast ชุดเดียวกัน แต่ให้บอตพูดข้อความนั้นด้วย TTS ในห้องของบอต; ไม่มี messages.txt หรือ scheduler ข้อความชุดที่สอง",
    ("bot", "language"): "เลือกภาษาหลักจาก locale ที่ SNTalkBot มีอยู่จริง แทนการพิมพ์รหัสภาษาเอง",
    ("playback", "is_stereo_wide"): "ตรงกับคำสั่ง 3d: ใช้ FFmpeg Stereo Widen รุ่นปัจจุบันผ่าน mpv/libavfilter",
    ("playback", "is_stereo_echo"): "ตรงกับคำสั่ง 3d2: Extra Stereo เพิ่มความต่างซ้าย/ขวา; คงชื่อ key เดิมเพื่อ compatibility แต่เอฟเฟ็กต์ไม่ใช่ Echo",
    ("playback", "is_bass_boosted"): "ตรงกับคำสั่ง bass: Bass/Lowshelf แบบลดความเสี่ยง clipping จาก preset เก่า",
}



def _field_kind(section, key, value):
    sk = (section.lower(), key.lower())
    stripped = str(value or "").strip()
    # One field intentionally accepts either a numeric TeamTalk Channel ID or
    # a historical channel path. Never infer it as an integer field just
    # because the current value happens to be 8.
    if sk == ("bot", "default_channel"):
        return "text"
    if safe_secret_key(key):
        return "secret"
    if sk in CONFIG_ENUMS:
        return "choice"
    if stripped.lower() in ("true", "false"):
        return "bool"
    if re.fullmatch(r"-?\d+", stripped):
        return "int"
    if re.fullmatch(r"-?\d+(?:\.\d+)", stripped):
        return "float"
    return "text"


def _field_label(section, key):
    return CONFIG_LABELS.get(key.lower(), key.replace("_", " ").strip().title())


def _field_description(section, key):
    return CONFIG_DESCRIPTIONS.get(
        (section.lower(), key.lower()),
        f"ค่า {key} ในหมวด [{section}] ใช้กำหนดพฤติกรรมของฟีเจอร์นี้; ค่าเดิมจะถูกเก็บไว้ถ้าไม่ได้แก้ไข",
    )


def safe_secret_key(key):
    lk = key.lower()
    return any(token in lk for token in SECRET_KEYS)


def _ensure_web_managed_config_defaults(cfg):
    if not cfg.has_section("global_broadcast"):
        cfg.add_section("global_broadcast")

    # Upgrade old 5.1.12-and-earlier announcement settings in-memory so the Web
    # Manager never presents controls for the removed messages.txt scheduler.
    old_interval = None
    if cfg.has_section("bot") and cfg.has_option("bot", "random_message_interval"):
        try:
            old_interval = int(cfg.get("bot", "random_message_interval", fallback="0") or 0)
        except ValueError:
            old_interval = None
        cfg.remove_option("bot", "random_message_interval")
    old_tts = None
    if cfg.has_section("tts") and cfg.has_option("tts", "random_broadcast_enabled"):
        try:
            old_tts = cfg.getboolean("tts", "random_broadcast_enabled", fallback=False)
        except ValueError:
            old_tts = False
        cfg.remove_option("tts", "random_broadcast_enabled")

    if not cfg.has_option("global_broadcast", "enabled"):
        cfg.set("global_broadcast", "enabled", "False")
    if not cfg.has_option("global_broadcast", "interval_minutes"):
        mapped = max(1, min(10080, old_interval)) if old_interval and old_interval > 0 else 60
        cfg.set("global_broadcast", "interval_minutes", str(mapped))
    if not cfg.has_option("global_broadcast", "tts_enabled"):
        cfg.set("global_broadcast", "tts_enabled", "True" if old_tts else "False")
    return cfg


def config_for_form(path: Path, user=None):
    cfg = _ensure_web_managed_config_defaults(read_config(path / "config.ini"))
    is_superadmin = bool(user and user.get("role") == "superadmin")
    sections = []
    for section in cfg.sections():
        fields = []
        for key, value in cfg.items(section):
            kind = _field_kind(section, key, value)
            locked = (section.lower(), key.lower()) in TENANT_LOCKED_CONFIG_KEYS and not is_superadmin
            fields.append({
                "section": section, "key": key, "value": value, "kind": kind,
                "set": bool(value), "locked": locked,
                "label": _field_label(section, key),
                "description": _field_description(section, key),
                "options": CONFIG_ENUMS.get((section.lower(), key.lower()), []),
            })
        sections.append({"name": section, "fields": fields})
    return sections


def save_config_form(path: Path, form, user=None):
    cfg = _ensure_web_managed_config_defaults(read_config(path / "config.ini"))
    is_superadmin = bool(user and user.get("role") == "superadmin")
    clear_secrets = set(form.getlist("clear_secret"))
    for section in cfg.sections():
        for key, old in list(cfg.items(section)):
            field = f"cfg__{section}__{key}"
            kind = _field_kind(section, key, old)
            locked = (section.lower(), key.lower()) in TENANT_LOCKED_CONFIG_KEYS and not is_superadmin
            supplied = form.get(field)
            if locked:
                if supplied is not None:
                    if kind == "secret":
                        if str(supplied) or f"{section}.{key}" in clear_secrets:
                            raise HTTPException(status_code=403, detail="ผู้ใช้ทั่วไปไม่สามารถเปลี่ยน TeamTalk connection/login identity หลังยืนยันเจ้าของแล้ว")
                    elif kind == "bool":
                        submitted = "True" if supplied == "on" else "False"
                        if submitted.casefold() != str(old).casefold():
                            raise HTTPException(status_code=403, detail="ผู้ใช้ทั่วไปไม่สามารถเปลี่ยน TeamTalk connection/login identity หลังยืนยันเจ้าของแล้ว")
                    elif str(supplied) != str(old):
                        raise HTTPException(status_code=403, detail="ผู้ใช้ทั่วไปไม่สามารถเปลี่ยน TeamTalk connection/login identity หลังยืนยันเจ้าของแล้ว")
                continue
            if kind == "secret":
                secret_id = f"{section}.{key}"
                if secret_id in clear_secrets:
                    cfg.set(section, key, "")
                else:
                    new_value = str(form.get(field, ""))
                    if new_value:
                        cfg.set(section, key, new_value)
            elif kind == "bool":
                cfg.set(section, key, "True" if form.get(field) == "on" else "False")
            elif kind == "choice":
                value = str(form.get(field, old))
                allowed = {str(v) for _label, v in CONFIG_ENUMS[(section.lower(), key.lower())]}
                if value not in allowed:
                    raise HTTPException(status_code=400, detail=f"ค่าของ [{section}] {key} ไม่อยู่ในตัวเลือกที่อนุญาต")
                cfg.set(section, key, value)
            elif kind == "int":
                value = str(form.get(field, old)).strip()
                try:
                    number = int(value)
                except ValueError:
                    raise HTTPException(status_code=400, detail=f"[{section}] {key} ต้องเป็นจำนวนเต็ม")
                if (section.lower(), key.lower()) == ("global_broadcast", "interval_minutes") and not (1 <= number <= 10080):
                    raise HTTPException(status_code=400, detail="Global Broadcast interval ต้องอยู่ระหว่าง 1-10080 นาที")
                cfg.set(section, key, str(number))
            elif kind == "float":
                value = str(form.get(field, old)).strip()
                try: float(value)
                except ValueError: raise HTTPException(status_code=400, detail=f"[{section}] {key} ต้องเป็นตัวเลข")
                cfg.set(section, key, value)
            else:
                cfg.set(section, key, str(form.get(field, old)))
    tmp = path / "config.ini.tmp"
    with tmp.open("w", encoding="utf-8") as f:
        cfg.write(f)
    os.chmod(tmp, 0o660)
    os.replace(tmp, path / "config.ini")
    try:
        os.chown(path / "config.ini", 10001, 10001)
    except PermissionError:
        pass


def job_cookie_check(name):
    if not BOT_NAME_RE.match(name):
        raise RuntimeError("Invalid instance name")
    stream_root(["helper", "cks-check", name], timeout=120)

def job_cookies_all(source_path):
    stream_root(["helper","cks-all",source_path],timeout=180)

def logs_text(name, tail=250):
    tail = max(20, min(int(tail), 2000))
    rc, out = root_run(["docker-logs", name, str(tail)], timeout=20)
    return out if rc == 0 else out or "ไม่พบ log/container"


def local_image_digest():
    if not docker_installed():
        return None
    rc, out = root_run(["image-inspect", image_name()], timeout=15)
    if rc != 0:
        return None
    try:
        data = json.loads(out)[0]
        for value in data.get("RepoDigests") or []:
            if "@sha256:" in value:
                return value.split("@", 1)[1]
    except Exception:
        return None
    return None

def remote_image_digest():
    if not docker_installed():
        return None
    rc, out = root_run(["remote-image-inspect", image_name()], timeout=30)
    if rc != 0:
        return None
    match = re.search(r"^Digest:\s*(sha256:[0-9a-f]{64})", out, re.M | re.I)
    return match.group(1).lower() if match else None


def guardian_status():
    port = int(os.getenv("SNWEB_PORT", "28765") or 28765)
    try:
        req = urllib.request.Request(f"http://127.0.0.1:{port}/guardian-healthz", headers={"Accept":"application/json"})
        with urllib.request.urlopen(req, timeout=0.6) as resp:
            data=json.loads(resp.read(65536).decode("utf-8","replace"))
        if data.get("ok"):
            return data
    except Exception:
        pass
    return None


def system_status(include_remote=False, include_expensive=True):
    """Collect system summary without letting one probe take down the dashboard."""
    warnings = []

    def probe(label, func, default=None):
        try:
            return func()
        except Exception as exc:
            LOGGER.exception("system status probe failed: %s", label)
            warnings.append(f"{label}: {type(exc).__name__}")
            return default

    settings = probe("TTUHelper settings", helper_settings, {
        "TTU_IMAGE_REPO": IMAGE_REPO_DEFAULT,
        "TTU_TAG": IMAGE_TAG_DEFAULT,
        "TTU_BOTS_ROOT": str(DEFAULT_BOTS_ROOT),
    }) or {}
    repo = settings.get("TTU_IMAGE_REPO") or IMAGE_REPO_DEFAULT
    tag = settings.get("TTU_TAG") or IMAGE_TAG_DEFAULT
    root = settings.get("TTU_BOTS_ROOT") or str(DEFAULT_BOTS_ROOT)
    data = {
        "web_version": VERSION,
        "helper_installed": probe("TTUHelper installed", helper_installed, False),
        "helper_version": probe("TTUHelper version", helper_version),
        "helper_remote": None,
        "web_remote": None,
        "bot_image_version": probe("SNTalkBot image version", bot_image_version) if include_expensive else None,
        "docker_installed": probe("Docker installed", docker_installed, False),
        "image": f"{repo}:{tag}",
        "local_image_digest": probe("local image digest", local_image_digest) if include_expensive else None,
        "remote_image_digest": None,
        "bots_root": root,
        "helper_source": str(TTU_SOURCE),
        "guardian": probe("Guardian health", guardian_status),
        "warnings": warnings,
    }
    if include_remote:
        data["web_remote"] = probe("Web Manager remote version", lambda: remote_version(WEB_REPO))
        data["helper_remote"] = probe("TTUHelper remote version", lambda: remote_version(TTU_REPO))
        data["remote_image_digest"] = probe("remote image digest", remote_image_digest)
    return data


@app.exception_handler(HTTPException)
async def http_exc(request: Request, exc: HTTPException):
    if exc.status_code == 303:
        return RedirectResponse(exc.headers.get("Location", "/login"), status_code=303)
    return PlainTextResponse(str(exc.detail), status_code=exc.status_code)


@app.exception_handler(Exception)
async def unhandled_exc(request: Request, exc: Exception):
    request_id=uuid.uuid4().hex[:12]
    LOGGER.exception("Unhandled Web Manager error request_id=%s path=%s", request_id, request.url.path)
    return HTMLResponse(
        _last_resort_error_html(request_id),
        status_code=500,
        headers={"X-SNTalkBot-Request-ID": request_id},
    )


def login_key(request: Request, username: str):
    host = request.client.host if request.client else "unknown"
    return f"{host}|{username}"

def login_blocked(request: Request, username: str):
    key = login_key(request, username)
    now = time.time()
    with _LOGIN_LOCK:
        rows = [t for t in _LOGIN_FAILURES.get(key, []) if now - t < LOGIN_WINDOW]
        _LOGIN_FAILURES[key] = rows
        return len(rows) >= LOGIN_MAX_FAILURES

def login_failed(request: Request, username: str):
    key = login_key(request, username)
    now = time.time()
    with _LOGIN_LOCK:
        rows = [t for t in _LOGIN_FAILURES.get(key, []) if now - t < LOGIN_WINDOW]
        rows.append(now); _LOGIN_FAILURES[key] = rows[-LOGIN_MAX_FAILURES:]

def login_succeeded(request: Request, username: str):
    with _LOGIN_LOCK:
        _LOGIN_FAILURES.pop(login_key(request, username), None)

@app.get("/setup", response_class=HTMLResponse)
def setup_page(request: Request):
    if not setup_required():
        return RedirectResponse("/login", status_code=303)
    return templates.TemplateResponse("setup.html", {"request": request, "error": None, "version": VERSION})


@app.post("/setup", response_class=HTMLResponse)
async def setup_submit(request: Request, username: str = Form(...), display_name: str = Form(""), password: str = Form(...), password2: str = Form(...)):
    if not setup_required():
        raise HTTPException(status_code=403, detail="Initial setup is already complete")
    username=username.strip()
    if not WEB_USERNAME_RE.fullmatch(username):
        return templates.TemplateResponse("setup.html", {"request": request, "error": "ชื่อผู้ใช้ต้องยาว 3-64 ตัว และใช้ A-Z a-z 0-9 _ . -", "version": VERSION}, status_code=400)
    if password != password2:
        return templates.TemplateResponse("setup.html", {"request": request, "error": "รหัสผ่านสองช่องไม่ตรงกัน", "version": VERSION}, status_code=400)
    try:
        user=STORE.create_first_superadmin(username,password,display_name=display_name)
    except Exception as exc:
        return templates.TemplateResponse("setup.html", {"request": request, "error": str(exc), "version": VERSION}, status_code=400)
    # Existing instances predate multi-user ownership; first superadmin claims them.
    root=bots_root()
    names=[x.name for x in root.iterdir()] if root.is_dir() else []
    STORE.claim_unowned(names,int(user["id"]))
    request.session.clear(); request.session["user_id"]=int(user["id"]); request.session["csrf"]=secrets.token_urlsafe(32)
    return RedirectResponse("/", status_code=303)


@app.get("/login", response_class=HTMLResponse)
def login_page(request: Request):
    if current_user(request):
        return RedirectResponse("/", status_code=303)
    if setup_required():
        return RedirectResponse("/setup", status_code=303)
    return templates.TemplateResponse("login.html", {"request": request, "error": None, "version": VERSION})


@app.post("/login", response_class=HTMLResponse)
async def login(request: Request, username: str = Form(...), password: str = Form(...)):
    if setup_required():
        return RedirectResponse("/setup", status_code=303)
    if login_blocked(request, username):
        return templates.TemplateResponse("login.html", {"request": request, "error": "พยายามเข้าสู่ระบบผิดหลายครั้ง กรุณารอประมาณ 5 นาทีแล้วลองใหม่", "version": VERSION}, status_code=429)
    user=STORE.verify(username,password)
    if user:
        login_succeeded(request, username)
        request.session.clear(); request.session["user_id"]=int(user["id"]); request.session["csrf"]=secrets.token_urlsafe(32)
        return RedirectResponse("/", status_code=303)
    login_failed(request, username)
    return templates.TemplateResponse("login.html", {"request": request, "error": "ชื่อผู้ใช้หรือรหัสผ่านไม่ถูกต้อง", "version": VERSION}, status_code=401)


@app.post("/logout")
async def logout(request: Request, csrf: str = Form(...)):
    require_login(request); check_csrf(request, csrf); request.session.clear(); return RedirectResponse("/login", status_code=303)


@app.get("/users", response_class=HTMLResponse)
def users_page(request: Request):
    user=require_superadmin(request)
    return templates.TemplateResponse("users.html", {"request":request,"user":user,"current_user":user,"users":STORE.list_users(),"csrf":csrf_token(request),"version":VERSION,"error":None})


@app.post("/users/create", response_class=HTMLResponse)
async def users_create(request: Request, csrf: str = Form(...), username: str = Form(...), display_name: str = Form(""), teamtalk_admin_username: str = Form(""), password: str = Form(...)):
    admin=require_superadmin(request); check_csrf(request,csrf); username=username.strip()
    if not WEB_USERNAME_RE.fullmatch(username):
        raise HTTPException(status_code=400,detail="ชื่อผู้ใช้ต้องยาว 3-64 ตัว และใช้ A-Z a-z 0-9 _ . -")
    try: STORE.create_user(username,password,role="user",display_name=display_name,teamtalk_admin_username=teamtalk_admin_username,created_by=int(admin["id"]))
    except Exception as exc: raise HTTPException(status_code=400,detail=str(exc))
    return RedirectResponse("/users",status_code=303)


@app.post("/users/{user_id}/teamtalk")
async def users_teamtalk(request: Request, user_id: int, csrf: str = Form(...), teamtalk_admin_username: str = Form("")):
    admin=require_superadmin(request); check_csrf(request,csrf)
    target=STORE.get_user(user_id)
    if not target: raise HTTPException(status_code=404)
    if target.get("role") == "superadmin" and int(target["id"]) == int(admin["id"]):
        # Super Admin never needs a TeamTalk mapping to create instances. Keeping
        # this editable is harmless, but it is not used as an authorization gate.
        pass
    STORE.set_teamtalk_admin_username(user_id, teamtalk_admin_username)
    return RedirectResponse("/users",status_code=303)


@app.post("/users/{user_id}/password")
async def users_password(request: Request, user_id: int, csrf: str = Form(...), password: str = Form(...)):
    require_superadmin(request); check_csrf(request,csrf)
    try: STORE.set_password(user_id,password)
    except Exception as exc: raise HTTPException(status_code=400,detail=str(exc))
    return RedirectResponse("/users",status_code=303)


@app.post("/users/{user_id}/toggle")
async def users_toggle(request: Request, user_id: int, csrf: str = Form(...)):
    admin=require_superadmin(request); check_csrf(request,csrf)
    if int(admin["id"])==int(user_id): raise HTTPException(status_code=400,detail="ไม่สามารถปิดบัญชี Super Admin ที่กำลังใช้งานอยู่")
    target=STORE.get_user(user_id)
    if not target: raise HTTPException(status_code=404)
    STORE.set_active(user_id, not bool(target["active"]))
    return RedirectResponse("/users",status_code=303)


def central_telegram_status():
    rc, out = root_run(["central-telegram-status"], timeout=10)
    if rc != 0:
        return {"configured": False, "default_chat_id": "", "error": "อ่านการตั้งค่า Telegram ส่วนกลางไม่สำเร็จ"}
    try:
        data = json.loads((out or "").strip().splitlines()[-1])
    except Exception:
        return {"configured": False, "default_chat_id": "", "error": "รูปแบบสถานะ Telegram ส่วนกลางไม่ถูกต้อง"}
    return {
        "configured": bool(data.get("configured")),
        "default_chat_id": str(data.get("default_chat_id") or ""),
        "error": None,
    }


def _version_at_least(value, minimum):
    try:
        left = tuple(int(x) for x in str(value or "0").split("."))
        right = tuple(int(x) for x in str(minimum).split("."))
        width = max(len(left), len(right))
        return left + (0,) * (width - len(left)) >= right + (0,) * (width - len(right))
    except Exception:
        return False


def job_apply_central_telegram(payload: dict, apply_running: bool):
    rc, out = root_run_stdin(["central-telegram-set"], payload, timeout=20, check=False)
    try:
        data = json.loads((out or "").strip().splitlines()[-1])
    except Exception:
        data = {}
    if rc != 0 or not data.get("ok"):
        raise RuntimeError(str(data.get("error") or "บันทึก Telegram ส่วนกลางไม่สำเร็จ"))
    job_emit("[OK] บันทึก Telegram ส่วนกลางแบบ root-only แล้ว; token ไม่ถูกแสดงในผลลัพธ์")
    if not apply_running:
        job_emit("ยังไม่ได้ Restart บอตที่กำลังรัน; ค่าใหม่จะมีผลเมื่อบอตถูกสร้าง/Restart ครั้งถัดไป")
        return
    hv = helper_version()
    if not _version_at_least(hv, "1.5.7"):
        job_emit(f"[WARNING] TTUHelper {hv or 'unknown'} ยังเก่ากว่า 1.5.7; อัปเดต TTUHelper แล้วกดอัปเดตบอตที่กำลังรันเพื่อให้ค่า Telegram ส่วนกลางเข้า container")
        return
    job_emit("กำลังใช้ค่า Telegram ส่วนกลางกับบอตที่กำลังรัน โดยรักษา config/SQLite/queue เดิม")
    stream_root(["helper", "update"], timeout=1800)


@app.get("/telegram", response_class=HTMLResponse)
def central_telegram_page(request: Request):
    user = require_superadmin(request)
    return templates.TemplateResponse("telegram.html", {
        "request": request, "user": user, "telegram": central_telegram_status(),
        "helper_version": helper_version(), "csrf": csrf_token(request), "version": VERSION,
    })


@app.post("/telegram")
async def central_telegram_save(
    request: Request, csrf: str = Form(...), token: str = Form(""),
    default_chat_id: str = Form(""), clear_token: str | None = Form(None),
    apply_running: str | None = Form(None),
):
    user = require_superadmin(request); check_csrf(request, csrf)
    payload = {"default_chat_id": str(default_chat_id or "").strip(), "clear_token": bool(clear_token)}
    if str(token or "").strip():
        payload["token"] = str(token).strip()
    jid = jobs.create(
        "บันทึก Telegram ส่วนกลาง", job_apply_central_telegram, payload, bool(apply_running),
        owner_user_id=int(user["id"]), kind="central-telegram",
    )
    return job_created_response(request, jid, "/telegram")


@app.get("/broadcasts", response_class=HTMLResponse)
def global_broadcasts_page(request: Request):
    user = require_superadmin(request)
    return templates.TemplateResponse("broadcasts.html", {
        "request": request, "user": user,
        "messages": STORE.list_global_broadcast_messages(),
        "csrf": csrf_token(request), "version": VERSION,
    })


@app.post("/broadcasts")
async def global_broadcasts_create(request: Request):
    require_superadmin(request)
    form = await request.form()
    check_csrf(request, str(form.get("csrf") or ""))
    messages = [str(value or "").strip() for value in form.getlist("message")]
    messages = [message for message in messages if message]
    try:
        STORE.create_global_broadcast_messages(messages, enabled=bool(form.get("enabled")))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return RedirectResponse("/broadcasts", status_code=303)


@app.post("/broadcasts/bulk")
async def global_broadcasts_legacy_bulk_create(
    request: Request, csrf: str = Form(...), messages: str = Form(...), enabled: str | None = Form(None)
):
    """Compatibility endpoint for the short-lived 1.1.18 form.

    One textarea is now always one message, including its line breaks.  This
    deliberately stops the old line-splitting interpretation.
    """
    require_superadmin(request); check_csrf(request, csrf)
    try:
        STORE.create_global_broadcast_message(messages, enabled=bool(enabled))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return RedirectResponse("/broadcasts", status_code=303)


@app.post("/broadcasts/{message_id}/update")
async def global_broadcasts_update(request: Request, message_id: int, csrf: str = Form(...), message: str = Form(...), enabled: str | None = Form(None)):
    require_superadmin(request); check_csrf(request, csrf)
    try:
        if not STORE.update_global_broadcast_message(message_id, message=message, enabled=bool(enabled)):
            raise HTTPException(status_code=404)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return RedirectResponse("/broadcasts", status_code=303)


@app.post("/broadcasts/{message_id}/delete")
async def global_broadcasts_delete(request: Request, message_id: int, csrf: str = Form(...)):
    require_superadmin(request); check_csrf(request, csrf)
    STORE.delete_global_broadcast_message(message_id)
    return RedirectResponse("/broadcasts", status_code=303)


@app.get("/", response_class=HTMLResponse)
def dashboard(request: Request):
    user=require_login(request)
    page_warnings=[]
    try:
        instances=list_instances(user, include_live=False, force_snapshot=True)
    except Exception as exc:
        LOGGER.exception("dashboard instance enumeration failed")
        instances=[]
        page_warnings.append(f"อ่านรายการ instance ไม่สำเร็จ ({type(exc).__name__})")
    try:
        system=system_status(False, include_expensive=False)
        page_warnings.extend(system.get("warnings") or [])
    except Exception as exc:
        LOGGER.exception("dashboard system summary failed")
        system={"helper_version":None,"docker_installed":False,"image":image_name(),"helper_installed":False,"warnings":[]}
        page_warnings.append(f"อ่านสถานะระบบไม่สำเร็จ ({type(exc).__name__})")
    return templates.TemplateResponse("dashboard.html", {
        "request": request, "user":user, "instances": instances, "system": system,
        "page_warnings":page_warnings, "csrf": csrf_token(request), "version": VERSION,
    })


def _dashboard_runtime_payload(row):
    live = row.get("runtime") if isinstance(row.get("runtime"), dict) else None
    return {
        "name": row.get("name"),
        "running": bool(row.get("running")),
        "container_status": (row.get("container") or {}).get("status") if isinstance(row.get("container"), dict) else None,
        "runtime": live,
    }


async def _dashboard_live_rows(user):
    rows = await asyncio.to_thread(list_instances, user, include_live=False)
    running = [row for row in rows if row.get("running")]
    if running:
        states = await asyncio.gather(*[
            asyncio.to_thread(live_state, bots_root() / str(row["name"]), running=True)
            for row in running
        ], return_exceptions=True)
        for row, state in zip(running, states):
            row["runtime"] = None if isinstance(state, Exception) else state
    return rows


@app.get("/dashboard/live")
async def dashboard_live(request: Request):
    user = require_login(request)
    async def events():
        last = None
        while True:
            if await request.is_disconnected():
                break
            try:
                rows = await _dashboard_live_rows(user)
                payload = {"instances": [_dashboard_runtime_payload(row) for row in rows], "server_epoch": time.time()}
                encoded = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
                if encoded != last:
                    last = encoded
                    yield "data: " + encoded + "\n\n"
            except Exception as exc:
                LOGGER.exception("dashboard live stream failed")
                yield "event: warning\ndata: " + json.dumps({"message": type(exc).__name__}) + "\n\n"
            await asyncio.sleep(1.0)
    return StreamingResponse(events(), media_type="text/event-stream", headers={"Cache-Control":"no-cache","X-Accel-Buffering":"no"})


def remote_update_status():
    # All network/Docker-heavy checks run outside the initial HTML request and in
    # parallel. The System page is immediately keyboard/screen-reader usable.
    with concurrent.futures.ThreadPoolExecutor(max_workers=5) as pool:
        fw = pool.submit(remote_version, WEB_REPO)
        fh = pool.submit(remote_version, TTU_REPO)
        fri = pool.submit(remote_image_digest)
        fli = pool.submit(local_image_digest)
        fbv = pool.submit(bot_image_version)
        return {
            "web_remote": fw.result(),
            "helper_remote": fh.result(),
            "remote_image_digest": fri.result(),
            "local_image_digest": fli.result(),
            "bot_image_version": fbv.result(),
        }


@app.get("/system/remote-status")
async def system_remote_status(request: Request):
    require_superadmin(request)
    data = await asyncio.to_thread(remote_update_status)
    return JSONResponse({"ok": True, **data})


@app.get("/help", response_class=HTMLResponse)
def help_page(request: Request):
    user=require_login(request)
    return templates.TemplateResponse("help.html", {"request": request, "user":user, "csrf": csrf_token(request), "version": VERSION})

def _public_base_url(request: Request):
    explicit = os.getenv("SNWEB_PUBLIC_BASE_URL", "").strip().rstrip("/")
    if explicit:
        return explicit
    proto = str(request.headers.get("x-forwarded-proto") or request.url.scheme or "https").split(",", 1)[0].strip()
    host = str(request.headers.get("x-forwarded-host") or request.headers.get("host") or request.url.netloc).split(",", 1)[0].strip()
    return f"{proto}://{host}".rstrip("/")

def github_webhook_status(request: Request):
    return {
        "configured": bool(_github_webhook_secret()),
        "callback_url": _public_base_url(request) + "/hooks/github/release",
        "repository": GITHUB_REPOSITORY,
        "last": STORE.get_system_state("github_release_webhook", {}) or {},
    }

def release_notification_rows():
    rows=[]
    root=bots_root()
    if not root.is_dir():
        return rows
    for path in sorted(root.iterdir(), key=lambda x: x.name.lower()):
        if not path.is_dir() or not BOT_NAME_RE.fullmatch(path.name) or not (path / "config.ini").is_file():
            continue
        try:
            cfg=_ensure_web_managed_config_defaults(read_config(path / "config.ini"))
            role=read_instance_role(path, cfg)
        except Exception:
            continue
        if role not in ("manager", "full"):
            continue
        rows.append({
            "name": path.name, "role": role,
            "enabled": cfg.getboolean("updates", "enabled", fallback=False),
            "broadcast_enabled": cfg.getboolean("updates", "broadcast_enabled", fallback=True),
        })
    return rows

def job_enable_release_notifications():
    rows=release_notification_rows()
    changed=0
    restarted=0
    for row in rows:
        path=bots_root() / row["name"]
        cfg=_ensure_web_managed_config_defaults(read_config(path / "config.ini"))
        if not cfg.has_section("updates"):
            cfg.add_section("updates")
        before=(cfg.getboolean("updates","enabled",fallback=False), cfg.getboolean("updates","broadcast_enabled",fallback=True))
        cfg.set("updates", "enabled", "True")
        cfg.set("updates", "broadcast_enabled", "True")
        cfg.set("updates", "repository", GITHUB_REPOSITORY)
        tmp=path / "config.ini.tmp"
        with tmp.open("w", encoding="utf-8") as f:
            cfg.write(f)
        os.chmod(tmp, 0o660)
        os.replace(tmp, path / "config.ini")
        try:
            os.chown(path / "config.ini", 10001, 10001)
        except PermissionError:
            pass
        if before != (True, True):
            changed += 1
        cont=docker_container(row["name"]) or {}
        if cont.get("running"):
            job_emit(f"Restart {row['name']} เพื่อใช้การแจ้ง GitHub Release")
            job_helper_action("restart", row["name"])
            restarted += 1
    job_emit(f"เปิดการแจ้ง GitHub Release สำหรับ Manager/Full {len(rows)} instance; เปลี่ยนค่า {changed}; restart {restarted}")

@app.get("/system", response_class=HTMLResponse)
def system_page(request: Request):
    user=require_superadmin(request)
    return templates.TemplateResponse("system.html", {"request": request, "user":user, "system": system_status(False, include_expensive=False), "webhook": github_webhook_status(request), "release_bots": release_notification_rows(), "csrf": csrf_token(request), "version": VERSION})


@app.post("/system/action")
async def system_action(request: Request, action: str = Form(...), csrf: str = Form(...)):
    user=require_superadmin(request); check_csrf(request, csrf)
    mapping = {
        "install-stack": ("ติดตั้ง/ตรวจ Core Stack", job_install_stack, ()),
        "update-helper": ("อัปเดต TTUHelper", job_update_helper, ()),
        "update-web": ("อัปเดต Web Manager", job_update_web, ()),
        "pull-image": ("ดาวน์โหลด SNTalkBot image", job_helper_action, ("pull",)),
        "update-running": ("อัปเดต SNTalkBot ที่กำลังรัน", job_helper_action, ("update",)),
        "doctor": ("ตรวจระบบ", job_helper_action, ("doctor",)),
        "start-all": ("เริ่มบอตทั้งหมด", job_helper_action, ("start-all",)),
        "stop-all": ("หยุดบอตทั้งหมด", job_helper_action, ("stop-all",)),
        "enable-release-notifications": ("เปิดการแจ้ง GitHub Release", job_enable_release_notifications, ()),
    }
    if action not in mapping:
        raise HTTPException(status_code=400, detail="Unknown action")
    title, func, args = mapping[action]
    jid = jobs.create(title, func, *args, owner_user_id=int(user["id"]), kind=action)
    return job_created_response(request, jid, "/system")


@app.get("/jobs/{jid}", response_class=HTMLResponse)
def job_page(request: Request, jid: str, return_to: str = "/"):
    user=require_login(request)
    job = jobs.get(jid)
    if not job or not can_view_job(user, job):
        raise HTTPException(status_code=404)
    return templates.TemplateResponse("job.html", {"request": request, "user":user, "job": job, "csrf": csrf_token(request), "version": VERSION, "process_generation": PROCESS_GENERATION, "return_to": _safe_return_to(return_to)})


@app.get("/jobs/{jid}/status")
def job_status(request: Request, jid: str):
    user=require_login(request)
    job=jobs.get(jid)
    if not job or not can_view_job(user, job):
        raise HTTPException(status_code=404)
    return JSONResponse({"id":job.get("id"),"title":job.get("title"),"status":job.get("status"),"output":job.get("output", ""),"kind":job.get("kind")})


@app.get("/jobs/{jid}/stream")
async def job_stream(request: Request, jid: str):
    user=require_login(request)
    initial=jobs.get(jid)
    if not initial or not can_view_job(user, initial):
        raise HTTPException(status_code=404)
    async def generate():
        last=-1
        while True:
            job=jobs.get(jid)
            if not job:
                yield "event: error\ndata: {}\n\n"; return
            payload=json.dumps(job,ensure_ascii=False)
            if len(job.get("output", "")) != last:
                last=len(job.get("output", ""))
                yield f"data: {payload}\n\n"
            if job.get("status") in ("success","failed"):
                return
            await asyncio.sleep(0.5)
    return StreamingResponse(generate(),media_type="text/event-stream",headers={"Cache-Control":"no-cache","X-Accel-Buffering":"no"})


def verify_teamtalk_admin_credentials(values: dict, username: str, password: str):
    """Prove a tenant controls an Administrator account on the target server.

    The credential is used for one short TeamTalk login in an ephemeral Docker
    container.  The password is never stored and never appears in argv/job logs.
    """
    username=str(username or "").strip()
    if not username:
        raise RuntimeError("ต้องระบุ TeamTalk Administrator username สำหรับยืนยันสิทธิ์")
    if password is None or password == "":
        raise RuntimeError("ต้องระบุรหัสผ่าน TeamTalk Administrator สำหรับยืนยันสิทธิ์")
    job_emit(f"กำลังยืนยัน TeamTalk Administrator {username} บนเซิร์ฟเวอร์เป้าหมายด้วยการ login ชั่วคราว")
    payload={
        "hostname":str(values.get("hostname") or ""),
        "tcp_port":int(values.get("tcp_port") or 10333),
        "udp_port":int(values.get("udp_port") or 10333),
        "encrypted":bool(values.get("encrypted")),
        "username":username,
        "password":password,
    }
    rc,out=root_run_stdin(["verify-teamtalk-admin"],payload,timeout=40,check=False)
    try:
        data=json.loads((out or "").strip().splitlines()[-1])
    except Exception:
        data={}
    if rc or not data.get("ok") or not data.get("administrator"):
        raise RuntimeError(str(data.get("error") or "ยืนยัน TeamTalk Administrator ไม่สำเร็จ กรุณาตรวจ server/port/username/password"))
    verified=str(data.get("username") or username).strip()
    job_emit(f"[OK] login สำเร็จและยืนยันว่า {verified} เป็น TeamTalk Administrator จริง")
    return verified


def job_create_verified(values: dict, owner_user_id: int, verification_username: str, verification_password: str, start_now: bool, require_owner_verification: bool = True):
    name=str(values["name"]).strip()
    path=None
    verified_username=str(verification_username or "").strip()
    try:
        # Verify before creating persistent bot files. A failed credential proof
        # therefore leaves no half-created instance behind.
        if require_owner_verification:
            verified_username=verify_teamtalk_admin_credentials(values,verification_username,verification_password)
        else:
            job_emit("[OK] Super Admin ของเว็บ: ข้าม TeamTalk owner credential verification")
        auth=[x.strip() for x in str(values.get("authorized_users") or "").split(',') if x.strip()]
        if verified_username and verified_username.casefold() not in {x.casefold() for x in auth}:
            auth.append(verified_username)
        values=dict(values)
        values["authorized_users"]=",".join(auth)
        job_emit(f"สร้าง instance {name}")
        path=create_instance(values)
        STORE.set_owner(name,owner_user_id,verified_username)
        if start_now:
            job_emit("เริ่มบอตตามคำขอ")
            job_helper_action("run",name)
        job_emit("สร้าง instance สำเร็จ" if not require_owner_verification else "สร้างและยืนยันเจ้าของ instance สำเร็จ")
    except Exception:
        if path is not None and path.exists():
            job_emit("การสร้างไม่สำเร็จ: กำลังล้าง instance ที่สร้างค้างไว้")
            try: job_helper_action("delete",name)
            except Exception as cleanup: job_emit(f"WARNING cleanup failed: {cleanup}")
            STORE.delete_owner(name)
        raise


@app.get("/instances/new", response_class=HTMLResponse)
def new_instance_page(request: Request):
    user=require_login(request)
    return templates.TemplateResponse("new_instance.html", {"request": request, "user":user, "csrf": csrf_token(request), "version": VERSION, "mapped_teamtalk_username": str(user.get("teamtalk_admin_username") or "")})


@app.post("/instances/new")
async def new_instance(
    request: Request, csrf: str = Form(...), name: str = Form(...), role: str = Form(...), nickname: str = Form("SN TalkBot"),
    hostname: str = Form(...), tcp_port: int = Form(10333), udp_port: int = Form(10333), encrypted: str | None = Form(None),
    username: str = Form(""), password: str = Form(""), channel: str = Form("/"), channel_password: str = Form(""),
    authorized_users: str = Form(""), owner_teamtalk_username: str = Form(""),
    verify_teamtalk_username: str = Form(""), verify_teamtalk_password: str = Form(""),
    language: str = Form("th"), status_message: str = Form("auto"), start_now: str | None = Form(None),
):
    user=require_login(request); check_csrf(request, csrf)
    name=name.strip()
    if not NEW_BOT_NAME_RE.fullmatch(name):
        raise HTTPException(status_code=400, detail="ชื่อ instance ใหม่ต้องใช้ตัวพิมพ์เล็ก a-z, 0-9, _, . หรือ - เท่านั้น ยาวไม่เกิน 63 ตัว ห้ามเว้นวรรค/สแลช และต้องขึ้นต้นด้วยตัวอักษรหรือตัวเลข")
    if not hostname.strip(): raise HTTPException(status_code=400, detail="TeamTalk hostname/IP is required")
    if not (1 <= tcp_port <= 65535 and 1 <= udp_port <= 65535): raise HTTPException(status_code=400, detail="Port must be 1-65535")
    is_superadmin = user.get("role") == "superadmin"
    # Web identity and TeamTalk identity are intentionally independent. Tenants
    # prove control themselves with a one-shot Administrator login; Super Admin
    # may create on any target server without this tenant authorization gate.
    owner_tt = owner_teamtalk_username.strip() if is_superadmin else verify_teamtalk_username.strip()
    if not is_superadmin and not owner_tt:
        raise HTTPException(status_code=400,detail="กรุณาระบุ TeamTalk Administrator username สำหรับยืนยันสิทธิ์")
    if not is_superadmin and not verify_teamtalk_password:
        raise HTTPException(status_code=400,detail="กรุณาระบุรหัสผ่าน TeamTalk Administrator สำหรับยืนยันสิทธิ์")
    auth=[x.strip() for x in authorized_users.split(',') if x.strip()]
    values={
        "name":name,"role":role,"nickname":nickname,"hostname":hostname,"tcp_port":tcp_port,"udp_port":udp_port,
        "encrypted":bool(encrypted),"username":username,"password":password,"channel":channel,"channel_password":channel_password,
        "authorized_users":",".join(auth),"language":language,"status_message":status_message,
    }
    jid=jobs.create(
        f"สร้าง {name}" if is_superadmin else f"สร้างและยืนยัน {name}",
        job_create_verified,values,int(user["id"]),owner_tt,
        "" if is_superadmin else verify_teamtalk_password,bool(start_now),not is_superadmin,
        owner_user_id=int(user["id"]),
    )
    return job_created_response(request, jid, "/instances/new")


@app.get("/instances/{name}", response_class=HTMLResponse)
def instance_page(request: Request, name: str, created: int = 0):
    user=require_login(request)
    path = instance_or_404(name,user)
    cfg = read_config(path / "config.ini")
    data = {
        "name": name, "path": str(path), "role": read_instance_role(path, cfg),
        "nickname": cfg.get("bot", "nickname", fallback=name),
        "server": cfg.get("server", "address", fallback=""),
        "default_channel": cfg.get("bot", "default_channel", fallback="/"),
        "container": docker_container(name), "runtime": None, "owner": STORE.owner(name),
    }
    data["runtime"] = live_state(path, running=bool(data["container"] and data["container"]["running"]))
    return templates.TemplateResponse("instance.html", {"request": request, "user":user, "bot": data, "created": created, "csrf": csrf_token(request), "version": VERSION})


@app.post("/instances/{name}/action")
async def instance_action(request: Request, name: str, action: str = Form(...), csrf: str = Form(...), confirm_name: str = Form("")):
    user=require_login(request); check_csrf(request, csrf); instance_or_404(name,user)
    if action not in ("run", "stop", "restart", "delete"):
        raise HTTPException(status_code=400, detail="Unknown instance action")
    if action == "delete":
        cont=docker_container(name)
        if cont and cont.get("running"):
            raise HTTPException(status_code=409,detail="ต้องหยุด instance ก่อนจึงจะลบได้")
        if confirm_name != name:
            raise HTTPException(status_code=400,detail="การลบต้องพิมพ์ชื่อ instance ให้ตรงทุกตัวอักษร")
    def work():
        job_helper_action(action,name)
        if action=="delete": STORE.delete_owner(name)
    jid = jobs.create(f"{action} {name}", work, owner_user_id=int(user["id"]))
    return job_created_response(request, jid, f"/instances/{name}")


@app.get("/instances/{name}/live")
async def instance_live(request: Request, name: str):
    user=require_login(request); path=instance_or_404(name,user)
    async def generate():
        previous=None
        while True:
            cont=docker_container(name)
            running=bool(cont and cont.get("running"))
            state=live_state(path, running=running) or {
                "connected":False, "transport":"none", "container_running":running,
                "player":None, "manager":None, "admins_online":[],
                "admins_online_count":0, "admins_in_room_count":0,
                "users_online":0, "room_users_online":0, "server_users_online":0, "room_users":[],
                "teamtalk_activity":{"speaking":0,"media":0,"video":0,"desktop":0},
                "server_teamtalk_activity":{"speaking":0,"media":0,"video":0,"desktop":0},
                "channel":{},
            }
            state["container_running"] = running
            payload=json.dumps(state,ensure_ascii=False,separators=(",",":"))
            if payload!=previous:
                previous=payload
                yield f"data: {payload}\n\n"
            await asyncio.sleep(0.5)
    return StreamingResponse(generate(),media_type="text/event-stream",headers={"Cache-Control":"no-cache","X-Accel-Buffering":"no"})


@app.get("/instances/{name}/logs", response_class=HTMLResponse)
def instance_logs(request: Request, name: str, tail: int = 250):
    user=require_login(request); instance_or_404(name,user)
    return templates.TemplateResponse("logs.html", {"request": request, "user":user, "name": name, "logs": logs_text(name, tail), "tail": tail, "csrf": csrf_token(request), "version": VERSION})


@app.get("/instances/{name}/config", response_class=HTMLResponse)
def instance_config(request: Request, name: str, saved: int = 0):
    user=require_login(request)
    path = instance_or_404(name,user)
    return templates.TemplateResponse("config.html", {"request": request, "user":user, "name": name, "sections": config_for_form(path, user), "saved": saved, "csrf": csrf_token(request), "version": VERSION})


@app.post("/instances/{name}/config")
async def instance_config_save(request: Request, name: str):
    user=require_login(request)
    path = instance_or_404(name,user)
    form = await request.form()
    check_csrf(request, str(form.get("csrf", "")))
    save_config_form(path, form, user)
    container = docker_container(name) or {}
    if bool(container.get("running")):
        jid = jobs.create(
            f"Apply config + restart {name}", job_helper_action, "restart", name,
            owner_user_id=int(user["id"]), kind="config-restart",
        )
        return job_created_response(request, jid, f"/instances/{name}/config?saved=1")
    return RedirectResponse(f"/instances/{name}/config?saved=1", status_code=303)


@app.post("/instances/{name}/limits")
async def instance_limits(request: Request, name: str, csrf: str = Form(...), cpu: str = Form(""), memory: str = Form("")):
    user=require_login(request); check_csrf(request, csrf)
    path = instance_or_404(name,user)
    cpu = cpu.strip(); memory = memory.strip()
    if cpu and not re.fullmatch(r"\d+(?:\.\d+)?", cpu):
        raise HTTPException(status_code=400, detail="CPU limit ไม่ถูกต้อง")
    if memory and not re.fullmatch(r"\d+(?:[kKmMgG])?", memory):
        raise HTTPException(status_code=400, detail="Memory limit ไม่ถูกต้อง")
    lines = []
    if cpu: lines.append(f"cpu={cpu}")
    if memory: lines.append(f"memory={memory}")
    (path / "limits.conf").write_text("\n".join(lines) + ("\n" if lines else ""), encoding="utf-8")
    os.chmod(path / "limits.conf", 0o660)
    try: os.chown(path / "limits.conf", 10001, 10001)
    except PermissionError: pass
    return RedirectResponse(f"/instances/{name}?limits=1", status_code=303)


@app.post("/instances/{name}/cookies")
async def instance_cookies(request: Request, name: str, csrf: str = Form(...), cookie_file: UploadFile = File(...)):
    user=require_login(request); check_csrf(request, csrf)
    path = instance_or_404(name,user)
    if read_instance_role(path) == "manager":
        raise HTTPException(status_code=400, detail="Server Manager Bot ไม่ใช้ YouTube cookies")
    safe_tmp = DATA_DIR / ("cookie-" + uuid.uuid4().hex + ".txt")
    try:
        data = await cookie_file.read()
        if len(data) > 10 * 1024 * 1024:
            raise HTTPException(status_code=400, detail="Cookie file ใหญ่เกิน 10 MB")
        safe_tmp.write_bytes(data)
        os.chmod(safe_tmp, 0o600)
        rc, out = root_run(["helper","cks",name,str(safe_tmp)], timeout=120)
        if rc != 0:
            raise HTTPException(status_code=400, detail=out)
    finally:
        safe_tmp.unlink(missing_ok=True)
    return RedirectResponse(f"/instances/{name}?cookies=1", status_code=303)


@app.post("/instances/{name}/cookies-check")
async def instance_cookies_check(request: Request, name: str, csrf: str = Form(...)):
    user=require_login(request); check_csrf(request, csrf); instance_or_404(name,user)
    jid = jobs.create(f"ตรวจ cookies {name}", job_cookie_check, name, owner_user_id=int(user["id"]))
    return job_created_response(request, jid, f"/instances/{name}")

@app.post("/system/cookies-all")
async def system_cookies_all(request: Request, csrf: str = Form(...), cookie_file: UploadFile = File(...)):
    admin=require_superadmin(request); check_csrf(request, csrf)
    tmp = DATA_DIR / ("cookies-upload-" + uuid.uuid4().hex + ".txt")
    data = await cookie_file.read()
    if len(data) > 10 * 1024 * 1024:
        raise HTTPException(status_code=400, detail="Cookie file ใหญ่เกิน 10 MB")
    tmp.write_bytes(data)
    os.chmod(tmp, 0o600)
    def work():
        try:
            return job_cookies_all(str(tmp))
        finally:
            tmp.unlink(missing_ok=True)
    jid = jobs.create("อัปเดต cookies ให้ Player/Full ทุกตัว", work, owner_user_id=int(admin["id"]))
    return job_created_response(request, jid, "/system")

@app.get("/migrate", response_class=HTMLResponse)
def migrate_page(request: Request):
    user=require_superadmin(request)
    return templates.TemplateResponse("migrate.html", {"request": request, "user":user, "csrf": csrf_token(request), "version": VERSION})


def job_migrate(source: str, role: str, replace: bool, start_after: bool, dry_run: bool, owner_user_id: int):
    source_path = Path(source).expanduser().resolve()
    if role not in ("full", "player", "manager"):
        raise RuntimeError("Role ไม่ถูกต้อง")
    names = DATA_DIR / ("migrate-names-" + uuid.uuid4().hex + ".txt")
    args = ["migrate-ttmediabot", str(source_path), role, str(names)]
    if replace:
        args.append("--replace")
    if dry_run:
        args.append("--dry-run")
    try:
        role_label = {"full":"Full Bot", "player":"Player Bot", "manager":"Server Manager Bot"}[role]
        job_emit(f"ตรวจและย้าย TTMediaBot จาก {source_path}")
        job_emit(f"ประเภทบอตที่เลือก: {role_label} ({role})")
        job_emit("นโยบาย config: สร้างจาก SNTalkBot template ปัจจุบัน แล้วนำเข้าเฉพาะค่า TTMediaBot ที่รองรับและตรวจสอบผ่าน")
        stream_root(args, timeout=900)
        imported=[]
        if names.is_file():
            imported=[x.strip() for x in names.read_text(encoding="utf-8",errors="replace").splitlines() if BOT_NAME_RE.fullmatch(x.strip())]
        if dry_run:
            job_emit(f"Dry run สำเร็จ พบรายการที่รองรับ {len(imported)} instance")
            return
        for name in imported:
            STORE.set_owner(name, owner_user_id, "")
            job_emit(f"กำหนดเจ้าของ Web Manager ให้ instance {name}")
            if start_after:
                job_emit(f"เริ่ม/รีสตาร์ต {name}")
                job_helper_action("restart", name)
        job_emit(f"Migration สำเร็จ {len(imported)} instance")
    finally:
        names.unlink(missing_ok=True)


@app.post("/migrate")
async def migrate_submit(request: Request, csrf: str = Form(...), source: str = Form(...), role: str = Form(...), replace: str | None = Form(None), start_after: str | None = Form(None), dry_run: str | None = Form(None)):
    admin=require_superadmin(request); check_csrf(request, csrf)
    jid = jobs.create("ย้าย TTMediaBot เก่า", job_migrate, source, role, bool(replace), bool(start_after), bool(dry_run), int(admin["id"]), owner_user_id=int(admin["id"]))
    return job_created_response(request, jid, "/migrate")


def _github_webhook_secret():
    direct = os.getenv("SNWEB_GITHUB_WEBHOOK_SECRET", "").strip()
    if direct:
        return direct.encode("utf-8")
    try:
        value = GITHUB_WEBHOOK_SECRET_FILE.read_text(encoding="utf-8").strip()
        return value.encode("utf-8") if value else b""
    except Exception:
        return b""


@app.post("/system/github-webhook-secret", response_class=HTMLResponse)
def github_webhook_secret_page(request: Request, csrf: str = Form(...)):
    user=require_superadmin(request); check_csrf(request, csrf)
    secret=_github_webhook_secret().decode("utf-8", "replace")
    if not secret:
        raise HTTPException(status_code=503, detail="GitHub release webhook secret is not configured")
    return templates.TemplateResponse("github_webhook.html", {
        "request": request, "user": user, "webhook": github_webhook_status(request),
        "secret": secret, "csrf": csrf_token(request), "version": VERSION,
    })

@app.post("/hooks/github/release")
async def github_release_hook(request: Request):
    secret = _github_webhook_secret()
    if not secret:
        raise HTTPException(status_code=503, detail="GitHub release webhook is not configured")
    raw = await request.body()
    supplied = request.headers.get("X-Hub-Signature-256", "")
    expected = "sha256=" + hmac.new(secret, raw, hashlib.sha256).hexdigest()
    if not hmac.compare_digest(supplied, expected):
        raise HTTPException(status_code=401, detail="Invalid webhook signature")
    event_name = request.headers.get("X-GitHub-Event", "")
    delivery_id = request.headers.get("X-GitHub-Delivery", "")
    if event_name != "release":
        STORE.set_system_state("github_release_webhook", {
            "event": event_name or "unknown", "accepted": False, "reason": "not_release",
            "delivery_id": delivery_id, "received_at": datetime.now(timezone.utc).isoformat(),
        })
        return JSONResponse({"ok": True, "accepted": False, "reason": "not_release"})
    try:
        event = json.loads(raw.decode("utf-8"))
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON")
    if not isinstance(event, dict):
        raise HTTPException(status_code=400, detail="Invalid payload")
    action = str(event.get("action") or "")
    release = event.get("release") if isinstance(event.get("release"), dict) else {}
    repository = event.get("repository") if isinstance(event.get("repository"), dict) else {}
    full_name = str(repository.get("full_name") or "").lower()
    expected_repo = GITHUB_REPOSITORY
    if action not in {"published", "released"} or bool(release.get("draft")) or full_name != expected_repo:
        STORE.set_system_state("github_release_webhook", {
            "event": "release", "action": action, "accepted": False, "reason": "filtered",
            "repository": full_name, "delivery_id": delivery_id,
            "received_at": datetime.now(timezone.utc).isoformat(),
        })
        return JSONResponse({"ok": True, "accepted": False, "reason": "filtered"})
    version = str(release.get("tag_name") or release.get("name") or "").strip().lstrip("vV")
    if not version:
        raise HTTPException(status_code=400, detail="Release version is missing")
    payload = {
        "repository": full_name,
        "version": version,
        "url": str(release.get("html_url") or ""),
    }
    attempted, delivered = await asyncio.to_thread(_fanout_release_event, payload)
    STORE.set_system_state("github_release_webhook", {
        "event": "release", "action": action, "accepted": True, "repository": full_name,
        "version": version, "url": payload["url"], "attempted": attempted, "delivered": delivered,
        "delivery_id": delivery_id, "received_at": datetime.now(timezone.utc).isoformat(),
    })
    return JSONResponse({
        "ok": True, "accepted": True, "attempted": attempted, "delivered": delivered
    }, status_code=202)


@app.get("/healthz")
def healthz():
    return {
        "ok": True, "version": VERSION, "generation": PROCESS_GENERATION,
        "started_epoch": int(PROCESS_STARTED_EPOCH),
    }
