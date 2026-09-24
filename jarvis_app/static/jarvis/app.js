/* JARVIS Web-Konsole: Chat, Live-Ereignisse, Benachrichtigungen, Browser-Befehle. */
(function () {
  const J = window.JARVIS;
  const $ = (id) => document.getElementById(id);
  const esc = J.esc;
  J.clientId = (crypto.randomUUID && crypto.randomUUID()) || String(Math.random()).slice(2);

  const els = {
    messages: $("messages"), input: $("input"), composer: $("composer"), send: $("btn-send"),
    log: $("log"), notifications: $("notifications"), files: $("files"), reminders: $("reminders"),
    alarms: $("alarms"), toasts: $("toasts"), state: $("state-label"), caption: $("live-caption"),
    mic: $("btn-mic"), screen: $("btn-screen"), camera: $("btn-camera"), stopAudio: $("btn-stop-audio"),
    stream: $("stream-audio"), attachInfo: $("attach-info"), attachName: $("attach-name"),
  };
  const prefs = {
    tts: $("opt-tts").checked,
  };
  let busy = false, typingEl = null;

  // ── Hilfen ──
  function time(d) { return (d ? new Date(d) : new Date()).toLocaleTimeString("de-DE", { hour: "2-digit", minute: "2-digit" }); }

  function md(text) {
    let s = esc(text);
    s = s.replace(/```(?:\w+)?\n?([\s\S]*?)```/g, (_, c) => `<pre>${c}</pre>`);
    s = s.replace(/`([^`\n]+)`/g, "<code>$1</code>");
    s = s.replace(/\*\*([^*\n]+)\*\*/g, "<b>$1</b>");
    s = s.replace(/(^|\s)\*([^*\n]+)\*(?=\s|$)/g, "$1<i>$2</i>");
    s = s.replace(/(https?:\/\/[^\s<]+[^\s<.,;:!?)])/g, '<a href="$1" target="_blank" rel="noopener">$1</a>');
    s = s.replace(/(?:^|\n)((?:[-*•] .+(?:\n|$))+)/g, (_, block) =>
      "\n<ul>" + block.trim().split("\n").map(l => `<li>${l.replace(/^[-*•] /, "")}</li>`).join("") + "</ul>");
    return s;
  }

  function addMessage(role, text, opts = {}) {
    const empty = els.messages.querySelector(".empty-chat");
    if (empty) empty.remove();
    const el = document.createElement("div");
    el.className = `msg ${role}`;
    const who = role === "user" ? (J.userName || "Du") : "JARVIS";
    const src = opts.source === "voice" ? " · 🎙" : opts.source === "discord" ? " · Discord" : "";
    el.innerHTML = `<div class="meta"><b>${esc(who)}</b><span>${time(opts.at)}${src}</span></div><div class="body">${md(text)}</div>`;
    if (opts.tools && opts.tools.length) {
      const chips = document.createElement("div");
      chips.className = "tool-chips";
      opts.tools.forEach(t => {
        const c = document.createElement("span");
        c.className = "chip";
        c.textContent = "⚙ " + t.name;
        c.title = (t.result || "").slice(0, 300);
        chips.appendChild(c);
      });
      el.appendChild(chips);
    }
    els.messages.appendChild(el);
    els.messages.scrollTop = els.messages.scrollHeight;
    return el;
  }

  function showEmpty() {
    els.messages.innerHTML = `<div class="empty-chat"><h2>WIE KANN ICH HELFEN?</h2>
      <div>Schreib mir, lade eine Datei hoch oder aktiviere den Sprachmodus.</div>
      <div class="suggestions">
        <button>Briefing bitte</button><button>Wie wird das Wetter morgen?</button>
        <button>Welche E-Mails sind ungelesen?</button><button>Stell einen Wecker auf 7:30</button>
        <button>Spiel SWR3 im Radio</button><button>Was siehst du auf meinem Bildschirm?</button>
      </div></div>`;
    els.messages.querySelectorAll(".suggestions button").forEach(b => b.onclick = () => { els.input.value = b.textContent; sendChat(); });
  }

  function logLine(text, cls = "") {
    const d = document.createElement("div");
    d.innerHTML = `<span class="t">${time()}</span><span class="${cls}">${esc(text)}</span>`;
    els.log.appendChild(d);
    while (els.log.children.length > 300) els.log.firstChild.remove();
    els.log.scrollTop = els.log.scrollHeight;
  }

  function setState(s) {
    const labels = { IDLE: "BEREIT", LISTENING: J.voice.active ? "HÖRT ZU" : "BEREIT", THINKING: "DENKT NACH", SPEAKING: "SPRICHT", CONNECTING: "VERBINDE", OFF: "BEREIT" };
    els.state.textContent = labels[s] || s;
    J.reactor.setState(s === "LISTENING" && !J.voice.active ? "IDLE" : s);
  }

  function toast(title, body = "", opts = {}) {
    const t = document.createElement("div");
    t.className = "toast" + (opts.kind === "alarm" ? " alarm" : "");
    t.innerHTML = `<b>${esc(title)}</b><div>${esc(body)}</div>`;
    if (opts.actions) {
      const a = document.createElement("div");
      a.className = "actions";
      opts.actions.forEach(([label, fn, primary]) => {
        const b = document.createElement("button");
        b.className = "btn" + (primary ? " primary" : "");
        b.textContent = label;
        b.onclick = () => { fn(); t.remove(); };
        a.appendChild(b);
      });
      t.appendChild(a);
    }
    els.toasts.appendChild(t);
    setTimeout(() => t.remove(), opts.sticky ? 120000 : 8000);
  }

  // ── Sprachausgabe (Text-Modus) ──
  let germanVoice = null;
  function pickVoice() {
    const voices = speechSynthesis.getVoices();
    germanVoice = voices.find(v => /de(-|_)DE/i.test(v.lang) && /male|mann|stefan|conrad|markus/i.test(v.name))
      || voices.find(v => /^de/i.test(v.lang)) || null;
  }
  if ("speechSynthesis" in window) { pickVoice(); speechSynthesis.onvoiceschanged = pickVoice; }
  function speak(text, force = false) {
    if (!("speechSynthesis" in window) || (!prefs.tts && !force) || J.voice.active) return;
    const clean = String(text).replace(/```[\s\S]*?```/g, "").replace(/[*_`#>]/g, "").replace(/https?:\/\/\S+/g, "Link").slice(0, 1200);
    const u = new SpeechSynthesisUtterance(clean);
    u.lang = "de-DE";
    if (germanVoice) u.voice = germanVoice;
    u.rate = 1.05;
    u.onstart = () => setState("SPEAKING");
    u.onend = () => setState("IDLE");
    speechSynthesis.cancel();
    speechSynthesis.speak(u);
  }

  // ── Audio: Radio/Streams und Wecksignal ──
  let alarmTimer = null, alarmCtx = null;
  function playStream(url, label) {
    stopAudio();
    els.stream.src = url;
    els.stream.play().then(() => {
      els.stopAudio.classList.remove("hidden");
      logLine(`♪ ${label || "Stream"} läuft`, "ok");
    }).catch(() => toast("Audio blockiert", "Der Browser verlangt einen Klick.", {
      actions: [["Abspielen", () => els.stream.play().then(() => els.stopAudio.classList.remove("hidden")), true]], sticky: true }));
  }
  function alarmTone(seconds = 60) {
    stopAudio();
    alarmCtx = new (window.AudioContext || window.webkitAudioContext)();
    const end = Date.now() + seconds * 1000;
    const beep = () => {
      if (Date.now() > end || !alarmCtx) return stopAudio();
      [880, 1100, 1320].forEach((f, i) => {
        const o = alarmCtx.createOscillator(), g = alarmCtx.createGain();
        o.frequency.value = f;
        o.connect(g); g.connect(alarmCtx.destination);
        const t0 = alarmCtx.currentTime + i * 0.22;
        g.gain.setValueAtTime(0.0001, t0);
        g.gain.exponentialRampToValueAtTime(0.35, t0 + 0.02);
        g.gain.exponentialRampToValueAtTime(0.0001, t0 + 0.2);
        o.start(t0); o.stop(t0 + 0.21);
      });
      alarmTimer = setTimeout(beep, 1300);
    };
    beep();
    els.stopAudio.classList.remove("hidden");
  }
  function stopAudio() {
    els.stream.pause();
    els.stream.removeAttribute("src");
    clearTimeout(alarmTimer);
    alarmTimer = null;
    if (alarmCtx) { alarmCtx.close(); alarmCtx = null; }
    if ("speechSynthesis" in window) speechSynthesis.cancel();
    J.voice.stopPlayback();
    els.stopAudio.classList.add("hidden");
  }
  els.stopAudio.onclick = stopAudio;

  function openUrl(url) {
    const w = window.open(url, "_blank", "noopener");
    if (!w) toast("Link öffnen", url, { actions: [["Öffnen", () => window.open(url, "_blank", "noopener"), true]], sticky: true });
    logLine(`↗ ${url}`, "tool");
  }

  // ── Browser-Benachrichtigungen ──
  const notifyToggle = $("opt-notify");
  notifyToggle.checked = "Notification" in window && Notification.permission === "granted";
  notifyToggle.onchange = async () => {
    if (!("Notification" in window)) { notifyToggle.checked = false; return toast("Nicht unterstützt", "Dieser Browser kann keine Benachrichtigungen."); }
    if (notifyToggle.checked) notifyToggle.checked = (await Notification.requestPermission()) === "granted";
  };
  function systemNotify(title, body) {
    if ("Notification" in window && Notification.permission === "granted" && document.hidden) {
      try { new Notification(title, { body, icon: "/static/jarvis/icon.svg" }); } catch (e) {}
    }
  }

  // ── Events-WebSocket ──
  let evWs = null, evRetry = 1000;
  function connectEvents() {
    evWs = new WebSocket(`${location.protocol === "https:" ? "wss" : "ws"}://${location.host}/ws/events/?cid=${encodeURIComponent(J.clientId)}`);
    evWs.binaryType = "arraybuffer";
    evWs.onopen = () => { evRetry = 1000; };
    evWs.onmessage = (e) => handleEvent(JSON.parse(e.data));
    evWs.onclose = () => { setTimeout(connectEvents, evRetry); evRetry = Math.min(evRetry * 2, 15000); };
  }
  J.events = {
    send(obj) { if (evWs && evWs.readyState === 1) evWs.send(JSON.stringify(obj)); },
    sendBinary(buf) { if (evWs && evWs.readyState === 1) evWs.send(buf); },
  };
  setInterval(() => J.events.send({ type: "ping", t: Date.now() }), 25000);

  function setAgent(a) {
    $("agent-dot").className = "dot" + (a.connected ? " ok" : "");
    $("agent-label").textContent = a.connected ? `PC: ${a.host || "verbunden"}` : "PC offline";
    $("agent-hint").classList.toggle("hidden", !!a.connected);
    $("pc-metrics").classList.toggle("hidden", !a.connected);
    if (a.metrics) setMetrics(a.metrics);
  }
  function bar(id, barId, val, suffix = "%") {
    if (val === undefined || val === null) return;
    $(id).textContent = Math.round(val) + suffix;
    $(barId).style.width = Math.max(0, Math.min(100, val)) + "%";
  }
  function setMetrics(m) {
    bar("m-cpu", "b-cpu", m.cpu);
    bar("m-ram", "b-ram", m.ram);
    $("battery-row").classList.toggle("hidden", m.battery === undefined || m.battery === null);
    bar("m-bat", "b-bat", m.battery);
  }

  function handleEvent(m) {
    switch (m.type) {
      case "hello":
        setAgent(m.agent || {});
        if (m.sync && m.sync.logs) m.sync.logs.forEach(l => logLine(`[Desktop] ${l.text}`, "sync"));
        break;
      case "log": logLine(m.text); break;
      case "tool":
        if (m.phase === "start") { logLine(`⚙ ${m.name} ${JSON.stringify(m.args || {}).slice(0, 120)}`, "tool"); setState("THINKING"); }
        else logLine(`✓ ${m.name} (${m.ms} ms) → ${(m.result || "").slice(0, 160)}`, /fehl|error|nicht verfügbar/i.test(m.result) ? "err" : "ok");
        break;
      case "state": setState(m.state === "LISTENING" && !J.voice.active ? "IDLE" : m.state); break;
      case "speak": speak(m.text, true); logLine(`🗣 ${m.text}`); break;
      case "agent": setAgent(m); logLine(m.connected ? `🖥 Desktop-Agent verbunden (${m.host})` : "🖥 Desktop-Agent getrennt", m.connected ? "ok" : "err"); break;
      case "metrics": setMetrics(m.metrics || {}); break;
      case "autopilot": { const t = $("opt-autopilot"); if (t) t.checked = !!m.active; break; }
      case "refresh": if (m.what === "alarms") loadAlarms(); if (m.what === "reminders") loadReminders(); break;
      case "sync": if (m.log) logLine(`[Desktop] ${m.log.text}`, "sync"); break;
      case "notification": onNotification(m); break;
      case "command": onCommand(m); break;
    }
  }

  function onNotification(n) {
    loadNotifications();
    if (n.kind === "reminder") loadReminders();
    const isAlarm = n.kind === "alarm";
    if (isAlarm) {
      if (n.data && n.data.stream) playStream(n.data.stream, "Wecker-Radio"); else alarmTone();
      loadAlarms();
    }
    toast(n.title, n.body, { kind: n.kind, sticky: isAlarm, actions: isAlarm ? [["Aus", stopAudio, true]] : null });
    systemNotify(n.title, n.body);
    if (n.speak && !isAlarm) speak(n.speak, true);
  }

  function onCommand(c) {
    switch (c.command) {
      case "open_url": openUrl(c.url); break;
      case "play_stream": playStream(c.url, c.label); break;
      case "alarm_tone": alarmTone(20); break;
      case "stop_audio": stopAudio(); break;
      case "voice_stop": if (J.voice.active) J.voice.stop(); break;
      case "request_share":
        toast("JARVIS möchte sehen", c.angle === "camera" ? "Kamera freigeben?" : "Bildschirm freigeben?", {
          sticky: true, actions: [["Freigeben", () => toggleShare(c.angle === "camera" ? "camera" : "screen"), true], ["Später", () => {}]] });
        break;
    }
  }

  // ── Chat ──
  async function sendChat() {
    const text = els.input.value.trim();
    if (!text || busy) return;
    els.input.value = "";
    autosize();
    addMessage("user", text);
    busy = true;
    els.send.disabled = true;
    typingEl = document.createElement("div");
    typingEl.className = "typing";
    typingEl.textContent = "JARVIS ARBEITET";
    els.messages.appendChild(typingEl);
    els.messages.scrollTop = els.messages.scrollHeight;
    try {
      const r = await J.api("/api/chat", { method: "POST", body: { message: text, client_id: J.clientId } });
      addMessage("model", r.response, { tools: r.tools });
      speak(r.response);
    } catch (e) {
      addMessage("model", "⚠ " + e.message);
    } finally {
      typingEl && typingEl.remove();
      busy = false;
      els.send.disabled = false;
      setState("IDLE");
      loadFiles();
    }
  }
  els.composer.onsubmit = (e) => { e.preventDefault(); sendChat(); };
  els.input.addEventListener("keydown", (e) => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); sendChat(); } });
  function autosize() { els.input.style.height = "auto"; els.input.style.height = Math.min(160, els.input.scrollHeight) + "px"; }
  els.input.addEventListener("input", autosize);

  async function loadHistory() {
    const r = await J.api("/api/history");
    els.messages.innerHTML = "";
    if (!r.messages.length) return showEmpty();
    r.messages.forEach(m => addMessage(m.role, m.text, { tools: m.tools, at: m.created_at, source: m.source }));
  }

  // ── Sprachmodus ──
  let liveUser = null, liveModel = null;
  els.mic.onclick = () => (J.voice.active ? J.voice.stop() : J.voice.start());
  $("reactor").onclick = () => els.mic.click();
  J.voice.on("active", (on) => {
    els.mic.classList.toggle("on", on);
    els.mic.querySelector("span").textContent = on ? "Beenden" : "Sprechen";
    if ("speechSynthesis" in window) speechSynthesis.cancel();
    if (!on) { els.caption.textContent = ""; setState("IDLE"); }
  });
  J.voice.on("state", (m) => {
    setState(m.state);
    if (m.state === "LISTENING" && m.wake_mode !== undefined)
      els.caption.textContent = m.wake_mode ? "Sag „Jarvis …“ um mich anzusprechen." : "Ich höre zu …";
  });
  J.voice.on("speaking", (on) => { setState(on ? "SPEAKING" : (J.voice.active ? "LISTENING" : "IDLE")); els.stopAudio.classList.toggle("hidden", !on && !els.stream.src); });
  J.voice.on("error", (m) => { toast("Sprachmodus", m.message); logLine(m.message, "err"); });
  J.voice.on("transcript", (m) => {
    if (m.role === "user") {
      if (!liveUser) liveUser = addMessage("user", "", { source: "voice" });
      const b = liveUser.querySelector(".body");
      b.textContent = (b.textContent + m.text).trimStart();
      els.caption.textContent = "„" + b.textContent.slice(-140) + "“";
    } else {
      if (!liveModel) liveModel = addMessage("model", "", { source: "voice" });
      const b = liveModel.querySelector(".body");
      b.textContent = (b.textContent + m.text).trimStart();
    }
    els.messages.scrollTop = els.messages.scrollHeight;
  });
  J.voice.on("turn_complete", () => {
    if (liveModel) liveModel.querySelector(".body").innerHTML = md(liveModel.querySelector(".body").textContent);
    liveUser = liveModel = null;
  });
  J.voice.on("share", (kind) => {
    els.screen.classList.toggle("on", kind === "screen");
    els.camera.classList.toggle("on", kind === "camera");
    if (kind) logLine(kind === "camera" ? "📷 Kamera freigegeben" : "🖥 Bildschirm freigegeben", "ok");
  });
  async function toggleShare(kind) {
    if (J.voice.sharing === kind) { J.voice.stopShare(); els[kind === "camera" ? "camera" : "screen"].classList.remove("on"); return; }
    try { await J.voice.startShare(kind); }
    catch (e) { toast("Freigabe abgebrochen", e.message); }
  }
  els.screen.onclick = () => toggleShare("screen");
  els.camera.onclick = () => toggleShare("camera");

  // ── Dateien (Upload, Drag & Drop) ──
  const fileInput = $("file-input");
  $("btn-attach").onclick = () => fileInput.click();
  fileInput.onchange = () => fileInput.files[0] && upload(fileInput.files[0]);
  async function upload(file) {
    const fd = new FormData();
    fd.append("file", file);
    logLine(`⇪ Lade ${file.name} hoch …`);
    try {
      const r = await J.api("/api/upload", { method: "POST", body: fd });
      logLine(`✓ ${r.name} hochgeladen`, "ok");
      loadFiles();
      els.input.focus();
    } catch (e) { toast("Upload fehlgeschlagen", e.message); }
    fileInput.value = "";
  }
  const center = $("center"), dropHint = $("drop-hint");
  ["dragenter", "dragover"].forEach(ev => center.addEventListener(ev, (e) => { e.preventDefault(); dropHint.classList.remove("hidden"); }));
  ["dragleave", "drop"].forEach(ev => center.addEventListener(ev, (e) => { e.preventDefault(); if (ev === "drop" || e.target === center) dropHint.classList.add("hidden"); }));
  center.addEventListener("drop", (e) => { dropHint.classList.add("hidden"); const f = e.dataTransfer.files[0]; if (f) upload(f); });
  $("attach-clear").onclick = async () => { await J.api("/api/files", { method: "POST", body: { name: "" } }); loadFiles(); };

  async function loadFiles() {
    const r = await J.api("/api/files");
    els.attachInfo.classList.toggle("hidden", !r.current);
    els.attachName.textContent = r.current ? r.current.replace(/^\d{8}_\d{6}_/, "") + " – JARVIS kann damit arbeiten" : "";
    els.files.innerHTML = r.files.length ? "" : '<div class="muted">Noch keine Dateien.</div>';
    r.files.forEach(f => {
      const d = document.createElement("div");
      d.className = "item";
      const short = f.name.replace(/^\d{8}_\d{6}_/, "");
      d.innerHTML = `<div class="grow"><a href="/files/${encodeURI(f.name)}" title="${esc(f.name)}">${esc(short)}</a>
        <div class="muted">${(f.size / 1024).toFixed(1)} KB ${r.current === f.name ? "· aktiv" : ""}</div></div>
        <button class="x" title="Als aktive Datei wählen">📎</button><button class="x" title="Löschen">✕</button>`;
      const [sel, del] = d.querySelectorAll("button");
      sel.onclick = async () => { await J.api("/api/files", { method: "POST", body: { name: f.name } }); loadFiles(); };
      del.onclick = async () => { await J.api("/api/files/delete", { method: "POST", body: { name: f.name } }); loadFiles(); };
      els.files.appendChild(d);
    });
  }

  // ── Benachrichtigungen, Erinnerungen, Wecker ──
  async function loadNotifications() {
    const r = await J.api("/api/notifications");
    els.notifications.innerHTML = r.notifications.length ? "" : '<div class="muted">Keine Benachrichtigungen.</div>';
    r.notifications.slice(0, 30).forEach(n => {
      const d = document.createElement("div");
      d.className = "item" + (n.read ? "" : " unread");
      d.innerHTML = `<div class="grow"><b>${esc(n.title)}</b><div>${esc(n.body)}</div><div class="muted">${new Date(n.created_at).toLocaleString("de-DE")}</div></div>`;
      els.notifications.appendChild(d);
    });
  }
  $("btn-read-all").onclick = async () => { await J.api("/api/notifications", { method: "POST", body: {} }); loadNotifications(); };

  async function loadReminders() {
    const r = await J.api("/api/reminders");
    els.reminders.innerHTML = r.reminders.length ? "" : '<div class="muted">Keine offenen Erinnerungen. Sag z. B. „Erinnere mich morgen um 9 an …“.</div>';
    r.reminders.forEach(x => {
      const d = document.createElement("div");
      d.className = "item";
      d.innerHTML = `<span>🔔</span><div class="grow"><b>${esc(x.due_at)}</b><div>${esc(x.message)}</div></div><button class="x" title="Löschen">✕</button>`;
      d.querySelector(".x").onclick = async () => { await J.api("/api/reminders", { method: "POST", body: { delete: x.id } }); loadReminders(); };
      els.reminders.appendChild(d);
    });
  }
  async function loadAlarms() {
    const r = await J.api("/api/alarms");
    els.alarms.innerHTML = "";
    r.alarms.forEach(a => {
      const d = document.createElement("div");
      d.className = "item";
      d.innerHTML = `<span>⏰</span><div class="grow"><b style="${a.active ? "" : "opacity:.45"}">${esc(a.time)}</b> <span class="muted">${esc(a.music || "Signalton")}</span></div>
        <button class="x" title="${a.active ? "Deaktivieren" : "Aktivieren"}">${a.active ? "⏸" : "▶"}</button><button class="x" title="Löschen">✕</button>`;
      const [tog, del] = d.querySelectorAll(".x");
      tog.onclick = async () => { await J.api("/api/alarms", { method: "POST", body: { toggle: a.id } }); loadAlarms(); };
      del.onclick = async () => { await J.api("/api/alarms", { method: "POST", body: { delete: a.id } }); loadAlarms(); };
      els.alarms.appendChild(d);
    });
  }
  $("alarm-form").onsubmit = async (e) => {
    e.preventDefault();
    const r = await J.api("/api/alarms", { method: "POST", body: { time: $("alarm-time").value, music: $("alarm-music").value } });
    toast("Wecker", r.message);
    loadAlarms();
  };

  // ── Schalter ──
  const saveProfile = (body) => J.api("/api/profile", { method: "POST", body }).catch(e => toast("Fehler", e.message));
  $("opt-tts").onchange = (e) => { prefs.tts = e.target.checked; if (!prefs.tts && "speechSynthesis" in window) speechSynthesis.cancel(); saveProfile({ tts_enabled: prefs.tts }); };
  $("opt-wake").onchange = (e) => { saveProfile({ wake_word_mode: e.target.checked }); if (J.voice.active) toast("Wake-Word", "Wird beim nächsten Start des Sprachmodus aktiv."); };
  $("opt-hydration").onchange = (e) => saveProfile({ hydration_reminder: e.target.checked });
  const auto = $("opt-autopilot");
  if (auto) auto.onchange = async (e) => {
    try {
      const r = await J.api("/api/autopilot", { method: "POST", body: { active: e.target.checked } });
      addMessage("model", r.message);
    } catch (err) { toast("Autopilot", err.message); e.target.checked = !e.target.checked; }
  };
  $("btn-clear-log").onclick = () => { els.log.innerHTML = ""; };

  // ── Mobile Tabs ──
  document.querySelectorAll("[data-mtab]").forEach(b => b.onclick = () => {
    document.querySelectorAll("[data-mtab]").forEach(x => x.classList.toggle("active", x === b));
    document.body.classList.remove("tab-activity", "tab-more");
    if (b.dataset.mtab !== "chat") document.body.classList.add("tab-" + b.dataset.mtab);
  });

  // ── Status ──
  async function loadStatus() {
    try {
      const s = await J.api("/api/status");
      setAgent(s.agent);
      if (s.server && s.server.metrics) { bar("s-cpu", "sb-cpu", s.server.metrics.cpu); bar("s-ram", "sb-ram", s.server.metrics.ram); }
      if (auto) auto.checked = !!s.autopilot;
      if (!s.api_key_configured && !loadStatus.warned) {
        loadStatus.warned = true;
        toast("Kein Gemini-API-Key", s.full_access ? "Bitte in den Einstellungen eintragen." : "Bitte den Administrator informieren.", { sticky: true,
          actions: s.full_access ? [["Einstellungen", () => location.href = "/settings/", true]] : null });
      }
    } catch (e) {}
  }

  // Start
  connectEvents();
  loadHistory().catch(() => showEmpty());
  loadStatus();
  setInterval(loadStatus, 30000);
  loadNotifications();
  loadReminders();
  loadAlarms();
  loadFiles();
  setState("IDLE");
})();
