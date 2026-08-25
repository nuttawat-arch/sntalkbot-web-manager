# SNTalkBot Web Manager 1.1.9 — Dashboard Recovery / Migration Repair Integration

- คง Users list-first และ Job dialog ในหน้าเดิมจาก 1.1.8
- เพิ่ม last-resort/fault-isolation รอบ Dashboard ต่อเนื่องเพื่อไม่ให้ config/realtime ของ instance ที่ migrate ตัวเดียวลากทั้งหน้าเว็บลง
- หน้า System แสดง TTUHelper รุ่นใหม่และ workflow อัปเดต helper เพื่อซ่อม config ที่ migrate มาแล้วอัตโนมัติ
- คู่มือผู้ใช้ยังเน้นงานที่ผู้ใช้ต้องทำจริง; Reverse Proxy ใช้ upstream 127.0.0.1:28765 โดยไม่อธิบาย implementation ภายในเกินจำเป็น

---

# SNTalkBot Web Manager 1.1.8 — Web UX / Dashboard Resilience

- หน้า **บัญชีผู้ใช้** แสดงรายชื่อก่อน และซ่อนฟอร์มสร้างบัญชีจนกด “สร้างบัญชีผู้ใช้”; เปิด/ปิดแบบ disclosure พร้อมย้ายโฟกัสให้โปรแกรมอ่านหน้าจอ
- งาน Update, Migration, Start/Stop/Restart/Delete และงานตรวจที่ใช้เวลานานเปิดเป็น **dialog ภายในหน้าเดิม** พร้อมสถานะสด, คัดลอกผลลัพธ์, ปิดได้โดยงานยังทำต่อ และเมื่อจบแล้วปิดเพื่อรีเฟรช/กลับหน้าเดิม
- เพิ่ม fault isolation ของ Dashboard: config/container/realtime/owner ของ instance ใดผิดรูปหรืออ่านไม่ได้จะเตือนเฉพาะการ์ดนั้น ไม่ทำให้ Dashboard ทั้งหน้ากลายเป็น HTTP 500
- เพิ่มหน้า error ภาษาไทยพร้อม Request ID สำหรับ exception ที่ไม่คาดคิด เพื่อรายงานได้โดยไม่เปิดเผย password/token/cookies
- ปรับคู่มือในเว็บให้เป็นงานที่ผู้ใช้ต้องทำจริง ลดรายละเอียดพอร์ต/backend/bridge ภายใน เหลือ Reverse Proxy target `http://127.0.0.1:28765` ที่จำเป็น
- เพิ่ม footer ลิขสิทธิ์ `© 2026 Nuttawat`, GitHub ผู้พัฒนา และ source repository ของ Web Manager
- คง Guardian 1.0.0, credential proof, stopped-only Delete, tenant isolation และ action safety เดิม

# SNTalkBot Web Manager 1.1.7 — Self-service TeamTalk Admin Proof

- ลูกค้าไม่ต้องใช้ Web username เดียวกับ TeamTalk username และไม่ต้องรอ Super Admin ผูก identity เป็น authorization gate
- หน้าสร้างบอตรับ TeamTalk Administrator username/password แยกจาก bot login; ระบบส่ง credentials ผ่าน stdin ไป privileged bridge และ one-shot verifier ใน SNTalkBot Docker image
- verifier login ไปยัง TeamTalk server เป้าหมายจริงและต้องได้ `UserType=Administrator` ก่อนสร้าง persistent instance; password ไม่เข้า argv, DB, config หรือ Job log
- `teamtalk_admin_username` เดิมในบัญชีผู้ใช้ยังเก็บไว้แบบ additive เป็นค่าเริ่มต้นช่วยกรอก เพื่อไม่ทำลาย schema/ข้อมูลเดิม แต่ลูกค้าสามารถยืนยัน username อื่นด้วย password จริงได้
- Web Super Admin ข้าม owner credential verification และสร้างบน server ใดก็ได้ตามเดิม
- กลุ่ม Delete แสดงเฉพาะ stopped instance; backend ตอบ 409 ถ้าพยายามลบขณะ container ยัง running พร้อมคง exact-name confirmation และ TTUHelper backup
- คง Guardian 1.0.0 / 28765 -> backend 28766, realtime room/server detail และ stopped snapshot suppression

# SNTalkBot Web Manager 1.1.6

