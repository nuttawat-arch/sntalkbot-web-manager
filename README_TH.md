# SNTalkBot Web Manager 1.1.2

เว็บแดชบอร์ด self-hosted สำหรับจัดการ SNTalkBot และ TTUHelper หลาย instance โดยไม่ต้องพิมพ์คำสั่ง Linux ทุกครั้ง เหมาะกับเครื่อง Ubuntu/Debian ที่รัน SNTalkBot/TTUHelper และออกแบบให้ใช้ได้ทั้งเจ้าของเครื่องคนเดียวหรือหลายบัญชีลูกค้า

Web Manager เป็นโปรเจกต์สำหรับผู้ใช้โฮสต์เอง ไม่เกี่ยวกับ Download Site หรือ Report API ของผู้พัฒนา

## 3 โปรเจกต์ที่ผู้ใช้โฮสต์เอง

1. **SNTalkBot 5.1.0+** — ตัวบอตหลักและ Realtime Status API ภายใน
2. **TTUHelper 1.5.0+** — จัดการหลาย instance, Docker, update, delete, API port/token และ Linux data layout
3. **SNTalkBot Web Manager 1.1.2+** — หน้าเว็บจัดการสองโปรเจกต์ด้านบน

## ความสามารถหลัก

- First-run Setup: ผู้ใช้คนแรกสร้าง **Super Admin** จากหน้าเว็บครั้งแรก หลังจากนั้นหน้า setup ปิด
- Super Admin สร้าง/ปิดบัญชีหรือรีเซ็ตรหัสผ่านผู้ใช้อื่นได้
- ผู้ใช้ทั่วไปเห็นและจัดการเฉพาะ instance/Job ที่ตนเป็นเจ้าของ
- ตอนสร้างบอตใหม่ ตรวจ TeamTalk username ของเจ้าของว่าเป็น Administrator ที่ออนไลน์อยู่จริง และไม่นับบัญชีบอตเองเป็นหลักฐาน
- สร้าง Full / Player / Server Manager ด้วยฟอร์ม ไม่ต้องกรอกเลขประเภท
- ชื่อ instance ใหม่ใช้เฉพาะ `a-z`, `0-9`, `.`, `-`, `_`, ห้าม space/slash/backslash และยาวไม่เกิน 63 ตัว
- Start / Stop / Restart / Delete รายตัว และ Start All / Stop All สำหรับ Super Admin
- Delete ต้องพิมพ์ชื่อ instance ยืนยัน และ TTUHelper สำรองข้อมูลก่อนลบจริง
- ดู Logs พร้อมปุ่มคัดลอกและเลือกจำนวนบรรทัด
- แก้ `config.ini` ทุก section/key; Boolean เป็น checkbox; secret ไม่อ่านค่าปัจจุบันกลับมาแสดง
- ตั้ง CPU/RAM limits
- อัปโหลด/ตรวจ YouTube cookies สำหรับ Player/Full
- Migration จาก TTMediaBot Docker Helper `config.json` v1 ผ่าน privileged bridge
- `doctor`, pull image, update SNTalkBot ที่กำลังรัน และอัปเดต source/helper ผ่านหน้าเว็บ
- งานยาวแสดง progress/error แบบ realtime ผ่าน SSE
- Dashboard อ่าน SNTalkBot Realtime API ภายในก่อน และ fallback ไป `runtime_status.json` เมื่อ API ใช้ไม่ได้

## สถานะสดที่ Dashboard รองรับ

เมื่อใช้ SNTalkBot 5.1.0 + TTUHelper 1.5.0 เว็บสามารถแสดงตาม role ได้ เช่น:

- connected/server/channel/nickname/status/uptime
- จำนวนผู้ใช้ออนไลน์
- จำนวนผู้พูด/Media/Video/Desktop
- Administrator ที่ออนไลน์ โดยตัด user ID ของบอตเองออก
- Player: เพลงปัจจุบัน, URL, volume, speed, Queue Mode, จำนวนคิว, M1/M2/M3, Autoplay, playlist/Related Radio และรายการคิวพร้อมผู้เพิ่ม
- Manager: filter, ci, ic, command lock, welcome และ events ล่าสุด

API ของแต่ละบอตใช้พอร์ตสุ่ม `20000-27999` แต่ bind เฉพาะ `127.0.0.1` และมี Bearer token ต่อ instance **ห้ามเปิดหรือ Reverse Proxy ช่วงพอร์ตนี้ออก Internet** Browser ติดต่อ Web Manager เท่านั้น

## ติดตั้งแบบคำสั่งเดียวจาก Download Site

หลังรุ่นนี้ถูก publish บนหน้า Download:

```bash
curl -fsSL https://ttdl.nuttawat.ddnsfree.com/install_web_manager.sh | sudo bash
```

bootstrap จะตรวจเครื่องมือ, ดาวน์โหลด Web Manager `latest`, ตรวจ SHA-256 และเรียก installer ต่อให้อัตโนมัติ ค่า default ยัง bind เฉพาะ `127.0.0.1:28765`


## Production layout แบบ Docker-only

Web Manager 1.1.2 ไม่ต้องมี SNTalkBot source checkout ที่ `/opt/sntalkbot` บน production host อีกแล้ว ตัวบอตจริงมาจาก Docker image ที่ TTUHelper กำหนด และข้อมูลแต่ละ instance อยู่ที่ `/opt/sntalkbot-bots/` ตาม production architecture ปัจจุบัน การสร้าง instance และ migration จะอ่าน `config_default.ini` จาก Docker image โดยตรง ส่วน `/opt/ttuhelper` และ `/opt/sntalkbot-web-manager` ยังคงเป็น source/tool บน host ตามหน้าที่ของตนเอง

