// Sound effects, all synthesised with WebAudio (no audio files).

let ctx = null;
let out = null;
let muted = localStorage.getItem("phase10.muted") === "1";
let volume = Number(localStorage.getItem("phase10.volume") ?? 0.8);
let noiseBuffer = null;
const BOOST = 5;

export const isMuted = () => muted;
export const getVolume = () => volume;

export function setMuted(value) {
  muted = value;
  localStorage.setItem("phase10.muted", value ? "1" : "0");
}

export function setVolume(value) {
  volume = Math.min(1, Math.max(0, value));
  localStorage.setItem("phase10.volume", String(volume));
  if (out) out.gain.setTargetAtTime(volume * BOOST, ctx.currentTime, 0.02);
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
    out.gain.value = volume * BOOST;
    out.connect(limiter).connect(ctx.destination);
  }
  if (ctx.state === "suspended") ctx.resume();
}

const ready = () => !muted && volume > 0 && ctx && ctx.state === "running";

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
  draw: () => noise(0.16, { gain: 0.06, freq: 2600, slide: 0.45, q: 0.7 }),
  snap: () => {
    noise(0.05, { gain: 0.12, freq: 1600, q: 1.2 });
    tone(180, 0.06, { type: "triangle", gain: 0.04 });
  },
  place: () => {
    for (let i = 0; i < 3; i++) noise(0.05, { gain: 0.09, freq: 1400 + i * 300, q: 1.4, at: i * 0.07 });
  },
  shuffle: () => {
    for (let i = 0; i < 14; i++) noise(0.04, { gain: 0.05, freq: 2200 + Math.random() * 1500, q: 2, at: i * 0.035 });
  },
  select: () => tone(1320, 0.04, { type: "sine", gain: 0.025 }),
  drag: () => noise(0.06, { gain: 0.03, freq: 3000, q: 1 }),
  phase: () => [523, 659, 784, 1046, 1318].forEach((f, i) => tone(f, 0.24, { type: "triangle", gain: 0.06, at: i * 0.08 })),
  skip: () => {
    tone(330, 0.16, { type: "square", gain: 0.035 });
    tone(220, 0.26, { type: "square", gain: 0.035, at: 0.14 });
  },
  out: () => [784, 988, 1175, 1568].forEach((f, i) => tone(f, 0.3, { type: "triangle", gain: 0.06, at: i * 0.1 })),
  turn: () => [659, 880].forEach((f, i) => tone(f, 0.18, { type: "triangle", gain: 0.06, at: i * 0.12 })),
  fanfare: () => [523, 659, 784, 1046, 784, 1046, 1318].forEach((f, i) => tone(f, 0.26, { type: "triangle", gain: 0.06, at: i * 0.12 })),
  lose: () => [392, 349, 311, 262].forEach((f, i) => tone(f, 0.32, { type: "triangle", gain: 0.05, at: i * 0.18 })),
  tick: () => tone(1250, 0.03, { type: "square", gain: 0.018 }),
  error: () => tone(170, 0.16, { type: "sawtooth", gain: 0.03 }),
  chat: () => tone(880, 0.07, { gain: 0.03 }),
};
