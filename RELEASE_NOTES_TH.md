# SNTalkBot Web Manager 1.1.17 — Cross-platform Release Validation Policy

- เพิ่มโหมด `tools/validate_web_manager.py --portable` และ auto-portable บน Windows: ตรวจ source/static/security contract, required files, LF line endings และ architecture invariants แต่ไม่รัน Linux-only runtime integration บน Windows
- Linux-only gates ได้แก่ Bash syntax, `os.chown`/ownership flows, Guardian socket/SSE runtime, SQLite lifecycle/password-recovery runtime และ TestClient action matrix จะถูกรันเต็มบน Linux ด้วย `server_verify.sh`
- Full validator บน Linux ยังรันทุก regression เหมือนเดิมและผ่านครบ; ไม่ได้ลด Linux acceptance criteria
- Runtime ของ Web Manager, API-only realtime, Central Global Broadcast, tenant isolation และ TTUHelper bridge ไม่มีการเปลี่ยน behavior จาก 1.1.16
