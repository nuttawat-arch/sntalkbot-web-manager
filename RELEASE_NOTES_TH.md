# SNTalkBot Web Manager 1.1.20 — Global Broadcast Composer + Random Bag

- แก้ความหมายการเพิ่มข้อความส่วนกลาง: 1 ช่อง textarea = 1 ข้อความ และข้อความหนึ่งมีหลายบรรทัด/ลิงก์ได้ตามปกติ
- ปุ่ม “เพิ่มข้อความอีก” เพิ่มช่องข้อความที่ 2, 3 ... ก่อนกดบันทึก; บันทึกทีละ 1 หรือหลายข้อความได้ และทุกข้อความอยู่ในรายการกลางชุดเดียว ไม่สร้างชุดย่อย
- Scheduler เปลี่ยนจากเรียงตามลำดับเป็นสุ่มแบบไม่ซ้ำ (random without replacement) แยกต่อ instance: จะไม่ส่งข้อความเดิมซ้ำจนกว่าจะส่งครบทุกข้อความที่เปิดใช้ในรอบนั้น
- ข้อความที่เพิ่มภายหลังระหว่างรอบจะเข้าร่วม random bag เดิมทันทีโดยไม่ทำให้ข้อความที่ส่งไปแล้วถูกส่งซ้ำในรอบปัจจุบัน
- สถานะ random bag (`remaining_ids` / `cycle_ids`) เก็บใน SQLite จึงคงหลัก no-repeat ข้าม Web Manager restart และหลีกเลี่ยงการซ้ำติดกันตรงขอบรอบเมื่อมีมากกว่า 1 ข้อความ

# SNTalkBot Web Manager 1.1.18 — Broadcast / Central Telegram / Accessible Config Controls

- หน้า Global Broadcast เพิ่มแบบ bulk: 1 บรรทัด = 1 ข้อความแยกกัน สูงสุด 100 ข้อความต่อครั้ง เหมาะกับประกาศสั้นหลายรายการและยังคงแบบฟอร์มข้อความหลายบรรทัดเดิม
- เพิ่มหน้า Super Admin “Telegram ส่วนกลาง” สำหรับตั้ง Bot Token และ Default Chat ID ชุดเดียวให้ทุก instance; token ไม่ถูกอ่านกลับมาแสดงและส่งเข้า privileged bridge ทาง stdin
- ค่า `bot.language` และ `welcome_mode` ใช้ตัวเลือก radio แทนช่อง text/number ที่ต้องจำรหัสดิบ
- เพิ่มชื่อ/คำอธิบาย Web Config สำหรับ `3d`, Extra Stereo และ Bass ให้ตรงกับ audio action รุ่นปัจจุบัน
- ต้องใช้ TTUHelper 1.5.7+ เพื่อ inject Telegram ส่วนกลางเข้า container; ค่า Telegram ราย instance เดิมยังเป็น fallback เพื่อ compatibility

# SNTalkBot Web Manager 1.1.17 — Cross-platform Release Validation Policy

- เพิ่มโหมด `tools/validate_web_manager.py --portable` และ auto-portable บน Windows: ตรวจ source/static/security contract, required files, LF line endings และ architecture invariants แต่ไม่รัน Linux-only runtime integration บน Windows
- Linux-only gates ได้แก่ Bash syntax, `os.chown`/ownership flows, Guardian socket/SSE runtime, SQLite lifecycle/password-recovery runtime และ TestClient action matrix จะถูกรันเต็มบน Linux ด้วย `server_verify.sh`
- Full validator บน Linux ยังรันทุก regression เหมือนเดิมและผ่านครบ; ไม่ได้ลด Linux acceptance criteria
- Runtime ของ Web Manager, API-only realtime, Central Global Broadcast, tenant isolation และ TTUHelper bridge ไม่มีการเปลี่ยน behavior จาก 1.1.16
