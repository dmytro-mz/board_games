// Sound effects, all synthesised with WebAudio (no audio files).

let ctx = null;
let out = null;
let muted = localStorage.getItem("toybattle.muted") === "1";
let volume = Number(localStorage.getItem("toybattle.volume") ?? 0.8);
let noiseBuffer = null;
const BOOST = 5;

export const isMuted = () => muted;
export const getVolume = () => volume;

export function setMuted(value) {
  muted = value;
  localStorage.setItem("toybattle.muted", value ? "1" : "0");
}

export function setVolume(value) {
  volume = Math.min(1, Math.max(0, value));
  localStorage.setItem("toybattle.volume", String(volume));
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

const flick = (at = 0, freq = 2600) => noise(0.07, { gain: 0.07, freq, q: 1.2, at, slide: 0.6 });

const thud = (at = 0, freq = 420, gain = 0.1) => {
  noise(0.09, { gain, freq, q: 1.4, at, type: "lowpass" });
  tone(freq / 3, 0.12, { type: "sine", gain: gain * 0.7, at, slide: 0.6 });
};

export const sfx = {
  select: () => noise(0.04, { gain: 0.04, freq: 3200, q: 2 }),
  place: () => {
    flick(0, 2400);
    thud(0.04, 380, 0.11);
  },
  cover: () => {
    flick(0, 2000);
    thud(0.03, 300, 0.13);
    tone(150, 0.14, { type: "triangle", gain: 0.04, at: 0.07, slide: 0.7 });
  },
  knock: () => {
    tone(900, 0.08, { type: "square", gain: 0.03, slide: 0.4 });
    noise(0.22, { gain: 0.08, freq: 1400, q: 0.8, at: 0.04, slide: 0.3 });
  },
  boing: () => tone(260, 0.32, { type: "triangle", gain: 0.06, slide: 2.6 }),
  draw: () => noise(0.16, { gain: 0.06, freq: 2600, slide: 0.45 }),
  shuffle: () => {
    for (let i = 0; i < 9; i++) flick(i * 0.05, 1800 + Math.random() * 1600);
  },
  rally: () => [392, 392, 523].forEach((f, i) => tone(f, 0.09, { type: "square", gain: 0.025, at: i * 0.09 })),
  magnet: () => tone(180, 0.35, { type: "sawtooth", gain: 0.025, slide: 3.5 }),
  sand: () => noise(0.4, { gain: 0.05, freq: 900, q: 0.5, slide: 0.5 }),
  whoosh: () => noise(0.35, { gain: 0.05, freq: 600, q: 0.7, slide: 4 }),
  medal: () => [988, 1319, 1568].forEach((f, i) => tone(f, 0.22, { type: "triangle", gain: 0.05, at: i * 0.08 })),
  turn: () => [659, 880].forEach((f, i) => tone(f, 0.18, { type: "triangle", gain: 0.06, at: i * 0.12 })),
  fanfare: () => [523, 659, 784, 1046, 784, 1046, 1318].forEach((f, i) => tone(f, 0.26, { type: "triangle", gain: 0.06, at: i * 0.12 })),
  lose: () => [392, 349, 311, 262].forEach((f, i) => tone(f, 0.32, { type: "triangle", gain: 0.05, at: i * 0.18 })),
  tick: () => tone(1250, 0.03, { type: "square", gain: 0.018 }),
  error: () => tone(170, 0.16, { type: "sawtooth", gain: 0.03 }),
  chat: () => tone(880, 0.07, { gain: 0.03 }),
};
