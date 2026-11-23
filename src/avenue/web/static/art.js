// Hand-drawn SVG artwork: the eight animal agents, the spy meeples, black market illustrations and icons.
// Everything is plain SVG markup strings so cards can be cloned cheaply for animations.

const eye = (x, y, { r = 4.2, iris = "#2b2233", lid = 0, lidColor = "#000", look = 0, shine = true } = {}) => `
  <ellipse cx="${x}" cy="${y}" rx="${r}" ry="${r * 1.08}" fill="#fff"/>
  <circle cx="${x + look}" cy="${y + 0.4}" r="${r * 0.62}" fill="${iris}"/>
  <circle cx="${x + look}" cy="${y + 0.4}" r="${r * 0.3}" fill="#120d16"/>
  ${shine ? `<circle cx="${x + look - r * 0.25}" cy="${y - r * 0.25}" r="${r * 0.2}" fill="#fff"/>` : ""}
  ${lid ? `<path d="M${x - r - 0.6} ${y - r * 1.2} H${x + r + 0.6} V${y - r + lid * r * 2} Q${x} ${y - r + lid * r * 2 + 1.6} ${x - r - 0.6} ${y - r + lid * r * 2} Z" fill="${lidColor}"/>` : ""}`;

const ink = "#2a1f2d";

