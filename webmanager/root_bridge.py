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


def clone_or_update(repo, target):
    target=Path(target)
    if (target/".git").is_dir():
        print(f"[GIT] Updating {target}", flush=True)
        run(["git","-C",target,"fetch","--all","--prune"])
        run(["git","-C",target,"pull","--ff-only"])
    elif target.exists():
        backup=target.with_name(target.name+".backup-"+datetime.now().strftime("%Y%m%d-%H%M%S"))
        print(f"[BACKUP] Existing non-Git directory: {target} -> {backup}", flush=True)
        target.rename(backup)
        run(["git","clone",repo,target])
    else:
        print(f"[GIT] Cloning {repo} -> {target}", flush=True)
        run(["git","clone",repo,target])


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
    clone_or_update(cfg["SNWEB_TTU_REPO"], cfg["SNWEB_TTU_SOURCE"])
    run(["bash", Path(cfg["SNWEB_TTU_SOURCE"])/"install.sh"], cwd=cfg["SNWEB_TTU_SOURCE"])
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
    if action=="docker-inspect":
        name=valid_name(args[0] if args else ""); return run(["docker","inspect",name], check=False)
    if action=="docker-logs":
        name=valid_name(args[0] if args else ""); tail=int(args[1] if len(args)>1 else 250); tail=max(20,min(tail,2000))
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
        clone_or_update(cfg["SNWEB_TTU_REPO"],cfg["SNWEB_TTU_SOURCE"]); return run(["bash",Path(cfg["SNWEB_TTU_SOURCE"])/"install.sh"],cwd=cfg["SNWEB_TTU_SOURCE"])
    if action=="update-web":
        clone_or_update(cfg["SNWEB_WEB_REPO"],cfg["SNWEB_INSTALL_DIR"])
        target=Path(cfg["SNWEB_INSTALL_DIR"])
        installer=target/"install.sh"
        if not installer.is_file(): raise SystemExit("Web Manager install.sh is missing after update")
        # Re-run the upgrade-safe installer so dependencies, root bridge,
        # permissions and systemd definitions cannot drift from the source.
        run(["bash",installer],cwd=target)
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
