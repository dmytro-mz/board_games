// HTML snippets shared by the board, dock, side panel and dialogs. Anything typed by a player goes through esc().
import { CITIES, COLORS, DNAME, EVENTS, H, INK, W } from "./data.js";

export const $ = (s, root = document) => root.querySelector(s);
export const $$ = (s, root = document) => [...root.querySelectorAll(s)];
export const clamp = (v, a, b) => Math.max(a, Math.min(b, v));
export const reduced = () => matchMedia("(prefers-reduced-motion: reduce)").matches;

const ESC = { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" };
export const esc = (t) => String(t ?? "").replace(/[&<>"']/g, (c) => ESC[c]);

// Replace the markup only when it changed: rebuilding the same thing resets focus, hover, scroll and animations.
export function setHtml(el, html) {
  if (el._html === html) return false;
  el._html = html;
  el.innerHTML = html;
  return true;
}

export const icon = (n, s = 18) => `<svg class="ic" width="${s}" height="${s}" aria-hidden="true"><use href="#i-${n}"/></svg>`;
export const isEv = (c) => c in EVENTS;
export const cardName = (c) => (isEv(c) ? EVENTS[c].name : CITIES[c]?.name || c);
export const cityName = (c) => CITIES[c]?.name || c;
export const plural = (n, w) => `${n} ${n === 1 ? w : w.endsWith("y") ? `${w.slice(0, -1)}ies` : `${w}s`}`;
export const listText = (arr) => (arr.length <= 1 ? arr.join("") : `${arr.slice(0, -1).join(", ")} and ${arr[arr.length - 1]}`);
export const colorCounts = (hand) => {
  const r = { blue: 0, yellow: 0, black: 0, red: 0 };
  for (const c of hand || []) if (!isEv(c) && CITIES[c]) r[CITIES[c].color]++;
  return r;
};

export function glyph(col, s = 10, onChip = false) {
  const f = onChip ? INK[col] : col === "black" ? "#1d2230" : COLORS[col];
  const st = !onChip && col === "black" ? ' stroke="#c2cad8" stroke-width="1.4"' : "";
  const shape = {
    blue: '<circle cx="5" cy="5" r="4.2"/>',
    yellow: '<path d="M5 .5 9.7 9.2H.3z"/>',
    black: '<rect x="1" y="1" width="8" height="8" rx="1"/>',
    red: '<path d="M5 .2 9.8 5 5 9.8.2 5z"/>',
  }[col];
  return `<svg class="gl" width="${s}" height="${s}" viewBox="0 0 10 10" aria-hidden="true" fill="${f}"${st}>${shape}</svg>`;
}

export function chip(c, tag = "span", extra = "") {
  if (isEv(c)) return `<${tag} class="chip event" ${extra}>${icon("event", 12)}${cardName(c)}</${tag}>`;
  const col = CITIES[c].color;
  return `<${tag} class="chip ${col}" ${extra}>${glyph(col, 9, true)}${CITIES[c].name}</${tag}>`;
}

export function ichip(id) {
  return `<button class="ichip" data-id="${id}" aria-label="Infection card ${CITIES[id].name}">${glyph(CITIES[id].color, 10)}${CITIES[id].name}</button>`;
}

export function pawnSvg(color, size = 24) {
  return `<svg width="${size}" height="${size}" viewBox="-8 -14 16 20" aria-hidden="true" class="pw"><use href="#pawn" fill="${color}" stroke="#08111f" stroke-width="1"/></svg>`;
}

export function vialSvg(col, status, size = 26) {
  const c = col === "black" ? "#9aa3b6" : COLORS[col];
  const done = status !== "none";
  const tick = done ? `<path d="M5.5,18.5 L8,21 L12.5,15.5" stroke="${col === "yellow" ? "#231a00" : "#fff"}" stroke-width="2" fill="none" stroke-linecap="round"/>` : "";
  const slash = status === "eradicated" ? `<path d="M2,26 L16,2" stroke="#fff" stroke-width="1.6" opacity=".85"/>` : "";
  return `<svg width="${size * 0.64}" height="${size}" viewBox="0 0 18 28" aria-hidden="true">
    <rect x="5" y="1" width="8" height="3" rx="1" fill="${c}"/>
    <path d="M6,4 L12,4 L12,10 L15,14 L15,24 Q15,27 12,27 L6,27 Q3,27 3,24 L3,14 L6,10 Z" fill="${done ? c : "none"}" stroke="${c}" stroke-width="1.6"/>${tick}${slash}</svg>`;
}

const WORLD_IMG =
  "data:image/svg+xml;charset=utf-8," +
  encodeURIComponent(`<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 ${W} ${H}"><path d="${MAP.land}" fill="#fff" fill-opacity=".3" fill-rule="evenodd"/></svg>`);

export function miniMap(id) {
  const c = CITIES[id];
  const vw = 560;
  const vh = 386;
  const vx = clamp(c.x - vw / 2, 0, W - vw);
  const vy = clamp(c.y - vh / 2, 0, H - vh);
  return `<svg viewBox="${vx} ${vy} ${vw} ${vh}" preserveAspectRatio="xMidYMid slice" aria-hidden="true"><image href="${WORLD_IMG}" width="${W}" height="${H}"/><circle cx="${c.x}" cy="${c.y}" r="18" fill="#fff" stroke="rgba(0,0,0,.55)" stroke-width="7"/></svg>`;
}

export function cardHtml(c, o = {}) {
  const tag = o.pick ? `aria-pressed="${!!o.sel}"` : "";
  const dis = o.disabled ? "disabled" : "";
  if (c === null) return `<div class="pcard back" aria-label="Hidden card"><span class="cname">?</span></div>`;
  if (c === "epidemic") {
    return `<div class="pcard epidemic" aria-label="Epidemic card"><span class="bio-big">☣︎</span><span class="cname">Epidemic</span></div>`;
  }
  if (isEv(c)) {
    const e = EVENTS[c];
    const extra = o.stored ? '<span class="stored-tag">Stored</span>' : "";
    return `<button class="pcard event" data-card="${c}" ${tag} ${dis} aria-label="Event ${e.name}: ${e.text}" title="${e.name}: ${e.text}"><span class="eico">${icon("event")}</span><span class="cname">${e.name}</span><span class="etext">${e.text}</span><span class="ctype">Event<span class="any"> · play any time</span></span>${extra}<span class="tick">${icon("check", 16)}</span></button>`;
  }
  const ci = CITIES[c];
  return `<button class="pcard ${ci.color}" data-card="${c}" ${tag} ${dis} aria-label="${ci.name}, ${ci.color}${o.here ? ", you are here" : ""}">
    <span class="mapbox">${miniMap(c)}${o.here ? `<span class="here">${icon("pin")}Here</span>` : ""}</span>
    <span class="cname">${ci.name}</span>
    <span class="ctype">${glyph(ci.color, 10, true)}${DNAME[ci.color]}</span>
    <span class="tick">${icon("check", 16)}</span></button>`;
}

export function toast(message, error = false) {
  const box = document.getElementById("toasts");
  const el = document.createElement("div");
  el.className = `toast${error ? " err" : ""}`;
  el.textContent = message;
  box.append(el);
  setTimeout(() => el.remove(), 3600);
}

export async function copyText(text) {
  if (navigator.clipboard && window.isSecureContext) {
    try {
      await navigator.clipboard.writeText(text);
      return true;
    } catch {
      /* fall through to the legacy path */
    }
  }
  // Plain-http LAN addresses are not a secure context, so the async clipboard API is missing.
  const area = document.createElement("textarea");
  Object.assign(area.style, { position: "fixed", opacity: "0", top: "0" });
  area.value = text;
  document.body.append(area);
  area.select();
  let ok = false;
  try {
    ok = document.execCommand("copy");
  } catch {
    ok = false;
  }
  area.remove();
  return ok;
}
