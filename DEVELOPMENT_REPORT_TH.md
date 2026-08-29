# Development Report — Web Manager 1.1.19

- Central Global Broadcast stored in Web Manager SQLite and delivered by a central scheduler over each bot's loopback Bearer API.
- Running-instance Config Save now schedules TTUHelper restart so persisted config becomes runtime behavior.
- New validator gates cover broadcast schema/CRUD/tenant denial and SQLite schedule persistence.

# Development Report — Web Manager 1.1.12

## ปัญหาที่แก้
- Super Admin production สามารถเห็น `บอตทั้งหมด (0)` ทั้งที่ TTUHelper มี instance จริง 8 ตัว เพราะหน้าเว็บพึ่ง filesystem/process-local visibility มากเกินไป
- Dashboard รุ่นก่อนเรียก Docker inspect และ realtime API ทีละ instance ทำให้ latency เพิ่มตามจำนวนบอต
- หน้า System ตรวจ GitHub และ Docker Registry แบบ synchronous ก่อน render จึงรู้สึกค้างเมื่อ network ช้า

## การแก้ไข
- เพิ่ม root bridge action `instances-snapshot` ซึ่งส่งออกเฉพาะ metadata ที่ไม่ใช่ secret: name, role, nickname, server, channel, created_at
- เพิ่ม `docker-list-managed` inspect container ที่มี `com.ttutilities.helper=true` ทั้งหมดใน Docker call เดียว
- `list_instances()` ใช้ batch snapshot เป็นหลัก และ fallback ไป implementation เดิมเมื่อกำลัง rolling upgrade กับ root bridge เก่า
- Super Admin claim เฉพาะ unowned real instances; existing tenant ownership ไม่ถูก overwrite
- Initial Dashboard ไม่โหลด realtime ต่อบอต; `/dashboard/live` ใช้ SSE stream เดียวและ parallel realtime probes
- client อัปเดตเฉพาะ DOM ที่เปลี่ยนและประกาศเหตุสำคัญผ่าน screen-reader live region
- System remote/image probes ถูกย้ายไป async request หลัง HTML พร้อมใช้งานแล้ว

## Validation
- Web Manager validator PASS รวม tenant isolation, Job action matrix, batch-discovery ownership regression, malformed config isolation, Guardian proxy/SSE และ staged updater rollback
- Python compile, Node syntax, Bash syntax และ LF-only PASS
