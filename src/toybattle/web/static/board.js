// The terrain drawn as one SVG: the floor art of its palette inside a raised rim, medal regions, paths, bases and
// the two H.Q. forts. Terrain coordinates live in a 100 × 160 box; the drawing adds a margin of PAD all round
// (BW × BH) so the forts and tiles on the edge rows are never cut off. `flip` turns the board 180° so every
// player sees their own H.Q. at the bottom.

import { s } from "/static/shared/dom.js";
import { SIDE_COLORS, armyStyle } from "./art.js";

export const W = 100;
export const H = 160;
export const TILE = 15; // troop tile size in board units
export const PAD = 9;
export const BW = W + 2 * PAD;
export const BH = H + 2 * PAD;
// Where a terrain point sits on the drawn board, in % of its width / height.
export const pct = (p) => ({ left: ((p.x + PAD) / BW) * 100, top: ((p.y + PAD) / BH) * 100 });

export const at = (node, flip) => (flip ? { x: W - node.x, y: H - node.y } : { x: node.x, y: node.y });

function rand(seed) {
  let x = 0;
  for (const c of seed) x = (x * 31 + c.charCodeAt(0)) >>> 0;
  return () => {
    x = (x * 1664525 + 1013904223) >>> 0;
    return x / 2 ** 32;
  };
}

