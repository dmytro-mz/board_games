// The ring: geometry (axial cells -> board percentages), the board drawing and the marble element.
//
// Cells are pointy-top hexagons in axial coordinates (q, r), r growing downwards; one unit is a cell's radius.
// The drawing is BW × BH units centred on the middle cell; `flip` turns it 180° so White sits at the bottom.

import { h, s } from "/static/shared/dom.js";

const SQ3 = Math.sqrt(3);
export const R_IN = 8.25; // the clay floor (a flat-topped hexagon around the cells)
export const R_OUT = 9.7; // outer edge of the rope
export const BW = 2 * R_OUT + 0.8;
export const BH = R_OUT * SQ3 + 0.8;
export const DIR_ANGLE = [0, -60, -120, 180, 120, 60]; // screen angle of each direction (degrees, y down)

let BOARD = { cells: [], names: [], dirs: [] };
export function setBoard(board) {
  BOARD = board;
}
export const cellCount = () => BOARD.cells.length;
export const cellName = (c) => BOARD.names[c] || "?";

export function xy(cell, flip) {
  const [q, r] = BOARD.cells[cell];
  const x = SQ3 * (q + r / 2);
  const y = 1.5 * r;
  return flip ? { x: -x, y: -y } : { x, y };
}

// Board units -> percent of the board box.
export const pct = (p) => ({ left: ((p.x + BW / 2) / BW) * 100, top: ((p.y + BH / 2) / BH) * 100 });

export function neighbour(cell, d) {
  if (cell == null || cell < 0 || cell >= BOARD.cells.length) return -1;
  const [q, r] = BOARD.cells[cell];
  const [dq, dr] = BOARD.dirs[d];
  const key = `${q + dq},${r + dr}`;
  if (!neighbour.index) neighbour.index = new Map(BOARD.cells.map(([a, b], i) => [`${a},${b}`, i]));
  return neighbour.index.get(key) ?? -1;
}

// The screen angle of direction d for this viewer.
export const screenAngle = (d, flip) => DIR_ANGLE[d] + (flip ? 180 : 0);

function hexPoints(radius, flatTop = true, cx = 0, cy = 0) {
  const pts = [];
  for (let i = 0; i < 6; i++) {
    const a = ((flatTop ? 0 : 30) + 60 * i) * (Math.PI / 180);
    pts.push(`${(cx + radius * Math.cos(a)).toFixed(3)},${(cy + radius * Math.sin(a)).toFixed(3)}`);
  }
  return pts.join(" ");
}

// Shared gradients (one copy per page).
export function installDefs() {
  if (document.getElementById("sumo-defs")) return;
  const svg = s(
    "svg",
    { id: "sumo-defs", class: "defs-holder", "aria-hidden": "true", width: 0, height: 0 },
    s(
      "defs",
      {},
      s("radialGradient", { id: "g-clay", cx: "50%", cy: "42%", r: "62%" }, s("stop", { offset: "0", "stop-color": "#e9cf9f" }), s("stop", { offset: "0.7", "stop-color": "#d6b17a" }), s("stop", { offset: "1", "stop-color": "#b98b55" })),
      s("radialGradient", { id: "g-dimple", cx: "50%", cy: "38%", r: "60%" }, s("stop", { offset: "0", "stop-color": "#8e6436" }), s("stop", { offset: "0.75", "stop-color": "#b48650" }), s("stop", { offset: "1", "stop-color": "#e7c995" })),
      s("linearGradient", { id: "g-rope", x1: "0", y1: "0", x2: "0", y2: "1" }, s("stop", { offset: "0", "stop-color": "#f0d58c" }), s("stop", { offset: "0.5", "stop-color": "#c99a45" }), s("stop", { offset: "1", "stop-color": "#8a6224" })),
      s("linearGradient", { id: "g-base", x1: "0", y1: "0", x2: "0", y2: "1" }, s("stop", { offset: "0", "stop-color": "#5b3a22" }), s("stop", { offset: "1", "stop-color": "#2e1c10" })),
      s("pattern", { id: "p-grain", width: 1.4, height: 1.4, patternUnits: "userSpaceOnUse" }, s("circle", { cx: 0.35, cy: 0.4, r: 0.07, fill: "rgba(90,55,20,0.18)" }), s("circle", { cx: 1.05, cy: 1.0, r: 0.05, fill: "rgba(255,240,210,0.25)" })),
    ),
  );
  document.body.prepend(svg);
}

// The board drawing: the earthen base, the twisted rope, the clay floor and a dimple for every cell.
export function boardSvg({ flip = false, mini = false, cls = "board-svg", layout = null } = {}) {
  const vb = `${-BW / 2} ${-BH / 2} ${BW} ${BH}`;
  const parts = [];
  parts.push(s("polygon", { points: hexPoints(R_OUT + 0.35), fill: "url(#g-base)" }));
  parts.push(s("polygon", { points: hexPoints(R_OUT - 0.25), fill: "none", stroke: "url(#g-rope)", "stroke-width": 1.15, "stroke-linejoin": "round" }));
  if (!mini) parts.push(s("polygon", { points: hexPoints(R_OUT - 0.25), fill: "none", stroke: "rgba(110,74,26,0.55)", "stroke-width": 1.15, "stroke-dasharray": "0.09 0.42", "stroke-linejoin": "round", class: "rope-twist" }));
  parts.push(s("polygon", { points: hexPoints(R_IN), fill: "url(#g-clay)", stroke: "#8c6233", "stroke-width": 0.18 }));
  if (!mini) parts.push(s("polygon", { points: hexPoints(R_IN), fill: "url(#p-grain)" }));
  const n = BOARD.cells.length;
  for (let c = 0; c < n; c++) {
    const p = xy(c, flip);
    parts.push(s("circle", { cx: p.x.toFixed(3), cy: p.y.toFixed(3), r: mini ? 0.62 : 0.74, fill: "url(#g-dimple)", class: "dimple" }));
  }
  if (layout) {
    const dot = (c, side) => {
      const p = xy(c, flip);
      return s("circle", { cx: p.x.toFixed(3), cy: p.y.toFixed(3), r: 0.74, class: `mini-marble m${side}` });
    };
    for (const c of layout.black) parts.push(dot(c, 0));
    for (const c of layout.white) parts.push(dot(c, 1));
  }
  return s("svg", { class: cls, viewBox: vb, preserveAspectRatio: "xMidYMid meet", "aria-hidden": "true" }, parts);
}

// A marble: a shiny sphere drawn with CSS gradients; `side` 0 = black, 1 = white.
export function marble(side, attrs = {}) {
  return h("div", { ...attrs, class: `marble m${side} ${attrs.class || ""}`.trim() }, h("i", { class: "shine" }));
}
