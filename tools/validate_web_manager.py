#!/usr/bin/env python3
from pathlib import Path
import ast, os, re, subprocess, sys, tempfile, time
root=Path(__file__).resolve().parents[1]
PORTABLE_ONLY = os.name == 'nt' or '--portable' in sys.argv
errors=[]
def need(cond,msg):
    if cond: print('[OK] '+msg)
    else: errors.append(msg); print('[FAIL] '+msg)
def defer(msg):
    print('[DEFERRED-LINUX] '+msg)
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
broadcasttpl=(root/'templates/broadcasts.html').read_text(encoding='utf-8')
storage=(root/'webmanager/storage.py').read_text(encoding='utf-8')
password_tool=(root/'webmanager/password_tool.py').read_text(encoding='utf-8')
js=(root/'static/app.js').read_text(encoding='utf-8')
help_tpl=(root/'templates/help.html').read_text(encoding='utf-8')
dash_tpl=(root/'templates/dashboard.html').read_text(encoding='utf-8')
system_tpl=(root/'templates/system.html').read_text(encoding='utf-8')
users_tpl=(root/'templates/users.html').read_text(encoding='utf-8')
error_tpl=(root/'templates/error.html').read_text(encoding='utf-8')
guardian=(root/'guardian/snweb_guardian.py').read_text(encoding='utf-8')

