// All game art: one hidden SVG sprite (monster portraits, equipment, tile landscapes, heroes) drawn with <use>,
// plus small builders for tokens, dice, coins, hearts and icons. Everything is original vector art.
import { s } from "./dom.js";
import { ITEM_ART, ITEM_BOX } from "./items.js";
import { MONSTER_ART, MONSTER_BACKDROP } from "./monsters.js";
import { MAP_VARIANTS, mapMarkup, sceneMarkup } from "./tiles.js";

const INK = "#1d130c";

export const HERO_FILL = {
  red: "#d9483b",
  blue: "#3f7fe0",
  green: "#3fae5a",
  yellow: "#f0c234",
  stone: "#8a8378",
};
const HERO_DARK = { red: "#7a1f16", blue: "#1d3d7a", green: "#1d5a2c", yellow: "#8a6208", stone: "#4a443c" };
const HERO_LIGHT = { red: "#f08a70", blue: "#8ab8f6", green: "#8ad89a", yellow: "#fae08a", stone: "#c8c0b4" };

export const DIE_FILL = {
  green: "#46a04e",
  blue: "#3576cc",
  orange: "#e8781c",
  yellow: "#f2c52f",
  black: "#2e2a28",
  purple: "#7d4cc0",
};
const DIE_LIGHT = { green: "#7fd07a", blue: "#7ab0f0", orange: "#ffb060", yellow: "#fff0a0", black: "#5e5854", purple: "#b08ae8" };
const DIE_DARK = { green: "#24642c", blue: "#1a427e", orange: "#9a4608", yellow: "#a87c0a", black: "#121010", purple: "#45226e" };

export const MONSTER_RING = { blue: "#5a86b0", brown: "#a8743e", green: "#a8b43e" };

const svgBox = (size, vb, ...children) => s("svg", { width: size, height: size, viewBox: vb, class: "ico", "aria-hidden": "true" }, ...children);
const use = (id, attrs = {}) => s("use", { href: `#${id}`, ...attrs });

// ------------------------------------------------------------------ paper grain
let grainUrl = "";
export function grain() {
  if (grainUrl) return grainUrl;
  const size = 160;
  const c = document.createElement("canvas");
  c.width = c.height = size;
  const ctx = c.getContext("2d");
  const img = ctx.createImageData(size, size);
  for (let i = 0; i < img.data.length; i += 4) {
    const v = 110 + Math.random() * 120;
    img.data[i] = v;
    img.data[i + 1] = v * 0.94;
    img.data[i + 2] = v * 0.82;
    img.data[i + 3] = 34 + Math.random() * 40;
  }
  ctx.putImageData(img, 0, 0);
  grainUrl = c.toDataURL();
  document.documentElement.style.setProperty("--grain", `url(${grainUrl})`);
  return grainUrl;
}

// ------------------------------------------------------------------ heroes
const standeeMarkup = (color) => {
  const c = HERO_FILL[color];
  const d = HERO_DARK[color];
  const l = HERO_LIGHT[color];
  const ln = (w) => `stroke="${INK}" stroke-width="${w}" stroke-linejoin="round" stroke-linecap="round"`;
  return `
    <ellipse cx="50" cy="132" rx="30" ry="7.5" fill="#000" opacity=".35"/>
    <ellipse cx="50" cy="129" rx="29" ry="7.5" fill="${d}" ${ln(2.4)}/>
    <path d="M24 128 Q50 136 76 128" fill="none" stroke="${l}" stroke-width="1.6" opacity=".7"/>
    <path d="M31 52 Q16 92 22 126 Q50 132 78 126 Q84 92 69 52 Z" fill="${d}" ${ln(2.4)}/>
    <path d="M38 104 L36 126 H48 L48 104 Z" fill="#5a3a22" ${ln(2.2)}/>
    <path d="M62 104 L64 126 H52 L52 104 Z" fill="#5a3a22" ${ln(2.2)}/>
    <path d="M33 58 Q50 51 67 58 L71 107 Q50 113 29 107 Z" fill="${c}" ${ln(2.4)}/>
    <path d="M50 54 L50 110" stroke="${d}" stroke-width="1.6" opacity=".6"/>
    <path d="M31 90 Q50 95 69 90 L69.6 97 Q50 102 30.4 97 Z" fill="#6a4426" ${ln(1.8)}/>
    <rect x="45" y="89.6" width="10" height="9" rx="2" fill="#e8c04a" ${ln(1.6)}/>
    <path d="M66 62 Q78 64 78 76 L74 80 Q70 70 64 70 Z" fill="${c}" ${ln(2)}/>
    <path d="M73.4 76 L88 26 L93 28 L79 78 Z" fill="#dfe4ea" ${ln(2)}/>
    <path d="M76 74 L89 29" stroke="#fff" stroke-width="1.4" opacity=".8"/>
    <path d="M68 76 L84 82" stroke="${INK}" stroke-width="7" stroke-linecap="round"/>
    <path d="M68 76 L84 82" stroke="#e8c04a" stroke-width="4" stroke-linecap="round"/>
    <circle cx="76" cy="80" r="5" fill="#f0c8a0" ${ln(1.8)}/>
    <circle cx="30" cy="82" r="19" fill="${c}" ${ln(2.6)}/>
    <circle cx="30" cy="82" r="13" fill="none" stroke="${l}" stroke-width="2.4" opacity=".8"/>
    <circle cx="30" cy="82" r="19" fill="none" stroke="#e8c04a" stroke-width="2.2"/>
    <circle cx="30" cy="82" r="5.4" fill="#e8c04a" ${ln(1.8)}/>
    <path d="M23 74 Q26 69 32 68" stroke="#fff" stroke-width="2" fill="none" opacity=".55" stroke-linecap="round"/>
    <circle cx="50" cy="40" r="13.5" fill="#f0c8a0" ${ln(2.2)}/>
    <path d="M38 44 Q50 62 62 44 Q60 54 50 56 Q40 54 38 44 Z" fill="#a8683a" ${ln(1.6)}/>
    <circle cx="45" cy="41" r="1.8" fill="${INK}"/><circle cx="55" cy="41" r="1.8" fill="${INK}"/>
    <path d="M37 34 Q22 30 19 13 Q28 23 39 26 Z" fill="#f2e6c8" ${ln(2)}/>
    <path d="M63 34 Q78 30 81 13 Q72 23 61 26 Z" fill="#f2e6c8" ${ln(2)}/>
    <path d="M35.6 37 Q35 20 50 18 Q65 20 64.4 37 Z" fill="#b8bec8" ${ln(2.2)}/>
    <path d="M35.6 35 Q50 29 64.4 35 L64.4 38.6 Q50 33 35.6 38.6 Z" fill="#e8c04a" ${ln(1.4)}/>
    <path d="M48 34 H52 V46 L50 48 L48 46 Z" fill="#b8bec8" ${ln(1.4)}/>
    <path d="M40 26 Q44 21 50 20.4" stroke="#fff" stroke-width="2" fill="none" opacity=".6" stroke-linecap="round"/>`;
};

