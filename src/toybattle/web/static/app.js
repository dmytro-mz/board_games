import { NAME_KEY, TOKEN_KEY, gameBase, leaveRoom, socketUrl } from "/static/shared/platform.js";
import { copyText, h, morph, openDialog, toast } from "/static/shared/dom.js";
import { SIDE_COLORS, armyStyle, icon, installArt, kindOf, richText, sideOf, strengthLabel, troopBack, troopTile } from "./art.js";
import { BH, BW, FX_ICON, at, boardSvg, pct } from "./board.js";
import { showRules } from "./rules.js";
import { getVolume, isMuted, setMuted, setVolume, sfx, unlockAudio } from "./sound.js";

const BASE = gameBase(import.meta.url); // /g/<key>/: this game's server routes
const MAX_SEATS = 2;
const SUMMARY_DELAY = 1900;
const STEP = 430; // ms between the animated events of one move

const app = document.getElementById("app");
const overlay = document.getElementById("overlay");
const URL_TOKEN = takeTokenFromUrl();

const S = {
  config: { reactions: [], terrains: [], kinds: [] },
  token: URL_TOKEN || localStorage.getItem(TOKEN_KEY) || newToken(),
  name: localStorage.getItem(NAME_KEY) || "",
  code: null,
  ws: null,
  retry: 0,
  reconnectTimer: null,
  connected: false,
  fatal: null,
  me: null,
  bots: [],
  log: [],
  state: null,
  ui: freshUi(),
  timer: { endAt: 0, total: 0, lastTick: 0 },
};
localStorage.setItem(TOKEN_KEY, S.token);

function freshUi() {
  return { sel: null, moveFrom: null, sideOpen: false, unread: 0, menu: false, summaryHidden: false, summaryAt: 0, pending: false, drag: null, info: null };
}

function takeTokenFromUrl() {
  const params = new URLSearchParams(location.search);
  const t = params.get("me");
  if (!t || !/^[0-9a-f]{16,64}$/.test(t)) return null;
  history.replaceState({}, "", location.pathname);
  return t;
}

function newToken() {
  const bytes = new Uint8Array(16);
  crypto.getRandomValues(bytes);
  return Array.from(bytes, (b) => b.toString(16).padStart(2, "0")).join("");
}

const ADJECTIVES = ["Brave", "Bouncy", "Sneaky", "Wobbly", "Tin", "Plucky", "Fuzzy", "Clockwork", "Rubber", "Mighty"];
const NOUNS = ["General", "Captain", "Marshal", "Sergeant", "Commander", "Admiral", "Corporal", "Colonel", "Major", "Cadet"];
const pick = (xs) => xs[Math.floor(Math.random() * xs.length)];
const suggestName = () => `${pick(ADJECTIVES)} ${pick(NOUNS)}`;

function saveName(name) {
  name = (name || "").trim().slice(0, 20);
  if (!name) return S.name;
  S.name = name;
  localStorage.setItem(NAME_KEY, name);
  return name;
}

const $ = (sel) => document.querySelector(sel);
const seatName = (st, seat) => st.seats[seat]?.name || "?";
const botInfo = (key) => S.bots.find((b) => b.key === key);
const terrainOf = (key) => S.config.terrains.find((t) => t.key === key) || S.config.terrains[0];
const kinds = () => S.config.kinds;
const kindName = (k) => S.config.kinds[k]?.name || `troop ${k}`;
// The army drawn at the bottom of the board: yours, or Blue for spectators.
const mySide = (st) => st.you.seat ?? 0;
const flipped = (st) => mySide(st) === 1;
const calm = window.matchMedia("(prefers-reduced-motion: reduce)");

// ------------------------------------------------------------------ routing + socket
function router() {
  const match = location.pathname.match(/\/r\/([A-Za-z0-9]{4,8})\/?$/);
  overlay.replaceChildren();
  if (match) enterRoom(match[1].toUpperCase());
  else leaveRoom();
}
window.addEventListener("popstate", router);

function logo() {
  return h("div", { class: "logo small" }, icon("fort", "logo-fort", 1), h("span", { class: "logo-word" }, "Toy Battle"));
}

async function enterRoom(code) {
  closeSocket();
  Object.assign(S, { code, state: null, log: [], fatal: null, me: null, connected: false, retry: 0 });
  S.ui = freshUi();
  document.title = `Toy Battle · ${code}`;
  if (!S.name && !URL_TOKEN) await askName(`Join table ${code}`);
  buildShell();
  connect();
}

function connect() {
  const ws = new WebSocket(socketUrl(BASE, S.code));
  S.ws = ws;
  ws.onopen = () => ws.send(JSON.stringify({ type: "hello", token: S.token, name: S.name }));
  ws.onmessage = (e) => onMessage(JSON.parse(e.data));
  ws.onclose = () => {
    if (S.ws !== ws) return;
    S.connected = false;
    renderConn();
    if (S.fatal) return;
    const delay = Math.min(8000, 400 * 2 ** S.retry++);
    S.reconnectTimer = setTimeout(connect, delay);
  };
}

function closeSocket() {
  clearTimeout(S.reconnectTimer);
  const ws = S.ws;
  S.ws = null;
  if (ws) ws.close();
}

function send(msg) {
  if (S.ws && S.ws.readyState === WebSocket.OPEN) S.ws.send(JSON.stringify(msg));
  else toast("Not connected. Reconnecting…", true);
}

function act(action) {
  S.ui.sel = null;
  S.ui.moveFrom = null;
  S.ui.pending = true;
  send({ type: "action", action });
  render();
}

function onMessage(msg) {
  switch (msg.type) {
    case "welcome":
      S.me = msg.you;
      S.bots = msg.bots;
      S.log = msg.log;
      S.connected = true;
      S.retry = 0;
      renderConn();
      renderFeed();
      break;
    case "state":
      applyState(msg);
      break;
    case "log":
      S.log.push(msg.entry);
      appendFeed(msg.entry);
      if (msg.entry.kind === "chat" && msg.entry.member !== S.me) {
        sfx.chat();
        if (!S.ui.sideOpen && window.matchMedia("(max-width: 1100px)").matches) {
          S.ui.unread++;
          renderTop();
        }
      }
      break;
    case "react":
      showReaction(msg);
      break;
    case "error":
      S.ui.pending = false;
      toast(msg.message, true);
      sfx.error();
      if (S.state) render();
      break;
    case "fatal":
      S.fatal = msg.message;
      closeSocket();
      app.replaceChildren(h("div", { class: "center-msg" }, h("div", {}, logo(), h("h2", {}, msg.message), h("p", {}, "Tables close a while after everyone has left."), h("button", { class: "btn primary big", onclick: () => leaveRoom() }, "Back to the start"))));
      break;
  }
}

// ------------------------------------------------------------------ state + animation
function applyState(next) {
  const prev = S.state;
  const events = next.event?.events || [];
  const live = prev && next.seq === prev.seq + 1 && !document.hidden && prev.game && next.game && prev.status !== "lobby";
  const before = live ? snapshot() : null;
  S.state = next;
  S.ui.pending = false;
  if (!prev) renderFeed();
  const g = next.game;
  if (g && g.time_left != null) {
    S.timer.endAt = performance.now() + g.time_left * 1000;
    S.timer.total = g.time_total;
  } else S.timer.endAt = 0;
  if (next.status !== prev?.status) {
    S.ui.summaryHidden = false;
    S.ui.summaryAt = next.status === "game_over" && prev?.status === "playing" ? performance.now() + SUMMARY_DELAY + timeline(events).end : 0;
    if (S.ui.summaryAt) setTimeout(renderOverlay, S.ui.summaryAt - performance.now() + 20);
  }
  if (next.event?.kind === "game_start") {
    S.ui = { ...freshUi(), sideOpen: S.ui.sideOpen, unread: S.ui.unread };
    if (!document.hidden) sfx.shuffle();
  }
  const mine = myTurn(next);
  if (!mine) {
    S.ui.sel = null;
    S.ui.moveFrom = null;
  }
  if (S.ui.sel != null && !(g?.racks[mySide(next)]?.troops || []).includes(S.ui.sel)) S.ui.sel = null;
  render();
  if (before) {
    animate(before, events, next);
  }
  afterApply(prev, next);
}

