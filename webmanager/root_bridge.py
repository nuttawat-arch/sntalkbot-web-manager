#!/usr/bin/env python3
from __future__ import annotations

import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
from datetime import datetime

NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,62}$")
CONFIG = Path("/etc/default/sntalkbot-web-manager")


def settings():
    data = {
        "SNWEB_TTU_SOURCE": "/opt/ttuhelper",
        "SNWEB_INSTALL_DIR": "/opt/sntalkbot-web-manager",
        "SNWEB_TTU_REPO": "https://github.com/nuttawat-arch/ttuhelper.git",
        "SNWEB_WEB_REPO": "https://github.com/nuttawat-arch/sntalkbot-web-manager.git",
    }
    if CONFIG.is_file():
        for raw in CONFIG.read_text(encoding="utf-8", errors="replace").splitlines():
            raw=raw.strip()
            if not raw or raw.startswith("#") or "=" not in raw: continue
            k,v=raw.split("=",1); data[k.strip()]=v.strip().strip('"').strip("'")
    return data


def helper_settings():
    data={"TTU_BOTS_ROOT":"/opt/sntalkbot-bots","TTU_IMAGE_REPO":"nuttawat0295/sntalkbot","TTU_TAG":"latest"}
    path=Path("/etc/default/ttuhelper")
    if path.is_file():
        for raw in path.read_text(encoding="utf-8",errors="replace").splitlines():
            raw=raw.strip()
            if not raw or raw.startswith("#") or "=" not in raw: continue
            k,v=raw.split("=",1); data[k.strip()]=v.strip().strip('"').strip("'")
    return data


def run(args, cwd=None, check=True):
    p=subprocess.run([str(x) for x in args], cwd=str(cwd) if cwd else None, text=True)
    if check and p.returncode:
        raise SystemExit(p.returncode)
    return p.returncode


def capture(args, cwd=None):
    p=subprocess.run(
        [str(x) for x in args], cwd=str(cwd) if cwd else None, text=True,
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False,
    )
    if p.returncode:
        if p.stderr:
            print(p.stderr, file=sys.stderr, end="" if p.stderr.endswith("\n") else "\n")
        raise SystemExit(p.returncode)
    return p.stdout


def image_name():
    helper=helper_settings()
    return f"{helper['TTU_IMAGE_REPO']}:{helper['TTU_TAG']}"


def image_text(path):
    # Only fixed in-image files used by Web Manager are accepted; callers cannot
    # turn this into a generic Docker read primitive.
    if path not in {"/app/config_default.ini", "/app/VERSION"}:
        raise SystemExit("image file is not allowed")
    return capture(["docker","run","--rm","--entrypoint","cat",image_name(),path])


def valid_name(name):
    if not NAME_RE.fullmatch(name or ""):
        raise SystemExit("invalid instance name")
    return name


def managed_container_json(name):
    name=valid_name(name)
    raw=capture(["docker","inspect",name])
    try:
        data=json.loads(raw)
        item=data[0]
        labels=(item.get("Config") or {}).get("Labels") or {}
    except Exception as exc:
        raise SystemExit(f"unable to parse Docker inspect for {name}: {exc}")
    helper=helper_settings(); expected_root=Path(helper["TTU_BOTS_ROOT"]).resolve()
    expected_data=str((expected_root/name).resolve())
    if labels.get("com.ttutilities.helper")!="true" or labels.get("com.ttutilities.bot")!=name or labels.get("com.ttutilities.data")!=expected_data:
        raise SystemExit(f"refusing unmanaged Docker container: {name}")
    return raw


def require_container_name_available(name):
    name=valid_name(name)
    p=subprocess.run(["docker","container","inspect",name],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,check=False)
    if p.returncode==0:
        raise SystemExit(f"Docker container name is already in use: {name}")
    return 0


def _stamp():
    return datetime.now().strftime("%Y%m%d-%H%M%S")