mainmod=(root/'webmanager/__main__.py').read_text(encoding='utf-8')
nginx=(root/'nginx.example.conf').read_text(encoding='utf-8')
proxyguide=(root/'REVERSE_PROXY_GUIDE_TH.md').read_text(encoding='utf-8')
expected=['new','run','stop','restart','delete','logs','ls','ps','start-all','stop-all','pull','update','migrate-ttmediabot','cks','cks-all','cks-check','limit','edit','path','doctor','version','help']
checks={
 'no shell=True':'shell=True' not in app and 'shell=True' not in bridge,
 'csrf':'check_csrf' in app,
 'three roles':all(x in app for x in ('"full"','"player"','"manager"')),
 'all 22 TTUHelper commands documented':all(('`'+x+'`') in mapping for x in expected),
 'delete confirmation on detail + dashboard': 'confirm_name' in app and 'พิมพ์ <strong>{{ bot.name }}</strong>' in insttpl and 'ลบ instance นี้' in dash_tpl and 'confirm_name' in dash_tpl,
 'delete is stopped-only in UI and backend':'{% if not bot.container or not bot.container.running %}' in insttpl and '{% if not bot.running %}' in dash_tpl and 'status_code=409' in app and 'ต้องหยุด instance ก่อนจึงจะลบได้' in app,
 'runtime status is API-only with no JSON fallback':'def live_state(path: Path, *, running: bool = True):' in app and 'return bot_api_status(path)' in app and 'runtime_status.json' not in app,
 'API uses loopback Bearer token':'http://127.0.0.1:{port}/v1/status' in app and 'Authorization' in app and 'Bearer {token}' in app,
 'multi-user database':'Store(DB_FILE)' in app and 'instance_owners' in storage,
 'first user becomes one atomic superadmin':'create_first_superadmin' in app and 'BEGIN IMMEDIATE' in storage and 'setup_required()' in app,
 'only superadmin creates accounts':'users_create' in app and 'require_superadmin(request)' in app,
 'tenant ownership enforced':'can_manage_instance' in app and 'owned_names' in app and 'owner_user_id' in app,
 'job ownership enforced':'can_view_job' in app and 'owner_user_id' in app and 'not can_view_job(user, initial)' in app,
 'tenant proves TeamTalk Administrator credentials':'verify_teamtalk_admin_credentials' in app and 'verify_teamtalk_password' in app and 'root_run_stdin' in app and 'verify-teamtalk-admin' in bridge and '/app/tools/verify_teamtalk_admin.py' in bridge,
 'TeamTalk verification password is stdin-only and non-persistent':'input=json.dumps(payload, ensure_ascii=False)' in app and 'sys.stdin.buffer.read' in bridge and '"docker","run","--rm","-i"' in bridge and 'verify_teamtalk_password' not in storage,
 'Linux lowercase instance rule':'NEW_BOT_NAME_RE = re.compile(r"^[a-z0-9][a-z0-9_.-]{0,62}$")' in app and 'pattern="[a-z0-9][a-z0-9_.-]{0,62}"' in newtpl,
 'config all sections':'config_for_form' in app and 'save_config_form' in app,
 'central Global Broadcast uses SQLite + loopback API scheduler':'SCHEMA_VERSION = 3' in storage and 'global_broadcast_messages' in storage and 'global_broadcast_state' in storage and 'def _global_broadcast_tick' in app and '/v1/events/global-broadcast' in app and 'bot_api_global_broadcast' in app and '@app.on_event("startup")' in app and 'tts_enabled' in app,
 'Global Broadcast is Manager/Full-only and interval bounded':'server_management_enabled' in app and 'global_broadcast' in app and 'interval_minutes' in app and '10080' in app and '_GLOBAL_BROADCAST_RETRY_AFTER' in app,
 'Super Admin can manage central broadcast messages':'@app.get("/broadcasts"' in app and '@app.post("/broadcasts")' in app and 'require_superadmin(request)' in app and 'ข้อความ Global Broadcast' in broadcasttpl and 'href="/broadcasts"' in base,
 'legacy configs gain disabled Global Broadcast defaults':'_ensure_web_managed_config_defaults' in app and 'random_message_interval' in app and 'random_broadcast_enabled' in app and 'cfg.remove_option("bot", "random_message_interval")' in app and 'cfg.remove_option("tts", "random_broadcast_enabled")' in app and 'cfg.set("global_broadcast", "enabled", "False")' in app and 'tts_enabled' in app,
 'config save applies running changes through TTUHelper restart':'kind="config-restart"' in app and 'job_helper_action, "restart", name' in app and 'docker_container(name)' in app,
 'new-instance channel field accepts ID or historical path':'Channel ID หรือ Channel path' in newtpl and 'gcid/cid' in newtpl and 'เช่น /music' in newtpl,
 'default_channel stays a text field for ID/path switching':'if sk == ("bot", "default_channel"):' in app and 'return "text"' in app and '("bot", "default_channel")' in app and 'gcid/cid' in app,
 'secret fields masked':'safe_secret_key' in app and 'clear_secret' in app,
'tenant cannot repoint verified TeamTalk identity':'TENANT_LOCKED_CONFIG_KEYS' in app and 'ผู้ใช้ทั่วไปไม่สามารถเปลี่ยน TeamTalk connection/login identity' in app and 'f.locked' in configtpl,
 'password recovery tool uses SQLite, not legacy auth.json':'webmanager.db' in password_tool and 'create_first_superadmin' in password_tool and "default='/etc/sntalkbot-web-manager/auth.json'" not in password_tool,
 'persistent sessions':'10 * 365 * 24 * 3600' in app,
 'login throttling':'LOGIN_MAX_FAILURES = 8' in app and 'login_blocked' in app,
 'realtime jobs':'StreamingResponse' in app and '/jobs/{jid}/stream' in app and 'EventSource' in js and 'data-job-id' in jobtpl,
 'in-page accessible Job dialog':'<dialog id="job-dialog"' in base and 'data-job-form' in system_tpl and 'X-SNTalkBot-Job-Dialog' in app and 'job_created_response' in app and 'showModal()' in js and 'ปิดและกลับไปทำงานต่อ' in js,
 'Job dialog endpoint is immune to form action DOM clobbering':'fetch(form.action' not in js and "form.getAttribute('action')" in js and 'new URL(actionAttr, document.baseURI).href' in js and 'name="action"' in system_tpl,
 'static JS/CSS URLs use content-hash cache busting':'/static/app.js?v={{ static_rev }}' in base and '/static/style.css?v={{ static_rev }}' in base and 'STATIC_REV' in app and 'hashlib.sha256' in app,
 'Users page hides create form until requested':'data-disclosure-target="create-user-panel"' in users_tpl and 'id="create-user-panel" hidden' in users_tpl and 'aria-expanded="false"' in users_tpl,
 'dashboard isolates malformed instance/realtime data':'Normalize old/new/partial realtime payloads' in app and 'warnings=[]' in app and 'ข้อมูลบางส่วนของ instance นี้อ่านไม่สมบูรณ์' in dash_tpl,
 'Super Admin dashboard uses authoritative batch snapshot and claims only unowned instances':'instances-snapshot' in app and 'docker-list-managed' in app and 'STORE.claim_unowned(names, int(user["id"]))' in app and 'owners_map(names)' in app and 'ผู้สร้าง/เจ้าของ:' in dash_tpl and 'สร้าง/นำเข้าเมื่อ:' in dash_tpl,
 'Dashboard realtime is one SSE stream with parallel bot probes':'/dashboard/live' in app and '_dashboard_live_rows' in app and 'asyncio.gather' in app and "new EventSource('/dashboard/live')" in js and 'dashboard-live-announcer' in dash_tpl,
 'System remote update probes do not block initial HTML':'system_status(False, include_expensive=False)' in app and '/system/remote-status' in app and 'ThreadPoolExecutor(max_workers=5)' in app and "fetch('/system/remote-status'" in js and 'การตรวจ GitHub/Docker Registry ทำต่อเบื้องหลัง' in system_tpl,
 'Dashboard batch snapshot has rolling-upgrade compatibility fallback':'_local_instance_snapshot' in app and 'Old root bridge compatibility only' in app and 'instances-snapshot' in bridge and 'docker-list-managed' in bridge,
 'last-resort 500 boundary is static and carries request id':'class LastResortErrorMiddleware' in app and '_last_resort_error_html' in app and 'X-SNTalkBot-Request-ID' in app and '@app.exception_handler(Exception)' in app and 'Request ID' in app,
 'realtime instance SSE':'/instances/{name}/live' in app and 'await asyncio.sleep(0.5)' in app and 'live-instance' in insttpl and 'container_running' in app and 'บอตหยุดอยู่ — ไม่มีข้อมูลสด' in js,
 'room/server realtime fields rendered':'room_users_online' in app and 'server_users_online' in app and 'live-room-users' in insttpl and 'live-server-users' in insttpl and 'admins_in_room_count' in app,
 'service does not run as root':'User=$SERVICE_USER' in installer and 'SERVICE_USER="${SNWEB_SERVICE_USER:-sntalkweb}"' in installer,
 'installer explicitly creates same-name service group':'groupadd --system "$SERVICE_USER"' in installer and 'useradd --system --gid "$SERVICE_USER"' in installer,
 'installer preserves existing environment settings on upgrade':'Keeping existing Web Manager settings; adding only missing defaults.' in installer and 'write_default SNWEB_COOKIE_SECURE' in installer,
 'manual/bootstrap installer converges Guardian + backend and verifies deployed version':'GUARDIAN_SERVICE="sntalkbot-web-guardian"' in installer and 'SNWEB_APP_PORT' in installer and 'app_health_url' in installer and 'Guardian is stable' in installer and 'enable --now sntalkbot-web-manager' not in installer,
 'routine Web Manager update keeps stable Guardian binary/unit unchanged':'if [[ ! -f "$GUARDIAN_SCRIPT" ]]' in installer and 'Keeping existing stable Web Guardian unchanged.' in installer and 'if [[ ! -f /etc/systemd/system/${GUARDIAN_SERVICE}.service ]]' in installer and 'Keeping existing stable Web Guardian systemd unit unchanged.' in installer and '${GUARDIAN_SCRIPT}.new' not in installer,
 'self-update installer can defer backend restart safely':'SNWEB_DEFER_RESTART' in installer and 'Guardian remains online' in installer and 'First Guardian transition scheduled' in installer,
 'self-update uses fresh staged checkout, rollback and scheduled backend restart':'replace_from_fresh_clone' in bridge and 'rollback_source_replace' in bridge and 'git","clone","--depth","1"' in bridge and 'SNWEB_DEFER_RESTART=1' in bridge and 'systemd-run' in bridge and '--on-active=2s' in bridge and 'GUARDIAN_TRANSITION_MARKER' in bridge,
 'privileged bridge is only sudo target':'NOPASSWD: $ROOT_BRIDGE *' in installer and 'snweb-root' in installer,
 'root bridge allowlist':'action not allowed' in bridge and 'migrate-ttmediabot' in bridge and 'install-stack' in bridge and 'bot-config-template' in bridge and 'bot-image-version' in bridge and 'container-name-check' in bridge,
 'Docker tenant isolation':'managed_container_json' in bridge and 'refusing unmanaged Docker container' in bridge and 'com.ttutilities.helper' in bridge and 'com.ttutilities.data' in bridge,
 'new-instance Docker name collision preflight':'container-name-check' in app and 'Docker container name is already in use' in bridge,
 'installer preflight':all(x in installer for x in ('has python3','has git','has curl','if has docker')),
 'no live git-pull updater remains':'pull --ff-only' not in bridge and 'pull --ff-only' not in app and 'pull --ff-only' not in (root/'install_remote.sh').read_text(encoding='utf-8'),
 'remote updater preserves full source before replace':'Preserving complete previous source' in (root/'install_remote.sh').read_text(encoding='utf-8') and '.incoming-' in (root/'install_remote.sh').read_text(encoding='utf-8') and '.failed-' in (root/'install_remote.sh').read_text(encoding='utf-8'),
 'rollback restores running Web Manager process as well as source':'systemctl restart sntalkbot-web-manager' in (root/'install_remote.sh').read_text(encoding='utf-8') and 'project_name == "Web Manager"' in bridge and '["systemctl","restart","sntalkbot-web-manager"]' in bridge,
 'production does not require /opt/sntalkbot source':'SNWEB_BOT_SOURCE' not in app and 'SNWEB_BOT_SOURCE' not in bridge and 'SNWEB_BOT_SOURCE' not in installer and 'update-bot-source' not in app and 'update-bot-source' not in bridge,
 'config template comes from Docker image':'bot-config-template' in app and 'image_text("/app/config_default.ini")' in bridge and '["docker","run","--rm","--entrypoint","cat",image_name(),path]' in bridge,
 'migration template comes from Docker image':'TemporaryDirectory(prefix="snweb-migrate-")' in bridge and 'template.write_text(image_text("/app/config_default.ini")' in bridge,
 'migration role is explicit in job output':'ประเภทบอตที่เลือก:' in app and 'นโยบาย config:' in app,
 'CloudPanel loopback default':'BIND="${SNWEB_BIND:-127.0.0.1}"' in installer and 'PORT="${SNWEB_PORT:-28765}"' in installer,
 'normal-user nav hides privileged pages':"{% if user.role == 'superadmin' %}" in base and '/users' in base and '/system' in base,
 'admin list excludes bot explained':'ไม่รวมบัญชีของบอตเอง' in insttpl,
 'user help stays task-focused':'127.0.0.1:28765' in help_tpl and '28766' not in help_tpl and '20000' not in help_tpl and 'privileged bridge' not in help_tpl and '124 canonical commands' not in help_tpl,
 'footer has copyright and developer links':'© 2026 Nuttawat' in base and 'https://github.com/nuttawat-arch' in base and 'https://github.com/nuttawat-arch/sntalkbot-web-manager' in base,
 'guardian architecture documented':'Guardian' in system_tpl and '28765' in proxyguide and '28766' in proxyguide,
 'stable 28765 Guardian + private 28766 backend defaults':'28766' in mainmod and "'127.0.0.1'" in mainmod and '127.0.0.1:28765' in nginx and 'PUBLIC_PORT' in guardian and 'BACKEND_PORT' in guardian and "'8765'" not in mainmod and ':8765' not in nginx,
 'reverse proxy guide covers standalone and common proxies':all(x in proxyguide for x in ('Standalone','CloudPanel','NGINX','Caddy','Apache','proxy_buffering off','SNWEB_COOKIE_SECURE')),
}
for name,ok in checks.items(): need(ok,name)
# Root bridge should never expose generic shell/user-provided executable APIs.
need('subprocess.run([str(x) for x in args]' in bridge and 'os.system' not in bridge and 'subprocess.Popen' not in bridge, 'root bridge executes only structured allowlisted argv actions')
# Shell syntax is authoritative on Linux. Windows publication deliberately does
# not translate native paths into Git-Bash paths because that made a Linux gate
# spuriously block a valid Windows release. server_verify.sh runs bash -n later.
if PORTABLE_ONLY:
    defer('installer shell syntax valid (authoritative bash -n runs on Linux server)')
    defer('remote installer shell syntax valid (authoritative bash -n runs on Linux server)')
