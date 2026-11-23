// Sound effects, all synthesised with WebAudio (no audio files).

let ctx = null;
let out = null;
let muted = safeGet("aa.muted") === "1";
let volume = Number(safeGet("aa.volume") ?? 0.85);
let noiseBuffer = null;
// The effects are written at modest per-sound gains; this lifts them to a loud level at full volume.
const BOOST = 5;

export const isMuted = () => muted;
export const getVolume = () => volume;

export function setMuted(value) {
  muted = value;
  safeSet("aa.muted", value ? "1" : "0");
}

export function setVolume(value) {
  volume = Math.min(1, Math.max(0, value));
  safeSet("aa.volume", String(volume));
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
    limiter.knee.value = 6;
    limiter.ratio.value = 12;
    limiter.attack.value = 0.003;
    limiter.release.value = 0.15;
    out = ctx.createGain();
    out.gain.value = volume * BOOST;
    out.connect(limiter).connect(ctx.destination);
  }
  if (ctx.state === "suspended") ctx.resume();
}

function ready() {
  return !muted && volume > 0 && ctx && ctx.state === "running";
}

function tone(freq, dur, { type = "sine", gain = 0.07, at = 0, slide = 0, vibrato = 0 } = {}) {
  if (!ready()) return;
  const t = ctx.currentTime + at;
  const osc = ctx.createOscillator();
  const amp = ctx.createGain();
  osc.type = type;
  osc.frequency.setValueAtTime(freq, t);
  if (slide) osc.frequency.exponentialRampToValueAtTime(freq * slide, t + dur);
  if (vibrato) {
    const lfo = ctx.createOscillator();
    const depth = ctx.createGain();
    lfo.frequency.value = 6;
    depth.gain.value = vibrato;
    lfo.connect(depth).connect(osc.frequency);
    lfo.start(t);
    lfo.stop(t + dur + 0.05);
  }
  amp.gain.setValueAtTime(0.0001, t);
  amp.gain.exponentialRampToValueAtTime(gain, t + 0.03);
  amp.gain.setValueAtTime(gain, t + Math.max(0.03, dur - 0.08));
  amp.gain.exponentialRampToValueAtTime(0.0001, t + dur);
  osc.connect(amp).connect(out);
  osc.start(t);
  osc.stop(t + dur + 0.05);
}

function noise(dur, { gain = 0.06, at = 0, freq = 2500, q = 0.9, attack = 0, slide = 0 } = {}) {
  if (!ready()) return null;
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
  filter.type = "bandpass";
  filter.frequency.setValueAtTime(freq, t);
  if (slide) filter.frequency.exponentialRampToValueAtTime(freq * slide, t + dur);
  filter.Q.value = q;
  const amp = ctx.createGain();
  if (attack) {
    amp.gain.setValueAtTime(0.0001, t);
    amp.gain.exponentialRampToValueAtTime(gain, t + attack);
  } else amp.gain.setValueAtTime(gain, t);
  amp.gain.exponentialRampToValueAtTime(0.0001, t + dur);
  src.connect(filter).connect(amp).connect(out);
  src.start(t);
  src.stop(t + dur + 0.05);
  return amp;
}

function safeGet(key) {
  try {
    return localStorage.getItem(key);
  } catch {
    return null;
  }
}

function safeSet(key, value) {
  try {
    localStorage.setItem(key, value);
  } catch {
    /* private mode */
  }
}

function chime(notes, { step = 0.11, dur = 0.22, type = "triangle", gain = 0.05, at = 0 } = {}) {
  notes.forEach((f, i) => tone(f, dur, { type, gain, at: at + i * step }));
}

export const sfx = {
  card: () => noise(0.09, { gain: 0.08, freq: 3400 }),
  deal: (n = 1) => {
    for (let i = 0; i < n; i++) noise(0.07, { gain: 0.06, freq: 3000 + i * 300, at: i * 0.08 });
  },
  flip: () => {
    noise(0.05, { gain: 0.07, freq: 2600 });
    noise(0.06, { gain: 0.05, freq: 4200, at: 0.07 });
  },
  place: () => {
    noise(0.08, { gain: 0.08, freq: 900 });
    tone(150, 0.08, { type: "sine", gain: 0.05 });
  },
  hop: (i = 0) => tone(520 + (i % 4) * 60, 0.06, { type: "triangle", gain: 0.035 }),
  back: () => tone(300, 0.12, { type: "triangle", gain: 0.04, slide: 0.7 }),
  land: () => {
    tone(196, 0.12, { type: "sine", gain: 0.06 });
    noise(0.06, { gain: 0.05, freq: 700 });
  },
  market: () => {
    chime([1319, 1760], { step: 0.09, dur: 0.18, type: "sine", gain: 0.05 });
    noise(0.12, { gain: 0.04, freq: 5200, at: 0.2 });
  },
  ability: () => chime([523, 659, 880], { step: 0.07, dur: 0.16, type: "sine", gain: 0.045 }),
  reveal: () => chime([392, 587], { step: 0.12, dur: 0.2, type: "triangle", gain: 0.05 }),
  turn: () => chime([659, 880, 1175], { step: 0.1, dur: 0.24, type: "sine", gain: 0.05 }),
  tick: () => tone(1250, 0.03, { type: "square", gain: 0.018 }),
  win: () => {
    chime([523, 659, 784, 1047, 784, 1047], { step: 0.11, dur: 0.24, gain: 0.06 });
    chime([1047, 1319, 1568], { step: 0.09, dur: 0.4, type: "sine", gain: 0.04, at: 0.75 });
  },
  lose: () => chime([392, 349, 311, 262], { step: 0.17, dur: 0.32, gain: 0.05 }),
  sneaky: () => chime([220, 262, 311, 262], { step: 0.14, dur: 0.16, type: "triangle", gain: 0.04 }),
  error: () => tone(170, 0.16, { type: "sawtooth", gain: 0.03 }),
  chat: () => tone(880, 0.07, { gain: 0.03 }),
};
