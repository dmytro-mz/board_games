// All artwork is original SVG drawn here: the eight toy troops, the troop tile (a framed token with the strength
// on a tab at the top and the effect as a small badge), the H.Q. fort, medals, the reserve bag and the icons of the
// special bases. Symbols and shared gradients live in one hidden <svg>; tiles <use> them. Army colours come in
// through the CSS variables --army / --army-d / --army-l, so one toy drawing serves both armies; the tile frames
// need real gradients, so they exist once per army (`frame-0`, `frame-1`).

import { h, s } from "/static/shared/dom.js";

export const ARMY = 24;
export const COPIES = 3;
export const sideOf = (t) => Math.floor(t / ARMY);
export const kindOf = (t) => Math.floor((t % ARMY) / COPIES);

export const SIDE_COLORS = [
  { name: "Blue", army: "#2f78e0", dark: "#173f8f", light: "#8fc0ff", ink: "#0d2a63", glow: "#5aa2ff" },
  { name: "Red", army: "#e5483b", dark: "#8f1f18", light: "#ffab9c", ink: "#5f120d", glow: "#ff7a5c" },
];

// The effect of each kind (same order as `troops.KIND_INFO`), drawn as the badge in the tile's corner.
export const KIND_EFFECT = ["", "draw2", "extra", "knock", "airdrop", "snatch", "draw1", ""];

const INK = "#241a33";
const O = `stroke="${INK}" stroke-width="2.4" stroke-linejoin="round" stroke-linecap="round"`;
const o = (w) => `stroke="${INK}" stroke-width="${w}" stroke-linejoin="round" stroke-linecap="round"`;
// An army-coloured shape with volume: flat army fill, then a shading overlay and the outline.
const vol = (d, extra = "") => `<path d="${d}" fill="var(--army)"/><path d="${d}" fill="url(#g-shade)"/><path d="${d}" fill="none" ${O} ${extra}/>`;
const shine = (cx, cy, rx, ry, rot = -25, op = 0.75) => `<ellipse cx="${cx}" cy="${cy}" rx="${rx}" ry="${ry}" fill="#fff" opacity="${op}" transform="rotate(${rot} ${cx} ${cy})"/>`;
const star = (cx, cy, r, fill, stroke = INK, sw = 1.6) => {
  const pts = [];
  for (let i = 0; i < 10; i++) {
    const a = -Math.PI / 2 + (i * Math.PI) / 5;
    const rr = i % 2 ? r * 0.45 : r;
    pts.push(`${(cx + Math.cos(a) * rr).toFixed(2)},${(cy + Math.sin(a) * rr).toFixed(2)}`);
  }
  return `<polygon points="${pts.join(" ")}" fill="${fill}" stroke="${stroke}" stroke-width="${sw}" stroke-linejoin="round"/>`;
};
const eye = (cx, cy, r = 3.2) => `<ellipse cx="${cx}" cy="${cy}" rx="${r * 0.85}" ry="${r}" fill="#1a1222"/><circle cx="${cx + r * 0.3}" cy="${cy - r * 0.4}" r="${r * 0.35}" fill="#fff"/>`;

// ------------------------------------------------------------------ shared paint
const DEFS = `
  <radialGradient id="g-shade" cx=".36" cy=".3" r=".85"><stop offset=".35" stop-color="#000" stop-opacity="0"/><stop offset="1" stop-color="#000" stop-opacity=".42"/></radialGradient>
  <linearGradient id="g-gloss" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="#fff" stop-opacity=".7"/><stop offset=".55" stop-color="#fff" stop-opacity="0"/></linearGradient>
  <linearGradient id="g-tin" x1="0" y1="0" x2=".2" y2="1"><stop offset="0" stop-color="#ffffff"/><stop offset=".45" stop-color="#c9d1db"/><stop offset=".55" stop-color="#aab4c0"/><stop offset="1" stop-color="#6e7886"/></linearGradient>
  <linearGradient id="g-steel" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="#8d96a3"/><stop offset="1" stop-color="#3c4350"/></linearGradient>
  <linearGradient id="g-gold" x1="0" y1="0" x2=".3" y2="1"><stop offset="0" stop-color="#fff4b0"/><stop offset=".4" stop-color="#ffd23f"/><stop offset="1" stop-color="#c98500"/></linearGradient>
  <radialGradient id="g-skin" cx=".4" cy=".35" r=".75"><stop offset="0" stop-color="#fff3e6"/><stop offset=".7" stop-color="#ffd3ad"/><stop offset="1" stop-color="#eaa77c"/></radialGradient>
  <radialGradient id="g-fur" cx=".4" cy=".32" r=".8"><stop offset="0" stop-color="#f0b979"/><stop offset=".65" stop-color="#c47f3f"/><stop offset="1" stop-color="#8a5222"/></radialGradient>
  <radialGradient id="g-muzzle" cx=".45" cy=".35" r=".8"><stop offset="0" stop-color="#fff2dc"/><stop offset="1" stop-color="#e5bc8a"/></radialGradient>
  <radialGradient id="g-frog" cx=".4" cy=".3" r=".85"><stop offset="0" stop-color="#b8f27e"/><stop offset=".6" stop-color="#5cc23c"/><stop offset="1" stop-color="#2c7d23"/></radialGradient>
  <radialGradient id="g-belly" cx=".5" cy=".3" r=".8"><stop offset="0" stop-color="#fbffd8"/><stop offset="1" stop-color="#d4ec8e"/></radialGradient>
  <linearGradient id="g-wood" x1="0" y1="0" x2="1" y2="1"><stop offset="0" stop-color="#e0a464"/><stop offset="1" stop-color="#8a5426"/></linearGradient>
  <linearGradient id="g-fur-black" x1="0" y1="0" x2="1" y2="1"><stop offset="0" stop-color="#5a5d6e"/><stop offset=".5" stop-color="#262833"/><stop offset="1" stop-color="#0d0e14"/></linearGradient>
  <radialGradient id="g-pink" cx=".4" cy=".35" r=".8"><stop offset="0" stop-color="#ffd9e0"/><stop offset="1" stop-color="#ef8aa0"/></radialGradient>
  <linearGradient id="g-paper" x1="0" y1="0" x2="1" y2="1"><stop offset="0" stop-color="#ffffff"/><stop offset="1" stop-color="#dfe7f1"/></linearGradient>
  <linearGradient id="g-paper-d" x1="0" y1="0" x2="1" y2="1"><stop offset="0" stop-color="#d4dde9"/><stop offset="1" stop-color="#a9b6c7"/></linearGradient>
  <linearGradient id="g-glass" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="#36507a"/><stop offset="1" stop-color="#0b1424"/></linearGradient>
  <radialGradient id="g-glow" cx=".5" cy=".5" r=".5"><stop offset="0" stop-color="#e9ffff"/><stop offset=".45" stop-color="#5ff2ff"/><stop offset="1" stop-color="#5ff2ff" stop-opacity="0"/></radialGradient>
  <linearGradient id="g-track" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="#5b6170"/><stop offset="1" stop-color="#22252e"/></linearGradient>
  <linearGradient id="g-white" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="#ffffff"/><stop offset="1" stop-color="#d9dde6"/></linearGradient>
  <linearGradient id="tb-screen" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="#2b3140"/><stop offset="1" stop-color="#11141c"/></linearGradient>
  <pattern id="tb-mesh" width="6" height="6.93" patternUnits="userSpaceOnUse"><path d="M0 3.46 L2 0 H4 L6 3.46 L4 6.93 H2Z" fill="none" stroke="#ffffff" stroke-opacity=".07" stroke-width=".7"/></pattern>
  <radialGradient id="tb-rivet" cx=".35" cy=".3" r=".8"><stop offset="0" stop-color="#ffffff"/><stop offset=".5" stop-color="#b9c2cd"/><stop offset="1" stop-color="#59626f"/></radialGradient>
  <linearGradient id="tb-rim" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="#fff6c4"/><stop offset=".5" stop-color="#e8b53a"/><stop offset="1" stop-color="#9c6a00"/></linearGradient>
  <radialGradient id="g-medal" cx=".38" cy=".32" r=".8"><stop offset="0" stop-color="#fff6b8"/><stop offset=".55" stop-color="#ffc928"/><stop offset="1" stop-color="#c47f00"/></radialGradient>
  ${[0, 1].map(armyDefs).join("")}`;