- เพิ่ม **SNTalkBot Web Guardian 1.0.0** เป็น service กลางที่คง socket `127.0.0.1:28765` ไว้เสมอ; FastAPI Web Manager ย้ายไป backend `127.0.0.1:28766` จึง restart/self-update ได้โดย Reverse Proxy ไม่เจอ raw 502 ในการอัปเดตปกติหลัง Guardian ติดตั้งแล้ว
- เมื่อ backend กำลัง restart Guardian แสดงหน้า maintenance ที่อ่านด้วยโปรแกรมอ่านหน้าจอได้และลองเชื่อมต่อใหม่อัตโนมัติ; API ได้ HTTP 503 + `Retry-After` แทน raw proxy failure
- Guardian เป็น infrastructure คงที่: routine Web Manager update ไม่เขียนทับและไม่ restart Guardian; การเปลี่ยน Guardian ในอนาคตต้องเป็น migration โดยตั้งใจ
- แก้ Dashboard/หน้า instance ไม่ให้แสดง `runtime_status.json` เก่าหลังบอตหยุด; บอตที่หยุดจะแสดงชัดว่าไม่มีข้อมูลสด
- เพิ่มกลุ่ม **ลบ instance นี้** บน Dashboard และหน้ารายละเอียด โดยต้องพิมพ์ชื่อ instance ตรงทุกตัวอักษรก่อน TTUHelper สำรองข้อมูลและลบจริง
- รองรับ realtime schema ของ SNTalkBot 5.1.2: แยกจำนวนคนในห้องปัจจุบัน/ทั้งเซิร์ฟเวอร์, Administrator ในห้อง/ทั้งเซิร์ฟเวอร์, activity ห้อง/เซิร์ฟเวอร์ และรายชื่อผู้ใช้ในห้อง
- หน้า Job ของ self-update รอ `/healthz` ของ process generation ใหม่และประกาศเมื่อ Web Manager กลับมาออนไลน์แล้ว
- ตรวจและแก้คู่มือให้ตรง action จริง: TTUHelper มี 22 คำสั่ง; SNTalkBot มี 124 canonical commands และ `. <คิว>` / `, <คิว>` เป็น syntax เพิ่มของ 2 คำสั่งเดิม ไม่เพิ่มจำนวน canonical commands

# SNTalkBot Web Manager 1.1.4

- แก้ upgrade จาก ZIP/bootstrap ที่ source เปลี่ยนเป็นรุ่นใหม่แล้วแต่ process เก่ายังทำงานอยู่ เพราะ `systemctl enable --now` ไม่ restart service ที่ active อยู่
- การติดตั้ง/อัปเดตจาก SSH/ZIP/bootstrap จะ `systemctl restart` จริง แล้วตรวจ `/healthz` จน version ตรงกับไฟล์ `VERSION`; ถ้าไม่ตรงให้ installer ล้มเพื่อเปิดทางให้ rollback คืน source รุ่นเดิม
- Self-update จากหน้า Web Manager ใช้ `SNWEB_DEFER_RESTART=1` เพื่อไม่ฆ่า request ตัวเอง และยัง schedule restart ผ่าน transient systemd unit หลัง privileged updater จบ
- คง staged source backup/rollback, persistent config/database และ Docker ownership safety จาก 1.1.3 ครบ

# SNTalkBot Web Manager 1.1.3

## การเปลี่ยนแปลง

- เปลี่ยน Self-update และการอัปเดต TTUHelper จาก `git pull --ff-only` บน live tree เป็น fresh staged checkout ก่อนแตะของเดิม
- ก่อนสลับรุ่นจะสำรอง source เดิมทั้งโฟลเดอร์ จึงเก็บ local edits, `.git`, `.venv` และไฟล์แปลกที่หลงอยู่ไว้เป็น rollback backup โดยไม่ให้สิ่งเหล่านี้ขวางการอัปเดต
- ถ้า clone/staging ล้ม จะไม่แตะ live source; ถ้า installer รุ่นใหม่ล้ม จะคืน source เดิมและ best-effort ติดตั้งรุ่นเดิมกลับ
- `install_remote.sh` ใช้พฤติกรรม staged/backup/rollback แบบเดียวกัน และเก็บ source backup ล่าสุดไว้ 3 ชุดโดยค่าเริ่มต้น
- คง action matrix, ownership, Docker collision guard, persistent DB/config และ reverse proxy เดิมทั้งหมด

---

# SNTalkBot Web Manager 1.1.2

## การเปลี่ยนแปลง

- ป้องกันชื่อ instance ชนกับ Docker container ของบริการอื่นก่อนสร้างบอต
- Docker inspect/logs ผ่าน privileged bridge จะอนุญาตเฉพาะ container ที่มี TTUHelper ownership labels ตรงกับ instance
- ทำงานร่วมกับ TTUHelper 1.5.2 เพื่อป้องกัน destructive container-name collision แบบ defense in depth
- คง action เดิมทั้งหมดและเพิ่ม regression coverage ของ action matrix

---

# SNTalkBot Web Manager 1.1.1

## การเปลี่ยนแปลง

