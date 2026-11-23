// The hex map: flat-topped hexes in doubled coordinates (col, row; col + row even), castle at the bottom.
import { heroStandee, monsterToken } from "./art.js";
import { s } from "./dom.js";

export const R = 50;
const SQ3 = Math.sqrt(3);
const hexPoints = (r) =>
  Array.from({ length: 6 }, (_, i) => {
    const a = (Math.PI / 3) * i;
    return `${(r * Math.cos(a)).toFixed(2)},${(r * Math.sin(a)).toFixed(2)}`;
  }).join(" ");
const HEX_POINTS = hexPoints(R);
const RIM_POINTS = hexPoints(R - 1.6);
const TARGET_POINTS = hexPoints(R - 3.2);
const MAP_VARIANTS = 4;

export const key = (hex) => `${hex[0]},${hex[1]}`;
export const center = (hex) => [hex[0] * 1.5 * R, (-hex[1] * SQ3 * R) / 2];

const LAIR_SPOTS = { 1: [[0, -11]], 2: [[-18, -9], [18, -9]] };
const FREE_SPOTS = [[0, -11], [-20, -8], [20, -8], [-28, 8], [28, 8], [0, 4], [-11, -20], [11, -20]];
const HERO_Y = 25;
const PLINTH_DEPTH = 36;
const WALL_SPOTS = [[-27, 49, -18], [0, 57, 0], [27, 49, 18]];

function monsterSpots(tile, monsters) {
  // Monsters on lairs sit on their lair; the rest fill free spots away from the lairs.
  const lairs = tile?.key ? LAIR_SPOTS[tile.lairs?.length || 0] || [] : [];
  const used = [];
  const out = new Map();
  for (const m of monsters) {
    if (m.lair !== null && m.lair !== undefined && lairs[m.lair]) {
      out.set(m.id, lairs[m.lair]);
      used.push(lairs[m.lair]);
    }
  }
  const free = FREE_SPOTS.filter(([x, y]) => !lairs.some(([lx, ly]) => Math.hypot(lx - x, ly - y) < 16));
  for (const m of monsters) {
    if (out.has(m.id)) continue;
    const spot = free.find(([x, y]) => !used.some(([ux, uy]) => Math.hypot(ux - x, uy - y) < 22)) || [0, 0];
    used.push(spot);
    out.set(m.id, spot);
  }
  return out;
}

const variantOf = (hex) => Math.abs(hex[0] * 7 + hex[1] * 13) % MAP_VARIANTS;

export class Board {
  constructor(handlers = {}) {
    this.handlers = handlers;
    this.el = s("svg", { class: "board", preserveAspectRatio: "xMidYMid meet", role: "img", "aria-label": "Map of Avel" });
    this.shadowLayer = s("g", { class: "tile-shadows" });
    this.tilesLayer = s("g", { class: "tiles" });
    this.markLayer = s("g", { class: "marks" });
    this.tokenLayer = s("g", { class: "tokens" });
    this.labelLayer = s("g", { class: "labels", "pointer-events": "none" });
    this.el.append(this.shadowLayer, this.tilesLayer, this.markLayer, this.tokenLayer, this.labelLayer);
    this.tokens = new Map(); // id -> <g>
    this.box = null;
  }

  fit(tiles) {
    let x0 = Infinity;
    let y0 = Infinity;
    let x1 = -Infinity;
    let y1 = -Infinity;
    for (const t of tiles) {
      const [x, y] = center(t.hex);
      x0 = Math.min(x0, x - R);
      x1 = Math.max(x1, x + R);
      y0 = Math.min(y0, y - (R * SQ3) / 2);
      y1 = Math.max(y1, y + (R * SQ3) / 2 + (t.key === "castle" ? PLINTH_DEPTH : 0));
    }
    const pad = 6;
    const box = `${x0 - pad} ${y0 - pad} ${x1 - x0 + 2 * pad} ${y1 - y0 + 2 * pad}`;
    if (box !== this.box) {
      this.el.setAttribute("viewBox", box);
      this.box = box;
    }
  }

