/* Sprachmodus (Gemini Live über /ws/live/) + Bildschirm-/Kamerafreigabe. */
(function () {
  const J = (window.JARVIS = window.JARVIS || {});
  const listeners = {};
  const emit = (type, data) => (listeners[type] || []).forEach(fn => { try { fn(data); } catch (e) { console.error(e); } });

  let ws = null, micCtx = null, micNode = null, micStream = null, micSource = null;
  let playCtx = null, nextTime = 0, sources = [];
  let active = false, wantActive = false, reconnectTimer = null;
  let share = null; // { stream, video, canvas, kind, timer }

  const wsUrl = (path) => `${location.protocol === "https:" ? "wss" : "ws"}://${location.host}${path}`;
  const concat = (prefix, buf) => {
    const out = new Uint8Array(buf.byteLength + 1);
    out[0] = prefix.charCodeAt(0);
    out.set(new Uint8Array(buf), 1);
    return out.buffer;
  };

  // ── Wiedergabe (PCM16 24 kHz) ──
  function ensurePlayCtx() {
    if (!playCtx) playCtx = new (window.AudioContext || window.webkitAudioContext)({ sampleRate: 24000 });
    if (playCtx.state === "suspended") playCtx.resume();
  }
  function playChunk(buf) {
    ensurePlayCtx();
    const pcm = new Int16Array(buf);
    const f32 = new Float32Array(pcm.length);
    let sum = 0;
    for (let i = 0; i < pcm.length; i++) { f32[i] = pcm[i] / 0x8000; sum += f32[i] * f32[i]; }
    J.reactor && J.reactor.setLevel(Math.min(1, Math.sqrt(sum / pcm.length) * 5));
    const ab = playCtx.createBuffer(1, f32.length, 24000);
    ab.copyToChannel(f32, 0);
    const src = playCtx.createBufferSource();
    src.buffer = ab;
    src.connect(playCtx.destination);
    const start = Math.max(playCtx.currentTime + 0.03, nextTime);
    src.start(start);
    nextTime = start + ab.duration;
    sources.push(src);
    src.onended = () => {
      sources = sources.filter(s => s !== src);
      if (!sources.length) emit("speaking", false);
    };
    emit("speaking", true);
  }
  function stopPlayback() {
    sources.forEach(s => { try { s.stop(); } catch (e) {} });
    sources = [];
    nextTime = 0;
    emit("speaking", false);
  }
  const isPlaying = () => playCtx && nextTime > playCtx.currentTime - 0.3;

  // ── Mikrofon ──
  async function startMic() {
    micStream = await navigator.mediaDevices.getUserMedia({
      audio: { echoCancellation: true, noiseSuppression: true, autoGainControl: true, channelCount: 1 },
    });
    micCtx = new (window.AudioContext || window.webkitAudioContext)();
    await micCtx.audioWorklet.addModule(J.workletUrl);
    micSource = micCtx.createMediaStreamSource(micStream);
    micNode = new AudioWorkletNode(micCtx, "mic-processor");
    micNode.port.onmessage = (e) => {
      if (!ws || ws.readyState !== 1 || isPlaying()) return; // Halbduplex: kein Echo an Gemini
      ws.send(concat("A", e.data));
    };
    micSource.connect(micNode);
  }
  function stopMic() {
    try { micSource && micSource.disconnect(); micNode && micNode.disconnect(); } catch (e) {}
    micStream && micStream.getTracks().forEach(t => t.stop());
    micCtx && micCtx.close();
    micCtx = micNode = micStream = micSource = null;
  }

  // ── Live-Verbindung ──
  function connect() {
    ws = new WebSocket(wsUrl(`/ws/live/?cid=${encodeURIComponent(J.clientId || "")}`));
    ws.binaryType = "arraybuffer";
    ws.onopen = () => ws.send(JSON.stringify({ type: "start" }));
    ws.onmessage = (e) => {
      if (typeof e.data !== "string") { playChunk(e.data); return; }
      const msg = JSON.parse(e.data);
      if (msg.type === "interrupted") stopPlayback();
      if (msg.type === "state" && msg.state === "OFF" && wantActive) scheduleReconnect();
      emit(msg.type, msg);
    };
    ws.onclose = () => {
      ws = null;
      if (wantActive) scheduleReconnect();
    };
  }
  function scheduleReconnect() {
    if (reconnectTimer) return;
    emit("state", { state: "CONNECTING" });
    reconnectTimer = setTimeout(() => {
      reconnectTimer = null;
      if (!wantActive) return;
      if (ws) { try { ws.close(); } catch (e) {} ws = null; }
      connect();
    }, 1500);
  }

  async function start() {
    if (active) return;
    wantActive = true;
    ensurePlayCtx();
    try {
      await startMic();
    } catch (e) {
      wantActive = false;
      emit("error", { message: "Mikrofon nicht verfügbar: " + e.message });
      return;
    }
    active = true;
    connect();
    emit("active", true);
  }
  function stop() {
    wantActive = false;
    active = false;
    clearTimeout(reconnectTimer);
    reconnectTimer = null;
    if (ws) { try { ws.send(JSON.stringify({ type: "stop" })); ws.close(); } catch (e) {} ws = null; }
    stopMic();
    stopPlayback();
    emit("active", false);
    emit("state", { state: "OFF" });
  }
  function sendText(text) {
    if (ws && ws.readyState === 1) { ws.send(JSON.stringify({ type: "text", text })); return true; }
    return false;
  }

  // ── Bildschirm / Kamera ──
  async function startShare(kind) {
    stopShare();
    const stream = kind === "camera"
      ? await navigator.mediaDevices.getUserMedia({ video: { width: 1280, height: 720 } })
      : await navigator.mediaDevices.getDisplayMedia({ video: { frameRate: 5 }, audio: false });
    const video = document.createElement("video");
    video.muted = true;
    video.playsInline = true;
    video.srcObject = stream;
    await video.play();
    const canvas = document.createElement("canvas");
    share = { stream, video, canvas, kind };
    stream.getVideoTracks()[0].addEventListener("ended", () => { stopShare(); emit("share", null); });
    const tick = () => {
      if (!share) return;
      const w = video.videoWidth, h = video.videoHeight;
      if (w && h) {
        const scale = Math.min(1, 1024 / w);
        canvas.width = Math.round(w * scale);
        canvas.height = Math.round(h * scale);
        canvas.getContext("2d").drawImage(video, 0, 0, canvas.width, canvas.height);
        canvas.toBlob(async (blob) => {
          if (!blob || !share) return;
          const data = concat(kind === "camera" ? "C" : "S", await blob.arrayBuffer());
          if (ws && ws.readyState === 1) ws.send(data);
          else if (J.events) J.events.sendBinary(data);
        }, "image/jpeg", 0.6);
      }
      share.timer = setTimeout(tick, active ? 1000 : 2000);
    };
    tick();
    emit("share", kind);
  }
  function stopShare() {
    if (!share) return;
    clearTimeout(share.timer);
    share.stream.getTracks().forEach(t => t.stop());
    share = null;
    J.events && J.events.send({ type: "share_stopped" });
  }

  J.voice = {
    on(type, fn) { (listeners[type] = listeners[type] || []).push(fn); },
    start, stop, sendText, stopPlayback,
    startShare, stopShare,
    get active() { return active; },
    get sharing() { return share && share.kind; },
  };
})();
