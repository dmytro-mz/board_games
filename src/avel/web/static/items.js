// Equipment art as SVG markup. Weapons are drawn upright in a 40×120 box (they fill a 1×3 backpack strip),
// elixirs in 50×100 (1×2), shields and helmets in 100×100 (2×2).

const INK = "#1d130c";
const ln = (w) => `stroke="${INK}" stroke-width="${w}" stroke-linejoin="round" stroke-linecap="round"`;
const P = (d, f, w = 2) => `<path d="${d}" fill="${f}"${w ? ` ${ln(w)}` : ""}/>`;
const C = (x, y, r, f, w = 2) => `<circle cx="${x}" cy="${y}" r="${r}" fill="${f}"${w ? ` ${ln(w)}` : ""}/>`;
const LN = (d, w = 2, c = INK, o = 1) =>
  `<path d="${d}" fill="none" stroke="${c}" stroke-width="${w}" stroke-linecap="round" stroke-linejoin="round"${o < 1 ? ` opacity="${o}"` : ""}/>`;
const HI = (d, o = 0.45) => `<path d="${d}" fill="#fff" opacity="${o}"/>`;
const SH = (d, o = 0.2) => `<path d="${d}" fill="#14080a" opacity="${o}"/>`;
const dots = (list, f, r = 1.6) => list.map(([x, y]) => C(x, y, r, f, 0)).join("");

const STEEL = "#cfd5dd";
const STEEL_DARK = "#8d96a3";
const GOLD = "#d9a93e";
const WOOD = "#8a5a33";
const GRIP = "#5a3a1e";

const grip = (y0, y1) => P(`M17.5 ${y0} H22.5 V${y1} H17.5 Z`, GRIP, 1.6) + LN(Array.from({ length: Math.floor((y1 - y0) / 5) }, (_, i) => `M17.5 ${y0 + 2 + i * 5} L22.5 ${y0 + 4.5 + i * 5}`).join(" "), 1, "#c9a064");

