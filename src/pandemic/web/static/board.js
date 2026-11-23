// The world map: cities, routes, cubes, stations, pawns; zoom and pan; label placement in screen pixels.
import { CITIES, COLORS, DCOLS, DNAME, EDGES, FULL, H, HOME, ROLES, W } from "./data.js";
import { modeTargets, movingPawn } from "./rules.js";
import { S, cubeCount, cubesAt, g, myTurn, players, stations, viewSeat } from "./store.js";
import { $, $$, clamp, reduced } from "./ui.js";

let vb = { ...HOME };
let userZoomed = false;
let handlers = { city: () => {}, background: () => {}, viewChanged: () => {} };

export const viewBox = () => vb;

export function renderMapBase(h) {
  handlers = h;
  const svg = $("#map");
  const oceans = MAP.oceans
    .map(([name, x, y, small]) => `<text class="ocean" x="${x}" y="${y}" font-size="${small ? 9 : 13}" letter-spacing="${small ? 1 : 4}">${name}</text>`)
    .join("");
  const ocean = getComputedStyle(document.documentElement).getPropertyValue("--ocean").trim();
  svg.innerHTML = `
    <defs><clipPath id="mapclip"><rect x="${FULL.x}" width="${FULL.w}" height="${H}"/></clipPath></defs>
    <g id="base">
      <path d="${MAP.land}" fill="#20365a" fill-rule="evenodd" stroke="#4b6d9d" stroke-width=".8" vector-effect="non-scaling-stroke" stroke-linejoin="round"/>
      <path d="${MAP.lakes}" fill="${ocean}" stroke="#4b6d9d" stroke-width=".6" vector-effect="non-scaling-stroke"/>
      <path d="${MAP.borders}" fill="none" stroke="rgba(160,195,245,.16)" stroke-width=".6" vector-effect="non-scaling-stroke"/>
      ${oceans}
    </g>
    <g id="edges" clip-path="url(#mapclip)"></g><g id="fxl"></g><g id="cities"></g><g id="pawns"></g>`;
  bindMap();
  vb = homeVB();
  userZoomed = false;
  setVB();
}

function scaleK() {
  const b = $("#map").getBoundingClientRect();
  return Math.min(b.width / vb.w, b.height / vb.h) || 1;
}
function boardAR() {
  const b = $("#board").getBoundingClientRect();
  return b.width / Math.max(1, b.height);
}
function containVB(r) {
  const ar = boardAR();
  if (ar > r.w / r.h) {
    const w = r.h * ar;
    return { x: r.x - (w - r.w) / 2, y: r.y, w, h: r.h };
  }
  const h = r.w / ar;
  return { x: r.x, y: r.y - (h - r.h) / 2, w: r.w, h };
}
// the whole map with room on the right for the map buttons, so Sydney isn't under them
function homeRect() {
  const bw = $("#board").getBoundingClientRect().width || 1000;
  return { ...HOME, w: HOME.w / Math.max(0.5, 1 - TOOLS_PX / bw) };
}
function homeVB() {
  const ar = boardAR();
  if (ar < (HOME.w / HOME.h) * 0.7) {
    // tall, narrow board: start zoomed in on your pawn; zooming out still reaches the whole map
    const at = players()[viewSeat()]?.at || "atl";
    const h = HOME.h;
    const w = h * ar;
    return { x: clamp(CITIES[at].x - w / 2, FULL.x, FULL.x + FULL.w - w), y: HOME.y, w, h };
  }
  return containVB(homeRect());
}
export function fitView() {
  vb = homeVB();
  userZoomed = false;
  setVB();
  renderMap();
}
export function refit() {
  if (!userZoomed) fitView();
  else renderMap();
}
export function showWholeMap() {
  vb = containVB(homeRect());
  userZoomed = true;
  setVB();
  handlers.viewChanged();
  renderMap();
}
function setVB() {
  $("#map")?.setAttribute("viewBox", `${vb.x} ${vb.y} ${vb.w} ${vb.h}`);
}

const riskCities = () => Object.keys(CITIES).filter((id) => Object.values(cubesAt(id)).some((v) => v >= 3));