  // ui: { targets: Map(hexKey -> {kind, label}), monsters: Set(ids), lairs: Set("c,r,i"), current, me, focus }
  update(game, cat, ui = {}) {
    this.fit(game.tiles);
    const tilesByKey = new Map(game.tiles.map((t) => [key(t.hex), t]));
    const monstersAt = new Map();
    for (const m of game.monsters) {
      const k = key(m.hex);
      if (!monstersAt.has(k)) monstersAt.set(k, []);
      monstersAt.get(k).push(m);
    }
    const heroesAt = new Map();
    for (const hero of game.heroes) {
      const k = key(hero.hex);
      if (!heroesAt.has(k)) heroesAt.set(k, []);
      heroesAt.get(k).push(hero);
    }
    const targets = ui.targets || new Map();

    // tiles (cheap to rebuild: the art lives in the sprite)
    this.shadowLayer.replaceChildren();
    this.tilesLayer.replaceChildren();
    this.markLayer.replaceChildren();
    this.labelLayer.replaceChildren();
    for (const t of game.tiles) {
      const [cx, cy] = center(t.hex);
      const info = t.key ? cat.tiles[t.key] : null;
      const k = key(t.hex);
      const target = targets.get(k);
      const faceUp = t.face_up && info;
      if (info?.castle) this.shadowLayer.append(plinth(cx, cy, game.walls));
      this.shadowLayer.append(s("polygon", { points: HEX_POINTS, class: "tile-depth", transform: `translate(${cx} ${cy + 3.2})` }));
      const g = s("g", {
        class: `tile${faceUp ? "" : " face-down"}${target ? ` target target-${target.kind}` : ""}${ui.focus === k ? " focus" : ""}`,
        transform: `translate(${cx} ${cy})`,
        "data-hex": k,
        onclick: (e) => {
          e.stopPropagation();
          this.handlers.onHex?.(t.hex, target);
        },
      });
      g.append(
        s("polygon", { points: HEX_POINTS, class: "hex-bg" }),
        s("use", { href: faceUp ? `#t-${t.key}` : `#t-map-${variantOf(t.hex)}`, x: -R, y: (-R * SQ3) / 2, width: 2 * R, height: R * SQ3, class: "tile-art" }),
        s("polygon", { points: RIM_POINTS, class: "hex-rim" }),
        s("polygon", { points: HEX_POINTS, class: "hex-edge" }),
      );
      if (faceUp) {
        if (info.shortcut) g.append(s("use", { href: "#ic-shortcut", x: 30, y: -12, width: 13, height: 13, class: "tile-shortcut" }));
        const spots = LAIR_SPOTS[info.lairs.length] || [];
        info.lairs.forEach((size, i) => {
          const [lx, ly] = spots[i];
          const lk = `${k},${i}`;
          const pickable = ui.lairs?.has(lk);
          const sealed = t.seals[i];
          const r = size === "big" ? 11 : 9;
          const lair = s(
            "g",
            {
              class: `lair${pickable ? " pickable" : ""}${sealed ? " sealed" : ""}`,
              transform: `translate(${lx} ${ly})`,
              "data-lair": lk,
              onclick: pickable
                ? (e) => {
                    e.stopPropagation();
                    this.handlers.onLair?.(t.hex, i);
                  }
                : null,
            },
            pickable ? s("circle", { r: r + 4, class: "lair-pick" }) : null,
            s("circle", { r: r + 0.6, cy: 1.2, fill: "rgba(0,0,0,.4)" }),
            s("use", { href: size === "big" ? "#ic-lair_big" : "#ic-lair", x: -r, y: -r, width: 2 * r, height: 2 * r }),
          );
          if (sealed) lair.append(s("use", { href: "#ic-seal", x: -r * 0.95, y: -r * 0.95, width: r * 1.9, height: r * 1.9, class: "seal-mark" }));
          g.append(lair);
        });
      }
      if (t.crater) {
        g.append(
          s(
            "g",
            { class: "crater-mark", transform: "translate(0 4)" },
            s("circle", { r: 17, fill: "#ff6a2a", opacity: 0.25, class: "crater-glow" }),
            s("use", { href: "#ic-crater", x: -14, y: -14, width: 28, height: 28 }),
          ),
        );
      }
      if (t.trap) {
        g.append(
          s(
            "g",
            { class: "trap-mark", transform: "translate(27 12)" },
            s("circle", { r: 9.5, fill: "#cfd2d4", stroke: "#1d130c", "stroke-width": 0.9 }),
            s("use", { href: "#ic-trap", x: -7.5, y: -8, width: 15, height: 15 }),
            s("use", { href: "#ic-coin8", x: 2, y: 1.6, width: 9.6, height: 9.6 }),
            s("text", { x: 6.8, y: 6.6, class: "trap-level", "text-anchor": "middle", "dominant-baseline": "central" }, t.trap),
          ),
        );
      }
      if (target) {
        g.append(s("polygon", { points: TARGET_POINTS, class: "target-ring", "pointer-events": "none" }));
        if (target.label) {
          const w = target.label.length * 3.6 + 8;
          this.labelLayer.append(
            s(
              "g",
              { class: `target-tag target-${target.kind.split(" ")[0]}`, transform: `translate(${cx} ${cy - 24.5})` },
              s("rect", { x: -w / 2, y: -4.4, width: w, height: 8.8, rx: 4.4 }),
              s("text", { "text-anchor": "middle", "dominant-baseline": "central", y: 0.2 }, target.label),
            ),
          );
        }
      }
      const title = faceUp ? info.name : "Unexplored land";
      g.append(s("title", {}, title));
      this.tilesLayer.append(g);
    }

    // tokens (keyed so they glide)
    const alive = new Set();
    for (const [k, list] of monstersAt) {
      const tile = tilesByKey.get(k);
      const tInfo = tile?.key && tile.face_up ? cat.tiles[tile.key] : null;
      const spots = monsterSpots(tInfo ? { key: tile.key, lairs: tInfo.lairs } : null, list);
      const [cx, cy] = center(list[0].hex);
      for (const m of list) {
        const info = cat.monsters[m.key];
        const r = info.size === "beast" ? 20 : info.size === "big" ? 16 : 13.5;
        const [ox, oy] = spots.get(m.id);
        const id = `m:${m.id}`;
        alive.add(id);
        const selectable = ui.monsters?.has(m.id);
        const left = m.toughness - m.damage;
        let g = this.tokens.get(id);
        const sig = `${m.key}|${left}|${m.damage}|${selectable}`;
        if (!g) {
          g = s("g", { class: "token-wrap monster-wrap entering", "data-id": m.id });
          this.tokens.set(id, g);
          this.tokenLayer.append(g);
          requestAnimationFrame(() => requestAnimationFrame(() => g.classList.remove("entering")));
        }
        if (g.dataset.sig !== sig) {
          g.replaceChildren(monsterToken(m.key, info, r, { id: m.id, left, damage: m.damage, selectable }));
          g.append(s("title", {}, `${info.name} · ${left}/${m.toughness} toughness`));
          g.dataset.sig = sig;
        }
        g.classList.toggle("selectable", !!selectable);
        g.onclick = (e) => {
          e.stopPropagation();
          this.handlers.onMonster?.(m.id, selectable);
        };
        g.style.transform = `translate(${cx + ox}px, ${cy + oy}px)`;
      }
    }
    for (const [, list] of heroesAt) {
      const [cx, cy] = center(list[0].hex);
      const n = list.length;
      list.forEach((hero, i) => {
        const id = `h:${hero.seat}`;
        alive.add(id);
        const x = cx + (i - (n - 1) / 2) * 14;
        const y = cy + HERO_Y - (n > 2 && i % 2 ? 3 : 0);
        let g = this.tokens.get(id);
        if (!g) {
          g = s("g", { class: "token-wrap hero-wrap", "data-seat": hero.seat });
          this.tokens.set(id, g);
          this.tokenLayer.append(g);
        }
        const current = ui.current === hero.seat;
        const sig = `${hero.color}|${hero.name}|${current}|${ui.me === hero.seat}|${hero.toughness}`;
        if (g.dataset.sig !== sig) {
          g.replaceChildren(pawn(hero, current, ui.me === hero.seat));
          g.dataset.sig = sig;
        }
        g.onclick = (e) => {
          e.stopPropagation();
          this.handlers.onHero?.(hero.seat);
        };
        g.style.transform = `translate(${x}px, ${y}px)`;
      });
    }
    // heroes stand in front of monsters, lower rows in front of higher ones
    const order = [...this.tokens.values()].filter((g) => g.isConnected && !g.classList.contains("leaving"));
    order.sort((a, b) => (a.classList.contains("hero-wrap") ? 1 : 0) - (b.classList.contains("hero-wrap") ? 1 : 0));
    for (const g of order) this.tokenLayer.append(g);
    for (const [id, g] of this.tokens) {
      if (!alive.has(id)) {
        g.classList.add("leaving");
        this.tokens.delete(id);
        setTimeout(() => g.remove(), 450);
      }
    }
  }
}

