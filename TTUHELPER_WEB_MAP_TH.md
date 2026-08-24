# Mapping TTUHelper → SNTalkBot Web Manager 1.1.1

- `new` → สร้างบอตใหม่
- `run` → ปุ่มเริ่มในแต่ละ instance
- `stop` → ปุ่มหยุดในแต่ละ instance
- `restart` → ปุ่มรีสตาร์ตในแต่ละ instance
- `delete` → ลบ instance หลังพิมพ์ชื่อยืนยัน และสำรองข้อมูลก่อนลบ
- `logs` → ดูบันทึก + คัดลอก
- `ls` → รายการบอตในแดชบอร์ด
- `ps` → container/image/status ในรายละเอียด
- `start-all` → ระบบ/อัปเดต → เริ่มทั้งหมด
- `stop-all` → ระบบ/อัปเดต → หยุดทั้งหมด
- `pull` → Pull image
- `update` → อัปเดตบอตที่กำลังรัน
- `migrate-ttmediabot` → ฟอร์มย้าย TTMediaBot
- `cks` → cookies ราย instance
- `cks-all` → cookies ทุก Player/Full
- `cks-check` → ตรวจ cookies โดยไม่แสดงค่า secret
- `limit` → CPU/RAM form
- `edit` → dynamic config editor ทุก section/key
- `path` → แสดง data directory
- `doctor` → ตรวจระบบ
- `version` → แสดงเวอร์ชัน
- `help` → คู่มือเว็บ

เว็บยังเพิ่มการ clone/install/update source ของ SNTalkBot และ TTUHelper ซึ่งเป็น workflow เหนือคำสั่ง TTUHelper ปกติ
