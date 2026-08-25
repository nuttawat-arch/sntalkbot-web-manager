function text(id, value) {
  const el = document.getElementById(id);
  if (el) el.textContent = value == null ? '-' : String(value);
}
function delay(ms) { return new Promise(resolve => setTimeout(resolve, ms)); }

// Copy buttons are shared by Logs, fallback Job pages and the in-page Job dialog.
document.addEventListener('click', async (e) => {
  const b = e.target.closest('[data-copy-target]');
  if (!b) return;
  const el = document.getElementById(b.dataset.copyTarget);
  if (!el) return;
  try {
    await navigator.clipboard.writeText(el.innerText || el.textContent || '');
    const old = b.textContent;
    b.textContent = 'คัดลอกแล้ว';
    setTimeout(() => { b.textContent = old; }, 1600);
  } catch (_) { el.focus(); }
});

// Accessible disclosure used by the Users page: the account form stays hidden
// until the Super Admin explicitly asks to create a user.
document.addEventListener('click', (e) => {
  const open = e.target.closest('[data-disclosure-target]');
  const close = e.target.closest('[data-disclosure-close]');
  if (open) {
    const panel = document.getElementById(open.dataset.disclosureTarget);
    if (!panel) return;
    panel.hidden = false;
    open.setAttribute('aria-expanded', 'true');
    const heading = panel.querySelector('[tabindex="-1"]');
    if (heading) heading.focus();
    return;
  }
  if (close) {
    const panel = document.getElementById(close.dataset.disclosureClose);
    if (!panel) return;
    panel.hidden = true;
    const opener = document.querySelector(`[data-disclosure-target="${CSS.escape(close.dataset.disclosureClose)}"]`);
    if (opener) { opener.setAttribute('aria-expanded', 'false'); opener.focus(); }
  }
});