function plinth(cx, cy, walls) {
  const g = s("g", { class: "plinth", transform: `translate(${cx} ${cy})` });
  const d = "M-46 18 Q-44 72 0 74 Q44 72 46 18 Z";
  g.append(
    s("path", { d, transform: "translate(0 3)", fill: "rgba(0,0,0,.45)" }),
    s("path", { d, class: "plinth-body" }),
    s("path", { d: "M-40 30 Q-38 66 0 68 Q38 66 40 30", class: "plinth-line" }),
  );
  WALL_SPOTS.forEach(([x, y, a], i) => {
    const built = i < walls;
    g.append(
      s(
        "g",
        { class: `wall-slot${built ? " built" : ""}`, transform: `translate(${x} ${y}) rotate(${a})` },
        built ? s("use", { href: "#ic-wall", x: -8, y: -8, width: 16, height: 16 }) : s("rect", { x: -7, y: -5, width: 14, height: 11, rx: 2 }),
      ),
    );
  });
  return g;
}

function pawn(hero, current, mine) {
  return s(
    "g",
    { class: `pawn${current ? " current" : ""}${mine ? " mine" : ""}` },
    current ? s("ellipse", { cx: 0, cy: -0.4, rx: 12, ry: 4.6, class: "pawn-halo" }) : null,
    heroStandee(hero.color, 29),
    s("title", {}, `${hero.name} · ${hero.toughness} toughness`),
  );
}
