#!/usr/bin/env python3
from pathlib import Path
import ast, os, re, subprocess, sys, tempfile, time
root=Path(__file__).resolve().parents[1]
errors=[]
def need(cond,msg):
    if cond: print('[OK] '+msg)
    else: errors.append(msg); print('[FAIL] '+msg)
for p in root.rglob('*.py'):
    if '.venv' in p.parts: continue
    try: ast.parse(p.read_text(encoding='utf-8'), filename=str(p))
    except SyntaxError as e: errors.append(f'{p}: {e}')
app=(root/'webmanager/app.py').read_text(encoding='utf-8')
bridge=(root/'webmanager/root_bridge.py').read_text(encoding='utf-8')
installer=(root/'install.sh').read_text(encoding='utf-8')
mapping=(root/'TTUHELPER_WEB_MAP_TH.md').read_text(encoding='utf-8')
base=(root/'templates/base.html').read_text(encoding='utf-8')
newtpl=(root/'templates/new_instance.html').read_text(encoding='utf-8')
insttpl=(root/'templates/instance.html').read_text(encoding='utf-8')
jobtpl=(root/'templates/job.html').read_text(encoding='utf-8')
configtpl=(root/'templates/config.html').read_text(encoding='utf-8')
storage=(root/'webmanager/storage.py').read_text(encoding='utf-8')
password_tool=(root/'webmanager/password_tool.py').read_text(encoding='utf-8')
js=(root/'static/app.js').read_text(encoding='utf-8')