function afterApply(prev, next) {
  if (myTurn(next) && !myTurn(prev)) {
    setTimeout(sfx.turn, 250);
    if (document.hidden) document.title = "🔔 Your move! · Toy Battle";
  }
  if (prev?.status === "playing" && next.status === "game_over") {
    const r = next.game.result;
    const delay = timeline(next.event?.events || []).end + 300;
    setTimeout(() => {
      if (r.reason === "hq") hqFalls(r.winner, next);
      if (next.you.seat === r.winner) {
        sfx.fanfare();
        confetti();
      } else if (next.you.seat != null) sfx.lose();
    }, delay);
  }
}

document.addEventListener("visibilitychange", () => {
  if (!document.hidden && S.code) document.title = `Toy Battle · ${S.code}`;
});

// When each event of a move starts animating (ms), so knock-offs come after the frog lands, medals after that…
function timeline(events) {
  let t = 0;
  const at = [];
  let end = 0;
  for (const e of events) {
    at.push(t);
    const d = { place: STEP, knock: STEP, move: STEP, recall: STEP, revive: STEP, snatch: STEP, pin: STEP * 0.8, draw: STEP * 0.7, medals: STEP * 1.2 }[e.kind] || 0;
    t += d;
    end = Math.max(end, t);
  }
  return { at, end };
}

function snapshot() {
  const map = new Map();
  for (const el of document.querySelectorAll("#game [data-key]")) {
    const ghost = flights.get(el.dataset.key)?.ghost;
    map.set(el.dataset.key, { rect: (ghost || el).getBoundingClientRect(), node: el.cloneNode(true) });
    land(el.dataset.key);
  }
  const rect = (sel) => $(sel)?.getBoundingClientRect() || null;
  return { map, bag: [rect("#bag-0"), rect("#bag-1")], rack: [rect("#rack-0"), rect("#rack-1")], discard: rect("#discard") };
}

const flights = new Map();

function land(key) {
  const f = flights.get(key);
  if (!f) return;
  f.ghost.remove();
  f.hide?.cancel();
  flights.delete(key);
  const el = document.querySelector(`#game [data-key="${key}"]`);
  if (el) el.style.visibility = "";
}

// Fly a stand-in of `el` from `from` to where `el` is now, after `delay` ms; the real element stays hidden.
function flyTo(el, from, { delay = 0, duration = 480, arc = 0, spin = 0, cls = "" } = {}) {
  if (calm.matches || !from) return;
  const to = el.getBoundingClientRect();
  if (!to.width) return;
  const dx = from.left + from.width / 2 - (to.left + to.width / 2);
  const dy = from.top + from.height / 2 - (to.top + to.height / 2);
  const sc = from.width / to.width || 1;
  if (Math.abs(dx) + Math.abs(dy) < 2 && Math.abs(sc - 1) < 0.02) return;
  const key = el.dataset.key;
  land(key);
  const ghost = el.cloneNode(true);
  ghost.classList.remove("target", "sel", "pick");
  ghost.classList.add("flying");
  if (cls) ghost.classList.add(cls);
  ghost.removeAttribute("id");
  Object.assign(ghost.style, { left: `${to.left}px`, top: `${to.top}px`, width: `${to.width}px`, height: `${to.height}px`, margin: "0", visibility: "" });
  document.body.append(ghost);
  el.style.visibility = "hidden";
  const mid = `translate(${dx / 2}px, ${dy / 2 - arc}px) scale(${(sc + 1) / 2 + arc / 300}) rotate(${spin / 2}deg)`;
  const anim = ghost.animate(
    [{ transform: `translate(${dx}px, ${dy}px) scale(${sc})` }, { transform: mid, offset: 0.5 }, { transform: `rotate(${spin}deg)` }],
    { duration, delay, easing: "cubic-bezier(.3,.6,.3,1)", fill: "backwards" },
  );
  flights.set(key, { ghost });
  anim.onfinish = () => {
    if (flights.get(key)?.ghost === ghost) {
      land(key);
      el.classList.remove("stomp");
      void el.offsetWidth;
      el.classList.add("stomp");
    } else ghost.remove();
  };
}

// A throw-away element flying between two rects (troops leaving the board for good, medals, hidden draws).
function flyNode(node, from, to, { delay = 0, duration = 520, spin = 0, fade = false, arc = 30 } = {}) {
  if (!from || !to || calm.matches) return;
  node.classList.add("flying");
  Object.assign(node.style, { left: `${from.left}px`, top: `${from.top}px`, width: `${from.width}px`, height: `${from.height}px` });
  document.body.append(node);
  const dx = to.left + to.width / 2 - (from.left + from.width / 2);
  const dy = to.top + to.height / 2 - (from.top + from.height / 2);
  const sc = Math.max(0.2, to.width / from.width);
  const anim = node.animate(
    [
      { transform: "none", opacity: 1 },
      { transform: `translate(${dx / 2}px, ${dy / 2 - arc}px) scale(${(1 + sc) / 2 + 0.15}) rotate(${spin / 2}deg)`, opacity: 1, offset: 0.5 },
      { transform: `translate(${dx}px, ${dy}px) scale(${sc}) rotate(${spin}deg)`, opacity: fade ? 0 : 1 },
    ],
    { duration, delay, easing: "cubic-bezier(.3,.6,.3,1)", fill: "both" },
  );
  anim.onfinish = () => node.remove();
}

function later(ms, fn) {
  if (ms <= 0) fn();
  else setTimeout(fn, ms);
}

function animate(before, events, st) {
  const { at } = timeline(events);
  const me = mySide(st);
  const now = (sel) => $(sel)?.getBoundingClientRect() || null;
  const delayOf = new Map(); // data-key -> delay of the event that moved it
  const kindOfMove = new Map();
  events.forEach((e, i) => {
    if (e.troop != null) {
      const key = `t${e.troop}`;
      if (!delayOf.has(key) || e.kind !== "draw") delayOf.set(key, at[i]);
      kindOfMove.set(key, e.kind);
    }
    if (e.kind === "draw") for (const t of e.troops) if (t != null) delayOf.set(`t${t}`, at[i]);
  });
  // Elements still (or newly) on screen
  for (const el of document.querySelectorAll("#game [data-key]")) {
    const key = el.dataset.key;
    const old = before.map.get(key);
    const delay = delayOf.get(key) || 0;
    const how = kindOfMove.get(key);
    const opts = { delay, duration: how === "knock" || how === "snatch" ? 560 : 470, arc: how === "place" ? 26 : how === "move" ? 18 : 10, spin: how === "knock" ? 540 : how === "snatch" ? 300 : 0 };
    if (old) {
      flyTo(el, old.rect, opts);
      continue;
    }
    if (key.startsWith("t")) {
      const troop = Number(key.slice(1));
      const side = sideOf(troop);
      const ev = events.find((e) => e.troop === troop || (e.kind === "draw" && e.troops.includes(troop)));
      if (!ev) continue;
      if (ev.kind === "draw") flyTo(el, before.bag[side], opts);
      else if (ev.kind === "place" || ev.kind === "snatch") flyTo(el, before.rack[side], opts);
      else if (ev.kind === "revive") flyTo(el, before.discard, opts);
    } else if (key.startsWith("hb")) {
      // a face-down troop arriving on the opponent's rack
      const side = Number(key[2]);
      const drew = events.findIndex((e) => e.kind === "draw" && e.seat === side);
      if (drew >= 0) flyTo(el, before.bag[side], { delay: at[drew], duration: 450, arc: 10 });
    }
  }
  // Sounds and extra effects per event
  events.forEach((e, i) => {
    const t = at[i];
    switch (e.kind) {
      case "place":
        later(t + 330, e.covered != null && sideOf(e.covered) !== e.seat ? sfx.cover : sfx.place);
        if (kindOf(e.troop) === 4) later(t, sfx.whoosh);
        if (kindOf(e.troop) === 0) later(t + 380, sfx.boing);
        later(t + 380, () => puff(e.node));
        break;
      case "knock":
        later(t, sfx.knock);
        later(t, () => bump(e.by));
        break;
      case "rally":
        later(t, sfx.rally);
        break;
      case "snatch":
        later(t, sfx.magnet);
        break;
      case "pin":
        later(t, sfx.sand);
        break;
      case "move":
        later(t, sfx.whoosh);
        break;
      case "recall":
      case "revive":
      case "draw":
        later(t + 100, sfx.draw);
        break;
      case "medals":
        later(t, () => medalFlight(e, st));
        break;
      default:
        break;
    }
  });
  // Opponent's hidden troops leaving their rack for the board don't exist as elements before: handled above.
  void me;
  void now;
}

function slotRect(node) {
  return document.querySelector(`.slot[data-node="${node}"]`)?.getBoundingClientRect() || null;
}