## การติดตั้งจาก ZIP

```bash
sudo mkdir -p /opt/sntalkbot-web-manager
sudo unzip -o SNTalkBot-Web-Manager-1.1.2.zip -d /opt/sntalkbot-web-manager
cd /opt/sntalkbot-web-manager
sudo chmod +x install.sh install_remote.sh
sudo ./install.sh
```

ค่า default Web Manager ฟังเฉพาะ:

```text
127.0.0.1:28765
```

ตรวจหลังติดตั้ง:

```bash
sudo systemctl status sntalkbot-web-manager --no-pager
curl -fsS http://127.0.0.1:28765/healthz
```

จากนั้นเปิดผ่าน Reverse Proxy/HTTPS แล้วสร้าง Super Admin คนแรกจากหน้าเว็บ

## การติดตั้งจาก GitHub

เมื่อ repository ถูก publish แล้ว:

```bash
cd /opt
sudo git clone https://github.com/nuttawat-arch/sntalkbot-web-manager.git
cd /opt/sntalkbot-web-manager
sudo chmod +x install.sh install_remote.sh
sudo ./install.sh
```

ถ้า clone อยู่แล้ว:

```bash
cd /opt/sntalkbot-web-manager
sudo git pull --ff-only
sudo ./install.sh
```

หรือใช้ `install_remote.sh` ตามคู่มือฉบับเต็ม

## Standalone ผ่าน IP

ค่า default ไม่เปิด Web Manager ออกทุก interface ถ้าต้องการใช้ `http://SERVER_IP:28765/` โดยตรง ให้เลือกอย่างตั้งใจ:

```bash
cd /opt/sntalkbot-web-manager
sudo env SNWEB_BIND=0.0.0.0 SNWEB_PORT=28765 ./install.sh
```

ควรจำกัด Firewall ให้เข้าถึงได้เฉพาะ IP ผู้ดูแล และ Reverse Proxy + HTTPS เหมาะกว่าถ้าใช้งานผ่าน Internet

## CloudPanel / Reverse Proxy

สำหรับ CloudPanel ให้สร้าง **Reverse Proxy Site** และใช้ upstream:

```text
http://127.0.0.1:28765
```

หลัง HTTPS ใช้งานได้ให้ตั้ง `SNWEB_COOKIE_SECURE=true` และ restart service

คู่มือ `REVERSE_PROXY_GUIDE_TH.md` มีขั้นตอนแบบละเอียดสำหรับ:

- Standalone ผ่าน IP:port
- CloudPanel ผ่านหน้าเว็บและ CLI
- NGINX
- Caddy
- Apache HTTP Server
- Reverse Proxy / Control Panel อื่น ๆ
- SSE realtime, HTTPS, Secure Cookie และ Troubleshooting

## สิทธิ์ Linux / root

Web application รันด้วย system user `sntalkweb` ไม่ใช่ root ตลอดเวลา งานที่ต้องใช้ root เช่น Docker, install/update/delete/migrate จะผ่าน root-owned privileged bridge ที่มี allowlist ตายตัว

- ไม่มี arbitrary web shell
- ไม่มี `shell=True`
- action อันตรายตรวจ ownership/role ฝั่ง backend
- Job log มี owner
- secret config ไม่ถูก render กลับ
- session เป็น long-lived แต่ถ้าบัญชีถูกปิด session เดิมจะใช้ต่อไม่ได้

## ถ้ายังไม่มี SNTalkBot/TTUHelper

Super Admin ใช้หน้า **ระบบ/อัปเดต → ติดตั้ง/ซ่อม Core Stack** ได้ ระบบจะ preflight ก่อนว่ามี `git`, `curl`, `python3`, CA certificates, Docker และ dependency ที่จำเป็นหรือไม่ แล้วติดตั้งเฉพาะสิ่งที่ขาด ก่อน clone/update SNTalkBot + TTUHelper, รัน installer และ `ttuhelper doctor`

Progress/Error จะแสดงขึ้นหน้า Job แบบ realtime ไม่ต้องรอจนคำสั่งทั้งหมดจบ

## คำสั่งดูแล Web Manager

```bash
sudo systemctl status sntalkbot-web-manager --no-pager
sudo systemctl restart sntalkbot-web-manager
sudo journalctl -u sntalkbot-web-manager -f
```

อ่านรายละเอียดทั้งหมดใน `REVERSE_PROXY_GUIDE_TH.md` และ `TTUHELPER_WEB_MAP_TH.md`
## ชื่อโดเมนสำหรับ CloudPanel

ถ้าสร้าง Reverse Proxy Site ให้กรอก Domain Name เป็น hostname อย่างเดียว เช่น `botmgr.example.com` และกรอก Reverse Proxy URL เป็น `http://127.0.0.1:28765` ห้ามเอา `https://` หรือ `:28765` ไปใส่ในช่อง Domain Name ดูขั้นตอนเต็มใน `REVERSE_PROXY_GUIDE_TH.md`

GitHub repo `nuttawat-arch/sntalkbot-web-manager` จำเป็นเฉพาะ Git clone / Self-update / `-SyncWebManager`; การติดตั้งจาก ZIP ใช้งานได้โดยไม่ต้องมี repo นี้

