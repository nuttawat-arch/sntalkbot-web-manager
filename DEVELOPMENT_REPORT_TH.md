# DEVELOPMENT REPORT — SNTalkBot Web Manager 1.1.3

วันที่: 2026-08-25

## ปัญหาจากรอบก่อน
- production 1.1.1 ติดตั้งได้ แต่รอบ publish 1.1.2 หยุดก่อนหน้า Download Site จึงยังแจก 1.1.1
- updater ที่อาศัย `git pull --ff-only` สามารถล้มเมื่อ source บน server มี local changes/CRLF หรือไฟล์ untracked เช่นกรณีที่พบจริงกับ `/opt/ttuhelper`
- bootstrap ZIP เดิมปฏิเสธทันทีเมื่อปลายทางเป็น Git clone ทำให้มีเส้นทางอัปเดตที่ยังกลับไปติดปัญหาเดิมได้

## การแก้ไข/ฟีเจอร์
- เปลี่ยน Web Manager Self-update, Update TTUHelper และ Core Stack source refresh เป็น fresh clone ลง staging ก่อนแตะ live source
- สำรอง live source ทั้งโฟลเดอร์ก่อนสลับ, rollback อัตโนมัติเมื่อ installer ล้ม และเก็บ backup ล่าสุด 3 ชุด
- `install_remote.sh` ใช้ staged/backup/rollback และไม่ใช้ live `git pull` อีก
- persistent state ยังคงอยู่นอก source: `/etc/sntalkbot-web-manager`, `/var/lib/sntalkbot-web-manager`, `/opt/sntalkbot-bots` จึงไม่ถูก source replacement ลบ

## การทดสอบรอบนี้
- Python compile, Bash syntax, LF-only, TestClient/action matrix และ updater regression (dirty source backup + rollback)
- ตรวจว่า source updater ไม่มี `git pull --ff-only` บน live tree

## ลบอะไรออก
- ไม่ลบ action ผู้ใช้; ลบเฉพาะกลไกอัปเดต live-tree แบบ `git pull` ที่เป็นสาเหตุ failure

## สถานะ
- พร้อม publish เป็น 1.1.3; หลัง publish ต้องอัปเดต production แล้วรัน strict server verification

---

# DEVELOPMENT REPORT — SNTalkBot Web Manager 1.1.2

วันที่: 2026-08-25

## ปัญหาจากรอบก่อน
- 1.1.1 ติดตั้งและ health check บน production สำเร็จที่ `127.0.0.1:28765` แต่ action ที่แตะ Docker ยังอาศัยชื่อ container ก่อนยืนยัน ownership label
- หากชื่อ instance ชนกับ container ของบริการอื่น อาจเกิดการอ่าน inspect/log ของ container ที่ไม่ใช่ SNTalkBot และ TTUHelper รุ่นก่อนมี destructive name-collision risk
- validator เดิมทดสอบ auth/tenant/config แต่ยังไม่ได้ regression-test route/action matrix ทุกกลุ่ม

## การแก้ไข/ฟีเจอร์
- root bridge ตรวจ label `com.ttutilities.helper`, `com.ttutilities.bot`, `com.ttutilities.data` ก่อน Docker inspect/logs
- เพิ่ม preflight `container-name-check` ก่อนสร้าง instance เพื่อปฏิเสธชื่อที่ชนกับ Docker container ใด ๆ ก่อนสร้างไฟล์/ownership
- ทำงานร่วมกับ TTUHelper 1.5.2 ซึ่งป้องกัน run/stop/restart/delete/logs จาก unmanaged same-name container ที่ต้นทางอีกชั้น
- เพิ่ม validator ตรวจ route/action matrix และ collision guard

## การทดสอบรอบนี้
- Python syntax, TestClient auth/tenant isolation, CSRF, config lock, job ownership, root bridge allowlist, Linux LF/Bash ผ่าน
- action mapping ครบ create/run/stop/restart/delete/logs/config/limits/cookies/cookies-check/system actions/migration

## ลบอะไรออก
- ไม่มี action หรือฟีเจอร์ผู้ใช้เดิมถูกลบ

## สถานะ
- ต้อง publish 1.1.2 + TTUHelper 1.5.2 แล้วรัน production smoke/strict verification อีกครั้ง

---

# DEVELOPMENT REPORT — SNTalkBot Web Manager 1.1.1

วันที่: 2026-08-24

## ปัญหาจากรอบก่อน
- 1.1.0 สมมุติว่ามี SNTalkBot source ที่ `/opt/sntalkbot` แต่ production จริงใช้ Docker image และเก็บ instance ใน `/opt/sntalkbot-bots` เท่านั้น
- Linux runtime ยังไม่เคยผ่าน health/functional verification บน production เพราะ Web Manager ยังไม่ได้ติดตั้งจริง

## การแก้ไข/ฟีเจอร์
- ยกเลิก dependency ต่อ host SNTalkBot source checkout
- อ่าน `/app/config_default.ini` และ `/app/VERSION` จาก Docker image ผ่าน root bridge allowlist แบบ fixed-path
- Core Stack ติดตั้ง/อัปเดต TTUHelper ซึ่งเป็นผู้ pull image; ไม่มีการ clone `/opt/sntalkbot`
- migration ใช้ config template ชั่วคราวที่อ่านจาก image
- เพิ่ม LF-only และ `bash -n` validation

## การทดสอบรอบนี้
- Python syntax, FastAPI/TestClient, auth/tenant isolation, CSRF, root-bridge allowlist, installer Bash syntax และ LF-only ผ่านใน dev environment
- production health `127.0.0.1:28765/healthz` ยังต้องพิสูจน์หลังติดตั้ง

## ลบอะไรออก
- ลบเฉพาะ action/UI ที่อัปเดต SNTalkBot host source (`update-bot-source`) ซึ่งไม่ใช่ deployment architecture จริง; การอัปเดต SNTalkBot ผ่าน Docker image/TTUHelper ยังอยู่ครบ

## สถานะ
- Source พร้อม publish; รอติดตั้งที่ `/opt/sntalkbot-web-manager` และ strict server verification