// Each portrait is drawn in a 120 × 120 box: a bust with the head around (60, 50).
const PORTRAITS = {
  fox: `
    <g>
      <path d="M14 120 C18 95 38 86 60 86 C82 86 102 95 106 120 Z" fill="#9fdcc0"/>
      <g fill="#fff" opacity=".95">
        <circle cx="30" cy="104" r="3.4"/><circle cx="44" cy="96" r="3.4"/><circle cx="60" cy="104" r="3.4"/>
        <circle cx="76" cy="96" r="3.4"/><circle cx="90" cy="106" r="3.4"/><circle cx="50" cy="114" r="3.4"/>
        <circle cx="70" cy="114" r="3.4"/><circle cx="22" cy="116" r="3"/><circle cx="98" cy="117" r="3"/>
      </g>
      <path d="M48 86 Q60 96 72 86 L68 80 H52 Z" fill="#f4f1ea"/>
      <path d="M36 36 L30 6 L54 26 Z" fill="#e2683a"/><path d="M38 31 L34 13 L49 26 Z" fill="#fbe3d1"/>
      <path d="M84 36 L90 6 L66 26 Z" fill="#e2683a"/><path d="M82 31 L86 13 L71 26 Z" fill="#fbe3d1"/>
      <path d="M60 20 C80 20 91 34 90 50 C89 62 82 70 72 75 L60 82 L48 75 C38 70 31 62 30 50 C29 34 40 20 60 20 Z" fill="#ef7a43"/>
      <path d="M31 52 C40 56 50 62 60 82 C70 62 80 56 89 52 C88 66 76 78 60 84 C44 78 32 66 31 52 Z" fill="#fff6ee"/>
      <path d="M52 22 Q60 30 68 22 Q60 26 52 22 Z" fill="#d85f2c"/>
      ${eye(48, 50, { r: 4.6, iris: "#3d9b6b", lid: 0.42, lidColor: "#ef7a43", look: 0.6 })}${eye(72, 50, { r: 4.6, iris: "#3d9b6b", lid: 0.42, lidColor: "#ef7a43", look: 0.6 })}
      <path d="M41 43 Q48 40 54 44" stroke="${ink}" stroke-width="1.6" fill="none" stroke-linecap="round"/>
      <path d="M66 44 Q72 40 79 43" stroke="${ink}" stroke-width="1.6" fill="none" stroke-linecap="round"/>
      <ellipse cx="60" cy="66" rx="4" ry="3" fill="${ink}"/>
      <path d="M53 73 Q60 78 68 72" stroke="#c23a4a" stroke-width="2" fill="none" stroke-linecap="round"/>
      <path d="M88 84 l14 -8 4 6 -14 8 z" fill="#fff" stroke="#c9c2b5"/><path d="M90 85 l12 -7" stroke="#e07070" stroke-width=".8"/>
      <rect x="99" y="58" width="2.4" height="20" rx="1" transform="rotate(25 100 68)" fill="#e2b04a"/>
    </g>`,
  squirrel: `
    <g>
      <path d="M86 112 C112 104 118 70 104 52 C94 38 76 44 82 58 C86 68 100 64 98 78 C96 92 80 94 82 112 Z" fill="#c9733a"/>
      <path d="M92 104 C108 96 110 74 102 62" stroke="#e2a066" stroke-width="5" fill="none" stroke-linecap="round"/>
      <path d="M14 120 C18 96 36 86 60 86 C84 86 102 96 106 120 Z" fill="#23243a"/>
      <path d="M48 86 L60 110 L72 86" fill="#3a3c5c"/><path d="M50 86 L60 104 L70 86 Z" fill="#f2ece2"/>
      <path d="M44 88 L60 112" stroke="#4b4e74" stroke-width="3"/><path d="M76 88 L62 110" stroke="#4b4e74" stroke-width="3"/>
      <path d="M36 32 C30 18 36 8 44 10 C50 12 50 22 48 30 Z" fill="#d98245"/><path d="M40 28 C37 20 40 14 44 15 C47 17 46 23 45 28 Z" fill="#f2c79c"/>
      <path d="M84 32 C90 18 84 8 76 10 C70 12 70 22 72 30 Z" fill="#d98245"/><path d="M80 28 C83 20 80 14 76 15 C73 17 74 23 75 28 Z" fill="#f2c79c"/>
      <path d="M33 8 l5 6" stroke="#b45f2a" stroke-width="2.4" stroke-linecap="round"/><path d="M87 8 l-5 6" stroke="#b45f2a" stroke-width="2.4" stroke-linecap="round"/>
      <ellipse cx="60" cy="52" rx="28" ry="27" fill="#e08c4c"/>
      <ellipse cx="60" cy="19" rx="8" ry="6" fill="#7a4220"/><rect x="55" y="22" width="10" height="5" rx="2" fill="#5a2f17"/>
      <path d="M38 34 Q60 22 82 34 Q72 28 60 28 Q48 28 38 34 Z" fill="#7a4220"/>
      <ellipse cx="60" cy="64" rx="16" ry="12" fill="#f6dcc0"/>
      ${eye(49, 50, { r: 4.4, iris: "#4a6fa5" })}${eye(71, 50, { r: 4.4, iris: "#4a6fa5" })}
      <path d="M41 42 L54 46" stroke="${ink}" stroke-width="2.6" stroke-linecap="round"/><path d="M79 42 L66 46" stroke="${ink}" stroke-width="2.6" stroke-linecap="round"/>
      <path d="M56 59 Q60 56 64 59 Q60 63 56 59 Z" fill="${ink}"/>
      <path d="M52 68 Q60 65 68 68" stroke="${ink}" stroke-width="1.8" fill="none" stroke-linecap="round"/>
      <rect x="57" y="67" width="6" height="5" rx="1" fill="#fff" stroke="#d8c8b4" stroke-width=".6"/>
    </g>`,
  owl: `
    <g>
      <path d="M14 120 C18 96 36 86 60 86 C84 86 102 96 106 120 Z" fill="#f1ebe0"/>
      <path d="M26 120 C28 100 40 92 52 90 L60 104 L68 90 C80 92 92 100 94 120 Z" fill="#e9a03b"/>
      <g stroke="#c4781f" stroke-width="1.4" opacity=".8"><path d="M34 98 V120 M46 92 V120 M74 92 V120 M86 98 V120"/><path d="M28 106 H92 M27 114 H93"/></g>
      <g stroke="#7d5aa6" stroke-width="1" opacity=".7"><path d="M40 94 V120 M80 94 V120"/><path d="M28 110 H92"/></g>
      <path d="M52 90 L60 100 L68 90 L60 86 Z" fill="#fff"/><path d="M54 92 L60 88 L66 92 L60 96 Z" fill="#e05a8a"/>
      <path d="M30 34 L26 12 L44 26 Z" fill="#a9825c"/><path d="M90 34 L94 12 L76 26 Z" fill="#a9825c"/>
      <ellipse cx="60" cy="52" rx="32" ry="30" fill="#b98e64"/>
      <path d="M60 26 Q54 34 60 40 Q66 34 60 26 Z" fill="#9b7350"/>
      <circle cx="47" cy="52" r="15" fill="#f3e6cf"/><circle cx="73" cy="52" r="15" fill="#f3e6cf"/>
      ${eye(47, 52, { r: 6, iris: "#d9363e" })}${eye(73, 52, { r: 6, iris: "#d9363e" })}
      <circle cx="47" cy="52" r="10.5" fill="none" stroke="${ink}" stroke-width="3"/><circle cx="73" cy="52" r="10.5" fill="none" stroke="${ink}" stroke-width="3"/>
      <path d="M57 50 Q60 47 63 50" stroke="${ink}" stroke-width="3" fill="none"/>
      <path d="M36 44 L30 40 M84 44 L90 40" stroke="${ink}" stroke-width="2.4"/>
      <path d="M55 62 L60 74 L65 62 Q60 59 55 62 Z" fill="#f1a33a"/>
      <path d="M44 78 Q50 70 58 76" stroke="#7a5638" stroke-width="2" fill="#efdfc7"/>
    </g>`,
  raccoon: `
    <g>
      <rect x="84" y="40" width="8" height="74" rx="4" transform="rotate(22 88 77)" fill="#d4a66a"/>
      <rect x="84" y="40" width="8" height="18" rx="3" transform="rotate(22 88 77)" fill="#b8874a"/>
      <path d="M14 120 C18 96 36 86 60 86 C84 86 102 96 106 120 Z" fill="#1e1e24"/>
      <path d="M46 86 L60 120 L74 86 Z" fill="#f5f3ef"/>
      <path d="M40 88 L58 120 L46 120 L32 94 Z" fill="#2c2c35"/><path d="M80 88 L62 120 L74 120 L88 94 Z" fill="#2c2c35"/>
      <circle cx="35" cy="102" r="1.6" fill="#9a9aa8"/><circle cx="85" cy="102" r="1.6" fill="#9a9aa8"/>
      <ellipse cx="34" cy="30" rx="10" ry="11" fill="#6f707b"/><ellipse cx="34" cy="31" rx="5" ry="6" fill="#2c2c35"/>
      <ellipse cx="86" cy="30" rx="10" ry="11" fill="#6f707b"/><ellipse cx="86" cy="31" rx="5" ry="6" fill="#2c2c35"/>
      <path d="M60 22 C82 22 92 38 90 54 C88 70 76 80 60 80 C44 80 32 70 30 54 C28 38 38 22 60 22 Z" fill="#8d8e9a"/>
      <path d="M44 18 C50 8 72 8 78 16 C70 14 66 20 70 26 C62 20 52 22 46 28 C44 24 42 22 44 18 Z" fill="#3e3e48"/>
      <path d="M30 46 C38 40 50 42 60 50 C70 42 82 40 90 46 C90 56 80 60 70 58 L60 56 L50 58 C40 60 30 56 30 46 Z" fill="#26262e"/>
      <path d="M44 64 C48 58 54 56 60 56 C66 56 72 58 76 64 C74 74 68 78 60 78 C52 78 46 74 44 64 Z" fill="#f0eee9"/>
      <path d="M36 40 L46 36 M84 40 L74 36" stroke="#f0eee9" stroke-width="3" stroke-linecap="round"/>
      ${eye(47, 50, { r: 3.8, iris: "#e2a33a" })}${eye(73, 50, { r: 3.8, iris: "#e2a33a" })}
      <ellipse cx="60" cy="62" rx="4.6" ry="3.2" fill="${ink}"/>
      <path d="M50 70 Q60 76 72 68" stroke="${ink}" stroke-width="1.8" fill="none" stroke-linecap="round"/>
      <path d="M64 71 l2 4 l2 -4.6 z" fill="#fff"/>
      <ellipse cx="96" cy="100" rx="7" ry="6" fill="#7a7a86"/>
    </g>`,
  wolf: `
    <g>
      <path d="M14 120 C18 96 36 86 60 86 C84 86 102 96 106 120 Z" fill="#f4f6f8"/>
      <path d="M22 120 C24 100 36 92 48 90 L60 120 Z" fill="#2f86c4"/><path d="M98 120 C96 100 84 92 72 90 L60 120 Z" fill="#2f86c4"/>
      <path d="M56 90 L60 96 L64 90 L66 120 L60 124 L54 120 Z" fill="#e8708e"/>
      <circle cx="52" cy="108" r="1.4" fill="#1d5a88"/><circle cx="52" cy="116" r="1.4" fill="#1d5a88"/>
      <path d="M34 40 L30 6 L52 28 Z" fill="#8fa6be"/><path d="M37 34 L35 14 L48 28 Z" fill="#dfe7ef"/>
      <path d="M86 40 L90 6 L68 28 Z" fill="#8fa6be"/><path d="M83 34 L85 14 L72 28 Z" fill="#dfe7ef"/>
      <path d="M60 20 C80 20 90 34 90 48 C90 60 84 66 80 70 L72 82 H48 L40 70 C36 66 30 60 30 48 C30 34 40 20 60 20 Z" fill="#a8bccf"/>
      <path d="M44 56 C50 52 54 54 60 54 C66 54 70 52 76 56 L74 76 C70 82 66 84 60 84 C54 84 50 82 46 76 Z" fill="#e8eef4"/>
      <path d="M30 50 L22 56 L32 58 Z M90 50 L98 56 L88 58 Z" fill="#a8bccf"/>
      ${eye(48, 46, { r: 4, iris: "#e8b13a" })}${eye(72, 46, { r: 4, iris: "#e8b13a" })}
      <path d="M40 38 L54 42 M80 38 L66 42" stroke="#3a4a5c" stroke-width="2.8" stroke-linecap="round"/>
      <path d="M53 62 Q60 58 67 62 Q66 68 60 69 Q54 68 53 62 Z" fill="${ink}"/>
      <path d="M50 75 Q58 80 70 73" stroke="${ink}" stroke-width="1.8" fill="none" stroke-linecap="round"/>
      <path d="M66 75 l2 4 l1.6 -5 z" fill="#fff"/>
    </g>`,
  pigeon: `
    <g>
      <path d="M12 120 C16 94 34 84 60 84 C86 84 104 94 108 120 Z" fill="#e7a76f"/>
      <path d="M40 86 C46 96 52 104 60 120 C68 104 74 96 80 86 C72 82 48 82 40 86 Z" fill="#7d79cc"/>
      <path d="M42 86 C48 92 54 92 60 90 C66 92 72 92 78 86 C70 80 50 80 42 86 Z" fill="#5fb59a"/>
      <path d="M26 92 L42 86 L46 104 Z M94 92 L78 86 L74 104 Z" fill="#f2bd86"/>
      <path d="M60 24 C80 24 88 38 88 52 C88 68 76 80 60 80 C44 80 32 68 32 52 C32 38 40 24 60 24 Z" fill="#8f8ad8"/>
      <path d="M40 64 C46 72 52 76 60 76 C68 76 74 72 80 64 C78 74 70 82 60 82 C50 82 42 74 40 64 Z" fill="#b27fc4" opacity=".7"/>
      <path d="M18 34 C22 26 98 26 102 34 C104 40 92 40 60 40 C28 40 16 40 18 34 Z" fill="#a0663b"/>
      <path d="M34 34 C34 10 86 10 86 34 Z" fill="#b9773f"/><rect x="34" y="28" width="52" height="6" fill="#5a3a24"/>
      <path d="M30 40 C26 20 94 20 90 40" stroke="#2b2b33" stroke-width="3.6" fill="none"/>
      <rect x="25" y="42" width="10" height="16" rx="5" fill="#2b2b33"/><rect x="85" y="42" width="10" height="16" rx="5" fill="#2b2b33"/>
      <circle cx="49" cy="52" r="8" fill="#f2542d" stroke="${ink}" stroke-width="2"/><circle cx="71" cy="52" r="8" fill="#f2542d" stroke="${ink}" stroke-width="2"/>
      <circle cx="47" cy="50" r="2.5" fill="#ffd29a" opacity=".9"/><circle cx="69" cy="50" r="2.5" fill="#ffd29a" opacity=".9"/>
      <path d="M57 52 H63" stroke="${ink}" stroke-width="2"/>
      <path d="M54 62 Q60 58 66 62 L60 70 Z" fill="#ead8b2"/><path d="M55 62 Q60 60 65 62" stroke="#cbb88f" stroke-width="1" fill="none"/>
    </g>`,
  otter: `
    <g>
      <path d="M14 120 C18 96 36 86 60 86 C84 86 102 96 106 120 Z" fill="#f0e2c4"/>
      <path d="M40 88 L44 120 M80 88 L76 120" stroke="#6b4527" stroke-width="5"/>
      <path d="M56 88 L60 94 L64 88 L63 116 L60 120 L57 116 Z" fill="#3b2f2a"/>
      <path d="M50 86 L60 94 L70 86 Z" fill="#fffaf0"/>
      <ellipse cx="34" cy="38" rx="7" ry="7" fill="#7d5233"/><ellipse cx="86" cy="38" rx="7" ry="7" fill="#7d5233"/>
      <path d="M60 24 C82 24 90 40 89 54 C88 70 76 82 60 82 C44 82 32 70 31 54 C30 40 38 24 60 24 Z" fill="#94643f"/>
      <path d="M42 60 C44 52 52 50 60 50 C68 50 76 52 78 60 C78 72 70 78 60 78 C50 78 42 72 42 60 Z" fill="#dfc29e"/>
      <path d="M28 36 C30 18 90 18 92 36 C92 40 84 36 60 36 C36 36 28 40 28 36 Z" fill="#6f553e"/>
      <path d="M30 36 C30 30 46 26 62 26 C78 26 92 30 96 36 C96 42 88 40 60 40 C40 40 30 42 30 36 Z" fill="#8a6a4c"/>
      <circle cx="60" cy="22" r="3" fill="#6f553e"/>
      ${eye(49, 49, { r: 3.8, iris: "#3a2a20" })}${eye(71, 49, { r: 3.8, iris: "#3a2a20" })}
      <path d="M43 44 Q49 41 54 44 M66 44 Q71 41 77 44" stroke="${ink}" stroke-width="1.6" fill="none" stroke-linecap="round"/>
      <ellipse cx="60" cy="58" rx="5" ry="3.6" fill="${ink}"/>
      <path d="M54 66 Q60 70 66 66" stroke="${ink}" stroke-width="1.6" fill="none" stroke-linecap="round"/>
      <g stroke="#5a3c26" stroke-width=".9"><path d="M40 60 H30 M40 64 L31 67 M80 60 H90 M80 64 L89 67"/></g>
      <circle cx="94" cy="84" r="7" fill="#94643f"/><circle cx="94" cy="84" r="3.4" fill="none" stroke="#dfc29e" stroke-width="1.6"/>
    </g>`,
  mole: `
    <g>
      <path d="M10 120 C14 94 34 84 60 84 C86 84 106 94 110 120 Z" fill="#d6ccb8"/>
      <path d="M38 84 L52 120 L60 98 L68 120 L82 84 C74 80 46 80 38 84 Z" fill="#c2b59d"/>
      <path d="M46 86 L60 98 L74 86 Z" fill="#f4efe6"/>
      <path d="M60 16 C86 16 96 36 96 54 C96 74 80 86 60 86 C40 86 24 74 24 54 C24 36 34 16 60 16 Z" fill="#5f566b"/>
      <path d="M40 22 C44 16 52 14 58 16 C52 18 46 22 44 28 Z" fill="#7a7088"/>
      <circle cx="48" cy="48" r="8.5" fill="#fff" fill-opacity=".25" stroke="#d9363e" stroke-width="2.6"/>
      <circle cx="72" cy="48" r="8.5" fill="#fff" fill-opacity=".25" stroke="#d9363e" stroke-width="2.6"/>
      <path d="M56.5 47 Q60 44 63.5 47" stroke="#d9363e" stroke-width="2.4" fill="none"/>
      <circle cx="48" cy="49" r="2.2" fill="${ink}"/><circle cx="72" cy="49" r="2.2" fill="${ink}"/>
      <path d="M40 38 L54 40 M80 38 L66 40" stroke="#3e3748" stroke-width="2" stroke-linecap="round"/>
      <path d="M60 56 C68 56 72 60 70 66 C68 70 52 70 50 66 C48 60 52 56 60 56 Z" fill="#f28ca3"/>
      <path d="M54 60 Q60 58 66 60" stroke="#fff" stroke-width="1.4" fill="none" opacity=".7"/>
      <path d="M52 76 Q60 72 68 76" stroke="#2f2a36" stroke-width="1.8" fill="none" stroke-linecap="round"/>
      <path d="M62 92 C66 80 76 78 80 84 C82 88 78 92 74 92 Z" fill="#f2a6b4"/>
      <path d="M66 82 l-1 -5 M70 80 l0 -5 M74 81 l1 -4" stroke="#e98597" stroke-width="2.2" stroke-linecap="round"/>
    </g>`,
};

