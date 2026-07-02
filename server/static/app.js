/* ── JARVIS Web UI – HUD + Live-Sync + Auth ──────────────────────────── */

// ── State ──
let isMuted = false;
let chatHistory = [];
let _authToken = localStorage.getItem('jarvis_token') || '';
let _authUser  = localStorage.getItem('jarvis_user') || '';
let _authRole  = localStorage.getItem('jarvis_role') || '';
const MAX_LOG = 200;

const $ = s => document.querySelector(s);
const $$ = s => document.querySelectorAll(s);

// ── Auth helpers ──────────────────────────────────────────────────────────

function authHeader() {
  return _authToken ? {'Authorization': 'Bearer ' + _authToken} : {};
}

async function apiFetch(url, opts = {}) {
  opts.headers = Object.assign({}, opts.headers || {}, authHeader());
  const r = await fetch(url, opts);
  if (r.status === 401) { showAuthScreen(); return null; }
  return r;
}

function showAuthScreen() {
  _authToken = _authUser = _authRole = '';
  localStorage.removeItem('jarvis_token');
  localStorage.removeItem('jarvis_user');
  localStorage.removeItem('jarvis_role');
  $('#app').classList.add('hidden');
  $('#auth-screen').classList.remove('hidden');
}

function showApp(username, role) {
  _authUser = username;
  _authRole = role;
  $('#auth-screen').classList.add('hidden');
  $('#app').classList.remove('hidden');
  $('#user-badge').textContent = '👤 ' + username + (role === 'admin' ? ' ★' : '');
  if (role === 'admin') $('#admin-section')?.classList.remove('hidden');
  initApp();
}

// ── Tab switcher ──────────────────────────────────────────────────────────

function authTab(tab) {
  $('#form-login').classList.toggle('hidden', tab !== 'login');
  $('#form-register').classList.toggle('hidden', tab !== 'register');
  $('#tab-login').classList.toggle('active', tab === 'login');
  $('#tab-register').classList.toggle('active', tab === 'register');
  $('#auth-msg').textContent = '';
}

function setAuthMsg(msg, isError) {
  const el = $('#auth-msg');
  el.textContent = msg;
  el.style.color = isError ? '#ff4444' : '#00ff88';
}

// ── Login ──────────────────────────────────────────────────────────────────

async function doLogin() {
  const username = $('#login-user').value.trim();
  const password = $('#login-pass').value;
  if (!username || !password) return setAuthMsg('Bitte alle Felder ausfüllen.', true);

  setAuthMsg('Anmeldung...', false);
  try {
    const r = await fetch('/api/auth/login', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({username, password}),
    });
    const d = await r.json();
    if (d.ok) {
      _authToken = d.token;
      localStorage.setItem('jarvis_token', d.token);
      localStorage.setItem('jarvis_user', d.username);
      localStorage.setItem('jarvis_role', d.role);
      showApp(d.username, d.role);
    } else {
      setAuthMsg(d.error || 'Fehler beim Anmelden.', true);
    }
  } catch(e) {
    setAuthMsg('Verbindungsfehler.', true);
  }
}

// ── Register ───────────────────────────────────────────────────────────────

async function doRegister() {
  const license_key = $('#reg-key').value.trim();
  const username    = $('#reg-user').value.trim();
  const password    = $('#reg-pass').value;
  if (!license_key || !username || !password) return setAuthMsg('Alle Felder erforderlich.', true);

  setAuthMsg('Konto wird erstellt...', false);
  try {
    const r = await fetch('/api/auth/register', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({license_key, username, password}),
    });
    const d = await r.json();
    if (d.ok) {
      _authToken = d.token;
      localStorage.setItem('jarvis_token', d.token);
      localStorage.setItem('jarvis_user', d.username);
      localStorage.setItem('jarvis_role', d.role);
      showApp(d.username, d.role);
    } else {
      setAuthMsg(d.error || 'Registrierung fehlgeschlagen.', true);
    }
  } catch(e) {
    setAuthMsg('Verbindungsfehler.', true);
  }
}