function armyDefs(side) {
  const c = SIDE_COLORS[side];
  return `
  <linearGradient id="tb-frame-${side}" x1="0" y1="0" x2=".25" y2="1"><stop offset="0" stop-color="${c.light}"/><stop offset=".28" stop-color="${c.army}"/><stop offset="1" stop-color="${c.dark}"/></linearGradient>
  <radialGradient id="tb-glow-${side}" cx=".5" cy=".55" r=".6"><stop offset="0" stop-color="${c.glow}" stop-opacity=".55"/><stop offset="1" stop-color="${c.glow}" stop-opacity="0"/></radialGradient>
  <pattern id="tb-stripes-${side}" width="8" height="8" patternUnits="userSpaceOnUse" patternTransform="rotate(45)"><rect width="8" height="8" fill="${c.army}"/><rect width="4" height="8" fill="${c.dark}"/></pattern>`;
}

// The frame of a troop tile, one per army: plastic body, metal-mesh screen, rivets. The tab is drawn separately on top.
function frameSymbol(side) {
  const c = SIDE_COLORS[side];
  const rivet = (x, y) => `<circle cx="${x}" cy="${y}" r="2.3" fill="url(#tb-rivet)" stroke="${c.dark}" stroke-width=".7"/>`;
  return `
    <rect x="3" y="11" width="94" height="87" rx="15" fill="${c.dark}"/>
    <rect x="3" y="8" width="94" height="87" rx="15" fill="url(#tb-frame-${side})" stroke="${c.dark}" stroke-width="2"/>
    <rect x="5.6" y="10.6" width="88.8" height="81.8" rx="12.6" fill="none" stroke="#fff" stroke-opacity=".38" stroke-width="1.3"/>
    <rect x="11" y="18" width="78" height="69" rx="9" fill="url(#tb-screen)"/>
    <rect x="11" y="18" width="78" height="69" rx="9" fill="url(#tb-mesh)"/>
    <rect x="11" y="18" width="78" height="69" rx="9" fill="url(#tb-glow-${side})"/>
    <rect x="11" y="18" width="78" height="69" rx="9" fill="none" stroke="#000" stroke-opacity=".55" stroke-width="2"/>
    <path d="M12.5 84 h75" stroke="#fff" stroke-opacity=".18" stroke-width="1"/>
    ${rivet(8.6, 14)}${rivet(91.4, 14)}${rivet(8.6, 90.5)}${rivet(91.4, 90.5)}`;
}

function tabSymbol(side) {
  const d = "M30 1.5 H70 Q74 1.5 73 5.5 L69.5 20 Q68.5 24.5 64 24.5 H36 Q31.5 24.5 30.5 20 L27 5.5 Q26 1.5 30 1.5Z";
  return `
    <path d="${d}" fill="#000" opacity=".35" transform="translate(0 2.2)"/>
    <path d="${d}" fill="url(#tb-frame-${side})" stroke="url(#tb-rim)" stroke-width="2.2"/>
    <path d="M31 4.5 H69" stroke="#fff" stroke-opacity=".5" stroke-width="1.4" stroke-linecap="round"/>`;
}

function backSymbol(side) {
  const c = SIDE_COLORS[side];
  return `
    <rect x="3" y="11" width="94" height="87" rx="15" fill="${c.dark}"/>
    <rect x="3" y="8" width="94" height="87" rx="15" fill="url(#tb-frame-${side})" stroke="${c.dark}" stroke-width="2"/>
    <rect x="11" y="16" width="78" height="71" rx="9" fill="url(#tb-stripes-${side})" stroke="#000" stroke-opacity=".4" stroke-width="2"/>
    <circle cx="50" cy="51.5" r="22" fill="${c.dark}" stroke="url(#tb-rim)" stroke-width="3"/>
    ${star(50, 52, 15, "url(#g-gold)", "#7a4f00", 1.6)}
    <rect x="5.6" y="10.6" width="88.8" height="81.8" rx="12.6" fill="none" stroke="#fff" stroke-opacity=".3" stroke-width="1.3"/>`;
}