export function portrait(animal) {
  return `<svg class="portrait" viewBox="0 0 120 120" aria-hidden="true">${PORTRAITS[animal] || ""}</svg>`;
}

// White picket fence + soft hills, drawn behind every agent.
export const FENCE = `<svg class="fence" viewBox="0 0 120 40" preserveAspectRatio="none" aria-hidden="true">
  <path d="M0 18 Q30 8 60 16 T120 12 V40 H0 Z" fill="rgba(255,255,255,.28)"/>
  <g fill="#fbf6ea">${Array.from({ length: 10 }, (_, i) => `<path d="M${i * 12 + 2} 40 V20 l4 -5 l4 5 V40 Z"/>`).join("")}</g>
  <rect x="0" y="26" width="120" height="3" fill="#efe6d1"/>
</svg>`;

// ---------------------------------------------------------------- meeples
// A spy meeple: classic meeple silhouette with a fedora, mask and animal ears.
export function meepleSvg(team) {
  const body = team === 0 ? "#2f9a5a" : "#2d7fd0";
  const dark = team === 0 ? "#1d6b3c" : "#1d5592";
  const light = team === 0 ? "#5cc485" : "#62a8ee";
  const ears =
    team === 0
      ? `<path d="M19 21 L17 9 L26 16 Z M45 21 L47 9 L38 16 Z" fill="${body}" stroke="${dark}" stroke-width="1.4" stroke-linejoin="round"/>`
      : `<path d="M18 19 C10 18 9 30 14 34 C16 28 18 24 22 22 Z M46 19 C54 18 55 30 50 34 C48 28 46 24 42 22 Z" fill="${dark}"/>`;
  return `<svg viewBox="0 0 64 74" class="meeple-svg" aria-hidden="true">
    <ellipse cx="32" cy="70" rx="22" ry="3.6" fill="rgba(0,0,0,.28)"/>
    ${ears}
    <path d="M32 12 C40 12 45 18 45 25 C45 29 43 32 40 34 C48 35 60 38 60 46 C60 50 56 51 50 50 L46 49 L54 66 C55 69 52 70 48 70 H38 L32 58 L26 70 H16 C12 70 9 69 10 66 L18 49 L14 50 C8 51 4 50 4 46 C4 38 16 35 24 34 C21 32 19 29 19 25 C19 18 24 12 32 12 Z" fill="${body}" stroke="${dark}" stroke-width="1.6" stroke-linejoin="round"/>
    <path d="M24 34 C28 36 36 36 40 34 C44 36 52 37 56 40" stroke="${light}" stroke-width="2" fill="none" opacity=".7"/>
    <path d="M22 24 C26 22 38 22 42 24 L41 28 C37 27 27 27 23 28 Z" fill="#1d1a22"/>
    <circle cx="27.5" cy="25.6" r="1.6" fill="#fff"/><circle cx="36.5" cy="25.6" r="1.6" fill="#fff"/>
    <path d="M13 15 C14 12 50 12 51 15 C51 18 46 18 32 18 C18 18 13 18 13 15 Z" fill="#2a2430"/>
    <path d="M21 15 C21 3 43 3 43 15 Z" fill="#3a3342"/><rect x="21" y="11" width="22" height="3.4" fill="${light}"/>
  </svg>`;
}

