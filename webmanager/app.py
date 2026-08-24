from __future__ import annotations

import asyncio
import configparser
from datetime import datetime, timezone
import hashlib
import hmac
import json
import os
from pathlib import Path
import re
import secrets
import shutil
import subprocess
import tempfile
import threading
import time
import urllib.request
import uuid
import zipfile

from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import HTMLResponse, RedirectResponse, PlainTextResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.middleware.sessions import SessionMiddleware

from webmanager.storage import Store

APP_ROOT = Path(__file__).resolve().parents[1]
VERSION = (APP_ROOT / "VERSION").read_text(encoding="utf-8").strip()
DATA_DIR = Path(os.getenv("SNWEB_DATA_DIR", "/var/lib/sntalkbot-web-manager"))
SESSION_SECRET_FILE = Path(os.getenv("SNWEB_SESSION_SECRET_FILE", "/etc/sntalkbot-web-manager/session_secret"))
DB_FILE = Path(os.getenv("SNWEB_DB_FILE", str(DATA_DIR / "webmanager.db")))
ROOT_BRIDGE = Path(os.getenv("SNWEB_ROOT_BRIDGE", "/usr/local/lib/sntalkbot-web-manager/snweb-root"))
TTU_CONFIG = Path(os.getenv("TTU_HELPER_CONFIG", "/etc/default/ttuhelper"))
DEFAULT_BOTS_ROOT = Path("/opt/sntalkbot-bots")
TTU_SOURCE = Path(os.getenv("SNWEB_TTU_SOURCE", "/opt/ttuhelper"))
TTU_REPO = os.getenv("SNWEB_TTU_REPO", "https://github.com/nuttawat-arch/ttuhelper.git")
WEB_REPO = os.getenv("SNWEB_WEB_REPO", "https://github.com/nuttawat-arch/sntalkbot-web-manager.git")
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

app = FastAPI(title="SNTalkBot Web Manager", docs_url=None, redoc_url=None)
# Ten-year persistent browser session. It remains invalid if the account is disabled
# or the server-side session secret is deliberately rotated.
app.add_middleware(SessionMiddleware, secret_key=SESSION_SECRET, same_site="lax", https_only=os.getenv("SNWEB_COOKIE_SECURE", "false").strip().lower() in ("1","true","yes","on"), max_age=10 * 365 * 24 * 3600)
app.mount("/static", StaticFiles(directory=APP_ROOT / "static"), name="static")
templates = Jinja2Templates(directory=APP_ROOT / "templates")

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


def read_instance_meta(path: Path):
    data = {}
    p = path / "instance.conf"
    if p.is_file():
        for raw in p.read_text(encoding="utf-8", errors="replace").splitlines():
            if "=" in raw:
                k, v = raw.split("=", 1)
                data[k.strip()] = v.strip()
    return data


def normalize_live_payload(data):
    """Normalize old/new SNTalkBot realtime schemas without mislabeling totals.

    SNTalkBot 5.1.2 makes users_online room-scoped and adds explicit room/server
    fields. Older snapshots used users_online for the whole server, so leave
    room_users_online unknown instead of presenting a server total as room data.
    """
    if not isinstance(data, dict):
        return data
    if "room_users_online" not in data:
        data["server_users_online"] = data.get("server_users_online", data.get("users_online"))
        data["room_users_online"] = None
        data.setdefault("room_users", [])
        data.setdefault("admins_in_room_count", None)
        data.setdefault("server_teamtalk_activity", data.get("teamtalk_activity") or {})
    return data


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


def live_state(path: Path, *, running: bool = True):
    # Never surface a recent runtime_status.json snapshot after the container
    # has stopped.  It is historical data at that point, not live state.
    if not running:
        return None
    return bot_api_status(path) or runtime_state(path)


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


def runtime_state(path: Path):
    p = path / "runtime_status.json"
    if not p.is_file():
        return None
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
        age = time.time() - float(data.get("updated_epoch") or 0)
        data["stale"] = age > 15
        data["age_seconds"] = max(0, int(age))
        return normalize_live_payload(data)
    except Exception:
        return None


