/* ── JARVIS Web UI – App Logic ──────────────────────────────────────── */

let isRecording = false;
let mediaRecorder = null;
let audioChunks = [];

document.addEventListener('DOMContentLoaded', () => {
  loadConfig();
  document.getElementById('text-input').addEventListener('keydown', (e) => {
    if (e.key === 'Enter') send();
  });
});

// ── Chat ──

async function send() {
  const input = document.getElementById('text-input');
  const text = input.value.trim();
  if (!text) return;
  input.value = '';

  addMessage(text, 'user');
  showTyping();

  try {
    const r = await fetch('/api/chat', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({message: text}),
    });
    const data = await r.json();
    removeTyping();
    if (data.error) {
      addMessage('Fehler: ' + data.error, 'jarvis');
    } else {
      addMessage(data.response || '(keine Antwort)', 'jarvis');
      if (data.logs && data.logs.length > 0) {
        console.log('[Tools]', data.logs);
      }
    }
  } catch (e) {
    removeTyping();
    addMessage('Verbindungsfehler: ' + e.message, 'jarvis');
  }
}

function addMessage(text, role) {
  const chat = document.getElementById('chat');
  const div = document.createElement('div');
  div.className = 'msg ' + role;
  const bubble = document.createElement('div');
  bubble.className = 'bubble ' + role;
  bubble.textContent = text;
  div.appendChild(bubble);
  chat.appendChild(div);
  chat.scrollTop = chat.scrollHeight;
}

function showTyping() {
  const chat = document.getElementById('chat');
  const div = document.createElement('div');
  div.className = 'msg jarvis typing';
  div.id = 'typing-indicator';
  const bubble = document.createElement('div');
  bubble.className = 'bubble jarvis';
  bubble.textContent = 'JARVIS denkt nach';
  div.appendChild(bubble);
  chat.appendChild(div);
  chat.scrollTop = chat.scrollHeight;
}

function removeTyping() {
  const el = document.getElementById('typing-indicator');
  if (el) el.remove();
}

async function resetChat() {
  if (!confirm('Chat-Verlauf zurücksetzen?')) return;
  await fetch('/api/reset', {method: 'POST'});
  document.getElementById('chat').innerHTML = `
    <div class="msg welcome">
      <div class="bubble jarvis">JARVIS bereit. Wie kann ich Ihnen helfen?</div>
    </div>`;
}

// ── Voice (Browser Mic) ──

async function toggleVoice() {
  const btn = document.getElementById('voice-btn');
  if (isRecording) {
    if (mediaRecorder && mediaRecorder.state !== 'inactive') {
      mediaRecorder.stop();
    }
    isRecording = false;
    btn.classList.remove('recording');
    btn.textContent = '🎤';
    return;
  }

  try {
    const stream = await navigator.mediaDevices.getUserMedia({audio: true});
    mediaRecorder = new MediaRecorder(stream, {mimeType: 'audio/webm'});
    audioChunks = [];
    isRecording = true;
    btn.classList.add('recording');
    btn.textContent = '⏹';

    mediaRecorder.ondataavailable = (e) => {
      if (e.data.size > 0) audioChunks.push(e.data);
    };

    mediaRecorder.onstop = async () => {
      stream.getTracks().forEach(t => t.stop());
      btn.classList.remove('recording');
      btn.textContent = '🎤';
      isRecording = false;

      if (audioChunks.length === 0) return;
      const blob = new Blob(audioChunks, {type: 'audio/webm'});
      if (blob.size < 1000) return;

      addMessage('🎤 Sprachaufnahme verarbeitet...', 'user');
      showTyping();
      // For now, send as text placeholder
      // TODO: Send audio to server for transcription
      const input = document.getElementById('text-input');
      input.value = '[Sprachnachricht]';
      send();
    };

    mediaRecorder.start();
  } catch (e) {
    alert('Mikrofon-Zugriff verweigert: ' + e.message);
  }
}

// ── Settings ──

function toggleSettings() {
  const overlay = document.getElementById('settings-overlay');
  overlay.classList.toggle('hidden');
  if (!overlay.classList.contains('hidden')) loadConfig();
}

function closeSettings(e) {
  if (e.target === e.currentTarget) toggleSettings();
}

async function loadConfig() {
  try {
    const r = await fetch('/api/config');
    const cfg = await r.json();
    document.getElementById('s-user-name').value = cfg.user_name || 'Sir';

    const kr = await fetch('/api/key');
    const kd = await kr.json();
    document.getElementById('s-api-key').value = kd.key || '';

    // Email
    const er = await fetch('/api/config/email');
    const accounts = await er.json();
    const el = document.getElementById('s-email-list');
    el.innerHTML = '';
    (accounts.length ? accounts : [{}]).forEach((a, i) => {
      addEmailRow(a.name, a.email, a.password, a.imap_server, a.smtp_server, a.smtp_port, i);
    });

    // JDS
    const jr = await fetch('/api/config/jds');
    const jds = await jr.json();
    document.getElementById('s-jds-url').value = jds.base_url || '';
    document.getElementById('s-jds-team').value = jds.team_code || '';
    document.getElementById('s-jds-token').value = jds.api_token || '';

    // Sites
    const sr = await fetch('/api/config/sites');
    const sites = await sr.json();
    const sl = document.getElementById('s-sites-list');
    sl.innerHTML = '';
    (sites.length ? sites : []).forEach(s => {
      addSiteRow(s.name, s.url, s.login_path, s.username, s.password, s.pages || []);
    });
  } catch (e) {
    console.error('Config load error:', e);
  }
}

// ── API Key ──

