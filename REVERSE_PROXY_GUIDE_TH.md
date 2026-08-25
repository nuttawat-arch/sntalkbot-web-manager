# คู่มือติดตั้ง SNTalkBot Web Manager 1.1.11: Standalone และ Reverse Proxy

Web Manager ใช้ 2 service: `sntalkbot-web-guardian` คง socket `127.0.0.1:28765` สำหรับ Reverse Proxy และ `sntalkbot-web-manager` รัน FastAPI backend ที่ `127.0.0.1:28766` โดยค่าเริ่มต้น ทั้งคู่ไม่เปิดหน้าจัดการออก Internet โดยตรง

> พอร์ต `28765` คือ stable Guardian/public-upstream ของ Web Manager, `28766` คือ FastAPI backend ภายใน ส่วน HTTP API ของ SNTalkBot แต่ละ instance ใช้พอร์ตสุ่ม `20000-27999` บน `127.0.0.1` เท่านั้น ทั้งสองช่วงแยกกันและไม่ควรเปิดผ่าน Firewall/Router

## 1. ก่อนติดตั้ง

รองรับ Ubuntu/Debian และควรใช้เครื่องเดียวกับ TTUHelper/SNTalkBot เพื่อให้เว็บอ่าน instance และเรียก privileged bridge ได้โดยตรง

ตรวจระบบเบื้องต้น:

```bash
uname -a
cat /etc/os-release
ss -ltn | grep ':28765 ' || true
```

ถ้าไม่มีผลจากคำสั่งสุดท้าย พอร์ต 28765 ยังว่างตามปกติ หากมี service อื่นใช้อยู่ ให้เลือกพอร์ตใหม่ เช่น `28775` และใช้เลขเดียวกันใน Reverse Proxy

## 2. ติดตั้งจาก ZIP

แตกไฟล์ release แล้ว:

```bash
sudo mkdir -p /opt/sntalkbot-web-manager
sudo unzip -o SNTalkBot-Web-Manager-1.1.11.zip -d /opt/sntalkbot-web-manager
cd /opt/sntalkbot-web-manager
sudo chmod +x install.sh install_remote.sh
sudo ./install.sh
```

ตัวติดตั้งจะตรวจ `python3`, `git`, `curl`, `sudo`, Python venv, CA certificates และ Docker ก่อน ติดตั้งเฉพาะสิ่งที่ขาด จากนั้นสร้าง system user `sntalkweb`, virtual environment, stable Guardian service, FastAPI backend service, session secret และ privileged allowlist bridge

ตรวจหลังติดตั้ง:

```bash
sudo systemctl status sntalkbot-web-manager --no-pager
curl -fsS http://127.0.0.1:28765/guardian-healthz
curl -fsS http://127.0.0.1:28765/healthz
curl -fsS http://127.0.0.1:28766/healthz
```

## 2.1 ติดตั้งแบบคำสั่งเดียวจาก Download Site

เมื่อหน้า Download รุ่น 5.1.0 ขึ้นไปถูก publish แล้ว สามารถใช้ตัว bootstrap ได้:

```bash
curl -fsSL https://ttdl.nuttawat.ddnsfree.com/install_web_manager.sh | sudo bash
```

หรือถ้ามี `wget`:

```bash
wget -qO- https://ttdl.nuttawat.ddnsfree.com/install_web_manager.sh | sudo bash
```

ตัว bootstrap ตรวจเครื่องมือที่ต้องใช้ก่อน, ดาวน์โหลด `SNTalkBot-Web-Manager-latest.zip` พร้อม `.sha256`, ตรวจ SHA-256 และแตกไป staging ก่อนแตะของเดิม จากนั้นสำรอง source เดิมทั้งโฟลเดอร์แล้วจึงติดตั้งรุ่นใหม่ จึงไม่ติดปัญหา local changes หรือ `.git`; ถ้า installer ล้มจะ restore source รุ่นเดิมให้อัตโนมัติ

