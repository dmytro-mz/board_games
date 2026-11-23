// Wide illustrated vistas of Avel Castle: the home banner (night, Black Moon), victory (dawn) and defeat (burning sky).
import { s } from "./dom.js";

const INK = "#10140f";

const SKY = {
  home: ["#0c2a2c", "#1d4a48", "#3f7468"],
  won: ["#36507a", "#d68a6a", "#f6d79a"],
  lost: ["#1a0a10", "#5a1418", "#c2482a"],
};
const HILL = {
  home: ["#173a36", "#1f4a40", "#2b5f48", "#356f4c"],
  won: ["#4a6a66", "#4f7a58", "#5f9050", "#6ea24e"],
  lost: ["#2a1416", "#33201a", "#3d2a1a", "#4a301c"],
};

function rand(seed) {
  let x = seed;
  return () => {
    x = (x * 16807) % 2147483647;
    return x / 2147483647;
  };
}

function stars(n, seed, opacity) {
  const r = rand(seed);
  let out = "";
  for (let i = 0; i < n; i++) {
    const x = r() * 400;
    const y = r() * 90;
    const sz = r() < 0.12 ? 1.4 : 0.7;
    out += `<circle cx="${x.toFixed(1)}" cy="${y.toFixed(1)}" r="${sz}" fill="#fff7dc" opacity="${(opacity * (0.4 + r() * 0.6)).toFixed(2)}"${sz > 1 ? ' class="twinkle"' : ""}/>`;
  }
  return out;
}

function pines(xs, base, h, fill) {
  return xs
    .map((x, i) => {
      const hh = h * (0.75 + ((i * 37) % 10) / 20);
      return `<path d="M${x} ${base - hh} L${x + hh * 0.32} ${base} L${x - hh * 0.32} ${base} Z" fill="${fill}" stroke="${INK}" stroke-width=".8" stroke-linejoin="round"/>`;
    })
    .join("");
}

function tower(x, y, w, hgt, roof, lit) {
  const crenel = Array.from({ length: Math.floor(w / 5) }, (_, i) => `<rect x="${x + i * 5 + 0.6}" y="${y - 3}" width="3" height="3.4" fill="#cdbfa6" stroke="${INK}" stroke-width=".7"/>`).join("");
  return `<rect x="${x}" y="${y}" width="${w}" height="${hgt}" fill="#c8b89c" stroke="${INK}" stroke-width="1.1"/>
    <rect x="${x}" y="${y}" width="${w * 0.32}" height="${hgt}" fill="#a8977c" opacity=".7"/>
    ${roof ? `<path d="M${x - 2.4} ${y} L${x + w / 2} ${y - w * 1.25} L${x + w + 2.4} ${y} Z" fill="${roof}" stroke="${INK}" stroke-width="1.1" stroke-linejoin="round"/><path d="M${x + w / 2} ${y - w * 1.25} L${x + w + 2.4} ${y} L${x + w * 0.62} ${y} Z" fill="#000" opacity=".22"/>` : crenel}
    <rect x="${x + w / 2 - 1.6}" y="${y + hgt * 0.28}" width="3.2" height="5" rx="1.6" fill="${lit}" class="window"/>`;
}

