/* AudioWorklet: Mikrofon → 16 kHz PCM16, in Blöcken von 100 ms an den Hauptthread. */
class MicProcessor extends AudioWorkletProcessor {
  constructor() {
    super();
    this.ratio = sampleRate / 16000;
    this.pos = 0;
    this.acc = 0;
    this.accN = 0;
    this.buf = new Int16Array(1600);
    this.len = 0;
  }

  process(inputs) {
    const ch = inputs[0] && inputs[0][0];
    if (!ch) return true;
    for (let i = 0; i < ch.length; i++) {
      // einfache Mittelwert-Dezimierung (ausreichend für Sprache)
      this.acc += ch[i];
      this.accN++;
      this.pos += 1;
      if (this.pos >= this.ratio) {
        this.pos -= this.ratio;
        const s = Math.max(-1, Math.min(1, this.acc / this.accN));
        this.acc = 0;
        this.accN = 0;
        this.buf[this.len++] = s < 0 ? s * 0x8000 : s * 0x7fff;
        if (this.len === this.buf.length) {
          this.port.postMessage(this.buf.buffer.slice(0));
          this.len = 0;
        }
      }
    }
    return true;
  }
}
registerProcessor("mic-processor", MicProcessor);