// ------------------------------------------------------------------ weapons (40×120)
const WEAPONS = {
  battle_axe: () =>
    [
      P("M18 26 L22 26 L22.8 114 L17.2 114 Z", WOOD, 1.8),
      LN("M17.6 94 L22.4 97 M17.6 100 L22.4 103 M17.6 106 L22.4 109", 1.4, "#3a2414"),
      P("M18 15 Q3 11 1 30 Q3 49 18 45 Z", STEEL, 1.8),
      P("M22 15 Q37 11 39 30 Q37 49 22 45 Z", STEEL, 1.8),
      LN("M4 22 Q2 30 4 38 M36 22 Q38 30 36 38", 1.6, "#fff", 0.8),
      SH("M18 30 Q8 32 4 40 Q8 46 18 45 Z M22 30 Q32 32 36 40 Q32 46 22 45 Z", 0.16),
      P("M17 15 L20 1 L23 15 Z", STEEL, 1.6),
      P("M15.6 13 H24.4 V47 H15.6 Z", "#6c727c", 1.6),
      dots([[20, 20], [20, 30], [20, 40]], GOLD, 1.5),
      C(20, 115.5, 3.2, GOLD, 1.4),
    ].join(""),
  long_sword: () =>
    [
      P("M17 86 L17 13 L20 2 L23 13 L23 86 Z", STEEL, 1.8),
      LN("M20 10 L20 82", 1.4, STEEL_DARK),
      HI("M17.8 84 L17.8 14 L19.4 6 L19.4 84 Z", 0.5),
      P("M5 85 Q20 89 35 85 L35 91 Q20 94 5 91 Z", GOLD, 1.6),
      grip(92, 108),
      C(20, 111.5, 4, GOLD, 1.6),
    ].join(""),
  broad_sword: () =>
    [
      P("M12.5 80 L12.5 17 L20 3 L27.5 17 L27.5 80 Z", STEEL, 1.8),
      P("M18.4 14 L18.4 76 L21.6 76 L21.6 14 L20 10 Z", STEEL_DARK, 0),
      HI("M13.6 78 L13.6 18 L18 9 L17.4 78 Z", 0.45),
      P("M3 79 Q10 74 20 79 Q30 74 37 79 L33 86 H7 Z", "#b88a3a", 1.6),
      C(20, 82, 2.6, "#d6453a", 1.2),
      grip(86, 104),
      P("M15 104 H25 L23 111 H17 Z", "#b88a3a", 1.4),
    ].join(""),
  morning_star: () => {
    const spikes = Array.from({ length: 8 }, (_, i) => {
      const a = (i / 8) * Math.PI * 2;
      const x = 20 + Math.cos(a) * 12;
      const y = 22 + Math.sin(a) * 12;
      const tx = 20 + Math.cos(a) * 19;
      const ty = 22 + Math.sin(a) * 19;
      const px = Math.cos(a + Math.PI / 2) * 3.4;
      const py = Math.sin(a + Math.PI / 2) * 3.4;
      return P(`M${(x + px).toFixed(1)} ${(y + py).toFixed(1)} L${tx.toFixed(1)} ${ty.toFixed(1)} L${(x - px).toFixed(1)} ${(y - py).toFixed(1)} Z`, STEEL, 1.4);
    }).join("");
    return [
      P("M17.4 34 H22.6 V114 H17.4 Z", "#7a5232", 1.8),
      LN("M17.4 44 H22.6 M17.4 48 H22.6", 1.6, GOLD),
      grip(94, 112),
      spikes,
      C(20, 22, 12.5, "#7d838c", 1.8),
      HI("M12 18 Q14 12 22 11 Q16 14 15 20 Z", 0.5),
      C(20, 115.5, 3, GOLD, 1.2),
    ].join("");
  },
  hand_axe: () =>
    [
      P("M18 30 L22 30 L22.6 112 L17.4 112 Z", WOOD, 1.8),
      LN("M17.6 92 L22.4 95 M17.6 98 L22.4 101 M17.6 104 L22.4 107", 1.4, "#3a2414"),
      P("M18 18 Q3 13 1 33 Q3 54 18 50 Z", STEEL, 1.8),
      LN("M4 24 Q2 33 4 44", 1.6, "#fff", 0.8),
      SH("M18 34 Q8 36 4 44 Q8 52 18 50 Z", 0.16),
      P("M16 16 H24 V50 H16 Z", "#6c727c", 1.6),
      P("M24 24 L33 28 L24 34 Z", STEEL, 1.4),
      dots([[20, 24], [20, 42]], GOLD, 1.4),
    ].join(""),
  dagger: () =>
    [
      P("M16.4 76 L16.4 36 L20 22 L23.6 36 L23.6 76 Z", STEEL, 1.8),
      LN("M20 32 L20 72", 1.2, STEEL_DARK),
      HI("M17.2 74 L17.2 37 L19.4 28 L19.4 74 Z", 0.5),
      P("M8 75 Q20 80 32 75 L31 80 Q20 84 9 80 Z", "#9a6a3a", 1.6),
      grip(80, 96),
      C(20, 99.5, 3.6, "#9a6a3a", 1.4),
      C(20, 99.5, 1.4, "#6ad0e0", 0),
    ].join(""),
};

// ------------------------------------------------------------------ shields (100×100)
const HEATER = "M50 5 L89 15 Q91 60 50 95 Q9 60 11 15 Z";
const HEATER_IN = "M50 12 L82 20 Q83 58 50 87 Q17 58 18 20 Z";
const rim = (inner, outer = "#8a8f98") => P(HEATER, outer, 2.2) + P(HEATER_IN, inner, 1.6);
const roundRim = (inner, outer = "#8a8f98") => C(50, 50, 44, outer, 2.2) + C(50, 50, 37, inner, 1.6);