function puff(node) {
  const r = slotRect(node);
  if (!r || calm.matches) return;
  const el = h("div", { class: "puff", style: { left: `${r.left + r.width / 2}px`, top: `${r.top + r.height / 2}px` } });
  document.body.append(el);
  setTimeout(() => el.remove(), 700);
}

function bump(node) {
  const el = document.querySelector(`.slot[data-node="${node}"] .troop`);
  if (!el || calm.matches) return;
  el.animate([{ transform: "none" }, { transform: "scale(1.18) rotate(-8deg)" }, { transform: "none" }], { duration: 360 });
}

function medalFlight(e, st) {
  sfx.medal();
  const t = terrainOf(st.game.terrain);
  const region = t.regions.find((r) => r.id === e.region);
  const board = $("#board")?.getBoundingClientRect();
  const target = $(`#medals-${e.seat}`)?.getBoundingClientRect();
  if (!region || !board || !target) return;
  const p = pct(at({ x: region.cx, y: region.cy }, flipped(st)));
  const size = board.width * 0.09;
  const from = { left: board.left + (p.left / 100) * board.width - size / 2, top: board.top + (p.top / 100) * board.height - size / 2, width: size, height: size };
  for (let k = 0; k < e.medals; k++) {
    const coin = h("div", { class: "coin" }, icon("medal"));
    flyNode(coin, from, { left: target.left, top: target.top, width: target.height, height: target.height }, { delay: k * 140, duration: 760, arc: 60 });
  }
  setTimeout(() => $(`#medals-${e.seat}`)?.animate([{ transform: "scale(1)" }, { transform: "scale(1.35)" }, { transform: "scale(1)" }], { duration: 420 }), 760 + (e.medals - 1) * 140);
}

function hqFalls(winner, st) {
  const loser = 1 - winner;
  const t = terrainOf(st.game.terrain);
  const hq = t.nodes.find((n) => n.kind === "hq" && n.side === loser && st.game.stacks[n.id].length);
  $("#board")?.animate([{ transform: "none" }, { transform: "translate(-6px, 3px) rotate(-0.6deg)" }, { transform: "translate(6px, -3px) rotate(0.6deg)" }, { transform: "none" }], { duration: 420, iterations: 2 });
  if (!hq) return;
  const r = slotRect(hq.id);
  if (!r) return;
  for (let i = 0; i < 18; i++) {
    const a = (i / 18) * Math.PI * 2;
    const bit = h("div", { class: "debris", style: { left: `${r.left + r.width / 2}px`, top: `${r.top + r.height / 2}px`, background: SIDE_COLORS[loser].army } });
    document.body.append(bit);
    bit.animate([{ transform: "translate(0,0) rotate(0)", opacity: 1 }, { transform: `translate(${Math.cos(a) * 110}px, ${Math.sin(a) * 110 + 60}px) rotate(${360 * Math.random()}deg)`, opacity: 0 }], { duration: 1100, easing: "cubic-bezier(.2,.7,.3,1)" }).onfinish = () => bit.remove();
  }
}

// ------------------------------------------------------------------ shell
function buildShell() {
  const input = h("input", { class: "text", placeholder: "Say something…", maxlength: 240, enterkeyhint: "send" });
  const form = h(
    "form",
    {
      class: "chat-form",
      onsubmit: (e) => {
        e.preventDefault();
        const text = input.value.trim();
        if (!text) return;
        send({ type: "chat", text });
        input.value = "";
      },
    },
    input,
    h("button", { class: "btn small" }, "Send"),
  );
  app.replaceChildren(
    h(
      "div",
      { class: "shell" },
      h("header", { class: "topbar", id: "topbar" }),
      h("main", { class: "main", id: "main" }, h("div", { class: "center-msg" }, h("p", {}, "Unpacking the toy box…"))),
      h(
        "aside",
        { class: "side", id: "side" },
        h("div", { class: "players", id: "players" }),
        h("div", { class: "side-head" }, "Battle log", h("button", { class: "icon-btn only-narrow", onclick: toggleSide, title: "Close" }, "✕")),
        h("div", { class: "feed", id: "feed" }),
        h("div", { class: "reactions" }, (S.config.reactions || []).map((emoji) => h("button", { title: "React", onclick: () => send({ type: "react", emoji }) }, emoji))),
        form,
      ),
    ),
    h("div", { id: "conn", class: "conn-banner hidden" }, "Reconnecting…"),
  );
  renderTop();
}

function renderConn() {
  $("#conn")?.classList.toggle("hidden", S.connected || !!S.fatal || !S.code);
}

function toggleSide() {
  S.ui.sideOpen = !S.ui.sideOpen;
  if (S.ui.sideOpen) S.ui.unread = 0;
  $("#side")?.classList.toggle("open", S.ui.sideOpen);
  renderTop();
}

function feedEntry(entry) {
  const time = new Date(entry.ts * 1000).toLocaleTimeString();
  if (entry.kind === "chat") return h("div", { class: "entry chat", title: time }, h("b", {}, entry.name), ": ", entry.text);
  const st = S.state;
  const side = entry.seat != null && st?.seats[entry.seat] ? entry.seat : null;
  const dot = side != null ? h("span", { class: "who", style: { background: SIDE_COLORS[side].army } }) : null;
  return h("div", { class: "entry log", title: time }, dot, richText(entry.text, kinds()));
}

function renderFeed() {
  const feed = $("#feed");
  if (!feed) return;
  feed.replaceChildren(...S.log.map(feedEntry));
  feed.scrollTop = feed.scrollHeight;
}

function appendFeed(entry) {
  const feed = $("#feed");
  if (!feed) return;
  const atBottom = feed.scrollHeight - feed.scrollTop - feed.clientHeight < 60;
  feed.append(feedEntry(entry));
  while (feed.children.length > 400) feed.firstChild.remove();
  if (atBottom || entry.member === S.me) feed.scrollTop = feed.scrollHeight;
}

function iconBtn(glyph, title, onclick, cls = "", badge = 0) {
  return h("button", { class: `icon-btn ${cls}`, title, "aria-label": title, onclick }, glyph, badge ? h("span", { class: "badge-dot" }, badge) : null);
}

const volumeControl = (() => {
  const btn = h("button", { class: "icon-btn" });
  const range = h("input", { type: "range", min: 0, max: 100, step: 1, class: "vol-range", "aria-label": "Volume" });
  const pct = h("span", { class: "vol-pct" });
  const sync = () => {
    const vol = getVolume();
    const off = isMuted() || vol === 0;
    btn.textContent = off ? "🔇" : vol < 0.4 ? "🔉" : "🔊";
    btn.title = off ? "Sound off. Click to turn on" : "Click to mute";
    range.value = String(Math.round(vol * 100));
    pct.textContent = off ? "off" : `${Math.round(vol * 100)}%`;
  };
  btn.addEventListener("click", () => {
    unlockAudio();
    if (isMuted() || getVolume() === 0) {
      setMuted(false);
      if (getVolume() === 0) setVolume(0.8);
      sync();
      sfx.place();
    } else {
      setMuted(true);
      sync();
    }
  });
  range.addEventListener("input", () => {
    setVolume(Number(range.value) / 100);
    if (isMuted()) setMuted(false);
    sync();
  });
  range.addEventListener("change", () => sfx.select());
  sync();
  const place = () => {
    const r = btn.getBoundingClientRect();
    wrap.style.setProperty("--vol-top", `${r.bottom + 4}px`);
    wrap.style.setProperty("--vol-right", `${Math.max(8, window.innerWidth - r.right - 60)}px`);
  };
  const wrap = h("div", { class: "vol", onpointerenter: place, onfocusin: place }, btn, h("div", { class: "vol-pop" }, h("span", {}, "🔈"), range, pct));
  return wrap;
})();

function renderTop() {
  const top = $("#topbar");
  if (!top) return;
  const st = S.state;
  const g = st?.game;
  let info = "";
  if (st?.status === "lobby") info = "Lobby";
  else if (g) info = `${terrainOf(g.terrain).name} · turn ${Math.ceil(g.turn / 2)}`;
  const before = [
    h("span", { class: "brand", title: "Leave", onclick: leaveTable }, icon("fort", "brand-fort", 1), h("span", { class: "brand-word" }, "Toy Battle")),
    h("span", { class: "chip code", title: "Copy table code", onclick: copyCode }, "📋 ", S.code),
    h("button", { class: "btn primary small invite-btn", title: `Copy the invite link (${inviteUrl()})`, onclick: copyInvite }, "🔗 ", h("span", { class: "invite-label" }, "Copy invite link")),
    h("span", { class: "round-info" }, info),
    h("span", { class: "spacer" }),
    iconBtn("📖", "Rule book", () => showRules(S.config, g?.terrain || st?.settings?.terrain)),
  ];
  const after = [iconBtn("💬", "Log & players", toggleSide, "only-narrow", S.ui.unread), iconBtn("⋯", "Menu", toggleMenu)];
  if (volumeControl.parentNode !== top) top.replaceChildren(h("span", { class: "top-l" }), volumeControl, h("span", { class: "top-r" }));
  morph(top.firstChild, before);
  morph(top.lastChild, after);
  const menu = document.getElementById("menu");
  if (!S.ui.menu) menu?.remove();
  else if (menu) morph(menu, [...renderMenu().childNodes]);
  else document.body.append(renderMenu());
}