const heroBust = (color) => {
  const c = HERO_FILL[color];
  const d = HERO_DARK[color];
  const l = HERO_LIGHT[color];
  const ln = (w) => `stroke="${INK}" stroke-width="${w}" stroke-linejoin="round" stroke-linecap="round"`;
  return `
    <defs><radialGradient id="bust-bg-${color}" cx=".5" cy=".3" r=".75"><stop offset="0" stop-color="${l}"/><stop offset=".7" stop-color="${c}"/><stop offset="1" stop-color="${d}"/></radialGradient></defs>
    <g clip-path="url(#disc-clip)">
      <rect width="100" height="100" fill="url(#bust-bg-${color})"/>
      <path d="M8 104 Q10 74 30 68 L70 68 Q90 74 92 104 Z" fill="${d}" ${ln(2.4)}/>
      <path d="M26 104 Q28 80 40 74 L60 74 Q72 80 74 104 Z" fill="${c}" ${ln(2.2)}/>
      <path d="M40 74 L50 86 L60 74" fill="none" ${ln(1.8)}/>
      <circle cx="50" cy="83" r="3.4" fill="#e8c04a" ${ln(1.4)}/>
      <circle cx="50" cy="52" r="19" fill="#f0c8a0" ${ln(2.4)}/>
      <path d="M33 57 Q50 84 67 57 Q64 72 50 75 Q36 72 33 57 Z" fill="#a8683a" ${ln(2)}/>
      <path d="M43 64 Q50 61 57 64" fill="none" ${ln(1.6)}/>
      <circle cx="43" cy="53" r="2.4" fill="${INK}"/><circle cx="57" cy="53" r="2.4" fill="${INK}"/>
      <path d="M32 44 Q12 40 8 16 Q20 30 34 34 Z" fill="#f2e6c8" ${ln(2.2)}/>
      <path d="M68 44 Q88 40 92 16 Q80 30 66 34 Z" fill="#f2e6c8" ${ln(2.2)}/>
      <path d="M30.6 48 Q29 22 50 20 Q71 22 69.4 48 Z" fill="#b8bec8" ${ln(2.4)}/>
      <path d="M30.6 45 Q50 37 69.4 45 L69.4 50 Q50 42 30.6 50 Z" fill="#e8c04a" ${ln(1.8)}/>
      <path d="M47 44 H53 V60 L50 63 L47 60 Z" fill="#b8bec8" ${ln(1.8)}/>
      <path d="M38 31 Q44 24 52 23" stroke="#fff" stroke-width="2.6" fill="none" opacity=".6" stroke-linecap="round"/>
    </g>`;
};

// ------------------------------------------------------------------ tile frames (banner + name)
const bannerIcon = (id, x, y, sz) => `<use href="#${id}" x="${x - sz / 2}" y="${y - sz / 2}" width="${sz}" height="${sz}"/>`;
const coinMark = (n, x, y, sz = 8.4) =>
  bannerIcon("ic-coin8", x, y, sz) +
  `<text x="${x}" y="${y + 0.3}" text-anchor="middle" dominant-baseline="central" font-size="${sz * 0.6}" font-weight="900" fill="#7a2a08" font-family="Cinzel, serif">${n}</text>`;
const arrow = (x, y) => `<path d="M${x - 2} ${y - 1.8} L${x + 1.6} ${y} L${x - 2} ${y + 1.8} Z" fill="#fff4dc"/>`;

