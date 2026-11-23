// The board: a loop of 14 spaces around the neighbourhood, two spy meeples and the table in the middle.
// Space 0 is the green home; spaces count clockwise. The board is turned so the viewer's home is at the bottom.
import { ICONS, STREET, meepleSvg } from "./art.js";
import { h } from "/static/shared/dom.js";

export const TRACK = 14;
const HOMES = [0, 7];
const MARKET = [2, 5, 9, 12];
// (column, row) of each space on a 5 × 4 ring, green home at the bottom middle, going clockwise (left first).
const CELLS = [
  [2, 3], [1, 3], [0, 3], [0, 2], [0, 1], [0, 0], [1, 0], [2, 0], [3, 0], [4, 0], [4, 1], [4, 2], [4, 3], [3, 3],
];
const COLS = 5;
const ROWS = 4;

const html = (markup) => {
  const t = document.createElement("template");
  t.innerHTML = markup.trim();
  return t.content.firstChild;
};

export class Board {
  constructor() {
    this.flip = false;
    this.advanced = false;
    this.squares = [null, null];
    this.cells = [];
    this.el = h("div", { class: "board" });
    this.el.innerHTML = STREET;
    this.ring = h("div", { class: "ring" });
    this.center = h("div", { class: "table-center" });
    this.meeples = [0, 1].map((team) => {
      const m = h("div", { class: `meeple t${team}`, "data-team": team }, h("div", { class: "meeple-body" }));
      m.firstChild.innerHTML = meepleSvg(team);
      return m;
    });
    for (let sq = 0; sq < TRACK; sq++) {
      const cell = h("div", { class: "cell", "data-sq": sq });
      this.cells.push(cell);
      this.ring.append(cell);
    }
    this.el.append(this.ring, this.center, ...this.meeples);
    this.layout();
  }

  setView(viewerTeam, advanced) {
    const flip = viewerTeam === 1;
    if (flip === this.flip && advanced === this.advanced) return;
    this.flip = flip;
    this.advanced = advanced;
    this.layout();
    for (let side = 0; side < 2; side++) if (this.squares[side] != null) this.place(side, this.squares[side], true);
  }

  // Centre of a space in % of the board.
  spot(sq) {
    let [c, r] = CELLS[((sq % TRACK) + TRACK) % TRACK];
    if (this.flip) [c, r] = [COLS - 1 - c, ROWS - 1 - r];
    return [((c + 0.5) / COLS) * 100, ((r + 0.5) / ROWS) * 100];
  }

  layout() {
    this.cells.forEach((cell, sq) => {
      let [c, r] = CELLS[sq];
      if (this.flip) [c, r] = [COLS - 1 - c, ROWS - 1 - r];
      Object.assign(cell.style, { left: `${(c / COLS) * 100}%`, top: `${(r / ROWS) * 100}%`, width: `${100 / COLS}%`, height: `${100 / ROWS}%` });
      // the arrow points to the next space (clockwise)
      const [x1, y1] = this.spot(sq);
      const [x2, y2] = this.spot(sq + 1);
      const angle = (Math.atan2((y2 - y1) * ROWS, (x2 - x1) * COLS) * 180) / Math.PI;
      const home = HOMES.indexOf(sq);
      const market = this.advanced && MARKET.includes(sq);
      cell.className = `cell${home >= 0 ? ` home t${home}` : ""}${market ? " bm" : ""}${MARKET.includes(sq) ? " corner" : ""}`;
      cell.replaceChildren(
        h(
          "div",
          { class: "tile" },
          home >= 0 ? html(`<span class="tile-icon">${ICONS.house}</span>`) : market ? html(`<span class="tile-icon">${ICONS.cart}</span>`) : null,
          h("span", { class: "chev", style: { transform: `rotate(${angle}deg)` } }, html(ICONS.arrow)),
        ),
      );
    });
  }

  // Where the two meeples sit; when they share a space they stand side by side.
  _xy(side, sq) {
    const [x, y] = this.spot(sq);
    const other = this.squares[1 - side];
    const shared = other != null && ((other % TRACK) + TRACK) % TRACK === ((sq % TRACK) + TRACK) % TRACK;
    return [shared ? x + (side === 0 ? -3.2 : 3.2) : x, y];
  }

  place(side, pos, quiet = false) {
    this.squares[side] = pos;
    for (const s of [0, 1]) {
      if (this.squares[s] == null) continue;
      const [x, y] = this._xy(s, this.squares[s]);
      const m = this.meeples[s];
      if (m.dataset.at === `${x},${y}`) continue;
      m.dataset.at = `${x},${y}`;
      if (quiet || s === side || !m.dataset.placed) {
        m.style.left = `${x}%`;
        m.style.top = `${y}%`;
      } else {
        m.animate([{ left: m.style.left, top: m.style.top }, { left: `${x}%`, top: `${y}%` }], { duration: 220, easing: "ease-out" });
        m.style.left = `${x}%`;
        m.style.top = `${y}%`;
      }
      m.dataset.placed = "1";
    }
  }

  // Hop a meeple space by space from absolute position `from` to `to`. Resolves when it has landed.
  hop(side, from, to, { hopMs = 200, onStep } = {}) {
    const m = this.meeples[side];
    const steps = Math.abs(to - from);
    if (!steps) {
      const body = m.firstChild;
      body.animate([{ transform: "scale(1)" }, { transform: "scale(1.12, .9)" }, { transform: "scale(1)" }], { duration: 260 });
      return Promise.resolve();
    }
    const dir = Math.sign(to - from);
    this.squares[side] = from;
    const points = [];
    for (let i = 0; i <= steps; i++) points.push(this.spot(from + dir * i));
    this.squares[side] = to;
    const last = this._xy(side, to);
    points[points.length - 1] = last;
    const dur = steps * hopMs + 120;
    const frames = points.map(([x, y], i) => ({ left: `${x}%`, top: `${y}%`, offset: (i * hopMs) / dur }));
    frames[frames.length - 1].offset = (steps * hopMs) / dur;
    frames.push({ left: `${last[0]}%`, top: `${last[1]}%`, offset: 1 });
    const body = m.firstChild;
    const arcs = [];
    for (let i = 0; i < steps; i++) {
      arcs.push({ transform: "translateY(0) scale(1)", offset: (i * hopMs) / dur });
      arcs.push({ transform: "translateY(-38%) scale(1.04)", offset: ((i + 0.5) * hopMs) / dur });
    }
    arcs.push({ transform: "translateY(0) scale(1.12, .88)", offset: (steps * hopMs) / dur });
    arcs.push({ transform: "translateY(0) scale(1)", offset: 1 });
    m.classList.add("moving");
    const a1 = m.animate(frames, { duration: dur, easing: "linear" });
    body.animate(arcs, { duration: dur, easing: "ease-in-out" });
    if (onStep) for (let i = 1; i <= steps; i++) setTimeout(() => onStep(i), i * hopMs - 40);
    m.style.left = `${last[0]}%`;
    m.style.top = `${last[1]}%`;
    m.dataset.at = `${last[0]},${last[1]}`;
    return a1.finished.then(
      () => {
        m.classList.remove("moving");
        this.place(side, to);
      },
      () => m.classList.remove("moving"),
    );
  }

  glow(sq, cls = "flash") {
    const cell = this.cells[((sq % TRACK) + TRACK) % TRACK];
    cell.classList.remove(cls);
    void cell.offsetWidth;
    cell.classList.add(cls);
    setTimeout(() => cell.classList.remove(cls), 1400);
  }
}
