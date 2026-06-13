/* ── JARVIS Web UI – HUD + Live-Sync ────────────────────────────────── */

// ── State ──
let isMuted = false;
let voiceListening = false;
let chatHistory = [];
const MAX_LOG = 200;

// ── DOM refs ──
const $ = s => document.querySelector(s);
const $$ = s => document.querySelectorAll(s);

// ── Clock ──
function tickClock() {
  const d = new Date();
  const days = ['So','Mo','Di','Mi','Do','Fr','Sa'];
  const months = ['Jan','Feb','Mär','Apr','Mai','Jun','Jul','Aug','Sep','Okt','Nov','Dez'];
  $('#clock').textContent = d.toLocaleTimeString('de-DE', {hour:'2-digit',minute:'2-digit'});
  $('#clock-date').textContent = `${days[d.getDay()]} ${d.getDate()} ${months[d.getMonth()]} ${d.getFullYear()}`;
}
setInterval(tickClock, 1000);
tickClock();

// ── Log ──
function addLog(text, type = 'sys') {
  const log = $('#log');
  const div = document.createElement('div');
  div.className = `log-line log-${type}`;
  div.textContent = text;
  log.appendChild(div);
  log.scrollTop = log.scrollHeight;
  // Prune
  while (log.children.length > MAX_LOG) log.removeChild(log.firstChild);
}

function setState(state) {
  const lbl = $('#state-label');
  const sub = $('#state-sub');
  lbl.className = '';
  switch(state) {
    case 'LISTENING':
      lbl.textContent = 'LISTENING';
      lbl.classList.add('state-listening');
      sub.textContent = 'Bereit für Befehle';
      break;
    case 'THINKING':
      lbl.textContent = 'THINKING';
      lbl.classList.add('state-thinking');
      sub.textContent = 'Verarbeite Anfrage...';
      break;
    case 'SPEAKING':
      lbl.textContent = 'SPEAKING';
      lbl.classList.add('state-speaking');
      sub.textContent = 'Antworte...';
      break;
    case 'PROCESSING':
      lbl.textContent = 'PROCESSING';
      lbl.classList.add('state-processing');
      sub.textContent = 'Führe Aktion aus...';
      break;
    default:
      lbl.textContent = state;
      sub.textContent = '';
  }
}

function setAutopilot(active) {
  $('#ap-label').textContent = active ? 'AUTOPILOT' : '';
}

// ── Chat ──
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
    const r = await fetch('/api/chat', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({message: text}),
    });
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
  } catch (e) {
    addLog('✗ Verbindungsfehler: ' + e.message, 'sys');
    setState('LISTENING');
  }
}

// ── File Drop (simuliert) ──
const fileZone = $('#file-zone');
fileZone.addEventListener('dragover', e => { e.preventDefault(); fileZone.classList.add('dragover'); });
fileZone.addEventListener('dragleave', () => fileZone.classList.remove('dragover'));
fileZone.addEventListener('drop', e => {
  e.preventDefault();
  fileZone.classList.remove('dragover');
  const files = e.dataTransfer.files;
  if (files.length) {
    const name = files[0].name;
    $('#file-name').textContent = name;
    addLog(`📎 ${name} (${(files[0].size/1024).toFixed(1)} KB)`, 'tool');
  }
});

// ── Mic Mute ──
const muteBtn = $('#mute-btn');
muteBtn.addEventListener('click', () => {
  isMuted = !isMuted;
  muteBtn.classList.toggle('muted', isMuted);
  muteBtn.textContent = isMuted ? '🔇' : '🎤';
  addLog(isMuted ? '🔇 Mikrofon stumm' : '🎤 Mikrofon aktiv', 'sys');
});

// ── Enter to send ──
$('#text-input').addEventListener('keydown', e => {
  if (e.key === 'Enter') send();
});

// ── Send button ──
$('#send-btn').addEventListener('click', send);

// ── SpeechRecognition (Browser API) ──
const SpeechRecognition = window.SpeechRecognition || window.webkitSpeechRecognition;
let recognition = null;
let voiceListening = false;

function stopVoice() {
  voiceListening = false;
  const btn = $('#voice-btn');
  btn.classList.remove('recording'); btn.textContent = '🎤';
  if (recognition) { try { recognition.abort(); } catch(_) {} recognition = null; }
}

function startVoice() {
  if (!SpeechRecognition) { alert('Spracherkennung wird von diesem Browser nicht unterstützt.'); return; }
  voiceListening = true;
  const btn = $('#voice-btn');
  btn.classList.add('recording'); btn.textContent = '⏹';
  recognition = new SpeechRecognition();
  recognition.lang = 'de-DE';
  recognition.continuous = false;
  recognition.interimResults = false;
  recognition.onresult = e => {
    const transcript = e.results[0][0].transcript;
    if (transcript) {
      $('#text-input').value = transcript;
      send();
    }
    stopVoice();
  };
  recognition.onerror = () => { stopVoice(); };
  recognition.onend = () => { if (voiceListening) stopVoice(); };
  recognition.start();
}