function toggleMenu() {
  S.ui.menu = !S.ui.menu;
  renderTop();
}

function renderMenu() {
  const st = S.state;
  const isHost = st?.host === S.me;
  const item = (label, fn) =>
    h(
      "button",
      {
        onclick: () => {
          S.ui.menu = false;
          renderTop();
          fn();
        },
      },
      label,
    );
  return h(
    "div",
    { class: "menu", id: "menu" },
    item("📖 Rule book", () => showRules(S.config, st?.game?.terrain || st?.settings?.terrain)),
    item("📱 Continue on another device", async () => {
      const url = `${inviteUrl()}?me=${S.token}`;
      const ok = await copyText(url);
      toast(ok ? "Personal link copied. Open it on your other device (don't share it!)" : url, !ok);
    }),
    item("✏️ Change my name", async () => {
      const name = await askName("Change your name", true);
      if (name) send({ type: "rename", name });
    }),
    isHost && st?.status !== "lobby"
      ? item("⏹ End game, back to lobby", () => {
          if (confirm("End the current game for everyone?")) send({ type: "to_lobby" });
        })
      : null,
    item("🚪 Leave table", leaveTable),
  );
}

document.addEventListener("click", (e) => {
  if (S.ui.menu && !e.target.closest(".menu") && !e.target.closest('[title="Menu"]')) {
    S.ui.menu = false;
    renderTop();
  }
});

function leaveTable() {
  S.ui.menu = false;
  document.getElementById("menu")?.remove();
  closeSocket();
  leaveRoom();
}

function inviteUrl() {
  const local = ["localhost", "127.0.0.1", "[::1]"].includes(location.hostname);
  const base = S.config.public_url || (local && S.config.lan_url) || location.origin;
  return `${base.replace(/\/$/, "")}/r/${S.code}`;
}

async function copyCode() {
  const ok = await copyText(S.code);
  toast(ok ? `Table code ${S.code} copied` : `Table code: ${S.code}`, !ok);
}

async function copyInvite() {
  const ok = await copyText(inviteUrl());
  toast(ok ? "Invite link copied. Send it to your opponent!" : inviteUrl(), !ok);
}

function askName(title, dismissable = false) {
  return new Promise((resolve) => {
    const suggestion = S.name || suggestName();
    const input = h("input", { class: "text", value: S.name, placeholder: suggestion, maxlength: 20, style: { width: "100%" } });
    let close = null;
    const done = (e) => {
      e?.preventDefault();
      const name = saveName(input.value || suggestion);
      close();
      resolve(name);
    };
    close = openDialog(h("div", { class: "modal" }, h("h2", {}, title), h("p", { class: "sub" }, "Pick a name your opponent will see."), h("form", { onsubmit: done }, input, h("div", { class: "actions" }, h("button", { class: "btn primary", type: "submit" }, "To the playroom!")))), { dismissable, onClose: () => resolve(null) });
    input.focus();
  });
}

// ------------------------------------------------------------------ render
function render() {
  renderTop();
  const st = S.state;
  const main = $("#main");
  if (!st || !main) return;
  renderPlayers(st);
  if (st.status === "lobby") renderLobby(st, main);
  else renderGame(st, main);
  renderOverlay();
}

function avatar(seat, online, bot) {
  const c = SIDE_COLORS[seat.seat] || SIDE_COLORS[0];
  const label = bot ? "🤖" : (seat.name || "?").trim().charAt(0).toUpperCase();
  return h("span", { class: `avatar ${bot ? "" : online ? "online" : "offline"}`, style: { background: `linear-gradient(180deg, ${c.army}, ${c.dark})` } }, label);
}

function renderPlayers(st) {
  const box = $("#players");
  if (!box) return;
  const g = st.game;
  const isHost = st.host === S.me;
  const rows = st.seats.map((s, i) => {
    const bot = s.bot ? botInfo(s.bot) : null;
    const sub = bot ? `${bot.label} ${"★".repeat(bot.stars)}` : s.autoplay ? "autopilot" : s.connected ? (i === st.you.seat ? "you" : "online") : "offline";
    const current = g && st.status === "playing" && g.current === i;
    return h(
      "div",
      { class: `pl-row s${i} ${current ? "current" : ""}`, "data-seat": i },
      avatar(s, s.connected, !!s.bot),
      h("div", { class: "pl-id" }, h("span", { class: "pl-name" }, s.name, s.member === st.host ? h("small", {}, " · host") : null), h("span", { class: "pl-sub" }, `${SIDE_COLORS[i].name} · ${sub}`)),
      isHost && !s.bot && !s.connected && st.status === "playing" ? h("button", { class: "btn small", onclick: () => send({ type: "autoplay", seat: i, on: !s.autoplay }) }, s.autoplay ? "Wait" : "Bot plays") : null,
      g ? h("span", { class: "pl-score", title: "Medals" }, icon("medal", "inline"), ` ${g.medals[i]}/${g.objective[i]}`) : null,
    );
  });
  const watching = st.spectators.filter((s) => s.connected);
  morph(box, [rows, watching.length ? h("div", { class: "pl-sub watching" }, `👀 Watching: ${watching.map((s) => s.name).join(", ")}`) : null]);
}