// ------------------------------------------------------------------ the toys (100 × 100, may overflow a little)
const TOYS = {
  // 0 Jack-in-the-Box: a jester on a spring popping out of a starred box with a crank
  0: `
    <ellipse cx="54" cy="95" rx="36" ry="4" fill="#000" opacity=".35"/>
    <path d="M34 50 L42 22 L94 26 L86 50Z" fill="var(--army-l)" ${O}/>
    <path d="M38 47 L44 28 L88 31" fill="none" stroke="#fff" stroke-opacity=".5" stroke-width="2"/>
    ${vol("M76 56 L90 47 V83 L76 93Z")}
    <path d="M18 56 L32 47 H90 L76 56Z" fill="var(--army-l)" ${O}/>
    <path d="M18 56 L32 47 H90 L76 56Z" fill="url(#g-shade)" opacity=".5"/>
    ${vol("M18 56 H76 V93 H18Z")}
    <path d="M21 60 H73 V70 H21Z" fill="url(#g-gloss)" opacity=".7"/>
    <path d="M18 56 H76 M18 93 H76" stroke="url(#g-gold)" stroke-width="4"/>
    <path d="M18 56 H76 M18 93 H76" stroke="${INK}" stroke-width="1" opacity=".5"/>
    ${star(47, 75, 12, "url(#g-gold)")}
    <path d="M90 66 H98" stroke="${INK}" stroke-width="5.5" stroke-linecap="round"/><path d="M90 66 H98" stroke="url(#g-tin)" stroke-width="3" stroke-linecap="round"/>
    <path d="M98 66 V55" stroke="${INK}" stroke-width="5.5" stroke-linecap="round"/><path d="M98 66 V55" stroke="url(#g-tin)" stroke-width="3" stroke-linecap="round"/>
    <circle cx="98" cy="53" r="4.2" fill="#e5483b" ${o(1.8)}/>${shine(96.8, 51.6, 1.6, 1, -30, 0.8)}
    <path d="M48 52 c-10 -2 -10 -6 0 -7 c10 -1 10 -5 0 -6 c-10 -1 -10 -5 0 -6 c10 -1 10 -5 0 -6" fill="none" stroke="${INK}" stroke-width="5" stroke-linecap="round"/>
    <path d="M48 52 c-10 -2 -10 -6 0 -7 c10 -1 10 -5 0 -6 c-10 -1 -10 -5 0 -6 c10 -1 10 -5 0 -6" fill="none" stroke="url(#g-tin)" stroke-width="2.6" stroke-linecap="round"/>
    <path d="M30 31 q4 -6 9 -2 q3 -6 9 -2 q4 -6 9 -1 q5 -4 9 2 q-4 8 -18 8 q-14 0 -18 -5z" fill="url(#g-white)" ${o(1.8)}/>
    <circle cx="48" cy="19" r="12.5" fill="url(#g-skin)" ${O}/>
    <path d="M36 14 C30 2 22 -2 12 2 C20 4 24 10 26 16Z" fill="var(--army)" ${o(2)}/>
    <path d="M36 14 C30 2 22 -2 12 2 C20 4 24 10 26 16Z" fill="url(#g-shade)"/>
    <path d="M60 14 C66 2 74 -3 85 0 C77 4 72 10 70 16Z" fill="url(#g-gold)" ${o(2)}/>
    <path d="M35 15 Q48 -2 61 15 Q48 9 35 15Z" fill="var(--army-l)" ${o(2)}/>
    <path d="M35 15 Q48 9 61 15" fill="none" stroke="url(#g-gold)" stroke-width="3"/>
    <circle cx="12" cy="3" r="4.4" fill="url(#g-gold)" ${o(1.8)}/><circle cx="85.5" cy="0.5" r="4.4" fill="var(--army)" ${o(1.8)}/>
    ${shine(10.8, 1.8, 1.5, 1, -30, 0.9)}${shine(84.3, -0.7, 1.5, 1, -30, 0.7)}
    ${eye(43.5, 19, 2.6)}${eye(53, 19, 2.6)}
    <circle cx="39.5" cy="25" r="2.6" fill="#ff8f8f" opacity=".7"/><circle cx="57" cy="25" r="2.6" fill="#ff8f8f" opacity=".7"/>
    <path d="M41.5 24.5 Q48.2 33 55 24.5 Q48.2 27 41.5 24.5Z" fill="#a3172b" ${o(1.6)}/>
    <path d="M44.5 27.6 Q48.2 30.4 52 27.6" fill="#ff7b8e"/>
    <circle cx="48.2" cy="22" r="2.6" fill="#ff5252" ${o(1.2)}/>${shine(43.5, 11, 4, 2, -20, 0.55)}`,

  // 1 Wind-up Mouse: a tin mouse on wheels with a big golden key
  1: `
    <ellipse cx="52" cy="94" rx="36" ry="4" fill="#000" opacity=".35"/>
    <path d="M86 76 c12 -2 14 -14 6 -18 c-6 -3 -10 3 -6 6" fill="none" stroke="${INK}" stroke-width="4.5" stroke-linecap="round"/>
    <path d="M86 76 c12 -2 14 -14 6 -18 c-6 -3 -10 3 -6 6" fill="none" stroke="#f3a6b6" stroke-width="2.4" stroke-linecap="round"/>
    <rect x="60.5" y="26" width="7" height="18" rx="2" fill="url(#g-gold)" ${o(2)}/>
    <path d="M64 27 C52 26 46 14 52 8 C58 4 63 14 64 22 C65 14 70 4 76 8 C82 14 76 26 64 27Z" fill="url(#g-gold)" ${O}/>
    <path d="M55 12 Q58 16 60 21 M73 12 Q70 16 68 21" fill="none" stroke="#fff" stroke-opacity=".7" stroke-width="1.6" stroke-linecap="round"/>
    <path d="M20 70 C18 52 36 40 58 42 C80 44 92 60 88 76 C86 86 74 89 56 89 H30 C22 89 20 80 20 70Z" fill="url(#g-tin)" ${O}/>
    <path d="M40 46 C52 41 70 43 80 52 L74 58 C64 52 50 50 42 54Z" fill="var(--army)" ${o(2)}/>
    <path d="M40 46 C52 41 70 43 80 52 L74 58 C64 52 50 50 42 54Z" fill="url(#g-gloss)"/>
    <path d="M28 80 Q56 86 86 76" fill="none" stroke="${INK}" stroke-width="1.4" opacity=".45"/>
    <circle cx="44" cy="80" r="1.3" fill="${INK}" opacity=".55"/><circle cx="56" cy="82" r="1.3" fill="${INK}" opacity=".55"/><circle cx="68" cy="81" r="1.3" fill="${INK}" opacity=".55"/>
    ${shine(60, 60, 14, 5, -12, 0.55)}
    <circle cx="34" cy="38" r="12" fill="url(#g-tin)" ${O}/><circle cx="34.5" cy="38.5" r="7.5" fill="url(#g-pink)" ${o(1.4)}/>
    <path d="M30 52 C30 44 18 46 8 62 C14 68 24 70 34 68Z" fill="url(#g-tin)" ${O}/>
    <circle cx="7.5" cy="62" r="4.3" fill="#ff6f8d" ${o(1.8)}/>${shine(6.3, 60.6, 1.6, 1, -30, 0.9)}
    ${eye(22, 55, 3)}
    <path d="M10 66 L0 70 M11 63 L0 62 M12 68 L3 75" stroke="${INK}" stroke-width="1.2" stroke-linecap="round"/>
    <circle cx="38" cy="88" r="6.5" fill="url(#g-steel)" ${o(2)}/><circle cx="38" cy="88" r="2" fill="#d9dee6"/>
    <circle cx="70" cy="88" r="6.5" fill="url(#g-steel)" ${o(2)}/><circle cx="70" cy="88" r="2" fill="#d9dee6"/>`,

  // 2 Tin Drummer: a toy soldier with a tall fur hat and a drum
  2: `
    <ellipse cx="50" cy="95" rx="32" ry="4.5" fill="#2f6b2a" ${o(1.8)}/>
    <path d="M34 2 C34 -4 62 -4 62 2 V27 H34Z" fill="url(#g-fur-black)" ${O}/>
    <path d="M39 4 Q40 14 39 24 M46 2 Q47 14 46 25 M53 2 Q54 14 53 25" fill="none" stroke="#fff" stroke-opacity=".14" stroke-width="2"/>
    <path d="M60 4 C66 -2 70 2 66 8 L62 12Z" fill="var(--army)" ${o(1.8)}/>
    <path d="M33 25 H63" stroke="url(#g-gold)" stroke-width="4.5" stroke-linecap="round"/>
    <circle cx="48" cy="32" r="10" fill="url(#g-skin)" ${O}/>
    <circle cx="41.5" cy="35.5" r="3" fill="#ff6b6b" opacity=".75"/><circle cx="54.5" cy="35.5" r="3" fill="#ff6b6b" opacity=".75"/>
    ${eye(44.5, 31, 1.9)}${eye(51.5, 31, 1.9)}
    <path d="M43 37.5 Q48 40.5 53 37.5" fill="none" stroke="${INK}" stroke-width="1.5" stroke-linecap="round"/>
    <path d="M38 33 Q48 46 58 33" fill="none" stroke="url(#g-gold)" stroke-width="1.6"/>
    <path d="M40 66 V86 H47 V66Z M49 66 V86 H56 V66Z" fill="url(#g-white)" ${o(2)}/>
    <path d="M38 86 H48 V92 H36 Q36 87 38 86Z M48 86 H58 Q60 87 60 92 H48Z" fill="#191b24" ${o(1.8)}/>
    ${vol("M35 44 Q48 39 61 44 L62 68 H34Z")}
    <path d="M37 45 L59 66 M59 45 L37 66" stroke="url(#g-white)" stroke-width="3.6"/>
    <path d="M37 45 L59 66 M59 45 L37 66" stroke="${INK}" stroke-width=".8" opacity=".35"/>
    <circle cx="48" cy="55.5" r="2.4" fill="url(#g-gold)" ${o(1)}/>
    <path d="M34 64 H62" stroke="url(#g-gold)" stroke-width="3.5"/>
    <path d="M29 47 Q35 41 40 44 L38 49Z M67 47 Q61 41 56 44 L58 49Z" fill="url(#g-gold)" ${o(1.6)}/>
    <path d="M35 47 Q26 54 30 64" fill="none" stroke="${INK}" stroke-width="7.5" stroke-linecap="round"/>
    <path d="M35 47 Q26 54 30 64" fill="none" stroke="var(--army)" stroke-width="4.6" stroke-linecap="round"/>
    <path d="M61 47 Q72 44 76 36" fill="none" stroke="${INK}" stroke-width="7.5" stroke-linecap="round"/>
    <path d="M61 47 Q72 44 76 36" fill="none" stroke="var(--army)" stroke-width="4.6" stroke-linecap="round"/>
    <path d="M52 64 H90 V82 Q71 89 52 82Z" fill="var(--army)" ${O}/>
    <path d="M52 64 H90 V82 Q71 89 52 82Z" fill="url(#g-shade)"/>
    <path d="M53 66 l6 13 6 -13 6 13 6 -13 6 13 6 -13" fill="none" stroke="url(#g-gold)" stroke-width="2.2" stroke-linejoin="round"/>
    <path d="M52 81 Q71 88 90 81" fill="none" stroke="url(#g-gold)" stroke-width="3.5"/>
    <ellipse cx="71" cy="64" rx="19" ry="6" fill="url(#g-white)" ${O}/>
    <ellipse cx="71" cy="64" rx="19" ry="6" fill="none" stroke="url(#g-gold)" stroke-width="2.4"/>
    <circle cx="30" cy="64" r="4" fill="url(#g-white)" ${o(1.6)}/><circle cx="76.5" cy="35.5" r="4" fill="url(#g-white)" ${o(1.6)}/>
    <path d="M31 63 L60 58" stroke="${INK}" stroke-width="4.6" stroke-linecap="round"/><path d="M31 63 L60 58" stroke="#d9a15d" stroke-width="2.6" stroke-linecap="round"/>
    <path d="M77 35 L72 58" stroke="${INK}" stroke-width="4.6" stroke-linecap="round"/><path d="M77 35 L72 58" stroke="#d9a15d" stroke-width="2.6" stroke-linecap="round"/>
    <circle cx="60.5" cy="58" r="2.8" fill="#fff3d6" ${o(1.3)}/><circle cx="71.8" cy="58.6" r="2.8" fill="#fff3d6" ${o(1.3)}/>
    <path d="M80 50 l4 -3 M82 55 l5 -1 M60 52 l-2 -4" stroke="#ffd23f" stroke-width="1.8" stroke-linecap="round"/>`,

  // 3 Slingshot Frog: a glossy frog with an army bandana, slingshot drawn
  3: `
    <ellipse cx="46" cy="94" rx="36" ry="4" fill="#000" opacity=".35"/>
    <path d="M10 88 C4 92 8 96 16 95 L30 94 L28 86Z M82 88 C88 92 84 96 76 95 L62 94 L64 86Z" fill="url(#g-frog)" ${o(2)}/>
    <path d="M46 34 C20 34 10 56 12 74 C14 88 28 94 46 94 C64 94 78 88 80 74 C82 56 72 34 46 34Z" fill="url(#g-frog)" ${O}/>
    <path d="M46 56 C32 56 26 66 27 76 C28 86 36 90 46 90 C56 90 64 86 65 76 C66 66 60 56 46 56Z" fill="url(#g-belly)" ${o(1.6)}/>
    <path d="M30 70 H40 M28 77 H39 M52 70 H62 M53 77 H64" stroke="#a9c96a" stroke-width="1.4" stroke-linecap="round"/>
    <circle cx="30" cy="32" r="12" fill="url(#g-frog)" ${O}/><circle cx="62" cy="32" r="12" fill="url(#g-frog)" ${O}/>
    <circle cx="30" cy="32" r="8" fill="#fff" ${o(1.4)}/><circle cx="62" cy="32" r="8" fill="#fff" ${o(1.4)}/>
    <circle cx="33" cy="32" r="4.4" fill="#1a1222"/><circle cx="65" cy="32" r="4.4" fill="#1a1222"/>
    <circle cx="34.5" cy="30.4" r="1.6" fill="#fff"/><circle cx="66.5" cy="30.4" r="1.6" fill="#fff"/>
    <path d="M21 25 Q30 19 39 25 M53 25 Q62 19 71 25" fill="none" stroke="${INK}" stroke-width="2" stroke-linecap="round"/>
    <path d="M20 41 C30 46 62 46 72 41 L74 49 C62 54 30 54 18 49Z" fill="var(--army)" ${o(2)}/>
    <path d="M20 41 C30 46 62 46 72 41 L73 44 C62 49 30 49 19 44Z" fill="#fff" opacity=".35"/>
    <path d="M18 47 L8 54 L16 56Z" fill="var(--army)" ${o(1.8)}/>
    <path d="M30 54 Q46 64 62 54" fill="none" stroke="${INK}" stroke-width="2.4" stroke-linecap="round"/>
    <circle cx="27" cy="54" r="3" fill="#ff8f8f" opacity=".6"/><circle cx="65" cy="54" r="3" fill="#ff8f8f" opacity=".6"/>
    ${shine(28, 42, 7, 3, -30, 0.35)}
    <path d="M86 6 L82 30 M100 10 L88 32" stroke="${INK}" stroke-width="6.5" stroke-linecap="round"/>
    <path d="M86 6 L82 30 M100 10 L88 32" stroke="url(#g-wood)" stroke-width="3.8" stroke-linecap="round"/>
    <path d="M85 30 L84 46" stroke="${INK}" stroke-width="6.5" stroke-linecap="round"/><path d="M85 30 L84 46" stroke="url(#g-wood)" stroke-width="3.8" stroke-linecap="round"/>
    <path d="M86 7 L70 20 L99 11" fill="none" stroke="var(--army)" stroke-width="2.2" stroke-linecap="round"/>
    <circle cx="70" cy="20" r="4.6" fill="url(#g-steel)" ${o(1.6)}/>${shine(68.8, 18.6, 1.6, 1, -30, 0.8)}
    <path d="M74 62 C82 58 86 52 85 44" fill="none" stroke="${INK}" stroke-width="9" stroke-linecap="round"/>
    <path d="M74 62 C82 58 86 52 85 44" fill="none" stroke="#5cc23c" stroke-width="5.8" stroke-linecap="round"/>
    <circle cx="85" cy="43" r="4.4" fill="url(#g-frog)" ${o(1.8)}/>
    <path d="M18 62 C10 66 12 76 20 74" fill="none" stroke="${INK}" stroke-width="9" stroke-linecap="round"/>
    <path d="M18 62 C10 66 12 76 20 74" fill="none" stroke="#5cc23c" stroke-width="5.8" stroke-linecap="round"/>`,

  // 4 Paper Plane: a folded plane with army stripes and a roundel, swooshing in
  4: `
    <path d="M2 74 C14 76 22 70 30 62" fill="none" stroke="#fff" stroke-width="3" stroke-dasharray="5 4" stroke-linecap="round" opacity=".7"/>
    <path d="M0 58 H14 M4 46 H18 M8 86 H22" stroke="#fff" stroke-width="2.6" stroke-linecap="round" opacity=".55"/>
    <ellipse cx="58" cy="95" rx="28" ry="3.5" fill="#000" opacity=".3"/>
    <path d="M46 62 L98 8 L52 86Z" fill="url(#g-paper-d)" ${O}/>
    <path d="M46 62 L98 8 L58 66 L56 92Z" fill="url(#g-paper-d)" ${O}/>
    <path d="M14 52 L98 8 L46 62Z" fill="url(#g-paper)" ${O}/>
    <path d="M46 62 L98 8 L70 60Z" fill="url(#g-paper)" ${O}/>
    <path d="M22 51 L90 14" stroke="var(--army)" stroke-width="4.5" stroke-linecap="round"/>
    <path d="M30 53 L88 18" stroke="var(--army-d)" stroke-width="1.6" stroke-linecap="round" opacity=".7"/>
    <path d="M60 60 L92 18" stroke="var(--army)" stroke-width="4" stroke-linecap="round"/>
    <circle cx="40" cy="47" r="7" fill="#fff" ${o(1.8)}/><circle cx="40" cy="47" r="4.4" fill="var(--army)"/><circle cx="40" cy="47" r="1.8" fill="#fff"/>
    <path d="M18 51 L60 30" stroke="#fff" stroke-width="1.6" stroke-linecap="round" opacity=".9"/>`,

  // 5 Magnet Bot: a tin robot with a glass visor holding up a big horseshoe magnet
  5: `
    <ellipse cx="44" cy="95" rx="32" ry="4" fill="#000" opacity=".35"/>
    <path d="M42 18 V8" stroke="${INK}" stroke-width="3.6"/><path d="M42 18 V8" stroke="url(#g-tin)" stroke-width="1.8"/>
    <circle cx="42" cy="6" r="4.4" fill="var(--army)" ${o(1.8)}/>${shine(40.8, 4.6, 1.6, 1, -30, 0.9)}
    <rect x="22" y="16" width="40" height="28" rx="9" fill="url(#g-tin)" ${O}/>
    <rect x="27" y="22" width="30" height="15" rx="7.5" fill="url(#g-glass)" ${o(1.6)}/>
    <circle cx="35" cy="29.5" r="5" fill="url(#g-glow)"/><circle cx="49" cy="29.5" r="5" fill="url(#g-glow)"/>
    <circle cx="35" cy="29.5" r="2" fill="#fff"/><circle cx="49" cy="29.5" r="2" fill="#fff"/>
    <path d="M29 24 Q42 20 55 24" fill="none" stroke="#fff" stroke-opacity=".35" stroke-width="1.6" stroke-linecap="round"/>
    <rect x="17" y="25" width="5" height="10" rx="2" fill="url(#g-steel)" ${o(1.6)}/><rect x="62" y="25" width="5" height="10" rx="2" fill="url(#g-steel)" ${o(1.6)}/>
    <rect x="37" y="44" width="10" height="5" fill="url(#g-steel)" ${o(1.4)}/>
    <path d="M28 76 L26 88 H36 L38 76Z M50 76 L52 88 H62 L60 76Z" fill="url(#g-steel)" ${o(2)}/>
    <path d="M22 88 H38 Q40 93 36 94 H22 Q18 93 22 88Z M50 88 H66 Q70 93 66 94 H52 Q48 93 50 88Z" fill="#2a2d38" ${o(1.8)}/>
    <rect x="18" y="48" width="48" height="31" rx="8" fill="url(#g-tin)" ${O}/>
    <rect x="25" y="54" width="22" height="18" rx="4" fill="url(#g-glass)" ${o(1.4)}/>
    <circle cx="31" cy="60" r="2.4" fill="#ffd23f"/><circle cx="38" cy="60" r="2.4" fill="#63f08a"/><path d="M28 67 H44" stroke="#5ff2ff" stroke-width="1.8" stroke-linecap="round"/>
    <circle cx="56" cy="63" r="5.6" fill="var(--army)" ${o(1.8)}/>${shine(54.6, 61.4, 2, 1.2, -30, 0.85)}
    ${shine(28, 51, 8, 2, -5, 0.6)}
    <path d="M18 58 Q8 66 14 76" fill="none" stroke="${INK}" stroke-width="7" stroke-linecap="round"/>
    <path d="M18 58 Q8 66 14 76" fill="none" stroke="url(#g-tin)" stroke-width="4.2" stroke-linecap="round"/>
    <circle cx="14.5" cy="77.5" r="4.2" fill="url(#g-steel)" ${o(1.6)}/>
    <path d="M64 56 Q76 52 76 42" fill="none" stroke="${INK}" stroke-width="7" stroke-linecap="round"/>
    <path d="M64 56 Q76 52 76 42" fill="none" stroke="url(#g-tin)" stroke-width="4.2" stroke-linecap="round"/>
    <path d="M62 34 V18 A18 18 0 0 1 98 18 V34 H88 V18 A8 8 0 0 0 72 18 V34Z" fill="var(--army)" ${O}/>
    <path d="M62 34 V18 A18 18 0 0 1 98 18 V34 H88 V18 A8 8 0 0 0 72 18 V34Z" fill="url(#g-shade)"/>
    <path d="M66 17 A14 14 0 0 1 80 4" fill="none" stroke="#fff" stroke-opacity=".55" stroke-width="2.4" stroke-linecap="round"/>
    <rect x="62" y="31" width="10" height="8" rx="1" fill="url(#g-tin)" ${o(1.8)}/><rect x="88" y="31" width="10" height="8" rx="1" fill="url(#g-tin)" ${o(1.8)}/>
    <circle cx="76" cy="41" r="4.2" fill="url(#g-steel)" ${o(1.6)}/>
    <path d="M60 46 l-4 5 M67 50 v6 M93 46 l4 5 M86 50 v6 M80 48 v8" stroke="#ffd23f" stroke-width="2" stroke-linecap="round"/>`,

  // 6 Teddy Bear: a stitched plush bear with an army bow and a heart patch
  6: `
    <ellipse cx="50" cy="95" rx="36" ry="4" fill="#000" opacity=".35"/>
    <circle cx="25" cy="16" r="10.5" fill="url(#g-fur)" ${O}/><circle cx="25" cy="16" r="5.4" fill="url(#g-muzzle)"/>
    <circle cx="75" cy="16" r="10.5" fill="url(#g-fur)" ${O}/><circle cx="75" cy="16" r="5.4" fill="url(#g-muzzle)"/>
    <path d="M24 72 C22 56 34 48 50 48 C66 48 78 56 76 72 C75 86 64 92 50 92 C36 92 25 86 24 72Z" fill="url(#g-fur)" ${O}/>
    <ellipse cx="28" cy="88" rx="11" ry="7.5" fill="url(#g-fur)" ${O}/><ellipse cx="72" cy="88" rx="11" ry="7.5" fill="url(#g-fur)" ${O}/>
    <ellipse cx="28" cy="89" rx="6" ry="4.2" fill="url(#g-muzzle)"/><ellipse cx="72" cy="89" rx="6" ry="4.2" fill="url(#g-muzzle)"/>
    <path d="M50 66 C40 58 34 66 38 72 C41 77 50 82 50 82 C50 82 59 77 62 72 C66 66 60 58 50 66Z" fill="var(--army)" ${o(2)}/>
    <path d="M50 66 C40 58 34 66 38 72 C41 77 50 82 50 82 C50 82 59 77 62 72 C66 66 60 58 50 66Z" fill="none" stroke="#fff" stroke-opacity=".8" stroke-width="1" stroke-dasharray="2 1.8" transform="translate(50 70) scale(.82) translate(-50 -70)"/>
    ${shine(42, 66, 3, 1.6, -30, 0.7)}
    <path d="M24 62 C12 58 8 66 12 72 C15 76 22 74 27 70Z" fill="url(#g-fur)" ${O}/>
    <path d="M76 62 C88 58 92 66 88 72 C85 76 78 74 73 70Z" fill="url(#g-fur)" ${O}/>
    <circle cx="50" cy="33" r="23" fill="url(#g-fur)" ${O}/>
    <path d="M62 15 L66 21 M65 14 L63 22" stroke="${INK}" stroke-width="1.2" opacity=".6"/>
    <ellipse cx="50" cy="42" rx="11.5" ry="9" fill="url(#g-muzzle)" ${o(1.8)}/>
    <path d="M45 37 Q50 33 55 37 Q55 42 50 42 Q45 42 45 37Z" fill="#2a1710" ${o(1)}/>${shine(48.4, 37, 1.8, 1, -20, 0.8)}
    <path d="M50 42 V45 M44 46 Q50 51 56 46" fill="none" stroke="${INK}" stroke-width="1.8" stroke-linecap="round"/>
    <circle cx="40" cy="29" r="3.6" fill="#1a1222"/><circle cx="60" cy="29" r="3.6" fill="#1a1222"/>
    <circle cx="41.2" cy="27.6" r="1.3" fill="#fff"/><circle cx="61.2" cy="27.6" r="1.3" fill="#fff"/>
    <circle cx="35" cy="38" r="3" fill="#ff8f8f" opacity=".5"/><circle cx="65" cy="38" r="3" fill="#ff8f8f" opacity=".5"/>
    ${vol("M50 56 L36 49 Q33 56 36 63Z")}${vol("M50 56 L64 49 Q67 56 64 63Z")}
    <circle cx="50" cy="56" r="4" fill="var(--army-d)" ${o(1.8)}/>
    ${shine(40, 18, 7, 3, -25, 0.35)}`,

  // 7 Tin Tank: a chunky wind-up tank with a star, a long gun and a pennant
  7: `
    <ellipse cx="50" cy="95" rx="46" ry="4" fill="#000" opacity=".35"/>
    <path d="M20 30 V8" stroke="${INK}" stroke-width="2.6"/><path d="M20 8 L34 12 L20 17Z" fill="var(--army)" ${o(1.6)}/>
    <rect x="56" y="34" width="40" height="8" rx="2.5" fill="url(#g-steel)" ${O}/>
    <rect x="92" y="31.5" width="8" height="13" rx="2" fill="url(#g-steel)" ${o(2)}/>
    <path d="M58 36 H92" stroke="#fff" stroke-opacity=".4" stroke-width="1.4"/>
    ${vol("M24 50 C24 32 36 24 50 24 C64 24 72 32 72 50Z")}
    <path d="M30 40 C32 31 40 27 49 27" fill="none" stroke="#fff" stroke-opacity=".55" stroke-width="3" stroke-linecap="round"/>
    <ellipse cx="48" cy="24" rx="9" ry="3.6" fill="var(--army-d)" ${o(1.8)}/>
    ${vol("M6 50 H94 L88 68 H12Z")}
    <path d="M9 53 H91" stroke="#fff" stroke-opacity=".45" stroke-width="2"/>
    ${star(50, 59, 7.5, "#fff", INK, 1.4)}
    <circle cx="18" cy="58" r="1.6" fill="${INK}" opacity=".6"/><circle cx="82" cy="58" r="1.6" fill="${INK}" opacity=".6"/>
    <rect x="2" y="66" width="96" height="27" rx="13.5" fill="url(#g-track)" ${O}/>
    <path d="M9 68 H91 M9 91 H91" stroke="#8e95a3" stroke-width="1.4" stroke-dasharray="3 3"/>
    ${[16, 34, 50, 66, 84].map((x) => `<circle cx="${x}" cy="79.5" r="7.6" fill="url(#g-tin)" ${o(1.8)}/><circle cx="${x}" cy="79.5" r="2.4" fill="#4a505d"/>`).join("")}`,
};