def _prune_source_backups(target, keep=3):
    target=Path(target)
    backups=sorted(target.parent.glob(target.name+".backup-*"), key=lambda p: p.name, reverse=True)
    for old in backups[keep:]:
        try:
            if old.is_dir() and not old.is_symlink():
                shutil.rmtree(old)
            else:
                old.unlink()
            print(f"[CLEANUP] Removed old source backup: {old}", flush=True)
        except OSError as exc:
            print(f"[WARN] Unable to remove old source backup {old}: {exc}", file=sys.stderr, flush=True)


def replace_from_fresh_clone(repo, target):
    """Stage a clean upstream checkout before touching the live source tree.

    Production source directories are disposable; persistent Web Manager state is
    kept in /etc and /var/lib, while SNTalkBot instance data lives under the
    TTUHelper bots root.  A fresh clone avoids git-pull failures caused by local
    edits, line-ending changes, or stray untracked files.  The previous complete
    source tree is retained as a rollback backup.
    """
    target=Path(target)
    target.parent.mkdir(parents=True, exist_ok=True)
    stamp=_stamp()
    incoming=target.with_name(target.name+f".incoming-{stamp}-{os.getpid()}")
    backup=target.with_name(target.name+f".backup-{stamp}-{os.getpid()}")
    if incoming.exists():
        shutil.rmtree(incoming) if incoming.is_dir() else incoming.unlink()
    print(f"[STAGE] Fresh clone {repo} -> {incoming}", flush=True)
    # Clone must finish successfully before the live tree is renamed.
    run(["git","clone","--depth","1",repo,incoming])
    if not (incoming/".git").is_dir() or not (incoming/"install.sh").is_file():
        shutil.rmtree(incoming, ignore_errors=True)
        raise SystemExit("staged repository is incomplete; live source was left untouched")
    if target.exists() or target.is_symlink():
        print(f"[BACKUP] Preserving complete previous source: {target} -> {backup}", flush=True)
        target.rename(backup)
    else:
        backup=None
    try:
        incoming.rename(target)
    except Exception:
        if backup is not None and backup.exists() and not target.exists():
            backup.rename(target)
        raise
    return backup


def rollback_source_replace(target, backup):
    target=Path(target)
    failed=target.with_name(target.name+f".failed-{_stamp()}-{os.getpid()}")
    if target.exists() or target.is_symlink():
        target.rename(failed)
        print(f"[ROLLBACK] Failed new source kept at {failed}", file=sys.stderr, flush=True)
    if backup is not None and Path(backup).exists():
        backup=Path(backup)
        backup.rename(target)
        print(f"[ROLLBACK] Restored previous source: {target}", file=sys.stderr, flush=True)


def install_fresh_checkout(repo, target, *, project_name, defer_restart=False):
    target=Path(target)
    backup=replace_from_fresh_clone(repo, target)
    installer=target/"install.sh"
    argv=["bash",installer]
    if defer_restart:
        argv=["env","SNWEB_DEFER_RESTART=1",*argv]
    rc=run(argv, cwd=target, check=False)
    if rc:
        print(f"[FAIL] {project_name} installer returned {rc}; restoring previous source", file=sys.stderr, flush=True)
        rollback_source_replace(target, backup)
        # If an upgrade changed installed helper/bridge files before failing,
        # best-effort re-run the restored installer to return system files to
        # the same version as the restored source.
        restored=target/"install.sh"
        if restored.is_file():
            run(["bash",restored], cwd=target, check=False)
        if project_name == "Web Manager":
            # The restored source may be 1.1.3 or older, whose installer did not
            # restart an already-active service.  Restore the running process too.
            run(["systemctl","restart","sntalkbot-web-manager"], check=False)
        raise SystemExit(rc)
    _prune_source_backups(target)
    return 0


