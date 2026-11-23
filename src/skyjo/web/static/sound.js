// Synthesised sound effects (WebAudio), so there are no audio assets to ship.

let ctx = null;
let muted = localStorage.getItem("skyjo.muted") === "1";
let noiseBuffer = null;

export const isMuted = () => muted;

export function setMuted(value) {
  muted = value;
  localStorage.setItem("skyjo.muted", value ? "1" : "0");
}

// Browsers only start audio after a user gesture.
export function unlockAudio() {
  if (!ctx) {
    const AC = window.AudioContext || window.webkitAudioContext;
    if (!AC) return;
    ctx = new AC();
  }
  if (ctx.state === "suspended") ctx.resume();
}

function ready() {
  return !muted && ctx && ctx.state === "running";
}

function tone(freq, dur, { type = "sine", gain = 0.07, at = 0, slide = 0 } = {}) {
  if (!ready()) return;
  const t = ctx.currentTime + at;
  const osc = ctx.createOscillator();
  const amp = ctx.createGain();
  osc.type = type;
  osc.frequency.setValueAtTime(freq, t);
  if (slide) osc.frequency.exponentialRampToValueAtTime(freq * slide, t + dur);
  amp.gain.setValueAtTime(0.0001, t);
  amp.gain.exponentialRampToValueAtTime(gain, t + 0.01);
  amp.gain.exponentialRampToValueAtTime(0.0001, t + dur);
  osc.connect(amp).connect(ctx.destination);
  osc.start(t);
  osc.stop(t + dur + 0.05);
}

function noise(dur, { gain = 0.06, at = 0, freq = 2500 } = {}) {
  if (!ready()) return;
  if (!noiseBuffer) {
    noiseBuffer = ctx.createBuffer(1, ctx.sampleRate * 0.5, ctx.sampleRate);
    const data = noiseBuffer.getChannelData(0);
    for (let i = 0; i < data.length; i++) data[i] = Math.random() * 2 - 1;
  }
  const t = ctx.currentTime + at;
  const src = ctx.createBufferSource();
  src.buffer = noiseBuffer;
  const filter = ctx.createBiquadFilter();
  filter.type = "bandpass";
  filter.frequency.value = freq;
  filter.Q.value = 0.9;
  const amp = ctx.createGain();
  amp.gain.setValueAtTime(gain, t);
  amp.gain.exponentialRampToValueAtTime(0.0001, t + dur);
  src.connect(filter).connect(amp).connect(ctx.destination);
  src.start(t);
  src.stop(t + dur + 0.05);
}

export const sfx = {
  card: () => noise(0.08, { gain: 0.09, freq: 3200 }),
  place: () => {
    noise(0.05, { gain: 0.08, freq: 1600 });
    tone(200, 0.07, { type: "triangle", gain: 0.05 });
  },
  flip: () => {
    noise(0.05, { gain: 0.07, freq: 4200 });
    tone(520, 0.08, { type: "triangle", gain: 0.035, slide: 1.6 });
  },
  turn: () => {
    tone(660, 0.14, { gain: 0.06 });
    tone(990, 0.24, { gain: 0.06, at: 0.12 });
  },
  clear: () => [523, 659, 784, 1047].forEach((f, i) => tone(f, 0.2, { type: "triangle", gain: 0.06, at: i * 0.07 })),
  alert: () => {
    tone(440, 0.12, { type: "square", gain: 0.03 });
    tone(587, 0.16, { type: "square", gain: 0.03, at: 0.16 });
  },
  round: () => [392, 523, 659].forEach((f, i) => tone(f, 0.28, { gain: 0.05, at: i * 0.1 })),
  win: () =>
    [523, 659, 784, 1047, 784, 1047].forEach((f, i) => tone(f, 0.24, { type: "triangle", gain: 0.06, at: i * 0.11 })),
  lose: () => [392, 349, 311].forEach((f, i) => tone(f, 0.3, { type: "triangle", gain: 0.05, at: i * 0.16 })),
  tick: () => tone(1250, 0.03, { type: "square", gain: 0.018 }),
  error: () => tone(170, 0.16, { type: "sawtooth", gain: 0.03 }),
  chat: () => tone(880, 0.07, { gain: 0.03 }),
  reveal: () => noise(0.3, { gain: 0.05, freq: 2200 }),
};