// Little white glyphs for the troop effect badges (100 × 100).
const FX_TROOP = {
  draw2: `<rect x="8" y="30" width="32" height="42" rx="7" fill="none" stroke="#fff" stroke-width="7"/><rect x="26" y="20" width="32" height="42" rx="7" fill="#161a24" stroke="#fff" stroke-width="7"/><path d="M62 52 H82 M72 42 V62" stroke="#7dff8a" stroke-width="8" stroke-linecap="round"/><text x="80" y="92" text-anchor="middle" font-family="Fredoka, sans-serif" font-weight="700" font-size="40" fill="#7dff8a">2</text>`,
  draw1: `<rect x="22" y="22" width="40" height="52" rx="8" fill="none" stroke="#fff" stroke-width="7"/><path d="M62 66 H90 M76 52 V80" stroke="#7dff8a" stroke-width="9" stroke-linecap="round"/>`,
  extra: `<rect x="35" y="35" width="30" height="34" rx="6" fill="#fff"/><path d="M78 40 A30 30 0 1 0 80 62" fill="none" stroke="#fff" stroke-width="7" stroke-linecap="round"/><path d="M90 30 L80 46 L66 34Z" fill="#fff"/>`,
  knock: `<rect x="22" y="20" width="48" height="58" rx="9" fill="none" stroke="#fff" stroke-width="7"/><path d="M50 50 L88 88 M88 50 L50 88" stroke="#161a24" stroke-width="20" stroke-linecap="round"/><path d="M50 50 L88 88 M88 50 L50 88" stroke="#ff5a4a" stroke-width="10" stroke-linecap="round"/>`,
  airdrop: `<path d="M12 46 A38 34 0 0 1 88 46 Q76 38 63 46 Q50 36 37 46 Q24 38 12 46Z" fill="#fff"/><path d="M14 46 L44 72 M37 46 L46 70 M63 46 L54 70 M86 46 L56 72" stroke="#fff" stroke-width="4"/><rect x="40" y="68" width="20" height="22" rx="4" fill="#fff"/>`,
  snatch: `<path d="M16 54 V38 A34 34 0 0 1 84 38 V54 H64 V38 A14 14 0 0 0 36 38 V54Z" fill="#ff5a4a" stroke="#fff" stroke-width="5" stroke-linejoin="round"/><rect x="16" y="54" width="20" height="16" fill="#fff"/><rect x="64" y="54" width="20" height="16" fill="#fff"/><path d="M26 82 v10 M50 78 v14 M74 82 v10" stroke="#ffd23f" stroke-width="6" stroke-linecap="round"/>`,
};