// ── Logout ─────────────────────────────────────────────────────────────────

async function doLogout() {
  await fetch('/api/auth/logout', {method:'POST', headers: authHeader()}).catch(()=>{});
  showAuthScreen();
}

// Enter-key support for auth forms
document.addEventListener('keydown', e => {
  if (e.key !== 'Enter') return;
  if (!$('#auth-screen').classList.contains('hidden')) {
    if (!$('#form-login').classList.contains('hidden')) doLogin();
    else doRegister();
  }
});

// ── App init ───────────────────────────────────────────────────────────────

function initApp() {
  tickClock();
  loadSyncState();
  connectSSE();
  updateMetrics();
  setInterval(tickClock, 1000);
  setInterval(updateMetrics, 3000);

  // bind send
  $('#send-btn').addEventListener('click', send);
  $('#text-input').addEventListener('keydown', e => { if (e.key === 'Enter') send(); });
  $('#mute-btn').addEventListener('click', () => {
    isMuted = !isMuted;
    $('#mute-btn').classList.toggle('muted', isMuted);
    $('#mute-btn').textContent = isMuted ? '🔇' : '🎤';
    addLog(isMuted ? '🔇 Mikrofon stumm' : '🎤 Mikrofon aktiv', 'sys');
  });

  const fileZone = $('#file-zone');
  fileZone.addEventListener('dragover', e => { e.preventDefault(); fileZone.classList.add('dragover'); });
  fileZone.addEventListener('dragleave', () => fileZone.classList.remove('dragover'));
  fileZone.addEventListener('drop', e => {
    e.preventDefault();
    fileZone.classList.remove('dragover');
    const files = e.dataTransfer.files;
    if (files.length) { $('#file-name').textContent = files[0].name; addLog(`📎 ${files[0].name}`, 'tool'); }
  });
}

// ── Clock ──────────────────────────────────────────────────────────────────

function tickClock() {
  const d = new Date();
  const days   = ['So','Mo','Di','Mi','Do','Fr','Sa'];
  const months = ['Jan','Feb','Mär','Apr','Mai','Jun','Jul','Aug','Sep','Okt','Nov','Dez'];
  const clk = $('#clock'); if (clk) clk.textContent = d.toLocaleTimeString('de-DE', {hour:'2-digit',minute:'2-digit'});
  const dt = $('#clock-date'); if (dt) dt.textContent = `${days[d.getDay()]} ${d.getDate()} ${months[d.getMonth()]} ${d.getFullYear()}`;
}

// ── Log ────────────────────────────────────────────────────────────────────

function addLog(text, type = 'sys') {
  const log = $('#log');
  if (!log) return;
  const div = document.createElement('div');
  div.className = `log-line log-${type}`;
  div.textContent = text;
  log.appendChild(div);
  log.scrollTop = log.scrollHeight;
  while (log.children.length > MAX_LOG) log.removeChild(log.firstChild);
}

function setState(state) {
  const lbl = $('#state-label');
  const sub = $('#state-sub');
  if (!lbl) return;
  lbl.className = '';
  switch(state) {
    case 'LISTENING':  lbl.textContent='LISTENING';  lbl.classList.add('state-listening');  sub.textContent='Bereit für Befehle'; break;
    case 'THINKING':   lbl.textContent='THINKING';   lbl.classList.add('state-thinking');   sub.textContent='Verarbeite Anfrage...'; break;
    case 'SPEAKING':   lbl.textContent='SPEAKING';   lbl.classList.add('state-speaking');   sub.textContent='Antworte...'; break;
    case 'PROCESSING': lbl.textContent='PROCESSING'; lbl.classList.add('state-processing'); sub.textContent='Führe Aktion aus...'; break;
    default: lbl.textContent=state; sub.textContent='';
  }
}

// ── Chat ───────────────────────────────────────────────────────────────────

