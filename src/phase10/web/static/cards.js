// Card faces and backs (pure HTML + CSS, sized by --cw), group rules mirrored from phase10/game/rules.py,
// and the little card chips used in the log.
import { h } from "./dom.js";

export const COLORS = ["red", "blue", "green", "yellow"];
export const COLOR_NAMES = { red: "Red", blue: "Blue", green: "Green", yellow: "Yellow" };
// A shape per colour, so colours can be told apart without seeing them.
export const COLOR_MARK = { red: "●", blue: "◆", green: "▲", yellow: "★" };

export const isWild = (c) => c.k === "w";
export const isSkip = (c) => c.k === "s";
export const isNum = (c) => c.k === "n";
export const points = (c) => (c.k === "w" ? 25 : c.k === "s" ? 15 : c.v <= 9 ? 5 : 10);
export const cardName = (c) => (isWild(c) ? "Wild" : isSkip(c) ? "Skip" : `${COLOR_NAMES[c.c]} ${c.v}`);

function skipIcon() {
  return h("span", { class: "skip-icon" });
}

// A full card face. `as` labels what a wild stands for inside a group.
export function cardEl(c, { cls = "", as = null, attrs = {} } = {}) {
  const kind = isWild(c) ? "wild" : isSkip(c) ? "skip" : `num c-${c.c}`;
  const corner = isWild(c) ? "W" : isSkip(c) ? "S" : String(c.v);
  const mark = isNum(c) ? COLOR_MARK[c.c] : "";
  const center = isWild(c)
    ? h("span", { class: "oval" }, h("span", { class: "num" }, "W"))
    : isSkip(c)
      ? h("span", { class: "oval" }, skipIcon())
      : h("span", { class: "oval" }, h("span", { class: `num ${c.v >= 10 ? "two" : ""}` }, c.v));
  return h(
    "div",
    { class: `card ${kind} ${cls}`, "data-id": c.id, title: cardName(c), ...attrs },
    h(
      "span",
      { class: "body" },
      h("span", { class: "corner tl" }, corner, h("i", {}, mark)),
      center,
      isWild(c) || isSkip(c) ? h("span", { class: "band" }, isWild(c) ? "WILD" : "SKIP") : null,
      h("span", { class: "corner br" }, corner, h("i", {}, mark)),
    ),
    as != null && isWild(c) ? h("span", { class: "as" }, typeof as === "number" ? as : COLOR_MARK[as]) : null,
  );
}

export function backEl(cls = "") {
  return h("div", { class: `card back ${cls}` }, h("span", { class: "body" }, h("span", { class: "back-logo" }, h("b", {}, "PHASE"), h("i", {}, "10"))));
}

// Inline chip for the log: [c:red:7], [c:wild], [c:skip].
export function chip(c) {
  if (isWild(c)) return h("span", { class: "chip-card wild" }, "W");
  if (isSkip(c)) return h("span", { class: "chip-card skip" }, "S");
  return h("span", { class: `chip-card c-${c.c}` }, c.v);
}

export function richText(text) {
  const out = [];
  const re = /\[c:(wild|skip|(red|blue|green|yellow):(\d+))\]/g;
  let last = 0;
  let m;
  while ((m = re.exec(text))) {
    if (m.index > last) out.push(text.slice(last, m.index));
    if (m[1] === "wild") out.push(chip({ k: "w" }));
    else if (m[1] === "skip") out.push(chip({ k: "s" }));
    else out.push(chip({ k: "n", c: m[2], v: Number(m[3]) }));
    last = re.lastIndex;
  }
  if (last < text.length) out.push(text.slice(last));
  return out;
}

// ------------------------------------------------------------------ rules (same messages as the server)
function naturals(cards, what) {
  if (cards.some(isSkip)) throw new Error(`Skip cards can't be part of a ${what}`);
  const nat = cards.filter(isNum);
  if (!nat.length) throw new Error(`A ${what} needs at least one number card, not only wilds`);
  return nat;
}