def install_stack(cfg):
    missing=[]
    for cmd,pkg in (("git","git"),("curl","curl"),("python3","python3")):
        if shutil.which(cmd): print(f"[OK] {cmd} already installed", flush=True)
        else: missing.append(pkg); print(f"[MISSING] {cmd}", flush=True)
    if missing:
        print("Installing only missing base packages: "+" ".join(missing), flush=True)
        run(["apt-get","update"]); run(["apt-get","install","-y",*missing,"ca-certificates"])
    else:
        print("[OK] base packages complete; skipping apt install", flush=True)
    if shutil.which("docker"):
        print("[OK] Docker command already installed", flush=True)
    else:
        print("[MISSING] Docker; TTUHelper installer will install it", flush=True)
    # SNTalkBot itself is deployed as a Docker image.  Do not create a host-side
    # /opt/sntalkbot source checkout just to satisfy Web Manager.
    install_fresh_checkout(cfg["SNWEB_TTU_REPO"], cfg["SNWEB_TTU_SOURCE"], project_name="TTUHelper")
    run(["ttuhelper","doctor"])


def migrate_ttmediabot(cfg, args):
    if len(args) < 3:
        raise SystemExit("migrate-ttmediabot requires source role names-file [--replace] [--dry-run]")
    source=Path(args.pop(0)).expanduser().resolve()
    role=args.pop(0)
    names=Path(args.pop(0)).resolve()
    replace=False; dry_run=False
    for arg in args:
        if arg=="--replace": replace=True
        elif arg=="--dry-run": dry_run=True
        else: raise SystemExit("unknown migration option")
    if role not in ("full","player","manager"): raise SystemExit("invalid migration role")
    if not source.is_dir(): raise SystemExit(f"legacy source not found: {source}")
    allowed_data=Path("/var/lib/sntalkbot-web-manager").resolve()
    if allowed_data not in names.parents: raise SystemExit("names file must be inside Web Manager data directory")
    helper=helper_settings(); dest=Path(helper["TTU_BOTS_ROOT"]).resolve()
    dest.mkdir(parents=True,exist_ok=True)
    migrator=Path("/usr/local/lib/ttuhelper/migrate_ttmediabot.py")
    if not migrator.is_file(): migrator=Path(cfg["SNWEB_TTU_SOURCE"])/"tools"/"migrate_ttmediabot.py"
    if not migrator.is_file(): raise SystemExit("TTMediaBot migrator is not installed")
    names.parent.mkdir(parents=True,exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="snweb-migrate-") as temp_dir:
        template=Path(temp_dir)/"config_default.ini"
        template.write_text(image_text("/app/config_default.ini"),encoding="utf-8")
        cmd=["python3",migrator,"--source",source,"--dest-root",dest,"--template",template,"--mode",role,"--yes","--names-file",names]
        if replace: cmd.append("--replace")
        if dry_run: cmd.append("--dry-run")
        rc=run(cmd,check=False)
        if rc: return rc
    if not dry_run and names.is_file():
        for name in names.read_text(encoding="utf-8",errors="replace").splitlines():
            name=name.strip()
            if not NAME_RE.fullmatch(name): continue
            target=(dest/name).resolve()
            if target.is_dir() and target.parent==dest:
                run(["chown","-R","10001:10001",target],check=False)
                run(["chmod","2770",target],check=False)
                for fname,mode in (("config.ini","0660"),("limits.conf","0660"),("instance.conf","0640"),("runtime_status.json","0640")):
                    fp=target/fname
                    if fp.exists(): run(["chmod",mode,fp],check=False)
    return 0