const SYMBOLS = {
  // ---------------------------------------------------------------- the H.Q.: a toy-block castle
  fort: `
    <ellipse cx="50" cy="94" rx="46" ry="5" fill="#000" opacity=".35"/>
    <path d="M24 92 V46 H76 V92Z" fill="var(--army)" ${O}/>
    <path d="M24 92 V46 H76 V92Z" fill="url(#g-shade)"/>
    <path d="M24 60 H76 M24 74 H76 M37 46 V60 M63 46 V60 M50 60 V74 M37 74 V92 M63 74 V92" stroke="var(--army-d)" stroke-width="1.6" opacity=".7"/>
    <path d="M24 46 V38 H32 V44 H40 V38 H48 V44 H52 V38 H60 V44 H68 V38 H76 V46Z" fill="var(--army-l)" ${o(2.2)}/>
    <path d="M38 92 V74 A12 12 0 0 1 62 74 V92Z" fill="#2a1d14" ${o(2.2)}/>
    <path d="M41 92 V75 A9 9 0 0 1 59 75 V92" fill="none" stroke="url(#g-gold)" stroke-width="2"/>
    <path d="M42 80 H58 M42 86 H58" stroke="#5a3b22" stroke-width="1.6"/>
    ${vol("M4 92 V36 H24 V92Z")}${vol("M76 92 V36 H96 V92Z")}
    <path d="M7 40 V88 M79 40 V88" stroke="#fff" stroke-opacity=".4" stroke-width="2.4" stroke-linecap="round"/>
    <path d="M2 36 V26 H8 V31 H12 V26 H16 V31 H20 V26 H26 V36Z M74 36 V26 H80 V31 H84 V26 H88 V31 H92 V26 H98 V36Z" fill="var(--army-l)" ${o(2.2)}/>
    <path d="M10 52 A4 4 0 0 1 18 52 V62 H10Z M82 52 A4 4 0 0 1 90 52 V62 H82Z" fill="#fff6c8" ${o(1.8)}/>
    <path d="M50 38 V6" stroke="${INK}" stroke-width="3.4" stroke-linecap="round"/><path d="M50 38 V6" stroke="url(#g-tin)" stroke-width="1.6" stroke-linecap="round"/>
    <path d="M51 6 Q62 4 72 10 Q62 14 51 16Z" fill="url(#g-gold)" ${o(2)}/>
    <circle cx="50" cy="5" r="3" fill="url(#g-gold)" ${o(1.4)}/>
    ${star(50, 54, 6, "url(#g-gold)", INK, 1.4)}`,
  medal: `
    <path d="M30 2 H45 L54 30 H39Z" fill="#3e7fd6" stroke="${INK}" stroke-width="2.4" stroke-linejoin="round"/>
    <path d="M70 2 H55 L46 30 H61Z" fill="#e5483b" stroke="${INK}" stroke-width="2.4" stroke-linejoin="round"/>
    <path d="M36 2 L44 28 M64 2 L56 28" stroke="#fff" stroke-opacity=".5" stroke-width="2"/>
    <circle cx="50" cy="61" r="33" fill="url(#g-medal)" stroke="${INK}" stroke-width="3"/>
    <circle cx="50" cy="61" r="25" fill="none" stroke="#a86a00" stroke-width="2.4" opacity=".7"/>
    <circle cx="50" cy="61" r="25" fill="none" stroke="#fff5b8" stroke-width="1.4" stroke-dasharray="3 3" opacity=".7"/>
    ${star(50, 62, 17, "url(#g-gold)", "#9a5f00", 2)}
    ${shine(38, 44, 9, 4, -35, 0.6)}`,
  // a region's medal on the board: ribbon and a plain coin, the number is written over it
  "medal-plain": `
    <path d="M28 0 H44 L54 32 H38Z" fill="#3e7fd6" stroke="${INK}" stroke-width="3" stroke-linejoin="round"/>
    <path d="M72 0 H56 L46 32 H62Z" fill="#e5483b" stroke="${INK}" stroke-width="3" stroke-linejoin="round"/>
    <circle cx="50" cy="62" r="34" fill="url(#g-medal)" stroke="${INK}" stroke-width="4"/>
    <circle cx="50" cy="62" r="26" fill="none" stroke="#a86a00" stroke-width="2.6" opacity=".6"/>
    ${shine(37, 45, 9, 4, -35, 0.6)}`,
  bag: `
    <ellipse cx="50" cy="94" rx="34" ry="4" fill="#000" opacity=".3"/>
    <path d="M34 34 h32 q24 18 20 42 q-4 18 -36 18 q-32 0 -36 -18 q-4 -24 20 -42z" fill="#c3874f" ${O}/>
    <path d="M34 34 h32 q24 18 20 42 q-4 18 -36 18 q-32 0 -36 -18 q-4 -24 20 -42z" fill="url(#g-shade)"/>
    <path d="M32 26 q18 -14 36 0 l-6 9 h-24z" fill="#9a6232" ${O}/>
    <path d="M30 36 q20 9 40 0" stroke="${INK}" stroke-width="8.5" fill="none" stroke-linecap="round"/>
    <path d="M30 36 q20 9 40 0" stroke="var(--army)" stroke-width="5.5" fill="none" stroke-linecap="round"/>
    ${star(50, 66, 11, "var(--army)", INK, 1.8)}
    ${shine(32, 56, 6, 3, -60, 0.35)}`,
  bin: `
    <ellipse cx="50" cy="94" rx="30" ry="4" fill="#000" opacity=".3"/>
    <path d="M22 30 h56 l-6 62 h-44z" fill="url(#g-tin)" ${O}/>
    <path d="M36 40 l2 44 M50 40 v44 M64 40 l-2 44" stroke="${INK}" stroke-width="2.4" opacity=".45"/>
    <rect x="16" y="20" width="68" height="10" rx="4" fill="url(#g-tin)" ${O}/>
    <rect x="40" y="12" width="20" height="8" rx="3" fill="url(#g-tin)" ${O}/>`,
  // special base icons, one per terrain effect
  "fx-recall": `<path d="M16 46 h68 v40 h-68z" fill="url(#g-wood)" ${o(4)}/><path d="M12 28 h76 v18 h-76z" fill="#d18a4a" ${o(4)}/><path d="M16 60 H84" stroke="#5c3416" stroke-width="3"/><rect x="43" y="38" width="14" height="16" rx="2" fill="url(#g-gold)" ${o(3)}/>`,
  "fx-draw": `<circle cx="50" cy="52" r="32" fill="#d9a35b" ${o(4)}/><circle cx="50" cy="52" r="32" fill="url(#g-shade)"/><circle cx="38" cy="42" r="5" fill="#5a3416"/><circle cx="60" cy="38" r="4.4" fill="#5a3416"/><circle cx="62" cy="62" r="5" fill="#5a3416"/><circle cx="40" cy="66" r="4.4" fill="#5a3416"/><circle cx="52" cy="52" r="3.4" fill="#5a3416"/>`,
  "fx-move": `<path d="M50 10 c16 16 26 28 26 46 a26 26 0 0 1 -52 0 c0 -10 6 -18 10 -24 c2 8 6 12 10 12 c-2 -12 0 -24 6 -34z" fill="#ff7a1a" ${o(4)}/><path d="M50 50 c7 7 11 11 11 18 a11 11 0 0 1 -22 0 c0 -7 6 -11 11 -18z" fill="#ffd54a"/>`,
  "fx-revive": `<path d="M24 86 V44 A26 26 0 0 1 76 44 V86 L67 78 L58 86 L50 78 L42 86 L33 78Z" fill="#eef1ff" ${o(4)}/><circle cx="40" cy="46" r="5" fill="${INK}"/><circle cx="60" cy="46" r="5" fill="${INK}"/><ellipse cx="50" cy="62" rx="5" ry="6" fill="${INK}"/>`,
  "fx-shield": `<path d="M50 8 L84 20 V48 C84 70 68 84 50 92 C32 84 16 70 16 48 V20Z" fill="#6fe3ff" ${o(4)}/><path d="M50 18 L74 27 V48 C74 64 63 74 50 80Z" fill="#fff" opacity=".45"/><path d="M28 74 L72 30" stroke="#ff5a4a" stroke-width="9" stroke-linecap="round"/>`,
  "fx-snipe": `<circle cx="50" cy="50" r="34" fill="none" stroke="#ff5a4a" stroke-width="7"/><circle cx="50" cy="50" r="18" fill="none" stroke="#ff5a4a" stroke-width="5"/><path d="M50 6 V30 M50 70 V94 M6 50 H30 M70 50 H94" stroke="${INK}" stroke-width="7" stroke-linecap="round"/><circle cx="50" cy="50" r="5" fill="#ff5a4a"/>`,
  "fx-restrict": `<circle cx="50" cy="50" r="34" fill="none" stroke="#ff6b6b" stroke-width="14"/><circle cx="50" cy="50" r="34" fill="none" stroke="#fff" stroke-width="14" stroke-dasharray="17.8 17.8"/><circle cx="50" cy="50" r="41" fill="none" stroke="${INK}" stroke-width="2.5"/><circle cx="50" cy="50" r="27" fill="none" stroke="${INK}" stroke-width="2.5"/>`,
  sand: `<path d="M8 92 q8 -30 42 -32 q34 2 42 32z" fill="#e8c27a" stroke="#9c7533" stroke-width="3"/><circle cx="34" cy="80" r="3" fill="#c49a52"/><circle cx="60" cy="74" r="2.6" fill="#c49a52"/><circle cx="70" cy="84" r="2" fill="#c49a52"/>`,
};
const FIT = { 0: "translate(9 13) scale(.86)", 2: "translate(11 16) scale(.8)", 5: "translate(4 8) scale(.92)" };
for (const [k, body] of Object.entries(TOYS)) SYMBOLS[`toy-${k}`] = FIT[k] ? `<g transform="${FIT[k]}">${body}</g>` : body;
for (const [k, body] of Object.entries(FX_TROOP)) SYMBOLS[`fxt-${k}`] = body;
for (const side of [0, 1]) {
  SYMBOLS[`frame-${side}`] = frameSymbol(side);
  SYMBOLS[`tab-${side}`] = tabSymbol(side);
  SYMBOLS[`back-${side}`] = backSymbol(side);
}

