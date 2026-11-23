// Sound effects, all synthesised with WebAudio (no audio files).

let ctx = null;
let out = null;
let muted = localStorage.getItem("pandemic.muted") === "1";
let noiseBuffer = null;
const VOLUME = 3;

export const isMuted = () => muted;

export function setMuted(value) {
  muted = value;
  localStorage.setItem("pandemic.muted", value ? "1" : "0");
}

// Browsers only start audio after a user gesture.
export function unlockAudio() {
  if (!ctx) {
    const AC = window.AudioContext || window.webkitAudioContext;
    if (!AC) return;
    ctx = new AC();
    const limiter = ctx.createDynamicsCompressor();
    limiter.threshold.value = -10;
    limiter.ratio.value = 12;
    out = ctx.createGain();
    out.gain.value = VOLUME;
    out.connect(limiter).connect(ctx.destination);
  }
  if (ctx.state === "suspended") ctx.resume();
}

const ready = () => !muted && ctx && ctx.state === "running";

function tone(freq, dur, { type = "sine", gain = 0.06, at = 0, slide = 0 } = {}) {
  if (!ready()) return;
  const t = ctx.currentTime + at;
  const osc = ctx.createOscillator();
  const amp = ctx.createGain();
  osc.type = type;
  osc.frequency.setValueAtTime(freq, t);
  if (slide) osc.frequency.exponentialRampToValueAtTime(freq * slide, t + dur);
  amp.gain.setValueAtTime(0.0001, t);
  amp.gain.exponentialRampToValueAtTime(gain, t + 0.02);
  amp.gain.exponentialRampToValueAtTime(0.0001, t + dur);
  osc.connect(amp).connect(out);
  osc.start(t);
  osc.stop(t + dur + 0.05);
}

function noise(dur, { gain = 0.06, at = 0, freq = 2500, q = 0.9, slide = 0, type = "bandpass" } = {}) {
  if (!ready()) return;
  if (!noiseBuffer) {
    noiseBuffer = ctx.createBuffer(1, ctx.sampleRate * 0.5, ctx.sampleRate);
    const data = noiseBuffer.getChannelData(0);
    for (let i = 0; i < data.length; i++) data[i] = Math.random() * 2 - 1;
  }
  const t = ctx.currentTime + at;
  const src = ctx.createBufferSource();
  src.buffer = noiseBuffer;
  src.loop = true;
  const filter = ctx.createBiquadFilter();
  filter.type = type;
  filter.frequency.setValueAtTime(freq, t);
  if (slide) filter.frequency.exponentialRampToValueAtTime(freq * slide, t + dur);
  filter.Q.value = q;
  const amp = ctx.createGain();
  amp.gain.setValueAtTime(gain, t);
  amp.gain.exponentialRampToValueAtTime(0.0001, t + dur);
  src.connect(filter).connect(amp).connect(out);
  src.start(t);
  src.stop(t + dur + 0.05);
}

export const sfx = {
  move: () => noise(0.22, { gain: 0.05, freq: 900, slide: 2.2, q: 0.8 }),
  flight: () => noise(0.5, { gain: 0.05, freq: 500, slide: 4, q: 0.6 }),
  treat: () => [1046, 1318].forEach((f, i) => tone(f, 0.09, { type: "triangle", gain: 0.04, at: i * 0.06 })),
  build: () => {
    for (let i = 0; i < 3; i++) noise(0.05, { gain: 0.09, freq: 900 + i * 250, q: 1.6, at: i * 0.09 });
  },
  card: () => noise(0.14, { gain: 0.05, freq: 2600, slide: 0.5, q: 0.7 }),
  event: () => [784, 1175].forEach((f, i) => tone(f, 0.16, { type: "sine", gain: 0.05, at: i * 0.08 })),
  cure: () => [523, 659, 784, 1046, 1318].forEach((f, i) => tone(f, 0.26, { type: "triangle", gain: 0.06, at: i * 0.08 })),
  infect: () => tone(260, 0.18, { type: "triangle", gain: 0.04, slide: 0.8 }),
  outbreak: () => {
    noise(0.5, { gain: 0.12, freq: 260, slide: 0.4, q: 0.7, type: "lowpass" });
    tone(110, 0.45, { type: "sawtooth", gain: 0.04, slide: 0.6 });
  },
  epidemic: () => [440, 415, 440, 415].forEach((f, i) => tone(f, 0.2, { type: "square", gain: 0.03, at: i * 0.22 })),
  turn: () => [659, 880].forEach((f, i) => tone(f, 0.18, { type: "triangle", gain: 0.06, at: i * 0.12 })),
  fanfare: () => [523, 659, 784, 1046, 784, 1046, 1318].forEach((f, i) => tone(f, 0.26, { type: "triangle", gain: 0.06, at: i * 0.12 })),
  lose: () => [392, 349, 311, 262].forEach((f, i) => tone(f, 0.32, { type: "triangle", gain: 0.05, at: i * 0.18 })),
  error: () => tone(170, 0.16, { type: "sawtooth", gain: 0.03 }),
  chat: () => tone(880, 0.07, { gain: 0.03 }),
};