// ------------------------------------------------------------------ lobby
function renderLobby(st, main) {
  const isHost = st.host === S.me;
  const mySeat = st.you.seat;
  const n = st.seats.length;
  const set = st.settings;
  const change = (k, v) => send({ type: "settings", changes: { [k]: v } });
  const hostName = st.seats.find((s) => s.member === st.host)?.name || st.spectators.find((s) => s.member === st.host)?.name || "the host";

  // Terrains first, at the top
  const card = (t) => {
    const on = set.terrain === t.key;
    const obj = t.objective[0] === t.objective[1] ? `${t.objective[0]} medals` : `Blue ${t.objective[0]} · Red ${t.objective[1]}`;
    return h(
      "button",
      { class: `terrain-card ${on ? "on" : ""}`, "data-key": `terrain-${t.key}`, disabled: !isHost && !on, "aria-pressed": on ? "true" : "false", title: t.blurb, onclick: () => isHost && change("terrain", t.key) },
      h("div", { class: "mini-board" }, boardSvg(t, { mini: true, special: set.special })),
      h("div", { class: "tc-text" }, h("span", { class: "tc-name" }, t.name), h("span", { class: "tc-fx" }, set.special ? t.effect_title : "No special bases"), h("span", { class: "tc-obj" }, icon("medal", "inline"), " ", obj)),
      t.first_game ? h("span", { class: "tc-tag" }, "first game") : null,
    );
  };
  const random = h(
    "button",
    { class: `terrain-card random ${set.terrain === "random" ? "on" : ""}`, "data-key": "terrain-random", disabled: !isHost && set.terrain !== "random", onclick: () => isHost && change("terrain", "random") },
    h("div", { class: "mini-board dice" }, "🎲"),
    h("div", { class: "tc-text" }, h("span", { class: "tc-name" }, "Surprise me"), h("span", { class: "tc-fx" }, "A random terrain"), h("span", { class: "tc-obj" }, "drawn at the start")),
  );
  const chosen = set.terrain === "random" ? null : terrainOf(set.terrain);
  const terrains = h(
    "section",
    { class: "panel terrains-panel" },
    h("h3", {}, "Battlefield", isHost ? h("small", {}, "pick the terrain") : h("small", {}, "chosen by the host")),
    h("div", { class: "terrain-grid" }, S.config.terrains.map(card), random),
    chosen ? h("p", { class: "terrain-note" }, h("b", {}, `${chosen.name}. `), chosen.blurb, " ", set.special ? h("span", {}, h("b", {}, `${chosen.effect_title}: `), chosen.effect_text) : "Special bases are switched off.") : null,
  );

  const seatRows = [];
  for (let i = 0; i < MAX_SEATS; i++) {
    const s = st.seats[i];
    if (i === 1) seatRows.push(h("div", { class: "versus-line" }, "VS"));
    if (!s) {
      seatRows.push(h("div", { class: `seat-empty s${i}` }, h("span", { class: "army-dot", style: armyStyle(i) }), `${SIDE_COLORS[i].name} army: empty seat`, mySeat == null ? h("button", { class: "btn small primary", onclick: () => send({ type: "sit" }) }, "Take it") : null));
      continue;
    }
    const bot = s.bot ? botInfo(s.bot) : null;
    const isMe = i === mySeat;
    seatRows.push(
      h(
        "div",
        { class: `seat-row s${i}` },
        h("div", { class: "seat-army", style: armyStyle(i) }, icon("fort", "seat-fort", i)),
        h("div", { class: "seat-id" }, h("span", { class: "name" }, s.name), h("span", { class: "army-name" }, `${SIDE_COLORS[i].name} army`)),
        s.member === st.host ? h("span", { class: "tag host" }, "Host") : null,
        isMe ? h("span", { class: "tag you" }, "You") : null,
        bot ? h("span", { class: "tag stars", title: bot.description }, "★".repeat(bot.stars)) : null,
        !s.bot && !s.connected ? h("span", { class: "tag" }, "offline") : null,
        isMe ? h("button", { class: "icon-btn", title: "Leave seat (watch instead)", onclick: () => send({ type: "stand" }) }, "⏏") : null,
        isHost && !isMe ? h("button", { class: "icon-btn", title: "Remove", onclick: () => send({ type: "remove_seat", seat: i }) }, "✕") : null,
      ),
    );
  }
  const spectators = st.spectators.filter((s) => s.connected);
  const seatsPanel = h(
    "section",
    { class: "panel" },
    h("h3", {}, "Commanders", h("small", {}, `${n} / ${MAX_SEATS}`)),
    h("div", { class: "seat-list" }, seatRows),
    isHost ? h("div", { class: "seat-tools" }, h("button", { class: "btn small", disabled: n < 2, onclick: () => send({ type: "swap" }) }, "🔀 Swap armies")) : null,
    spectators.length ? h("p", { class: "waiting" }, "Watching: ", spectators.map((s) => s.name).join(", ")) : null,
  );
  const botsPanel = h(
    "section",
    { class: "panel" },
    h("h3", {}, "Play against the bot", isHost ? null : h("small", {}, "host only")),
    h(
      "div",
      { class: "bot-grid" },
      S.bots.map((b) =>
        h(
          "button",
          { class: "bot-btn", disabled: !isHost || n >= MAX_SEATS, title: b.description, onclick: () => send({ type: "add_bot", bot: b.key }) },
          h("span", { class: "bot-face" }, "🤖"),
          h("span", { class: "bot-txt" }, h("span", { class: "bname" }, b.label, " ", h("span", { class: "stars" }, "★".repeat(b.stars))), h("span", { class: "bdesc" }, b.description)),
        ),
      ),
    ),
  );
  const select = (k, options) =>
    h(
      "select",
      { class: "select", disabled: !isHost, onchange: (e) => change(k, isNaN(Number(e.target.value)) ? e.target.value : Number(e.target.value)) },
      options.map(([value, label]) => {
        const opt = h("option", { value }, label);
        opt.selected = String(set[k]) === String(value);
        return opt;
      }),
    );
  const toggle = (k) => {
    const input = h("input", { type: "checkbox", disabled: !isHost, onchange: (e) => change(k, e.target.checked) });
    input.checked = !!set[k];
    return h("label", { class: "switch" }, input, h("span"));
  };
  const row = (label, help, control) => h("div", { class: "setting" }, h("span", { class: "label" }, label, h("small", {}, help)), control);
  const settingsPanel = h(
    "section",
    { class: "panel" },
    h("h3", {}, "Table rules", isHost ? null : h("small", {}, "set by the host")),
    h(
      "div",
      { class: "settings" },
      row("Special bases", "Off for a calmer first game: troop effects only", toggle("special")),
      row(
        "Turn timer",
        "The autopilot finishes your turn when time runs out",
        select("turn_timer", [
          [0, "Off"],
          [30, "30 s"],
          [60, "1 min"],
          [90, "90 s"],
          [180, "3 min"],
        ]),
      ),
      row(
        "Bot speed",
        "How quickly the bot moves",
        select("bot_speed", [
          ["slow", "Relaxed"],
          ["normal", "Normal"],
          ["fast", "Fast"],
        ]),
      ),
    ),
  );
  const actions = isHost
    ? h("div", { class: "lobby-actions" }, h("button", { class: "btn ghost", onclick: () => showRules(S.config, set.terrain) }, "📖 Rule book"), h("button", { class: "btn primary big", disabled: n < 2, onclick: () => send({ type: "start" }) }, n < 2 ? "Waiting for an opponent" : "⚔️ To battle!"))
    : h("div", { class: "lobby-actions" }, h("button", { class: "btn ghost", onclick: () => showRules(S.config, set.terrain) }, "📖 Rule book"), h("span", { class: "waiting" }, `Waiting for ${hostName} to start the game…`));
  morph(main, h("section", { class: "lobby", id: "lobby" }, terrains, h("div", { class: "lobby-grid" }, h("div", { class: "lobby-col" }, seatsPanel, botsPanel), settingsPanel), actions));
}

// ------------------------------------------------------------------ game
const legal = (g) => g.legal || [];
function myTurn(st) {
  return !!st && st.status === "playing" && st.game && st.game.current === st.you.seat && legal(st.game).length > 0;
}

const placeTargets = (g, troop) => new Set(legal(g).filter((a) => a.type === "place" && a.troop === troop).map((a) => a.node));
const placeable = (g) => new Set(legal(g).filter((a) => a.type === "place").map((a) => a.troop));

function layoutMode(main) {
  const r = main.getBoundingClientRect();
  const wide = r.width / Math.max(1, r.height) > 0.95 && r.width >= 600;
  if (wide) {
    const hud = Math.min(420, Math.max(250, r.width * 0.36));
    const bh = Math.min(r.height - 20, ((r.width - hud - 36) * BH) / BW);
    return { mode: "wide", bw: (bh * BW) / BH, hud };
  }
  // tall: opponent strip, board, prompt, my rack
  const tile = Math.max(30, Math.min(50, (Math.min(r.width, 640) - 24) / 8.6));
  const reserve = 50 + 66 + (tile * 1.25 + 56) + 52;
  const bw = Math.min(r.width - 16, ((r.height - reserve) * BW) / BH, 660);
  return { mode: "tall", bw: Math.max(200, bw), hud: Math.min(r.width, 640), tile };
}

function renderGame(st, main) {
  const g = st.game;
  const me = mySide(st);
  const opp = 1 - me;
  const t = terrainOf(g.terrain);
  const flip = flipped(st);
  const lay = layoutMode(main);
  const tile = lay.tile || Math.max(30, Math.min(66, (lay.hud - 60) / 5.75));
  const view = h(
    "div",
    { class: `game ${lay.mode}`, id: "game", style: { "--bw": `${lay.bw}px`, "--hud": `${lay.hud}px`, "--tile": `${tile}px` } },
    h("div", { class: "board-wrap" }, renderBoard(st, t, flip)),
    h("div", { class: "hud" }, armyPanel(st, opp, false), centerPanel(st), armyPanel(st, me, true)),
  );
  morph(main, view);
}