mainmod=(root/'webmanager/__main__.py').read_text(encoding='utf-8')
nginx=(root/'nginx.example.conf').read_text(encoding='utf-8')
proxyguide=(root/'REVERSE_PROXY_GUIDE_TH.md').read_text(encoding='utf-8')
expected=['new','run','stop','restart','delete','logs','ls','ps','start-all','stop-all','pull','update','migrate-ttmediabot','cks','cks-all','cks-check','limit','edit','path','doctor','version','help']
checks={
 'no shell=True':'shell=True' not in app and 'shell=True' not in bridge,
 'csrf':'check_csrf' in app,
 'three roles':all(x in app for x in ('"full"','"player"','"manager"')),
 'all 22 TTUHelper commands documented':all(('`'+x+'`') in mapping for x in expected),
 'delete confirmation': 'confirm_name' in app and 'Type the exact instance name' not in app and 'พิมพ์ <strong>{{ bot.name }}</strong>' in insttpl,
 'runtime HTTP API preferred with JSON fallback':'bot_api_status(path) or runtime_state(path)' in app,
 'API uses loopback Bearer token':'http://127.0.0.1:{port}/v1/status' in app and 'Authorization' in app and 'Bearer {token}' in app,
 'multi-user database':'Store(DB_FILE)' in app and 'instance_owners' in storage,
 'first user becomes one atomic superadmin':'create_first_superadmin' in app and 'BEGIN IMMEDIATE' in storage and 'setup_required()' in app,
 'only superadmin creates accounts':'users_create' in app and 'require_superadmin(request)' in app,
 'tenant ownership enforced':'can_manage_instance' in app and 'owned_names' in app and 'owner_user_id' in app,
 'job ownership enforced':'can_view_job' in app and 'owner_user_id' in app and 'not can_view_job(user, initial)' in app,
 'owner must be online TeamTalk admin':'verify_owner_admin' in app and 'admins_online' in app and 'username เดียวกับบอต' in app,
 'Linux lowercase instance rule':'NEW_BOT_NAME_RE = re.compile(r"^[a-z0-9][a-z0-9_.-]{0,62}$")' in app and 'pattern="[a-z0-9][a-z0-9_.-]{0,62}"' in newtpl,
 'config all sections':'config_for_form' in app and 'save_config_form' in app,
 'secret fields masked':'safe_secret_key' in app and 'clear_secret' in app,
'tenant cannot repoint verified TeamTalk identity':'TENANT_LOCKED_CONFIG_KEYS' in app and 'ผู้ใช้ทั่วไปไม่สามารถเปลี่ยน TeamTalk connection/login identity' in app and 'f.locked' in configtpl,
 'password recovery tool uses SQLite, not legacy auth.json':'webmanager.db' in password_tool and 'create_first_superadmin' in password_tool and "default='/etc/sntalkbot-web-manager/auth.json'" not in password_tool,
 'persistent sessions':'10 * 365 * 24 * 3600' in app,
 'login throttling':'LOGIN_MAX_FAILURES = 8' in app and 'login_blocked' in app,
 'realtime jobs':'StreamingResponse' in app and '/jobs/{jid}/stream' in app and 'EventSource' in js and 'data-job-id' in jobtpl,
 'realtime instance SSE':'/instances/{name}/live' in app and 'await asyncio.sleep(0.5)' in app and 'live-instance' in insttpl,
 'service does not run as root':'User=$SERVICE_USER' in installer and 'SERVICE_USER="${SNWEB_SERVICE_USER:-sntalkweb}"' in installer,
 'installer explicitly creates same-name service group':'groupadd --system "$SERVICE_USER"' in installer and 'useradd --system --gid "$SERVICE_USER"' in installer,
 'installer preserves existing environment settings on upgrade':'Keeping existing Web Manager settings; adding only missing defaults.' in installer and 'write_default SNWEB_COOKIE_SECURE' in installer,
 'self-update reruns upgrade-safe installer then schedules restart':'run(["bash",installer],cwd=target)' in bridge and 'systemd-run' in bridge and '--on-active=2s' in bridge,
 'privileged bridge is only sudo target':'NOPASSWD: $ROOT_BRIDGE *' in installer and 'snweb-root' in installer,
 'root bridge allowlist':'action not allowed' in bridge and 'migrate-ttmediabot' in bridge and 'install-stack' in bridge,
 'installer preflight':all(x in installer for x in ('has python3','has git','has curl','if has docker')),
 'CloudPanel loopback default':'BIND="${SNWEB_BIND:-127.0.0.1}"' in installer and 'PORT="${SNWEB_PORT:-28765}"' in installer,
 'normal-user nav hides privileged pages':"{% if user.role == 'superadmin' %}" in base and '/users' in base and '/system' in base,
 'admin list excludes bot explained':'ไม่รวมบัญชีของบอตเอง' in insttpl,
 'consistent 28765 safe bind defaults':'28765' in mainmod and "'127.0.0.1'" in mainmod and '127.0.0.1:28765' in nginx and "'8765'" not in mainmod and ':8765' not in nginx,
 'reverse proxy guide covers standalone and common proxies':all(x in proxyguide for x in ('Standalone','CloudPanel','NGINX','Caddy','Apache','proxy_buffering off','SNWEB_COOKIE_SECURE')),
}
for name,ok in checks.items(): need(ok,name)
# Root bridge should never expose generic shell/user-provided executable APIs.
need('subprocess.run([str(x) for x in args]' in bridge and 'os.system' not in bridge and 'subprocess.Popen' not in bridge, 'root bridge executes only structured allowlisted argv actions')
# Shell syntax
need(subprocess.run(['bash','-n',str(root/'install.sh')],capture_output=True).returncode==0,'installer shell syntax valid')
# Functional tenant/auth test with isolated data/root. No host Docker/TTUHelper action is invoked.
try:
    with tempfile.TemporaryDirectory() as td:
        t=Path(td); bots=t/'bots'; bots.mkdir(); etc=t/'ttu.conf'; secret=t/'secret'; secret.write_text('validation-secret-0123456789\n')
        etc.write_text(f'TTU_BOTS_ROOT="{bots}"\nTTU_IMAGE_REPO="example/bot"\nTTU_TAG="latest"\n')
        env=os.environ.copy(); env.update({
            'SNWEB_DATA_DIR':str(t/'data'),'SNWEB_DB_FILE':str(t/'data/db.sqlite'),'SNWEB_SESSION_SECRET_FILE':str(secret),
            'TTU_HELPER_CONFIG':str(etc),'SNWEB_ROOT_BRIDGE':'/bin/false','SNWEB_BOT_SOURCE':str(t/'source'),
        })
        test_code = """
from pathlib import Path
import re, sys, time
sys.path.insert(0, %r)
from fastapi.testclient import TestClient
from webmanager import app as mod
client=TestClient(mod.app)
r=client.get('/setup'); assert r.status_code==200 and 'Super Admin' in r.text
r=client.post('/setup',data={'username':'rootadmin','display_name':'Owner','password':'verystrongpass1','password2':'verystrongpass1'},follow_redirects=False); assert r.status_code==303
try:
 mod.STORE.create_first_superadmin('secondroot','anotherstrongpass1')
 raise AssertionError('second first-run superadmin was created')
except ValueError:
 pass
r=client.get('/users'); assert r.status_code==200
m=re.search(r'name=\"csrf\" value=\"([^\"]+)\"',r.text); assert m
csrf=m.group(1)
r=client.post('/users/create',data={'csrf':csrf,'username':'customer','display_name':'Customer','password':'customerpass123'},follow_redirects=False); assert r.status_code==303
admin=mod.STORE.get_user_by_username('rootadmin'); customer=mod.STORE.get_user_by_username('customer'); assert customer
root=mod.bots_root()
for name in ('mine','other'):
 p=root/name; p.mkdir(); (p/'config.ini').write_text('[server]\\naddress=x\\n[bot]\\nnickname='+name+'\\n[features]\\nplayer_enabled=True\\nserver_management_enabled=False\\n')
mod.STORE.set_owner('mine',customer['id'],'adminhuman'); mod.STORE.set_owner('other',admin['id'],'rootadmin')
client2=TestClient(mod.app)
r=client2.post('/login',data={'username':'customer','password':'customerpass123'},follow_redirects=False); assert r.status_code==303
r=client2.get('/'); assert r.status_code==200 and 'mine' in r.text and 'other' not in r.text and '/system' not in r.text
assert client2.get('/instances/other').status_code==404
assert client2.get('/users').status_code==403
r=client2.get('/instances/mine/config'); assert r.status_code==200 and 'ล็อกสำหรับบัญชีผู้ใช้ทั่วไป' in r.text
m2=re.search(r'name="csrf" value="([^"]+)"',r.text); assert m2
customer_csrf=m2.group(1)
r=client2.post('/instances/mine/config',data={'csrf':customer_csrf,'kind__server__address':'text','cfg__server__address':'unauthorized.example'},follow_redirects=False); assert r.status_code==403
assert 'address=x' in (root/'mine'/'config.ini').read_text()
# Super Admin can still perform an intentional connection change.
r=client.post('/instances/mine/config',data={'csrf':csrf,'kind__server__address':'text','cfg__server__address':'admin-approved.example'},follow_redirects=False); assert r.status_code==303
assert 'address = admin-approved.example' in (root/'mine'/'config.ini').read_text()
j1=mod.jobs.create('admin secret job',lambda:'done',owner_user_id=admin['id']); time.sleep(.1)
assert client2.get('/jobs/'+j1).status_code==404
j2=mod.jobs.create('customer job',lambda:'done',owner_user_id=customer['id']); time.sleep(.1)
assert client2.get('/jobs/'+j2).status_code==200
print('FUNCTIONAL_OK')
""" % str(root)
        proc=subprocess.run([sys.executable,'-c',test_code],env=env,capture_output=True,text=True,timeout=30)
        need(proc.returncode==0 and 'FUNCTIONAL_OK' in proc.stdout, 'first-run auth, tenant instance isolation, privileged-page denial and job ownership execute in TestClient')
        if proc.returncode: print(proc.stdout); print(proc.stderr)
except Exception as exc:
    need(False,f'functional Web Manager test: {exc!r}')
try:
    with tempfile.TemporaryDirectory() as td:
        db=Path(td)/'recovery.db'
        env=os.environ.copy(); env['PYTHONPATH']=str(root)
        cmd=[sys.executable,'-m','webmanager.password_tool','--db',str(db),'--username','recoveradmin','--password','recoverypass123']
        first=subprocess.run(cmd,cwd=root,env=env,capture_output=True,text=True,timeout=20)
        second=subprocess.run(cmd,cwd=root,env=env,capture_output=True,text=True,timeout=20)
        from sqlite3 import connect
        with connect(db) as con:
            count=con.execute('SELECT COUNT(*) FROM users').fetchone()[0]
            role=con.execute('SELECT role FROM users WHERE username=?',('recoveradmin',)).fetchone()[0]
        need(first.returncode==0 and second.returncode==0 and count==1 and role=='superadmin', 'SQLite password recovery creates only first Super Admin and later resets that account')
except Exception as exc:
    need(False,f'password recovery test: {exc!r}')
if errors:
    print('\n'.join(errors)); raise SystemExit(1)
print('[OK] Python syntax, multi-user isolation, realtime transport and privileged-bridge safety invariants')