(function jobDialogController() {
  const dialog = document.getElementById('job-dialog');
  if (!dialog || typeof dialog.showModal !== 'function') return;
  const title = document.getElementById('job-dialog-title');
  const status = document.getElementById('job-dialog-status');
  const note = document.getElementById('job-dialog-note');
  const recovery = document.getElementById('job-dialog-recovery');
  const output = document.getElementById('job-dialog-output');
  const close = document.getElementById('job-dialog-close');
  let active = null;

  function show(launcher) {
    active = {launcher, es: null, completed: false, returnTo: location.pathname + location.search, kind: '', generation: ''};
    title.textContent = 'กำลังเริ่มงาน';
    status.textContent = 'กำลังส่งคำสั่ง…';
    note.textContent = 'คุณสามารถปิดหน้าต่างนี้ได้ งานจะทำต่อเบื้องหลัง';
    recovery.hidden = true;
    recovery.textContent = '';
    output.textContent = '';
    close.textContent = 'ปิด';
    dialog.showModal();
    title.focus();
  }

  async function waitForNewWebProcess(oldGeneration) {
    recovery.hidden = false;
    recovery.textContent = 'อัปเดต source สำเร็จแล้ว กำลังรอ Web Manager รุ่นใหม่กลับมาออนไลน์';
    for (let attempt = 0; attempt < 90; attempt += 1) {
      await delay(1000);
      try {
        const resp = await fetch('/healthz', {cache: 'no-store', headers: {'Accept': 'application/json'}});
        if (!resp.ok) continue;
        const health = await resp.json();
        if (health.ok && health.generation && (!oldGeneration || health.generation !== oldGeneration)) {
          recovery.textContent = `Web Manager กลับมาออนไลน์แล้ว รุ่น ${health.version || '-'}`;
          return true;
        }
      } catch (_) {}
    }
    recovery.textContent = 'ยังยืนยัน process รุ่นใหม่ไม่ได้ งานอัปเดตจบแล้วแต่ควรตรวจหน้า ระบบ/อัปเดต อีกครั้ง';
    return false;
  }

  function connect(meta) {
    active.returnTo = meta.return_to || active.returnTo;
    active.kind = meta.kind || '';
    active.generation = meta.process_generation || '';
    title.textContent = meta.title || 'งานกำลังทำงาน';
    status.textContent = 'สถานะ: running';
    const es = new EventSource(meta.stream_url);
    active.es = es;
    es.onmessage = async (event) => {
      let job;
      try { job = JSON.parse(event.data); } catch (_) { return; }
      title.textContent = job.title || title.textContent;
      status.textContent = `สถานะ: ${job.status || '-'}`;
      output.textContent = job.output || '';
      output.scrollTop = output.scrollHeight;
      if (job.kind) active.kind = job.kind;
      if (['success', 'failed'].includes(job.status)) {
        active.completed = true;
        es.close();
        close.textContent = 'ปิดและกลับไปทำงานต่อ';
        note.textContent = job.status === 'success' ? 'งานเสร็จแล้ว ปิดหน้าต่างเพื่อกลับไปหน้าเดิม' : 'งานไม่สำเร็จ คุณสามารถคัดลอกผลลัพธ์แล้วปิดหน้าต่างได้';
        if (job.status === 'success' && active.kind === 'update-web') await waitForNewWebProcess(active.generation);
      }
    };
    es.onerror = () => {
      if (!active || active.completed) return;
      status.textContent = 'การเชื่อมต่อสถานะขาดหาย กำลังเชื่อมใหม่…';
      // EventSource reconnects automatically. This is especially useful during
      // Web Manager self-update while Guardian keeps the public socket alive.
    };
  }

  close.addEventListener('click', () => dialog.close());
  dialog.addEventListener('cancel', (e) => { e.preventDefault(); dialog.close(); });
  dialog.addEventListener('close', () => {
    const done = active && active.completed;
    const returnTo = active && active.returnTo;
    const launcher = active && active.launcher;
    if (active && active.es) active.es.close();
    active = null;
    if (done && returnTo && returnTo === location.pathname + location.search) {
      location.reload();
      return;
    }
    if (done && returnTo) {
      location.assign(returnTo);
      return;
    }
    if (launcher && document.contains(launcher)) launcher.focus();
  });

  document.addEventListener('submit', async (e) => {
    const form = e.target.closest('form[data-job-form]');
    if (!form) return;
    e.preventDefault();
    const submitter = e.submitter || form.querySelector('button[type="submit"],button:not([type])');
    if (!form.reportValidity()) return;
    show(submitter || form);
    try {
      let body;
      try { body = new FormData(form, submitter || undefined); }
      catch (_) {
        body = new FormData(form);
        if (submitter && submitter.name) body.set(submitter.name, submitter.value);
      }
      // Do not use form.action/form.method here. HTML forms expose named controls
      // as properties, so a submit button named "action" can clobber form.action
      // and turn the fetch target into an element/stringified garbage URL. Read the
      // attributes explicitly so System actions such as update-helper always POST to
      // the declared endpoint (/system/action).
      const actionAttr = form.getAttribute('action') || location.pathname;
      const endpoint = new URL(actionAttr, document.baseURI).href;
      const methodAttr = form.getAttribute('method') || 'post';
      const resp = await fetch(endpoint, {
        method: methodAttr.toUpperCase(),
        body,
        credentials: 'same-origin',
        headers: {
          'Accept': 'application/json',
          'X-SNTalkBot-Job-Dialog': '1',
          'X-SNTalkBot-Return-To': location.pathname + location.search,
        },
      });
      if (resp.status !== 202) {
        const message = await resp.text();
        status.textContent = `ไม่สามารถเริ่มงานได้ (HTTP ${resp.status})`;
        output.textContent = message || 'ไม่ทราบรายละเอียด';
        active.completed = true;
        close.textContent = 'ปิด';
        return;
      }
      const meta = await resp.json();
      meta.title = (submitter && submitter.textContent ? submitter.textContent.trim() : '') || 'งานกำลังทำงาน';
      meta.kind = meta.kind || '';
      meta.process_generation = document.documentElement.dataset.webGeneration || '';
      connect(meta);
    } catch (err) {
      status.textContent = 'ไม่สามารถเชื่อมต่อเพื่อเริ่มงานได้';
      output.textContent = String(err || 'Network error');
      active.completed = true;
    }
  });
})();