async function saveApiKey() {
  const key = document.getElementById('s-api-key').value.trim();
  if (!key) return showSettingsMsg('Bitte Key eingeben', true);
  const r = await fetch('/api/key', {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({key}),
  });
  const d = await r.json();
  showSettingsMsg(d.ok ? 'API-Key gespeichert' : d.error, !d.ok);
}

// ── User Name ──

async function saveUserName() {
  const name = document.getElementById('s-user-name').value.trim();
  const r = await fetch('/api/config', {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({user_name: name || 'Sir'}),
  });
  const d = await r.json();
  showSettingsMsg(d.ok ? 'Name gespeichert' : d.error, !d.ok);
}

// ── E-Mail ──

function addEmailRow(name, email, password, imap, smtp, port, replaceIndex) {
  const list = document.getElementById('s-email-list');
  const row = document.createElement('div');
  row.className = 'email-row';
  row.dataset.index = replaceIndex !== undefined ? replaceIndex : list.children.length;
  row.innerHTML = `
    <div class="row">
      <input class="em-name" placeholder="Name" value="${esc(name||'')}">
      <input class="em-email" placeholder="E-Mail" value="${esc(email||'')}">
      <input class="em-pw" type="password" placeholder="Passwort" value="${esc(password||'')}">
      <button class="rm-btn" onclick="this.closest('.email-row').remove()">✕</button>
    </div>
    <div class="row">
      <input class="em-imap" placeholder="IMAP-Server" value="${esc(imap||'imap.gmail.com')}">
      <input class="em-smtp" placeholder="SMTP-Server" value="${esc(smtp||'smtp.gmail.com')}">
      <input class="em-port" placeholder="Port" value="${port||'587'}" style="max-width:70px">
    </div>`;
  list.appendChild(row);
}

async function saveEmail() {
  const rows = document.querySelectorAll('#s-email-list .email-row');
  const accounts = [];
  rows.forEach(row => {
    const name = row.querySelector('.em-name').value.trim();
    const email = row.querySelector('.em-email').value.trim();
    if (!name || !email) return;
    accounts.push({
      name, email,
      password: row.querySelector('.em-pw').value,
      imap_server: row.querySelector('.em-imap').value || 'imap.gmail.com',
      smtp_server: row.querySelector('.em-smtp').value || 'smtp.gmail.com',
      smtp_port: parseInt(row.querySelector('.em-port').value) || 587,
    });
  });
  const r = await fetch('/api/config/email', {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({accounts}),
  });
  const d = await r.json();
  showSettingsMsg(d.ok ? 'E-Mails gespeichert' : d.error, !d.ok);
}

// ── JDS ──

async function saveJDS() {
  const data = {
    base_url: document.getElementById('s-jds-url').value.trim(),
    team_code: document.getElementById('s-jds-team').value.trim(),
    api_token: document.getElementById('s-jds-token').value.trim(),
  };
  const r = await fetch('/api/config/jds', {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify(data),
  });
  const d = await r.json();
  showSettingsMsg(d.ok ? 'JDS gespeichert' : d.error, !d.ok);
}

// ── Knowledge Sites ──

function addSiteRow(name, url, loginPath, username, password, pages) {
  const list = document.getElementById('s-sites-list');
  const row = document.createElement('div');
  row.className = 'site-row';
  row.innerHTML = `
    <div class="row">
      <input class="s-name" placeholder="Name" value="${esc(name||'')}">
      <input class="s-url" placeholder="URL" value="${esc(url||'')}">
      <button class="rm-btn" onclick="this.closest('.site-row').remove()">✕</button>
    </div>
    <div class="row">
      <input class="s-login" placeholder="Login-Pfad" value="${esc(loginPath||'')}">
      <input class="s-user" placeholder="Benutzername" value="${esc(username||'')}">
      <input class="s-pw" type="password" placeholder="Passwort" value="${esc(password||'')}">
    </div>
    <div class="row">
      <input class="s-pages" placeholder="Seiten (durch Leerzeichen getrennt)" value="${esc((pages||[]).join(' '))}">
    </div>`;
  list.appendChild(row);
}

async function saveSites() {
  const rows = document.querySelectorAll('#s-sites-list .site-row');
  const sites = [];
  rows.forEach(row => {
    const name = row.querySelector('.s-name').value.trim();
    const url = row.querySelector('.s-url').value.trim();
    if (!name || !url) return;
    const pagesStr = row.querySelector('.s-pages').value.trim();
    sites.push({
      name, url: url.replace(/\/+$/,''),
      login_path: row.querySelector('.s-login').value.trim(),
      username: row.querySelector('.s-user').value.trim(),
      password: row.querySelector('.s-pw').value,
      pages: pagesStr ? pagesStr.split(/\s+/) : [],
    });
  });
  const r = await fetch('/api/config/sites', {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({sites}),
  });
  const d = await r.json();
  showSettingsMsg(d.ok ? 'Wissensseiten gespeichert' : d.error, !d.ok);
}

// ── Helpers ──

function esc(s) {
  if (!s) return '';
  return String(s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;');
}

let settingsMsgTimer = null;
function showSettingsMsg(msg, isError) {
  const el = document.getElementById('settings-msg');
  el.textContent = msg;
  el.style.color = isError ? 'var(--red)' : 'var(--green)';
  el.classList.remove('hidden');
  clearTimeout(settingsMsgTimer);
  settingsMsgTimer = setTimeout(() => el.classList.add('hidden'), 3000);
}

// Patch: save buttons in settings use the async fns directly
document.addEventListener('click', (e) => {
  if (e.target.matches('#s-email-list ~ .btn') && e.target.textContent.includes('Konto')) {
    // already handled by onclick
  }
});
