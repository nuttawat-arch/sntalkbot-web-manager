# TTUHelper ↔ SNTalkBot Web Manager 1.1.11 — action map ตามโค้ดจริง

TTUHelper รุ่นปัจจุบันมี **22 public commands** แต่ Web Manager ไม่เรียก CLI interactive ทุกคำสั่งตรง ๆ บางความสามารถทำ native ในเว็บเพื่อให้ non-interactive, ตรวจ ownership และไม่เปิด arbitrary shell

| TTUHelper capability | หน้าเว็บ | Implementation จริง |
|---|---|---|
| `new` | สร้างบอต | Web-native: อ่าน `config_default.ini` จาก Docker image, เขียน instance/config แล้วใช้ `run` เพื่อยืนยันเจ้าของ |
| `run` | เริ่ม | เรียก TTUHelper ผ่าน privileged bridge |
| `stop` | หยุด | เรียก TTUHelper ผ่าน privileged bridge |
| `restart` | รีสตาร์ต | เรียก TTUHelper ผ่าน privileged bridge |
| `delete` | กลุ่มลบ | เรียก TTUHelper `delete <name> --yes` หลังเว็บตรวจ exact-name confirmation; helper backup ก่อนลบ |
| `logs` | ดูบันทึก | Web-native `docker logs` ผ่าน ownership-label guard |
| `ls` | Dashboard | Web-native อ่าน instance root ที่ผู้ใช้มีสิทธิ์ |
| `ps` | Container status | Web-native Docker inspect ผ่าน ownership-label guard |
| `start-all` | System | เรียก TTUHelper จริง |
| `stop-all` | System | เรียก TTUHelper จริง |
| `pull` | Pull image | เรียก TTUHelper จริง |
| `update` | อัปเดตบอตที่รัน | เรียก TTUHelper จริง |
| `migrate-ttmediabot` | Migration | privileged migrator ของ TTUHelper + Docker template; ไม่เปิด interactive CLI |
| `cks` | Cookies รายตัว | เรียก TTUHelper จริง |
| `cks-all` | Cookies ทุก Player/Full | เรียก TTUHelper จริง |
| `cks-check` | ตรวจ cookies | เรียก TTUHelper จริง |
| `limit` | CPU/RAM | Web-native validate + เขียน `limits.conf`; TTUHelper consume ตอน run/recreate |
| `edit` | Config editor | Web-native edit `config.ini` + secret/tenant locks |
| `path` | รายละเอียด instance | Web-native แสดง path ที่ resolve จาก `TTU_BOTS_ROOT` |
| `doctor` | System | เรียก TTUHelper จริง |
| `version` | System | เรียก `ttuhelper version` แบบ read-only |
| `help` | คู่มือเว็บ | เอกสารนี้/หน้า Help ไม่เรียก CLI help เพื่อไม่ผูก UI กับ text parsing |

Web Manager เพิ่ม workflow staged/backup/rollback สำหรับอัปเดตตัวเองและ TTUHelper; SNTalkBot อัปเดตผ่าน Docker image เท่านั้น ไม่มี host-side `/opt/sntalkbot` source checkout