ตั้งแต่ 1.1.7 เป็นต้นไป Guardian 1.0.0 เป็น service กลางคงที่และติดตั้งเฉพาะครั้งแรก Routine self-update จะไม่เขียนทับหรือ restart Guardian; หน้าเว็บจึงยังตอบ maintenance/health ได้ระหว่าง FastAPI backend restart การอัปเกรด Guardian ในอนาคตต้องทำเป็น migration แยกโดยตั้งใจ

## 3. ติดตั้งจาก GitHub

```bash
cd /opt
sudo git clone https://github.com/nuttawat-arch/sntalkbot-web-manager.git
cd /opt/sntalkbot-web-manager
sudo chmod +x install.sh install_remote.sh
sudo ./install.sh
```

ถ้ามี repo/การติดตั้งอยู่แล้ว ไม่ต้อง `git pull` ให้ใช้ updater ที่ทนต่อ local changes โดยตรง:

```bash
sudo bash /opt/sntalkbot-web-manager/install_remote.sh
```

`install_remote.sh` จะตรวจ `git`/CA certificates, clone รุ่นใหม่ลง staging, สำรอง source เดิมทั้งโฟลเดอร์และ rollback ได้เอง:

```bash
sudo bash /opt/sntalkbot-web-manager/install_remote.sh
```

## 4. เปิดครั้งแรก

เปิด URL ที่ Reverse Proxy ชี้มา หรือ Standalone URL แล้วหน้าแรกจะเป็น Initial Setup เพราะฐานข้อมูลยังไม่มีผู้ใช้ ให้สร้าง Username/Password ของ Super Admin คนแรก บัญชีนี้เป็นผู้ดูแลสูงสุดของ Web Manager

หลัง Setup แล้วหน้า Setup จะไม่เปิดให้สร้าง Super Admin คนใหม่อีก Super Admin เดิมเป็นผู้สร้างบัญชีลูกค้าเพิ่มเติมจากเมนู `บัญชีผู้ใช้`

---

# วิธี A — Standalone ผ่าน IP โดยไม่ใช้ Reverse Proxy

ใช้เฉพาะกรณีที่ต้องการเข้าด้วย IP/port โดยตรง ไม่มี HTTPS จาก Web Manager เอง

ติดตั้งโดยตั้ง bind เป็นทุก interface อย่างตั้งใจ:

```bash
cd /opt/sntalkbot-web-manager
sudo env SNWEB_BIND=0.0.0.0 SNWEB_PORT=28765 ./install.sh
```

จากนั้นเปิด:

```text
http://SERVER_IP:28765/
```

ตรวจค่าจริง:

```bash
grep -E '^SNWEB_(BIND|PORT|COOKIE_SECURE)' /etc/default/sntalkbot-web-manager
sudo ss -ltnp | grep ':28765 '
```

ถ้ามี Firewall ให้เปิด TCP 28765 เฉพาะ IP ผู้ดูแลเท่าที่ทำได้ ตัวอย่าง UFW แบบจำกัดต้นทาง:

```bash
sudo ufw allow from YOUR_ADMIN_IP to any port 28765 proto tcp
```

ไม่ควรเปิดพอร์ต `20000-27999` เพราะเป็น API ภายในของบอต

Standalone HTTP จะใช้ `SNWEB_COOKIE_SECURE=false` ตามค่าเริ่มต้น หากเว็บเปิดสาธารณะบน Internet แนะนำ Reverse Proxy + HTTPS มากกว่า

กลับไป bind เฉพาะ localhost ภายหลัง:

```bash
sudo sed -i 's/^SNWEB_BIND=.*/SNWEB_BIND="127.0.0.1"/' /etc/default/sntalkbot-web-manager
sudo systemctl restart sntalkbot-web-guardian
sudo systemctl restart sntalkbot-web-manager
```

---

# วิธี B — CloudPanel Reverse Proxy (แนะนำถ้าใช้ CloudPanel)