function castle(kind) {
  const lit = kind === "lost" ? "#3a2a22" : "#ffd36a";
  const roofA = kind === "lost" ? "#4a2a26" : "#c0483a";
  const roofB = kind === "lost" ? "#3a2a2a" : "#2f7a72";
  const flag = (x, y, c) => `<path d="M${x} ${y} V${y - 12}" stroke="${INK}" stroke-width="1"/><path d="M${x} ${y - 12} L${x + 9} ${y - 9.6} L${x} ${y - 7.2} Z" fill="${c}" stroke="${INK}" stroke-width=".7" class="flag"/>`;
  return `<g class="castle">
    <path d="M150 116 L150 96 ${Array.from({ length: 20 }, (_, i) => `H${152 + i * 5} V${i % 2 ? 96 : 92}`).join(" ")} H252 V116 Z" fill="#b8a888" stroke="${INK}" stroke-width="1.1"/>
    ${tower(158, 76, 14, 40, roofB, lit)}
    ${tower(228, 76, 14, 40, roofB, lit)}
    <rect x="178" y="70" width="44" height="46" fill="#cfc0a2" stroke="${INK}" stroke-width="1.1"/>
    <rect x="178" y="70" width="12" height="46" fill="#a8977c" opacity=".6"/>
    ${Array.from({ length: 9 }, (_, i) => `<rect x="${178.6 + i * 5}" y="66.6" width="3" height="3.6" fill="#cfc0a2" stroke="${INK}" stroke-width=".7"/>`).join("")}
    <path d="M192 116 V104 Q200 94 208 104 V116 Z" fill="#3a2418" stroke="${INK}" stroke-width="1.1"/>
    <rect x="184" y="80" width="3.4" height="6" rx="1.7" fill="${lit}" class="window"/><rect x="212.6" y="80" width="3.4" height="6" rx="1.7" fill="${lit}" class="window"/>
    ${tower(192, 42, 16, 28, roofA, lit)}
    ${flag(200, 22, kind === "lost" ? "#5a3a3a" : "#e8c065")}${flag(165, 58.5, kind === "lost" ? "#4a3030" : "#d9483b")}${flag(235, 58.5, kind === "lost" ? "#4a3030" : "#3f7fe0")}
    ${kind === "lost" ? `<path d="M150 96 L156 102 L152 108 L158 116 L150 116 Z M246 92 L252 100 L252 116 L244 110 Z" fill="#1a0e0c"/><path d="M214 66 L222 74 L222 66 Z" fill="#1a0e0c"/>` : ""}
  </g>`;
}

function sun(kind) {
  if (kind === "won") {
    return `<circle cx="200" cy="100" r="70" fill="url(#vs-glow-won)"/><circle cx="200" cy="104" r="26" fill="#fff2c0" opacity=".9"/>
      ${Array.from({ length: 14 }, (_, i) => {
        const a = Math.PI + (i / 13) * Math.PI;
        return `<path d="M${200 + Math.cos(a) * 34} ${104 + Math.sin(a) * 34} L${200 + Math.cos(a) * 90} ${104 + Math.sin(a) * 90}" stroke="#fff2c0" stroke-width="3" opacity=".25" stroke-linecap="round"/>`;
      }).join("")}`;
  }
  const big = kind === "lost";
  const cx = big ? 200 : 312;
  const cy = big ? 46 : 46;
  const r = big ? 30 : 24;
  return `<circle cx="${cx}" cy="${cy}" r="${r * 2.6}" fill="url(#vs-glow-${kind})"/>
    <circle cx="${cx}" cy="${cy}" r="${r + 3}" fill="none" stroke="${big ? "#ff9a6a" : "#c8a8ff"}" stroke-width="1.4" opacity=".7" class="corona"/>
    <circle cx="${cx}" cy="${cy}" r="${r}" fill="#120a1e" stroke="${big ? "#ff7a4a" : "#b08aff"}" stroke-width="1.6"/>
    <path d="M${cx - r * 0.6} ${cy - r * 0.2} Q${cx} ${cy - r * 0.55} ${cx + r * 0.6} ${cy - r * 0.2}" stroke="#2e2048" stroke-width="2" fill="none"/>
    <circle cx="${cx - r * 0.3}" cy="${cy + r * 0.25}" r="${r * 0.14}" fill="#22163a"/><circle cx="${cx + r * 0.35}" cy="${cy + r * 0.12}" r="${r * 0.09}" fill="#22163a"/>`;
}

function orbits(kind) {
  if (kind === "won") return "";
  const c = kind === "lost" ? "#ff8a5a" : "#9ad8c8";
  return `<g fill="none" stroke="${c}" stroke-width=".6" opacity=".22">
    <ellipse cx="200" cy="40" rx="180" ry="60"/><ellipse cx="200" cy="40" rx="140" ry="44" stroke-dasharray="2 3"/><ellipse cx="200" cy="40" rx="230" ry="80"/>
  </g>`;
}

