# SNTalkBot Web Manager 1.1.22 — Concise Image Version + Telegram Ownership

- หน้า ระบบ/อัปเดต แสดง SNTalkBot image แบบเดียวกับ Web Manager/TTUHelper: `เวอร์ชันที่ใช้อยู่ | รุ่นบน GitHub เวอร์ชัน`
- ตัด digest/ชื่อ image/Docker registry รายละเอียดยาวออกจากภาพรวมปกติ; diagnostic backend/doctor เดิมยังคงอยู่
- หน้า Telegram ส่วนกลางอธิบาย precedence ชัดเจน: token ของ instance ชนะและไม่ผสม Chat ID ส่วนกลาง; Telegram กลางเป็น fallback เฉพาะ instance ที่ไม่มี token ของตนเอง
- คง accessible sub-tabs และ live-config apply จาก 1.1.21 โดยไม่เปลี่ยน action ที่ทำงานดีอยู่แล้ว