const SHIELDS = {
  wolf_shield: () =>
    [
      rim("#3f8f4c"),
      HI("M22 22 L50 14 L50 30 Q34 28 24 40 Z", 0.18),
      P("M37 38 L34 21 L44 30 Q50 28 56 30 L66 21 L63 38 Q64 54 50 66 Q36 54 37 38 Z", "#e6eaee", 1.8),
      P("M44 54 Q50 52 56 54 Q55 62 50 66 Q45 62 44 54 Z", "#bfc6cf", 1.2),
      P("M47 55 Q50 54 53 55 Q52 57.6 50 57.6 Q48 57.6 47 55 Z", INK, 0),
      P("M41 41 L47 43 L42 45 Z", INK, 0) + P("M59 41 L53 43 L58 45 Z", INK, 0),
      dots([[50, 9], [20, 18], [80, 18], [16, 50], [84, 50]], "#e2e6ea", 1.6),
    ].join(""),
  knight_shield: () =>
    [
      rim("#3c5fa8", "#c9a64a"),
      P("M50 12 L82 20 Q83 34 82 47 L50 47 Z", "#e6eaef", 0),
      P("M50 47 L18 47 Q20 70 50 87 Z", "#e6eaef", 0),
      P(HEATER_IN, "none", 1.6),
      P("M46 14 H54 V43 H80 V51 H54 V86 L50 88 L46 86 V51 H20 V43 H46 Z", "#d9a93e", 1.6),
      C(50, 47, 5, "#d6453a", 1.4),
      HI("M22 22 L46 15 L46 30 Q32 30 24 38 Z", 0.16),
    ].join(""),
  wooden_shield: () =>
    [
      rim("#a8723e", "#6d737c"),
      LN("M34 16 Q33 56 38 80 M50 12 L50 87 M66 16 Q67 56 62 80", 1.6, "#5a3a1e"),
      LN("M26 30 Q28 34 26 38 M42 52 Q44 56 42 60 M58 30 Q60 34 58 38 M72 52 Q73 56 71 60", 1.2, "#6e4526"),
      P("M18 38 Q50 32 82 38 L82 46 Q50 40 18 46 Z", "#6d737c", 1.6),
      dots([[24, 41], [37, 39], [50, 38.4], [63, 39], [76, 41]], "#c9ced6", 1.6),
      C(50, 58, 8, "#8d96a3", 1.6),
      HI("M46 54 Q48 51 52 51 Q48 53 48 57 Z", 0.6),
    ].join(""),
  spider_shield: () =>
    [
      roundRim("#8a5a2b", "#5a3a1e"),
      LN("M50 13 V87 M13 50 H87", 1.2, "#6e4526", 0.6),
      LN("M44 46 Q30 34 24 24 M44 50 Q28 46 18 46 M44 54 Q30 58 20 66 M46 58 Q36 70 32 80", 2.6),
      LN("M56 46 Q70 34 76 24 M56 50 Q72 46 82 46 M56 54 Q70 58 80 66 M54 58 Q64 70 68 80", 2.6),
      C(50, 42, 6, "#241612", 1.4),
      `<ellipse cx="50" cy="58" rx="9" ry="11" fill="#241612" stroke="${INK}" stroke-width="1.4"/>`,
      P("M47 54 L50 58 L53 54 L50 62 Z", "#d6453a", 0),
      dots([[48, 41], [52, 41]], "#ff6a3a", 1.1),
      dots([[50, 8], [8, 50], [92, 50], [50, 92]], "#c9ced6", 1.6),
    ].join(""),
  bear_shield: () =>
    [
      roundRim("#6b4a2e", "#8a8f98"),
      LN("M26 22 Q22 50 26 78 M38 15 Q35 50 38 86 M50 13 V87 M62 15 Q65 50 62 86 M74 22 Q78 50 74 78", 1.2, "#3e2a18", 0.7),
      `<ellipse cx="50" cy="60" rx="15" ry="12" fill="#efe1c2" stroke="${INK}" stroke-width="1.8"/>`,
      `<ellipse cx="33" cy="42" rx="5.6" ry="7" fill="#efe1c2" stroke="${INK}" stroke-width="1.6" transform="rotate(-24 33 42)"/>`,
      `<ellipse cx="44" cy="35" rx="5.6" ry="7" fill="#efe1c2" stroke="${INK}" stroke-width="1.6" transform="rotate(-8 44 35)"/>`,
      `<ellipse cx="56" cy="35" rx="5.6" ry="7" fill="#efe1c2" stroke="${INK}" stroke-width="1.6" transform="rotate(8 56 35)"/>`,
      `<ellipse cx="67" cy="42" rx="5.6" ry="7" fill="#efe1c2" stroke="${INK}" stroke-width="1.6" transform="rotate(24 67 42)"/>`,
      dots([[50, 9], [21, 21], [79, 21], [9, 50], [91, 50], [21, 79], [79, 79], [50, 91]], "#d8dde4", 1.5),
    ].join(""),
  round_shield: () => {
    const rays = Array.from({ length: 8 }, (_, i) => {
      const a = (i / 8) * Math.PI * 2;
      return `M${(50 + Math.cos(a) * 12).toFixed(1)} ${(50 + Math.sin(a) * 12).toFixed(1)} L${(50 + Math.cos(a) * 37).toFixed(1)} ${(50 + Math.sin(a) * 37).toFixed(1)}`;
    }).join(" ");
    return [
      roundRim("#3f6fb8", "#c9ced6"),
      P("M50 13 A37 37 0 0 1 87 50 L50 50 Z", "#5a8ad0", 0),
      P("M50 87 A37 37 0 0 1 13 50 L50 50 Z", "#5a8ad0", 0),
      C(50, 50, 37, "none", 1.6),
      LN(rays, 1.6, "#e9edf2", 0.8),
      C(50, 50, 12, "#c9ced6", 1.8),
      HI("M43 45 Q45 40 51 39 Q46 43 46 48 Z", 0.7),
      dots([[50, 9.5], [21.4, 21.4], [78.6, 21.4], [9.5, 50], [90.5, 50], [21.4, 78.6], [78.6, 78.6], [50, 90.5]], "#5a6270", 1.5),
    ].join("");
  },
};