function tileBanner(info) {
  const parts = [];
  switch (info.action) {
    case "market":
      parts.push(coinMark(3, -16.5, 0), arrow(-10.5, 0), bannerIcon("ic-bag", -5, 0, 8.4), `<line x1="0.5" y1="-4" x2="0.5" y2="4" stroke="#fff4dc" stroke-width=".6" opacity=".6"/>`, bannerIcon("ic-bag", 6, 0, 8.4), arrow(11.5, 0), coinMark(2, 17, 0));
      break;
    case "seal":
      parts.push(coinMark(3, -6, 0), arrow(0, 0), bannerIcon("ic-seal", 6.5, 0, 9));
      break;
    case "wall":
      parts.push(coinMark(3, -6, 0), arrow(0, 0), bannerIcon("ic-wall", 6.5, 0, 9));
      break;
    case "trap":
      parts.push(coinMark(3, -14, 0, 7.4), coinMark(5, -6.4, 0, 7.4), coinMark(7, 1.2, 0, 7.4), arrow(7, 0), bannerIcon("ic-trap", 13, 0, 9));
      break;
    case "work":
      parts.push(bannerIcon("ic-hammer", -6, 0, 8.6), arrow(0, 0), coinMark(2, 6.5, 0));
      break;
    case "upgrade":
      parts.push(coinMark(3, -6, 0), arrow(0, 0), bannerIcon("ic-upgrade", 6.5, 0, 9));
      break;
    case "wish":
      parts.push(coinMark(1, -9, 0), arrow(-3, 0), bannerIcon("ic-dice2", 4.6, 0, 10));
      break;
    default:
      return "";
  }
  const half = info.action === "market" || info.action === "trap" ? 23 : 15;
  return `<g transform="translate(0 33.2)">
    <path d="M${-half - 5} -3.4 L${-half} -5.6 L${-half} 5.6 L${-half - 5} 3.4 L${-half - 2.8} 0 Z" fill="#245a52" stroke="${INK}" stroke-width=".8" stroke-linejoin="round"/>
    <path d="M${half + 5} -3.4 L${half} -5.6 L${half} 5.6 L${half + 5} 3.4 L${half + 2.8} 0 Z" fill="#245a52" stroke="${INK}" stroke-width=".8" stroke-linejoin="round"/>
    <rect x="${-half}" y="-6.2" width="${2 * half}" height="12.4" rx="3" fill="#6a4426" stroke="${INK}" stroke-width=".9"/>
    <rect x="${-half + 1.2}" y="-5" width="${2 * half - 2.4}" height="10" rx="2.2" fill="#2f7066" stroke="#e8c870" stroke-width=".55"/>
    ${parts.join("")}
  </g>`;
}

// The scroll must stay inside the hex: neighbouring tiles are drawn over anything that sticks out.
function tileName(info) {
  const label = info.name.replace("Abandoned ", "").replace(" Workshop", "");
  const fs = Math.min(5.3, 44 / (label.length * 0.74));
  const textW = label.length * 0.74 * fs;
  const w = Math.min(50, textW + 9);
  return `<g transform="translate(0 -33.6)">
    <path d="M${-w / 2 - 3} -1 L${-w / 2} -4.4 L${-w / 2} 4 L${-w / 2 - 3} 2.2 Z" fill="#c9a870" stroke="${INK}" stroke-width=".6" stroke-linejoin="round"/>
    <path d="M${w / 2 + 3} -1 L${w / 2} -4.4 L${w / 2} 4 L${w / 2 + 3} 2.2 Z" fill="#c9a870" stroke="${INK}" stroke-width=".6" stroke-linejoin="round"/>
    <rect x="${-w / 2}" y="-4.4" width="${w}" height="8.4" rx="1.6" fill="#f4e6c4" stroke="${INK}" stroke-width=".7"/>
    <text y=".1" text-anchor="middle" dominant-baseline="central" class="tile-name" style="font-size:${fs.toFixed(2)}px"${textW > 44 ? ' textLength="44" lengthAdjust="spacingAndGlyphs"' : ""}>${label}</text>
  </g>`;
}