// ---------------------------------------------------------------- small icons
export const ICONS = {
  spy: `<svg viewBox="0 0 48 48" aria-hidden="true"><path d="M6 20 C6 17 42 17 42 20 C42 23 36 23 24 23 C12 23 6 23 6 20 Z" fill="currentColor"/><path d="M13 20 C13 6 35 6 35 20 Z" fill="currentColor"/><path d="M12 26 C16 24 32 24 36 26 L35 31 C31 29 17 29 13 31 Z" fill="currentColor"/><path d="M15 33 C18 40 30 40 33 33" stroke="currentColor" stroke-width="3" fill="none" stroke-linecap="round"/></svg>`,
  cart: `<svg viewBox="0 0 48 48" aria-hidden="true"><path d="M9 13 C9 11 33 11 33 13 C33 15 29 15 21 15 C13 15 9 15 9 13 Z" fill="currentColor"/><path d="M14 13 C14 4 28 4 28 13 Z" fill="currentColor"/><path d="M13 18 H29 L27 22 H15 Z" fill="currentColor"/><path d="M12 25 H34 L32 37 H14 Z" fill="currentColor"/><path d="M34 25 L37 18 H41" stroke="currentColor" stroke-width="2.6" fill="none" stroke-linecap="round"/><circle cx="17" cy="41" r="3" fill="currentColor"/><circle cx="29" cy="41" r="3" fill="currentColor"/></svg>`,
  house: `<svg viewBox="0 0 48 48" aria-hidden="true"><path d="M24 7 L43 23 H37 V41 H28 V30 H20 V41 H11 V23 H5 Z" fill="currentColor"/></svg>`,
  infinity: `<svg viewBox="0 0 48 24" aria-hidden="true"><path d="M13 4 C6 4 3 9 3 12 C3 15 6 20 13 20 C20 20 28 4 35 4 C42 4 45 9 45 12 C45 15 42 20 35 20 C28 20 20 4 13 4 Z" fill="none" stroke="currentColor" stroke-width="4"/></svg>`,
  bolt: `<svg viewBox="0 0 24 32" aria-hidden="true"><path d="M15 1 L3 18 H11 L8 31 L21 12 H13 Z" fill="currentColor"/></svg>`,
  check: `<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M4 12.5 L9.5 18 L20 6" stroke="currentColor" stroke-width="3.6" fill="none" stroke-linecap="round" stroke-linejoin="round"/></svg>`,
  cross: `<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M6 6 L18 18 M18 6 L6 18" stroke="currentColor" stroke-width="3.8" stroke-linecap="round"/></svg>`,
  arrow: `<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M5 12 H17 M12 6 L18 12 L12 18" stroke="currentColor" stroke-width="3" fill="none" stroke-linecap="round" stroke-linejoin="round"/></svg>`,
  book: `<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M4 5 C7 4 10 4 12 6 C14 4 17 4 20 5 V19 C17 18 14 18 12 20 C10 18 7 18 4 19 Z" fill="none" stroke="currentColor" stroke-width="2" stroke-linejoin="round"/><path d="M12 6 V20" stroke="currentColor" stroke-width="2"/></svg>`,
};