Guardian ยังคงฟัง `127.0.0.1:28765`, FastAPI อยู่ `127.0.0.1:28766` และ CloudPanel เป็นผู้รับ Domain/HTTPS จากภายนอก

## ผ่านหน้า CloudPanel

1. ชี้ DNS A/AAAA ของโดเมน เช่น `botmgr.example.com` มาที่ IP ของ Server
2. เข้า CloudPanel → **Sites** → **Add Site**
3. เลือก **Create a Reverse Proxy**
4. Domain Name: `botmgr.example.com` — ใส่เฉพาะ hostname เท่านั้น ห้ามใส่ `https://`, path, `/` ท้ายชื่อ หรือ `:28765`
5. Reverse Proxy URL: `http://127.0.0.1:28765` — ช่องนี้จึงค่อยใส่ scheme และ port
6. กำหนด Site User/Password ตาม CloudPanel แล้วกด Create
7. ติดตั้ง/ออก SSL certificate ให้โดเมนตามเมนู SSL/TLS ของ CloudPanel
8. เปิด Vhost Editor ของไซต์ แล้วตรวจ location `/` ให้รองรับ realtime SSE โดยมีค่าหลัก:

```nginx
proxy_pass http://127.0.0.1:28765;
proxy_http_version 1.1;
proxy_set_header Host $host;
proxy_set_header X-Real-IP $remote_addr;
proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
proxy_set_header X-Forwarded-Proto $scheme;
proxy_buffering off;
proxy_cache off;
proxy_read_timeout 3600s;
proxy_send_timeout 3600s;
```

`proxy_buffering off` สำคัญกับ Job progress และสถานะ instance แบบ Server-Sent Events ไม่เช่นนั้นบาง proxy อาจพักข้อมูลไว้ก่อนแล้วค่อยส่งเป็นก้อน

CloudPanel Vhost Editor ตรวจ syntax และ revert เมื่อ config ผิดก่อนทำให้ไซต์ล่ม จึงควรแก้จากหน้า Vhost ของไซต์นั้นโดยตรง

เมื่อ HTTPS ใช้งานได้แล้ว:

```bash
sudo sed -i 's/^SNWEB_COOKIE_SECURE=.*/SNWEB_COOKIE_SECURE="true"/' /etc/default/sntalkbot-web-manager
sudo systemctl restart sntalkbot-web-manager
```

ตรวจ:

```bash
curl -fsS https://botmgr.example.com/healthz
```

## ผ่าน CloudPanel CLI

CloudPanel มีคำสั่งสร้าง Reverse Proxy โดยตรง ตัวอย่าง:

```bash
sudo clpctl site:add:reverse-proxy \
  --domainName=botmgr.example.com \
  --reverseProxyUrl='http://127.0.0.1:28765' \
  --siteUser=botmgr \
  --siteUserPassword='CHANGE_THIS_PASSWORD'
```

จากนั้นจัดการ SSL/TLS และ Vhost SSE ตามขั้นตอนด้านบน

---

> **GitHub repository ของ Web Manager:** การติดตั้งแบบ Git clone, ปุ่ม Self-update และ Release Automation `-SyncWebManager` ต้องมี `https://github.com/nuttawat-arch/sntalkbot-web-manager.git` อยู่จริงก่อน หากติดตั้งจาก ZIP/Download Site อย่างเดียวไม่จำเป็นต้องมี repository นี้

# วิธี C — NGINX ปกติ

สร้าง server block เช่น `/etc/nginx/sites-available/sntalkbot-web-manager`:

```nginx
server {
    listen 80;
    server_name botmgr.example.com;

    location / {
        proxy_pass http://127.0.0.1:28765;
        proxy_http_version 1.1;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_buffering off;
        proxy_cache off;
        proxy_read_timeout 3600s;
        proxy_send_timeout 3600s;
    }
}
```