// ------------------------------------------------------------------ small icon symbols (100×100)
const ICONS = {
  coin8: () => {
    const oct = (r) =>
      Array.from({ length: 8 }, (_, i) => {
        const a = (Math.PI / 8) * (2 * i + 1);
        return `${(50 + r * Math.cos(a)).toFixed(1)},${(50 + r * Math.sin(a)).toFixed(1)}`;
      }).join(" ");
    return `<polygon points="${oct(47)}" fill="#a85a0c" stroke="${INK}" stroke-width="4" stroke-linejoin="round"/>
      <polygon points="${oct(42)}" fill="url(#g-coin)"/>
      <polygon points="${oct(30)}" fill="none" stroke="#c46a10" stroke-width="3.4" opacity=".7"/>
      <path d="M28 30 Q38 22 48 26" stroke="#fff6c8" stroke-width="4" fill="none" stroke-linecap="round" opacity=".8"/>`;
  },
  coin: () => `<use href="#ic-coin8" width="100" height="100"/><path d="M58 36 Q44 30 38 42 Q34 54 46 58 Q56 60 56 52 Q54 46 48 48" fill="none" stroke="#b45a08" stroke-width="5" stroke-linecap="round"/>`,
  bag: () => `<path d="M30 40 Q12 64 18 84 Q26 96 50 96 Q74 96 82 84 Q88 64 70 40 Z" fill="#e8892a" stroke="${INK}" stroke-width="4" stroke-linejoin="round"/>
      <path d="M36 40 L28 18 Q40 26 50 18 Q60 26 72 18 L64 40 Z" fill="#e8892a" stroke="${INK}" stroke-width="4" stroke-linejoin="round"/>
      <path d="M30 40 Q50 46 70 40" fill="none" stroke="${INK}" stroke-width="5"/>
      <path d="M30 40 Q50 46 70 40" fill="none" stroke="#7a3a10" stroke-width="2.4"/>
      <path d="M44 62 Q50 56 56 62 Q60 70 50 74 Q40 70 44 62 Z M50 52 V80" fill="none" stroke="#9a4a10" stroke-width="3.4" stroke-linecap="round"/>
      <path d="M28 66 Q26 78 34 86" stroke="#ffd09a" stroke-width="4" fill="none" stroke-linecap="round" opacity=".8"/>`,
  wall: () => `<path d="M8 34 V16 H24 V26 H40 V16 H60 V26 H76 V16 H92 V34 Z" fill="#b8b0a2" stroke="${INK}" stroke-width="4" stroke-linejoin="round"/>
      <rect x="8" y="34" width="84" height="54" fill="#a8a092" stroke="${INK}" stroke-width="4"/>
      <path d="M8 52 H92 M8 70 H92 M30 34 V52 M62 34 V52 M44 52 V70 M76 52 V70 M24 70 V88 M58 70 V88" stroke="${INK}" stroke-width="3.4"/>
      <path d="M12 38 H28 M34 38 H58 M48 56 H72" stroke="#fff" stroke-width="2.4" opacity=".45"/>`,
  seal: () => `<path d="M50 92 Q14 88 8 50 Q6 20 30 8 Q22 26 26 44 Q34 70 62 72 Q80 72 92 60 Q84 88 50 92 Z" fill="#d8e2e6" stroke="${INK}" stroke-width="4" stroke-linejoin="round"/>
      <path d="M22 40 Q22 58 34 68 M30 54 L36 52 M24 30 L30 32 M44 78 L46 72 M58 80 L58 74 M72 76 L70 70" stroke="#2fa49a" stroke-width="4" fill="none" stroke-linecap="round"/>
      <path d="M16 46 Q16 28 26 18" stroke="#fff" stroke-width="3" fill="none" opacity=".7" stroke-linecap="round"/>`,
  trap: () => `<circle cx="50" cy="56" r="34" fill="none" stroke="${INK}" stroke-width="9"/>
      <circle cx="50" cy="56" r="34" fill="none" stroke="#a8645a" stroke-width="5"/>
      <path d="M18 50 L26 38 L30 50 L36 34 L42 48 L50 30 L58 48 L64 34 L70 50 L74 38 L82 50" fill="#e2e6ea" stroke="${INK}" stroke-width="3.4" stroke-linejoin="round"/>
      <path d="M18 62 L26 74 L30 62 L36 78 L42 64 L50 82 L58 64 L64 78 L70 62 L74 74 L82 62" fill="#e2e6ea" stroke="${INK}" stroke-width="3.4" stroke-linejoin="round"/>
      <rect x="40" y="50" width="20" height="12" rx="4" fill="#6d737c" stroke="${INK}" stroke-width="3"/>`,
  upgrade: () => `<circle cx="50" cy="50" r="42" fill="#e8f4f8" stroke="${INK}" stroke-width="4"/>
      <circle cx="50" cy="50" r="34" fill="#5ab8e0" stroke="#2a7aa8" stroke-width="2"/>
      <path d="M30 44 Q34 26 52 26 Q68 28 70 44" fill="none" stroke="#fff" stroke-width="7" stroke-linecap="round"/>
      <path d="M58 44 L70 58 L80 42 Z" fill="#fff"/>
      <path d="M38 66 Q50 74 62 66" fill="none" stroke="#fff" stroke-width="5" stroke-linecap="round" opacity=".8"/>`,
  shortcut: () => `<circle cx="50" cy="50" r="44" fill="#3a2a6a" stroke="${INK}" stroke-width="4"/>
      <circle cx="50" cy="50" r="38" fill="url(#g-portal)"/>
      <path d="M50 20 A30 30 0 1 1 20 50 A20 20 0 1 0 50 30 A10 10 0 1 1 40 40" fill="none" stroke="#f2ecff" stroke-width="7" stroke-linecap="round"/>`,
  lair: () => `<circle cx="50" cy="50" r="46" fill="#b8c84a" stroke="${INK}" stroke-width="4"/>
      <circle cx="50" cy="50" r="38" fill="#241a14" stroke="#e8f0a8" stroke-width="2.4"/>
      <path d="M26 36 Q50 30 74 36 L68 40 L64 62 L58 42 L50 46 L42 42 L36 62 L32 40 Z" fill="#f4eedc" stroke="${INK}" stroke-width="2.4" stroke-linejoin="round"/>`,
  lair_big: () => `<circle cx="50" cy="50" r="47" fill="#b8c84a" stroke="${INK}" stroke-width="4"/>
      <circle cx="50" cy="50" r="40" fill="none" stroke="#e8f0a8" stroke-width="3"/>
      <circle cx="50" cy="50" r="34" fill="#241a14" stroke="${INK}" stroke-width="2.4"/>
      <path d="M28 38 Q50 32 72 38 L66 42 L62 66 L57 44 L50 48 L43 44 L38 66 L34 42 Z" fill="#f4eedc" stroke="${INK}" stroke-width="2.4" stroke-linejoin="round"/>`,
  hammer: () => `<path d="M46 40 L54 40 L58 94 L42 94 Z" fill="#9a6a3a" stroke="${INK}" stroke-width="4" stroke-linejoin="round"/>
      <path d="M16 16 H70 Q86 20 86 34 V44 H16 Z" fill="#a8adb5" stroke="${INK}" stroke-width="4" stroke-linejoin="round"/>
      <path d="M22 22 H66" stroke="#fff" stroke-width="3" opacity=".6"/>`,
  dice2: () => `<rect x="8" y="26" width="46" height="46" rx="11" fill="${DIE_FILL.green}" stroke="${INK}" stroke-width="4" transform="rotate(-12 31 49)"/>
      <rect x="46" y="30" width="46" height="46" rx="11" fill="${DIE_FILL.green}" stroke="${INK}" stroke-width="4" transform="rotate(10 69 53)"/>
      <path d="M31 36 L35 44 V58 H27 V44 Z M24 58 H38" fill="#fff" stroke="none" transform="rotate(-12 31 49)"/>
      <path d="M69 40 L82 44 Q82 60 69 68 Q56 60 56 44 Z" fill="#fff" transform="rotate(10 69 53)"/>`,
  moon: () => `<path d="M64 10 A42 42 0 1 0 64 90 A32 32 0 1 1 64 10 Z" fill="#f2ecd2" stroke="${INK}" stroke-width="4" stroke-linejoin="round"/>`,
  crater: () => `<circle cx="50" cy="50" r="46" fill="#2a1418" stroke="${INK}" stroke-width="4"/>
      <circle cx="50" cy="50" r="40" fill="url(#g-lava)"/>
      <path d="M50 50 L30 28 M50 50 L76 34 M50 50 L72 74 M50 50 L26 70 M50 50 L50 14 M30 28 L20 36 M76 34 L84 48 M72 74 L60 84" stroke="#ffcf5a" stroke-width="4" fill="none" stroke-linecap="round"/>
      <circle cx="50" cy="50" r="10" fill="#fff2a0"/>`,
  black_moon: () => `<circle cx="50" cy="50" r="44" fill="#7a3aff" opacity=".25"/><circle cx="50" cy="50" r="36" fill="#120a1e" stroke="#b08aff" stroke-width="3.4"/>
      <path d="M30 40 Q50 30 70 40" stroke="#3a2a5a" stroke-width="3" fill="none"/><circle cx="40" cy="58" r="5" fill="#2a1a40"/><circle cx="62" cy="54" r="3.4" fill="#2a1a40"/>`,
  boot: () => `<path d="M30 10 H60 V60 L86 70 Q92 74 90 84 V90 H24 Q22 60 30 10 Z" fill="#8a5a33" stroke="${INK}" stroke-width="4" stroke-linejoin="round"/>
      <path d="M30 22 H60" stroke="#5a3a22" stroke-width="5"/><path d="M24 82 H90" stroke="#5a3a22" stroke-width="5"/>`,
};