// ---------------------------------------------------------------- black market illustrations (100 × 64 scenes)
const sky = (a, b, id) => `<defs><linearGradient id="${id}" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="${a}"/><stop offset="1" stop-color="${b}"/></linearGradient></defs><rect width="100" height="64" fill="url(#${id})"/>`;

const MARKET_ART = {
  distraction_device: `${sky("#5b3d8f", "#8a5fb8", "g1")}
    <rect x="0" y="48" width="100" height="16" fill="#3b2760"/>
    <rect x="30" y="16" width="40" height="30" rx="4" fill="#d8a456"/><rect x="34" y="20" width="27" height="22" rx="3" fill="#9fe3f2"/>
    <circle cx="65" cy="25" r="2" fill="#6b4a1e"/><circle cx="65" cy="32" r="2" fill="#6b4a1e"/>
    <path d="M42 16 L36 6 M58 16 L64 6" stroke="#3b2760" stroke-width="1.6"/>
    <path d="M39 33 l4 -6 l4 4 l5 -7 l6 9" stroke="#e8456a" stroke-width="1.6" fill="none"/>
    <rect x="34" y="46" width="4" height="6" fill="#6b4a1e"/><rect x="62" y="46" width="4" height="6" fill="#6b4a1e"/>
    <ellipse cx="16" cy="52" rx="10" ry="8" fill="#2b1f44"/><ellipse cx="84" cy="52" rx="10" ry="8" fill="#2b1f44"/>
    <path d="M10 44 l2 -6 l3 5 M80 44 l3 -6 l2 6" fill="#2b1f44" stroke="#2b1f44" stroke-width="2"/>`,
  watchtower_hq: `${sky("#bfe7f2", "#e6f6ec", "g2")}
    <rect x="0" y="52" width="100" height="12" fill="#7dc36b"/>
    <rect x="46" y="24" width="8" height="30" fill="#9a6a3c"/>
    <circle cx="50" cy="18" r="18" fill="#7cc35a"/><circle cx="34" cy="24" r="11" fill="#9bd36a"/><circle cx="66" cy="22" r="12" fill="#9bd36a"/>
    <rect x="38" y="22" width="24" height="14" fill="#c58a52"/><path d="M36 22 L50 12 L64 22 Z" fill="#a0522d"/>
    <rect x="47" y="26" width="6" height="6" fill="#ffe28a"/><path d="M42 36 V52 M46 38 H42 M46 44 H42 M46 50 H42" stroke="#7a5230" stroke-width="1.4"/>
    <g fill="#fbf6ea">${Array.from({ length: 9 }, (_, i) => `<path d="M${i * 12} 64 V54 l3 -3 l3 3 V64 Z"/>`).join("")}</g>`,
  sinister_twin: `${sky("#f7c6d4", "#fbe3ea", "g3")}
    <path d="M0 50 H100 V64 H0 Z" fill="#e7a9bf"/>
    <g transform="translate(-6 4) scale(.52)">${PORTRAITS.fox}</g>
    <g transform="translate(106 4) scale(-.52 .52)" style="filter:brightness(.5) saturate(1.5) hue-rotate(-25deg)">${PORTRAITS.fox}</g>
    <path d="M50 4 V64" stroke="#fff" stroke-width="1.4" stroke-dasharray="3 3" opacity=".8"/>`,
  supercomputer: `${sky("#ffcf7a", "#ffb15a", "g4")}
    <rect x="0" y="46" width="100" height="18" fill="#e48a3c"/>
    <rect x="22" y="12" width="44" height="32" rx="4" fill="#efe2c8"/><rect x="27" y="16" width="34" height="22" rx="2" fill="#3fb5c9"/>
    <path d="M38 22 C46 22 46 32 38 32 Z" fill="none" stroke="#1d5a6b" stroke-width="2.4"/><path d="M36 22 V32" stroke="#1d5a6b" stroke-width="2.4"/>
    <rect x="16" y="44" width="56" height="8" rx="2" fill="#d9c9a8"/><g fill="#a89676">${Array.from({ length: 12 }, (_, i) => `<rect x="${19 + i * 4.2}" y="46" width="3" height="2"/>`).join("")}</g>
    <rect x="72" y="22" width="10" height="7" fill="#ffd86b" transform="rotate(-8 77 25)"/><rect x="74" y="32" width="9" height="7" fill="#9fe08a" transform="rotate(6 78 35)"/>
    <path d="M82 46 L90 24 L96 28" stroke="#c94a2a" stroke-width="2.6" fill="none"/><ellipse cx="92" cy="22" rx="8" ry="4" fill="#e9573a"/>`,
  leader_of_the_pack: `${sky("#cfe3ea", "#eef4ee", "g5")}
    <rect x="0" y="46" width="100" height="18" fill="#d9cdb4"/>
    <path d="M30 64 V30 C30 22 70 22 70 30 V64" fill="#b86a3c"/><path d="M34 60 V32 C34 27 66 27 66 32 V60" fill="#d08850"/>
    <g transform="translate(22 10) scale(.46)">${PORTRAITS.wolf}</g>
    <path d="M41 6 L45 14 L50 7 L55 14 L59 6 L58 16 H42 Z" fill="#f2c443" stroke="#b78f1c" stroke-width="1"/>`,
  getaway_car: `${sky("#6cc8e8", "#cdeef4", "g6")}
    <rect x="0" y="44" width="100" height="20" fill="#7e7c95"/><path d="M0 54 H100" stroke="#fff" stroke-width="1.4" stroke-dasharray="8 6"/>
    <rect x="56" y="10" width="34" height="26" fill="#f6e07c"/><path d="M52 12 L73 2 L94 12 Z" fill="#e48d5c"/><rect x="62" y="18" width="7" height="7" fill="#7cc6e2"/><rect x="76" y="18" width="7" height="7" fill="#7cc6e2"/>
    <path d="M12 46 C12 38 22 36 30 36 L38 30 H58 L66 36 C78 36 88 38 88 46 V50 H12 Z" fill="#e03b3b"/>
    <path d="M40 32 H56 L62 36 H36 Z" fill="#bfe7f4"/><path d="M14 44 H86" stroke="#fff" stroke-width="2" opacity=".8"/>
    <circle cx="28" cy="50" r="7" fill="#262329"/><circle cx="28" cy="50" r="3.4" fill="#e9e9ee"/><circle cx="72" cy="50" r="7" fill="#262329"/><circle cx="72" cy="50" r="3.4" fill="#e9e9ee"/>`,
  masterplan: `${sky("#f2b8a0", "#9f8ad0", "g7")}
    <rect x="0" y="50" width="100" height="14" fill="#5b4a85"/>
    <g fill="#2a2240">
      <ellipse cx="20" cy="38" rx="6" ry="7"/><path d="M13 30 l2 -6 l3 4 M27 30 l-2 -6 l-3 4" stroke="#2a2240" stroke-width="2"/><rect x="14" y="44" width="12" height="20" rx="4"/>
      <ellipse cx="38" cy="30" rx="7" ry="8"/><path d="M30 26 C30 18 46 18 46 26 Z"/><rect x="30" y="37" width="16" height="27" rx="5"/>
      <ellipse cx="56" cy="28" rx="7" ry="8"/><path d="M50 22 l1 -8 l5 6 M62 22 l-1 -8 l-5 6"/><rect x="48" y="35" width="16" height="29" rx="5"/>
      <ellipse cx="74" cy="32" rx="6" ry="7"/><rect x="67" y="38" width="14" height="26" rx="5"/>
      <ellipse cx="90" cy="42" rx="7" ry="9"/><rect x="83" y="48" width="14" height="16" rx="5"/>
      <path d="M70 12 C74 6 82 8 84 4 C84 10 78 14 72 14 Z"/>
    </g>`,
  security_system: `${sky("#3a3f8f", "#e36c5c", "g8")}
    <g fill="#c47a45">${Array.from({ length: 9 }, (_, i) => `<path d="M${i * 12} 64 V38 l5 -6 l5 6 V64 Z"/>`).join("")}</g>
    <rect x="0" y="46" width="100" height="3" fill="#9c5a2e"/>
    <rect x="22" y="22" width="8" height="42" fill="#a56a3e"/>
    <rect x="16" y="10" width="22" height="12" rx="3" fill="#ef7b2e" transform="rotate(-12 27 16)"/><circle cx="36" cy="13" r="3.4" fill="#ff3b3b"/>
    <path d="M38 13 L100 0 V12 Z" fill="#ff5a5a" opacity=".55"/>
    <rect x="52" y="40" width="18" height="12" fill="#e8c38a"/><circle cx="61" cy="46" r="4" fill="none" stroke="#d33" stroke-width="1.6"/><path d="M58 49 L64 43" stroke="#d33" stroke-width="1.6"/>`,
  outpost: `${sky("#8fd0f0", "#e4f4fb", "g9")}
    <rect x="44" y="6" width="9" height="58" fill="#8a5a32"/><rect x="18" y="20" width="62" height="5" fill="#8a5a32"/>
    <path d="M0 30 Q50 22 100 34" stroke="#333" stroke-width="1" fill="none"/>
    ${[22, 34, 60, 72]
      .map(
        (x) => `<g transform="translate(${x} 12)"><ellipse cx="0" cy="4" rx="6" ry="5" fill="#9a97d8"/><circle cx="1" cy="-2" r="3.6" fill="#8f8ad8"/>
      <rect x="-1.5" y="-4" width="5.6" height="2.2" rx="1" fill="#f2542d"/><path d="M-4 -4 C-4 -9 6 -9 6 -4 Z" fill="#b9773f"/><path d="M4 -1 l3 1 -3 1 z" fill="#ead8b2"/></g>`,
      )
      .join("")}`,
  smoke_screen: `${sky("#9bc3e0", "#e8eef2", "g10")}
    <g fill="#5a5a66" opacity=".85"><circle cx="40" cy="14" r="10"/><circle cx="54" cy="10" r="12"/><circle cx="68" cy="16" r="9"/><circle cx="30" cy="22" r="7"/></g>
    <g fill="#fbf6ea">${Array.from({ length: 9 }, (_, i) => `<path d="M${i * 12} 64 V40 l4 -5 l4 5 V64 Z"/>`).join("")}</g>
    <path d="M30 34 H70 C70 46 60 52 50 52 C40 52 30 46 30 34 Z" fill="#d63b2a"/><rect x="28" y="32" width="44" height="3" fill="#333"/>
    <path d="M36 34 Q40 24 44 34 M48 34 Q52 22 56 34 M60 34 Q64 26 68 34" fill="#ff9a2e"/>
    <path d="M40 52 L34 64 M60 52 L66 64 M50 52 V64" stroke="#333" stroke-width="2"/>`,
  brainwashing_device: `${sky("#a7d8e6", "#d7eef0", "g11")}
    <rect x="58" y="6" width="32" height="44" fill="#eef6f8"/><rect x="58" y="6" width="32" height="44" fill="none" stroke="#9cc0c8" stroke-width="2"/>
    <ellipse cx="38" cy="38" rx="26" ry="8" fill="#e9dcc2"/>
    <path d="M18 36 C18 28 58 28 58 36 C58 40 18 40 18 36 Z" fill="#e8a24a"/><path d="M22 34 l32 0 M26 32 l24 0" stroke="#c97d24" stroke-width="1.2"/>
    <g transform="translate(74 26)"><path d="M0 0 m-10 0 a10 10 0 1 0 20 0 a7 7 0 1 0 -14 0 a4 4 0 1 0 8 0" fill="none" stroke="#7a4fc2" stroke-width="2.2"/></g>
    <path d="M24 30 Q28 24 26 18 M36 28 Q40 22 38 16" stroke="#fff" stroke-width="1.6" fill="none" opacity=".8"/>`,
  double_trouble: `${sky("#f6b37a", "#f2d7a8", "g12")}
    <g transform="translate(-4 8) scale(.5) rotate(-6 60 60)">${PORTRAITS.squirrel}</g>
    <g transform="translate(104 8) scale(-.5 .5) rotate(-6 60 60)">${PORTRAITS.squirrel}</g>`,
  surveillance_truck: `${sky("#7cc7e8", "#d9f0f6", "g13")}
    <rect x="0" y="48" width="100" height="16" fill="#e6d6b0"/>
    <path d="M14 48 V22 C14 18 18 16 22 16 H66 C72 16 76 20 78 26 L86 36 V48 Z" fill="#f4a5c0"/>
    <rect x="22" y="22" width="30" height="14" rx="2" fill="#bfe7f4"/><rect x="58" y="22" width="16" height="12" rx="2" fill="#bfe7f4"/>
    <path d="M14 40 H86" stroke="#fff" stroke-width="2"/>
    <path d="M36 6 L40 16 L44 6 Z" fill="#d9a45a"/><circle cx="40" cy="6" r="4" fill="#fff4f8"/>
    <circle cx="28" cy="50" r="6" fill="#2b2930"/><circle cx="72" cy="50" r="6" fill="#2b2930"/>
    <circle cx="66" cy="28" r="2.6" fill="#333"/><path d="M68 28 L74 26" stroke="#333" stroke-width="1.6"/>`,
  secret_recruit: `${sky("#f6e6c2", "#e8cfa0", "g14")}
    <rect x="0" y="0" width="56" height="64" fill="#2a2430"/><rect x="56" y="0" width="44" height="64" fill="#f3e3c3"/>
    <path d="M24 18 C24 8 38 8 38 18 Z" fill="#14101a"/><path d="M18 18 C18 16 44 16 44 18 C44 20 18 20 18 18 Z" fill="#14101a"/>
    <ellipse cx="31" cy="24" rx="7" ry="8" fill="#14101a"/><path d="M20 64 C20 40 42 34 48 40 L52 64 Z" fill="#14101a"/>
    <rect x="66" y="22" width="10" height="16" rx="2" fill="#d9b36a"/><circle cx="71" cy="30" r="2.6" fill="#a37d32"/>
    <path d="M50 44 C56 40 60 34 64 30" stroke="#c48a4a" stroke-width="5" stroke-linecap="round"/>`,
  spycation: `${sky("#f58e6a", "#f7d27c", "g15")}
    <circle cx="74" cy="22" r="11" fill="#ffd06a"/>
    <rect x="0" y="40" width="100" height="8" fill="#43b6c9"/><rect x="0" y="48" width="100" height="16" fill="#f2d39c"/>
    <path d="M10 6 Q40 -4 66 14" stroke="#e04f6a" stroke-width="5" fill="none"/><path d="M38 6 L44 58" stroke="#8a5a32" stroke-width="2"/>
    <path d="M22 58 L32 40 L58 40 L50 58" stroke="#7b4fb0" stroke-width="3" fill="none"/><path d="M30 44 L54 44 L48 56 L26 56 Z" fill="#b28ad8" opacity=".9"/>
    <path d="M64 46 L70 36 M70 36 L74 46" stroke="#fff" stroke-width="1.6"/><path d="M66 36 H74 L70 30 Z" fill="#ff7a9a"/>`,
};