else:
    need(subprocess.run(['bash','-n',str(root/'install.sh')],capture_output=True).returncode==0,'installer shell syntax valid')
    need(subprocess.run(['bash','-n',str(root/'install_remote.sh')],capture_output=True).returncode==0,'remote installer shell syntax valid')
crlf=[]
for path in root.rglob('*'):
    if not path.is_file() or '.git' in path.parts or '__pycache__' in path.parts or '.venv' in path.parts: continue
    if path.suffix.lower() not in {'.py','.sh','.html','.js','.css','.md','.txt'} and path.name not in {'VERSION','.gitattributes'}: continue
    if b'\r\n' in path.read_bytes(): crlf.append(str(path.relative_to(root)))
need(not crlf, 'Linux/Web Manager source line endings are LF-only')
if crlf: print('CRLF files: '+', '.join(crlf[:12]))

# The Web Manager is a Linux service. On a Windows publisher, stop after the
# portable/static contract above. The following tests intentionally exercise
# Linux ownership (os.chown), Bash, Guardian sockets, SQLite lifecycle,
# TestClient integration and privileged action routing. They are executed in
# full by SNTalkBot-Release-Automation/server_verify.sh on the Linux host.
if PORTABLE_ONLY:
    for msg in (
        'central Global Broadcast SQLite runtime persistence/rotation',
        'first-run auth + tenant isolation + privileged-page/job ownership TestClient flow',
        'create/run/stop/restart/delete/logs/config/limits/cookies/system/migration action matrix',
        'batch instance discovery + ownership functional regression',
        'staged source updater backup/rollback functional regression',
        'Guardian public socket/form/SSE runtime regression',
        'SQLite password recovery runtime regression',
    ):
        defer(msg)
    if errors:
        print('\n'.join(errors)); raise SystemExit(1)
    print('[OK] Windows portable Web Manager validation passed; Linux runtime validation is deferred to server_verify.sh')
    raise SystemExit(0)