// ------------------------------------------------------------------ the sprite
let spriteInstalled = false;

export function installSprite(cat) {
  if (spriteInstalled) return;
  spriteInstalled = true;
  const g = grain();
  const hexPts = Array.from({ length: 6 }, (_, i) => `${(50 * Math.cos((Math.PI / 3) * i)).toFixed(2)},${(50 * Math.sin((Math.PI / 3) * i)).toFixed(2)}`).join(" ");
  const defs = [];
  defs.push(`
    <clipPath id="disc-clip"><circle cx="50" cy="50" r="50"/></clipPath>
    <clipPath id="hex-clip"><polygon points="${hexPts}"/></clipPath>
    <pattern id="grain-pat" patternUnits="userSpaceOnUse" width="60" height="60"><image href="${g}" width="60" height="60"/></pattern>
    <radialGradient id="tile-vig" cx="50%" cy="45%" r="62%"><stop offset=".55" stop-color="#1a1008" stop-opacity="0"/><stop offset="1" stop-color="#1a1008" stop-opacity=".42"/></radialGradient>
    <radialGradient id="map-vig" cx="50%" cy="50%" r="60%"><stop offset=".4" stop-color="#7a5a30" stop-opacity="0"/><stop offset="1" stop-color="#6a4a20" stop-opacity=".45"/></radialGradient>
    <linearGradient id="g-coin" x1="0" y1="0" x2="1" y2="1"><stop offset="0" stop-color="#fff2a0"/><stop offset=".45" stop-color="#f6c638"/><stop offset="1" stop-color="#e08a18"/></linearGradient>
    <radialGradient id="g-portal" cx=".5" cy=".5" r=".5"><stop offset="0" stop-color="#c8a8ff"/><stop offset="1" stop-color="#5a3aa8"/></radialGradient>
    <radialGradient id="g-lava" cx=".5" cy=".5" r=".5"><stop offset="0" stop-color="#ff9a2a"/><stop offset=".6" stop-color="#d8341a"/><stop offset="1" stop-color="#4a0e0a"/></radialGradient>
    <radialGradient id="tok-gloss" cx=".35" cy=".25" r=".7"><stop offset="0" stop-color="#fff" stop-opacity=".38"/><stop offset=".5" stop-color="#fff" stop-opacity="0"/></radialGradient>
    <radialGradient id="tok-vig" cx=".5" cy=".5" r=".5"><stop offset=".7" stop-color="#000" stop-opacity="0"/><stop offset="1" stop-color="#000" stop-opacity=".45"/></radialGradient>
    <linearGradient id="rim-blue" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="#8ab0d4"/><stop offset="1" stop-color="#34557a"/></linearGradient>
    <linearGradient id="rim-brown" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="#c8925a"/><stop offset="1" stop-color="#5a3518"/></linearGradient>
    <linearGradient id="rim-green" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="#d0dc6a"/><stop offset="1" stop-color="#5a6a1a"/></linearGradient>
    <linearGradient id="rim-beast" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="#e8c060"/><stop offset="1" stop-color="#7a3a10"/></linearGradient>
    <linearGradient id="g-heart" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="#f0506a"/><stop offset="1" stop-color="#9a1630"/></linearGradient>
    <linearGradient id="g-heart-empty" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="#8a6ab8"/><stop offset="1" stop-color="#4a3270"/></linearGradient>
    <filter id="glow" x="-50%" y="-50%" width="200%" height="200%"><feGaussianBlur stdDeviation="2.4" result="b"/><feMerge><feMergeNode in="b"/><feMergeNode in="SourceGraphic"/></feMerge></filter>
    <filter id="soft-glow" x="-50%" y="-50%" width="200%" height="200%"><feGaussianBlur stdDeviation="3"/></filter>`);
  for (const color of Object.keys(DIE_FILL)) {
    defs.push(
      `<linearGradient id="dg-${color}" x1="0" y1="0" x2="1" y2="1"><stop offset="0" stop-color="${DIE_LIGHT[color]}"/><stop offset=".45" stop-color="${DIE_FILL[color]}"/><stop offset="1" stop-color="${DIE_DARK[color]}"/></linearGradient>`,
    );
  }
  for (const [k, f] of Object.entries(ICONS)) defs.push(`<symbol id="ic-${k}" viewBox="0 0 100 100">${f()}</symbol>`);
  for (const [k, f] of Object.entries(MONSTER_ART)) {
    const info = cat.monsters?.[k];
    const bd = MONSTER_BACKDROP[k === "beast" ? "beast" : info?.color || "blue"];
    defs.push(`<symbol id="m-${k}" viewBox="0 0 100 100">
      <radialGradient id="mbg-${k}" cx=".5" cy=".32" r=".72"><stop offset="0" stop-color="${bd[0]}"/><stop offset=".62" stop-color="${bd[1]}"/><stop offset="1" stop-color="${bd[2]}"/></radialGradient>
      <g clip-path="url(#disc-clip)"><rect width="100" height="100" fill="url(#mbg-${k})"/>${f()}<rect width="100" height="100" fill="url(#tok-vig)"/></g></symbol>`);
  }
  for (const [k, f] of Object.entries(ITEM_ART)) {
    const kind = cat.equipment?.[k]?.kind || "shield";
    const [w, hh] = ITEM_BOX[kind];
    defs.push(`<symbol id="i-${k}" viewBox="0 0 ${w} ${hh}">${f()}</symbol>`);
  }
  for (const color of Object.keys(HERO_FILL)) {
    defs.push(`<symbol id="hero-${color}" viewBox="0 0 100 140">${standeeMarkup(color)}</symbol>`);
    defs.push(`<symbol id="bust-${color}" viewBox="0 0 100 100">${heroBust(color)}</symbol>`);
  }
  const tileBox = 'viewBox="-50 -43.3 100 86.6"';
  for (const [k, info] of Object.entries(cat.tiles || {})) {
    defs.push(`<symbol id="t-${k}" ${tileBox}><g clip-path="url(#hex-clip)">${sceneMarkup(k)}
      <rect x="-50" y="-44" width="100" height="88" fill="url(#grain-pat)" opacity=".55" style="mix-blend-mode:multiply"/>
      <polygon points="${hexPts}" fill="url(#tile-vig)"/></g>${tileBanner(info)}${tileName(info)}</symbol>`);
  }
  for (let i = 0; i < MAP_VARIANTS; i++) {
    defs.push(`<symbol id="t-map-${i}" ${tileBox}><g clip-path="url(#hex-clip)"><rect x="-50" y="-44" width="100" height="88" fill="#ead6ae"/>
      <rect x="-50" y="-44" width="100" height="88" fill="url(#grain-pat)" opacity=".9" style="mix-blend-mode:multiply"/>${mapMarkup(i)}
      <polygon points="${hexPts}" fill="url(#map-vig)"/></g></symbol>`);
  }
  const holder = document.createElement("div");
  holder.setAttribute("aria-hidden", "true");
  holder.style.cssText = "position:absolute;width:0;height:0;overflow:hidden";
  holder.innerHTML = `<svg xmlns="http://www.w3.org/2000/svg" width="0" height="0"><defs>${defs.join("")}</defs></svg>`;
  document.body.prepend(holder);
}

