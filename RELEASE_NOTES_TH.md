# SNTalkBot Web Manager 1.1.12 — Realtime Dashboard & Ownership/Performance Fix

- Super Admin ใช้รายการ instance จริงจาก privileged batch snapshot จึงเห็นทุกบอตใน `/opt/sntalkbot-bots` แม้ Web service permission/group มีช่วงเปลี่ยนรุ่น; มี compatibility fallback สำหรับ root bridge รุ่นก่อนหน้า
- instance ที่มีอยู่จริงแต่ยังไม่มี owner mapping จะถูกผูกให้ Super Admin อัตโนมัติ โดยไม่แตะ instance ที่มีเจ้าของผู้ใช้ทั่วไปอยู่แล้ว
- Dashboard แสดง `ผู้สร้าง/เจ้าของ` และเวลา `สร้าง/นำเข้าเมื่อ` จาก `instance.conf` (`created=`) หรือ owner record fallback
- ผู้ใช้ทั่วไปยังเห็นเฉพาะบอตของตนและจำนวนของตน; tenant isolation เดิมยังบังคับทั้งหน้า instance และ Job
- Dashboard initial HTML ไม่รอ realtime API ทีละบอตอีกต่อไป: metadata + Docker state ใช้ batch snapshot แล้วข้อมูลสด 8+ บอตอัปเดตผ่าน SSE stream เดียว
- realtime API ของบอตที่กำลังรันถูก probe แบบขนานด้วย `asyncio.gather`; การเปลี่ยน start/stop, TeamTalk connect/disconnect, เพลง และจำนวนคิวประกาศผ่าน `aria-live` โดยไม่ reload หน้า
- หน้า System ไม่รอ GitHub/Docker Registry และ image probes ก่อน render; งานหนักย้ายไป `/system/remote-status` ทำพร้อมกันเบื้องหลัง ทำให้ปุ่มใช้งานได้ทันที
- คง Job-dialog DOM-clobber fix และ static asset cache-busting จาก 1.1.11
- Guardian 1.0.0 คงเดิม