# Central broadcast persistence/rotation must survive process restart and stay in SQLite.
try:
    with tempfile.TemporaryDirectory() as td:
        spec=__import__('importlib.util').util.spec_from_file_location('_snweb_storage_validation', root/'webmanager/storage.py')
        smod=__import__('importlib.util').util.module_from_spec(spec); spec.loader.exec_module(smod)
        store=smod.Store(Path(td)/'webmanager.db')
        first=store.create_global_broadcast_message('ข้อความหนึ่ง', enabled=True)
        second=store.create_global_broadcast_message('ข้อความสอง', enabled=True)
        assert [r['id'] for r in store.list_global_broadcast_messages(enabled_only=True)]==[first,second]
        assert store.next_global_broadcast_message(0)['id']==first
        assert store.next_global_broadcast_message(first)['id']==second
        assert store.next_global_broadcast_message(second)['id']==first
        assert store.update_global_broadcast_message(first,message='ข้อความหนึ่งแก้ไข',enabled=False)
        assert store.next_global_broadcast_message(0)['id']==second
        store.set_global_broadcast_state('manager-a',last_sent=123.5,last_message_id=second)
        # Re-open through a fresh Store instance to prove persistence rather than RAM-only state.
        store2=smod.Store(Path(td)/'webmanager.db')
        state=store2.global_broadcast_state('manager-a')
        assert state['last_sent']==123.5 and state['last_message_id']==second
        assert store2.delete_global_broadcast_message(first)
        need(True,'central Global Broadcast messages, rotation and per-instance schedule state persist in SQLite')
except Exception as exc:
    need(False,f'central Global Broadcast SQLite runtime test: {exc!r}')