// ------------------------------------------------------------------ dice
// Each face symbol is drawn in a 0..100 box centred on 50,50.
export function faceSymbol(face, color = "#fff") {
  switch (face) {
    case "sword":
      return s(
        "g",
        { fill: color, stroke: "none" },
        s("path", { d: "M50 6 L59 20 L59 62 L41 62 L41 20 Z" }),
        s("path", { d: "M24 62 H76 Q78 70 70 71 H30 Q22 70 24 62 Z" }),
        s("rect", { x: 44, y: 70, width: 12, height: 17, rx: 2 }),
        s("circle", { cx: 50, cy: 91, r: 6 }),
      );
    case "shield":
      return s("path", { d: "M50 8 L86 19 Q86 66 50 92 Q14 66 14 19 Z", fill: color });
    case "spell":
      return s(
        "g",
        { fill: color },
        s("path", { d: "M50 4 L60 38 L94 50 L60 62 L50 96 L40 62 L6 50 L40 38 Z" }),
        s("circle", { cx: 80, cy: 18, r: 6 }),
        s("circle", { cx: 20, cy: 82, r: 5 }),
      );
    case "claw":
      return s(
        "g",
        { fill: color },
        s("path", { d: "M14 12 Q34 40 28 90 Q22 92 20 86 Q26 46 8 18 Z" }),
        s("path", { d: "M40 6 Q60 40 52 94 Q46 96 44 90 Q50 44 33 12 Z" }),
        s("path", { d: "M66 12 Q86 42 78 90 Q72 92 70 86 Q76 46 59 18 Z" }),
      );
    case "parry":
      return s(
        "g",
        {},
        s("circle", { cx: 50, cy: 50, r: 36, fill: color }),
        s("circle", { cx: 50, cy: 50, r: 22, fill: "none", stroke: "rgba(0,0,0,.45)", "stroke-width": 7 }),
        s("circle", { cx: 50, cy: 50, r: 8, fill: "rgba(0,0,0,.45)" }),
      );
    default:
      return s("g");
  }
}

export function die(color, face, size = 34, extra = {}) {
  const ink = color === "yellow" ? "#5a3c00" : "#fff";
  const cls = ["die", `die-${color}`, face === "blank" ? "blank-face" : "", extra.class || ""].join(" ");
  return s(
    "svg",
    { width: size, height: size, viewBox: "0 0 100 100", class: cls, "data-face": face, "data-die": color },
    s("rect", { x: 5, y: 8, width: 90, height: 88, rx: 22, fill: DIE_DARK[color], stroke: INK, "stroke-width": 4 }),
    s("rect", { x: 5, y: 4, width: 90, height: 86, rx: 22, fill: `url(#dg-${color})`, stroke: INK, "stroke-width": 4 }),
    s("rect", { x: 14, y: 10, width: 72, height: 16, rx: 8, fill: "#fff", opacity: 0.22 }),
    face === "blank" ? null : s("g", { transform: "translate(21 18) scale(.58)", opacity: 0.25 }, faceSymbol(face, "#000")),
    face === "blank" ? null : s("g", { transform: "translate(21 15) scale(.58)" }, faceSymbol(face, ink)),
  );
}