function renderBoard(st, t, flip) {
  const g = st.game;
  const mine = myTurn(st);
  const pend = g.pending?.kind;
  let targets = new Set();
  let picks = new Set();
  if (mine && S.ui.sel != null) targets = placeTargets(g, S.ui.sel);
  if (mine && pend === "knock") picks = new Set(legal(g).filter((a) => a.type === "knock").map((a) => a.node));
  if (mine && pend === "recall") picks = new Set(legal(g).filter((a) => a.type === "recall").map((a) => a.node));
  if (mine && pend === "move") {
    if (S.ui.moveFrom == null) picks = new Set(legal(g).filter((a) => a.type === "move").map((a) => a.node));
    else targets = new Set(legal(g).filter((a) => a.type === "move" && a.node === S.ui.moveFrom).map((a) => a.to));
  }
  const svg = boardSvg(t, { flip, special: g.special, taken: g.region_taken, id: "board-svg" });
  const last = lastPlaced(st);
  // A troop hides the base it stands on: a pin keeps special bases (and the Tropical Pool's numbers) recognisable.
  const fxId = g.special && t.effect !== "none" && t.effect !== "restrict" ? FX_ICON[t.effect] : null;
  const pin = (n) => (n.allow && g.special ? h("span", { class: "fx-pin allow" }, n.allow.join("·")) : n.kind === "special" && fxId ? h("span", { class: "fx-pin", title: t.effect_title }, icon(fxId)) : null);
  const slots = t.nodes.map((n) => {
    const p = at(n, flip);
    const stack = g.stacks[n.id];
    const top = stack.length ? stack[stack.length - 1] : null;
    const cls = ["slot", n.kind, baseInfo(g, t, n) ? "has-info" : "", S.ui.info === n.id ? "info-open" : "", targets.has(n.id) ? "target" : "", picks.has(n.id) ? "pick" : "", S.ui.moveFrom === n.id ? "from" : "", last === n.id ? "last" : "", g.pending && g.pending.node === n.id ? "acting" : ""].filter(Boolean).join(" ");
    const under = stack.slice(0, -1).slice(-3);
    return h(
      "div",
      {
        class: cls,
        "data-node": n.id,
        style: { left: `${pct(p).left}%`, top: `${pct(p).top}%` },
        onclick: () => clickNode(n.id),
        title: stack.length > 1 ? `Stack of ${stack.length}: ${stack.map((x) => `${SIDE_COLORS[sideOf(x)].name} ${strengthLabel(kindOf(x))}`).join(" · ")} (top last)` : null,
      },
      under.map((x, i) => h("div", { class: `under s${sideOf(x)}`, style: { ...armyStyle(sideOf(x)), "--i": under.length - i } })),
      top != null ? troopTile(top, { kinds: kinds(), cls: "on-board" }) : null,
      stack.length > 1 ? h("span", { class: "depth" }, stack.length) : null,
      top != null ? pin(n) : null,
    );
  });
  return h("div", { class: "board", id: "board", "data-terrain": t.key }, svg, h("div", { class: "slots" }, slots), infoBubble(g, t, flip));
}

// What a tap on a base explains: special bases (their effect) and the Tropical Pool's rings (the strengths that fit).
function baseInfo(g, t, n) {
  if (!g.special || !n) return null;
  if (n.allow) {
    const nums = n.allow.map(String);
    const list = nums.length > 1 ? `${nums.slice(0, -1).join(", ")} or ${nums[nums.length - 1]}` : nums[0];
    const title = n.kind === "hq" ? `${SIDE_COLORS[n.side]?.name || ""} H.Q. · ${t.effect_title}` : t.effect_title;
    return { ico: FX_ICON.restrict, title, lead: "", text: `Only a troop of strength ${list} (or a ★ Jack-in-the-Box) may be placed here.` };
  }
  if (n.kind !== "special" || t.effect === "none" || t.effect === "restrict") return null;
  const lead = t.effect === "shield" ? "" : "When you place a troop here";
  return { ico: FX_ICON[t.effect], title: t.effect_title, lead, text: t.effect_text };
}

function infoBubble(g, t, flip) {
  const n = t.nodes.find((x) => x.id === S.ui.info);
  const info = baseInfo(g, t, n);
  if (!info) return null;
  const p = pct(at(n, flip));
  const cls = ["base-info", p.top < 34 ? "below" : "above", p.left < 30 ? "l" : p.left > 70 ? "r" : "c"].join(" ");
  return h(
    "div",
    { class: cls, "data-key": `info-${n.id}`, role: "tooltip", style: { left: `${p.left}%`, top: `${p.top}%` }, onclick: () => closeInfo() },
    info.ico ? icon(info.ico, "bi-ico") : null,
    h("div", { class: "bi-text" }, h("div", { class: "bi-title" }, info.title), info.lead ? h("div", { class: "bi-when" }, info.lead) : null, h("div", {}, info.text)),
  );
}

function closeInfo() {
  if (S.ui.info == null) return false;
  S.ui.info = null;
  document.querySelector(".base-info")?.remove();
  document.querySelector(".slot.info-open")?.classList.remove("info-open");
  return true;
}

function lastPlaced(st) {
  const evs = st.event?.events || [];
  for (let i = evs.length - 1; i >= 0; i--) if (evs[i].kind === "place" || evs[i].kind === "move") return evs[i].kind === "move" ? evs[i].to : evs[i].node;
  return null;
}

function armyPanel(st, side, mineSide) {
  const g = st.game;
  const rack = g.racks[side];
  const seat = st.seats[side];
  const isYou = st.you.seat === side;
  const current = st.status === "playing" && g.current === side;
  const can = isYou && myTurn(st);
  const usable = can ? placeable(g) : new Set();
  const pinned = new Set(rack.pinned);
  const troops = [...rack.troops].sort((a, b) => kindOf(a) - kindOf(b) || a - b);
  const tiles = troops.map((x) => {
    const selectable = usable.has(x);
    const cls = [pinned.has(x) ? "pinned" : "", S.ui.sel === x ? "sel" : "", selectable ? "usable" : "", !isYou && rack.known.includes(x) ? "known" : ""].filter(Boolean).join(" ");
    return troopTile(x, {
      kinds: kinds(),
      cls,
      extra: selectable ? { onpointerdown: (e) => startDrag(e, x), tabindex: 0 } : {},
    });
  });
  for (let i = 0; i < rack.hidden; i++) tiles.push(troopBack(side, `hb${side}-${i}`, i < rack.pinned_count - rack.pinned.length ? "pinned" : ""));
  // empty sockets show how much room the rack (max 8) has left
  const room = mineSide ? Math.max(0, 8 - tiles.length) : 0;
  for (let i = 0; i < room; i++) tiles.push(h("div", { class: "rack-slot", "data-key": `rs${side}-${i}`, "aria-hidden": "true" }));
  const drawAction = can && legal(g).some((a) => a.type === "draw");
  const status = seat ? (seat.bot ? "bot" : seat.connected ? "" : "offline") : "";
  return h(
    "div",
    { class: `army ${mineSide ? "mine" : "theirs"} s${side} ${current ? "current" : ""}`, style: armyStyle(side), "data-seat": side },
    h(
      "div",
      { class: "army-head" },
      h("span", { class: "army-flag" }, icon("fort", "flag-fort", side)),
      h("span", { class: "army-name" }, seat?.name || SIDE_COLORS[side].name, isYou ? h("small", {}, " (you)") : null, status ? h("small", {}, ` · ${status}`) : null, current && !isYou && st.status === "playing" ? h("span", { class: "thinking" }, h("i"), h("i"), h("i")) : null),
      h("span", { class: "medals", id: `medals-${side}`, title: `Medals: ${g.medals[side]} of ${g.objective[side]} needed` }, icon("medal", "medal-ico"), h("b", {}, g.medals[side]), h("small", {}, `/${g.objective[side]}`)),
    ),
    h(
      "div",
      { class: "army-body" },
      h(
        "button",
        { class: `bag ${drawAction ? "can-draw" : ""}`, id: `bag-${side}`, disabled: !drawAction, title: drawAction ? "Draw 2 troops (ends your turn)" : `${g.reserves[side]} troops in reserve`, onclick: () => drawAction && act({ type: "draw" }) },
        icon("bag", "bag-ico", side),
        h("span", { class: "bag-n" }, g.reserves[side]),
        drawAction ? h("span", { class: "bag-label" }, g.reserves[side] === 1 || rack.count === 7 ? "Draw 1" : "Draw 2") : null,
      ),
      h("div", { class: `rack ${rack.count ? "" : "empty"}`, id: `rack-${side}` }, tiles),
    ),
  );
}

const EFFECT_TEXT = {
  draw2: ["Wind-up Mouse", "Draw 2 troops from your reserve?", "Draw"],
  draw1: ["Teddy Bear", "Draw 1 troop from your reserve?", "Draw"],
  bdraw: ["Snack stash", "Draw 1 troop from your reserve?", "Draw"],
  extra: ["Tin Drummer", "Place one more troop: pick it from your rack.", null],
  knock: ["Slingshot Frog", "Tap a glowing enemy troop to knock it off.", null],
  snatch: ["Magnet Bot", "Pull a random troop off your opponent's rack?", "Magnet!"],
  snipe: ["Battlefield", "Bury a random troop of your opponent's rack for their next turn?", "Bury it"],
  recall: ["Toy chest", "Tap one of your other troops to take it back to your rack.", null],
  revive: ["Old trunk", "Take one of your troops back from the discard?", null],
  move: ["Hot floor", "Tap a glowing enemy troop, then the base to push it to.", null],
};

