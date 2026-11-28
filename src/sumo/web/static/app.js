import { frameLoop, gameBase, leaveRoom, NAME_KEY, socketUrl, TOKEN_KEY } from "/static/shared/platform.js";
import { copyText, h, morph, openDialog, toast } from "/static/shared/dom.js";
import { BH, BW, boardSvg, cellName, installDefs, marble, neighbour, pct, screenAngle, setBoard, xy } from "./board.js";
import { showRules } from "./rules.js";
import { getVolume, isMuted, setMuted, setVolume, sfx, unlockAudio } from "./sound.js";

// The turn timer only draws frames while a timer is running (`tickTimer`, kicked after every render).
const kickTimer = frameLoop(tickTimer, () => S.timer.endAt && S.state?.status === "playing");

const BASE = gameBase(import.meta.url); // /g/<key>/: this game's server routes
const MAX_SEATS = 2;
const SUMMARY_DELAY = 1500;
const MOVE_MS = 320;
const OUT_MS = 820;
const SIDE = [
  { name: "Black", dot: "#16161c", ring: "#6b6f86" },
  { name: "White", dot: "#f4efe4", ring: "#c9b99a" },
];

const app = document.getElementById("app");
const overlay = document.getElementById("overlay");
const URL_TOKEN = takeTokenFromUrl();