export function faceIcon(face, size = 16, color = "currentColor") {
  return svgBox(size, "0 0 100 100", faceSymbol(face, color));
}

// ------------------------------------------------------------------ small icons
export function coinIcon(size = 16) {
  return svgBox(size, "0 0 100 100", use("ic-coin", { width: 100, height: 100 }));
}

const HEART_D = "M50 90 C18 68 6 50 6 32 C6 16 18 7 31 7 C40 7 46 12 50 20 C54 12 60 7 69 7 C82 7 94 16 94 32 C94 50 82 68 50 90 Z";
export function heartIcon(size = 16, full = true) {
  return svgBox(
    size,
    "0 0 100 100",
    s("path", { d: HEART_D, fill: full ? "url(#g-heart)" : "url(#g-heart-empty)", stroke: INK, "stroke-width": 6, "stroke-linejoin": "round" }),
    full
      ? s("path", { d: "M22 26 Q26 16 36 17", stroke: "#fff", "stroke-width": 7, fill: "none", "stroke-linecap": "round", opacity: 0.7 })
      : s("path", { d: "M26 38 L46 58 M40 28 L64 52 M58 24 L76 42", stroke: "#b8a0e0", "stroke-width": 5, "stroke-linecap": "round", opacity: 0.5 }),
  );
}

export function symbolIcon(symbol, size = 16) {
  const id = { wall: "wall", seal: "seal", trap: "trap", upgrade: "upgrade", shortcut: "shortcut", moon: "moon", bag: "bag", hammer: "hammer", wish: "dice2", lair: "lair", crater: "crater", black_moon: "black_moon", boot: "boot" }[symbol];
  if (symbol === "action") {
    return svgBox(size, "0 0 100 100", s("circle", { cx: 50, cy: 50, r: 40, fill: "#f2c72f", stroke: INK, "stroke-width": 8 }));
  }
  return svgBox(size, "0 0 100 100", id ? use(`ic-${id}`, { width: 100, height: 100 }) : null);
}

export function lairIcon(size, big = false) {
  return svgBox(size, "0 0 100 100", use(big ? "ic-lair_big" : "ic-lair", { width: 100, height: 100 }));
}

// ------------------------------------------------------------------ heroes
export function heroAvatar(color, size = 34) {
  return s("svg", { width: size, height: size, viewBox: "0 0 100 100", class: "avatar-art", "aria-hidden": "true" }, use(`bust-${color in HERO_FILL ? color : "stone"}`, { width: 100, height: 100 }));
}

export function heroFigure(color, height = 60) {
  return s("svg", { width: (height * 100) / 140, height, viewBox: "0 0 100 140", class: "hero-figure", "aria-hidden": "true" }, use(`hero-${color in HERO_FILL ? color : "stone"}`, { width: 100, height: 140 }));
}

// A standee on the board: feet at the origin, about `height` units tall.
export function heroStandee(color, height = 24) {
  const w = (height * 100) / 140;
  return use(`hero-${color in HERO_FILL ? color : "stone"}`, { x: -w / 2, y: -height * 0.93, width: w, height });
}

// ------------------------------------------------------------------ monsters
function heartBadge(n, size) {
  return s(
    "g",
    { class: "m-heart" },
    s("path", { d: HEART_D, transform: `translate(${-size / 2} ${-size / 2}) scale(${size / 100})`, fill: "url(#g-heart)", stroke: "#fff4e0", "stroke-width": 9, "stroke-linejoin": "round" }),
    s("path", { d: HEART_D, transform: `translate(${-size / 2} ${-size / 2}) scale(${size / 100})`, fill: "none", stroke: INK, "stroke-width": 4, "stroke-linejoin": "round" }),
    s(
      "text",
      { y: -size * 0.04, "text-anchor": "middle", "dominant-baseline": "central", "font-size": size * 0.56, class: "m-heart-n" },
      String(n),
    ),
  );
}

function diceChips(info, r) {
  const list = [...Array(info.black).fill("black"), ...Array(info.purple).fill("purple")];
  const sz = r * 0.3;
  const g = s("g", { class: "m-dice" });
  list.forEach((d, i) => {
    const a = Math.PI / 2 - (i - (list.length - 1) / 2) * 0.32 - 0.05;
    const x = Math.cos(a) * r * 0.86 + r * 0.12;
    const y = Math.sin(a) * r * 0.86;
    g.append(s("rect", { x: x - sz / 2, y: y - sz / 2, width: sz, height: sz, rx: sz * 0.3, fill: DIE_FILL[d], stroke: "#fff4e0", "stroke-width": r * 0.035, transform: `rotate(45 ${x} ${y})` }));
  });
  return g;
}

function rewardMarks(info, r) {
  const list = [];
  for (let i = 0; i < info.reward.coins; i++) list.push("coin8");
  for (let i = 0; i < info.reward.equipment; i++) list.push("bag");
  for (let i = 0; i < info.reward.upgrades; i++) list.push("upgrade");
  const g = s("g", { class: "m-reward" });
  const sz = r * (list.length > 4 ? 0.26 : 0.32);
  list.forEach((id, i) => {
    const a = Math.PI + 0.7 - i * (list.length > 4 ? 0.26 : 0.34);
    const x = Math.cos(a) * r * 0.78;
    const y = Math.sin(a) * r * 0.78;
    g.append(use(`ic-${id}`, { x: x - sz / 2, y: y - sz / 2, width: sz, height: sz }));
  });
  return g;
}

