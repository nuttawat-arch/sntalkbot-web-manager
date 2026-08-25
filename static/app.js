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


(function dashboardRealtime() {
  const root = document.getElementById('dashboard-live-root');
  if (!root || !window.EventSource) return;
  const expected = new Set((root.dataset.instanceNames || '').split(',').filter(Boolean));
  const announcer = document.getElementById('dashboard-live-announcer');
  const previous = new Map();
  const safeId = (name) => {
    const node = document.querySelector(`[data-dashboard-live="${CSS.escape(name)}"]`);
    return node ? node.dataset.dashboardIndex : null;
  };
  const announce = (msg) => {
    if (!announcer || !msg) return;
    announcer.textContent = '';
    window.setTimeout(() => { announcer.textContent = msg; }, 20);
  };
  const es = new EventSource('/dashboard/live');
  es.onmessage = (event) => {
    let payload; try { payload = JSON.parse(event.data); } catch (_) { return; }
    const rows = Array.isArray(payload.instances) ? payload.instances : [];
    const names = new Set(rows.map((x) => x.name));
    if (names.size !== expected.size || [...names].some((name) => !expected.has(name))) {
      announce('รายการบอตเปลี่ยนแปลง กำลังอัปเดตแดชบอร์ด');
      window.setTimeout(() => location.reload(), 300);
      return;
    }
    for (const row of rows) {
      const idx = safeId(row.name); if (!idx) continue;
      const running = document.getElementById(`dash-running-${idx}`);
      const connection = document.getElementById(`dash-connection-${idx}`);
      const room = document.getElementById(`dash-room-${idx}`);
      const activity = document.getElementById(`dash-activity-${idx}`);
      const player = document.getElementById(`dash-player-${idx}`);
      const live = row.runtime && !row.runtime.stale ? row.runtime : null;
      if (running) running.textContent = row.running ? 'กำลังรัน' : 'หยุดอยู่';
      if (!row.running) {
        if (connection) { connection.textContent = 'บอตหยุดอยู่ — ไม่มีข้อมูลสด'; connection.classList.add('muted'); }
        if (room) room.hidden = true; if (activity) activity.hidden = true; if (player) player.hidden = true;
      } else if (!live) {
        if (connection) { connection.textContent = 'กำลังรอข้อมูลสดจากบอต…'; connection.classList.add('muted'); }
        if (room) room.hidden = true; if (activity) activity.hidden = true; if (player) player.hidden = true;
      } else {
        if (connection) { connection.textContent = live.connected ? 'เชื่อมต่อ TeamTalk แล้ว' : 'ยังไม่เชื่อมต่อ TeamTalk'; connection.classList.remove('muted'); }
        if (room) {
          const ch = (live.channel && (live.channel.name || live.channel.id)) || '-';
          room.textContent = `สด: ห้อง ${ch} | คนในห้อง ${live.room_users_online ?? '-'} | ทั้งเซิร์ฟเวอร์ ${live.server_users_online ?? '-'} | Administrator ออนไลน์ ${live.admins_online_count ?? 0}`;
          room.hidden = false;
        }
        if (activity) {
          const a = live.teamtalk_activity || {};
          activity.textContent = `TeamTalk: กำลังพูด ${a.speaking ?? 0} | media ${a.media ?? 0} | video ${a.video ?? 0} | desktop ${a.desktop ?? 0}`;
          activity.hidden = false;
        }
        if (player) {
          if (live.player) {
            player.textContent = `Player: ${live.player.is_playing ? 'กำลังเล่น' : 'ว่าง'} — ${live.player.title || '-'} | คิว ${live.player.queue_count ?? 0} | Q ${live.player.queue_mode ? 'ON' : 'OFF'} | M${live.player.play_mode ?? 0}`;
            player.hidden = false;
          } else player.hidden = true;
        }
      }
      const now = {
        running: !!row.running,
        connected: !!(live && live.connected),
        title: live && live.player ? (live.player.title || '') : '',
        queue: live && live.player ? (live.player.queue_count ?? 0) : 0,
      };
      const before = previous.get(row.name);
      if (before) {
        if (before.running !== now.running) announce(`${row.name} ${now.running ? 'เริ่มทำงานแล้ว' : 'หยุดทำงานแล้ว'}`);
        else if (now.running && before.connected !== now.connected) announce(`${row.name} ${now.connected ? 'เชื่อมต่อ TeamTalk แล้ว' : 'หลุดจาก TeamTalk'}`);
        else if (now.title && before.title !== now.title) announce(`${row.name} กำลังเล่น ${now.title}`);
        else if (before.queue !== now.queue) announce(`${row.name} จำนวนคิวเปลี่ยนเป็น ${now.queue}`);
      }
      previous.set(row.name, now);
    }
  };
  es.onerror = () => {
    const msg = document.getElementById('dashboard-live-announcer');
    if (msg) msg.textContent = 'การเชื่อมต่อข้อมูลสดขาดหายชั่วคราว ระบบกำลังเชื่อมใหม่อัตโนมัติ';
  };
})();

(function systemRemoteStatus() {
  const status = document.getElementById('remote-update-status');
  if (!status) return;
  fetch('/system/remote-status', {cache: 'no-store', headers: {'Accept':'application/json'}})
    .then((r) => r.ok ? r.json() : Promise.reject(new Error(`HTTP ${r.status}`)))
    .then((data) => {
      const web = document.getElementById('remote-web');
      const helper = document.getElementById('remote-helper');
      const image = document.getElementById('remote-image');
      const localImage = document.getElementById('local-image');
      const botVersion = document.getElementById('local-bot-version');
      if (web) {
        const local = web.dataset.localVersion || '';
        web.textContent = data.web_remote ? `| รุ่นบน GitHub ${data.web_remote}${local && data.web_remote !== local ? ' — มี Web Manager รุ่นใหม่' : ''}` : '| ตรวจรุ่นบน GitHub ไม่สำเร็จ';
      }
      if (helper) {
        const local = helper.dataset.localVersion || '';
        helper.textContent = data.helper_remote ? `| รุ่นบน GitHub ${data.helper_remote}${local && data.helper_remote !== local ? ' — มี TTUHelper รุ่นใหม่' : ''}` : '| ตรวจรุ่นบน GitHub ไม่สำเร็จ';
      }
      if (botVersion) botVersion.textContent = data.bot_image_version || 'ยังอ่านเวอร์ชันไม่ได้';
      if (localImage) localImage.textContent = data.local_image_digest ? `Local digest: ${data.local_image_digest}` : 'Local digest: ยังอ่านไม่ได้';
      if (image) {
        const local = data.local_image_digest || '';
        image.textContent = data.remote_image_digest ? `Remote latest: ${data.remote_image_digest}${local ? (data.remote_image_digest === local ? ' — ตรงกับ latest' : ' — มี image ใหม่') : ''}` : 'Remote latest: ตรวจไม่สำเร็จ';
      }
      status.textContent = 'ตรวจรุ่นล่าสุดเบื้องหลังเสร็จแล้ว';
    })
    .catch((err) => { status.textContent = `ตรวจรุ่นล่าสุดเบื้องหลังไม่สำเร็จ: ${err}`; });
})();
