function text(id, value) {
  const el = document.getElementById(id);
  if (el) el.textContent = value == null ? '-' : String(value);
}
function escText(value) { return value == null ? '' : String(value); }

document.addEventListener('click', async (e) => {
  const b = e.target.closest('[data-copy-target]');
  if (!b) return;
  const el = document.getElementById(b.dataset.copyTarget);
  if (!el) return;
  try { await navigator.clipboard.writeText(el.innerText || el.textContent || ''); b.textContent = 'คัดลอกแล้ว'; }
  catch (_) { el.focus(); }
});

(function jobLive() {
  const out = document.getElementById('jobout');
  if (!out || !out.dataset.jobId || !window.EventSource) return;
  const status = document.getElementById('job-status');
  const note = document.getElementById('job-running-note');
  const recovery = document.getElementById('web-update-recovery');
  const oldGeneration = out.dataset.webGeneration || '';
  let recoveryStarted = false;

  async function waitForNewWebProcess() {
    if (recoveryStarted || out.dataset.jobKind !== 'update-web') return;
    recoveryStarted = true;
    if (recovery) {
      recovery.hidden = false;
      recovery.textContent = 'อัปเดต source สำเร็จแล้ว กำลังรอ Web Manager process รุ่นใหม่ โดย Guardian จะคงหน้าเว็บนี้ไว้';
    }
    for (let attempt = 0; attempt < 60; attempt += 1) {
      await new Promise(resolve => setTimeout(resolve, 1000));
      try {
        const resp = await fetch('/healthz', {cache: 'no-store', headers: {'Accept': 'application/json'}});
        if (!resp.ok) continue;
        const health = await resp.json();
        if (health.ok && health.generation && health.generation !== oldGeneration) {
          if (recovery) recovery.textContent = `Web Manager กลับมาออนไลน์แล้ว รุ่น ${health.version || '-'} — Guardian ไม่ได้ปล่อย reverse proxy เป็น 502`;
          return;
        }
      } catch (_) {}
    }
    if (recovery) recovery.textContent = 'ยังยืนยัน process รุ่นใหม่ไม่ได้ กรุณาเปิดหน้า ระบบ/อัปเดต เพื่อตรวจสถานะอีกครั้ง';
  }

  const es = new EventSource(`/jobs/${encodeURIComponent(out.dataset.jobId)}/stream`);
  es.onmessage = (event) => {
    try {
      const job = JSON.parse(event.data);
      out.textContent = job.output || '';
      out.scrollTop = out.scrollHeight;
      if (status) status.innerHTML = `สถานะ: <strong>${escText(job.status)}</strong>`;
      if (note) note.hidden = !['queued','running'].includes(job.status);
      if (['success','failed'].includes(job.status)) {
        es.close();
        if (job.status === 'success') waitForNewWebProcess();
      }
    } catch (_) {}
  };
})();;