/* label placement in screen pixels; important cities always keep a label */
function segHits([x1, y1, x2, y2], [a, b, c, d]) {
  let t0 = 0;
  let t1 = 1;
  const dx = x2 - x1;
  const dy = y2 - y1;
  const p = [-dx, dx, -dy, dy];
  const q = [x1 - a, c - x1, y1 - b, d - y1];
  for (let i = 0; i < 4; i++) {
    if (p[i] === 0) {
      if (q[i] < 0) return false;
      continue;
    }
    const t = q[i] / p[i];
    if (p[i] < 0) {
      if (t > t1) return false;
      if (t > t0) t0 = t;
    } else {
      if (t < t0) return false;
      if (t < t1) t1 = t;
    }
  }
  return true;
}

function computeLabels(u, tier) {
  const ids = Object.keys(CITIES);
  const node = {};
  const cubeB = {};
  const pieces = [];
  const pl = players();
  const st = stations();
  for (const id of ids) {
    const c = CITIES[id];
    node[id] = [c.x - 9 * u, c.y - 9 * u, c.x + 9 * u, c.y + 9 * u];
    const n = cubeCount(id);
    if (n) {
      const hw = n * 4.5 + 1;
      cubeB[id] = [c.x - hw * u, c.y - 22 * u, c.x + hw * u, c.y - 11 * u];
    }
    const np = pl.filter((p) => p.at === id).length;
    if (np) pieces.push([c.x + 7 * u, c.y - 15 * u, c.x + (10 + np * 11) * u, c.y + 7 * u]);
    if (st.includes(id)) pieces.push([c.x - 23 * u, c.y - 8 * u, c.x - 9 * u, c.y + 7 * u]);
  }
  const segs = EDGES.filter(([a, b]) => Math.abs(CITIES[a].x - CITIES[b].x) < W / 2).map(([a, b]) => [CITIES[a].x, CITIES[a].y, CITIES[b].x, CITIES[b].y]);
  const norm = 1 / (u * u * 30);
  const ov = (a, b) => {
    const w = Math.min(a[2], b[2]) - Math.max(a[0], b[0]);
    const h = Math.min(a[3], b[3]) - Math.max(a[1], b[1]);
    return w > 0 && h > 0 ? w * h * norm : 0;
  };
  const crowd = (id) => ids.filter((o) => Math.hypot(CITIES[o].x - CITIES[id].x, CITIES[o].y - CITIES[id].y) < 60 * u).length;
  const order = [...ids].sort((a, b) => tier[a] - tier[b] || crowd(b) - crowd(a));
  const placed = [];
  const out = {};
  for (const id of order) {
    const c = CITIES[id];
    const w = c.name.length * 5.9 + 4;
    const up = cubeB[id] ? -24 : -13;
    const C = (dx, dy, a, box, pen) => ({ x: c.x + dx * u, y: c.y + dy * u, a, pen, box: [c.x + box[0] * u, c.y + box[1] * u, c.x + box[2] * u, c.y + box[3] * u] });
    const cands = [
      C(0, 22, "middle", [-w / 2, 12, w / 2, 25], 0),
      C(12, 4.5, "start", [11, -5, 12 + w, 7], 0.6),
      C(-12, 4.5, "end", [-12 - w, -5, -11, 7], 0.6),
      C(8, 21, "start", [6, 12, 8 + w, 25], 0.9),
      C(-8, 21, "end", [-8 - w, 12, -6, 25], 0.9),
      C(0, up, "middle", [-w / 2, up - 11, w / 2, up + 2], 1.1),
    ];
    let best = null;
    for (const cd of cands) {
      const B = cd.box;
      let s = cd.pen;
      if (B[0] < FULL.x || B[2] > FULL.x + FULL.w || B[1] < 0 || B[3] > H) s += 50;
      for (const o of ids) {
        if (o === id) continue;
        s += 10 * ov(B, node[o]);
        if (cubeB[o]) s += 3 * ov(B, cubeB[o]);
      }
      if (cubeB[id]) s += 4 * ov(B, cubeB[id]);
      for (const pb of placed) s += 12 * ov(B, pb);
      for (const pc of pieces) s += 6 * ov(B, pc);
      for (const sg of segs) if (segHits(sg, B)) s += 0.8;
      if (!best || s < best.s) best = { ...cd, s };
    }
    const off = tier[id] > 0 && best.s > 8;
    if (!off) placed.push(best.box);
    out[id] = { ...best, off };
  }
  return out;
}

