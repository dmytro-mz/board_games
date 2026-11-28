// The rule book (our own words), opened from the lobby and from the table, with small move diagrams.

import { h, openDialog, s } from "/static/shared/dom.js";
import { boardSvg } from "./board.js";

const SQ3 = Math.sqrt(3);
const DIRS = [
  [1, 0],
  [1, -1],
  [0, -1],
  [-1, 0],
  [-1, 1],
  [0, 1],
];
const ANG = [0, -60, -120, 180, 120, 60];
const px = ([q, r]) => ({ x: SQ3 * (q + r / 2), y: 1.5 * r });

// A patch of the ring. `cells`: [q, r] pairs; `marbles`: {"q,r": side}; arrows: [{at: [q, r], dir, bad}];
// `ghosts`: cells where a marble ends up (dashed); `edge`: [q, r, dir] draws the rope beyond that cell.
function patch({ cells, marbles = {}, ghosts = [], arrows = [], edge = null, cross = null }) {
  const pts = cells.map(px);
  if (edge) {
    const p = px([edge[0] + DIRS[edge[2]][0], edge[1] + DIRS[edge[2]][1]]);
    pts.push(p);
  }
  const minX = Math.min(...pts.map((p) => p.x)) - 1.2;
  const maxX = Math.max(...pts.map((p) => p.x)) + 1.2;
  const minY = Math.min(...pts.map((p) => p.y)) - 1.2;
  const maxY = Math.max(...pts.map((p) => p.y)) + 1.2;
  const parts = [s("rect", { x: minX, y: minY, width: maxX - minX, height: maxY - minY, rx: 0.8, fill: "url(#g-clay)" })];
  if (edge) {
    const [q, r, d] = edge;
    const c = px([q, r]);
    const a = (ANG[d] * Math.PI) / 180;
    const ex = c.x + Math.cos(a) * 1.25;
    const ey = c.y + Math.sin(a) * 1.25;
    const nx = -Math.sin(a) * 1.6;
    const ny = Math.cos(a) * 1.6;
    parts.push(s("line", { x1: ex - nx, y1: ey - ny, x2: ex + nx, y2: ey + ny, stroke: "#c99a45", "stroke-width": 0.6, "stroke-linecap": "round" }));
  }
  for (const c of cells) {
    const p = px(c);
    parts.push(s("circle", { cx: p.x, cy: p.y, r: 0.74, fill: "url(#g-dimple)" }));
  }
  for (const [key, side] of Object.entries(marbles)) {
    const p = px(key.split(",").map(Number));
    parts.push(s("circle", { cx: p.x, cy: p.y, r: 0.78, class: `mini-marble m${side}` }));
    parts.push(s("ellipse", { cx: p.x - 0.25, cy: p.y - 0.3, rx: 0.24, ry: 0.15, fill: "rgba(255,255,255,0.55)" }));
  }
  for (const g of ghosts) {
    const p = px(g);
    parts.push(s("circle", { cx: p.x, cy: p.y, r: 0.72, class: "d-ghost" }));
  }
  for (const ar of arrows) {
    const p = px(ar.at);
    const a = ANG[ar.dir];
    parts.push(s("path", { d: "M -0.55 -0.28 L 0.15 -0.28 L 0.15 -0.55 L 0.7 0 L 0.15 0.55 L 0.15 0.28 L -0.55 0.28 Z", class: `d-arrow ${ar.bad ? "bad" : ""}`, transform: `translate(${p.x} ${p.y}) rotate(${a})` }));
  }
  if (cross) {
    const p = px(cross);
    parts.push(s("path", { d: `M ${p.x - 0.5} ${p.y - 0.5} L ${p.x + 0.5} ${p.y + 0.5} M ${p.x + 0.5} ${p.y - 0.5} L ${p.x - 0.5} ${p.y + 0.5}`, class: "d-cross" }));
  }
  return s("svg", { viewBox: `${minX} ${minY} ${maxX - minX} ${maxY - minY}`, "aria-hidden": "true", style: { width: `${((maxX - minX) * 20).toFixed(0)}px` } }, parts);
}