เปิดไซต์และตรวจ syntax:

```bash
sudo ln -s /etc/nginx/sites-available/sntalkbot-web-manager /etc/nginx/sites-enabled/sntalkbot-web-manager
sudo nginx -t
sudo systemctl reload nginx
```

จากนั้นเพิ่ม HTTPS ด้วยวิธีที่คุณใช้กับ NGINX/Certbot อยู่แล้ว และตั้ง `SNWEB_COOKIE_SECURE=true`

---

# วิธี D — Caddy

Caddy รองรับ reverse proxy โดยตรง และเมื่อใช้ hostname ปกติ Caddy สามารถจัด HTTPS ให้ตาม configuration/environment ที่ถูกต้องได้

`/etc/caddy/Caddyfile`:

```caddy
botmgr.example.com {
    reverse_proxy 127.0.0.1:28765
}
```

ตรวจและ reload:

```bash
sudo caddy validate --config /etc/caddy/Caddyfile
sudo systemctl reload caddy
```

Caddy รองรับ streaming response ของ reverse proxy; Web Manager ยังส่ง `Cache-Control: no-cache` และ `X-Accel-Buffering: no` สำหรับ SSE อยู่แล้ว

เมื่อใช้ HTTPS ให้ตั้ง `SNWEB_COOKIE_SECURE=true`

---

# วิธี E — Apache HTTP Server 2.4

เปิด modules ที่ต้องใช้:

```bash
sudo a2enmod proxy proxy_http headers
```

ตัวอย่าง VirtualHost:

```apache
<VirtualHost *:80>
    ServerName botmgr.example.com
    ProxyRequests Off
    ProxyPreserveHost On
    ProxyPass / http://127.0.0.1:28765/ timeout=3600
    ProxyPassReverse / http://127.0.0.1:28765/
    RequestHeader set X-Forwarded-Proto "http"
</VirtualHost>
```

เปิดไซต์และ reload:

```bash
sudo a2ensite sntalkbot-web-manager.conf
sudo apachectl configtest
sudo systemctl reload apache2
```

ถ้า VirtualHost HTTPS ให้ส่ง `X-Forwarded-Proto "https"` และตั้ง `SNWEB_COOKIE_SECURE=true`

---

# วิธี F — Reverse Proxy / Control Panel อื่น ๆ

ถ้าใช้แผงควบคุมหรือบริการ Reverse Proxy อื่นที่ไม่มีตัวอย่างเฉพาะ ให้ใช้หลักเดียวกันดังนี้:

1. Backend/Upstream URL = `http://127.0.0.1:28765` เมื่อ proxy อยู่บนเครื่องเดียวกับ Web Manager
2. ส่ง Host เดิมและ `X-Forwarded-For` / `X-Forwarded-Proto` ให้ backend
3. ปิด response buffering/cache สำหรับเส้นทาง Web Manager เพื่อให้ Server-Sent Events ส่งสถานะและ Job progress ออกทันที
4. ตั้ง read timeout ยาวอย่างน้อย 1 ชั่วโมงสำหรับหน้า realtime/job stream
5. เปิด HTTPS ที่ proxy แล้วตั้ง `SNWEB_COOKIE_SECURE=true`
6. อย่า proxy หรือ port-forward พอร์ต API ภายในของบอต `20000-27999`

ตัวอย่าง header/behavior ที่ควรมีเมื่อระบบนั้นรองรับ:

```text
Upstream: http://127.0.0.1:28765
Host: preserve original host
X-Forwarded-For: client/proxy chain
X-Forwarded-Proto: https
Response buffering: off
Proxy cache: off
Read timeout: 3600 seconds
```

ถ้า Reverse Proxy รันอยู่ใน container คนละ network กับ host อย่าเดาว่า `127.0.0.1` จะหมายถึง host เพราะมันจะหมายถึง container นั้นเอง ให้กำหนด host-gateway/network route ตามระบบที่ใช้ หรือวาง proxy บน host เดียวกันแบบ native service ซึ่งตรงกับตัวอย่าง CloudPanel/NGINX/Caddy/Apache ด้านบนมากกว่า