def list_instances(user=None):
    root = bots_root()
    result = []
    if not root.is_dir():
        return result
    allowed = None
    if user and user.get("role") != "superadmin":
        allowed = STORE.owned_names(int(user["id"]))
    for path in sorted(root.iterdir(), key=lambda p: p.name.lower()):
        if not path.is_dir() or not (path / "config.ini").is_file():
            continue
        if allowed is not None and path.name not in allowed:
            continue
        cfg = read_config(path / "config.ini")
        cont = docker_container(path.name)
        live = live_state(path, running=bool(cont and cont["running"]))
        owner = STORE.owner(path.name)
        result.append({
            "name": path.name,
            "path": str(path),
            "role": read_instance_role(path, cfg),
            "nickname": cfg.get("bot", "nickname", fallback=path.name),
            "server": cfg.get("server", "address", fallback=""),
            "channel": cfg.get("bot", "default_channel", fallback="/"),
            "container": cont,
            "running": bool(cont and cont["running"]),
            "runtime": live,
            "owner": owner,
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

    def _meta_path(self, jid):
        return DATA_DIR / "jobs" / f"{jid}.json"

    def _log_path(self, jid):
        return DATA_DIR / "jobs" / f"{jid}.txt"

    def _persist_meta(self, job):
        safe = {
            "id": job.get("id"), "title": job.get("title"), "status": job.get("status"),
            "created": job.get("created"), "finished": job.get("finished"),
            "owner_user_id": job.get("owner_user_id"), "kind": job.get("kind"),
        }
        try:
            path = self._meta_path(job["id"])
            path.write_text(json.dumps(safe, ensure_ascii=False), encoding="utf-8")
            os.chmod(path, 0o600)
        except Exception:
            pass

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
        meta = self._meta_path(jid)
        log = self._log_path(jid)
        if not meta.is_file():
            return {}
        try:
            job = json.loads(meta.read_text(encoding="utf-8"))
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
    return path


def safe_secret_key(key):
    lk = key.lower()
    return any(token in lk for token in SECRET_KEYS)


def config_for_form(path: Path, user=None):
    cfg = read_config(path / "config.ini")
    is_superadmin = bool(user and user.get("role") == "superadmin")
    sections = []
    for section in cfg.sections():
        fields = []
        for key, value in cfg.items(section):
            stripped = value.strip()
            kind = "text"
            if safe_secret_key(key):
                kind = "secret"
            elif stripped.lower() in ("true", "false"):
                kind = "bool"
            elif re.fullmatch(r"-?\d+", stripped):
                kind = "int"
            elif re.fullmatch(r"-?\d+(?:\.\d+)", stripped):
                kind = "float"
            locked = (section.lower(), key.lower()) in TENANT_LOCKED_CONFIG_KEYS and not is_superadmin
            fields.append({"section": section, "key": key, "value": value, "kind": kind, "set": bool(value), "locked": locked})
        sections.append({"name": section, "fields": fields})
    return sections


def save_config_form(path: Path, form, user=None):
    cfg = read_config(path / "config.ini")
    is_superadmin = bool(user and user.get("role") == "superadmin")
    clear_secrets = set(form.getlist("clear_secret"))
    for section in cfg.sections():
        for key, old in list(cfg.items(section)):
            field = f"cfg__{section}__{key}"
            kind = f"kind__{section}__{key}"
            marker = form.get(kind, "text")
            locked = (section.lower(), key.lower()) in TENANT_LOCKED_CONFIG_KEYS and not is_superadmin
            if locked:
                # Disabled fields are normally absent from HTML submission. If a
                # forged POST supplies a different value, reject it server-side.
                supplied = form.get(field)
                if supplied is not None:
                    if safe_secret_key(key):
                        if str(supplied) or f"{section}.{key}" in clear_secrets:
                            raise HTTPException(status_code=403, detail="ผู้ใช้ทั่วไปไม่สามารถเปลี่ยน TeamTalk connection/login identity หลังยืนยันเจ้าของแล้ว")
                    elif marker == "bool":
                        submitted = "True" if form.get(field) == "on" else "False"
                        if submitted.casefold() != str(old).casefold():
                            raise HTTPException(status_code=403, detail="ผู้ใช้ทั่วไปไม่สามารถเปลี่ยน TeamTalk connection/login identity หลังยืนยันเจ้าของแล้ว")
                    elif str(supplied) != str(old):
                        raise HTTPException(status_code=403, detail="ผู้ใช้ทั่วไปไม่สามารถเปลี่ยน TeamTalk connection/login identity หลังยืนยันเจ้าของแล้ว")
                continue
            if safe_secret_key(key):
                secret_id = f"{section}.{key}"
                if secret_id in clear_secrets:
                    cfg.set(section, key, "")
                else:
                    new = str(form.get(field, ""))
                    if new:
                        cfg.set(section, key, new)
            elif marker == "bool":
                cfg.set(section, key, "True" if form.get(field) == "on" else "False")
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


def system_status(include_remote=False):
    settings = helper_settings()
    data = {
        "web_version": VERSION,
        "helper_installed": helper_installed(),
        "helper_version": helper_version(),
        "helper_remote": None,
        "web_remote": None,
        "bot_image_version": bot_image_version(),
        "docker_installed": docker_installed(),
        "image": f"{settings['TTU_IMAGE_REPO']}:{settings['TTU_TAG']}",
        "local_image_digest": local_image_digest(),
        "remote_image_digest": None,
        "bots_root": settings["TTU_BOTS_ROOT"],
        "helper_source": str(TTU_SOURCE),
        "guardian": guardian_status(),
    }
    if include_remote:
        data["web_remote"] = remote_version(WEB_REPO)
        data["helper_remote"] = remote_version(TTU_REPO)
        data["remote_image_digest"] = remote_image_digest()
    return data


@app.exception_handler(HTTPException)
async def http_exc(request: Request, exc: HTTPException):
    if exc.status_code == 303:
        return RedirectResponse(exc.headers.get("Location", "/login"), status_code=303)
    return PlainTextResponse(str(exc.detail), status_code=exc.status_code)


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
async def users_create(request: Request, csrf: str = Form(...), username: str = Form(...), display_name: str = Form(""), password: str = Form(...)):
    admin=require_superadmin(request); check_csrf(request,csrf); username=username.strip()
    if not WEB_USERNAME_RE.fullmatch(username):
        raise HTTPException(status_code=400,detail="ชื่อผู้ใช้ต้องยาว 3-64 ตัว และใช้ A-Z a-z 0-9 _ . -")
    try: STORE.create_user(username,password,role="user",display_name=display_name,created_by=int(admin["id"]))
    except Exception as exc: raise HTTPException(status_code=400,detail=str(exc))
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


@app.get("/", response_class=HTMLResponse)
def dashboard(request: Request):
    user=require_login(request)
    return templates.TemplateResponse("dashboard.html", {
        "request": request, "user":user, "instances": list_instances(user), "system": system_status(False),
        "csrf": csrf_token(request), "version": VERSION,
    })


@app.get("/help", response_class=HTMLResponse)
def help_page(request: Request):
    user=require_login(request)
    return templates.TemplateResponse("help.html", {"request": request, "user":user, "csrf": csrf_token(request), "version": VERSION})

@app.get("/system", response_class=HTMLResponse)
def system_page(request: Request):
    user=require_superadmin(request)
    return templates.TemplateResponse("system.html", {"request": request, "user":user, "system": system_status(True), "csrf": csrf_token(request), "version": VERSION})


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
    }
    if action not in mapping:
        raise HTTPException(status_code=400, detail="Unknown action")
    title, func, args = mapping[action]
    jid = jobs.create(title, func, *args, owner_user_id=int(user["id"]), kind=action)
    return RedirectResponse(f"/jobs/{jid}", status_code=303)


@app.get("/jobs/{jid}", response_class=HTMLResponse)
def job_page(request: Request, jid: str):
    user=require_login(request)
    job = jobs.get(jid)
    if not job or not can_view_job(user, job):
        raise HTTPException(status_code=404)
    return templates.TemplateResponse("job.html", {"request": request, "user":user, "job": job, "csrf": csrf_token(request), "version": VERSION, "process_generation": PROCESS_GENERATION})


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


def verify_owner_admin(name: str, owner_teamtalk_username: str, bot_username: str, keep_running: bool):
    path=bots_root()/name
    target=owner_teamtalk_username.strip().casefold()
    if not target:
        raise RuntimeError("ต้องระบุ TeamTalk username ของเจ้าของเพื่อยืนยันสิทธิ์ Administrator")
    if bot_username.strip() and target == bot_username.strip().casefold():
        raise RuntimeError("TeamTalk username ที่ใช้ยืนยันเจ้าของต้องไม่ใช่ username ของบอตเอง")
    job_emit("เริ่มบอตชั่วคราวเพื่อยืนยันว่าเจ้าของออนไลน์และเป็น TeamTalk Administrator")
    job_helper_action("run",name)
    deadline=time.time()+45
    connected_seen=False
    while time.time()<deadline:
        state=bot_api_status(path) or runtime_state(path)
        if state and state.get("connected"):
            connected_seen=True
            admins=state.get("admins_online") or []
            for admin in admins:
                if str(admin.get("username") or "").strip().casefold()==target:
                    job_emit(f"[OK] ยืนยัน Administrator: {admin.get('username')} / {admin.get('nickname') or '-'}")
                    if not keep_running:
                        job_emit("ผู้ใช้เลือกยังไม่รันบอตหลังสร้าง; หยุด container หลังยืนยันสิทธิ์")
                        job_helper_action("stop",name)
                    return state
        time.sleep(1)
    if connected_seen:
        raise RuntimeError("ไม่พบ TeamTalk username ของเจ้าของในรายชื่อ Administrator ที่ออนไลน์อยู่ กรุณาออนไลน์ด้วยบัญชีแอดมินของคุณแล้วสร้างใหม่")
    raise RuntimeError("บอตยังเชื่อมต่อ TeamTalk ไม่สำเร็จภายในเวลาตรวจสอบ กรุณาตรวจ host/port/username/password")


def job_create_verified(values: dict, owner_user_id: int, owner_teamtalk_username: str, start_now: bool):
    name=str(values["name"]).strip()
    path=None
    try:
        job_emit(f"สร้าง instance {name}")
        path=create_instance(values)
        STORE.set_owner(name,owner_user_id,owner_teamtalk_username)
        verify_owner_admin(name,owner_teamtalk_username,str(values.get("username") or ""),start_now)
        job_emit("สร้างและยืนยันเจ้าของ instance สำเร็จ")
    except Exception:
        if path is not None and path.exists():
            job_emit("การตรวจสิทธิ์ไม่ผ่าน: กำลังล้าง instance ที่สร้างค้างไว้")
            try: job_helper_action("delete",name)
            except Exception as cleanup: job_emit(f"WARNING cleanup failed: {cleanup}")
            STORE.delete_owner(name)
        raise


@app.get("/instances/new", response_class=HTMLResponse)
def new_instance_page(request: Request):
    user=require_login(request)
    return templates.TemplateResponse("new_instance.html", {"request": request, "user":user, "csrf": csrf_token(request), "version": VERSION})


@app.post("/instances/new")
async def new_instance(
    request: Request, csrf: str = Form(...), name: str = Form(...), role: str = Form(...), nickname: str = Form("SN TalkBot"),
    hostname: str = Form(...), tcp_port: int = Form(10333), udp_port: int = Form(10333), encrypted: str | None = Form(None),
    username: str = Form(""), password: str = Form(""), channel: str = Form("/"), channel_password: str = Form(""),
    authorized_users: str = Form(""), owner_teamtalk_username: str = Form(...), language: str = Form("th"), status_message: str = Form("auto"), start_now: str | None = Form(None),
):
    user=require_login(request); check_csrf(request, csrf)
    name=name.strip()
    if not NEW_BOT_NAME_RE.fullmatch(name):
        raise HTTPException(status_code=400, detail="ชื่อ instance ใหม่ต้องใช้ตัวพิมพ์เล็ก a-z, 0-9, _, . หรือ - เท่านั้น ยาวไม่เกิน 63 ตัว ห้ามเว้นวรรค/สแลช และต้องขึ้นต้นด้วยตัวอักษรหรือตัวเลข")
    if not hostname.strip(): raise HTTPException(status_code=400, detail="TeamTalk hostname/IP is required")
    if not (1 <= tcp_port <= 65535 and 1 <= udp_port <= 65535): raise HTTPException(status_code=400, detail="Port must be 1-65535")
    owner_tt=owner_teamtalk_username.strip()
    if not owner_tt: raise HTTPException(status_code=400,detail="ต้องระบุ TeamTalk username ของคุณสำหรับยืนยันสิทธิ์ Administrator")
    if username.strip() and owner_tt.casefold()==username.strip().casefold():
        raise HTTPException(status_code=400,detail="บัญชีที่ใช้ยืนยันเจ้าของห้ามเป็น TeamTalk username เดียวกับบอต เพราะระบบต้องไม่นับบอตเองเป็น Administrator ของเจ้าของ")
    auth=[x.strip() for x in authorized_users.split(',') if x.strip()]
    if owner_tt.casefold() not in {x.casefold() for x in auth}: auth.append(owner_tt)
    values={
        "name":name,"role":role,"nickname":nickname,"hostname":hostname,"tcp_port":tcp_port,"udp_port":udp_port,
        "encrypted":bool(encrypted),"username":username,"password":password,"channel":channel,"channel_password":channel_password,
        "authorized_users":",".join(auth),"language":language,"status_message":status_message,
    }
    jid=jobs.create(f"สร้างและยืนยัน {name}",job_create_verified,values,int(user["id"]),owner_tt,bool(start_now),owner_user_id=int(user["id"]))
    return RedirectResponse(f"/jobs/{jid}",status_code=303)


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
    if action == "delete" and confirm_name != name:
        raise HTTPException(status_code=400,detail="การลบต้องพิมพ์ชื่อ instance ให้ตรงทุกตัวอักษร")
    def work():
        job_helper_action(action,name)
        if action=="delete": STORE.delete_owner(name)
    jid = jobs.create(f"{action} {name}", work, owner_user_id=int(user["id"]))
    return RedirectResponse(f"/jobs/{jid}", status_code=303)


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
    return RedirectResponse(f"/jobs/{jid}", status_code=303)

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
    return RedirectResponse(f"/jobs/{jid}", status_code=303)

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
        job_emit(f"ตรวจและย้าย TTMediaBot จาก {source_path}")
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
    return RedirectResponse(f"/jobs/{jid}", status_code=303)


@app.get("/healthz")
def healthz():
    return {
        "ok": True, "version": VERSION, "generation": PROCESS_GENERATION,
        "started_epoch": int(PROCESS_STARTED_EPOCH),
    }