def main():
    if os.geteuid()!=0: raise SystemExit("root bridge must run as root")
    cfg=settings(); args=sys.argv[1:]
    if not args: raise SystemExit("missing action")
    action=args.pop(0)
    if action=="helper":
        if not args: raise SystemExit("missing helper action")
        sub=args.pop(0)
        allowed_global={"start-all","stop-all","pull","update","doctor","version"}
        allowed_instance={"run","stop","restart","delete","cks","cks-check"}
        if sub == "cks-all":
            if len(args)!=1: raise SystemExit("cks-all requires one uploaded file")
            source=Path(args[0]).resolve()
            allowed_root=Path("/var/lib/sntalkbot-web-manager").resolve()
            if allowed_root not in source.parents: raise SystemExit("cookie upload path is outside Web Manager data directory")
            return run(["ttuhelper","cks-all",source])
        if sub in allowed_global:
            if args: raise SystemExit("unexpected arguments")
            return run(["ttuhelper",sub])
        if sub in allowed_instance:
            if not args: raise SystemExit("missing instance")
            name=valid_name(args.pop(0))
            cmd=["ttuhelper",sub,name]
            if sub=="delete":
                if args: raise SystemExit("unexpected arguments")
                cmd.append("--yes")
            elif sub=="cks":
                if len(args)>1: raise SystemExit("too many arguments")
                if args:
                    source=Path(args[0]).resolve(); allowed_root=Path("/var/lib/sntalkbot-web-manager").resolve()
                    if allowed_root not in source.parents: raise SystemExit("cookie upload path is outside Web Manager data directory")
                    cmd.append(str(source))
            elif args: raise SystemExit("unexpected arguments")
            return run(cmd)
        raise SystemExit("helper action not allowed")
    if action=="container-name-check":
        if len(args)!=1: raise SystemExit("container-name-check requires one instance name")
        return require_container_name_available(args[0])
    if action=="docker-inspect":
        if len(args)!=1: raise SystemExit("docker-inspect requires one instance name")
        sys.stdout.write(managed_container_json(args[0])); return 0
    if action=="docker-logs":
        if not args: raise SystemExit("docker-logs requires an instance name")
        name=valid_name(args[0]); managed_container_json(name)
        tail=int(args[1] if len(args)>1 else 250); tail=max(20,min(tail,2000))
        return run(["docker","logs","--tail",str(tail),name], check=False)
    if action=="image-inspect":
        if len(args)!=1 or not re.fullmatch(r"[A-Za-z0-9._/:@-]+",args[0]): raise SystemExit("bad image")
        return run(["docker","image","inspect",args[0]], check=False)
    if action=="remote-image-inspect":
        if len(args)!=1 or not re.fullmatch(r"[A-Za-z0-9._/:@-]+",args[0]): raise SystemExit("bad image")
        return run(["docker","buildx","imagetools","inspect",args[0]], check=False)
    if action=="migrate-ttmediabot": return migrate_ttmediabot(cfg,args)
    if action=="bot-config-template":
        if args: raise SystemExit("unexpected arguments")
        sys.stdout.write(image_text("/app/config_default.ini")); return 0
    if action=="bot-image-version":
        if args: raise SystemExit("unexpected arguments")
        sys.stdout.write(image_text("/app/VERSION").strip()+"\n"); return 0
    if action=="install-stack": return install_stack(cfg)
    if action=="update-helper":
        return install_fresh_checkout(cfg["SNWEB_TTU_REPO"], cfg["SNWEB_TTU_SOURCE"], project_name="TTUHelper")
    if action=="update-web":
        target=Path(cfg["SNWEB_INSTALL_DIR"])
        install_fresh_checkout(cfg["SNWEB_WEB_REPO"], target, project_name="Web Manager", defer_restart=True)
        # Restart from a separate transient systemd unit after this privileged
        # helper exits; restarting directly here can kill the caller's cgroup
        # before the web job receives its success output.
        unit="sntalkbot-web-manager-restart-"+datetime.now().strftime("%Y%m%d%H%M%S")
        run(["systemd-run","--unit",unit,"--on-active=2s","/bin/systemctl","restart","sntalkbot-web-manager"])
        print("Web Manager updated; restart scheduled in 2 seconds.", flush=True)
        return 0
    raise SystemExit("action not allowed")

if __name__=="__main__":
    raise SystemExit(main() or 0)
