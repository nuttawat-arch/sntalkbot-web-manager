# Development Report — Web Manager 1.1.9 (Queue/Migration Recovery)

- ยืนยันบั๊ก production bare Internal Server Error ยังต้องถือเป็น blocker; 1.1.9 ใช้ dashboard fault isolation + static last-resort Request ID boundary ที่ไม่พึ่ง Jinja/config/database
- รองรับ workflow TTUHelper 1.5.3 ที่ตรวจและซ่อม config ของ instance ที่มี TTMediaBot migration marker โดยอัตโนมัติ
- ไม่เปลี่ยน role migration: production รอบก่อนผู้ใช้เลือก Player จริง จึงไม่มี Full→Player bug
- คง accessible Users disclosure, in-page Job dialog, stopped-only Delete, Guardian-safe self-update และ TeamTalk credential proof

---

# Development Report — Web Manager 1.1.8 (UX / 500 Resilience)

## Production evidence / issue
- หลัง migration 7 TTMediaBot สำเร็จ ผู้ใช้รายงานว่า `botmgr` เคยตอบ bare `Internal Server Error` ขณะที่ SNTalkBot playback ยังทำงานปกติ; log ที่ได้รับไม่มี traceback จึงไม่อ้างสาเหตุเฉพาะเจาะจง
- Harden จุดเสี่ยงที่พบจาก audit: Dashboard เดิมพึ่งโครงสร้าง config/realtime ของทุก instance มากเกินไป ทำให้ payload ผิดรูป/กึ่งอัปเดตมีโอกาสลากทั้งหน้า 500

## Changes
- per-instance fault isolation + defensive realtime normalization; instance ผิดรูปเตือนเฉพาะการ์ด
- generic 500 page ภาษาไทยพร้อม Request ID และ server-side traceback logging
- Users list-first disclosure; create form ไม่แสดงจนผู้ใช้กด
- in-page accessible Job dialog สำหรับงานยาว: focus, realtime SSE, copy, close-and-continue, same-page refresh หลังจบ
- user help ลด internal implementation; footer copyright/GitHub

## Validation
- TestClient จำลอง malformed migrated config แล้ว `/` ต้องยัง 200 และแสดง warning เฉพาะ instance
- dialog Job initiation ต้องตอบ 202 JSON; legacy/no-JS fallback 303 Job page ยังคงอยู่
- action matrix, tenant isolation, credential proof, stopped-only delete, Guardian POST/SSE, updater rollback, Bash/LF ผ่าน

# Development Report — Web Manager 1.1.7 (Credential Proof / Stopped-only Delete)

## 2026-08-25
- เปลี่ยน owner verification จาก “มี TeamTalk username นี้อยู่ในรายชื่อ Administrator ที่ออนไลน์” เป็นการพิสูจน์ credentials จริง: tenant กรอก TeamTalk Administrator username/password เอง
- เพิ่ม `root_run_stdin()` และ privileged action `verify-teamtalk-admin`; password ไม่อยู่ใน command line และ root bridge ส่งต่อ stdin เข้า ephemeral SNTalkBot verifier container
- verification ทำก่อน `create_instance()` ดังนั้น password ผิด/non-admin/network fail จะไม่ทิ้ง bot directory/container ครึ่งสำเร็จ
- verified TeamTalk username ถูกบันทึกเป็น owner/authorized user; verification password ไม่ถูก persist
- ค่า `users.teamtalk_admin_username` เดิมคงไว้เป็น optional prefill เพื่อรักษา backward compatibility ไม่ใช้เป็น gate
- safe-delete ยืนยันอีกชั้น: UI ซ่อน Delete ขณะ running และ backend ตอบ HTTP 409 หาก bypass UI
- validator เพิ่ม credential stdin/non-persistence/action regression และ action matrix เดิมยังผ่านครบ

---

# Development Report — Web Manager 1.1.6 (Account Identity / Safe Delete)

## 2026-08-25
- แยก Web username ออกจาก TeamTalk Administrator identity อย่างเป็นทางการ: Super Admin เป็นผู้ผูก `teamtalk_admin_username` บนบัญชีลูกค้า และลูกค้าแก้ mapping นี้เองไม่ได้
- ลูกค้าสร้าง instance ได้เมื่อ TeamTalk username ที่ผูกไว้ออนไลน์และเป็น Administrator บน server เป้าหมายจริง; ห้ามใช้ bot username เป็นหลักฐาน
- Web Super Admin ข้าม owner-verification และสร้าง instance บน TeamTalk server ใดก็ได้ โดยยังต้องมี bot connection credentials ที่ถูกต้องเพื่อให้บอตออนไลน์
- ปุ่ม/กลุ่ม Delete แสดงเฉพาะ instance ที่หยุดแล้ว และ backend ตอบ 409 หากมีการยิง delete ไปยัง instance ที่กำลังรัน แม้ข้าม UI
- รักษา exact-name confirmation + TTUHelper backup ก่อนลบ
- เพิ่ม schema migration แบบ additive สำหรับ `users.teamtalk_admin_username`; ไม่ลบบัญชี/ownership เดิม
- ตรวจคู่มือ/validator ให้สะท้อน mapping และ safe-delete rules ใหม่

---

# DEVELOPMENT REPORT — SNTalkBot Web Manager 1.1.6

วันที่: 2026-08-25