// Per palette: floor colours, the look of paths and regions, and a decoration painter.
export const PALETTES = {
  rug: {
    floor: ["#b8452f", "#8f2f22"],
    path: "#fff4dc",
    dash: "2.2 2",
    region: "#ffe7b8",
    base: ["#fbe7c4", "#c98f5a"],
    special: ["#ffd54a", "#b07800"],
    deco: (g, r) => {
      g.push(s("rect", { x: -2.5, y: -2.5, width: 105, height: 165, rx: 5, fill: "none", stroke: "#e9b44c", "stroke-width": 1.6 }));
      g.push(s("rect", { x: 0, y: 0, width: 100, height: 160, rx: 4, fill: "none", stroke: "#f6d9a4", "stroke-width": 0.6, "stroke-dasharray": "1.5 1.5" }));
      for (let i = 0; i < 26; i++) {
        const x = 8 + r() * 84;
        const y = 8 + r() * 144;
        const k = 1.4 + r() * 2;
        g.push(s("path", { d: `M${x} ${y - k} L${x + k} ${y} L${x} ${y + k} L${x - k} ${y}z`, fill: "#d9663f", opacity: 0.55 }));
      }
      for (let x = -2; x <= 102; x += 4) {
        g.push(s("path", { d: `M${x} -6 v2.5 M${x} 163.5 v2.5`, stroke: "#f6d9a4", "stroke-width": 0.8 }));
      }
    },
  },
  lagoon: {
    floor: ["#55c3e6", "#1f7fb4"],
    path: "#ffffff",
    dash: "0.1 2.6",
    region: "#c9f3ff",
    base: ["#ffffff", "#7fc6e2"],
    special: ["#ffe36b", "#d29b00"],
    deco: (g, r) => {
      for (let i = 0; i < 34; i++) {
        const x = r() * 100;
        const y = r() * 160;
        const rr = 0.8 + r() * 2.6;
        g.push(s("circle", { cx: x, cy: y, r: rr, fill: "none", stroke: "#e8fbff", "stroke-width": 0.5, opacity: 0.7 }));
        g.push(s("circle", { cx: x - rr * 0.35, cy: y - rr * 0.35, r: rr * 0.25, fill: "#fff", opacity: 0.6 }));
      }
      for (let y = 10; y < 160; y += 22) {
        g.push(s("path", { d: `M0 ${y} q12 -4 25 0 t25 0 t25 0 t25 0`, fill: "none", stroke: "#bdeeff", "stroke-width": 0.6, opacity: 0.6 }));
      }
    },
  },
  pillow: {
    floor: ["#c6b3ec", "#8d73c7"],
    path: "#fff8ff",
    dash: "1.6 1.4",
    region: "#f6eaff",
    base: ["#ffffff", "#e3c8f2"],
    special: ["#ffd0e6", "#d46a9c"],
    deco: (g) => {
      for (let x = 0; x <= 100; x += 20) g.push(s("path", { d: `M${x} 0 V160`, stroke: "#e9dcff", "stroke-width": 0.5, "stroke-dasharray": "1 1.2", opacity: 0.8 }));
      for (let y = 0; y <= 160; y += 20) g.push(s("path", { d: `M0 ${y} H100`, stroke: "#e9dcff", "stroke-width": 0.5, "stroke-dasharray": "1 1.2", opacity: 0.8 }));
      for (let x = 0; x <= 100; x += 20) for (let y = 0; y <= 160; y += 20) g.push(s("circle", { cx: x, cy: y, r: 0.9, fill: "#a58bd8" }));
    },
  },
  lava: {
    floor: ["#ff7a22", "#b3200b"],
    path: "#ffe4a8",
    dash: "3 1.6",
    region: "#ffcf8a",
    base: ["#a87447", "#5b3218"],
    special: ["#ffe14d", "#c25b00"],
    deco: (g, r) => {
      for (let i = 0; i < 14; i++) {
        let x = r() * 100;
        let y = r() * 160;
        let d = `M${x} ${y}`;
        for (let k = 0; k < 4; k++) {
          x += (r() - 0.5) * 14;
          y += (r() - 0.5) * 14;
          d += ` L${x} ${y}`;
        }
        g.push(s("path", { d, fill: "none", stroke: "#ffd23f", "stroke-width": 0.8, opacity: 0.6, "stroke-linecap": "round" }));
      }
      for (let i = 0; i < 18; i++) g.push(s("circle", { cx: r() * 100, cy: r() * 160, r: 0.6 + r() * 1.4, fill: "#ffe27a", opacity: 0.5 }));
    },
  },
  attic: {
    floor: ["#4a3a5e", "#1d1628"],
    path: "#d7c9ff",
    dash: "1.8 1.6",
    region: "#8a79b5",
    base: ["#b99566", "#6b4a2a"],
    special: ["#bcd2ff", "#5367b8"],
    deco: (g, r) => {
      for (let x = 0; x < 100; x += 12.5) {
        g.push(s("path", { d: `M${x} 0 V160`, stroke: "#120d19", "stroke-width": 0.7, opacity: 0.7 }));
        const y = r() * 140;
        g.push(s("path", { d: `M${x} ${y} h12.5`, stroke: "#120d19", "stroke-width": 0.6, opacity: 0.6 }));
      }
      g.push(s("path", { d: "M70 0 L100 0 L100 60 L30 160 L0 160 Z", fill: "#e9e4ff", opacity: 0.06 }));
      g.push(s("circle", { cx: 88, cy: 10, r: 6, fill: "#fff7d6", opacity: 0.85 }));
      g.push(s("circle", { cx: 85.5, cy: 8.5, r: 5.4, fill: "#2d2340" }));
      for (let i = 0; i < 12; i++) g.push(s("circle", { cx: r() * 100, cy: r() * 160, r: 0.4, fill: "#fff", opacity: 0.6 }));
    },
  },
  gutter: {
    floor: ["#7a96a8", "#3e5a6e"],
    path: "#f3f7fa",
    dash: "2.4 1.2",
    region: "#cfe3ee",
    base: ["#fff7e6", "#c9b38b"],
    special: ["#ffffff", "#9fb4c2"],
    deco: (g, r) => {
      for (let y = 6; y < 160; y += 10) {
        g.push(s("path", { d: `M0 ${y} q10 3 20 0 t20 0 t20 0 t20 0 t20 0`, fill: "none", stroke: "#a9c3d3", "stroke-width": 0.5, opacity: 0.6 }));
      }
      for (let i = 0; i < 9; i++) {
        const x = r() * 100;
        const y = r() * 160;
        const a = r() * 360;
        g.push(s("path", { d: "M0 0 q4 -4 8 0 q-4 4 -8 0z M0 0 h8", fill: "#8fbf4a", stroke: "#4f7a22", "stroke-width": 0.4, transform: `translate(${x} ${y}) rotate(${a})`, opacity: 0.85 }));
      }
    },
  },
  workshop: {
    floor: ["#8b98a6", "#4b5663"],
    path: "#ffd54a",
    dash: "3 1.5",
    region: "#d9e1ea",
    base: ["#e8edf2", "#8a96a3"],
    special: ["#ffd54a", "#a87800"],
    deco: (g, r) => {
      for (let x = 4; x < 100; x += 11) for (let y = 4; y < 160; y += 11) g.push(s("circle", { cx: x, cy: y, r: 0.5, fill: "#2e3640", opacity: 0.5 }));
      for (const y of [-5.5, 161.5]) {
        for (let x = -12; x < 112; x += 8) g.push(s("path", { d: `M${x} ${y} l4 0 l4 4 l-4 0z`, fill: "#ffd54a", opacity: 0.8 }));
      }
      for (let i = 0; i < 4; i++) {
        const x = 10 + r() * 80;
        const y = 20 + r() * 120;
        g.push(s("circle", { cx: x, cy: y, r: 4, fill: "none", stroke: "#36404b", "stroke-width": 1.2, "stroke-dasharray": "1.4 1", opacity: 0.4 }));
      }
    },
  },
  sandpit: {
    floor: ["#f1d38c", "#cf9f4f"],
    path: "#7a5427",
    dash: "1.2 1.8",
    region: "#fff0c4",
    base: ["#fff6dc", "#d8b06a"],
    special: ["#ff9d2e", "#a85400"],
    deco: (g, r) => {
      for (let i = 0; i < 120; i++) g.push(s("circle", { cx: r() * 100, cy: r() * 160, r: 0.25 + r() * 0.45, fill: "#a87a3a", opacity: 0.45 }));
      for (let i = 0; i < 5; i++) {
        const x = r() * 100;
        const y = r() * 160;
        g.push(s("path", { d: `M${x} ${y} q6 -3 12 0`, fill: "none", stroke: "#b8893f", "stroke-width": 0.8, opacity: 0.5 }));
      }
    },
  },
};