(function instanceLive() {
  const root = document.getElementById('live-instance');
  if (!root || !root.dataset.instance || !window.EventSource) return;
  const connection = document.getElementById('live-connection');
  let lastConnection = connection ? connection.textContent : '';
  const es = new EventSource(`/instances/${encodeURIComponent(root.dataset.instance)}/live`);
  es.onmessage = (event) => {
    let s; try { s = JSON.parse(event.data); } catch (_) { return; }
    const liveData = document.getElementById('live-data');
    if (s.container_running === false) {
      const stopped = 'บอตหยุดอยู่ — ไม่มีข้อมูลสด';
      if (connection && stopped !== lastConnection) { connection.textContent = stopped; lastConnection = stopped; }
      if (liveData) liveData.hidden = true;
      const playerBox=document.getElementById('live-player'); if(playerBox) playerBox.hidden=true;
      const managerBox=document.getElementById('live-manager'); if(managerBox) managerBox.hidden=true;
      return;
    }
    if (liveData) liveData.hidden = false;
    const conn = s.connected ? 'เชื่อมต่อ TeamTalk แล้ว' : 'ยังไม่เชื่อมต่อ TeamTalk';
    if (connection && conn !== lastConnection) { connection.textContent = conn; lastConnection = conn; }
    text('live-transport', s.transport || (s.api ? 'http-api' : 'runtime bridge'));
    text('live-version', s.version || '-');
    text('live-channel', (s.channel && (s.channel.name || s.channel.id)) || '-');
    text('live-users', s.room_users_online == null ? 'รอ SNTalkBot 5.1.2+' : s.room_users_online);
    text('live-server-users', s.server_users_online ?? '-');
    text('live-admin-count', s.admins_online_count ?? 0);
    text('live-admin-room-count', s.admins_in_room_count ?? '-');
    const a = s.teamtalk_activity || {};
    text('live-speaking', a.speaking ?? 0); text('live-media', a.media ?? 0); text('live-video', a.video ?? 0); text('live-desktop', a.desktop ?? 0);
    const sa = s.server_teamtalk_activity || {};
    text('live-server-speaking', sa.speaking ?? '-'); text('live-server-media', sa.media ?? '-'); text('live-server-video', sa.video ?? '-'); text('live-server-desktop', sa.desktop ?? '-');
    const roomUsers = document.getElementById('live-room-users');
    if (roomUsers) {
      roomUsers.replaceChildren();
      const rows = s.room_users || [];
      if (!rows.length) { const li=document.createElement('li'); li.textContent='ยังไม่พบผู้ใช้ในห้อง'; roomUsers.appendChild(li); }
      for (const user of rows) {
        const li=document.createElement('li');
        const st=user.state || {};
        const stateParts=[]; if(st.speaking) stateParts.push('กำลังพูด'); if(st.media) stateParts.push('Media'); if(st.video) stateParts.push('Video'); if(st.desktop) stateParts.push('Desktop');
        li.textContent = `${user.nickname || user.username || '-'}${user.username ? ' ('+user.username+')' : ''} — User ID ${user.user_id ?? '-'} — ${user.account_type === 'administrator' ? 'Administrator' : 'User'}${user.client_name ? ' — Client '+user.client_name : ''}${user.status_mode !== undefined && user.status_mode !== null ? ' — Status mode '+user.status_mode : ''}${user.status_message ? ' — สถานะ: '+user.status_message : ''}${stateParts.length ? ' — '+stateParts.join(', ') : ''}`;
        roomUsers.appendChild(li);
      }
    }
    const admins = document.getElementById('live-admins');
    if (admins) {
      admins.replaceChildren();
      const rows = s.admins_online || [];
      if (!rows.length) { const li=document.createElement('li'); li.textContent='ยังไม่พบ'; admins.appendChild(li); }
      for (const admin of rows) { const li=document.createElement('li'); li.textContent = `${admin.username || '-'}${admin.nickname ? ' — '+admin.nickname : ''} — User ID ${admin.user_id ?? '-'}${admin.in_bot_channel ? ' — อยู่ในห้องเดียวกับบอต' : (admin.channel_id ? ' — Channel ID '+admin.channel_id : '')}`; admins.appendChild(li); }
    }
    const playerBox=document.getElementById('live-player');
    if (playerBox) {
      playerBox.hidden=!s.player;
      if (s.player) {
        const p=s.player;
        text('live-player-summary', `${p.is_playing?'กำลังเล่น':'ว่าง'}: ${p.title||'-'} | คิว ${p.queue_count||0} | Q ${p.queue_mode?'ON':'OFF'} | M${p.play_mode||'-'} | Volume ${p.volume??'-'} | Speed ${p.speed??'-'}`);
        const q=document.getElementById('live-queue'), empty=document.getElementById('live-queue-empty');
        if(q){q.replaceChildren(); const rows=p.queue||[]; if(empty) empty.hidden=rows.length>0; for(const item of rows){const li=document.createElement('li'); li.textContent=`${item.current?'กำลังเล่น: ':''}${item.title||'Unknown'}${item.added_by?' — เพิ่มโดย '+item.added_by:''}`; q.appendChild(li);}}
      }
    }
    const managerBox=document.getElementById('live-manager');
    if(managerBox){managerBox.hidden=!s.manager; if(s.manager){const m=s.manager; text('live-manager-summary',`Filter ${m.filter?'ON':'OFF'} | CI ${m.channel_input?'ON':'OFF'} | IC ${m.intercept?'ON':'OFF'} | Commands ${m.commands_locked?'locked':'open'}`);}}
  };
  es.onerror = () => { if (connection && lastConnection !== 'การเชื่อมต่อข้อมูลสดขาดหาย กำลังเชื่อมใหม่') { lastConnection='การเชื่อมต่อข้อมูลสดขาดหาย กำลังเชื่อมใหม่'; connection.textContent=lastConnection; } };
})();