export function vista(kind = "home", { heroes = [], beast = false, feet = 166 } = {}) {
  const sky = SKY[kind];
  const hill = HILL[kind];
  const glow = kind === "won" ? "#fff0b0" : kind === "lost" ? "#ff6a3a" : "#8a5aff";
  const svg = s("svg", { viewBox: "0 0 400 170", class: `vista vista-${kind}`, preserveAspectRatio: "xMidYMid slice", "aria-hidden": "true" });
  const heroUses = heroes
    .map((c, i) => {
      const n = heroes.length;
      const x = 200 + (i - (n - 1) / 2) * 26;
      return `<g class="vista-hero" style="animation-delay:${-i * 0.6}s"><ellipse cx="${x}" cy="${feet}" rx="10" ry="2.6" fill="#000" opacity=".35"/><use href="#hero-${c}" x="${x - 15}" y="${feet - 41}" width="30" height="42"/></g>`;
    })
    .join("");
  svg.innerHTML = `
    <defs>
      <linearGradient id="vs-sky-${kind}" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="${sky[0]}"/><stop offset=".62" stop-color="${sky[1]}"/><stop offset="1" stop-color="${sky[2]}"/></linearGradient>
      <radialGradient id="vs-glow-${kind}" cx=".5" cy=".5" r=".5"><stop offset="0" stop-color="${glow}" stop-opacity=".55"/><stop offset="1" stop-color="${glow}" stop-opacity="0"/></radialGradient>
      <linearGradient id="vs-mist-${kind}" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="#fff" stop-opacity="0"/><stop offset="1" stop-color="${kind === "lost" ? "#ff8a5a" : "#e8f4ec"}" stop-opacity=".22"/></linearGradient>
    </defs>
    <rect width="400" height="170" fill="url(#vs-sky-${kind})"/>
    ${kind === "won" ? "" : stars(70, kind === "lost" ? 7 : 3, kind === "lost" ? 0.5 : 1)}
    ${orbits(kind)}
    ${sun(kind)}
    <path d="M0 104 Q40 82 86 92 Q130 100 160 86 Q200 70 240 86 Q290 100 330 84 Q370 72 400 90 V170 H0 Z" fill="${hill[0]}"/>
    ${pines([24, 36, 52, 344, 360, 372, 386], 100, 16, hill[1])}
    <path d="M0 118 Q60 102 120 112 Q150 116 170 112 L230 112 Q260 116 290 110 Q350 100 400 114 V170 H0 Z" fill="${hill[1]}" stroke="${INK}" stroke-width=".8"/>
    <path d="M140 118 Q200 100 260 118 Z" fill="${hill[2]}"/>
    ${castle(kind)}
    <rect y="104" width="400" height="20" fill="url(#vs-mist-${kind})"/>
    ${pines([70, 84, 96, 300, 314, 330, 120, 282], 132, 22, hill[2])}
    <path d="M0 138 Q70 120 150 134 Q200 142 250 134 Q330 120 400 136 V170 H0 Z" fill="${hill[2]}" stroke="${INK}" stroke-width=".9"/>
    <path d="M-10 170 Q60 146 140 156 Q200 162 260 156 Q340 146 410 170 Z" fill="${hill[3]}" stroke="${INK}" stroke-width=".9"/>
    ${beast ? `<g class="vista-beast"><circle cx="200" cy="150" r="22" fill="#000" opacity=".35"/><use href="#m-beast" x="178" y="124" width="44" height="44"/><circle cx="200" cy="146" r="22" fill="none" stroke="#e8c065" stroke-width="2"/></g>` : ""}
    ${heroUses}
    <rect width="400" height="170" fill="url(#grain-pat)" opacity=".5" style="mix-blend-mode:overlay"/>`;
  return svg;
}