# Functional tenant/auth test with isolated data/root. No host Docker/TTUHelper action is invoked.
try:
    with tempfile.TemporaryDirectory() as td:
        t=Path(td); bots=t/'bots'; bots.mkdir(); etc=t/'ttu.conf'; secret=t/'secret'; secret.write_text('validation-secret-0123456789\n')
        etc.write_text(f'TTU_BOTS_ROOT="{bots}"\nTTU_IMAGE_REPO="example/bot"\nTTU_TAG="latest"\n')
        env=os.environ.copy(); env.update({
            'SNWEB_DATA_DIR':str(t/'data'),'SNWEB_DB_FILE':str(t/'data/db.sqlite'),'SNWEB_SESSION_SECRET_FILE':str(secret),
            'TTU_HELPER_CONFIG':str(etc),'SNWEB_ROOT_BRIDGE':'/bin/false',
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
assert 'data-disclosure-target="create-user-panel"' in r.text and 'id="create-user-panel" hidden' in r.text
m=re.search(r'name=\"csrf\" value=\"([^\"]+)\"',r.text); assert m
csrf=m.group(1)
# Central Global Broadcast CRUD is Super Admin-only and persists immediately.
r=client.get('/broadcasts'); assert r.status_code==200 and 'ข้อความ Global Broadcast ส่วนกลาง' in r.text
r=client.post('/broadcasts',data={'csrf':csrf,'message':'ประกาศส่วนกลางทดสอบ','enabled':'1'},follow_redirects=False); assert r.status_code==303
rows=mod.STORE.list_global_broadcast_messages(); assert len(rows)==1 and rows[0]['message']=='ประกาศส่วนกลางทดสอบ' and rows[0]['enabled']==1
# Job-producing forms support in-page dialog metadata while normal redirects remain available.
rj=client.post('/system/action',data={'csrf':csrf,'action':'doctor'},headers={'X-SNTalkBot-Job-Dialog':'1','X-SNTalkBot-Return-To':'/system'},follow_redirects=False); assert rj.status_code==202
meta=rj.json(); assert meta['job_id'] and meta['stream_url'].endswith('/stream') and meta['return_to']=='/system'
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
assert client2.get('/broadcasts').status_code==403
r=client2.get('/instances/mine/config'); assert r.status_code==200 and 'ล็อกสำหรับบัญชีผู้ใช้ทั่วไป' in r.text
m2=re.search(r'name="csrf" value="([^"]+)"',r.text); assert m2
customer_csrf=m2.group(1)
# A tenant whose Web username differs from TeamTalk can self-prove an Admin credential.
def tenant_root(args, timeout=120, check=False):
 a=tuple(str(x) for x in args)
 if a and a[0]=='container-name-check': return 0,''
 if a and a[0]=='bot-config-template':
  return 0,'[server]\\naddress=\\ntcp_port=10333\\nudp_port=10333\\nencrypted=False\\nusername=\\npassword=\\n[bot]\\nlanguage=th\\nnickname=SN TalkBot\\ndefault_channel=/\\nchannel_password=\\nstatus_message=auto\\n[accounts]\\nauthorized_users=\\n[features]\\nplayer_enabled=True\\nserver_management_enabled=True\\n[playback]\\ncookiefile_path=/app/data/cookies.txt\\n'
 if a and a[0]=='docker-inspect': return 1,''
 return 0,''
def tenant_root_stdin(args,payload,timeout=45,check=False):
 assert tuple(args)==('verify-teamtalk-admin',)
 assert payload['username']=='tenantadmin' and payload['password']=='tenant-proof-secret'
 return 0,'{"ok":true,"authenticated":true,"administrator":true,"username":"tenantadmin","user_id":88,"user_type":2}\\n'
mod.root_run=tenant_root; mod.root_run_stdin=tenant_root_stdin
r=client2.get('/instances/new'); assert r.status_code==200 and 'TeamTalk Administrator password' in r.text
csrf_new=re.search(r'name="csrf" value="([^"]+)"',r.text).group(1)
r=client2.post('/instances/new',data={'csrf':csrf_new,'name':'tenantbot','role':'manager','hostname':'server.example','tcp_port':'10333','udp_port':'10333','verify_teamtalk_username':'tenantadmin','verify_teamtalk_password':'tenant-proof-secret','username':'botservice','password':'bot-only-secret','language':'th'},follow_redirects=False); assert r.status_code==303
jid=r.headers['location'].rsplit('/',1)[-1].split('?',1)[0]
for _ in range(100):
 j=mod.jobs.get(jid)
 if j.get('status') in ('success','failed'): break
 time.sleep(.02)
assert mod.jobs.get(jid).get('status')=='success', mod.jobs.get(jid)
owner=mod.STORE.owner('tenantbot'); assert owner and owner['teamtalk_admin_username']=='tenantadmin'
assert 'tenant-proof-secret' not in (root/'tenantbot'/'config.ini').read_text()
assert b'tenant-proof-secret' not in Path(mod.DB_FILE).read_bytes()
assert all('tenant-proof-secret' not in str(j.get('output') or '') for j in mod.jobs.jobs.values())
r=client2.post('/instances/mine/config',data={'csrf':customer_csrf,'kind__server__address':'text','cfg__server__address':'unauthorized.example'},follow_redirects=False); assert r.status_code==403
assert 'address=x' in (root/'mine'/'config.ini').read_text()
# Super Admin can still perform an intentional connection change.
r=client.post('/instances/mine/config',data={'csrf':csrf,'kind__server__address':'text','cfg__server__address':'admin-approved.example'},follow_redirects=False); assert r.status_code==303
assert 'address = admin-approved.example' in (root/'mine'/'config.ini').read_text()
j1=mod.jobs.create('admin secret job',lambda:'done',owner_user_id=admin['id']); time.sleep(.1)
assert client2.get('/jobs/'+j1).status_code==404
j2=mod.jobs.create('customer job',lambda:'done',owner_user_id=customer['id']); time.sleep(.1)
assert client2.get('/jobs/'+j2).status_code==200
# One malformed migrated instance must not turn the whole dashboard into HTTP 500.
bad=root/'brokenmigrate'; bad.mkdir(); (bad/'config.ini').write_text('[broken\\nvalue=x\\n'); mod.STORE.set_owner('brokenmigrate',admin['id'],'')
r=client.get('/'); assert r.status_code==200 and 'brokenmigrate' in r.text and 'ข้อมูลบางส่วนของ instance นี้อ่านไม่สมบูรณ์' in r.text
# A failing *fast* dashboard probe is isolated as a warning instead of taking down /.
# Heavy image/registry probes are deliberately absent from the initial Dashboard request.
orig_helper_version=mod.helper_version
def probe_boom(): raise RuntimeError('validator-probe-boom')
mod.helper_version=probe_boom
r=client.get('/'); assert r.status_code==200 and 'TTUHelper version: RuntimeError' in r.text
mod.helper_version=orig_helper_version
partial=mod.normalize_live_payload({'room_users_online':1,'player':{'title':'เพลงทดสอบ'},'channel':None,'teamtalk_activity':None})
assert partial['channel']=={'id':0,'name':''} and partial['teamtalk_activity']['speaking']==0 and partial['player']['queue']==[]
# The normal FastAPI exception handler must return Thai HTML + Request ID.
async def validator_boom(): raise RuntimeError('validator-route-boom')
mod.app.add_api_route('/__validator_boom', validator_boom, methods=['GET'])
no_raise=TestClient(mod.app, raise_server_exceptions=False)
r=no_raise.get('/__validator_boom'); assert r.status_code==500 and 'Request ID:' in r.text and r.headers.get('x-sntalkbot-request-id')
# The outer pure-ASGI boundary must work even if failure is outside routing/Jinja/session.
async def bare_boom(scope, receive, send): raise RuntimeError('validator-asgi-boom')
boundary_client=TestClient(mod.LastResortErrorMiddleware(bare_boom), raise_server_exceptions=False)
r=boundary_client.get('/'); assert r.status_code==500 and 'Request ID:' in r.text and r.headers.get('x-sntalkbot-request-id')
print('FUNCTIONAL_OK')
""" % str(root)
        proc=subprocess.run([sys.executable,'-c',test_code],env=env,capture_output=True,text=True,timeout=30)
        need(proc.returncode==0 and 'FUNCTIONAL_OK' in proc.stdout, 'first-run auth, tenant instance isolation, privileged-page denial and job ownership execute in TestClient')
        if proc.returncode: print(proc.stdout); print(proc.stderr)
except Exception as exc:
    need(False,f'functional Web Manager test: {exc!r}')

# Functional action-matrix test. Privileged calls are replaced with an in-process
# recorder, so every web route can be exercised without touching host Docker,
# TTUHelper, systemd, or real instances.
try:
    with tempfile.TemporaryDirectory() as td:
        t=Path(td); bots=t/'bots'; bots.mkdir(); etc=t/'ttu.conf'; secret=t/'secret'; secret.write_text('validation-secret-actions-0123456789\n')
        etc.write_text(f'TTU_BOTS_ROOT="{bots}"\nTTU_IMAGE_REPO="example/bot"\nTTU_TAG="latest"\n')
        env=os.environ.copy(); env.update({
            'SNWEB_DATA_DIR':str(t/'data'),'SNWEB_DB_FILE':str(t/'data/db.sqlite'),'SNWEB_SESSION_SECRET_FILE':str(secret),
            'TTU_HELPER_CONFIG':str(etc),'SNWEB_ROOT_BRIDGE':'/bin/false',
        })
        action_code = r"""
from pathlib import Path
import re, sys, time
sys.path.insert(0, %r)
from fastapi.testclient import TestClient
from webmanager import app as mod
calls=[]
def fake_root(args, timeout=120, check=False):
    a=tuple(str(x) for x in args); calls.append(('root',a))
    if a and a[0]=='bot-config-template':
        return 0, '[server]\naddress=\ntcp_port=10333\nudp_port=10333\nencrypted=False\nusername=\npassword=\n[bot]\nlanguage=th\nnickname=SN TalkBot\ndefault_channel=/\nchannel_password=\nstatus_message=auto\n[accounts]\nauthorized_users=\n[features]\nplayer_enabled=True\nserver_management_enabled=True\n[playback]\ncookiefile_path=/app/data/cookies.txt\n'
    if a and a[0]=='container-name-check': return 0,''
    if a and a[0]=='docker-logs': return 0,'hello-log\n'
    if a and a[0]=='docker-inspect': return 1,''
    if a and a[0]=='bot-image-version': return 0,'5.1.1\n'
    if a and a[0]=='image-inspect': return 1,''
    if a and a[0]=='remote-image-inspect': return 1,''
    return 0,''
def fake_root_stdin(args, payload, timeout=45, check=False):
    calls.append(('root-stdin',tuple(str(x) for x in args),tuple(sorted(payload.keys()))))
    assert payload.get('password') == 'owner-secret'
    return 0, '{"ok":true,"authenticated":true,"administrator":true,"username":"owneradmin","user_id":77,"user_type":2}\n'
def fake_stream(args, timeout=1800):
    calls.append(('stream',tuple(str(x) for x in args))); return 0
mod.root_run=fake_root; mod.root_run_stdin=fake_root_stdin; mod.stream_root=fake_stream
assert mod.verify_teamtalk_admin_credentials({'hostname':'teamtalk.example','tcp_port':10333,'udp_port':10333,'encrypted':False},'owneradmin','owner-secret') == 'owneradmin'
client=TestClient(mod.app)
r=client.post('/setup',data={'username':'rootadmin','display_name':'Owner','password':'verystrongpass1','password2':'verystrongpass1'},follow_redirects=False); assert r.status_code==303
r=client.get('/'); assert r.status_code==200
csrf=re.search(r'name="csrf" value="([^"]+)"',r.text).group(1)
# Create action
r=client.post('/instances/new',data={'csrf':csrf,'name':'actionbot','role':'full','nickname':'Action Bot','hostname':'teamtalk.example','tcp_port':'10333','udp_port':'10333','owner_teamtalk_username':'owneradmin','authorized_users':'owneradmin','language':'th','status_message':'auto'},follow_redirects=False); assert r.status_code==303
jid=r.headers['location'].rsplit('/',1)[-1].split('?',1)[0]
for _ in range(100):
    j=mod.jobs.get(jid)
    if j.get('status') in ('success','failed'): break
    time.sleep(.02)
assert mod.jobs.get(jid).get('status')=='success', mod.jobs.get(jid)
assert (mod.bots_root()/'actionbot'/'config.ini').is_file()
assert any(x[1] and x[1][0]=='container-name-check' for x in calls)
assert any(x[0]=='root-stdin' and x[1]==('verify-teamtalk-admin',) for x in calls)
# Logs
r=client.get('/instances/actionbot/logs'); assert r.status_code==200 and 'hello-log' in r.text
# Config
r=client.get('/instances/actionbot/config'); assert r.status_code==200
csrf2=re.search(r'name="csrf" value="([^"]+)"',r.text).group(1)
r=client.post('/instances/actionbot/config',data={'csrf':csrf2,'kind__bot__nickname':'text','cfg__bot__nickname':'Changed Bot'},follow_redirects=False); assert r.status_code==303
# Limits
r=client.post('/instances/actionbot/limits',data={'csrf':csrf,'cpu':'0.5','memory':'256m'},follow_redirects=False); assert r.status_code==303
assert 'cpu=0.5' in (mod.bots_root()/'actionbot'/'limits.conf').read_text()
# Cookies install + check
r=client.post('/instances/actionbot/cookies',data={'csrf':csrf},files={'cookie_file':('cookies.txt',b'# Netscape HTTP Cookie File\n.youtube.com\tTRUE\t/\tTRUE\t0\tSID\tx\n','text/plain')},follow_redirects=False); assert r.status_code==303
r=client.post('/instances/actionbot/cookies-check',data={'csrf':csrf},follow_redirects=False); assert r.status_code==303
# Instance run/stop/restart
for action in ('run','stop','restart'):
    r=client.post('/instances/actionbot/action',data={'csrf':csrf,'action':action},follow_redirects=False); assert r.status_code==303
# System actions
for action in ('install-stack','update-helper','update-web','pull-image','update-running','doctor','start-all','stop-all'):
    r=client.post('/system/action',data={'csrf':csrf,'action':action},follow_redirects=False); assert r.status_code==303
# All cookies
r=client.post('/system/cookies-all',data={'csrf':csrf},files={'cookie_file':('cookies.txt',b'# Netscape HTTP Cookie File\n.youtube.com\tTRUE\t/\tTRUE\t0\tSID\tx\n','text/plain')},follow_redirects=False); assert r.status_code==303
# Migration route
r=client.post('/migrate',data={'csrf':csrf,'source':'/tmp/legacy-source','role':'full','dry_run':'on'},follow_redirects=False); assert r.status_code==303
# Wait for queued actions
for _ in range(200):
    if all(j.get('status') in ('success','failed') for j in list(mod.jobs.jobs.values())): break
    time.sleep(.02)
expected=[
 ('helper','cks','actionbot'),('helper','cks-check','actionbot'),('helper','run','actionbot'),('helper','stop','actionbot'),('helper','restart','actionbot'),
 ('install-stack',),('update-helper',),('update-web',),('helper','pull'),('helper','update'),('helper','doctor'),('helper','start-all'),('helper','stop-all'),('helper','cks-all'),('migrate-ttmediabot',)
]
flat=[c[1] for c in calls if c[0]=='stream']+[c[1] for c in calls if c[0]=='root']
for want in expected:
    assert any(tuple(row[:len(want)])==want for row in flat), (want,flat)
# Migration role selected in the form must cross Web Manager/root bridge unchanged.
migration_calls=[row for row in flat if row and row[0]=='migrate-ttmediabot']
assert any(len(row)>=3 and row[2]=='full' for row in migration_calls), migration_calls
# A stopped container must never surface a fresh-looking runtime_status fallback.
rows=mod.list_instances(); assert next(x for x in rows if x['name']=='actionbot')['runtime'] is None
# Running instances must not show Delete and backend must reject a direct bypass.
orig_docker_container=mod.docker_container
orig_live_state=mod.live_state
mod.docker_container=lambda name: {'name':name,'running':True,'status':'running'}
mod.live_state=lambda *a,**k: None
r=client.get('/'); assert r.status_code==200 and 'ลบ instance นี้' not in r.text
r=client.post('/instances/actionbot/action',data={'csrf':csrf,'action':'delete','confirm_name':'actionbot'},follow_redirects=False); assert r.status_code==409
mod.docker_container=orig_docker_container
mod.live_state=orig_live_state
# Once stopped, Dashboard exposes the confirmed delete group.
r=client.get('/'); assert r.status_code==200 and 'ลบ instance นี้' in r.text and 'confirm_name' in r.text
# Delete last; ownership must be removed only after the job action is queued/executed.
r=client.post('/instances/actionbot/action',data={'csrf':csrf,'action':'delete','confirm_name':'actionbot'},follow_redirects=False); assert r.status_code==303
jid=r.headers['location'].rsplit('/',1)[-1].split('?',1)[0]
for _ in range(100):
    j=mod.jobs.get(jid)
    if j.get('status') in ('success','failed'): break
    time.sleep(.02)
assert mod.jobs.get(jid).get('status')=='success'
assert any(row[:3]==('helper','delete','actionbot') for row in [c[1] for c in calls if c[0]=='stream'])
print('ACTION_MATRIX_OK')
""" % str(root)
        proc=subprocess.run([sys.executable,'-c',action_code],env=env,capture_output=True,text=True,timeout=45)
        need(proc.returncode==0 and 'ACTION_MATRIX_OK' in proc.stdout, 'create/run/stop/restart/delete/logs/config/limits/cookies/system/migration routes execute through the expected action matrix')
        if proc.returncode: print(proc.stdout); print(proc.stderr)
except Exception as exc:
    need(False,f'functional Web Manager action matrix: {exc!r}')

# Functional batch-discovery/ownership regression: Super Admin sees every real
# instance, unowned legacy instances are assigned only to Super Admin, and a
# normal tenant still sees only their own mapping.
try:
    with tempfile.TemporaryDirectory() as td:
        t=Path(td); bots=t/'bots'; bots.mkdir(); etc=t/'ttu.conf'; secret=t/'secret'; secret.write_text('snapshot-validation-secret-0123456789\n')
        etc.write_text(f'TTU_BOTS_ROOT="{bots}"\nTTU_IMAGE_REPO="example/bot"\nTTU_TAG="latest"\n')
        env=os.environ.copy(); env.update({
            'SNWEB_DATA_DIR':str(t/'data'),'SNWEB_DB_FILE':str(t/'data/db.sqlite'),'SNWEB_SESSION_SECRET_FILE':str(secret),
            'TTU_HELPER_CONFIG':str(etc),'SNWEB_ROOT_BRIDGE':'/bin/false',
        })
        snapshot_code = r"""
import json, re, sys
sys.path.insert(0, %r)
from fastapi.testclient import TestClient
from webmanager import app as mod
snapshot=[
 {'name':'LegacyBot','role':'player','nickname':'Legacy','server':'tt.example','channel':'/','created_at':'2026-08-20T01:02:03+00:00','config_warning':''},
 {'name':'TenantBot','role':'player','nickname':'Tenant','server':'tt.example','channel':'/room','created_at':'2026-08-21T02:03:04+00:00','config_warning':''},
]
containers={x['name']:{'exists':True,'running':True,'status':'running','image':'example/bot:latest','restart_count':0} for x in snapshot}
def fake_root(args,timeout=120,check=False):
 a=tuple(str(x) for x in args)
 if a==('instances-snapshot',): return 0,json.dumps(snapshot)
 if a==('docker-list-managed',): return 0,json.dumps(containers)
 if a and a[0]=='bot-image-version': return 0,'5.1.6\n'
 if a and a[0]=='image-inspect': return 1,''
 if a and a[0]=='docker-inspect': return 1,''
 return 0,''
mod.root_run=fake_root
mod.helper_version=lambda:'1.5.3'; mod.guardian_status=lambda:{'ok':True,'guardian_version':'1.0.0','backend':'127.0.0.1:28766'}
client=TestClient(mod.app)
r=client.post('/setup',data={'username':'rootadmin','display_name':'Root Owner','password':'verystrongpass1','password2':'verystrongpass1'},follow_redirects=False); assert r.status_code==303
admin=mod.STORE.get_user_by_username('rootadmin')
customer=mod.STORE.create_user('customer','customerpass123',display_name='Customer',created_by=admin['id'])
mod.STORE.set_owner('TenantBot',customer['id'],'tenantadmin')
r=client.get('/'); assert r.status_code==200
assert 'บอตทั้งหมด (2)' in r.text and 'LegacyBot' in r.text and 'TenantBot' in r.text
assert 'Root Owner (rootadmin)' in r.text and '2026-08-20T01:02:03+00:00' in r.text
assert mod.STORE.owner('LegacyBot')['owner_user_id']==admin['id']
assert mod.STORE.owner('TenantBot')['owner_user_id']==customer['id']
client2=TestClient(mod.app); assert client2.post('/login',data={'username':'customer','password':'customerpass123'},follow_redirects=False).status_code==303
r=client2.get('/'); assert r.status_code==200 and 'บอตของคุณ (1)' in r.text and 'TenantBot' in r.text and 'LegacyBot' not in r.text
print('SNAPSHOT_OWNERSHIP_OK')
""" % str(root)
        proc=subprocess.run([sys.executable,'-c',snapshot_code],env=env,capture_output=True,text=True,timeout=30)
        need(proc.returncode==0 and 'SNAPSHOT_OWNERSHIP_OK' in proc.stdout, 'Super Admin sees all batch-discovered instances while tenant count/ownership stays isolated')
        if proc.returncode: print(proc.stdout); print(proc.stderr)
except Exception as exc:
    need(False,f'batch ownership functional test: {exc!r}')

# Functional source-updater regression: a dirty live tree must be backed up and replaced
# only after a fresh staged clone succeeds. No network/git process is invoked.
try:
    with tempfile.TemporaryDirectory() as td:
        import importlib.util
        t=Path(td); target=t/'web'; target.mkdir(); (target/'local-edit.txt').write_text('keep me')
        (target/'.git').mkdir(); (target/'install.sh').write_text('#!/bin/sh\nexit 0\n')
        spec=importlib.util.spec_from_file_location('snweb_root_bridge_test', root/'webmanager/root_bridge.py')
        rb=importlib.util.module_from_spec(spec); spec.loader.exec_module(rb)
        old_run=rb.run
        def fake_run(args,cwd=None,check=True):
            args=[str(x) for x in args]
            if args[:4]==['git','clone','--depth','1']:
                incoming=Path(args[-1]); incoming.mkdir(parents=True); (incoming/'.git').mkdir();
                (incoming/'install.sh').write_text('#!/bin/sh\nexit 0\n'); (incoming/'VERSION').write_text('new\n')
                return 0
            return 0
        rb.run=fake_run
        backup=rb.replace_from_fresh_clone('https://example.invalid/repo.git',target)
        need((target/'VERSION').read_text().strip()=='new' and backup is not None and (backup/'local-edit.txt').read_text()=='keep me', 'dirty Web Manager source is fully backed up and replaced by a fresh staged checkout')
        rb.rollback_source_replace(target,backup)
        need((target/'local-edit.txt').read_text()=='keep me', 'source updater rollback restores the complete previous tree')
        rb.run=old_run
except Exception as exc:
    need(False,f'functional staged source updater: {exc!r}')

# Guardian runtime regression: backend downtime must yield a maintenance response, not a raw proxy 502; once backend returns the same stable socket proxies again. POST bodies and SSE must pass through without buffering.
try:
    import socket, urllib.request, urllib.error
    def free_port():
        sock=socket.socket(); sock.bind(('127.0.0.1',0)); port=sock.getsockname()[1]; sock.close(); return port
    public_port=free_port(); backend_port=free_port()
    while backend_port == public_port:
        backend_port = free_port()
    env=os.environ.copy(); env.update({'SNWEB_BIND':'127.0.0.1','SNWEB_PORT':str(public_port),'SNWEB_APP_BIND':'127.0.0.1','SNWEB_APP_PORT':str(backend_port)})
    gp=subprocess.Popen([sys.executable,str(root/'guardian/snweb_guardian.py')],env=env,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True)
    try:
        for _ in range(40):
            try:
                urllib.request.urlopen(f'http://127.0.0.1:{public_port}/guardian-healthz',timeout=.2); break
            except Exception:
                if gp.poll() is not None:
                    out, err = gp.communicate(timeout=1)
                    raise AssertionError(f'guardian exited during startup rc={gp.returncode}: {out} {err}')
                time.sleep(.05)
        else:
            raise AssertionError('guardian health endpoint did not become ready')
        try:
            urllib.request.urlopen(f'http://127.0.0.1:{public_port}/',timeout=1); raise AssertionError('maintenance unexpectedly returned success')
        except urllib.error.HTTPError as exc:
            body=exc.read().decode('utf-8','replace'); assert exc.code==503 and 'กำลังเริ่มหรืออัปเดตบริการเว็บ' in body
        backend_code = '''from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
import sys,time
class H(BaseHTTPRequestHandler):
    protocol_version="HTTP/1.1"
    def log_message(self,*a): pass
    def do_GET(self):
        if self.path=="/events":
            self.send_response(200); self.send_header("Content-Type","text/event-stream"); self.send_header("Cache-Control","no-cache"); self.end_headers()
            self.wfile.write(b"data: first\\n\\n"); self.wfile.flush(); time.sleep(1.5)
            self.wfile.write(b"data: second\\n\\n"); self.wfile.flush(); return
        body=(b'{"ok":true,"version":"test"}' if self.path=="/healthz" else b"backend-ok")
        self.send_response(200); self.send_header("Content-Length",str(len(body))); self.end_headers(); self.wfile.write(body)
    def do_POST(self):
        n=int(self.headers.get("Content-Length") or 0); body=self.rfile.read(n)
        out=b"post:"+body
        self.send_response(200); self.send_header("Content-Length",str(len(out))); self.end_headers(); self.wfile.write(out)
ThreadingHTTPServer(("127.0.0.1",int(sys.argv[1])),H).serve_forever()
'''
        bp=subprocess.Popen([sys.executable,'-c',backend_code,str(backend_port)])
        try:
            reconnect_deadline = time.monotonic() + 8.0
            while time.monotonic() < reconnect_deadline:
                try:
                    with urllib.request.urlopen(f'http://127.0.0.1:{public_port}/healthz', timeout=.5) as resp:
                        payload = resp.read().decode()
                    if '"version":"test"' in payload:
                        break
                except Exception:
                    pass
                time.sleep(.1)
            else:
                raise AssertionError('guardian never reconnected to backend within 8 seconds')
            req=urllib.request.Request(f'http://127.0.0.1:{public_port}/echo',data=b'action=doctor',method='POST')
            with urllib.request.urlopen(req,timeout=2) as resp:
                assert resp.read()==b'post:action=doctor'
            started=time.monotonic()
            with urllib.request.urlopen(f'http://127.0.0.1:{public_port}/events',timeout=3) as resp:
                first=resp.readline()+resp.readline()
                elapsed=time.monotonic()-started
                assert b'data: first' in first, first
                assert elapsed < 1.2, f'first SSE event buffered for {elapsed:.2f}s'
        finally:
            bp.terminate(); bp.wait(timeout=5)
        need(True,'Guardian keeps the public socket, proxies forms and streams SSE without raw 502/buffering while FastAPI restarts')
    finally:
        gp.terminate(); gp.wait(timeout=5)
except Exception as exc:
    need(False,f'Guardian runtime test: {exc!r}')

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