function centerPanel(st) {
  const g = st.game;
  const mine = myTurn(st);
  let prompt;
  const btns = [];
  if (st.status === "game_over") {
    const r = g.result;
    const who = st.you.seat === r.winner ? "You win" : `${seatName(st, r.winner)} wins`;
    prompt = h("div", { class: "prompt over" }, h("b", {}, `🏆 ${who}!`), " ", r.reason === "hq" ? "The H.Q. has fallen." : r.reason === "medals" ? "Enough medals collected." : "A player was stuck; medals decided.");
    btns.push(h("button", { class: "btn small primary", onclick: () => ((S.ui.summaryHidden = false), (S.ui.summaryAt = 0), renderOverlay()) }, "Results"));
  } else if (mine && g.phase === "effect" && g.pending) {
    const [who, text, yes] = EFFECT_TEXT[g.pending.kind] || ["", "Choose", null];
    prompt = h("div", { class: "prompt effect" }, h("b", {}, who), " ", text);
    if (yes) btns.push(h("button", { class: "btn primary", onclick: () => act({ type: "take" }) }, yes));
    if (g.pending.kind === "revive") btns.push(h("button", { class: "btn primary", onclick: () => openRevive(st) }, "Choose a troop"));
    if (g.pending.kind === "move" && S.ui.moveFrom != null) btns.push(h("button", { class: "btn small", onclick: () => ((S.ui.moveFrom = null), render()) }, "Back"));
    btns.push(h("button", { class: "btn ghost", onclick: () => act({ type: "skip" }) }, "Skip"));
  } else if (mine) {
    const canDraw = legal(g).some((a) => a.type === "draw");
    prompt = h("div", { class: "prompt yours" }, h("b", {}, "Your move. "), S.ui.sel != null ? `Place the ${kindName(kindOf(S.ui.sel))} on a glowing spot.` : canDraw ? "Place a troop, or draw from your bag." : "Place a troop.");
    if (S.ui.sel != null) btns.push(h("button", { class: "btn small ghost", onclick: () => ((S.ui.sel = null), render()) }, "Cancel"));
  } else if (st.status === "playing") {
    const cur = g.current;
    const name = seatName(st, cur);
    const doing = g.phase === "effect" && g.pending ? ` is using the ${(EFFECT_TEXT[g.pending.kind] || [""])[0]}` : " is thinking";
    prompt = h("div", { class: "prompt waiting" }, h("span", { class: "army-dot", style: armyStyle(cur) }), name, doing, h("span", { class: "dots" }, "…"));
  }
  const discard = g.discard;
  const top = discard.length ? discard[discard.length - 1] : null;
  return h(
    "div",
    { class: "center" },
    h("div", { class: "timer-track" }, h("div", { class: "timer-bar", id: "timer" })),
    h("div", { class: "prompt-row" }, prompt, h("div", { class: "prompt-btns" }, btns)),
    h(
      "div",
      { class: "piles" },
      h(
        "button",
        { class: "discard", id: "discard", title: "Discard: knocked-off and magnetised troops. Click to see them all", onclick: () => openDiscard(st) },
        icon("bin", "bin-ico"),
        top != null ? troopTile(top, { kinds: kinds(), cls: "discard-top" }) : null,
        h("span", { class: "pile-n" }, discard.length),
      ),
      terrainInfo(g),
    ),
    troopGuide(st),
  );
}

// Wide screens: the eight kinds at a glance (strength, name, effect) in the HUD's free space.
function troopGuide(st) {
  const side = mySide(st);
  return h(
    "div",
    { class: "guide" },
    h("div", { class: "guide-head" }, "Troops"),
    kinds().map((k) =>
      h(
        "div",
        { class: "guide-row", title: `${k.name}: ${k.text}` },
        troopTile(side * 24 + k.kind * 3, { kinds: kinds(), key: false }),
        h("div", { class: "guide-txt" }, h("b", {}, k.name), h("small", {}, k.kind === 0 ? "Joker · covers anything" : k.effect ? k.title : "No effect · strongest")),
      ),
    ),
  );
}

function terrainInfo(g) {
  const t = terrainOf(g.terrain);
  const obj = t.objective[0] === t.objective[1] ? `${t.objective[0]} medals` : `Blue ${t.objective[0]}, Red ${t.objective[1]} medals`;
  const fx = g.special && t.effect !== "none" ? FX_ICON[t.effect] : null;
  return h(
    "div",
    { class: "terrain-info" },
    fx ? icon(fx, "ti-ico") : null,
    h(
      "div",
      {},
      h("div", { class: "ti-name" }, t.name),
      h("div", {}, h("b", {}, "To win: "), `storm the enemy H.Q. or collect ${obj}.`),
      g.special && t.effect !== "none" ? h("div", {}, h("b", {}, `${t.effect_title}: `), t.effect_text) : t.effect === "none" ? h("div", {}, t.effect_text) : null,
      g.special && t.effect !== "none" ? h("div", { class: "ti-hint" }, "Tap a special base on the board to read it.") : null,
    ),
  );
}

function openDiscard(st) {
  const d = st.game.discard;
  const byside = [0, 1].map((side) => d.filter((x) => sideOf(x) === side).sort((a, b) => kindOf(a) - kindOf(b)));
  let close = null;
  close = openDialog(
    h(
      "div",
      { class: "modal" },
      h("h2", {}, "Discard"),
      d.length ? null : h("p", { class: "sub" }, "Nothing has been discarded yet."),
      byside.map((xs, side) => (xs.length ? h("div", { class: "discard-group" }, h("h4", {}, `${SIDE_COLORS[side].name} (${seatName(st, side)})`), h("div", { class: "tile-row" }, xs.map((x) => troopTile(x, { kinds: kinds(), key: false })))) : null)),
      h("div", { class: "actions" }, h("button", { class: "btn primary", onclick: () => close() }, "Close")),
    ),
  );
}

function openRevive(st) {
  const opts = legal(st.game).filter((a) => a.type === "revive");
  let close = null;
  close = openDialog(
    h(
      "div",
      { class: "modal" },
      h("h2", {}, "Old trunk"),
      h("p", { class: "sub" }, "Take one of your troops back to your rack:"),
      h(
        "div",
        { class: "tile-row pickable" },
        opts.map((a) =>
          h(
            "button",
            {
              class: "tile-btn",
              onclick: () => {
                close();
                act({ type: "revive", troop: a.troop });
              },
            },
            troopTile(a.troop, { kinds: kinds(), key: false }),
          ),
        ),
      ),
      h("div", { class: "actions" }, h("button", { class: "btn ghost", onclick: () => close() }, "Back")),
    ),
  );
}

// ------------------------------------------------------------------ input
// A tap on a base makes a move when it can; otherwise it opens (or closes) the base's explanation.
function clickNode(node) {
  if (playNode(node)) return closeInfo();
  const g = S.state?.game;
  const t = g && terrainOf(g.terrain);
  const n = t?.nodes.find((x) => x.id === node);
  const was = S.ui.info;
  closeInfo();
  if (S.ui.sel != null) S.ui.sel = null;
  if (baseInfo(g, t, n) && was !== node) S.ui.info = node;
  render();
}

function playNode(node) {
  const st = S.state;
  if (!myTurn(st) || S.ui.pending) return false;
  const g = st.game;
  const pend = g.pending?.kind;
  if (pend === "knock" || pend === "recall") {
    const a = legal(g).find((x) => x.type === pend && x.node === node);
    if (a) act(a);
    return !!a;
  }
  if (pend === "move") {
    if (S.ui.moveFrom == null) {
      if (!legal(g).some((a) => a.type === "move" && a.node === node)) return false;
      S.ui.moveFrom = node;
      sfx.select();
      render();
      return true;
    }
    const a = legal(g).find((x) => x.type === "move" && x.node === S.ui.moveFrom && x.to === node);
    if (a) act(a);
    else if (legal(g).some((x) => x.type === "move" && x.node === node)) {
      S.ui.moveFrom = node;
      render();
    } else return false;
    return true;
  }
  if (S.ui.sel != null && placeTargets(g, S.ui.sel).has(node)) {
    act({ type: "place", troop: S.ui.sel, node });
    return true;
  }
  return false;
}

function selectTroop(troop) {
  const st = S.state;
  if (!myTurn(st) || !placeable(st.game).has(troop)) return;
  S.ui.sel = S.ui.sel === troop ? null : troop;
  sfx.select();
  render();
}

