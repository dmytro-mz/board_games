// Sound effects, all synthesised with WebAudio (no audio files).

let ctx = null;
let out = null;
let muted = localStorage.getItem("sumo.muted") === "1";
let volume = Number(localStorage.getItem("sumo.volume") ?? 0.8);
let noiseBuffer = null;
const BOOST = 5;

export const isMuted = () => muted;
export const getVolume = () => volume;

export function setMuted(value) {
  muted = value;
  localStorage.setItem("sumo.muted", value ? "1" : "0");
}

export function setVolume(value) {
  volume = Math.min(1, Math.max(0, value));
  localStorage.setItem("sumo.volume", String(volume));
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

// Stone on stone: a short bright click plus a low knock.
const clack = (at = 0, freq = 3200, gain = 0.08) => {
  noise(0.035, { gain, freq, q: 3, at });
  tone(freq / 4, 0.05, { type: "triangle", gain: gain * 0.5, at, slide: 0.8 });
};

const roll = (at = 0, dur = 0.28, gain = 0.035) => noise(dur, { gain, freq: 700, q: 0.6, at, type: "lowpass", slide: 0.6 });

export const sfx = {
  select: () => clack(0, 4200, 0.04),
  deselect: () => clack(0, 2600, 0.03),
  move: (n = 1) => {
    roll(0, 0.26, 0.03 + n * 0.006);
    clack(0.24, 2800, 0.05);
  },
  push: (n = 1) => {
    clack(0, 3000, 0.1);
    clack(0.03, 2300, 0.07);
    roll(0.02, 0.3, 0.04 + n * 0.008);
    tone(140, 0.14, { type: "sine", gain: 0.05, at: 0.02, slide: 0.7 });
  },
  out: () => {
    roll(0, 0.22, 0.05);
    tone(520, 0.35, { type: "sine", gain: 0.045, at: 0.18, slide: 0.35 });
    noise(0.12, { gain: 0.09, freq: 380, q: 1.2, at: 0.5, type: "lowpass" });
    clack(0.52, 1800, 0.08);
    clack(0.62, 2200, 0.04);
  },
  shuffle: () => {
    for (let i = 0; i < 10; i++) clack(i * 0.045, 2600 + Math.random() * 1800, 0.035);
  },
  gong: () => {
    tone(196, 1.6, { type: "sine", gain: 0.06 });
    tone(294, 1.2, { type: "sine", gain: 0.025, at: 0.01 });
    tone(392, 0.9, { type: "triangle", gain: 0.012, at: 0.02 });
  },
  turn: () => [587, 784].forEach((f, i) => tone(f, 0.18, { type: "triangle", gain: 0.05, at: i * 0.12 })),
  fanfare: () => [523, 659, 784, 1046, 784, 1046, 1318].forEach((f, i) => tone(f, 0.26, { type: "triangle", gain: 0.06, at: i * 0.12 })),
  lose: () => [392, 349, 311, 262].forEach((f, i) => tone(f, 0.32, { type: "triangle", gain: 0.05, at: i * 0.18 })),
  tick: () => tone(1250, 0.03, { type: "square", gain: 0.018 }),
  error: () => tone(170, 0.16, { type: "sawtooth", gain: 0.03 }),
  chat: () => tone(880, 0.07, { gain: 0.03 }),
};