function labelTiers(targets) {
  const t = {};
  const viewer = players()[viewSeat()];
  const hand = new Set(viewer?.hand || []);
  const risk = new Set(riskCities());
  const focus = new Set(S.ui.fx.focus || []);
  const st = stations();
  const at = new Set(players().map((p) => p.at));
  for (const id in CITIES) {
    t[id] = 3;
    if (cubeCount(id)) t[id] = 2;
    if (risk.has(id) || st.includes(id) || hand.has(id)) t[id] = 1;
    if (at.has(id) || targets.has(id) || focus.has(id)) t[id] = 0;
  }
  return t;
}

let mapRaf = 0;
export function queueMap() {
  cancelAnimationFrame(mapRaf);
  mapRaf = requestAnimationFrame(renderMap);
}

// The city ringed as "yours": the pawn you are about to move, or the viewer's pawn.
function ringCity() {
  const pl = players();
  if (S.ui.mode === "airlift") return pl[S.ui.airlift ?? viewSeat()]?.at;
  if (myTurn()) return pl[movingPawn()]?.at;
  return pl[viewSeat()]?.at;
}

export function renderMap() {
  if (!$("#map") || !g()) return;
  const focusedId = document.activeElement?.closest?.(".city")?.dataset.id;
  const u = 1 / scaleK();
  const ring = ringCity();
  const targets = new Set(modeTargets());
  const fx = S.ui.fx;
  const focusSet = new Set(fx.focus || []);
  const mode = S.ui.mode;
  const st = stations();
  const pl = players();

  let edges = "";
  let wrapLabels = "";
  for (const [a, b] of EDGES) {
    const A = CITIES[a];
    const B = CITIES[b];
    const on = mode === "drive" && ((a === ring && targets.has(b)) || (b === ring && targets.has(a)));
    const wrap = Math.abs(A.x - B.x) > W / 2;
    const [L, R] = A.x < B.x ? [A, B] : [B, A];
    const segs = wrap ? [[L.x, L.y, R.x - W, R.y], [R.x, R.y, L.x + W, L.y]] : [[A.x, A.y, B.x, B.y]];
    for (const [x1, y1, x2, y2] of segs) {
      edges += `<line x1="${x1}" y1="${y1}" x2="${x2}" y2="${y2}" stroke="${on ? "var(--you)" : "rgba(225,235,255,.5)"}" stroke-width="${(on ? 2.6 : 1.4) * u}" ${wrap ? `stroke-dasharray="${6 * u} ${4 * u}"` : ""} stroke-linecap="round"/>`;
    }
    if (wrap) {
      // the left end leaves the map towards the Pacific: name the city it leads to
      const edge = FULL.x + 4 * u;
      const gx = R.x - W;
      const t = gx >= edge ? 1 : (L.x - edge) / (L.x - gx);
      const ey = L.y + (R.y - L.y) * t;
      wrapLabels += `<text class="wrap-label ${on ? "on" : ""}" x="${edge}" y="${ey - 5 * u}" font-size="${11 * u}" stroke-width="${3 * u}">‹ ${R.name}</text>`;
    }
  }
  $("#edges").innerHTML = edges + wrapLabels;

  let fxl = "";
  for (const [a, b] of fx.lines || []) {
    const A = CITIES[a];
    const B = CITIES[b];
    if (Math.abs(A.x - B.x) > W / 2) continue;
    fxl += `<line x1="${A.x}" y1="${A.y}" x2="${B.x}" y2="${B.y}" stroke="var(--alert)" stroke-width="${3 * u}" stroke-linecap="round" opacity=".9"/>`;
  }
  $("#fxl").innerHTML = fxl;

  const L = computeLabels(u, labelTiers(targets));
  const now = performance.now();
  const fAge = now - (fx.flashAt || 0);
  const flash = fAge < 2400 ? fx.flash || [] : [];
  fx.ghost = (fx.ghost || []).filter((gh) => now - gh.at < 800);
  const ghost = fx.ghost;
  const newSt = fx.newStation && now - fx.newStation.at < 500 ? fx.newStation.id : null;
  const rovId = focusedId || ring;
  let nodes = "";
  for (const id in CITIES) {
    const c = CITIES[id];
    const m = cubesAt(id);
    const isT = targets.has(id);
    const dim = mode && !isT && id !== ring;
    const list = [];
    for (const col of DCOLS) for (let i = 0; i < (m[col] || 0); i++) list.push(col);
    const cw = 7;
    const gap = 2;
    const tot = list.length * cw + (list.length - 1) * gap;
    const cubeRect = (col, x, cls = "", style = "") =>
      `<rect class="${cls}" style="${style}" x="${x}" y="${c.y - 20 * u}" width="${cw * u}" height="${cw * u}" rx="${1.4 * u}" fill="${COLORS[col]}" stroke="${col === "black" ? "#c2cad8" : "rgba(0,0,0,.55)"}" stroke-width="${u}"/>`;
    const cubes = list.map((col, i) => cubeRect(col, c.x + (-tot / 2 + i * (cw + gap)) * u)).join("");
    const ghosts = ghost
      .filter((gh) => gh.id === id)
      .flatMap((gh) =>
        Array.from({ length: gh.n }, (_, i) => {
          const gx = c.x + (-(gh.n * cw + (gh.n - 1) * gap) / 2 + i * (cw + gap)) * u;
          return cubeRect(gh.col, gx, "ghost", `animation-delay:${i * 60 - (now - gh.at)}ms`);
        }),
      )
      .join("");
    const danger = Object.values(m).some((v) => v >= 3)
      ? `<circle cx="${c.x}" cy="${c.y}" r="${12.5 * u}" fill="none" stroke="#fff" stroke-width="${1.6 * u}" stroke-dasharray="${3 * u} ${2.6 * u}"/>`
      : "";
    const stn = st.includes(id) ? `<use href="#station" ${newSt === id ? `class="pop-in" style="animation-delay:${fx.newStation.at - now}ms"` : ""} transform="translate(${c.x - 16 * u} ${c.y - 0.5 * u}) scale(${u})"/>` : "";
    const fl = flash.includes(id)
      ? `<circle class="flash ${fx.flashKind || ""}" style="animation-delay:${flash.indexOf(id) * 180 - fAge}ms" cx="${c.x}" cy="${c.y}" r="${12 * u}" stroke-width="${3 * u}"/>`
      : "";
    const youRing = id === ring ? `<circle cx="${c.x}" cy="${c.y}" r="${11 * u}" fill="none" stroke="var(--you)" stroke-width="${2.4 * u}"/>` : "";
    const lab = L[id];
    const desc = [
      `${DNAME[c.color]} city`,
      ...Object.entries(m)
        .filter(([, v]) => v)
        .map(([k, v]) => `${v} ${k} cube${v > 1 ? "s" : ""}`),
      st.includes(id) ? "research station" : "",
      ...pl.filter((p) => p.at === id).map((p) => p.name.replace(/"/g, "")),
    ]
      .filter(Boolean)
      .join(", ");
    nodes += `<g class="city ${isT ? "target" : ""} ${dim ? "dim" : ""} ${focusSet.has(id) ? "focus" : ""}" data-id="${id}" tabindex="${id === rovId ? 0 : -1}" role="button" aria-label="${c.name}: ${desc.replace(/[<>&]/g, "")}">
      <circle cx="${c.x}" cy="${c.y}" r="${15 * u}" fill="transparent"/>
      <circle class="halo" cx="${c.x}" cy="${c.y}" r="${15 * u}" fill="rgba(47,214,181,.2)" stroke="var(--you)" stroke-width="${2 * u}"/>
      <circle class="fx-ring" cx="${c.x}" cy="${c.y}" r="${15 * u}" fill="rgba(255,92,122,.16)" stroke="var(--alert)" stroke-width="${2.4 * u}"/>
      <circle class="fring" cx="${c.x}" cy="${c.y}" r="${18 * u}" fill="none" stroke="#fff" stroke-width="${2 * u}"/>
      ${danger}${youRing}
      <circle class="node" cx="${c.x}" cy="${c.y}" r="${7 * u}" fill="${COLORS[c.color]}" stroke="${c.color === "black" ? "#c2cad8" : "#08111f"}" stroke-width="${1.5 * u}"/>
      ${stn}${cubes}${ghosts}${fl}
      <text class="label ${lab.off ? "off" : ""}" x="${lab.x}" y="${lab.y}" text-anchor="${lab.a}" font-size="${12 * u}" stroke-width="${3 * u}">${c.name}</text>
    </g>`;
  }
  $("#cities").innerHTML = nodes;

  const byCity = {};
  for (const p of pl) (byCity[p.at] ||= []).push(p.i);
  const cur = g().current;
  const moving = myTurn() ? movingPawn() : null;
  let pawns = "";
  for (const id in byCity) {
    byCity[id].forEach((i, j) => {
      const c = CITIES[id];
      const big = i === cur;
      const sel = moving != null && moving !== cur && i === moving;
      pawns += `<g class="pawn ${sel ? "sel" : ""}" id="pawn-${i}"><use href="#pawn" transform="translate(${c.x + (13 + j * 11) * u} ${c.y + 5 * u}) scale(${(big || sel ? 1.25 : 1) * u})" fill="${ROLES[pl[i].role].color}" stroke="${sel ? "#fff" : "#08111f"}" stroke-width="1.2"/></g>`;
    });
  }
  $("#pawns").innerHTML = pawns;

  if (focusedId) $(`#map .city[data-id="${focusedId}"]`)?.focus({ preventScroll: true });
}

export function highlightCity(id, on) {
  $(`#map .city[data-id="${id}"]`)?.classList.toggle("hl", on);
}

export function animatePawn(i, ids) {
  if (reduced() || ids.length < 2) return;
  const el = document.getElementById(`pawn-${i}`);
  if (!el) return;
  const end = CITIES[ids[ids.length - 1]];
  const step = (id) => {
    let x = CITIES[id].x - end.x;
    if (Math.abs(x) > W / 2) x -= Math.sign(x) * W; // across the Pacific: slide off the near edge
    return `translate(${x}px, ${CITIES[id].y - end.y}px)`;
  };
  el.animate(
    ids.map((id) => ({ transform: step(id) })),
    { duration: 260 * (ids.length - 1) + 140, easing: "ease-in-out" },
  );
}

/* zoom & pan */
export function zoom(f, cx = vb.x + vb.w / 2, cy = vb.y + vb.h / 2) {
  const ar = vb.w / vb.h;
  const nw = clamp(vb.w * f, W / 5, Math.max(homeRect().w, FULL.h * ar));
  const nh = nw / ar;
  vb.x = cx - (cx - vb.x) * (nw / vb.w);
  vb.y = cy - (cy - vb.y) * (nh / vb.h);
  vb.w = nw;
  vb.h = nh;
  clampVB();
  userZoomed = true;
  setVB();
  handlers.viewChanged();
  queueMap();
}
const TOOLS_PX = 56; // the map buttons along the right edge
const HINT_PX = 90; // the mode hint along the bottom edge (three lines on a phone)
function clampVB() {
  const span = (lo, len, size, extra = 0) => [Math.min(lo, lo + len - size), Math.max(lo, lo + len - size) + extra];
  const [x0, x1] = span(FULL.x, FULL.w, vb.w, TOOLS_PX / scaleK()); // the right edge can slide out from under the buttons
  const [y0, y1] = span(FULL.y, FULL.h, vb.h, HINT_PX / scaleK()); // and the bottom edge from under the mode hint
  vb.x = clamp(vb.x, x0, x1);
  vb.y = clamp(vb.y, y0, y1);
}
// whether a city's dot is hidden under a button floating on the map
function underButton(c) {
  const svg = $("#map");
  const pt = svg.createSVGPoint();
  pt.x = c.x;
  pt.y = c.y;
  const p = pt.matrixTransform(svg.getScreenCTM());
  return $$(".map-tools button, #mode-hint button, #feed button").some((b) => {
    const r = b.getBoundingClientRect();
    return r.width && p.x > r.left - 12 && p.x < r.right + 12 && p.y > r.top - 12 && p.y < r.bottom + 12;
  });
}
export function ensureVisible(id) {
  const c = CITIES[id];
  const m = vb.w * 0.08;
  if (c.x < vb.x + m || c.x > vb.x + vb.w - m || c.y < vb.y + m || c.y > vb.y + vb.h - m || underButton(c)) {
    vb.x = c.x - vb.w / 2;
    vb.y = c.y - vb.h / 2;
    clampVB();
    setVB();
    renderMap();
  }
}

let drag = null;
let pinch = null;
const pointers = new Map();
let suppressClick = false; // the click that ends a drag or pinch is not a tap; the next pointerdown clears it
let windowBound = false;

function toSvg(x, y) {
  const svg = $("#map");
  const pt = svg.createSVGPoint();
  pt.x = x;
  pt.y = y;
  return pt.matrixTransform(svg.getScreenCTM().inverse());
}

// The city closest to a screen point, if within `px` screen pixels.
function nearestCity(x, y, px) {
  const p = toSvg(x, y);
  let best = null;
  let bestD = px / scaleK();
  for (const id in CITIES) {
    const d = Math.hypot(CITIES[id].x - p.x, CITIES[id].y - p.y);
    if (d < bestD) {
      best = id;
      bestD = d;
    }
  }
  return best;
}

function spread() {
  const [a, b] = [...pointers.values()];
  return { d: Math.hypot(a.x - b.x, a.y - b.y), x: (a.x + b.x) / 2, y: (a.y + b.y) / 2 };
}

function endGesture(e) {
  pointers.delete(e.pointerId);
  if (drag?.moved || pinch) {
    suppressClick = true;
    queueMap();
  }
  if (pointers.size < 2) pinch = null;
  drag = null; // a finger left over from a pinch doesn't start dragging
  $("#map")?.classList.remove("dragging");
}

function bindMap() {
  const svg = $("#map");
  $("#zin").onclick = () => zoom(0.75);
  $("#zout").onclick = () => zoom(1 / 0.75);
  $("#zfit").onclick = () => showWholeMap();
  svg.addEventListener(
    "wheel",
    (e) => {
      e.preventDefault();
      const sp = toSvg(e.clientX, e.clientY);
      zoom(e.deltaY > 0 ? 1.12 : 0.89, sp.x, sp.y);
    },
    { passive: false },
  );
  svg.addEventListener("pointerdown", (e) => {
    suppressClick = false;
    pointers.set(e.pointerId, { x: e.clientX, y: e.clientY });
    if (pointers.size === 2) {
      drag = null;
      pinch = spread();
    } else if (pointers.size === 1) {
      drag = { x: e.clientX, y: e.clientY, vx: vb.x, vy: vb.y, moved: false };
    }
  });
  if (!windowBound) {
    windowBound = true;
    addEventListener("pointermove", (e) => {
      if (!$("#map")) return;
      if (pointers.has(e.pointerId)) pointers.set(e.pointerId, { x: e.clientX, y: e.clientY });
      if (pinch && pointers.size >= 2) {
        const now = spread();
        if (now.d > 0 && pinch.d > 0) {
          const sp = toSvg(now.x, now.y);
          zoom(pinch.d / now.d, sp.x, sp.y);
        }
        pinch = now;
        return;
      }
      if (!drag) return;
      const dx = e.clientX - drag.x;
      const dy = e.clientY - drag.y;
      if (Math.abs(dx) + Math.abs(dy) > 5) {
        drag.moved = true;
        $("#map").classList.add("dragging");
      }
      if (!drag.moved) return;
      const s = 1 / scaleK();
      vb.x = drag.vx - dx * s;
      vb.y = drag.vy - dy * s;
      clampVB();
      userZoomed = true;
      setVB();
      handlers.viewChanged();
    });
    addEventListener("pointerup", endGesture);
    addEventListener("pointercancel", endGesture);
  }
  svg.addEventListener("click", (e) => {
    if (suppressClick) {
      suppressClick = false;
      return;
    }
    const el = e.target.closest(".city");
    if (el) return handlers.city(el.dataset.id, false);
    const near = nearestCity(e.clientX, e.clientY, 22);
    if (near) handlers.city(near, false);
    else handlers.background();
  });
  svg.addEventListener("focusin", (e) => {
    const el = e.target.closest(".city");
    if (!el) return;
    for (const x of $$('#map .city[tabindex="0"]')) if (x !== el) x.setAttribute("tabindex", "-1");
    el.setAttribute("tabindex", "0");
  });
  svg.addEventListener("keydown", (e) => {
    const el = e.target.closest(".city");
    if (!el) return;
    const id = el.dataset.id;
    if (e.key === "Enter" || e.key === " ") {
      e.preventDefault();
      handlers.city(id, true);
      return;
    }
    const d = { ArrowRight: [1, 0], ArrowLeft: [-1, 0], ArrowUp: [0, -1], ArrowDown: [0, 1] }[e.key];
    if (!d) return;
    e.preventDefault();
    const c = CITIES[id];
    let best = null;
    for (const o in CITIES) {
      if (o === id) continue;
      const dx = CITIES[o].x - c.x;
      const dy = CITIES[o].y - c.y;
      const along = dx * d[0] + dy * d[1];
      if (along <= 0) continue;
      const s = along + Math.abs(dx * d[1] - dy * d[0]) * 2.5;
      if (!best || s < best.s) best = { o, s };
    }
    if (best) {
      ensureVisible(best.o);
      $(`#map .city[data-id="${best.o}"]`)?.focus();
    }
  });
  $("#legend-btn").onclick = (e) => {
    e.stopPropagation();
    const lg = $("#legend");
    lg.classList.toggle("hidden");
    $("#legend-btn").setAttribute("aria-expanded", String(!lg.classList.contains("hidden")));
  };
  $("#legend").innerHTML = legendHtml();
}

export function legendHtml() {
  const sw = (inner, vbx = "-12 -12 24 24") => `<svg width="22" height="22" viewBox="${vbx}" aria-hidden="true">${inner}</svg>`;
  return `
    <span>${sw(`<circle r="7" fill="${COLORS.red}" stroke="#08111f" stroke-width="1.5"/>`)}City, coloured by its disease</span>
    <span>${sw(`<rect x="-8" y="-4" width="7" height="7" rx="1.4" fill="${COLORS.black}" stroke="#c2cad8"/><rect x="1" y="-4" width="7" height="7" rx="1.4" fill="${COLORS.black}" stroke="#c2cad8"/>`)}Disease cubes</span>
    <span>${sw(`<circle r="9" fill="none" stroke="#fff" stroke-width="1.6" stroke-dasharray="3 2.6"/><circle r="6" fill="${COLORS.yellow}"/>`)}3 cubes: the next one causes an outbreak</span>
    <span>${sw(`<circle r="9" fill="none" stroke="#2fd6b5" stroke-width="2.4"/><circle r="6" fill="${COLORS.black}" stroke="#c2cad8"/>`)}Your location</span>
    <span>${sw('<use href="#station"/>', "-9 -9 18 18")}Research station</span>
    <span>${sw(`<use href="#pawn" fill="${ROLES.medic.color}" stroke="#08111f"/>`, "-8 -14 16 20")}Player pawn (role colour)</span>
    <span>${sw(`<line x1="-10" y1="0" x2="10" y2="0" stroke="rgba(225,235,255,.6)" stroke-width="1.5" stroke-dasharray="4 3"/>`)}Route that wraps around the map</span>`;
}