function startDrag(e, troop) {
  if (e.button !== 0 && e.pointerType === "mouse") return;
  const el = e.currentTarget;
  const start = { x: e.clientX, y: e.clientY };
  let ghost = null;
  const move = (ev) => {
    const dx = ev.clientX - start.x;
    const dy = ev.clientY - start.y;
    if (!ghost && Math.hypot(dx, dy) > 7) {
      const r = el.getBoundingClientRect();
      ghost = el.cloneNode(true);
      ghost.classList.add("dragging");
      Object.assign(ghost.style, { left: `${r.left}px`, top: `${r.top}px`, width: `${r.width}px`, height: `${r.height}px` });
      document.body.append(ghost);
      if (S.ui.sel !== troop) {
        S.ui.sel = troop;
        render();
      }
    }
    if (ghost) {
      const r = el.getBoundingClientRect();
      ghost.style.transform = `translate(${ev.clientX - start.x}px, ${ev.clientY - start.y}px) scale(1.12)`;
      void r;
      const slot = document.elementsFromPoint(ev.clientX, ev.clientY).find((x) => x.classList?.contains("slot"));
      document.querySelectorAll(".slot.hover").forEach((x) => x !== slot && x.classList.remove("hover"));
      if (slot?.classList.contains("target")) slot.classList.add("hover");
    }
  };
  const up = (ev) => {
    window.removeEventListener("pointermove", move);
    window.removeEventListener("pointerup", up);
    window.removeEventListener("pointercancel", up);
    if (!ghost) {
      selectTroop(troop);
      return;
    }
    ghost.remove();
    document.querySelectorAll(".slot.hover").forEach((x) => x.classList.remove("hover"));
    const slot = document.elementsFromPoint(ev.clientX, ev.clientY).find((x) => x.classList?.contains("slot"));
    const node = slot ? Number(slot.dataset.node) : null;
    if (node != null && placeTargets(S.state.game, troop).has(node)) act({ type: "place", troop, node });
  };
  window.addEventListener("pointermove", move);
  window.addEventListener("pointerup", up);
  window.addEventListener("pointercancel", up);
}

document.addEventListener("keydown", (e) => {
  if (e.target.closest?.("input, textarea, select") || e.metaKey || e.ctrlKey || e.altKey) return;
  const st = S.state;
  if (e.key === "Escape" && closeInfo()) return;
  if (e.key === "Escape" && (S.ui.sel != null || S.ui.moveFrom != null)) {
    S.ui.sel = null;
    S.ui.moveFrom = null;
    render();
    return;
  }
  if (!myTurn(st)) return;
  const g = st.game;
  if (/^[1-8]$/.test(e.key)) {
    const troops = [...g.racks[mySide(st)].troops].sort((a, b) => kindOf(a) - kindOf(b) || a - b);
    const x = troops[Number(e.key) - 1];
    if (x != null) selectTroop(x);
  } else if (e.key.toLowerCase() === "d" && legal(g).some((a) => a.type === "draw")) act({ type: "draw" });
});

for (const ev of ["pointerdown", "keydown"]) window.addEventListener(ev, unlockAudio, { capture: true });
// a tap anywhere but on a base or the bubble closes a base's explanation
document.addEventListener("pointerdown", (e) => !e.target.closest?.(".slot, .base-info") && closeInfo());
window.addEventListener("resize", () => {
  if (S.state && S.state.status !== "lobby") render();
});

// ------------------------------------------------------------------ end of game
function renderOverlay() {
  const st = S.state;
  const over = st && st.game && st.status === "game_over";
  if (!over || performance.now() < S.ui.summaryAt) {
    if (overlay.firstChild) overlay.replaceChildren();
    return;
  }
  if (S.ui.summaryHidden) {
    morph(overlay, h("div", { class: "mini-bar" }, "🏁 Game over", h("button", { class: "btn small primary", onclick: () => ((S.ui.summaryHidden = false), renderOverlay()) }, "Show results")));
    return;
  }
  const g = st.game;
  const r = g.result;
  const me = st.you.seat;
  const isHost = st.host === S.me;
  const won = me === r.winner;
  const title = me == null ? `🏆 ${seatName(st, r.winner)} wins!` : won ? "🏆 Victory!" : `${seatName(st, r.winner)} wins`;
  const how = {
    hq: `${seatName(st, r.winner)} stormed the ${SIDE_COLORS[1 - r.winner].name} H.Q.`,
    medals: `${seatName(st, r.winner)} collected ${r.medals[r.winner]} medals.`,
    stuck: `${seatName(st, g.stuck)} could neither draw nor place: ${r.medals[0] === r.medals[1] ? "equal medals, so the stuck player loses" : "more medals wins"}.`,
  }[r.reason];
  const racks = [0, 1].map((side) => h("div", { class: "end-army", style: armyStyle(side) }, h("h4", {}, h("span", { class: "army-dot", style: armyStyle(side) }), seatName(st, side), h("span", { class: "end-medals" }, icon("medal", "inline"), ` ${r.medals[side]}`)), h("div", { class: "tile-row small" }, g.racks[side].troops.length ? g.racks[side].troops.map((x) => troopTile(x, { kinds: kinds(), key: false })) : h("small", {}, "rack empty"))));
  const actions = [
    h("button", { class: "btn ghost", onclick: () => ((S.ui.summaryHidden = true), renderOverlay()) }, "👀 Look at the board"),
    isHost ? h("button", { class: "btn", onclick: () => send({ type: "to_lobby" }) }, "Back to lobby") : null,
    isHost ? h("button", { class: "btn primary", onclick: () => send({ type: "play_again" }) }, "Rematch ↻") : h("span", { class: "grow" }, "Waiting for the host…"),
  ];
  morph(overlay, h("div", { class: "backdrop" }, h("div", { class: `modal end ${won ? "won" : ""}` }, h("h2", {}, title), h("p", { class: "sub" }, how), h("p", { class: "label" }, "Left on the racks"), h("div", { class: "end-racks" }, racks), h("div", { class: "actions" }, actions))));
}

function confetti() {
  const layer = h("div", { class: "confetti" });
  const colors = ["#ffd54a", "#2f78e0", "#e5483b", "#5dbb4a", "#ffffff", "#ff9d2e"];
  for (let i = 0; i < 90; i++) {
    layer.append(h("i", { style: { left: `${Math.random() * 100}%`, background: pick(colors), animationDuration: `${2.2 + Math.random() * 2}s`, animationDelay: `${Math.random() * 0.8}s`, transform: `rotate(${Math.random() * 360}deg)` } }));
  }
  document.body.append(layer);
  setTimeout(() => layer.remove(), 5200);
}

function showReaction(msg) {
  const st = S.state;
  const name = st?.seats.find((s) => s.member === msg.member)?.name || st?.spectators.find((s) => s.member === msg.member)?.name || "";
  let rect = msg.seat != null ? $(`.army[data-seat="${msg.seat}"]`)?.getBoundingClientRect() : null;
  if (!rect) rect = msg.seat != null ? $(`.pl-row[data-seat="${msg.seat}"]`)?.getBoundingClientRect() : null;
  if (!rect || !rect.width) rect = $("#main")?.getBoundingClientRect();
  if (!rect) return;
  const bubble = h("div", { class: "bubble", style: { left: `${rect.left + rect.width / 2 + (Math.random() - 0.5) * 40}px`, top: `${rect.top + 10}px` } }, msg.emoji, h("small", {}, name));
  document.body.append(bubble);
  setTimeout(() => bubble.remove(), 2300);
}

function tickTimer() {
  const bar = $("#timer");
  if (bar) {
    const st = S.state;
    if (S.timer.endAt && st?.status === "playing") {
      const left = Math.max(0, S.timer.endAt - performance.now());
      const frac = S.timer.total ? left / (S.timer.total * 1000) : 0;
      bar.style.width = `${(frac * 100).toFixed(2)}%`;
      bar.classList.toggle("low", left < 8000);
      if (left > 0 && left < 5000 && myTurn(st)) {
        const sec = Math.ceil(left / 1000);
        if (sec !== S.timer.lastTick) {
          S.timer.lastTick = sec;
          sfx.tick();
        }
      }
    } else bar.style.width = "0";
  }
  requestAnimationFrame(tickTimer);
}
requestAnimationFrame(tickTimer);

// ------------------------------------------------------------------ boot
async function boot() {
  installArt();
  S.config = await fetch(`${BASE}api/config`).then((r) => r.json());
  router();
}
boot().catch((e) => {
  console.error(e);
  app.replaceChildren(h("div", { class: "center-msg" }, h("p", {}, "Could not load the game. Is the server running?")));
});