export function marketArt(key) {
  return `<svg class="mart" viewBox="0 0 100 64" preserveAspectRatio="xMidYMid slice" aria-hidden="true">${MARKET_ART[key] || ""}</svg>`;
}

// ---------------------------------------------------------------- the neighbourhood (board centre)
export const STREET = `<svg class="street" viewBox="0 0 300 240" preserveAspectRatio="xMidYMid slice" aria-hidden="true">
  <defs>
    <linearGradient id="st-sky" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="#7fcbe9"/><stop offset=".55" stop-color="#d4f0ec"/></linearGradient>
    <linearGradient id="st-road" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="#8a7fb8"/><stop offset="1" stop-color="#5c5287"/></linearGradient>
  </defs>
  <rect width="300" height="240" fill="url(#st-sky)"/>
  <g fill="#fff" opacity=".9"><ellipse cx="96" cy="70" rx="20" ry="6"/><ellipse cx="110" cy="65" rx="12" ry="7"/><ellipse cx="210" cy="78" rx="22" ry="6"/><ellipse cx="224" cy="73" rx="12" ry="6"/></g>
  <path d="M0 132 Q70 112 150 124 T300 118 V240 H0 Z" fill="#a3d98f"/>
  <g>
    <rect x="72" y="104" width="40" height="30" fill="#f3d0c4"/><path d="M67 106 L92 88 L117 106 Z" fill="#8a6bb3"/><rect x="79" y="112" width="8" height="8" fill="#fff6d0"/><rect x="97" y="112" width="8" height="8" fill="#fff6d0"/>
    <rect x="170" y="96" width="50" height="38" fill="#f6e3a6"/><path d="M164 98 L195 74 L226 98 Z" fill="#d5714d"/><rect x="178" y="106" width="10" height="9" fill="#8fd0ee"/><rect x="202" y="106" width="10" height="9" fill="#8fd0ee"/><rect x="190" y="118" width="9" height="16" fill="#9a5b3b"/>
    <rect x="226" y="108" width="34" height="27" fill="#cfe8f0"/><path d="M221 110 L243 94 L265 110 Z" fill="#5f8fb0"/><rect x="233" y="116" width="8" height="8" fill="#fff6d0"/>
  </g>
  <g><rect x="128" y="96" width="5" height="36" fill="#8a5a32"/><circle cx="130" cy="92" r="17" fill="#5fb45a"/><circle cx="119" cy="99" r="11" fill="#79c76a"/><circle cx="142" cy="98" r="12" fill="#79c76a"/></g>
  <path d="M140 240 C150 200 168 170 152 140 C146 130 152 126 160 126 H170 C178 128 176 134 172 140 C162 168 196 200 222 240 Z" fill="url(#st-road)"/>
  <path d="M168 236 C166 206 170 176 166 146" stroke="#fff" stroke-width="2.2" stroke-dasharray="8 7" fill="none" opacity=".9"/>
  <g fill="#fbf6ea">${Array.from({ length: 7 }, (_, i) => `<path d="M${66 + i * 10} 168 V146 l3.5 -4.5 l3.5 4.5 V168 Z"/>`).join("")}</g>
  <rect x="64" y="154" width="72" height="3" fill="#e9dfc8"/>
  <g fill="#fbf6ea">${Array.from({ length: 6 }, (_, i) => `<path d="M${190 + i * 10} 168 V146 l3.5 -4.5 l3.5 4.5 V168 Z"/>`).join("")}</g>
  <rect x="188" y="154" width="62" height="3" fill="#e9dfc8"/>
  <path d="M0 190 Q80 178 140 196 V240 H0 Z" fill="#8fcf80"/><path d="M220 196 Q270 184 300 190 V240 H210 Z" fill="#8fcf80"/>
  <rect x="236" y="130" width="3" height="40" fill="#555"/><circle cx="237.5" cy="128" r="4" fill="#ffe69a"/>
  <g transform="translate(210 176)"><path d="M0 8 C0 2 26 2 26 8 L28 14 H-2 Z" fill="#e03b3b"/><circle cx="5" cy="14" r="3" fill="#333"/><circle cx="21" cy="14" r="3" fill="#333"/><path d="M6 4 H18 L21 8 H4 Z" fill="#bfe7f4"/></g>
</svg>`;