export const palette = (key) => PALETTES[key] || PALETTES.rug;

export const FX_ICON = { recall: "fx-recall", draw: "fx-draw", move: "fx-move", revive: "fx-revive", shield: "fx-shield", snipe: "fx-snipe", restrict: "fx-restrict" };

// The static part of a board. `taken`: region id -> owner, to colour taken regions; `mini` skips small detail.
export function boardSvg(terrain, { flip = false, special = true, taken = null, mini = false, id = null } = {}) {
  const p = palette(terrain.palette);
  const nodes = terrain.nodes;
  const P = (n) => at(nodes[n], flip);
  const r = rand(terrain.key);
  const uid = `${terrain.key}${mini ? "m" : ""}${flip ? "f" : ""}`;
  const deco = [];
  p.deco(deco, r);
  const regions = terrain.regions.map((reg) => {
    const pts = reg.ring.map((n) => {
      const q = P(n);
      return `${q.x},${q.y}`;
    });
    const owner = taken ? taken[reg.id] : null;
    const c = owner != null ? SIDE_COLORS[owner] : null;
    const center = at({ x: reg.cx, y: reg.cy }, flip);
    return s(
      "g",
      { class: `region ${owner != null ? `taken s${owner}` : ""}`, "data-region": reg.id },
      s("polygon", { points: pts.join(" "), fill: c ? c.army : p.region, opacity: c ? 0.45 : 0.14, "stroke-linejoin": "round" }),
      c ? s("polygon", { points: pts.join(" "), fill: "none", stroke: c.light, "stroke-width": 0.8, opacity: 0.9, "stroke-dasharray": "1.6 1.2" }) : null,
      reg.medals > 0
        ? s(
            "g",
            { class: "region-medal", transform: `translate(${center.x} ${center.y})` },
            c ? s("circle", { r: 6.2, cy: 1.6, fill: c.dark, stroke: c.light, "stroke-width": 0.8 }) : null,
            s("use", { href: "#medal-plain", x: -5.6, y: -5.2, width: 11.2, height: 11.2, filter: c ? null : "drop-shadow(0 0.6px 0.6px rgba(0,0,0,.5))" }),
            s("text", { class: "medal-n", y: 1.9, "text-anchor": "middle", "dominant-baseline": "central" }, String(reg.medals)),
          )
        : null,
    );
  });
  const edges = terrain.edges.map(([a, b]) => {
    const A = P(a);
    const B = P(b);
    const line = (stroke, width, extra = {}) => s("line", { x1: A.x, y1: A.y, x2: B.x, y2: B.y, stroke, "stroke-width": width, "stroke-linecap": "round", ...extra });
    return s("g", {}, line("rgba(0,0,0,0.32)", 3.4, { transform: "translate(0 0.5)" }), line(p.path, 2.4, { opacity: 0.35 }), line(p.path, 1.1, { "stroke-dasharray": p.dash }));
  });
  const fx = special && terrain.effect !== "none" ? FX_ICON[terrain.effect] : null;
  const bases = nodes.map((n) => {
    const q = P(n.id);
    if (n.kind === "hq") {
      const size = 25;
      const c = SIDE_COLORS[n.side];
      return s(
        "g",
        { class: `hq s${n.side}`, "data-node": n.id, style: armyStyle(n.side) },
        s("ellipse", { cx: q.x, cy: q.y + 1.2, rx: 11.5, ry: 10.5, fill: "rgba(0,0,0,0.4)" }),
        s("circle", { cx: q.x, cy: q.y, r: 11, fill: c.dark, stroke: c.light, "stroke-width": 0.9 }),
        s("circle", { cx: q.x, cy: q.y, r: 9.4, fill: c.army, opacity: 0.6 }),
        s("circle", { cx: q.x, cy: q.y, r: 9.4, fill: "none", stroke: "#fff", "stroke-width": 0.5, "stroke-dasharray": "1.2 1", opacity: 0.7 }),
        s("use", { href: "#fort", x: q.x - size / 2, y: q.y - size / 2 - 2, width: size, height: size }),
        n.allow && special ? allowBadge(n.allow, q, true) : null,
      );
    }
    const isSpecial = n.kind === "special" && !!fx;
    const [light, dark] = isSpecial ? p.special : p.base;
    const g = [
      s("circle", { cx: q.x, cy: q.y + 1.2, r: 8.6, fill: "rgba(0,0,0,0.42)" }),
      s("circle", { cx: q.x, cy: q.y, r: 8.4, fill: `url(#rim-${uid}-${isSpecial ? "s" : "b"})`, stroke: "rgba(0,0,0,0.55)", "stroke-width": 0.6 }),
      s("circle", { cx: q.x, cy: q.y, r: 6.5, fill: `url(#base-${uid}-${isSpecial ? "s" : "b"})`, stroke: dark, "stroke-width": 0.6 }),
      s("path", { d: `M${q.x - 5} ${q.y - 3.4} A6 6 0 0 1 ${q.x + 3.4} ${q.y - 5}`, fill: "none", stroke: "#fff", "stroke-width": 0.9, "stroke-linecap": "round", opacity: 0.55 }),
    ];
    if (isSpecial) {
      g.push(s("circle", { cx: q.x, cy: q.y, r: 9.4, fill: "none", stroke: light, "stroke-width": 0.7, "stroke-dasharray": "1.4 1.1", opacity: 0.9 }));
      if (terrain.effect !== "restrict") g.push(s("use", { href: `#${fx}`, x: q.x - 4.2, y: q.y - 4.2, width: 8.4, height: 8.4 }));
    }
    if (n.allow && special) g.push(allowBadge(n.allow, q, false));
    return s("g", { class: `base ${isSpecial ? "special" : ""}`, "data-node": n.id }, g);
  });
  const grad = (gid, [a, b]) => s("radialGradient", { id: gid, cx: 0.4, cy: 0.35, r: 0.75 }, s("stop", { offset: 0, "stop-color": a }), s("stop", { offset: 1, "stop-color": b }));
  const rimGrad = (gid, [a, b]) => s("linearGradient", { id: gid, x1: 0, y1: 0, x2: 0, y2: 1 }, s("stop", { offset: 0, "stop-color": a }), s("stop", { offset: 0.5, "stop-color": b }), s("stop", { offset: 1, "stop-color": "#1b1426" }));
  const defs = s(
    "defs",
    {},
    s("linearGradient", { id: `floor-${uid}`, x1: 0, y1: 0, x2: 0.3, y2: 1 }, s("stop", { offset: 0, "stop-color": p.floor[0] }), s("stop", { offset: 1, "stop-color": p.floor[1] })),
    grad(`base-${uid}-b`, p.base),
    grad(`base-${uid}-s`, p.special),
    rimGrad(`rim-${uid}-b`, ["#ffffff", p.base[1]]),
    rimGrad(`rim-${uid}-s`, ["#fff7c2", p.special[1]]),
    s("radialGradient", { id: `vig-${uid}`, cx: 0.5, cy: 0.5, r: 0.75 }, s("stop", { offset: 0.6, "stop-color": "#000", "stop-opacity": 0 }), s("stop", { offset: 1, "stop-color": "#000", "stop-opacity": 0.38 })),
    s("linearGradient", { id: `frame-${uid}`, x1: 0, y1: 0, x2: 0.4, y2: 1 }, s("stop", { offset: 0, "stop-color": "#4b3f86" }), s("stop", { offset: 0.5, "stop-color": "#2a2352" }), s("stop", { offset: 1, "stop-color": "#151129" })),
    s("clipPath", { id: `clip-${uid}` }, s("rect", { x: -PAD + 3.5, y: -PAD + 3.5, width: BW - 7, height: BH - 7, rx: 6 })),
  );
  const inner = { x: -PAD + 3.5, y: -PAD + 3.5, width: BW - 7, height: BH - 7, rx: 6 };
  return s(
    "svg",
    { class: `board-svg ${mini ? "mini" : ""}`, viewBox: `${-PAD} ${-PAD} ${BW} ${BH}`, preserveAspectRatio: "xMidYMid meet", id, "aria-hidden": "true" },
    defs,
    // the raised rim of the board, with a gold inlay
    s("rect", { x: -PAD, y: -PAD, width: BW, height: BH, rx: 9, fill: `url(#frame-${uid})` }),
    s("rect", { x: -PAD + 0.8, y: -PAD + 0.8, width: BW - 1.6, height: BH - 1.6, rx: 8.4, fill: "none", stroke: "#fff", "stroke-opacity": 0.22, "stroke-width": 0.8 }),
    s("rect", { ...inner, fill: `url(#floor-${uid})`, stroke: "#e8b53a", "stroke-width": 1.3 }),
    s("g", { "clip-path": `url(#clip-${uid})` }, s("g", { class: "deco" }, mini ? deco.slice(0, 40) : deco), s("rect", { ...inner, fill: `url(#vig-${uid})` })),
    s("rect", { ...inner, fill: "none", stroke: "#000", "stroke-opacity": 0.35, "stroke-width": 0.6, transform: "translate(0 0.6)" }),
    s("g", { class: "regions" }, regions),
    s("g", { class: "edges" }, edges),
    s("g", { class: "nodes" }, bases),
  );
}

function allowBadge(allow, q, hq) {
  const label = allow.join("·");
  const y = q.y + (hq ? 10.5 : 7.6);
  const w = 3.4 + label.length * 1.9;
  return s("g", { class: "allow" }, s("rect", { x: q.x - w / 2, y: y - 2.5, width: w, height: 5, rx: 2.5, fill: "#ffffff", stroke: "#e0533d", "stroke-width": 0.7 }), s("text", { x: q.x, y: y + 0.2, "text-anchor": "middle", "dominant-baseline": "middle", class: "allow-t" }, label));
}
