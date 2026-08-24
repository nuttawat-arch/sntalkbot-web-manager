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