// Fallback full-page Job view remains available when JavaScript/dialog support is
// unavailable or when a Job URL is opened directly.
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
    if (recovery) { recovery.hidden = false; recovery.textContent = 'กำลังรอ Web Manager รุ่นใหม่กลับมาออนไลน์'; }
    for (let attempt = 0; attempt < 90; attempt += 1) {
      await delay(1000);
      try {
        const resp = await fetch('/healthz', {cache: 'no-store', headers: {'Accept': 'application/json'}});
        if (!resp.ok) continue;
        const health = await resp.json();
        if (health.ok && health.generation && health.generation !== oldGeneration) {
          if (recovery) recovery.textContent = `Web Manager กลับมาออนไลน์แล้ว รุ่น ${health.version || '-'}`;
          return;
        }
      } catch (_) {}
    }
    if (recovery) recovery.textContent = 'ยังยืนยัน process รุ่นใหม่ไม่ได้ กรุณาตรวจหน้า ระบบ/อัปเดต อีกครั้ง';
  }

  const es = new EventSource(`/jobs/${encodeURIComponent(out.dataset.jobId)}/stream`);
  es.onmessage = (event) => {
    try {
      const job = JSON.parse(event.data);
      out.textContent = job.output || '';
      out.scrollTop = out.scrollHeight;
      if (status) status.textContent = `สถานะ: ${job.status || '-'}`;
      if (note) note.hidden = !['queued','running'].includes(job.status);
      if (['success','failed'].includes(job.status)) {
        es.close();
        if (job.status === 'success') waitForNewWebProcess();
      }
    } catch (_) {}
  };
})();

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
    text('live-users', s.room_users_online == null ? 'ไม่ทราบ' : s.room_users_online);
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
      const rows = Array.isArray(s.room_users) ? s.room_users : [];
      if (!rows.length) { const li=document.createElement('li'); li.textContent='ยังไม่พบผู้ใช้ในห้อง'; roomUsers.appendChild(li); }
      for (const user of rows) {
        const li=document.createElement('li');
        const st=(user && user.state) || {};
        const stateParts=[]; if(st.speaking) stateParts.push('กำลังพูด'); if(st.media) stateParts.push('Media'); if(st.video) stateParts.push('Video'); if(st.desktop) stateParts.push('Desktop');
        li.textContent = `${user.nickname || user.username || '-'}${user.username ? ' ('+user.username+')' : ''} — User ID ${user.user_id ?? '-'} — ${user.account_type === 'administrator' ? 'Administrator' : 'User'}${user.client_name ? ' — Client '+user.client_name : ''}${user.status_message ? ' — สถานะ: '+user.status_message : ''}${stateParts.length ? ' — '+stateParts.join(', ') : ''}`;
        roomUsers.appendChild(li);
      }
    }
    const admins = document.getElementById('live-admins');
    if (admins) {
      admins.replaceChildren();
      const rows = Array.isArray(s.admins_online) ? s.admins_online : [];
      if (!rows.length) { const li=document.createElement('li'); li.textContent='ยังไม่พบ'; admins.appendChild(li); }
      for (const admin of rows) { const li=document.createElement('li'); li.textContent = `${admin.username || '-'}${admin.nickname ? ' — '+admin.nickname : ''} — User ID ${admin.user_id ?? '-'}${admin.in_bot_channel ? ' — อยู่ในห้องเดียวกับบอต' : ''}`; admins.appendChild(li); }
    }
    const playerBox=document.getElementById('live-player');
    if (playerBox) {
      playerBox.hidden=!s.player;
      if (s.player) {
        const p=s.player;
        text('live-player-summary', `${p.is_playing?'กำลังเล่น':'ว่าง'}: ${p.title||'-'} | คิว ${p.queue_count||0} | Q ${p.queue_mode?'ON':'OFF'} | M${p.play_mode||'-'} | Volume ${p.volume??'-'} | Speed ${p.speed??'-'}`);
        const q=document.getElementById('live-queue'), empty=document.getElementById('live-queue-empty');
        if(q){q.replaceChildren(); const rows=Array.isArray(p.queue)?p.queue:[]; if(empty) empty.hidden=rows.length>0; for(const item of rows){const li=document.createElement('li'); li.textContent=`${item.current?'กำลังเล่น: ':''}${item.title||'Unknown'}${item.added_by?' — เพิ่มโดย '+item.added_by:''}`; q.appendChild(li);}}
      }
    }
    const managerBox=document.getElementById('live-manager');
    if(managerBox){managerBox.hidden=!s.manager; if(s.manager){const m=s.manager; text('live-manager-summary',`Filter ${m.filter?'ON':'OFF'} | CI ${m.channel_input?'ON':'OFF'} | IC ${m.intercept?'ON':'OFF'} | Commands ${m.commands_locked?'locked':'open'}`);}}
  };
  es.onerror = () => { if (connection && lastConnection !== 'การเชื่อมต่อข้อมูลสดขาดหาย กำลังเชื่อมใหม่') { lastConnection='การเชื่อมต่อข้อมูลสดขาดหาย กำลังเชื่อมใหม่'; connection.textContent=lastConnection; } };
})();