// ------------------------------------------------------------------ helmets (100×100)
const DOME = "M17 70 Q15 17 50 13 Q85 17 83 70 Z";
const HELMETS = {
  eagle_helm: () =>
    [
      P("M20 46 Q2 32 3 6 Q11 18 19 22 Q12 10 15 2 Q24 18 28 32 Z", "#f2e6c8", 1.8),
      P("M80 46 Q98 32 97 6 Q89 18 81 22 Q88 10 85 2 Q76 18 72 32 Z", "#f2e6c8", 1.8),
      LN("M9 14 Q14 26 22 32 M91 14 Q86 26 78 32", 1.2, "#b8a27a"),
      P(DOME, "#b07a3a", 2),
      HI("M24 40 Q26 22 44 18 Q32 26 30 42 Z", 0.3),
      P("M17 70 Q15 56 26 54 L40 54 L44 62 L56 62 L60 54 L74 54 Q85 56 83 70 L72 82 L64 70 L36 70 L28 82 Z", "#8a5a28", 1.8),
      P("M45 30 L50 72 L55 30 Q50 26 45 30 Z", "#d9a93e", 1.6),
      P("M24 52 Q34 46 44 52 L44 58 Q34 54 24 58 Z M56 52 Q66 46 76 52 L76 58 Q66 54 56 58 Z", "#2a1a10", 0),
      LN("M17 50 Q50 40 83 50", 2.4, "#d9a93e"),
    ].join(""),
  horned_helm: () =>
    [
      P("M22 48 Q4 42 5 14 Q11 34 27 36 Z", "#efe1c2", 1.8),
      P("M78 48 Q96 42 95 14 Q89 34 73 36 Z", "#efe1c2", 1.8),
      LN("M10 30 L16 32 M8 22 L13 25 M90 30 L84 32 M92 22 L87 25", 1.2, "#a8946a"),
      P(DOME, "#5b8a4a", 2),
      HI("M24 40 Q26 22 44 18 Q32 26 30 42 Z", 0.25),
      P("M17 70 L17 56 L83 56 L83 70 L74 88 L66 70 L34 70 L26 88 Z", "#486e3a", 1.8),
      P("M28 56 Q38 50 46 56 L46 64 L28 64 Z M54 56 Q62 50 72 56 L72 64 L54 64 Z", "#1d2414", 0),
      P("M46 46 H54 V76 H46 Z", "#3a5a2e", 1.6),
      LN("M17 52 Q50 44 83 52", 3, "#c9a64a"),
      dots([[26, 51], [38, 48], [62, 48], [74, 51]], "#f2d27a", 1.6),
    ].join(""),
  viking_helm: () =>
    [
      P(DOME, "#a8adb5", 2),
      HI("M24 40 Q26 22 44 18 Q32 26 30 42 Z", 0.35),
      P("M46 14 H54 V52 H46 Z", "#8d939c", 1.4),
      LN("M18 50 Q50 42 82 50", 6, "#7a7f88") + LN("M18 50 Q50 42 82 50", 2, "#c9ced6"),
      P("M22 52 Q22 70 34 72 Q44 70 46 58 L46 52 Z M78 52 Q78 70 66 72 Q56 70 54 58 L54 52 Z", "#8d939c", 1.8),
      `<circle cx="34" cy="60" r="7" fill="#1a1612"/><circle cx="66" cy="60" r="7" fill="#1a1612"/>`,
      P("M46 52 H54 L53 84 L50 87 L47 84 Z", "#a8adb5", 1.6),
      dots([[24, 49], [36, 46.4], [64, 46.4], [76, 49], [50, 22], [50, 34]], "#e6eaee", 1.5),
    ].join(""),
  knight_helm: () =>
    [
      P("M50 14 Q34 2 30 -2 Q40 10 44 16 Z", "#3f6fc0", 1.4),
      P("M46 16 Q50 -4 66 -2 Q58 6 54 16 Z", "#5a8ad0", 1.6),
      P("M20 22 Q50 10 80 22 L82 86 Q50 96 18 86 Z", "#7a8fb0", 2),
      HI("M24 26 Q34 18 46 17 L44 84 Q32 82 24 80 Z", 0.18),
      P("M24 46 H76 V52 H24 Z", "#151a24", 0),
      P("M47 52 H53 V78 H47 Z", "#151a24", 0),
      LN("M20 22 Q50 10 80 22 M18 40 H82 M18 58 H82", 1.6),
      dots([[28, 70], [34, 76], [28, 82], [72, 70], [66, 76], [72, 82]], "#151a24", 1.4),
      LN("M50 12 V40", 2, "#d9a93e"),
    ].join(""),
  iron_helm: () =>
    [
      P("M6 64 Q50 50 94 64 Q96 74 86 74 Q50 64 14 74 Q4 74 6 64 Z", "#5a6068", 2),
      P("M22 62 Q20 22 50 20 Q80 22 78 62 Q50 54 22 62 Z", "#6d737c", 2),
      HI("M28 46 Q30 28 46 25 Q36 32 34 48 Z", 0.3),
      LN("M50 20 V56", 2.4, "#4a5058"),
      LN("M22 56 Q50 48 78 56", 2.4, "#8d939c"),
      dots([[30, 54], [42, 51.4], [58, 51.4], [70, 54]], "#c9ced6", 1.5),
      P("M30 74 Q50 68 70 74 L68 86 Q50 82 32 86 Z", "#2a2c30", 0),
    ].join(""),
  demon_helm: () =>
    [
      P("M24 36 Q8 30 6 8 Q10 20 18 22 Q14 14 18 6 Q22 22 32 30 Z", "#241612", 1.8),
      P("M76 36 Q92 30 94 8 Q90 20 82 22 Q86 14 82 6 Q78 22 68 30 Z", "#241612", 1.8),
      P(DOME, "#8a2a2a", 2),
      HI("M24 40 Q26 22 44 18 Q32 26 30 42 Z", 0.22),
      P("M17 70 Q15 50 30 48 L44 54 L50 50 L56 54 L70 48 Q85 50 83 70 L70 90 L60 78 L50 86 L40 78 L30 90 Z", "#5a1a1a", 1.8),
      P("M28 54 L44 58 L40 64 L28 61 Z M72 54 L56 58 L60 64 L72 61 Z", "#ffb03a", 1.2),
      `<circle cx="36" cy="59" r="7" fill="#ff8a2a" opacity=".3"/><circle cx="64" cy="59" r="7" fill="#ff8a2a" opacity=".3"/>`,
      P("M40 76 L42 82 L44 77 L46 83 L48 78 L50 84 L52 78 L54 83 L56 77 L58 82 L60 76 Z", "#efe6cf", 1),
      LN("M50 14 V48", 2, "#4a0e0e"),
    ].join(""),
};