export function installArt() {
  if (document.getElementById("toybattle-art")) return;
  const symbols = Object.entries(SYMBOLS)
    .map(([id, body]) => `<symbol id="${id}" viewBox="0 0 100 100" overflow="visible">${body}</symbol>`)
    .join("");
  const holder = h("div", { class: "defs-holder", id: "toybattle-art", "aria-hidden": "true" });
  holder.innerHTML = `<svg xmlns="http://www.w3.org/2000/svg"><defs>${DEFS}</defs>${symbols}</svg>`;
  document.body.prepend(holder);
}

export function armyStyle(side) {
  const c = SIDE_COLORS[side] || SIDE_COLORS[0];
  return { "--army": c.army, "--army-d": c.dark, "--army-l": c.light, "--army-ink": c.ink };
}

export function icon(id, cls = "", side = 0, title = null) {
  return s("svg", { class: `art ${cls}`, viewBox: "0 0 100 100", style: armyStyle(side), "aria-hidden": title ? null : "true" }, title ? s("title", {}, title) : null, s("use", { href: `#${id}` }));
}

export const strengthLabel = (kind) => (kind === 0 ? "★" : String(kind));

// The face of a troop as one SVG: frame, the toy on its screen, the strength tab, the effect badge.
function tileFace(side, kind) {
  const fx = KIND_EFFECT[kind];
  return s(
    "svg",
    { class: "face", viewBox: "0 0 100 100", "aria-hidden": "true" },
    s("use", { href: `#frame-${side}` }),
    s("svg", { x: 4, y: 12, width: 92, height: 86, viewBox: "0 0 100 100", overflow: "visible", preserveAspectRatio: "xMidYMid meet" }, s("use", { href: `#toy-${kind}` })),
    s("use", { href: `#tab-${side}` }),
    kind === 0
      ? s("g", { class: "tab-star" }, s("path", { d: starPath(50, 13, 8.6), fill: "#fff", stroke: SIDE_COLORS[side].ink, "stroke-width": 1.6, "stroke-linejoin": "round" }))
      : s("text", { class: "tab-n", x: 50, y: 13.6, "text-anchor": "middle", "dominant-baseline": "central", stroke: SIDE_COLORS[side].ink }, String(kind)),
    fx
      ? s(
          "g",
          { class: "fx-badge" },
          s("circle", { cx: 84, cy: 83, r: 12.5, fill: "#161a24", stroke: "url(#tb-rim)", "stroke-width": 2.4 }),
          s("use", { href: `#fxt-${fx}`, x: 75.5, y: 74.5, width: 17, height: 17 }),
        )
      : null,
  );
}