export function setValue(cards, size) {
  if (cards.length < size) throw new Error(`A set needs at least ${size} cards, you picked ${cards.length}`);
  const values = [...new Set(naturals(cards, "set").map((c) => c.v))].sort((a, b) => a - b);
  if (values.length > 1) throw new Error(`A set is cards of the same number, but these have ${values.join(", ")}`);
  return values[0];
}

export function runLows(cards, size) {
  if (cards.length < size) throw new Error(`A run needs at least ${size} cards, you picked ${cards.length}`);
  const n = cards.length;
  if (n > 12) throw new Error("A run can't be longer than 12 cards");
  const values = naturals(cards, "run").map((c) => c.v);
  const dupes = [...new Set(values.filter((v, i) => values.indexOf(v) !== i))].sort((a, b) => a - b);
  if (dupes.length) throw new Error(`A run can't have the same number twice (${dupes.join(", ")})`);
  const lo = Math.min(...values);
  const hi = Math.max(...values);
  if (hi - lo + 1 > n) throw new Error(`From ${lo} to ${hi} there are ${hi - lo + 1 - values.length} gaps, but only ${n - values.length} wild(s) to fill them`);
  const out = [];
  for (let s = Math.max(1, hi - n + 1); s <= Math.min(lo, 12 - n + 1); s++) out.push(s);
  return out;
}

export function colorOf(cards, size) {
  if (cards.length < size) throw new Error(`You need at least ${size} cards of one color, you picked ${cards.length}`);
  const colors = new Set(naturals(cards, "color group").map((c) => c.c));
  if (colors.size > 1) throw new Error("All cards must have the same color (wilds are fine)");
  return [...colors][0];
}

export function checkGroup(kind, cards, size) {
  if (kind === "set") return { value: setValue(cards, size) };
  if (kind === "color") return { color: colorOf(cards, size) };
  return { lows: runLows(cards, size) };
}

// Where a card may go on a group: [] / ["any"] / ["low", "high"] (a copy of Group.ends_for).
export function endsFor(group, c) {
  if (isSkip(c)) return [];
  if (group.kind === "set") return isWild(c) || c.v === group.value ? ["any"] : [];
  if (group.kind === "color") return isWild(c) || c.c === group.color ? ["any"] : [];
  const ends = [];
  if (group.low > 1 && (isWild(c) || c.v === group.low - 1)) ends.push("low");
  if (group.high < 12 && (isWild(c) || c.v === group.high + 1)) ends.push("high");
  return ends;
}

export function whyNot(group, c) {
  if (isSkip(c)) return "Skip cards can't be added to groups";
  if (group.kind === "set") return `This is a set of ${group.value}s`;
  if (group.kind === "color") return `This group is all ${group.color}`;
  if (group.low === 1 && group.high === 12) return "This run is already complete from 1 to 12";
  const fits = [group.low - 1, group.high + 1].filter((v) => v >= 1 && v <= 12);
  return `This run goes ${group.low}–${group.high}; only ${fits.join(" or ")} (or a wild) fits`;
}

export function groupTitle(g) {
  if (g.kind === "set") return `Set of ${g.value}s`;
  if (g.kind === "run") return `Run ${g.low}–${g.high}`;
  return `${COLOR_NAMES[g.color]} ×${g.cards.length}`;
}

export function reqLabel(r) {
  if (r.kind === "color") return `${r.size} of one color`;
  return `${r.kind === "set" ? "Set" : "Run"} of ${r.size}`;
}

export function sortByValue(cards) {
  const rank = (c) => (isNum(c) ? c.v * 10 + COLORS.indexOf(c.c) : isWild(c) ? 1000 : 2000);
  return [...cards].sort((a, b) => rank(a) - rank(b) || a.id - b.id);
}

export function sortByColor(cards) {
  const rank = (c) => (isNum(c) ? COLORS.indexOf(c.c) * 100 + c.v : isWild(c) ? 1000 : 2000);
  return [...cards].sort((a, b) => rank(a) - rank(b) || a.id - b.id);
}
