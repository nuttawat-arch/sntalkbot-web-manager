# Web Manager 1.1.23 — New Bot Default Cookies

- Full/Player ที่สร้างจากหน้าเว็บได้รับ default `cookies.txt` จาก SNTalkBot image ทันที ไม่ต้องรอ first container start
- bundled default ถูกอ่านผ่าน privileged allowlist เฉพาะ local Web Manager; ไม่เปิดเผย cookie ในหน้าเว็บหรือ job output
- Manager-only ไม่สร้าง YouTube cookie
- ไม่มีการเปลี่ยน action เดิมของหน้าเว็บ

---

# SNTalkBot Web Manager 1.1.22 — Concise Image Version + Telegram Ownership

- หน้า ระบบ/อัปเดต แสดง SNTalkBot image แบบเดียวกับ Web Manager/TTUHelper: `เวอร์ชันที่ใช้อยู่ | รุ่นบน GitHub เวอร์ชัน`
- ตัด digest/ชื่อ image/Docker registry รายละเอียดยาวออกจากภาพรวมปกติ; diagnostic backend/doctor เดิมยังคงอยู่
- หน้า Telegram ส่วนกลางอธิบาย precedence ชัดเจน: token ของ instance ชนะและไม่ผสม Chat ID ส่วนกลาง; Telegram กลางเป็น fallback เฉพาะ instance ที่ไม่มี token ของตนเอง
- คง accessible sub-tabs และ live-config apply จาก 1.1.21 โดยไม่เปลี่ยน action ที่ทำงานดีอยู่แล้ว
