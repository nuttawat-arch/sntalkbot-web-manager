# นำ SNTalkBot Web Manager 1.1.8 ขึ้น GitHub

ชื่อ repository ที่ระบบใช้เป็นค่าเริ่มต้น: `nuttawat-arch/sntalkbot-web-manager`

repository นี้ **จำเป็น** เมื่อจะใช้ Git clone, ปุ่ม Self-update ของ Web Manager หรือ `publish_all.ps1 -SyncWebManager` แต่ **ไม่จำเป็น** ถ้าผู้ใช้ติดตั้งจาก ZIP/Download Site อย่างเดียว

```bash
git init
git branch -M main
git add -A
git commit -m "Initial SNTalkBot Web Manager 1.1.8"
git remote add origin https://github.com/nuttawat-arch/sntalkbot-web-manager.git
git push -u origin main
```

หลัง repository ถูก publish ผู้ใช้ติดตั้งได้ด้วย:

```bash
sudo git clone https://github.com/nuttawat-arch/sntalkbot-web-manager.git /opt/sntalkbot-web-manager
cd /opt/sntalkbot-web-manager
sudo ./install.sh
```

หรือคำสั่งเดียว:

```bash
curl -fsSL https://raw.githubusercontent.com/nuttawat-arch/sntalkbot-web-manager/main/install_remote.sh | sudo bash
```

## สิ่งที่ห้าม commit

Web Manager 1.1.8 ใช้ SQLite ไม่ได้ใช้ `auth.json` เป็นฐานบัญชีอีกแล้ว ข้อมูล/secret จริงอยู่ภายนอก source tree เช่น:

- `/var/lib/sntalkbot-web-manager/webmanager.db`
- `/etc/sntalkbot-web-manager/session_secret`
- `/etc/default/sntalkbot-web-manager`
- `/opt/sntalkbot-bots/<instance>/config.ini`
- cookies ของแต่ละ instance
- log/job output ที่อาจมีข้อมูลระบบ

`.gitignore` กัน `.env`, `*.db`, `session_secret`, cache และ log ใน working tree ไว้แล้ว แต่ผู้ดูแลต้องไม่คัดลอกไฟล์ production เหล่านี้เข้ามาใน repository เอง