$('#voice-btn')?.addEventListener('click', () => {
  if (voiceListening) stopVoice();
  else startVoice();
});

// ── SpeechSynthesis (vorlesen) ──
let synth = window.speechSynthesis;
function speakResponse(text) {
  if (!synth || !text) return;
  synth.cancel();
  const utter = new SpeechSynthesisUtterance(text);
  utter.lang = 'de-DE';
  utter.rate = 0.95;
  utter.pitch = 1.0;
  // deutsche Stimme bevorzugen (mit fallback für asynchrone Stimmen-Ladung)
  const tryVoice = () => {
    const voices = synth.getVoices();
    const de = voices.find(v => v.lang.startsWith('de'));
    if (de) utter.voice = de;
    synth.speak(utter);
  };
  const voices = synth.getVoices();
  if (voices.length) tryVoice();
  else { synth.onvoiceschanged = tryVoice; }
}

// ── Live-Sync via SSE ──
function connectSSE() {
  const es = new EventSource('/api/stream');
  es.onmessage = e => {
    try {
      const data = JSON.parse(e.data);
      if (data.state) setState(data.state);
      if (data.logs && data.logs.length) {
        data.logs.forEach(log => addLog(log.text, log.text.startsWith('Du:') ? 'user' : log.text.startsWith('Jarvis:') ? 'jarvis' : 'sys'));
      }
    } catch(_) {}
  };
  es.onerror = () => { es.close(); setTimeout(connectSSE, 3000); };
}
connectSSE();

// ── Initial State laden ──
async function loadSyncState() {
  try {
    const r = await fetch('/api/sync-logs');
    const data = await r.json();
    if (data.state) setState(data.state);
    if (data.logs && data.logs.length) {
      data.logs.forEach(log => addLog(log.text, 'sys'));
    }
  } catch(_) {}
}
loadSyncState();

// ── Settings ── (unchanged from original, simplified)
function toggleSettings() {
  const overlay = $('#settings-overlay');
  overlay.classList.toggle('hidden');
  if (!overlay.classList.contains('hidden')) loadConfig();
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
    const r = await fetch('/api/config');
    const cfg = await r.json();
    $('#s-user-name').value = cfg.user_name || 'Sir';
    const kr = await fetch('/api/key');
    const kd = await kr.json();
    $('#s-api-key').value = kd.key || '';
    const er = await fetch('/api/config/email');
    const accounts = await er.json();
    const el = $('#s-email-list'); el.innerHTML = '';
    (accounts.length ? accounts : [{}]).forEach((a, i) => addEmailRow(a.name, a.email, a.password, a.imap_server, a.smtp_server, a.smtp_port, i));
    const jr = await fetch('/api/config/jds');
    const jds = await jr.json();
    $('#s-jds-url').value = jds.base_url || '';
    $('#s-jds-team').value = jds.team_code || '';
    $('#s-jds-token').value = jds.api_token || '';
    const sr = await fetch('/api/config/sites');
    const sites = await sr.json();
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
  const r = await fetch('/api/config', {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({user_name: name || 'Sir'})});
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
    const url = row.querySelector('.s-url').value.trim();
    if (!name || !url) return;
    const pagesStr = row.querySelector('.s-pages').value.trim();
    sites.push({name, url: url.replace(/\/+$/,''), login_path: row.querySelector('.s-login').value.trim(), username: row.querySelector('.s-user').value.trim(), password: row.querySelector('.s-pw').value, pages: pagesStr ? pagesStr.split(/\s+/) : []});
  });
  const r = await fetch('/api/config/sites', {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({sites})});
  const d = await r.json();
  showSettingsMsg(d.ok ? 'Wissensseiten gespeichert' : d.error, !d.ok);
}

// ── Metrics (simulierte Werte für Web) ──
function updateMetrics() {
  function rnd(min,max) { return Math.random() * (max-min) + min; }
  function setMetric(id, label, pct, val, color) {
    const el = document.getElementById(id);
    if (!el) return;
    el.querySelector('.m-label').textContent = label;
    el.querySelector('.m-fill').style.width = Math.min(100, pct) + '%';
    el.querySelector('.m-val').textContent = val;
  }
  setMetric('m-cpu', 'CPU', rnd(5,35), `${Math.round(rnd(5,35))}%`, 'var(--pri)');
  setMetric('m-ram', 'RAM', rnd(40,75), `${Math.round(rnd(40,75))}%`, 'var(--acc)');
  setMetric('m-net', 'NET', rnd(0,20), `${Math.round(rnd(0,5))}MB/s`, 'var(--green)');
  setMetric('m-gpu', 'GPU', rnd(0,30), `${Math.round(rnd(0,30))}%`, 'var(--acc2)');
  setMetric('m-tmp', 'TMP', rnd(35,65), `${Math.round(rnd(35,65))}°C`, 'var(--red)');
}
setInterval(updateMetrics, 3000);
updateMetrics();