// ------------------------------------------------------------------ elixirs (50×100)
const BOTTLE = "M19 13 H31 V32 Q45 40 45 62 Q45 93 25 95 Q5 93 5 62 Q5 40 19 32 Z";
const LIQUID = "M7 58 Q16 54 25 57 Q34 60 43 56 Q44 60 43.6 66 Q42 91 25 92.6 Q8 91 6.4 66 Q6 61 7 58 Z";
function bottle(liquid, mark) {
  return [
    `<ellipse cx="25" cy="96" rx="17" ry="3" fill="#000" opacity=".25"/>`,
    P(BOTTLE, "rgba(220,240,255,.35)", 2),
    P(LIQUID, liquid, 0),
    SH("M33 58 Q42 58 43.6 66 Q42 91 25 92.6 Q36 84 36 66 Z", 0.18),
    P(BOTTLE, "none", 2),
    `<path d="M10 52 Q12 42 19 37" fill="none" stroke="#fff" stroke-width="2.6" stroke-linecap="round" opacity=".7"/>`,
    `<circle cx="11" cy="60" r="1.6" fill="#fff" opacity=".7"/>`,
    P("M16 4 H34 V14 H16 Z", "#b8864a", 1.8),
    LN("M16 8 H34", 1, "#7a5228"),
    P("M17 31 H33", "none", 0) + LN("M17.5 31 H32.5", 2.4, "#c9a64a"),
    mark,
  ].join("");
}
const MARK = {
  shield: P("M25 64 L35 67 Q35 78 25 85 Q15 78 15 67 Z", "#fff", 1.4),
  sword: P("M23.6 84 L23.6 66 L25 62 L26.4 66 L26.4 84 Z", "#fff", 1.2) + P("M19 80 H31 V82.6 H19 Z", "#fff", 1.2),
  spell: P("M25 61 L27.6 70 L36 73 L27.6 76 L25 85 L22.4 76 L14 73 L22.4 70 Z", "#fff", 1.2),
  heart: P("M25 86 C14 78 13 72 15 68 C17 64 23 64 25 69 C27 64 33 64 35 68 C37 72 36 78 25 86 Z", "#fff", 1.4),
};
const ELIXIRS = {
  blue_elixir: () => bottle("#3a7fd8", MARK.shield),
  orange_elixir: () => bottle("#ec7d1e", MARK.sword),
  yellow_elixir: () => bottle("#f2c52f", MARK.spell),
  healing_elixir: () => bottle("#d8324e", MARK.heart),
};

export const ITEM_BOX = { weapon: [40, 120], shield: [100, 100], helmet: [100, 100], elixir: [50, 100] };
export const ITEM_ART = { ...WEAPONS, ...SHIELDS, ...HELMETS, ...ELIXIRS };