- แก้ architecture mismatch จาก 1.1.0 ที่ยังคาดว่ามี SNTalkBot source ที่ `/opt/sntalkbot` ทั้งที่ production จริง deploy SNTalkBot ผ่าน Docker image และเก็บ instance ที่ `/opt/sntalkbot-bots/`
- การสร้าง instance อ่าน `config_default.ini` จาก Docker image โดยตรงผ่าน privileged bridge แบบ allowlist
- Migration TTMediaBot ใช้ template ชั่วคราวที่อ่านจาก Docker image จึงไม่ต้อง clone source บอตลง host
- Core Stack ติดตั้ง/ซ่อมเฉพาะ TTUHelper แล้วให้ TTUHelper pull SNTalkBot image; ตัดปุ่ม/งาน `update SNTalkBot source` ที่ไม่ตรง production architecture
- หน้า System แสดงเวอร์ชัน SNTalkBot จาก image และ digest local/remote แทน host source version
- รักษา reverse proxy `127.0.0.1:28765`, multi-user ownership, FastAPI/TestClient, root-bridge allowlist และ persistent settings เดิม

## ปัญหาที่ตรวจพบจากรุ่นก่อน

- validator 1.1.0 ผ่าน functional/security tests แต่ยังยอมรับ `/opt/sntalkbot` เป็น dependency จึงไม่ตรวจเจอว่า production host ของผู้พัฒนาไม่มี source path นี้

## สถานะการตรวจ

- ต้องผ่าน Python compile, TestClient, root-bridge allowlist, Bash syntax, LF-only Linux files และ source-less Docker template regression ก่อน publish

---

# SNTalkBot Web Manager 1.1.0

## สิ่งที่ผู้ใช้ควรรู้

- เพิ่มระบบหลายบัญชี: ผู้ใช้คนแรกเป็น Super Admin และ Super Admin เท่านั้นสร้าง/ปิดบัญชีหรือรีเซ็ตรหัสผ่านผู้ใช้อื่นได้
- ผู้ใช้ทั่วไปเห็นและจัดการเฉพาะ instance ที่ตนเป็นเจ้าของ; Job, Log, Config และ action ทุกเส้นทางตรวจ ownership ฝั่ง backend
- ตอนสร้าง instance ต้องยืนยัน TeamTalk username ของเจ้าของว่าเป็น Administrator ที่ออนไลน์อยู่จริง และไม่นับบัญชีของบอตเอง
- เพิ่ม realtime dashboard ผ่าน SNTalkBot read-only loopback HTTP API; ถ้า API ใช้ไม่ได้จะ fallback ไป runtime_status.json
- เพิ่ม progress แบบ realtime สำหรับงานติดตั้ง อัปเดต doctor migration และงานยาวอื่น ๆ
- เพิ่มการลบ instance ผ่านหน้าเว็บ โดยต้องพิมพ์ชื่อยืนยันและ TTUHelper สำรองข้อมูลก่อนลบ
- Web Manager ทำงานด้วย system user `sntalkweb`; งาน root ผ่าน privileged allowlist bridge เท่านั้น ไม่มี arbitrary web shell
- ค่าเริ่มต้น Web Manager bind เฉพาะ `127.0.0.1:28765`; รองรับ Standalone แบบตั้งใจเปิด `0.0.0.0` และ Reverse Proxy ผ่าน CloudPanel/NGINX/Caddy/Apache
- เพิ่มคู่มือ Reverse Proxy/SSE/HTTPS แบบละเอียดใน `REVERSE_PROXY_GUIDE_TH.md`
- หน้า Download รองรับ bootstrap installer แบบคำสั่งเดียว ดาวน์โหลด `latest` พร้อมตรวจ SHA-256 ก่อนเรียก `install.sh`; ถ้า source เป็น Git clone จะไม่เขียนทับ metadata ของ Git
- แก้ first-run SQLite transaction race ที่อาจทำให้สร้าง Super Admin แล้วหน้า Setup ล้มใน draft ก่อนหน้า
## Final cross-project hardening

- first-run Super Admin creation เป็น atomic transaction ป้องกันการสร้าง Super Admin สองบัญชีพร้อมกัน
- ผู้ใช้ทั่วไปไม่สามารถเปลี่ยน TeamTalk host/ports/encryption/bot login หลังผ่าน owner verification; Super Admin ยังแก้ได้
- `password_tool.py` เปลี่ยนจาก legacy `auth.json` ไปใช้ SQLite recovery โดยไม่ลบ compatibility command
- installer สร้าง system group `sntalkweb` อย่างชัดเจน และรักษา `/etc/default/sntalkbot-web-manager` เดิมตอนอัปเกรด
- Self-update รัน `install.sh` แบบ upgrade-safe เพื่ออัปเดต dependencies/root bridge/systemd แล้ว schedule restart หลัง job จบ
- เปลี่ยนตัวอย่าง fallback public port เป็น 28775 เพื่อสงวน 28766 สำหรับ FastAPI backend ภายในของ Web Manager