## ปัญหาจากรอบก่อน
- ขณะ Web Manager restart/self-update Reverse Proxy สามารถเห็น backend หายชั่วคราวและตอบ 502 ได้ เพราะ 1.1.4 เป็น process เดียวที่ถือพอร์ต 28765
- instance ที่หยุดแล้วอาจยังมี `runtime_status.json` snapshot ล่าสุด ทำให้หน้าเว็บดูเหมือนยังมีข้อมูลสด
- Dashboard ต้องมีทางลบ instance ที่ค้นหาได้ง่ายแต่ห้ามลบทันที
- คู่มือบางจุดใช้ช่วง realtime API/ความหมาย “ผู้ใช้ออนไลน์” ไม่ตรง runtime จริง

## สิ่งที่แก้/เพิ่ม
- เพิ่ม stable Guardian 1.0.0 ถือ public loopback 28765; FastAPI backend ใช้ 28766
- Guardian ให้ maintenance 503 + Retry-After ระหว่าง backend down และกลับไป proxy อัตโนมัติเมื่อ backendมา
- routine update ติดตั้ง Guardian เฉพาะครั้งแรกและไม่เขียนทับ/restart service กลางในรอบอัปเดตเว็บ
- stopped instance ไม่อ่าน stale runtime fallback และ SSE ซ่อน live/player/manager state ทันที
- เพิ่ม safe-delete group ที่ Dashboard + detail พร้อม exact-name confirmation; TTUHelper ยัง backup ก่อนลบ
- รองรับ SNTalkBot 5.1.2 room-scoped realtime และแสดงรายละเอียดผู้ใช้/Administrator/activity แยกห้องกับเซิร์ฟเวอร์
- audit คู่มือกับ route/action จริงและเพิ่ม validator ป้องกัน documentation drift

## ลบอะไร
- ไม่ลบ action หรือข้อมูลผู้ใช้; เลิกความหมายเดิมที่ใช้ข้อมูลทั้งเซิร์ฟเวอร์เป็น “ผู้ใช้ออนไลน์” ของห้อง และเลิกแสดง stale live snapshot เมื่อ container หยุด

## ผลตรวจ ณ source
- `python3 tools/validate_web_manager.py` ผ่าน: auth/ownership/create/run/stop/restart/delete/log/config/limits/cookies/system/migration action matrix ครบ
- stopped-state regression ยืนยันว่า container หยุดแล้ว runtime fallback ถูกซ่อนทั้ง server render และ SSE
- Guardian runtime regression ผ่านทั้ง maintenance เมื่อ backend down, proxy POST/form, SSE event streaming แบบไม่ buffer และกลับมา proxy อัตโนมัติเมื่อ backendขึ้น
- updater regression ผ่าน dirty-source staging/backup/rollback และ rollback คืน running process
- compatibility audit ของ production 1.1.4 ผ่าน: root bridge 1.1.4 เรียก checkout ใหม่ด้วย `SNWEB_DEFER_RESTART=1`; installer 1.1.6 จึง schedule first Guardian transition หลัง Job ตอบกลับ และ delayed restart เดิมของ 1.1.4 กลายเป็น backend restart เพิ่มโดยไม่หยุด Guardian
- Bash/Python/LF และคู่มือ/พอร์ต/command-count invariants ผ่าน

## สถานะ/สิ่งที่ยังเหลือ
- หลัง PublishFirst ต้องทดสอบ production self-update 1.1.4 → 1.1.6 ผ่านหน้าเว็บหนึ่งครั้ง, ทดสอบ stopped instance, safe delete ด้วย instance ทดสอบ และรัน strict server verifier
- การย้ายจากระบบเดิมที่ Web Manager ถือ 28765 ไป Guardian เป็น migration ครั้งแรก จึงอาจมีช่องว่างระดับสั้นมากครั้งเดียวตอนสลับผู้ถือ socket; หลัง Guardian ทำงานแล้ว routine self-update จะไม่ทำให้ public socket หาย

---

# DEVELOPMENT REPORT — SNTalkBot Web Manager 1.1.4

## ปัญหาที่พบจาก production 1.1.3
- bootstrap ดาวน์โหลด/ตรวจ SHA และ backup/replace source สำเร็จ; `/opt/sntalkbot-web-manager/VERSION` เป็น 1.1.3
- แต่ systemd process ยังเป็น process เดิมจาก 1.1.1 และ `/healthz` ยังรายงาน 1.1.1 เพราะ `systemctl enable --now` ไม่ restart service ที่ active อยู่

## สิ่งที่แก้
- manual/ZIP/bootstrap installer restart service จริงและ gate ความสำเร็จด้วย health version เทียบกับ `VERSION`
- self-update จากหน้าเว็บ defer restart เพื่อรักษา job response แล้วใช้ transient systemd restart ตามเดิม
- ถ้า version หลัง restart ไม่ตรง installer จะ fail; bootstrap staged updater สามารถ rollback source รุ่นเดิมได้

## ผลตรวจ
- Python/Bash/LF validator ผ่าน
- action matrix/security tests เดิมยังอยู่ครบ
- validator เพิ่ม invariant ห้ามกลับไปใช้ `enable --now` เป็นตัวแทนของ restart และบังคับมี version-aware health verification

## สถานะ
- พร้อม publish 1.1.4; production ต้องอัปเดตแล้วตรวจ `cat VERSION` และ `/healthz` ให้เป็น 1.1.4 ตรงกัน

---

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