async function send() {
  const input = $('#text-input');
  const text = input.value.trim();
  if (!text) return;
  input.value = '';
  addLog(text, 'user');
  chatHistory.push({role:'user', text});
  setState('THINKING');
  addLog('⟫ JARVIS denkt nach...', 'tool');

  try {
    const r = await apiFetch('/api/chat', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({message: text}),
    });
    if (!r) return;
    const data = await r.json();
    if (data.error) {
      addLog('✗ ' + data.error, 'sys');
      setState('LISTENING');
    } else {
      const resp = data.response || '(keine Antwort)';
      addLog(resp, 'jarvis');
      chatHistory.push({role:'jarvis', text: resp});
      speakResponse(resp);
      setState('LISTENING');
    }
  } catch(e) {
    addLog('✗ Verbindungsfehler: ' + e.message, 'sys');
    setState('LISTENING');
  }
}

// ── Speech Synthesis ───────────────────────────────────────────────────────

const synth = window.speechSynthesis;
function speakResponse(text) {
  if (!synth || !text) return;
  synth.cancel();
  const utter = new SpeechSynthesisUtterance(text);
  utter.lang = 'de-DE'; utter.rate = 0.95; utter.pitch = 1.0;
  const tryVoice = () => {
    const voices = synth.getVoices();
    const de = voices.find(v => v.lang.startsWith('de'));
    if (de) utter.voice = de;
    synth.speak(utter);
  };
  if (synth.getVoices().length) tryVoice();
  else synth.onvoiceschanged = tryVoice;
}

// ── Live-Sync SSE ──────────────────────────────────────────────────────────

function connectSSE() {
  const es = new EventSource('/api/stream');
  es.onmessage = e => {
    try {
      const data = JSON.parse(e.data);
      if (data.state) setState(data.state);
      if (data.logs) data.logs.forEach(log => addLog(log.text, log.text.startsWith('Du:') ? 'user' : log.text.startsWith('Jarvis:') ? 'jarvis' : 'sys'));
    } catch(_) {}
  };
  es.onerror = () => { es.close(); setTimeout(connectSSE, 3000); };
}

async function loadSyncState() {
  try {
    const r = await fetch('/api/sync-logs');
    const data = await r.json();
    if (data.state) setState(data.state);
    if (data.logs) data.logs.forEach(log => addLog(log.text, 'sys'));
  } catch(_) {}
}

// ── Settings ───────────────────────────────────────────────────────────────

function toggleSettings() {
  const overlay = $('#settings-overlay');
  overlay.classList.toggle('hidden');
  if (!overlay.classList.contains('hidden')) { loadConfig(); if (_authRole === 'admin') adminLoadKeys(); }
}
function closeSettings(e) { if (e.target === e.currentTarget) toggleSettings(); }