const row = (n, r = 0, q0 = 0) => Array.from({ length: n }, (_, i) => [q0 + i, r]);
const m = (list, side) => Object.fromEntries(list.map(([q, r]) => [`${q},${r}`, side]));
// an arrow drawn halfway between a cell and its neighbour in direction d
const between = ([q, r], d, bad = false) => ({ at: [q + DIRS[d][0] / 2, r + DIRS[d][1] / 2], dir: d, bad });

function diagram(svg, text, ok = true) {
  return h("div", { class: `diagram ${ok ? "" : "no"}` }, svg, h("p", {}, ...text));
}

export function showRules(config) {
  const tabs = [
    ["basics", "The game"],
    ["moves", "Moving & pushing"],
    ["openings", "Openings"],
    ["table", "At this table"],
  ];
  let tab = "basics";
  const body = h("div", { class: "rules-body" });
  const nav = h("div", { class: "rules-tabs" });
  const sec = (title, ...children) => h("section", {}, h("h3", {}, title), ...children);
  const p = (...c) => h("p", {}, ...c);
  const li = (...c) => h("li", {}, ...c);
  const toWin = config.to_win || 6;

  const pages = {
    basics: () => [
      sec(
        "Goal",
        p(`Two teams of ${config.marbles || 14} marbles, black and white, share a hexagonal ring of 61 dimples. You win the moment you have pushed `, h("b", {}, `${toWin} of your rival's marbles`), " out of the ring."),
      ),
      sec(
        "Your turn",
        p("Black moves first, then you take turns. On your turn you make exactly one move: pick ", h("b", {}, "one, two or three"), " of your marbles that stand next to each other in a straight line, and move them all ", h("b", {}, "one step"), " in the same direction."),
        h(
          "ul",
          {},
          li(h("b", {}, "Along the line"), " (in line): the front marble steps forward and the others follow it. This is the only way to push."),
          li(h("b", {}, "Sideways"), ": two or three marbles each step into the empty dimple next to them, in one of the four other directions. Every one of those dimples must be empty."),
        ),
        p("You can never pass, and a marble never leaves the ring on its own: only rival marbles go out, pushed by you."),
      ),
      sec(
        "Pushing",
        p("When an in-line move runs into rival marbles in the same line, you may push them one step if ", h("b", {}, "you are more"), ": two push one, three push one or two. Four or more never move together, so three is the strongest push."),
        p("Behind the pushed marbles there must be an empty dimple or the edge of the ring. If it is the edge, the last rival marble falls out: that one counts towards your ", toWin, "."),
      ),
      sec("Tips", h("ul", {}, li("Keep your marbles together: a tight group is hard to push and pushes hard."), li("The middle is strong. Marbles on the edge are in danger."), li("A pushed line can push back next turn if it is now bigger than yours."))),
    ],
    moves: () => [
      sec(
        "Moves",
        h(
          "div",
          { class: "diagrams" },
          diagram(patch({ cells: row(5), marbles: m(row(3), 0), ghosts: [[3, 0]], arrows: [between([2, 0], 0)] }), [h("b", {}, "In line. "), "Three marbles step forward; the front one moves into the empty dimple."]),
          diagram(patch({ cells: [...row(3, 0), ...row(3, -1, 1)], marbles: m(row(3, 0), 0), ghosts: row(3, -1, 1), arrows: [between([1, 0], 1)] }), [h("b", {}, "Sideways. "), "Each marble steps into the free dimple next to it, all in the same direction."]),
          diagram(patch({ cells: row(4), marbles: m([[0, 0]], 1), ghosts: [[1, 0]], arrows: [between([0, 0], 0)] }), [h("b", {}, "One marble "), "may step into any empty dimple next to it."]),
        ),
      ),
      sec(
        "Pushes",
        h(
          "div",
          { class: "diagrams" },
          diagram(patch({ cells: row(5), marbles: { ...m(row(2), 0), "2,0": 1 }, ghosts: [[3, 0]], arrows: [between([1, 0], 0)] }), [h("b", {}, "Two push one. "), "The white marble moves back one dimple."]),
          diagram(patch({ cells: row(6), marbles: { ...m(row(3), 0), "3,0": 1, "4,0": 1 }, ghosts: [[5, 0]], arrows: [between([2, 0], 0)] }), [h("b", {}, "Three push two. "), "Three is the most that can push."]),
          diagram(patch({ cells: row(3), marbles: { ...m(row(2), 0), "2,0": 1 }, edge: [2, 0, 0], arrows: [between([1, 0], 0)] }), [h("b", {}, "Out! "), "With the edge right behind, the pushed marble falls out of the ring."]),
        ),
      ),
      sec(
        "Not allowed",
        h(
          "div",
          { class: "diagrams" },
          diagram(patch({ cells: row(5), marbles: { ...m(row(2), 0), ...m(row(2, 0, 2), 1) }, arrows: [between([1, 0], 0, true)], cross: [2, 0] }), [h("b", {}, "Two against two. "), "Equal numbers never push. You must be more."], false),
          diagram(patch({ cells: row(5), marbles: { ...m(row(3), 0), "3,0": 1, "4,0": 0 }, arrows: [between([2, 0], 0, true)], cross: [3, 0] }), [h("b", {}, "Blocked. "), "Behind the rival there is one of your own marbles: no push."], false),
          diagram(patch({ cells: row(4), marbles: { "0,0": 0, "1,0": 1 }, arrows: [between([0, 0], 0, true)], cross: [1, 0] }), [h("b", {}, "One alone "), "can never push, and sideways moves never push at all."], false),
        ),
      ),
    ],
    openings: () => [
      sec(
        "Three ways to start",
        p("The host picks the opening in the lobby (or lets chance decide). The rules are the same in all three."),
        h(
          "div",
          { class: "layout-list" },
          (config.layouts || []).map((l) => h("div", { class: "layout-row" }, h("div", { class: "mini-board" }, boardSvg({ mini: true, layout: l, cls: "mini-svg" })), h("div", {}, h("h4", {}, l.name), h("p", {}, l.blurb)))),
        ),
      ),
    ],
    table: () => [
      sec(
        "Making a move here",
        h(
          "ul",
          {},
          li(h("b", {}, "Tap"), " one of your marbles, then tap more of them in the same line (up to three). Gold arrows show where the group can go; a red one is a push. Tap an arrow, or the glowing dimple where the front marble would land."),
          li(h("b", {}, "Drag"), " a marble in a direction to move it at once, together with your marbles right in front of it (a push, if rivals are in the way). Dragging a selected marble moves the whole selection."),
          li("Tap a selected marble again to drop it from the group; ", h("b", {}, "Esc"), " clears the selection."),
        ),
      ),
      sec(
        "Table options",
        h(
          "ul",
          {},
          li(h("b", {}, "Move limit: "), "two careful players can circle each other for a long time. With a limit, the game ends after that many moves each, and whoever lost fewer marbles wins (equal: a draw)."),
          li(h("b", {}, "Turn timer: "), "when your time runs out, the autopilot moves for you."),
          li(h("b", {}, "Resign: "), "from the ⋯ menu, if the game is lost."),
          li(h("b", {}, "Bots: "), "the Rookie, the Ozeki and the Yokozuna, from gentle to strong. The board turns so your marbles are at the bottom."),
        ),
      ),
    ],
  };

  const show = (key) => {
    tab = key;
    nav.replaceChildren(...tabs.map(([k, label]) => h("button", { class: `tab ${k === tab ? "on" : ""}`, onclick: () => show(k) }, label)));
    body.replaceChildren(...pages[key]());
    body.scrollTop = 0;
  };
  let close = null;
  const modal = h(
    "div",
    { class: "modal rules" },
    h("div", { class: "rules-head" }, h("h2", {}, "How to play Marble Sumo"), h("button", { class: "icon-btn", title: "Close", onclick: () => close() }, "✕")),
    nav,
    body,
  );
  show(tab);
  close = openDialog(modal);
}
