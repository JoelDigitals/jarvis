/* Animierter Arc-Reaktor – zeigt den Zustand von JARVIS (bereit / hört zu / denkt / spricht). */
(function () {
  const canvas = document.getElementById("reactor");
  if (!canvas) return;
  const ctx = canvas.getContext("2d");
  const W = canvas.width, H = canvas.height, CX = W / 2, CY = H / 2;
  const COLORS = {
    IDLE: [0, 204, 255], LISTENING: [0, 204, 255], THINKING: [138, 92, 255],
    SPEAKING: [90, 230, 255], CONNECTING: [255, 170, 51], OFF: [70, 100, 120],
  };
  let state = "IDLE", level = 0, smooth = 0, t = 0;
  let color = COLORS.IDLE.slice();

  function rgba(c, a) { return `rgba(${c[0] | 0},${c[1] | 0},${c[2] | 0},${a})`; }

  function draw() {
    t += 1 / 60;
    const target = COLORS[state] || COLORS.IDLE;
    for (let i = 0; i < 3; i++) color[i] += (target[i] - color[i]) * 0.08;
    smooth += (level - smooth) * 0.25;
    level *= 0.92;

    ctx.clearRect(0, 0, W, H);
    const speed = state === "THINKING" ? 2.6 : state === "SPEAKING" ? 1.4 : state === "OFF" ? 0.15 : 0.5;
    const pulse = state === "SPEAKING" ? smooth : state === "LISTENING" ? 0.12 + 0.08 * Math.sin(t * 3) : 0.05 * Math.sin(t * 1.5);
    const R = W * 0.36;

    // äußeres Leuchten
    const g = ctx.createRadialGradient(CX, CY, R * 0.2, CX, CY, R * 1.35);
    g.addColorStop(0, rgba(color, 0.18 + pulse * 0.4));
    g.addColorStop(1, rgba(color, 0));
    ctx.fillStyle = g;
    ctx.fillRect(0, 0, W, H);

    // Segment-Ringe
    const rings = [
      { r: R, n: 36, w: 5, len: 0.12, dir: 1, a: 0.85 },
      { r: R * 0.82, n: 12, w: 9, len: 0.34, dir: -1.6, a: 0.55 },
      { r: R * 1.1, n: 72, w: 2, len: 0.05, dir: 0.6, a: 0.35 },
    ];
    for (const ring of rings) {
      ctx.lineWidth = ring.w;
      ctx.strokeStyle = rgba(color, ring.a);
      for (let i = 0; i < ring.n; i++) {
        const a0 = (i / ring.n) * Math.PI * 2 + t * speed * ring.dir * 0.4;
        ctx.beginPath();
        ctx.arc(CX, CY, ring.r * (1 + pulse * 0.08), a0, a0 + ring.len);
        ctx.stroke();
      }
    }

    // Kern
    const core = R * (0.42 + pulse * 0.18);
    const cg = ctx.createRadialGradient(CX, CY, 0, CX, CY, core);
    cg.addColorStop(0, "rgba(235,250,255,.95)");
    cg.addColorStop(0.35, rgba(color, 0.9));
    cg.addColorStop(1, rgba(color, 0));
    ctx.fillStyle = cg;
    ctx.beginPath();
    ctx.arc(CX, CY, core, 0, Math.PI * 2);
    ctx.fill();

    // Dreieck wie beim Mark-Reaktor
    ctx.strokeStyle = rgba(color, 0.7);
    ctx.lineWidth = 3;
    ctx.beginPath();
    for (let i = 0; i < 3; i++) {
      const a = -Math.PI / 2 + (i * Math.PI * 2) / 3 + t * speed * 0.15;
      const x = CX + Math.cos(a) * R * 0.62, y = CY + Math.sin(a) * R * 0.62;
      i ? ctx.lineTo(x, y) : ctx.moveTo(x, y);
    }
    ctx.closePath();
    ctx.stroke();

    requestAnimationFrame(draw);
  }
  requestAnimationFrame(draw);

  window.JARVIS = window.JARVIS || {};
  JARVIS.reactor = {
    setState(s) { state = s || "IDLE"; },
    setLevel(v) { level = Math.max(level, Math.min(1, v)); },
  };
})();