# 5. หลังตั้ง Reverse Proxy

ตรวจ local services ก่อน:

```bash
systemctl is-active sntalkbot-web-guardian sntalkbot-web-manager
curl -fsS http://127.0.0.1:28765/guardian-healthz
curl -fsS http://127.0.0.1:28765/healthz
curl -fsS http://127.0.0.1:28766/healthz
```

แล้วตรวจ domain:

```bash
curl -fsS https://botmgr.example.com/healthz
```

สถานะควรตอบ JSON ที่มี `ok` และ version

ตรวจ systemd log:

```bash
sudo journalctl -u sntalkbot-web-guardian -u sntalkbot-web-manager -n 100 --no-pager
```

Realtime ที่ควรทดสอบ:

1. Login
2. เปิด instance ที่กำลังรัน
3. ดูจำนวนคนในห้อง/ทั้งเซิร์ฟเวอร์, Administrator ในห้อง/ทั้งเซิร์ฟเวอร์, รายชื่อคนในห้อง, เพลง/คิว
4. เปิดหน้า Job แล้วสั่ง `doctor` หรือ update
5. Output ควรเพิ่มทีละบรรทัดโดยไม่ต้อง refresh

# 6. พอร์ตที่ควรรู้

- `28765/tcp` — Web Guardian สำหรับ Reverse Proxy; ค่า default bind `127.0.0.1`
- `28766/tcp` — Web Manager FastAPI backend; bind `127.0.0.1` เท่านั้นและไม่ต้องเปิด/Proxy โดยตรง
- `28775/tcp` — ตัวอย่างพอร์ต Guardian สาธารณะทางเลือก หากตั้ง `SNWEB_PORT=28775` เพราะ 28765 ถูก service อื่นใช้
- `20000-27999/tcp` — SNTalkBot read-only realtime APIs; bind `127.0.0.1` และมี token ต่อ instance
- TeamTalk TCP/UDP — ใช้ค่าของ TeamTalk Server เดิม ไม่เกี่ยวกับพอร์ต Web Manager

ห้ามทำ port-forward ช่วง `20000-27999` ออก Internet

# 7. คำสั่งดูแล Web Manager

```bash
sudo systemctl status sntalkbot-web-guardian sntalkbot-web-manager --no-pager
# Routine Web Manager restart: Guardian ยังอยู่ ไม่ต้อง restart
sudo systemctl restart sntalkbot-web-manager
sudo journalctl -u sntalkbot-web-guardian -u sntalkbot-web-manager -f
```

หลังแก้ `SNWEB_COOKIE_SECURE` ให้ restart `sntalkbot-web-manager`; ถ้าแก้ `SNWEB_BIND`/`SNWEB_PORT`/`SNWEB_APP_BIND`/`SNWEB_APP_PORT` ต้อง restart ทั้ง Guardian และ Web Manager เพราะ Guardian อ่านค่าพอร์ต/ปลายทางตอนเริ่ม process

# 8. ถ้าเปิดเว็บไม่ได้

ตรวจตามลำดับ:

```bash
sudo systemctl status sntalkbot-web-manager --no-pager
sudo ss -ltnp | grep ':28765 '
curl -v http://127.0.0.1:28765/healthz
sudo journalctl -u sntalkbot-web-guardian -u sntalkbot-web-manager -n 100 --no-pager
```

ถ้า localhost ใช้ได้แต่ domain ไม่ได้ ปัญหาอยู่ฝั่ง Reverse Proxy/DNS/SSL มากกว่า Web Manager

ถ้า Job ทำงานแต่ output มาทีเดียวตอนจบ ให้ตรวจว่า NGINX/CloudPanel มี `proxy_buffering off` ใน location ที่ proxy ไป Web Manager