function esc(s) { if (!s) return ''; return String(s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;'); }

let settingsMsgTimer = null;
function showSettingsMsg(msg, isError) {
  const el = $('#settings-msg');
  el.textContent = msg;
  el.style.color = isError ? 'var(--red)' : 'var(--green)';
  el.classList.remove('hidden');
  clearTimeout(settingsMsgTimer);
  settingsMsgTimer = setTimeout(() => el.classList.add('hidden'), 3000);
}

async function loadConfig() {
  try {
    const h = {'Content-Type': 'application/json', ...authHeader()};
    const cfg = await (await apiFetch('/api/config')).json();
    $('#s-user-name').value = cfg.user_name || 'Sir';
    const kd = await (await fetch('/api/key')).json();
    $('#s-api-key').value = kd.key || '';
    const accounts = await (await fetch('/api/config/email')).json();
    const el = $('#s-email-list'); el.innerHTML = '';
    (accounts.length ? accounts : [{}]).forEach((a, i) => addEmailRow(a.name, a.email, a.password, a.imap_server, a.smtp_server, a.smtp_port, i));
    const jds = await (await fetch('/api/config/jds')).json();
    $('#s-jds-url').value = jds.base_url || '';
    $('#s-jds-team').value = jds.team_code || '';
    $('#s-jds-token').value = jds.api_token || '';
    const sites = await (await fetch('/api/config/sites')).json();
    const sl = $('#s-sites-list'); sl.innerHTML = '';
    (sites.length ? sites : []).forEach(s => addSiteRow(s.name, s.url, s.login_path, s.username, s.password, s.pages || []));
  } catch(e) { console.error('Config load error:', e); }
}

async function saveApiKey() {
  const key = $('#s-api-key').value.trim();
  if (!key) return showSettingsMsg('Bitte Key eingeben', true);
  const r = await fetch('/api/key', {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({key})});
  const d = await r.json();
  showSettingsMsg(d.ok ? 'API-Key gespeichert' : d.error, !d.ok);
}

async function saveUserName() {
  const name = $('#s-user-name').value.trim();
  const r = await apiFetch('/api/config', {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({user_name: name || 'Sir'})});
  const d = await r.json();
  showSettingsMsg(d.ok ? 'Name gespeichert' : d.error, !d.ok);
}

function addEmailRow(name, email, password, imap, smtp, port, replaceIndex) {
  const list = $('#s-email-list');
  const row = document.createElement('div'); row.className = 'email-row';
  row.dataset.index = replaceIndex !== undefined ? replaceIndex : list.children.length;
  row.innerHTML = `<div class="row"><input class="em-name" placeholder="Name" value="${esc(name||'')}"><input class="em-email" placeholder="E-Mail" value="${esc(email||'')}"><input class="em-pw" type="password" placeholder="Passwort" value="${esc(password||'')}"><button class="rm-btn" onclick="this.closest('.email-row').remove()">✕</button></div><div class="row"><input class="em-imap" placeholder="IMAP-Server" value="${esc(imap||'imap.gmail.com')}"><input class="em-smtp" placeholder="SMTP-Server" value="${esc(smtp||'smtp.gmail.com')}"><input class="em-port" placeholder="Port" value="${port||'587'}" style="max-width:70px"></div>`;
  list.appendChild(row);
}

async function saveEmail() {
  const rows = $$('#s-email-list .email-row');
  const accounts = [];
  rows.forEach(row => {
    const name = row.querySelector('.em-name').value.trim();
    const email = row.querySelector('.em-email').value.trim();
    if (!name || !email) return;
    accounts.push({name, email, password: row.querySelector('.em-pw').value, imap_server: row.querySelector('.em-imap').value || 'imap.gmail.com', smtp_server: row.querySelector('.em-smtp').value || 'smtp.gmail.com', smtp_port: parseInt(row.querySelector('.em-port').value) || 587});
  });
  const r = await fetch('/api/config/email', {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({accounts})});
  const d = await r.json();
  showSettingsMsg(d.ok ? 'E-Mails gespeichert' : d.error, !d.ok);
}

async function saveJDS() {
  const data = {base_url: $('#s-jds-url').value.trim(), team_code: $('#s-jds-team').value.trim(), api_token: $('#s-jds-token').value.trim()};
  const r = await fetch('/api/config/jds', {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify(data)});
  const d = await r.json();
  showSettingsMsg(d.ok ? 'JDS gespeichert' : d.error, !d.ok);
}

function addSiteRow(name, url, loginPath, username, password, pages) {
  const list = $('#s-sites-list');
  const row = document.createElement('div'); row.className = 'site-row';
  row.innerHTML = `<div class="row"><input class="s-name" placeholder="Name" value="${esc(name||'')}"><input class="s-url" placeholder="URL" value="${esc(url||'')}"><button class="rm-btn" onclick="this.closest('.site-row').remove()">✕</button></div><div class="row"><input class="s-login" placeholder="Login-Pfad" value="${esc(loginPath||'')}"><input class="s-user" placeholder="Benutzername" value="${esc(username||'')}"><input class="s-pw" type="password" placeholder="Passwort" value="${esc(password||'')}"></div><div class="row"><input class="s-pages" placeholder="Seiten (durch Leerzeichen getrennt)" value="${esc((pages||[]).join(' '))}"></div>`;
  list.appendChild(row);
}

async function saveSites() {
  const rows = $$('#s-sites-list .site-row');
  const sites = [];
  rows.forEach(row => {
    const name = row.querySelector('.s-name').value.trim();
    const url  = row.querySelector('.s-url').value.trim();
    if (!name || !url) return;
    const pagesStr = row.querySelector('.s-pages').value.trim();
    sites.push({name, url: url.replace(/\/+$/,''), login_path: row.querySelector('.s-login').value.trim(), username: row.querySelector('.s-user').value.trim(), password: row.querySelector('.s-pw').value, pages: pagesStr ? pagesStr.split(/\s+/) : []});
  });
  const r = await fetch('/api/config/sites', {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({sites})});
  const d = await r.json();
  showSettingsMsg(d.ok ? 'Wissensseiten gespeichert' : d.error, !d.ok);
}

// ── Admin: Lizenzen ────────────────────────────────────────────────────────

async function adminLoadKeys() {
  const container = $('#admin-keys-list');
  if (!container) return;
  try {
    const r = await apiFetch('/api/admin/licenses');
    if (!r) return;
    const keys = await r.json();
    if (!keys.length) { container.innerHTML = '<span style="color:var(--text-dim)">Keine Schlüssel vorhanden.</span>'; return; }
    container.innerHTML = keys.map(k => `
      <div class="key-row" style="display:flex;align-items:center;gap:6px;padding:3px 0;border-bottom:1px solid var(--border)">
        <code style="flex:1;color:var(--pri);font-size:10px;word-break:break-all">${esc(k.key)}</code>
        <span style="color:var(--text-dim);white-space:nowrap">${k.uses}/${k.max_uses}</span>
        <span style="color:${k.active ? 'var(--green)' : 'var(--red)'};font-size:10px">${k.active ? '●' : '○'}</span>
        ${k.label ? `<span style="color:var(--text-med);font-size:10px">${esc(k.label)}</span>` : ''}
        <button class="rm-btn" onclick="adminRevokeKey('${esc(k.key)}')">✕</button>
      </div>`).join('');
  } catch(e) { container.innerHTML = '<span style="color:var(--red)">Fehler beim Laden.</span>'; }
}

async function adminCreateKey() {
  const maxUses = parseInt($('#s-lic-uses').value) || 20;
  const label   = $('#s-lic-label').value.trim();
  const r = await apiFetch('/api/admin/licenses', {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({max_uses: maxUses, label}),
  });
  if (!r) return;
  const d = await r.json();
  if (d.ok) {
    showSettingsMsg('Schlüssel: ' + d.key, false);
    adminLoadKeys();
  } else {
    showSettingsMsg(d.error || 'Fehler', true);
  }
}

async function adminRevokeKey(key) {
  if (!confirm('Schlüssel deaktivieren: ' + key + '?')) return;
  const r = await apiFetch('/api/admin/licenses/' + encodeURIComponent(key), {method:'DELETE'});
  if (!r) return;
  adminLoadKeys();
}

// ── Metrics ────────────────────────────────────────────────────────────────

function updateMetrics() {
  function rnd(min,max) { return Math.random() * (max-min) + min; }
  function setMetric(id, pct, val) {
    const el = document.getElementById(id);
    if (!el) return;
    el.querySelector('.m-fill').style.width = Math.min(100, pct) + '%';
    el.querySelector('.m-val').textContent = val;
  }
  setMetric('m-cpu', rnd(5,35),  `${Math.round(rnd(5,35))}%`);
  setMetric('m-ram', rnd(40,75), `${Math.round(rnd(40,75))}%`);
  setMetric('m-net', rnd(0,20),  `${Math.round(rnd(0,5))}MB/s`);
  setMetric('m-gpu', rnd(0,30),  `${Math.round(rnd(0,30))}%`);
  setMetric('m-tmp', rnd(35,65), `${Math.round(rnd(35,65))}°C`);
}

// ── Bootstrap ──────────────────────────────────────────────────────────────

(async () => {
  // Gespeicherten Token prüfen
  if (_authToken) {
    try {
      const r = await fetch('/api/auth/me', {headers: {'Authorization': 'Bearer ' + _authToken}});
      if (r.ok) {
        const d = await r.json();
        showApp(d.username, d.role);
        return;
      }
    } catch(_) {}
  }
  showAuthScreen();
})();
