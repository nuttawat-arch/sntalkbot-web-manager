# SNTalkBot Web Manager 1.1.16 — Unified Broadcast / Legacy Config Cleanup

- Central Global Broadcast เป็นแหล่งข้อความประกาศตามรอบเพียงชุดเดียวใน SQLite; หน้า Super Admin CRUD ข้อความสด และ scheduler ส่งผ่าน loopback Bearer API ไปยัง Manager/Full ที่เปิดใช้
- เพิ่ม `global_broadcast.tts_enabled`: ถ้าเปิด บอตพูดข้อความ Central Broadcast ชุดเดียวกันโดยไม่ใช้ `messages.txt`, Random TTS data source หรือ scheduler แยก
- Config editor ซ่อน/ลบ `random_message_interval` และ `random_broadcast_enabled` รุ่นเก่า พร้อม migrate ค่าไป Central Broadcast เมื่อเหมาะสม
- realtime dashboard ยังคง API-only: `/v1/status` → SSE; ไม่มี JSON snapshot fallback และ API unavailable แสดง unavailable ตามจริง
- Save Config ของ instance ที่กำลังรันยังสร้าง TTUHelper restart job เพื่อให้ startup settings มีผลจริง

# SNTalkBot Web Manager 1.1.15 — Central Broadcast / Runtime Config Apply

- เพิ่มฐานข้อมูล SQLite กลาง `global_broadcast_messages` และ `global_broadcast_state` พร้อม WAL เดิม เพื่อเก็บข้อความส่วนกลางและเวลาส่งล่าสุดของแต่ละ instance โดยไม่เขียน realtime state ลงไฟล์ทุกวินาที
- Super Admin มีหน้า “ข้อความ Global Broadcast” สำหรับเพิ่ม แก้ เปิด/ปิด และลบข้อความสด; scheduler ส่งหมุนเฉพาะ Manager/Full ที่เปิด `[global_broadcast] enabled = True` และเคารพ `interval_minutes` 1-10080 นาที
- Web Manager ส่งข้อความเข้า bot ผ่าน loopback Bearer API `/v1/events/global-broadcast`; ถ้าบอตหยุด/restart จะไม่เลื่อน state ส่งสำเร็จและใช้ retry backoff
- Config เก่าที่ยังไม่มี `[global_broadcast]` แสดงค่า default `enabled=False`, `interval_minutes=60` ในหน้าเว็บได้ทันที
- แก้ Save Config ของ instance ที่กำลังรัน: หลังเขียน config สำเร็จจะสร้าง TTUHelper restart job อัตโนมัติ ทำให้ค่า startup เช่น `player_enabled` มีผลจริงโดยไม่ต้องเป็น TeamTalk Administrator
- validator ตรวจ schema/rotation/state persistence, Super Admin-only CRUD, tenant denial, scheduler/API invariants และ config-restart wiring

# SNTalkBot Web Manager 1.1.14 — Channel ID / Path Field Compatibility

- ช่องสร้างบอตและ Config ระบุชัดว่ารับ Channel ID หรือ Channel path ในช่องเดียว
- `bot.default_channel` ถูก render เป็น text field เสมอ แม้ค่าปัจจุบันเป็น `8` จึงเปลี่ยนกลับเป็น `/music` ได้โดยไม่ติด input type=number
- ค่า `8`/`"8"` ถูกเก็บตามที่ผู้ใช้กรอก; runtime SNTalkBot เป็นผู้ตีความว่าเป็น Channel ID

# SNTalkBot Web Manager 1.1.13 — API-only Realtime / SQLite Jobs / Webhook Updates

- Dashboard realtime ใช้ local SNTalkBot API เป็นแหล่งข้อมูลสดเพียงทางเดียวแล้ว ไม่มี `runtime_status.json` fallback; หาก API ใช้ไม่ได้จะแสดง unavailable แทน snapshot เก่า
- `webmanager.db` ใช้ WAL + schema version/downgrade guard และเก็บ Job metadata ใน SQLite; `.txt` เหลือเฉพาะ append-only job output
- หน้า Config ใช้ server-side field metadata/allowed values; boolean เป็น checkbox และค่าตายตัว เช่น TTS, M1/M2/M3, Kick/Ban, gender, account detection และ logging level เป็น radio พร้อมคำอธิบาย/ARIA
- GitHub release webhook ตรวจ secret/repository/action แล้ว fan-out เฉพาะ running instances ไป local `/v1/events/release` เพื่อแจ้ง TeamTalk/Telegram โดยไม่ต้อง poll ทุกบอต
- JS/CSS cache-bust ใช้ content hash และ HTML ส่ง `no-store` ป้องกันหน้าใหม่จับคู่กับ static รุ่นเก่าหลังอัปเดต
- คง Super Admin all-instance visibility, tenant isolation, Guardian 28765 + private backend 28766 และ Job dialog/action safety เดิม

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