// A monster token drawn at the origin with radius r.
export function monsterToken(key, info, r, opts = {}) {
  const big = info.size === "big";
  const beast = info.size === "beast";
  const color = beast ? "beast" : info.color || "blue";
  const g = s("g", { class: `mtoken ${info.size}${opts.selectable ? " selectable" : ""}`, "data-monster": opts.id || key });
  g.append(s("circle", { r: r * 1.04, cy: r * 0.12, fill: "rgba(0,0,0,.5)", class: "m-shadow" }));
  if (opts.selectable) g.append(s("circle", { r: r * 1.22, class: "m-select" }));
  if (beast) {
    const spikes = [];
    for (let i = 0; i < 16; i++) {
      const a = (i / 16) * Math.PI * 2;
      const a2 = a + Math.PI / 16;
      spikes.push(`${(Math.cos(a) * r * 1.2).toFixed(2)},${(Math.sin(a) * r * 1.2).toFixed(2)} ${(Math.cos(a2) * r * 0.96).toFixed(2)},${(Math.sin(a2) * r * 0.96).toFixed(2)}`);
    }
    g.append(s("polygon", { points: spikes.join(" "), fill: "#5a0f08", stroke: INK, "stroke-width": r * 0.05, "stroke-linejoin": "round" }));
  }
  g.append(s("circle", { r, fill: `url(#rim-${color})`, stroke: INK, "stroke-width": r * 0.07 }));
  if (big || beast) g.append(s("circle", { r: r * 0.93, fill: "none", stroke: "#f4dc8a", "stroke-width": r * 0.035, "stroke-dasharray": `${r * 0.08} ${r * 0.1}` }));
  const ri = r * (big || beast ? 0.83 : 0.86);
  g.append(use(`m-${key}`, { x: -ri, y: -ri, width: 2 * ri, height: 2 * ri }));
  g.append(s("circle", { r: ri, fill: "url(#tok-gloss)", stroke: INK, "stroke-width": r * 0.04 }));
  if (opts.detail) {
    g.append(rewardMarks(info, r));
    g.append(diceChips(info, r));
  }
  if (opts.left !== undefined) {
    const hs = r * (opts.detail ? 0.5 : 0.62);
    const hg = heartBadge(opts.left, hs);
    hg.setAttribute("transform", `translate(${(-r * (opts.detail ? 0.62 : 0.66)).toFixed(2)} ${(r * (opts.detail ? 0.5 : 0.62)).toFixed(2)})`);
    if (opts.damage > 0) hg.classList.add("hurt");
    g.append(hg);
  }
  return g;
}

export function monsterBadge(key, info, size = 40, opts = {}) {
  const r = 40;
  const pad = info.size === "beast" ? 10 : 5;
  return s(
    "svg",
    { width: size, height: size, viewBox: `${-r - pad} ${-r - pad} ${2 * (r + pad)} ${2 * (r + pad)}`, class: "mbadge" },
    monsterToken(key, info, r, opts),
  );
}

// ------------------------------------------------------------------ equipment
// Square icon (lists, slots, dialogs). Weapons lean diagonally so they fill the square.
export function itemIcon(key, kind, size = 34, upgraded = false) {
  const svg = s("svg", { width: size, height: size, viewBox: "0 0 100 100", class: `item-ico${upgraded ? " upgraded" : ""}` });
  if (kind === "weapon") svg.append(s("g", { transform: "rotate(40 50 50)" }, use(`i-${key}`, { x: 33, y: -4, width: 34, height: 108 })));
  else if (kind === "elixir") svg.append(use(`i-${key}`, { x: 18, y: 4, width: 64, height: 92 }));
  else svg.append(use(`i-${key}`, { x: 4, y: 4, width: 92, height: 92 }));
  if (upgraded) {
    svg.append(
      s("path", {
        d: "M80 2 L85.5 13 L97.5 14.6 L88.6 23 L91 35 L80 29 L69 35 L71.4 23 L62.5 14.6 L74.5 13 Z",
        fill: "#7fe0ff",
        stroke: INK,
        "stroke-width": 3,
        "stroke-linejoin": "round",
      }),
    );
  }
  return svg;
}

// The item drawn to fill a w×h cell area (backpack): art keeps its natural proportions.
export function itemArt(key, kind, sideways = false) {
  const [w, hh] = ITEM_BOX[kind] || [100, 100];
  if (sideways) {
    return s("svg", { viewBox: `0 0 ${hh} ${w}`, class: "item-art", preserveAspectRatio: "xMidYMid meet" }, s("g", { transform: `translate(0 ${w}) rotate(-90)` }, use(`i-${key}`, { width: w, height: hh })));
  }
  return s("svg", { viewBox: `0 0 ${w} ${hh}`, class: "item-art", preserveAspectRatio: "xMidYMid meet" }, use(`i-${key}`, { width: w, height: hh }));
}

// ------------------------------------------------------------------ rich text: [key] tokens in log lines
export function richText(text, cat) {
  const out = [];
  const re = /\[([a-z_]+)\]/g;
  let last = 0;
  let m;
  while ((m = re.exec(text))) {
    if (m.index > last) out.push(text.slice(last, m.index));
    const key = m[1];
    if (key === "coin") out.push(coinIcon(14));
    else if (cat?.monsters?.[key]) out.push(monsterBadge(key, cat.monsters[key], 20));
    else if (cat?.equipment?.[key]) out.push(itemIcon(key, cat.equipment[key].kind, 18));
    last = re.lastIndex;
  }
  if (last < text.length) out.push(text.slice(last));
  return out;
}