function starPath(cx, cy, r) {
  let d = "";
  for (let i = 0; i < 10; i++) {
    const a = -Math.PI / 2 + (i * Math.PI) / 5;
    const rr = i % 2 ? r * 0.45 : r;
    d += `${i ? "L" : "M"}${(cx + Math.cos(a) * rr).toFixed(2)} ${(cy + Math.sin(a) * rr).toFixed(2)} `;
  }
  return `${d}Z`;
}

// A troop tile (HTML wrapper around the SVG face): army colours, sizes and states come from CSS.
export function troopTile(troop, { kinds, cls = "", key = true, extra = {} } = {}) {
  const side = sideOf(troop);
  const kind = kindOf(troop);
  const info = kinds?.[kind];
  const name = info?.name || "";
  return h(
    "div",
    {
      class: `troop k${kind} s${side} ${cls}`,
      "data-key": key ? `t${troop}` : null,
      "data-troop": troop,
      style: armyStyle(side),
      title: name ? `${name} (${kind === 0 ? "joker" : `strength ${kind}`})${info?.title ? ` · ${info.title}: ${info.text}` : ""}` : null,
      ...extra,
    },
    tileFace(side, kind),
  );
}

// A face-down troop of the opponent's rack.
export function troopBack(side, key, cls = "") {
  return h("div", { class: `troop back s${side} ${cls}`, "data-key": key, style: armyStyle(side) }, s("svg", { class: "face", viewBox: "0 0 100 100", "aria-hidden": "true" }, s("use", { href: `#back-${side}` })));
}

// Log text: "{t:side:kind}" becomes a small troop chip.
export function richText(text, kinds) {
  const parts = [];
  const re = /\{t:(\d):(\d)\}/g;
  let last = 0;
  let m;
  while ((m = re.exec(text))) {
    if (m.index > last) parts.push(text.slice(last, m.index));
    const side = Number(m[1]);
    const kind = Number(m[2]);
    parts.push(
      h(
        "span",
        { class: `chip-troop s${side}`, style: armyStyle(side), title: kinds?.[kind]?.name || "" },
        s("svg", { viewBox: "-4 -4 108 108", "aria-hidden": "true" }, s("use", { href: `#toy-${kind}` })),
        h("b", {}, strengthLabel(kind)),
        kinds?.[kind] ? h("span", { class: "chip-name" }, kinds[kind].name) : null,
      ),
    );
    last = re.lastIndex;
  }
  if (last < text.length) parts.push(text.slice(last));
  return parts;
}