const S = {
  config: { reactions: [], layouts: [], board: null, to_win: 6 },
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
  return { sel: [], drag: null, sideOpen: false, unread: 0, menu: false, summaryHidden: false, summaryAt: 0, pending: false };
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

const ADJECTIVES = ["Mighty", "Steady", "Rolling", "Iron", "Mountain", "Thunder", "Gentle", "Polished", "Heavy", "Swift"];
const NOUNS = ["Boulder", "Pebble", "Wrestler", "Marble", "Stone", "Champion", "Pusher", "Rock", "Giant", "Sumo"];
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
const seatName = (st, seat) => st.seats[seat]?.name || SIDE[seat]?.name || "?";
const botInfo = (key) => S.bots.find((b) => b.key === key);
const layoutOf = (key) => S.config.layouts.find((l) => l.key === key) || S.config.layouts[0];
// The colour drawn at the bottom of the board: yours, or Black for spectators.
const mySide = (st) => st.you.seat ?? 0;
const flipped = (st) => mySide(st) === 1;
const calm = window.matchMedia("(prefers-reduced-motion: reduce)");
const toWin = () => S.config.to_win || 6;

// ------------------------------------------------------------------ routing + socket
function router() {
  const match = location.pathname.match(/\/r\/([A-Za-z0-9]{4,8})\/?$/);
  overlay.replaceChildren();
  if (match) enterRoom(match[1].toUpperCase());
  else leaveRoom();
}
window.addEventListener("popstate", router);

function logo() {
  return h("div", { class: "logo small" }, brandMark("logo-mark"), h("span", { class: "logo-word" }, "Marble Sumo"));
}

function brandMark(cls) {
  return h("span", { class: `brand-mark ${cls}` }, marble(0, { class: "bm a" }), marble(1, { class: "bm b" }));
}

async function enterRoom(code) {
  closeSocket();
  Object.assign(S, { code, state: null, log: [], fatal: null, me: null, connected: false, retry: 0 });
  S.ui = freshUi();
  document.title = `Marble Sumo · ${code}`;
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

function act(move) {
  S.ui.sel = [];
  S.ui.pending = true;
  send({ type: "action", action: { type: "move", marbles: move.marbles, dir: move.dir } });
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
  kickTimer();
  const outMove = events.find((e) => e.kind === "move" && e.out != null);
  if (next.status !== prev?.status) {
    S.ui.summaryHidden = false;
    S.ui.summaryAt = next.status === "game_over" && prev?.status === "playing" ? performance.now() + SUMMARY_DELAY + (outMove ? OUT_MS : 0) : 0;
    if (S.ui.summaryAt) setTimeout(renderOverlay, S.ui.summaryAt - performance.now() + 20);
  }
  const fresh = next.event?.kind === "game_start";
  if (fresh) S.ui = { ...freshUi(), sideOpen: S.ui.sideOpen, unread: S.ui.unread };
  if (!myTurn(next)) S.ui.sel = [];
  else S.ui.sel = S.ui.sel.filter((c) => g.cells[c] === mySide(next));
  render();
  if (fresh && !document.hidden) {
    sfx.gong();
    setTimeout(sfx.shuffle, 250);
    dropIn();
  }
  if (before) animate(before, events, next);
  afterApply(prev, next);
}

function afterApply(prev, next) {
  if (myTurn(next) && !myTurn(prev)) {
    setTimeout(sfx.turn, 380);
    if (document.hidden) document.title = "🔔 Your move! · Marble Sumo";
  }
  if (prev?.status === "playing" && next.status === "game_over") {
    const r = next.game.result;
    const outMove = (next.event?.events || []).some((e) => e.kind === "move" && e.out != null);
    setTimeout(
      () => {
        if (r.winner == null) return;
        if (next.you.seat === r.winner) {
          sfx.fanfare();
          confetti();
        } else if (next.you.seat != null) sfx.lose();
        else sfx.gong();
      },
      outMove ? OUT_MS + 200 : 300,
    );
  }
}

document.addEventListener("visibilitychange", () => {
  if (!document.hidden && S.code) document.title = `Marble Sumo · ${S.code}`;
});

function snapshot() {
  const map = new Map();
  for (const el of document.querySelectorAll("#board .marble[data-key]")) {
    el.getAnimations().forEach((a) => a.finish());
    map.set(el.dataset.key, el.getBoundingClientRect());
  }
  return { map, board: $("#board")?.getBoundingClientRect() || null };
}

// Marbles slide to their new cells; a marble pushed over the edge rolls off, drops, and pops up in the tray.
function animate(before, events, st) {
  const ev = events.find((e) => e.kind === "move");
  if (!ev) return;
  const pushed = ev.pushed.length > 0;
  if (pushed) sfx.push(ev.marbles.length);
  else sfx.move(ev.marbles.length);
  if (calm.matches) {
    if (ev.out != null) setTimeout(sfx.out, 50);
    return;
  }
  const outId = ev.paths.find((p) => p[2] == null)?.[0];
  for (const el of document.querySelectorAll("#board .marble[data-key]")) {
    const old = before.map.get(el.dataset.key);
    if (!old) continue;
    const now = el.getBoundingClientRect();
    const dx = old.left - now.left;
    const dy = old.top - now.top;
    if (Math.abs(dx) + Math.abs(dy) < 1) continue;
    const isPushed = ev.pushed.length && ev.paths.some((p) => `m${p[0]}` === el.dataset.key && ev.pushed.includes(p[1]));
    el.animate(
      isPushed
        ? [{ transform: `translate(${dx}px, ${dy}px)` }, { transform: `translate(${dx * 0.92}px, ${dy * 0.92}px)`, offset: 0.25 }, { transform: "none" }]
        : [{ transform: `translate(${dx}px, ${dy}px)` }, { transform: "none" }],
      { duration: MOVE_MS, easing: isPushed ? "cubic-bezier(.2,.9,.3,1)" : "cubic-bezier(.35,.1,.25,1)" },
    );
  }
  if (outId != null) rollOff(before, ev, outId, st);
}

function later(ms, fn) {
  if (ms <= 0) fn();
  else setTimeout(fn, ms);
}

function rollOff(before, ev, outId, st) {
  const old = before.map.get(`m${outId}`);
  const board = $("#board")?.getBoundingClientRect();
  if (!old || !board) return;
  const flip = flipped(st);
  const ang = (screenAngle(ev.dir, flip) * Math.PI) / 180;
  const unit = board.width / BW;
  // one cell further (onto the rope), then a bit more while it drops
  const edge = { x: Math.cos(ang) * Math.sqrt(3) * unit, y: Math.sin(ang) * Math.sqrt(3) * unit };
  const fall = { x: edge.x * 1.45, y: edge.y * 1.45 + unit * 0.6 };
  const side = Math.floor(outId / (S.config.marbles || 14));
  const ghost = marble(side, { class: "ghost" });
  Object.assign(ghost.style, { left: `${old.left}px`, top: `${old.top}px`, width: `${old.width}px`, height: `${old.height}px` });
  document.body.append(ghost);
  const anim = ghost.animate(
    [
      { transform: "none", opacity: 1 },
      { transform: `translate(${edge.x * 0.55}px, ${edge.y * 0.55}px)`, opacity: 1, offset: 0.28 },
      { transform: `translate(${edge.x}px, ${edge.y}px) scale(1.04)`, opacity: 1, offset: 0.48 },
      { transform: `translate(${fall.x}px, ${fall.y}px) scale(0.55)`, opacity: 0.0 },
    ],
    { duration: OUT_MS, easing: "cubic-bezier(.4,.1,.6,1)", fill: "both" },
  );
  anim.onfinish = () => ghost.remove();
  setTimeout(sfx.out, 40);
  later(OUT_MS * 0.55, () => $("#board")?.animate([{ transform: "none" }, { transform: "translate(-3px, 2px)" }, { transform: "translate(3px, -1px)" }, { transform: "none" }], { duration: 260 }));
  const tray = document.querySelector(`.tray .marble[data-key="t${outId}"]`);
  if (tray) {
    tray.animate([{ transform: "scale(0)", opacity: 0 }, { transform: "scale(0)", opacity: 0, offset: 0.7 }, { transform: "scale(1.35)", opacity: 1, offset: 0.88 }, { transform: "none", opacity: 1 }], { duration: OUT_MS + 300, easing: "ease-out" });
    later(OUT_MS + 120, () => tray.closest(".tray")?.animate([{ boxShadow: "0 0 0 0 rgba(255,210,120,0)" }, { boxShadow: "0 0 0 6px rgba(255,210,120,0.35)" }, { boxShadow: "0 0 0 0 rgba(255,210,120,0)" }], { duration: 600 }));
  }
}

// The opening: marbles drop onto their dimples, Black's side first.
function dropIn() {
  if (calm.matches) return;
  const els = [...document.querySelectorAll("#board .marble[data-key]")];
  els.forEach((el, i) => {
    el.animate([{ transform: "translateY(-40%) scale(1.3)", opacity: 0 }, { transform: "none", opacity: 1 }], { duration: 300, delay: 30 + i * 18, easing: "cubic-bezier(.3,1.4,.5,1)", fill: "backwards" });
  });
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
      h("main", { class: "main", id: "main" }, h("div", { class: "center-msg" }, h("p", {}, "Sweeping the ring…"))),
      h(
        "aside",
        { class: "side", id: "side" },
        h("div", { class: "players", id: "players" }),
        h("div", { class: "side-head" }, "Match log", h("button", { class: "icon-btn only-narrow", onclick: toggleSide, title: "Close" }, "✕")),
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
  const dot = side != null ? h("span", { class: `who m${side}` }) : null;
  return h("div", { class: "entry log", title: time }, dot, entry.text);
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
  const label = h("span", { class: "vol-pct" });
  const sync = () => {
    const vol = getVolume();
    const off = isMuted() || vol === 0;
    btn.textContent = off ? "🔇" : vol < 0.4 ? "🔉" : "🔊";
    btn.title = off ? "Sound off. Click to turn on" : "Click to mute";
    range.value = String(Math.round(vol * 100));
    label.textContent = off ? "off" : `${Math.round(vol * 100)}%`;
  };
  btn.addEventListener("click", () => {
    unlockAudio();
    if (isMuted() || getVolume() === 0) {
      setMuted(false);
      if (getVolume() === 0) setVolume(0.8);
      sync();
      sfx.select();
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
  const wrap = h("div", { class: "vol", onpointerenter: place, onfocusin: place }, btn, h("div", { class: "vol-pop" }, h("span", {}, "🔈"), range, label));
  return wrap;
})();

function renderTop() {
  const top = $("#topbar");
  if (!top) return;
  const st = S.state;
  const g = st?.game;
  let info = "";
  if (st?.status === "lobby") info = "Lobby";
  else if (g) info = `${layoutOf(g.layout).name} · move ${g.turn + (g.current == null ? 0 : 1)}${g.move_limit ? ` of ${g.move_limit * 2}` : ""}`;
  const before = [
    h("span", { class: "brand", title: "Leave", onclick: leaveTable }, brandMark("brand-mark-top"), h("span", { class: "brand-word" }, "Marble Sumo")),
    h("span", { class: "chip code", title: "Copy table code", onclick: copyCode }, "📋 ", S.code),
    h("button", { class: "btn primary small invite-btn", title: `Copy the invite link (${inviteUrl()})`, onclick: copyInvite }, "🔗 ", h("span", { class: "invite-label" }, "Copy invite link")),
    h("span", { class: "round-info" }, info),
    h("span", { class: "spacer" }),
    iconBtn("📖", "Rule book", () => showRules(S.config)),
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
  const seated = st?.you.seat != null;
  return h(
    "div",
    { class: "menu", id: "menu" },
    item("📖 Rule book", () => showRules(S.config)),
    item("📱 Continue on another device", async () => {
      const url = `${inviteUrl()}?me=${S.token}`;
      const ok = await copyText(url);
      toast(ok ? "Personal link copied. Open it on your other device (don't share it!)" : url, !ok);
    }),
    item("✏️ Change my name", async () => {
      const name = await askName("Change your name", true);
      if (name) send({ type: "rename", name });
    }),
    seated && st?.status === "playing" ? item("🏳 Resign this game", confirmResign) : null,
    isHost && st?.status !== "lobby"
      ? item("⏹ End game, back to lobby", () => {
          if (confirm("End the current game for everyone?")) send({ type: "to_lobby" });
        })
      : null,
    item("🚪 Leave table", leaveTable),
  );
}

function confirmResign() {
  if (confirm("Resign this game? Your opponent wins.")) send({ type: "resign" });
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
    close = openDialog(h("div", { class: "modal" }, h("h2", {}, title), h("p", { class: "sub" }, "Pick a name your opponent will see."), h("form", { onsubmit: done }, input, h("div", { class: "actions" }, h("button", { class: "btn primary", type: "submit" }, "Into the ring!")))), { dismissable, onClose: () => resolve(null) });
    input.focus();
  });
}

// ------------------------------------------------------------------ render
function render() {
  renderView();
  kickTimer();
}

function renderView() {
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
  const label = bot ? "🤖" : (seat.name || "?").trim().charAt(0).toUpperCase();
  return h("span", { class: `avatar m${seat.seat} ${bot ? "" : online ? "online" : "offline"}` }, label);
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
      h("div", { class: "pl-id" }, h("span", { class: "pl-name" }, s.name, s.member === st.host ? h("small", {}, " · host") : null), h("span", { class: "pl-sub" }, `${SIDE[i].name} · ${sub}`)),
      isHost && !s.bot && !s.connected && st.status === "playing" ? h("button", { class: "btn small", onclick: () => send({ type: "autoplay", seat: i, on: !s.autoplay }) }, s.autoplay ? "Wait" : "Bot plays") : null,
      g ? h("span", { class: "pl-score", title: "Rival marbles pushed out" }, `${g.out[1 - i]}/${toWin()}`) : null,
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

  const card = (l) => {
    const on = set.layout === l.key;
    return h(
      "button",
      { class: `layout-card ${on ? "on" : ""}`, "data-key": `layout-${l.key}`, disabled: !isHost && !on, "aria-pressed": on ? "true" : "false", title: l.blurb, onclick: () => isHost && change("layout", l.key) },
      h("div", { class: "mini-board" }, boardSvg({ mini: true, layout: l, cls: "mini-svg" })),
      h("div", { class: "lc-text" }, h("span", { class: "lc-name" }, l.name), h("span", { class: "lc-blurb" }, l.blurb)),
      l.key === "classic" ? h("span", { class: "lc-tag" }, "first game") : null,
    );
  };
  const random = h(
    "button",
    { class: `layout-card random ${set.layout === "random" ? "on" : ""}`, "data-key": "layout-random", disabled: !isHost && set.layout !== "random", onclick: () => isHost && change("layout", "random") },
    h("div", { class: "mini-board dice" }, "🎲"),
    h("div", { class: "lc-text" }, h("span", { class: "lc-name" }, "Surprise me"), h("span", { class: "lc-blurb" }, "One of the three openings, drawn at the start.")),
  );
  const layouts = h(
    "section",
    { class: "panel layouts-panel" },
    h("h3", {}, "Opening", isHost ? h("small", {}, "pick the starting position") : h("small", {}, "chosen by the host")),
    h("div", { class: "layout-grid" }, S.config.layouts.map(card), random),
  );

  const seatRows = [];
  for (let i = 0; i < MAX_SEATS; i++) {
    const s = st.seats[i];
    if (i === 1) seatRows.push(h("div", { class: "versus-line" }, "VS"));
    if (!s) {
      seatRows.push(h("div", { class: `seat-empty s${i}` }, h("span", { class: `side-dot m${i}` }), `${SIDE[i].name}: empty seat`, mySeat == null ? h("button", { class: "btn small primary", onclick: () => send({ type: "sit" }) }, "Take it") : null));
      continue;
    }
    const bot = s.bot ? botInfo(s.bot) : null;
    const isMe = i === mySeat;
    seatRows.push(
      h(
        "div",
        { class: `seat-row s${i}` },
        marble(i, { class: "seat-marble" }),
        h("div", { class: "seat-id" }, h("span", { class: "name" }, s.name), h("span", { class: "side-name" }, i === 0 ? "Black · moves first" : "White")),
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
    h("h3", {}, "Wrestlers", h("small", {}, `${n} / ${MAX_SEATS}`)),
    h("div", { class: "seat-list" }, seatRows),
    isHost ? h("div", { class: "seat-tools" }, h("button", { class: "btn small", disabled: n < 2, onclick: () => send({ type: "swap" }) }, "🔀 Swap colours")) : null,
    spectators.length ? h("p", { class: "waiting" }, "Watching: ", spectators.map((s) => s.name).join(", ")) : null,
  );
  const botsPanel = h(
    "section",
    { class: "panel" },
    h("h3", {}, "Play against a bot", isHost ? null : h("small", {}, "host only")),
    h(
      "div",
      { class: "bot-grid" },
      S.bots.map((b) =>
        h(
          "button",
          { class: "bot-btn", "data-key": `bot-${b.key}`, disabled: !isHost || n >= MAX_SEATS, title: b.description, onclick: () => send({ type: "add_bot", bot: b.key }) },
          h("span", { class: "bot-face" }, "🤖"),
          h("span", { class: "bot-txt" }, h("span", { class: "bname" }, b.label, " ", h("span", { class: "stars" }, "★".repeat(b.stars))), h("span", { class: "bdesc" }, b.description)),
        ),
      ),
    ),
  );
  const select = (k, options) =>
    h(
      "select",
      { class: "select", "data-setting": k, disabled: !isHost, onchange: (e) => change(k, isNaN(Number(e.target.value)) ? e.target.value : Number(e.target.value)) },
      options.map(([value, label]) => {
        const opt = h("option", { value }, label);
        opt.selected = String(set[k]) === String(value);
        return opt;
      }),
    );
  const row = (label, help, control) => h("div", { class: "setting" }, h("span", { class: "label" }, label, h("small", {}, help)), control);
  const settingsPanel = h(
    "section",
    { class: "panel" },
    h("h3", {}, "Ring rules", isHost ? null : h("small", {}, "set by the host")),
    h(
      "div",
      { class: "settings" },
      row("Move limit", "After that many moves each, fewer marbles lost wins", select("move_limit", (S.config.move_limits || [0]).map((v) => [v, v ? `${v} each` : "None"]))),
      row(
        "Turn timer",
        "The autopilot moves for you when time runs out",
        select("turn_timer", [
          [0, "Off"],
          [30, "30 s"],
          [60, "1 min"],
          [120, "2 min"],
          [300, "5 min"],
        ]),
      ),
      row(
        "Bot speed",
        "How quickly the bots move",
        select("bot_speed", [
          ["slow", "Relaxed"],
          ["normal", "Normal"],
          ["fast", "Fast"],
        ]),
      ),
    ),
  );
  const actions = isHost
    ? h("div", { class: "lobby-actions" }, h("button", { class: "btn ghost", onclick: () => showRules(S.config) }, "📖 Rule book"), h("button", { class: "btn primary big", disabled: n < 2, onclick: () => send({ type: "start" }) }, n < 2 ? "Waiting for an opponent" : "⚫ Into the ring!"))
    : h("div", { class: "lobby-actions" }, h("button", { class: "btn ghost", onclick: () => showRules(S.config) }, "📖 Rule book"), h("span", { class: "waiting" }, `Waiting for ${hostName} to start the game…`));
  morph(main, h("section", { class: "lobby", id: "lobby" }, layouts, h("div", { class: "lobby-grid" }, h("div", { class: "lobby-col" }, seatsPanel, botsPanel), settingsPanel), actions));
}

// ------------------------------------------------------------------ moves
const legal = (g) => g.legal || [];
function myTurn(st) {
  return !!st && st.status === "playing" && st.game && st.game.current === st.you.seat && legal(st.game).length > 0;
}
const setKey = (cells) => [...cells].sort((a, b) => a - b).join(",");
const movesFor = (g, sel) => {
  const key = setKey(sel);
  return legal(g).filter((m) => setKey(m.marbles) === key);
};

// The marble of `group` furthest along d (the head of an inline move).
function headOf(group, d) {
  return group.find((c) => !group.includes(neighbour(c, d)));
}

function isInline(m) {
  if (m.marbles.length === 1) return true;
  const [a, b] = [...m.marbles].sort((x, y) => x - y);
  return neighbour(a, m.dir) === b || neighbour(b, m.dir) === a || neighbour(neighbour(a, m.dir), m.dir) === b || neighbour(neighbour(b, m.dir), m.dir) === a;
}

// Cells a tap can use to make a move of the selection: where the head lands (inline), or any landing cell (sideways).
function landingMap(g, sel) {
  const map = new Map();
  const add = (c, m) => {
    if (c < 0) return;
    if (map.has(c) && map.get(c) !== m) map.set(c, null);
    else map.set(c, m);
  };
  for (const m of movesFor(g, sel)) {
    if (isInline(m)) add(neighbour(headOf(m.marbles, m.dir), m.dir), m);
    else for (const c of m.marbles) add(neighbour(c, m.dir), m);
  }
  for (const [c, m] of [...map]) if (!m) map.delete(c);
  return map;
}

// Own marbles in a straight line of 1–3 (the selection can be any such line, even one that can't move).
function isLine(cells) {
  if (cells.length <= 1) return true;
  if (cells.length > 3) return false;
  for (let d = 0; d < 3; d++) {
    for (const start of cells) {
      const run = [start];
      while (run.length < cells.length) run.push(neighbour(run[run.length - 1], d));
      if (run.every((c) => cells.includes(c))) return true;
    }
  }
  return false;
}

function clickMarble(cell) {
  const st = S.state;
  if (!myTurn(st) || S.ui.pending) return;
  const g = st.game;
  const me = mySide(st);
  let sel = S.ui.sel;
  if (g.cells[cell] !== me) return;
  if (sel.includes(cell)) {
    const rest = sel.filter((c) => c !== cell);
    sel = isLine(rest) ? rest : [cell]; // dropping the middle of three keeps just the tapped one
    sfx.deselect();
  } else {
    let cand = [...sel, cell];
    if (sel.length === 1) {
      // two apart in a line with an own marble between: take all three
      for (let d = 0; d < 6; d++) {
        const mid = neighbour(sel[0], d);
        if (mid >= 0 && neighbour(mid, d) === cell && g.cells[mid] === me) cand = [sel[0], mid, cell];
      }
    }
    sel = cand.length <= 3 && isLine(cand) ? cand : [cell];
    sfx.select();
  }
  S.ui.sel = sel;
  render();
}

function clickCell(cell) {
  const st = S.state;
  if (!myTurn(st) || S.ui.pending) return;
  const g = st.game;
  if (S.ui.sel.length) {
    const m = landingMap(g, S.ui.sel).get(cell);
    if (m) return act(m);
  }
  if (g.cells[cell] === mySide(st)) return clickMarble(cell);
  if (S.ui.sel.length) {
    S.ui.sel = [];
    sfx.deselect();
    render();
  }
}

// Drag a marble: with a selection that contains it, the selection moves; otherwise the marble and the own marbles
// right ahead of it in that direction move together (an inline push, if rivals are in the way).
function startDrag(e, cell) {
  if (e.button !== 0 && e.pointerType === "mouse") return;
  const st = S.state;
  if (!myTurn(st) || S.ui.pending) return;
  const g = st.game;
  const me = mySide(st);
  if (g.cells[cell] !== me) return;
  e.preventDefault();
  const start = { x: e.clientX, y: e.clientY };
  const flip = flipped(st);
  let dragging = false;
  let move = null;
  const groupFor = (d) => {
    if (S.ui.sel.includes(cell)) {
      const m = movesFor(g, S.ui.sel).find((x) => x.dir === d);
      if (m) return m;
    }
    const run = [cell];
    while (run.length < 3) {
      const n = neighbour(run[run.length - 1], d);
      if (n < 0 || g.cells[n] !== me) break;
      run.push(n);
    }
    return movesFor(g, run).find((x) => x.dir === d) || null;
  };
  const onMove = (ev) => {
    const dx = ev.clientX - start.x;
    const dy = ev.clientY - start.y;
    const dist = Math.hypot(dx, dy);
    const board = $("#board")?.getBoundingClientRect();
    const threshold = board ? Math.max(10, (board.width / BW) * 0.7) : 14;
    if (dist < threshold) {
      if (dragging) setPreview(null);
      dragging = false;
      move = null;
      return;
    }
    dragging = true;
    const ang = (Math.atan2(dy, dx) * 180) / Math.PI;
    let best = 0;
    let bestDiff = 999;
    for (let d = 0; d < 6; d++) {
      const diff = Math.abs(((ang - screenAngle(d, flip) + 540) % 360) - 180);
      if (diff < bestDiff) {
        bestDiff = diff;
        best = d;
      }
    }
    move = groupFor(best);
    setPreview(move, best, cell);
  };
  const onUp = () => {
    window.removeEventListener("pointermove", onMove);
    window.removeEventListener("pointerup", onUp);
    window.removeEventListener("pointercancel", onUp);
    setPreview(null);
    if (!dragging) return clickCell(cell);
    if (move) act(move);
    else sfx.error();
  };
  window.addEventListener("pointermove", onMove);
  window.addEventListener("pointerup", onUp);
  window.addEventListener("pointercancel", onUp);
}

// While dragging: the marbles that would move glow, an arrow shows the direction (red if no such move).
function setPreview(m, d = null, cell = null) {
  document.querySelectorAll("#board .cell.preview").forEach((x) => x.classList.remove("preview"));
  $("#drag-arrow")?.remove();
  if (d == null) return;
  const st = S.state;
  const flip = flipped(st);
  const group = m ? m.marbles : [cell];
  for (const c of group) document.querySelector(`#board .cell[data-cell="${c}"]`)?.classList.add("preview");
  const head = headOf(group, d) ?? cell;
  const p = xy(head, flip);
  const ang = screenAngle(d, flip);
  const at = { x: p.x + Math.cos((ang * Math.PI) / 180) * 1.25, y: p.y + Math.sin((ang * Math.PI) / 180) * 1.25 };
  const q = pct(at);
  $("#board .arrows")?.append(h("div", { id: "drag-arrow", class: `drag-arrow ${m ? "" : "bad"}`, style: { left: `${q.left}%`, top: `${q.top}%`, "--rot": `${ang}deg` } }, "➜"));
}

document.addEventListener("keydown", (e) => {
  if (e.target.closest?.("input, textarea, select") || e.metaKey || e.ctrlKey || e.altKey) return;
  if (e.key === "Escape" && S.ui.sel.length) {
    S.ui.sel = [];
    render();
  }
});

for (const ev of ["pointerdown", "keydown"]) window.addEventListener(ev, unlockAudio, { capture: true });
window.addEventListener("resize", () => {
  if (S.state && S.state.status !== "lobby") render();
});

// ------------------------------------------------------------------ game
function layoutMode(main) {
  const r = main.getBoundingClientRect();
  const aspect = BW / BH;
  const wide = r.width / Math.max(1, r.height) > 1.2 && r.width >= 640;
  if (wide) {
    const hud = Math.min(380, Math.max(250, r.width * 0.32));
    const bw = Math.min(r.width - hud - 36, (r.height - 20) * aspect);
    return { mode: "wide", bw: Math.max(240, bw), hud };
  }
  const reserve = 64 + 64 + 64 + 30;
  const bw = Math.min(r.width - 12, (r.height - reserve) * aspect, 760);
  return { mode: "tall", bw: Math.max(220, bw), hud: Math.min(r.width - 12, 640) };
}

function renderGame(st, main) {
  const me = mySide(st);
  const lay = layoutMode(main);
  const view = h(
    "div",
    { class: `game ${lay.mode}`, id: "game", style: { "--bw": `${lay.bw}px`, "--hud": `${lay.hud}px` } },
    h("div", { class: "board-wrap" }, renderBoard(st)),
    h("div", { class: "hud" }, playerPanel(st, 1 - me, false), centerPanel(st), playerPanel(st, me, true)),
  );
  morph(main, view);
}

function renderBoard(st) {
  const g = st.game;
  const flip = flipped(st);
  const me = mySide(st);
  const mine = myTurn(st) && !S.ui.pending;
  const sel = S.ui.sel;
  const usable = new Set(mine ? legal(g).flatMap((m) => m.marbles) : []);
  const landing = mine && sel.length ? landingMap(g, sel) : new Map();
  const last = g.last;
  const lastFrom = new Set();
  const lastTo = new Set();
  if (last && last.kind === "move") {
    for (const [, from, to] of last.paths) {
      if (!last.pushed.includes(from)) lastFrom.add(from);
      if (to != null) lastTo.add(to);
    }
    for (const [, , to] of last.paths) lastFrom.delete(to);
  }
  const size = (Math.sqrt(3) * 0.9 * 100) / BW; // marble diameter in % of the board width
  const cellSize = (Math.sqrt(3) * 100) / BW;
  const marbles = [];
  const cells = [];
  const marks = [];
  for (let c = 0; c < g.cells.length; c++) {
    const p = pct(xy(c, flip));
    const pos = { left: `${p.left}%`, top: `${p.top}%` };
    const v = g.cells[c];
    if (v >= 0) marbles.push(marble(v, { "data-key": `m${g.ids[c]}`, "data-cell": c, class: [lastTo.has(c) ? "last" : "", sel.includes(c) ? "sel" : ""].filter(Boolean).join(" "), style: pos }));
    if (lastFrom.has(c) && v < 0) marks.push(h("div", { class: "from-mark", "data-key": `f${c}`, style: pos }));
    const land = landing.get(c);
    const cls = ["cell", usable.has(c) ? "usable" : "", sel.includes(c) ? "sel" : "", land ? (v >= 0 && v !== me ? "target push" : "target") : ""].filter(Boolean).join(" ");
    cells.push(
      h("div", {
        class: cls,
        "data-cell": c,
        title: cellName(c),
        style: pos,
        onpointerdown: (e) => (g.cells[c] === me && mine ? startDrag(e, c) : null),
        onclick: (e) => {
          if (g.cells[c] === me && mine) return; // handled by the pointer events (tap or drag)
          e.preventDefault();
          clickCell(c);
        },
      }),
    );
  }
  const arrows = mine && sel.length ? directionArrows(g, sel, flip) : [];
  return h(
    "div",
    { class: `board ${mine ? "my-turn" : ""}`, id: "board", style: { "--msize": `${size}%`, "--csize": `${cellSize}%` } },
    boardSvg({ flip, cls: "board-svg" }),
    h("div", { class: "marks" }, marks),
    h("div", { class: "marbles" }, marbles),
    h("div", { class: "cells" }, cells),
    h("div", { class: "arrows" }, arrows),
  );
}

// One arrow per direction the selection can move in, just beyond the selection on that side.
function directionArrows(g, sel, flip) {
  const pts = sel.map((c) => xy(c, flip));
  const cx = pts.reduce((a, p) => a + p.x, 0) / pts.length;
  const cy = pts.reduce((a, p) => a + p.y, 0) / pts.length;
  return movesFor(g, sel).map((m) => {
    const ang = screenAngle(m.dir, flip);
    const ux = Math.cos((ang * Math.PI) / 180);
    const uy = Math.sin((ang * Math.PI) / 180);
    const reach = Math.max(...pts.map((p) => (p.x - cx) * ux + (p.y - cy) * uy));
    const at = pct({ x: cx + ux * (reach + 1.0), y: cy + uy * (reach + 1.0) });
    const push = m.marbles.length > 1 && isInline(m) && g.cells[neighbour(headOf(m.marbles, m.dir), m.dir)] >= 0;
    return h(
      "button",
      { class: `dir-arrow ${push ? "push" : ""}`, "data-key": `a${m.dir}`, "data-dir": m.dir, title: push ? "Push" : "Move", style: { left: `${at.left}%`, top: `${at.top}%`, "--rot": `${ang}deg` }, onclick: () => act(m) },
      h("span", {}, "➜"),
    );
  });
}

function playerPanel(st, side, bottom) {
  const g = st.game;
  const seat = st.seats[side];
  const isYou = st.you.seat === side;
  const current = st.status === "playing" && g.current === side;
  const status = seat ? (seat.bot ? `bot ${"★".repeat(botInfo(seat.bot)?.stars || 0)}` : seat.autoplay ? "autopilot" : seat.connected ? "" : "offline") : "";
  const won = g.lost[1 - side];
  const slots = [];
  for (let i = 0; i < toWin(); i++) {
    const id = won[i];
    slots.push(h("div", { class: "socket", "data-key": `s${side}-${i}` }, id != null ? marble(1 - side, { "data-key": `t${id}` }) : null));
  }
  return h(
    "div",
    { class: `player ${bottom ? "mine" : "theirs"} s${side} ${current ? "current" : ""}`, "data-seat": side },
    h(
      "div",
      { class: "player-head" },
      marble(side, { class: "head-marble" }),
      h(
        "span",
        { class: "player-name" },
        seat?.name || SIDE[side].name,
        isYou ? h("small", {}, " (you)") : null,
        status ? h("small", {}, ` · ${status}`) : null,
        current && !isYou ? h("span", { class: "thinking" }, h("i"), h("i"), h("i")) : null,
      ),
      h("span", { class: "score", title: `${won.length} of ${toWin()} rival marbles pushed out` }, h("b", {}, won.length), h("small", {}, `/${toWin()}`)),
    ),
    h("div", { class: "tray", title: "Rival marbles pushed out" }, slots),
  );
}

function centerPanel(st) {
  const g = st.game;
  const mine = myTurn(st);
  let prompt;
  const btns = [];
  if (st.status === "game_over") {
    const r = g.result;
    let text;
    if (r.winner == null) text = h("b", {}, "🤝 A draw.");
    else text = h("b", {}, st.you.seat === r.winner ? "🏆 You win!" : `🏆 ${seatName(st, r.winner)} wins!`);
    prompt = h("div", { class: "prompt over" }, text, " ", r.reason === "resign" ? "By resignation." : r.reason === "limit" ? "The move limit was reached." : "Six marbles out.");
    btns.push(h("button", { class: "btn small primary", onclick: () => ((S.ui.summaryHidden = false), (S.ui.summaryAt = 0), renderOverlay()) }, "Results"));
  } else if (mine) {
    const sel = S.ui.sel;
    let text;
    if (!sel.length) text = "Pick one to three of your marbles in a line, then a direction. Or drag a marble.";
    else if (movesFor(g, sel).length) text = "Tap an arrow or a glowing spot to move. Add a marble in line to move more.";
    else text = "These can't move together. Add a neighbour in line, or pick other marbles.";
    prompt = h("div", { class: "prompt yours" }, h("b", {}, "Your move. "), text);
    if (sel.length) btns.push(h("button", { class: "btn small ghost", onclick: () => ((S.ui.sel = []), render()) }, "Clear"));
  } else if (st.status === "playing") {
    const cur = g.current;
    prompt = h("div", { class: "prompt waiting" }, h("span", { class: `side-dot m${cur}` }), seatName(st, cur), " is thinking", h("span", { class: "dots" }, "…"));
  }
  const lay = layoutOf(g.layout);
  const moves = g.turn;
  return h(
    "div",
    { class: "center" },
    h("div", { class: "timer-track" }, h("div", { class: "timer-bar", id: "timer" })),
    h("div", { class: "prompt-row" }, prompt, h("div", { class: "prompt-btns" }, btns)),
    h(
      "div",
      { class: "info-card" },
      h("div", { class: "ic-row" }, h("b", {}, lay.name), h("span", {}, g.move_limit ? `${moves} of ${g.move_limit * 2} moves` : `${moves} ${moves === 1 ? "move" : "moves"}`)),
      h(
        "ul",
        { class: "ic-help" },
        h("li", {}, "Move 1–3 marbles in a line one step: along the line or sideways."),
        h("li", {}, "Push rivals along your line when you outnumber them: 2 → 1, 3 → 1 or 2."),
        h("li", {}, `First to push ${toWin()} rival marbles out of the ring wins.`),
      ),
    ),
  );
}

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
  const won = me != null && me === r.winner;
  let title;
  if (r.winner == null) title = "🤝 A draw";
  else if (me == null) title = `🏆 ${seatName(st, r.winner)} wins!`;
  else title = won ? "🏆 Victory!" : `${seatName(st, r.winner)} wins`;
  const how =
    r.winner == null
      ? `The move limit came with ${r.out[0]} to ${r.out[1]} marbles out.`
      : {
          push: `${seatName(st, r.winner)} pushed ${toWin()} ${SIDE[1 - r.winner].name.toLowerCase()} marbles out of the ring in ${g.turn} moves.`,
          resign: `${seatName(st, 1 - r.winner)} resigned.`,
          limit: `The move limit came: ${seatName(st, r.winner)} lost fewer marbles (${r.out[r.winner]} to ${r.out[1 - r.winner]}).`,
        }[r.reason];
  const sides = [0, 1].map((side) =>
    h(
      "div",
      { class: `end-side s${side}` },
      marble(side, { class: "end-marble" }),
      h("div", { class: "end-name" }, seatName(st, side), h("small", {}, SIDE[side].name)),
      h("div", { class: "end-score" }, h("b", {}, g.out[1 - side]), h("small", {}, " pushed out")),
    ),
  );
  const actions = [
    h("button", { class: "btn ghost", onclick: () => ((S.ui.summaryHidden = true), renderOverlay()) }, "👀 Look at the ring"),
    isHost ? h("button", { class: "btn", onclick: () => send({ type: "to_lobby" }) }, "Back to lobby") : null,
    isHost ? h("button", { class: "btn primary", onclick: () => send({ type: "play_again" }) }, "Rematch ↻") : h("span", { class: "grow" }, "Waiting for the host…"),
  ];
  morph(overlay, h("div", { class: "backdrop" }, h("div", { class: `modal end ${won ? "won" : ""}` }, h("h2", {}, title), h("p", { class: "sub" }, how), h("div", { class: "end-sides" }, sides), h("div", { class: "actions" }, actions))));
}

function confetti() {
  const layer = h("div", { class: "confetti" });
  const colors = ["#f2c14e", "#16161c", "#f4efe4", "#c8763a", "#e5484d", "#ffffff"];
  for (let i = 0; i < 90; i++) {
    layer.append(h("i", { style: { left: `${Math.random() * 100}%`, background: pick(colors), animationDuration: `${2.2 + Math.random() * 2}s`, animationDelay: `${Math.random() * 0.8}s`, transform: `rotate(${Math.random() * 360}deg)` } }));
  }
  document.body.append(layer);
  setTimeout(() => layer.remove(), 5200);
}

function showReaction(msg) {
  const st = S.state;
  const name = st?.seats.find((s) => s.member === msg.member)?.name || st?.spectators.find((s) => s.member === msg.member)?.name || "";
  let rect = msg.seat != null ? $(`.player[data-seat="${msg.seat}"]`)?.getBoundingClientRect() : null;
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
}

// ------------------------------------------------------------------ boot
async function boot() {
  S.config = await fetch(`${BASE}api/config`).then((r) => r.json());
  setBoard(S.config.board);
  installDefs();
  router();
}
boot().catch((e) => {
  console.error(e);
  app.replaceChildren(h("div", { class: "center-msg" }, h("p", {}, "Could not load the game. Is the server running?")));
});
