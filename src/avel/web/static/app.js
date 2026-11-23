import { NAME_KEY, TOKEN_KEY, gameBase, leaveRoom, socketUrl } from "/static/shared/platform.js";
import {
  HERO_FILL,
  coinIcon,
  die,
  faceIcon,
  heartIcon,
  heroAvatar,
  heroFigure,
  installSprite,
  itemArt,
  itemIcon,
  monsterBadge,
  richText,
  symbolIcon,
} from "./art.js";
import { Board, key as hexKey } from "./board.js";
import { copyText, h, openDialog, s, toast } from "./dom.js";
import { vista } from "./scenery.js";

const BASE = gameBase(import.meta.url); // /g/<key>/: this game's server routes

const app = document.getElementById("app");
const overlay = document.getElementById("overlay");
const URL_TOKEN = takeTokenFromUrl();

const S = {
  cat: { tiles: {}, monsters: {}, equipment: {}, craters: {}, traps: {}, moon_track: [] },
  bots: [],
  token: URL_TOKEN || localStorage.getItem(TOKEN_KEY) || newToken(),
  name: localStorage.getItem(NAME_KEY) || "",
  code: null,
  ws: null,
  retry: 0,
  reconnectTimer: null,
  connected: false,
  fatal: null,
  me: null,
  log: [],
  state: null,
  board: null,
  ui: freshUi(),
};
localStorage.setItem(TOKEN_KEY, S.token);
window.__avel = S;

function freshUi() {
  return {
    mode: null, // {kind: "reroll", item, picked: []} | {kind: "seal"} | {kind: "trap", level}
    split: null, // spells counted as swords (null = suggested)
    rolling: false,
    pending: false,
    tab: "party",
    unread: 0,
    summaryClosed: false,
    hint: null,
    lastGame: 0,
  };
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

const ADJ = ["Brave", "Bold", "Silver", "Swift", "Merry", "Iron", "Wise", "Lucky", "Gentle", "Wild"];
const NOUN = ["Ranger", "Knight", "Bard", "Druid", "Archer", "Squire", "Warden", "Seeker", "Shieldmaiden", "Wanderer"];
const pick = (xs) => xs[Math.floor(Math.random() * xs.length)];
const suggestName = () => `${pick(ADJ)} ${pick(NOUN)}`;

function saveName(name) {
  name = (name || "").trim().slice(0, 20);
  if (!name) return S.name;
  S.name = name;
  localStorage.setItem(NAME_KEY, name);
  return name;
}

const $ = (sel) => document.querySelector(sel);
const plural = (n, w) => `${n} ${n === 1 ? w : `${w}s`}`;
const game = () => S.state?.game || null;
const mySeat = () => S.state?.you?.seat ?? null;
const legal = () => game()?.legal || [];
const ofType = (type) => legal().filter((a) => a.type === type);
const hexEq = (a, b) => a && b && a[0] === b[0] && a[1] === b[1];
const itemName = (key) => S.cat.equipment[key]?.name || key;
const monsterName = (key) => S.cat.monsters[key]?.name || key;
const tileAt = (g, hex) => g.tiles.find((t) => hexEq(t.hex, hex));
const tileName = (g, hex) => {
  const t = tileAt(g, hex);
  return t?.key ? S.cat.tiles[t.key].name : "an unexplored tile";
};

function canon(v) {
  if (Array.isArray(v)) return v.map(canon);
  if (v && typeof v === "object") {
    const out = {};
    for (const k of Object.keys(v).sort()) out[k] = canon(v[k]);
    return out;
  }
  return v;
}
const same = (a, b) => JSON.stringify(canon(a)) === JSON.stringify(canon(b));
const isLegal = (a) => legal().some((x) => same(x, a));
const findLegal = (pred) => legal().find(pred);

// ------------------------------------------------------------------ routing

function router() {
  const match = location.pathname.match(/\/r\/([A-Za-z0-9]{4,8})\/?$/);
  overlay.replaceChildren();
  if (match) enterRoom(match[1].toUpperCase());
  else leaveRoom();
}
window.addEventListener("popstate", router);

// ------------------------------------------------------------------ home
function logo(small = false) {
  return h(
    "div",
    { class: `logo${small ? " small" : ""}` },
    h("span", { class: "logo-top" }, "Chronicles of"),
    h("span", { class: "logo-word" }, "Avel"),
  );
}


// ------------------------------------------------------------------ room / socket
function askName(title) {
  return new Promise((resolve) => {
    const input = h("input", { class: "text", value: S.name, placeholder: suggestName(), maxlength: 20 });
    let close = () => {};
    const ok = () => {
      saveName(input.value || input.placeholder);
      close();
      resolve();
    };
    input.addEventListener("keydown", (e) => e.key === "Enter" && ok());
    close = openDialog(
      h("div", { class: "dialog" }, h("h2", {}, title), h("label", { class: "field" }, "Your name", input), h("div", { class: "dialog-actions" }, h("button", { class: "btn primary", onclick: ok }, "Join"))),
      { dismissable: false },
    );
  });
}

async function enterRoom(code) {
  closeSocket();
  Object.assign(S, { code, state: null, log: [], fatal: null, me: null, connected: false, retry: 0 });
  S.ui = freshUi();
  S.board = null;
  document.title = `Avel · ${code}`;
  if (!S.name && !URL_TOKEN) await askName(`Join table ${code}`);
  buildShell();
  connect();
}

function connect() {
  const proto = location.protocol === "https:" ? "wss" : "ws";
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
  S.ui.hint = null;
  S.ui.mode = null;
  S.ui.pending = true;
  send({ type: "action", action });
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
      if (S.ui.tab !== "log" && msg.entry.kind === "chat") {
        S.ui.unread++;
        renderTabs();
      }
      break;
    case "react":
      showReaction(msg);
      break;
    case "hint":
      S.ui.hint = msg.action;
      toast(h("span", { class: "toast-hint" }, bulbIcon(16), describeAction(msg.action)), false, "hint");
      render();
      break;
    case "error":
      S.ui.pending = false;
      toast(msg.message, true);
      render();
      break;
    case "fatal":
      S.fatal = msg.message;
      app.replaceChildren(
        h(
          "div",
          { class: "home" },
          h("div", { class: "home-card small" }, h("div", { class: "home-banner short" }, vista("lost"), logo(true)), h("p", { class: "tagline" }, msg.message), h("div", { class: "home-form" }, h("button", { class: "btn primary", onclick: () => leaveRoom() }, "Back home"))),
        ),
      );
      break;
  }
}

function applyState(msg) {
  const prev = S.state;
  S.state = msg;
  S.ui.pending = false;
  S.ui.hint = null;
  const g = msg.game;
  const ev = msg.event;
  if (!g || prev?.game?.phase !== g.phase || prev?.game?.actor !== g.actor) {
    S.ui.mode = null;
    S.ui.split = null;
  }
  if (msg.status === "playing" && prev?.status !== "playing") {
    S.ui.summaryClosed = false;
    closeAllDialogs();
  }
  if (ev?.kind === "move") {
    const kinds = ev.events.map((e) => e.kind);
    if (kinds.includes("roll") || kinds.includes("reroll")) {
      S.ui.rolling = true;
      S.ui.split = null;
      setTimeout(() => {
        S.ui.rolling = false;
        document.querySelectorAll(".dice-tray .die.rolling").forEach((d) => d.classList.remove("rolling"));
      }, 700);
    }
    for (const e of ev.events) flashEvent(e, g);
  }
  render();
}

function closeAllDialogs() {
  document.querySelectorAll(".backdrop").forEach((b) => b.remove());
}

// ------------------------------------------------------------------ shell
function buildShell() {
  app.replaceChildren(
    h(
      "div",
      { class: "shell" },
      h(
        "header",
        { class: "topbar" },
        h("button", { class: "brand", onclick: () => leaveRoom(), title: "Leave the table" }, symbolIcon("black_moon", 26), h("span", {}, "Avel")),
        h("button", { class: "chip code", id: "code-chip", title: "Copy the invite link", onclick: copyInvite }, S.code),
        h("span", { class: "round-info", id: "round-info" }),
        h("span", { class: "spacer" }),
        h("span", { class: "conn", id: "conn" }),
        h("button", { class: "icon-btn", title: "How to play", onclick: showRules }, "?"),
        h("button", { class: "icon-btn side-toggle", id: "side-toggle", title: "Party & log", onclick: toggleSide }, "☰", h("span", { class: "badge-dot hidden", id: "side-dot" })),
      ),
      h("main", { class: "main", id: "main" }),
      h(
        "aside",
        { class: "side", id: "side" },
        h("div", { class: "tabs", id: "tabs" }),
        h("div", { class: "side-body", id: "side-body" }, h("div", { class: "party", id: "party" }), h("div", { class: "feed-wrap", id: "feed-wrap" }, h("div", { class: "feed", id: "feed" }), chatForm())),
      ),
    ),
  );
  renderTabs();
  renderFeed();
}

function toggleSide() {
  document.body.classList.toggle("side-open");
}

function chatForm() {
  const input = h("input", { class: "text", placeholder: "Say something…", maxlength: 240, "aria-label": "Chat message" });
  const sendChat = (e) => {
    e.preventDefault();
    const text = input.value.trim();
    if (!text) return;
    send({ type: "chat", text });
    input.value = "";
  };
  return h("form", { class: "chat-form", onsubmit: sendChat }, input, h("button", { class: "btn small", type: "submit" }, "Send"));
}

function renderTabs() {
  const tabs = $("#tabs");
  if (!tabs) return;
  const setTab = (t) => {
    S.ui.tab = t;
    if (t === "log") S.ui.unread = 0;
    renderTabs();
  };
  tabs.replaceChildren(
    h("button", { class: `tab${S.ui.tab === "party" ? " on" : ""}`, onclick: () => setTab("party") }, "Party"),
    h("button", { class: `tab${S.ui.tab === "log" ? " on" : ""}`, onclick: () => setTab("log") }, "Chronicle", S.ui.unread ? h("span", { class: "count" }, S.ui.unread) : null),
  );
  $("#side")?.setAttribute("data-tab", S.ui.tab);
  $("#side-dot")?.classList.toggle("hidden", !S.ui.unread);
}

async function copyInvite() {
  const url = `${location.origin}/r/${S.code}`;
  if (await copyText(url)) toast("Invite link copied");
  else toast(url);
}

function renderConn() {
  const el = $("#conn");
  if (!el) return;
  el.textContent = S.connected ? "" : "Reconnecting…";
  el.className = `conn${S.connected ? "" : " bad"}`;
}

// ------------------------------------------------------------------ feed
function renderFeed() {
  const feed = $("#feed");
  if (!feed) return;
  feed.replaceChildren(...S.log.map(feedEntry));
  feed.scrollTop = feed.scrollHeight;
}

function appendFeed(entry) {
  const feed = $("#feed");
  if (!feed) return;
  const atBottom = feed.scrollHeight - feed.scrollTop - feed.clientHeight < 40;
  feed.append(feedEntry(entry));
  while (feed.children.length > 500) feed.firstChild.remove();
  if (atBottom) feed.scrollTop = feed.scrollHeight;
}

const elixirKey = () => Object.values(S.cat.equipment).find((e) => e.kind === "elixir")?.key;
const LOG_ICON = {
  "🛡": () => shieldMark(16),
  "🗺": () => symbolIcon("shortcut", 16),
  "👹": () => symbolIcon("lair", 16),
  "⚔️": () => faceIcon("sword", 15, "#e8c065"),
  "🧪": () => (elixirKey() ? itemIcon(elixirKey(), "elixir", 17) : heartIcon(15)),
  "🎲": () => die("green", "sword", 16),
  "💥": () => symbolIcon("trap", 16),
  "🏆": () => starIcon(16),
  "🎁": () => symbolIcon("bag", 16),
  "🏃": () => symbolIcon("boot", 16),
  "💫": () => heartIcon(15, false),
  "🏕": () => heartIcon(15),
  "💰": () => coinIcon(16),
  "🛒": () => symbolIcon("bag", 16),
  "🌙": () => symbolIcon("seal", 16),
  "🧱": () => symbolIcon("wall", 16),
  "🪤": () => symbolIcon("trap", 16),
  "🔨": () => symbolIcon("hammer", 16),
  "✨": () => symbolIcon("upgrade", 16),
  "🪙": () => symbolIcon("wish", 16),
  "🤝": () => coinIcon(16),
  "🌘": () => symbolIcon("moon", 16),
  "🐲": () => monsterBadge("beast", S.cat.monsters.beast, 20),
  "👣": () => symbolIcon("boot", 16),
  "🏰": () => symbolIcon("wall", 16),
  "🎉": () => starIcon(16),
  "☠️": () => symbolIcon("black_moon", 18),
};

function starIcon(size = 16) {
  return s(
    "svg",
    { width: size, height: size, viewBox: "0 0 100 100", class: "ico", "aria-hidden": "true" },
    s("path", { d: "M50 4 L62 34 L95 36 L69 57 L78 90 L50 72 L22 90 L31 57 L5 36 L38 34 Z", fill: "#f6c638", stroke: "#1d130c", "stroke-width": 7, "stroke-linejoin": "round" }),
  );
}

function feedEntry(e) {
  const seats = S.state?.seats || [];
  const color = e.seat !== null && e.seat !== undefined ? seats[e.seat]?.color : null;
  if (e.kind === "chat") return h("div", { class: "entry chat" }, h("b", {}, e.name), ": ", e.text);
  const round = /^— Round/.test(e.text);
  let text = e.text;
  let icon = null;
  const lead = text.match(/^(\S+)\s/);
  if (lead && LOG_ICON[lead[1]]) {
    icon = h("span", { class: "log-ico" }, LOG_ICON[lead[1]]());
    text = text.slice(lead[0].length);
  }
  return h(
    "div",
    { class: `entry log${round ? " round" : ""}${icon ? " has-ico" : ""}` },
    color ? h("span", { class: "who", style: { "--hc": HERO_FILL[color] } }) : null,
    icon,
    h("span", { class: "log-text" }, richText(text, S.cat)),
  );
}

function showReaction(msg) {
  const el = h("div", { class: "reaction-pop" }, msg.emoji);
  document.body.append(el);
  setTimeout(() => el.remove(), 1600);
}

// ------------------------------------------------------------------ render
function render() {
  const st = S.state;
  if (!st) return;
  renderTop();
  const main = $("#main");
  if (!main) return;
  if (st.status === "lobby" || !st.game) {
    document.body.classList.remove("in-game");
    renderLobby(main);
  } else {
    document.body.classList.add("in-game");
    renderGame(main);
  }
  renderParty();
}

function renderTop() {
  const info = $("#round-info");
  const g = game();
  if (!info) return;
  if (!g || S.state.status === "lobby") {
    info.textContent = "Lobby";
    return;
  }
  const left = S.cat.moon_track.length - 1 - g.moon;
  const bits = [`Round ${g.round}`];
  bits.push(g.beast_out ? "The Beast is out!" : left === 1 ? "Black Moon next round" : `Black Moon in ${left} rounds`);
  info.textContent = bits.join(" · ");
}

// ------------------------------------------------------------------ lobby
function renderLobby(main) {
  const st = S.state;
  const isHost = st.host === S.me;
  const seated = st.you.seat !== null;
  const url = `${location.origin}/r/${S.code}`;
  const seatCards = st.seats.map((seat, i) =>
    h(
      "div",
      { class: `seat-card${seat.member === S.me ? " mine" : ""}${!seat.connected ? " away" : ""}`, style: { "--hc": HERO_FILL[seat.color] } },
      h("div", { class: "seat-order", title: i === 0 ? "Holds the coat of arms: starts every round and steers the monsters" : `Plays ${ordinal(i + 1)}` }, i === 0 ? shieldMark(18) : i + 1),
      h("div", { class: "seat-stage" }, heroFigure(seat.color, 92)),
      h("div", { class: "seat-name" }, seat.name),
      h(
        "div",
        { class: "seat-tags" },
        seat.bot ? h("span", { class: "tag" }, "bot") : null,
        seat.member === st.host ? h("span", { class: "tag host" }, "host") : null,
        seat.member === S.me ? h("span", { class: "tag you" }, "you") : null,
        !seat.connected ? h("span", { class: "tag off" }, "away") : null,
      ),
      isHost && (seat.bot || seat.member !== S.me) ? h("button", { class: "seat-remove", title: "Remove", "aria-label": `Remove ${seat.name}`, onclick: () => send({ type: "remove_seat", seat: i }) }, "×") : null,
    ),
  );
  for (let i = st.seats.length; i < 4; i++) {
    const sit = !seated && i === st.seats.length;
    seatCards.push(
      h(
        sit ? "button" : "div",
        { class: `seat-card empty${sit ? " sit" : ""}`, onclick: sit ? () => send({ type: "sit" }) : null },
        h("div", { class: "seat-stage" }, heroFigure("stone", 92)),
        h("div", { class: "seat-name" }, sit ? "Take this seat" : "Free seat"),
      ),
    );
  }
  const settings = st.settings;
  const crater = S.cat.craters[settings.crater];
  const setting = (k, v) => send({ type: "settings", changes: { [k]: v } });
  const seg = (k, options, label) =>
    h(
      "div",
      { class: "seg", role: "group", "aria-label": label },
      options.map(([v, text]) => h("button", { class: `seg-btn${settings[k] === v ? " on" : ""}`, disabled: !isHost, "aria-pressed": settings[k] === v ? "true" : "false", onclick: () => setting(k, v) }, text)),
    );
  const craters = h(
    "div",
    { class: "crater-pick", role: "group", "aria-label": "Crater difficulty" },
    Object.values(S.cat.craters).map((c) =>
      h(
        "button",
        { class: `crater-opt${c.key === settings.crater ? " on" : ""}`, disabled: !isHost, "aria-pressed": c.key === settings.crater ? "true" : "false", onclick: () => setting("crater", c.key) },
        symbolIcon("crater", 44),
        h("span", { class: "crater-name" }, c.name),
        h("span", { class: "flames" }, Array.from({ length: c.flames }, () => flameIcon(12))),
      ),
    ),
  );
  const n = Math.max(1, st.seats.length);
  const craterNote = crater ? craterText(crater, n) : "";
  main.replaceChildren(
    h(
      "div",
      { class: "lobby" },
      h(
        "section",
        { class: "invite panel" },
        h("div", { class: "invite-text" }, h("h2", {}, "Gather your party"), h("p", {}, "Send this link to friends — or fill the seats with bots. Everyone plays together against the Beast.")),
        h("div", { class: "link-box" }, h("input", { class: "text", value: url, readonly: true, onclick: (e) => e.target.select(), "aria-label": "Invite link" }), h("button", { class: "btn", onclick: copyInvite }, "Copy link")),
      ),
      h(
        "div",
        { class: "lobby-grid" },
        h(
          "section",
          { class: "panel heroes-panel" },
          h("h3", {}, "Heroes", h("small", {}, `${st.seats.length}/4`)),
          h("div", { class: "seat-list" }, seatCards),
          h(
            "div",
            { class: "seat-buttons" },
            seated ? h("button", { class: "btn small ghost", onclick: () => send({ type: "stand" }) }, "Stand up") : null,
            isHost && st.seats.length > 1 ? h("button", { class: "btn small ghost", onclick: () => send({ type: "shuffle" }) }, "Shuffle order") : null,
          ),
          isHost
            ? h(
                "div",
                { class: "bot-block" },
                h("h4", {}, "Add a bot companion"),
                h(
                  "div",
                  { class: "bot-grid" },
                  S.bots.map((b) =>
                    h(
                      "button",
                      { class: "bot-btn", disabled: st.seats.length >= 4, onclick: () => send({ type: "add_bot", bot: b.key }) },
                      h("span", { class: "bname" }, h("span", { class: "plus" }, "+"), b.label),
                      h("span", { class: "stars", title: `${b.stars} of 3` }, Array.from({ length: 3 }, (_, i) => h("span", { class: i < b.stars ? "on" : "" }, "★"))),
                      h("span", { class: "bdesc" }, b.description),
                    ),
                  ),
                ),
              )
            : null,
        ),
        h(
          "section",
          { class: "panel settings-panel" },
          h("h3", {}, "Table settings", isHost ? null : h("small", {}, "the host decides")),
          h("div", { class: "field" }, h("span", { class: "field-label" }, "Crater token · difficulty"), craters),
          h("p", { class: "note crater-note" }, craterNote),
          h(
            "div",
            { class: "field" },
            h("span", { class: "field-label" }, "Bot speed"),
            seg(
              "bot_speed",
              ["slow", "normal", "fast"].map((v) => [v, v]),
              "Bot speed",
            ),
          ),
          h(
            "div",
            { class: "field" },
            h("span", { class: "field-label" }, "Turn timer"),
            seg(
              "turn_timer",
              [0, 60, 120, 300].map((v) => [v, v ? `${v / 60} min` : "off"]),
              "Turn timer",
            ),
          ),
          h(
            "label",
            { class: "switch" },
            h("input", { type: "checkbox", checked: settings.hints, disabled: !isHost, onchange: (e) => setting("hints", e.target.checked) }),
            h("span", { class: "switch-track" }),
            h("span", {}, "Allow hints — ask a bot for advice"),
          ),
          h(
            "div",
            { class: "start-row" },
            isHost
              ? h("button", { class: "btn primary big", disabled: !st.seats.length, onclick: () => send({ type: "start" }) }, faceIcon("sword", 20), "Begin the adventure")
              : h("p", { class: "note waiting" }, "Waiting for the host to start…"),
          ),
          h("p", { class: "note center" }, n === 1 ? "Solo: you get 4 actions per turn." : `${n} heroes, 2 actions each per turn. The Black Moon rises after ${n >= 3 ? 10 : 12} rounds.`),
        ),
      ),
    ),
  );
}

const ordinal = (n) => `${n}${{ 1: "st", 2: "nd", 3: "rd" }[n] || "th"}`;

function shieldMark(size = 16) {
  return s(
    "svg",
    { width: size, height: size, viewBox: "0 0 100 100", class: "ico", "aria-hidden": "true" },
    s("path", { d: "M50 6 L88 18 Q88 66 50 94 Q12 66 12 18 Z", fill: "#2f7066", stroke: "#1d130c", "stroke-width": 7, "stroke-linejoin": "round" }),
    s("path", { d: "M50 18 L76 26 Q76 60 50 80 Q24 60 24 26 Z", fill: "none", stroke: "#e8c065", "stroke-width": 6 }),
    s("path", { d: "M50 30 L56 44 H70 L58 52 L62 66 L50 58 L38 66 L42 52 L30 44 H44 Z", fill: "#e8c065" }),
  );
}

function flameIcon(size = 12) {
  return s(
    "svg",
    { width: size, height: size, viewBox: "0 0 100 100", class: "ico flame", "aria-hidden": "true" },
    s("path", { d: "M50 4 Q60 30 76 44 Q92 62 80 82 Q68 98 50 98 Q30 98 20 82 Q10 62 28 44 Q34 58 42 58 Q34 30 50 4 Z", fill: "#ff7a2a", stroke: "#1d130c", "stroke-width": 6, "stroke-linejoin": "round" }),
    s("path", { d: "M50 52 Q60 66 62 76 Q62 90 50 90 Q38 90 38 78 Q40 66 50 52 Z", fill: "#ffe07a" }),
  );
}

function craterText(c, n) {
  const sizes = c.monsters[String(n)] || [];
  const who = sizes.length ? sizes.map((x) => `a ${x} monster`).join(" and ") : "no extra monsters";
  return `When the Black Moon rises the crater releases ${who} for ${plural(n, "hero")}, plus the Beast (toughness ${S.cat.beast_toughness[n]}).`;
}

// ------------------------------------------------------------------ game screen
function renderGame(main) {
  const g = game();
  let root = main.querySelector(".game");
  if (!root) {
    S.board = new Board({ onHex, onMonster, onLair, onHero });
    root = h(
      "div",
      { class: "game" },
      h("section", { class: "stage", id: "stage" }, h("div", { class: "moonbar", id: "moonbar" }), h("div", { class: "board-wrap", id: "board-wrap" }, S.board.el), h("div", { class: "battle-layer", id: "battle-layer" })),
      h("section", { class: "dock", id: "dock" }, h("div", { class: "prompt", id: "prompt" }), h("div", { class: "myboard", id: "myboard" })),
    );
    main.replaceChildren(root);
  }
  renderMoon(g);
  S.board.update(g, S.cat, boardUi(g));
  renderBattle(g);
  renderPrompt(g);
  renderMyBoard(g);
  renderSummary(g);
}

function boardUi(g) {
  const me = mySeat();
  const ui = { targets: new Map(), monsters: new Set(), lairs: new Set(), current: g.phase === "game_over" ? null : g.current, me };
  const mode = S.ui.mode;
  if (mode?.kind === "seal") {
    for (const a of ofType("seal")) ui.lairs.add(`${a.at[0]},${a.at[1]},${a.lair}`);
    return ui;
  }
  if (mode?.kind === "trap") {
    for (const a of ofType("trap")) if (a.level === mode.level) ui.targets.set(hexKey(a.at), { kind: "trap", label: "trap", action: a });
    return ui;
  }
  if (g.phase === "steer") {
    for (const a of ofType("steer")) ui.targets.set(hexKey(a.to), { kind: "steer", label: "here", action: a });
    if (g.march?.monster) ui.focus = hexKey(g.monsters.find((m) => m.id === g.march.monster)?.hex || [99, 99]);
    return ui;
  }
  if (g.phase === "turn") {
    const hero = g.heroes[me];
    for (const a of ofType("move")) {
      const isNeighbour = hero && isAdjacent(hero.hex, a.to);
      ui.targets.set(hexKey(a.to), { kind: "move", label: isNeighbour ? "" : "shortcut", action: a });
    }
    for (const a of ofType("battle")) ui.monsters.add(a.monster);
  }
  if (S.ui.hint?.type === "move") {
    const t = ui.targets.get(hexKey(S.ui.hint.to));
    if (t) t.kind = "move hinted";
  }
  return ui;
}

function isAdjacent(a, b) {
  const dc = b[0] - a[0];
  const dr = b[1] - a[1];
  return (dc === 0 && Math.abs(dr) === 2) || (Math.abs(dc) === 1 && Math.abs(dr) === 1);
}

function onHex(hex, target) {
  if (target?.action) return act(target.action);
  showTileInfo(hex);
}

function onMonster(id, selectable) {
  const a = ofType("battle").find((x) => x.monster === id);
  if (selectable && a) return act(a);
  const g = game();
  const m = g.monsters.find((x) => x.id === id);
  if (m) showMonsterInfo(m);
}

function onLair(hex, lair) {
  const a = ofType("seal").find((x) => hexEq(x.at, hex) && x.lair === lair);
  if (a) act(a);
}

function onHero(seat) {
  showHeroDialog(seat);
}

// ------------------------------------------------------------------ moon track
const MOON_TITLE = { start: "Start", spawn: "Monsters appear in empty lairs", heal: "Every hero heals 1", black_moon: "The Black Moon: the Beast appears" };

function renderMoon(g) {
  const bar = $("#moonbar");
  const track = S.cat.moon_track;
  const start = S.cat.moon_start[g.n];
  const spaces = track.map((sym, i) => {
    const here = i === g.moon;
    const past = i < g.moon;
    const skipped = i < start;
    let icon;
    if (sym === "spawn") icon = symbolIcon("lair", 22);
    else if (sym === "heal") icon = heartIcon(20);
    else if (sym === "black_moon") icon = symbolIcon("black_moon", 30);
    else icon = h("span", { class: "moon-dot" });
    const marks = [];
    if (i === S.cat.last_seal_space + 1) marks.push(h("span", { class: "lost-mark", title: "Seals are gone once the astrolabe gets here" }, symbolIcon("seal", 12)));
    if (i === S.cat.last_trap_space + 1) marks.push(h("span", { class: "lost-mark", title: "Traps are gone once the astrolabe gets here" }, symbolIcon("trap", 12)));
    const startMark = Object.entries(S.cat.moon_start)
      .filter(([, v]) => v === i)
      .map(([k]) => k);
    return h(
      "div",
      { class: `moon-space ${sym}${here ? " here" : ""}${past ? " past" : ""}${skipped ? " skipped" : ""}`, title: MOON_TITLE[sym] || "" },
      icon,
      marks,
      startMark.length && i > 0 ? h("span", { class: "start-mark", title: `Start for ${startMark.join(" or ")} heroes` }, startMark.length > 1 ? `${startMark[0]}–${startMark[startMark.length - 1]}` : startMark[0]) : null,
      here ? h("span", { class: "astrolabe" }) : null,
    );
  });
  const beast = g.monsters.find((m) => m.key === "beast");
  const beastInfo = S.cat.monsters.beast;
  const status = g.beast_out
    ? beast
      ? h(
          "div",
          { class: "beast-bar", title: "The Beast's toughness" },
          monsterBadge("beast", beastInfo, 34),
          h("div", { class: "bar" }, h("div", { class: "fill", style: { width: `${(100 * (beast.toughness - beast.damage)) / beast.toughness}%` } })),
          h("b", {}, `${beast.toughness - beast.damage}/${beast.toughness}`),
        )
      : h("div", { class: "beast-bar slain" }, monsterBadge("beast", beastInfo, 34), h("b", {}, "slain"))
    : null;
  const stat = (title, icon, value, extra) => h("span", { class: "stat", title }, icon, h("b", {}, value), extra ? h("small", {}, extra) : null);
  const stats = h(
    "div",
    { class: "moon-stats" },
    stat("Walls standing at the castle / left to build", symbolIcon("wall", 20), g.walls, g.walls_allowed ? `+${g.walls_left}` : ""),
    stat("Moon seals left", symbolIcon("seal", 20), g.seals_allowed ? g.seals_left : "–"),
    stat("Traps placed", symbolIcon("trap", 20), `${Object.values(g.traps).filter(Boolean).length}/3`),
    stat("Equipment tokens in the bag", symbolIcon("bag", 20), g.bag),
  );
  bar.replaceChildren(...[h("div", { class: "moon-track" }, h("div", { class: "moon-ribbon" }, spaces)), status, stats].filter(Boolean));
}

// ------------------------------------------------------------------ prompt (what you can do now)
function renderPrompt(g) {
  const el = $("#prompt");
  const me = mySeat();
  const st = S.state;
  const actor = g.actor;
  const mine = actor === me && me !== null && st.status === "playing" && legal().length > 0;
  const name = (seat) => st.seats[seat]?.name || "?";
  const parts = [];
  let title = "";
  let sub = "";
  const buttons = [];
  const timer = g.time_left !== null && g.time_left !== undefined ? timerBar(g) : null;

  if (g.phase === "game_over") {
    title = g.result?.won ? "Victory!" : "Defeat";
    sub = g.result?.won ? `Avel is saved after ${g.result.rounds} rounds.` : `The castle fell in round ${g.result?.rounds}.`;
    if (st.host === S.me) {
      buttons.push(h("button", { class: "btn primary", onclick: () => send({ type: "play_again" }) }, "Play again"));
      buttons.push(h("button", { class: "btn", onclick: () => send({ type: "to_lobby" }) }, "Back to lobby"));
    }
  } else if (!mine) {
    const who = name(actor);
    const what = {
      turn: `${who} is taking their turn`,
      prepare: `${who} prepares for battle`,
      clash: `${who} is in battle`,
      after_clash: `${who} decides whether to fight on`,
      choose_upgrade: `${who} picks an item to upgrade`,
      overflow: `${who} is repacking their backpack`,
      stun_loss: `${who} picks an item to lose`,
      steer: `${who} steers the marching monsters`,
    }[g.phase];
    title = what || "Waiting…";
    sub = me === null ? "You are watching this game." : "Wait for your turn — you can look around the map and your backpack meanwhile.";
    if (g.phase === "turn") parts.push(actionPips(g));
  } else {
    switch (g.phase) {
      case "turn":
        promptTurn(g, buttons, parts);
        title = g.actions_left > 0 ? "Your turn" : "No actions left";
        sub = g.actions_left > 0 ? "Click a glowing tile to move, or choose an action." : "Finish with free moves (equip, trade, drink) or end your turn.";
        break;
      case "prepare":
      case "clash":
      case "after_clash":
        title = "Battle!";
        sub = "Use the battle panel on the map.";
        break;
      case "choose_upgrade":
        title = "Free upgrade";
        sub = "Choose the item to flip to its upgraded side.";
        for (const a of ofType("choose_upgrade")) buttons.push(itemChoiceButton(g, a.item, () => act(a), true));
        break;
      case "overflow": {
        title = "Your backpack overflows";
        sub = "Discard items or coins (or move gear on/off your hero) until everything fits.";
        const coin = findLegal((a) => a.type === "discard" && a.coins === 1);
        if (coin) buttons.push(h("button", { class: "btn", onclick: () => act(coin) }, "Drop 1 ", coinIcon(14)));
        for (const a of ofType("discard").filter((x) => x.item)) buttons.push(itemChoiceButton(g, a.item, () => act(a), false, "Drop"));
        const done = findLegal((a) => a.type === "done");
        if (done) buttons.push(h("button", { class: "btn primary", onclick: () => act(done) }, "Done"));
        break;
      }
      case "stun_loss":
        title = "Stunned!";
        sub = "You wake up in the castle, fully healed, without your coins. Choose one item to lose.";
        for (const a of ofType("lose")) buttons.push(itemChoiceButton(g, a.item, () => act(a), false, "Lose"));
        break;
      case "steer": {
        const m = g.monsters.find((x) => x.id === g.march?.monster);
        title = `Steer the ${m ? monsterName(m.key) : "monster"}`;
        sub = "It has several shortest paths to the castle. Click a glowing tile.";
        for (const a of ofType("steer")) buttons.push(h("button", { class: "btn", onclick: () => act(a) }, tileName(g, a.to)));
        break;
      }
    }
    if (st.settings.hints && g.phase !== "game_over") buttons.push(hintButton());
  }
  const actorHero = g.heroes[actor];
  const face = g.phase === "game_over" ? symbolIcon(g.result?.won ? "wall" : "black_moon", 44) : actorHero ? heroAvatar(actorHero.color, 48) : null;
  el.replaceChildren(
    h(
      "div",
      { class: `prompt-card${mine ? " mine" : ""}${g.phase === "game_over" ? (g.result?.won ? " won" : " lost") : ""}` },
      h("div", { class: "prompt-head" }, face ? h("span", { class: "prompt-face" }, face) : null, h("div", { class: "prompt-title" }, h("h2", {}, title), sub ? h("p", { class: "sub" }, sub) : null), parts),
      timer,
      buttons.length ? h("div", { class: "prompt-buttons" }, buttons) : null,
    ),
  );
}

function hintButton() {
  return h("button", { class: "btn ghost small hint-btn", title: "Ask a bot for advice", onclick: () => send({ type: "hint" }) }, bulbIcon(15), "Hint");
}

function bulbIcon(size = 14) {
  return s(
    "svg",
    { width: size, height: size, viewBox: "0 0 100 100", class: "ico", "aria-hidden": "true" },
    s("path", { d: "M50 6 Q80 6 82 36 Q82 52 68 64 V76 H32 V64 Q18 52 18 36 Q20 6 50 6 Z", fill: "#f6dc8c", stroke: "#1d130c", "stroke-width": 6, "stroke-linejoin": "round" }),
    s("path", { d: "M34 84 H66 M38 94 H62", stroke: "#1d130c", "stroke-width": 7, "stroke-linecap": "round" }),
    s("path", { d: "M34 32 Q38 20 50 18", stroke: "#fff", "stroke-width": 6, fill: "none", "stroke-linecap": "round" }),
  );
}

function timerBar(g) {
  const pct = Math.max(0, Math.min(100, (100 * g.time_left) / (g.time_total || 1)));
  return h("div", { class: "timer" }, h("div", { class: "fill", style: { width: `${pct}%` } }), h("span", {}, `${Math.ceil(g.time_left)}s`));
}

function actionPips(g) {
  const pips = [];
  for (let i = 0; i < g.per_turn; i++) pips.push(h("span", { class: `pip${i < g.actions_left ? " on" : ""}` }));
  return h("span", { class: "pips", title: `${g.actions_left} of ${g.per_turn} actions left` }, pips);
}

const TILE_ACTION_TEXT = {
  market: "Sell items for 2 coins, buy random equipment for 3 (2 transactions).",
  seal: "Pay 3 coins to seal an empty lair: no monster spawns there again.",
  wall: "Pay 3 coins to build a wall fragment in front of the castle.",
  trap: "Pay 3, 5 or 7 coins to set a trap for the Beast on a face-up tile.",
  work: "Earn 2 coins (only if no monster is here).",
  upgrade: "Pay 3 coins to flip one of your items to its upgraded side.",
  wish: "Pay 1 coin and roll 2 green dice: two swords 4 coins, sword+shield equipment, two shields an upgrade.",
};

function promptTurn(g, buttons, parts) {
  parts.push(actionPips(g));
  const hint = S.ui.hint;
  const hinted = (a) => (hint && same(hint, a) ? " hint" : "");
  if (S.ui.mode?.kind === "seal") {
    buttons.push(h("span", { class: "mode-note" }, "Click a glowing lair on the map to seal it."));
    buttons.push(h("button", { class: "btn", onclick: () => setMode(null) }, "Cancel"));
    return;
  }
  if (S.ui.mode?.kind === "trap") {
    buttons.push(h("span", { class: "mode-note" }, `Click a glowing tile to place the level ${S.ui.mode.level} trap.`));
    buttons.push(h("button", { class: "btn", onclick: () => setMode(null) }, "Cancel"));
    return;
  }
  for (const a of ofType("battle")) {
    const m = g.monsters.find((x) => x.id === a.monster);
    const info = m ? S.cat.monsters[m.key] : null;
    buttons.push(h("button", { class: `btn battle${hinted(a)}`, onclick: () => act(a) }, info ? monsterBadge(m.key, info, 30) : faceIcon("sword", 18), h("span", {}, "Battle ", h("b", {}, info ? info.name : "monster"))));
  }
  const cost = (n) => h("span", { class: "cost" }, n, coinIcon(15));
  const market = ofType("market");
  if (market.length) buttons.push(h("button", { class: `btn${hint?.type === "market" ? " hint" : ""}`, onclick: openMarket, title: TILE_ACTION_TEXT.market }, symbolIcon("bag", 20), "Market…"));
  if (ofType("seal").length) buttons.push(h("button", { class: `btn${hint?.type === "seal" ? " hint" : ""}`, onclick: () => setMode({ kind: "seal" }), title: TILE_ACTION_TEXT.seal }, symbolIcon("seal", 20), "Seal a lair", cost(3)));
  const wall = findLegal((a) => a.type === "wall");
  if (wall) buttons.push(h("button", { class: `btn${hinted(wall)}`, onclick: () => act(wall), title: TILE_ACTION_TEXT.wall }, symbolIcon("wall", 20), "Build a wall", cost(3)));
  if (ofType("trap").length) buttons.push(h("button", { class: `btn${hint?.type === "trap" ? " hint" : ""}`, onclick: openTrap, title: TILE_ACTION_TEXT.trap }, symbolIcon("trap", 20), "Set a trap…"));
  const work = findLegal((a) => a.type === "work");
  if (work) buttons.push(h("button", { class: `btn${hinted(work)}`, onclick: () => act(work), title: TILE_ACTION_TEXT.work }, symbolIcon("hammer", 20), "Work", h("span", { class: "cost gain" }, "+2", coinIcon(15))));
  if (ofType("upgrade").length) buttons.push(h("button", { class: `btn${hint?.type === "upgrade" ? " hint" : ""}`, onclick: openAlchemist, title: TILE_ACTION_TEXT.upgrade }, symbolIcon("upgrade", 20), "Upgrade an item…"));
  const wish = findLegal((a) => a.type === "wish");
  if (wish) buttons.push(h("button", { class: `btn${hinted(wish)}`, onclick: () => act(wish), title: TILE_ACTION_TEXT.wish }, symbolIcon("wish", 20), "Make a wish", cost(1)));
  const rest = findLegal((a) => a.type === "rest");
  if (rest) buttons.push(h("button", { class: `btn${hinted(rest)}`, onclick: () => act(rest), title: "Heal up to 2 toughness" }, heartIcon(18), "Rest", h("span", { class: "cost gain" }, "+2", heartIcon(14))));
  const heal = ofType("drink")[0];
  if (heal) {
    const it = game().items[heal.item];
    buttons.push(h("button", { class: `btn${hinted(heal)}`, onclick: () => act(heal), title: "Free: heal to full" }, it ? itemIcon(it.key, it.kind, 22) : null, "Drink healing elixir"));
  }
  const end = findLegal((a) => a.type === "end_turn");
  if (end) buttons.push(h("button", { class: `btn ${g.actions_left === 0 ? "primary" : "end"}${hinted(end)}`, onclick: () => confirmEnd(g, end) }, "End turn"));
}

function confirmEnd(g, end) {
  if (g.actions_left > 0 && !confirm(`You still have ${plural(g.actions_left, "action")}. End your turn anyway?`)) return;
  act(end);
}

function setMode(mode) {
  S.ui.mode = mode;
  render();
}

function itemChoiceButton(g, itemId, onclick, upgradedPreview = false, verb = "") {
  const item = g.items[itemId];
  const info = S.cat.equipment[item.key];
  const effects = upgradedPreview ? info.upgraded : item.upgraded ? info.upgraded : info.basic;
  return h(
    "button",
    { class: "btn item-choice", onclick, title: effects.map((e) => e.text).join(" ") },
    itemIcon(item.key, item.kind, 26, upgradedPreview || item.upgraded),
    h("span", {}, verb ? `${verb} ` : "", info.name),
  );
}

// ------------------------------------------------------------------ battle panel
function clashOutcome(dice, bonus, k) {
  const c = { sword: 0, shield: 0, spell: 0, claw: 0, parry: 0 };
  for (const d of dice) if (d.face in c) c[d.face]++;
  const asSwords = Math.min(k, c.spell);
  const swords = c.sword + asSwords + bonus.filter((b) => b === "sword").length;
  const shields = c.shield + c.spell - asSwords + bonus.filter((b) => b === "shield").length;
  return { dealt: Math.max(0, swords - c.parry), taken: Math.max(0, c.claw - shields), spells: c.spell };
}

function renderBattle(g) {
  const layer = $("#battle-layer");
  const b = g.battle;
  if (!b) {
    layer.replaceChildren();
    layer.classList.remove("on");
    return;
  }
  layer.classList.add("on");
  const me = mySeat();
  const mine = b.seat === me && g.actor === me && legal().length > 0;
  const hero = g.heroes[b.seat];
  const monster = g.monsters.find((m) => m.id === b.monster);
  if (!monster) {
    layer.replaceChildren();
    return;
  }
  const info = S.cat.monsters[monster.key];
  const left = monster.toughness - monster.damage;
  const heroDice = [];
  const monsterDice = [];
  const mode = S.ui.mode?.kind === "reroll" ? S.ui.mode : null;
  const rerollable = new Set();
  if (mode) for (const a of ofType("reroll").filter((x) => x.item === mode.item)) for (const i of a.dice) rerollable.add(i);
  const rolled = g.phase === "clash" || g.phase === "after_clash";
  if (rolled && b.dice.length) {
    b.dice.forEach((d, i) => {
      const picked = mode?.picked.includes(i);
      const can = rerollable.has(i);
      const el = die(d.die, d.face, 44, { class: `${S.ui.rolling ? "rolling" : ""}${can ? " can-pick" : ""}${picked ? " picked" : ""}${b.rerolled.includes(i) ? " was-rerolled" : ""}` });
      el.dataset.i = i;
      if (can) {
        el.addEventListener("click", () => {
          const list = mode.picked.includes(i) ? mode.picked.filter((x) => x !== i) : [...mode.picked, i];
          if (list.length > mode.count) list.shift();
          S.ui.mode = { ...mode, picked: list };
          render();
        });
      }
      (d.die === "black" || d.die === "purple" ? monsterDice : heroDice).push(el);
    });
  } else {
    for (const d of b.pool) (d === "black" || d === "purple" ? monsterDice : heroDice).push(h("span", { class: "die-ghost" }, die(d, "blank", 44, { class: "ghost" })));
  }
  for (const sym of b.bonus) heroDice.push(h("span", { class: "bonus-sym", title: "Bonus from equipment" }, "+", faceIcon(sym, 22)));

  const res = rolled ? clashOutcome(b.dice, b.bonus, 0) : null;
  const spells = res?.spells || 0;
  const suggested = b.preview?.spell_swords ?? 0;
  const split = Math.min(spells, S.ui.split ?? suggested);
  const outcome = rolled ? clashOutcome(b.dice, b.bonus, split) : null;

  const controls = [];
  if (mine && g.phase === "prepare") {
    for (const a of ofType("drink")) {
      const it = g.items[a.item];
      controls.push(h("button", { class: "btn", onclick: () => act(a) }, itemIcon(it.key, it.kind, 22), ` Drink ${itemName(it.key)} (+1 ${S.cat.equipment[it.key].potion})`));
    }
    const fight = findLegal((a) => a.type === "fight");
    if (fight) controls.push(h("button", { class: "btn primary big", onclick: () => act(fight) }, symbolIcon("wish", 22), "Roll the dice"));
    const retreat = findLegal((a) => a.type === "retreat");
    if (retreat) controls.push(h("button", { class: "btn", onclick: () => act(retreat) }, b.potions.length ? "Retreat" : "Never mind (keep the action)"));
  }
  if (mine && g.phase === "clash") {
    if (mode) {
      controls.push(h("span", { class: "mode-note" }, `Pick up to ${mode.count} highlighted ${mode.count === 1 ? "die" : "dice"} to reroll.`));
      const chosen = [...mode.picked].sort((x, y) => x - y);
      const a = ofType("reroll").find((x) => x.item === mode.item && same(x.dice, chosen));
      controls.push(h("button", { class: "btn primary", disabled: !a, onclick: () => a && act(a) }, `Reroll ${chosen.length || ""}`));
      controls.push(h("button", { class: "btn", onclick: () => setMode(null) }, "Cancel"));
    } else {
      const usable = new Map();
      for (const a of legal()) if (a.type === "reroll" || a.type === "bonus") if (!usable.has(a.item)) usable.set(a.item, a);
      for (const [itemId, a] of usable) {
        const it = g.items[itemId];
        const eff = (it.upgraded ? S.cat.equipment[it.key].upgraded : S.cat.equipment[it.key].basic).find((e) => e.kind === a.type);
        const label = a.type === "bonus" ? `+1 ${eff?.symbol}` : `Reroll ${eff?.count === 1 ? "1" : `≤${eff?.count}`} ${eff?.colors.join("/")}`;
        const onclick = a.type === "bonus" ? () => act(a) : () => setMode({ kind: "reroll", item: itemId, count: eff?.count || 1, picked: [] });
        controls.push(h("button", { class: `btn equip-use${S.ui.hint?.item === itemId ? " hint" : ""}`, onclick, title: eff?.text }, itemIcon(it.key, it.kind, 22, it.upgraded), ` ${label}`));
      }
      if (spells) {
        controls.push(
          h(
            "div",
            { class: "spell-split" },
            h("span", {}, faceIcon("spell", 16), ` ${plural(spells, "spell")}:`),
            h("button", { class: "btn small", disabled: split <= 0, onclick: () => ((S.ui.split = split - 1), render()), "aria-label": "Fewer swords" }, "−"),
            h("span", { class: "split-val" }, `${split} `, faceIcon("sword", 14), ` / ${spells - split} `, faceIcon("shield", 14)),
            h("button", { class: "btn small", disabled: split >= spells, onclick: () => ((S.ui.split = split + 1), render()), "aria-label": "More swords" }, "+"),
          ),
        );
      }
      const resolve = ofType("resolve").find((a) => a.spell_swords === split);
      if (resolve) controls.push(h("button", { class: "btn primary big", onclick: () => act(resolve) }, `Resolve: deal ${outcome.dealt}, take ${outcome.taken}`));
    }
  }
  if (mine && g.phase === "after_clash") {
    const fight = findLegal((a) => a.type === "fight");
    const retreat = findLegal((a) => a.type === "retreat");
    if (fight) controls.push(h("button", { class: `btn primary big${S.ui.hint?.type === "fight" ? " hint" : ""}`, onclick: () => act(fight) }, faceIcon("sword", 20), `Fight on · clash ${b.clash + 1} of 3`));
    if (retreat) controls.push(h("button", { class: `btn${S.ui.hint?.type === "retreat" ? " hint" : ""}`, onclick: () => act(retreat) }, "Retreat"));
  }
  if (mine && S.state.settings.hints && !mode) controls.push(hintButton());
  if (!mine) controls.push(h("span", { class: "mode-note" }, `${hero.name} is fighting…`));

  const last =
    b.last && g.phase === "after_clash"
      ? h("div", { class: "last-clash" }, `Clash ${b.last.clash}: `, faceIcon("sword", 15), ` dealt ${b.last.dealt} · `, faceIcon("claw", 15), ` took ${b.last.taken}`)
      : null;
  const kills = outcome && outcome.dealt >= left;
  const stuns = outcome && outcome.taken >= hero.toughness;
  const preview =
    outcome && g.phase === "clash"
      ? h(
          "div",
          { class: `preview${kills ? " kill" : ""}${stuns ? " stun" : ""}` },
          h("span", { class: "pv dealt" }, faceIcon("sword", 16), h("b", {}, outcome.dealt), " to the monster", kills ? h("em", {}, " — defeats it!") : null),
          h("span", { class: "pv taken" }, faceIcon("claw", 16), h("b", {}, outcome.taken), ` to ${hero.name}`, stuns ? h("em", {}, " — stunned!") : null),
        )
      : null;
  const reward = [];
  if (info.reward.coins) reward.push(h("span", { class: "rw" }, h("b", {}, info.reward.coins), coinIcon(18)));
  for (let i = 0; i < info.reward.equipment; i++) reward.push(h("span", { class: "rw", title: "equipment from the bag" }, symbolIcon("bag", 18)));
  for (let i = 0; i < info.reward.upgrades; i++) reward.push(h("span", { class: "rw", title: "upgrade" }, symbolIcon("upgrade", 18)));
  const hearts = [];
  for (let i = 0; i < S.cat.max_toughness; i++) hearts.push(heartIcon(18, i < hero.toughness));
  const mhp = [];
  for (let i = 0; i < monster.toughness; i++) mhp.push(h("span", { class: `mpip${i < left ? " on" : ""}` }));
  const clashDots = [1, 2, 3].map((n) => h("span", { class: `clash-dot${n < b.clash || (n === b.clash && g.phase === "after_clash") ? " done" : n === b.clash ? " now" : ""}` }));
  layer.replaceChildren(
    h(
      "div",
      { class: `battle-panel${info.size === "beast" ? " vs-beast" : ""}`, role: "dialog", "aria-label": "Battle" },
      h(
        "div",
        { class: "duel" },
        h(
          "div",
          { class: "duelist hero-side", style: { "--hc": HERO_FILL[hero.color] } },
          h("div", { class: "portrait" }, heroAvatar(hero.color, 76)),
          h("div", { class: "duel-id" }, h("b", {}, hero.name), h("div", { class: "hearts" }, hearts)),
        ),
        h("div", { class: "vs-crest" }, h("span", { class: "vs-word" }, "VS"), h("span", { class: "clash-no" }, g.phase === "prepare" ? "Prepare" : `Clash ${b.clash} of 3`), h("span", { class: "clash-dots" }, clashDots)),
        h(
          "div",
          { class: "duelist monster-side" },
          h("div", { class: "portrait" }, monsterBadge(monster.key, info, info.size === "beast" ? 98 : 88, { detail: true, left, damage: monster.damage })),
          h(
            "div",
            { class: "duel-id" },
            h("b", {}, info.name),
            h("div", { class: "mhp", title: `${left} of ${monster.toughness} toughness left` }, mhp),
            h("div", { class: "reward" }, h("small", {}, "Reward"), reward.length ? reward : "—"),
          ),
        ),
      ),
      info.attribute_text ? h("div", { class: "attr" }, h("b", {}, "Beware: "), info.attribute_text) : null,
      h(
        "div",
        { class: "trays" },
        h("div", { class: "dice-tray hero-tray" }, h("span", { class: "tray-label" }, b.seat === me ? "Your dice" : `${hero.name}'s dice`), h("div", { class: "tray-dice" }, heroDice)),
        h("div", { class: "dice-tray monster-tray" }, h("span", { class: "tray-label" }, "Monster dice"), h("div", { class: "tray-dice" }, monsterDice)),
      ),
      last,
      preview,
      h("div", { class: "battle-controls" }, controls),
    ),
  );
}

// ------------------------------------------------------------------ hero boards
function renderMyBoard(g) {
  const el = $("#myboard");
  const me = mySeat();
  const seat = me !== null && me < g.heroes.length ? me : g.current;
  el.replaceChildren(heroBoard(g, seat, { compact: false }));
}

function heroBoard(g, seat, { compact }) {
  const hero = g.heroes[seat];
  const me = mySeat();
  const mine = seat === me;
  const hearts = [];
  for (let i = S.cat.max_toughness - 1; i >= 0; i--) hearts.push(heartIcon(compact ? 15 : 19, i < hero.toughness));
  const slot = (kind) => {
    const id = hero.slots[kind];
    const item = id ? g.items[id] : null;
    const sample = Object.values(S.cat.equipment).find((e) => e.kind === kind);
    return h(
      "button",
      {
        class: `slot slot-${kind}${item ? " filled" : ""}${item?.upgraded ? " upgraded" : ""}`,
        title: item ? `${itemName(item.key)}${item.upgraded ? " (upgraded)" : ""}` : `No ${kind}`,
        onclick: item ? () => showItem(g, seat, id) : null,
        disabled: !item,
      },
      item ? itemArt(item.key, item.kind) : sample ? h("span", { class: "slot-ghost" }, itemArt(sample.key, kind)) : null,
      item?.upgraded ? upgradeStar() : null,
      h("span", { class: "slot-label" }, kind),
    );
  };
  const bp = S.cat.backpack;
  const cells = [];
  for (let y = 0; y < bp.h; y++) for (let x = 0; x < bp.w; x++) cells.push(h("span", { class: "cell", style: { gridColumn: x + 1, gridRow: y + 1 } }));
  const packed = [];
  if (hero.layout) {
    hero.pack.forEach((id, i) => {
      const [x, y, w, hh] = hero.layout[i];
      const item = g.items[id];
      packed.push(
        h(
          "button",
          {
            class: `bp-item kind-${item.kind}${item.upgraded ? " upgraded" : ""}${w > hh ? " sideways" : ""}`,
            style: { gridColumn: `${x + 1} / span ${w}`, gridRow: `${y + 1} / span ${hh}` },
            title: `${itemName(item.key)}${item.upgraded ? " (upgraded)" : ""}`,
            onclick: () => showItem(g, seat, id),
          },
          itemArt(item.key, item.kind, w > hh),
          item.upgraded ? upgradeStar() : null,
        ),
      );
    });
    for (const [x, y] of hero.coin_cells) packed.push(h("span", { class: "bp-coin", style: { gridColumn: x + 1, gridRow: y + 1 } }, coinIcon(compact ? 22 : 30)));
  }
  const overflow = !hero.layout;
  const bag = h(
    "div",
    { class: `backpack${overflow ? " overflow" : ""}`, style: { "--cols": bp.w, "--rows": bp.h } },
    overflow ? null : cells,
    overflow ? null : packed,
    overflow
      ? h(
          "div",
          { class: "overflow-list" },
          h("b", {}, "Doesn't fit!"),
          h(
            "div",
            { class: "loose" },
            hero.pack.map((id) => h("button", { class: "bp-loose", onclick: () => showItem(g, seat, id) }, itemIcon(g.items[id].key, g.items[id].kind, 34, g.items[id].upgraded))),
          ),
          h("span", { class: "loose-coins" }, coinIcon(18), hero.coins),
        )
      : null,
  );
  const here = tileName(g, hero.hex);
  return h(
    "div",
    { class: `hero-board${compact ? " compact" : ""}${g.current === seat && g.phase !== "game_over" ? " current" : ""}`, style: { "--hc": HERO_FILL[hero.color] } },
    h(
      "div",
      { class: "hb-head" },
      h("span", { class: "hb-avatar" }, heroAvatar(hero.color, compact ? 38 : 44)),
      h("div", { class: "hb-id" }, h("b", {}, hero.name, mine ? h("small", {}, " · you") : null), h("span", { class: "hb-where" }, `at ${here}`)),
      h("span", { class: "hb-coins", title: `${plural(hero.coins, "coin")}` }, coinIcon(compact ? 22 : 26), h("b", {}, hero.coins)),
    ),
    h(
      "div",
      { class: "hb-body" },
      h("div", { class: "hb-hearts", title: `${hero.toughness} of ${S.cat.max_toughness} toughness` }, hearts),
      h("div", { class: "equip" }, slot("weapon"), h("div", { class: "equip-col" }, slot("helmet"), slot("shield"))),
      h("div", { class: "pack-wrap" }, h("span", { class: "pack-label" }, "Backpack"), bag),
    ),
  );
}

function upgradeStar() {
  return s(
    "svg",
    { viewBox: "0 0 100 100", class: "up-star", "aria-hidden": "true" },
    s("path", { d: "M50 4 L62 34 L95 36 L69 57 L78 90 L50 72 L22 90 L31 57 L5 36 L38 34 Z", fill: "#7fe0ff", stroke: "#1d130c", "stroke-width": 7, "stroke-linejoin": "round" }),
  );
}

function showItem(g, seat, itemId) {
  const item = g.items[itemId];
  const info = S.cat.equipment[item.key];
  const options = [];
  const mine = seat === mySeat();
  const close = () => closeFn();
  const doAct = (a) => {
    close();
    act(a);
  };
  if (mine) {
    for (const a of legal()) {
      if (a.item !== itemId) continue;
      if (a.type === "equip") options.push(h("button", { class: "btn", onclick: () => doAct(a) }, "Put on"));
      if (a.type === "unequip") options.push(h("button", { class: "btn", onclick: () => doAct(a) }, "Put in backpack"));
      if (a.type === "drink") options.push(h("button", { class: "btn primary", onclick: () => doAct(a) }, "Drink"));
      if (a.type === "discard") options.push(h("button", { class: "btn danger", onclick: () => doAct(a) }, "Discard"));
      if (a.type === "give") options.push(h("button", { class: "btn", onclick: () => doAct(a) }, `Give to ${g.heroes[a.to].name}`));
      if (a.type === "lose") options.push(h("button", { class: "btn danger", onclick: () => doAct(a) }, "Lose this one"));
      if (a.type === "choose_upgrade") options.push(h("button", { class: "btn primary", onclick: () => doAct(a) }, "Upgrade this"));
    }
  } else {
    for (const a of legal()) if (a.type === "take" && a.item === itemId && a.source === seat) options.push(h("button", { class: "btn", onclick: () => doAct(a) }, "Take it"));
  }
  const side = (label, effects, active) =>
    h("div", { class: `fx-side${active ? " active" : ""}` }, h("small", {}, label), effects.length ? effects.map((e) => h("p", {}, e.text)) : h("p", {}, "—"));
  const body = [];
  if (info.kind === "elixir") {
    body.push(h("p", {}, info.heals ? "Drink between actions (not in battle) to heal fully. Free." : `Drink while preparing a battle: +1 ${info.potion} die for the whole battle.`));
  } else {
    body.push(side("Basic", info.basic, !item.upgraded), side("Upgraded", info.upgraded, item.upgraded));
  }
  const closeFn = openDialog(
    h(
      "div",
      { class: "dialog item-dialog" },
      h(
        "div",
        { class: "item-head" },
        h("div", { class: `item-token kind-${item.kind}${item.upgraded ? " upgraded" : ""}` }, itemArt(item.key, item.kind), item.upgraded ? upgradeStar() : null),
        h("div", {}, h("h2", {}, info.name), h("p", { class: "note" }, `${info.kind}${item.upgraded ? " · upgraded" : ""} · ${g.heroes[seat].name}`)),
      ),
      body,
      h("div", { class: "dialog-actions" }, options, h("button", { class: "btn ghost", onclick: close }, "Close")),
    ),
  );
}

function showHeroDialog(seat) {
  const g = game();
  if (!g) return;
  const close = openDialog(h("div", { class: "dialog hero-dialog" }, heroBoard(g, seat, { compact: false }), h("div", { class: "dialog-actions" }, h("button", { class: "btn ghost", onclick: () => close() }, "Close"))));
}

// ------------------------------------------------------------------ party (side panel)
function renderParty() {
  const el = $("#party");
  const st = S.state;
  if (!el || !st) return;
  const g = st.game;
  if (!g || st.status === "lobby") {
    el.replaceChildren(
      ...[
        h("div", { class: "side-note" }, "Seated:"),
        ...st.seats.map((seat) =>
          h("div", { class: "pl-row lobby-row", style: { "--hc": HERO_FILL[seat.color] } }, h("span", { class: "pl-avatar" }, heroAvatar(seat.color, 36)), h("div", { class: "pl-id" }, h("span", { class: "pl-name" }, seat.name, seat.bot ? h("small", {}, " bot") : null))),
        ),
        st.spectators.length ? h("div", { class: "side-note" }, `Watching: ${st.spectators.map((x) => x.name).join(", ")}`) : null,
      ].filter(Boolean),
    );
    return;
  }
  const me = mySeat();
  const myHero = me !== null ? g.heroes[me] : null;
  const rows = g.heroes.map((hero) => {
    const seat = st.seats[hero.seat];
    const together = myHero && hero.seat !== me && hexEq(hero.hex, myHero.hex);
    const hearts = [];
    for (let i = 0; i < S.cat.max_toughness; i++) hearts.push(heartIcon(14, i < hero.toughness));
    const gear = ["weapon", "helmet", "shield"].map((k) => (hero.slots[k] ? itemIcon(g.items[hero.slots[k]].key, k, 26, g.items[hero.slots[k]].upgraded) : h("span", { class: "gear-empty", title: `No ${k}` })));
    const extra = [];
    if (together) {
      const give = findLegal((a) => a.type === "give" && a.to === hero.seat && a.coins === 1);
      const take = findLegal((a) => a.type === "take" && a.source === hero.seat && a.coins === 1);
      if (give) extra.push(h("button", { class: "btn small", onclick: () => act(give) }, "Give 1", coinIcon(12)));
      if (take) extra.push(h("button", { class: "btn small", onclick: () => act(take) }, "Take 1", coinIcon(12)));
    }
    return h(
      "div",
      { class: `pl-row${g.current === hero.seat && g.phase !== "game_over" ? " current" : ""}${g.actor === hero.seat ? " acting" : ""}`, onclick: () => showHeroDialog(hero.seat), style: { "--hc": HERO_FILL[hero.color] } },
      h("span", { class: "pl-avatar" }, heroAvatar(hero.color, 46)),
      h(
        "div",
        { class: "pl-id" },
        h(
          "span",
          { class: "pl-name" },
          hero.name,
          hero.seat === me ? h("small", {}, " you") : seat?.bot ? h("small", {}, " bot") : null,
          seat && !seat.connected ? h("small", { class: "off" }, " away") : null,
          hero.seat === g.start_seat ? h("span", { class: "arms", title: "Coat of arms: starts each round" }, shieldMark(15)) : null,
        ),
        h("span", { class: "pl-stats" }, h("span", { class: "hearts" }, hearts), h("span", { class: "pl-coins" }, coinIcon(17), h("b", {}, hero.coins))),
        h("span", { class: "pl-gear" }, gear),
        h("span", { class: "pl-where" }, tileName(g, hero.hex), together ? " · with you" : ""),
        extra.length ? h("span", { class: "pl-extra", onclick: (e) => e.stopPropagation() }, extra) : null,
      ),
    );
  });
  el.replaceChildren(...rows);
}

// ------------------------------------------------------------------ dialogs: market, alchemist, trap
function openMarket() {
  const g = game();
  const me = mySeat();
  const hero = g.heroes[me];
  const owned = [...Object.values(hero.slots).filter(Boolean), ...hero.pack];
  let sell = [];
  let buy = 0;
  const box = h("div", { class: "dialog market" });
  let close = () => {};
  const draw = () => {
    const chosen = [...sell].sort();
    const action = { type: "market", sell: chosen, buy };
    const ok = isLegal(action);
    const coins = hero.coins + 2 * sell.length - 3 * buy;
    box.replaceChildren(
      dialogHead("marketplace", "Marketplace"),
      h("p", { class: "note" }, "Up to 2 transactions in one action. Sales happen first: 2 coins each. Purchases draw a random token from the bag: 3 coins each."),
      h("h4", {}, "Sell"),
      h(
        "div",
        { class: "market-items" },
        owned.length
          ? owned.map((id) => {
              const it = g.items[id];
              const on = sell.includes(id);
              return h(
                "button",
                {
                  class: `market-item${on ? " on" : ""}`,
                  onclick: () => {
                    sell = on ? sell.filter((x) => x !== id) : [...sell, id];
                    if (sell.length + buy > 2) buy = Math.max(0, 2 - sell.length);
                    draw();
                  },
                },
                itemIcon(it.key, it.kind, 34, it.upgraded),
                h("span", {}, itemName(it.key)),
              );
            })
          : h("p", { class: "note" }, "Nothing to sell."),
      ),
      h("h4", {}, "Buy"),
      h(
        "div",
        { class: "buy-row" },
        [0, 1, 2].map((n) => h("button", { class: `btn small${buy === n ? " on" : ""}`, disabled: sell.length + n > 2, onclick: () => ((buy = n), draw()) }, n === 0 ? "nothing" : `${n} token${n > 1 ? "s" : ""}`)),
        h("span", { class: "note" }, `${g.bag} in the bag`),
      ),
      h("p", { class: "market-total" }, "Coins after: ", h("b", {}, coins), coinIcon(14)),
      h("div", { class: "dialog-actions" }, h("button", { class: "btn primary", disabled: !ok, onclick: () => (close(), act(action)) }, "Trade"), h("button", { class: "btn ghost", onclick: () => close() }, "Cancel")),
    );
  };
  draw();
  close = openDialog(box);
}

function openAlchemist() {
  const g = game();
  let close = () => {};
  const rows = ofType("upgrade").map((a) => {
    const it = g.items[a.item];
    const info = S.cat.equipment[it.key];
    return h(
      "button",
      { class: "upgrade-row", onclick: () => (close(), act(a)) },
      itemIcon(it.key, it.kind, 40),
      h("div", {}, h("b", {}, info.name), h("p", { class: "note" }, "Now: ", info.basic.map((e) => e.text).join(" ")), h("p", {}, "→ ", info.upgraded.map((e) => e.text).join(" "))),
    );
  });
  close = openDialog(
    h(
      "div",
      { class: "dialog" },
      dialogHead("alchemist", "Alchemist Workshop"),
      h("p", { class: "note" }, "Pay 3 coins to flip one item to its upgraded side."),
      h("div", { class: "upgrade-list" }, rows),
      h("div", { class: "dialog-actions" }, h("button", { class: "btn ghost", onclick: () => close() }, "Cancel")),
    ),
  );
}

function openTrap() {
  const g = game();
  let close = () => {};
  const levels = [...new Set(ofType("trap").map((a) => a.level))].sort((a, b) => a - b);
  const rows = Object.values(S.cat.traps).map((t) => {
    const ok = levels.includes(t.level);
    const placed = g.traps[String(t.level)];
    return h(
      "button",
      { class: "trap-row", disabled: !ok, onclick: () => (close(), setMode({ kind: "trap", level: t.level })) },
      h("b", {}, `Level ${t.level}`),
      h("span", { class: "trap-dice" }, t.dice.map((d) => die(d, "sword", 22)), t.damage ? ` +${t.damage}` : ""),
      h("span", { class: "note" }, placed ? "already placed" : `${t.level} coins`),
    );
  });
  close = openDialog(
    h(
      "div",
      { class: "dialog" },
      dialogHead("elven_camp", "Elven Camp"),
      h("p", { class: "note" }, "Traps hurt only the Beast: when it enters the tile, roll the dice — every sword plus the bonus is a wound. One trap per tile, each level once. Think about the Beast's shortest path from the crater."),
      h("div", { class: "trap-list" }, rows),
      h("div", { class: "dialog-actions" }, h("button", { class: "btn ghost", onclick: () => close() }, "Cancel")),
    ),
  );
}

// A painted strip of the tile's landscape with the dialog title on it.
function dialogHead(tileKey, title, sub = null, picture = null) {
  const href = S.cat.tiles[tileKey] ? `#t-${tileKey}` : "#t-map-1";
  const art = picture || s("svg", { viewBox: "-50 -30 100 44", preserveAspectRatio: "xMidYMid slice", class: "head-art", "aria-hidden": "true" }, s("use", { href, x: -50, y: -43.3, width: 100, height: 86.6 }));
  return h("div", { class: "dialog-head" }, art, h("div", { class: "dialog-title" }, h("h2", {}, title), sub ? h("p", {}, sub) : null));
}

// ------------------------------------------------------------------ info popups
function showTileInfo(hex) {
  const g = game();
  const t = tileAt(g, hex);
  if (!t) return;
  const info = t.key ? S.cat.tiles[t.key] : null;
  const monsters = g.monsters.filter((m) => hexEq(m.hex, hex));
  const heroes = g.heroes.filter((x) => hexEq(x.hex, hex));
  const lines = [];
  if (!info) lines.push(h("p", {}, "Unexplored. Move here to reveal it — a lair spawns a monster at once."));
  else {
    if (info.castle) lines.push(h("p", {}, `Avel Castle. ${plural(g.walls, "wall fragment")} stand. If any monster enters, the game is lost.`));
    if (info.action) lines.push(h("p", {}, TILE_ACTION_TEXT[info.action]));
    if (info.lairs.length) lines.push(h("p", {}, `${info.lairs.length === 2 ? "Two" : "One"} ${info.lairs[0]} monster lair${info.lairs.length > 1 ? "s" : ""}${t.seals.some(Boolean) ? ` (${t.seals.filter(Boolean).length} sealed)` : ""}.`));
    if (info.shortcut) lines.push(h("p", {}, "Shortcut: move from here to any other face-up shortcut tile."));
    if (info.symbol) lines.push(h("p", { class: "note" }, `Crater symbol: ${info.symbol}.`));
  }
  if (t.trap) lines.push(h("p", {}, `A level ${t.trap} trap waits for the Beast.`));
  if (t.crater) lines.push(h("p", { class: "with-ico" }, symbolIcon("crater", 22), "The crater: the Beast will appear here."));
  for (const m of monsters) lines.push(monsterLine(m));
  if (heroes.length) lines.push(h("p", { class: "note" }, `Here: ${heroes.map((x) => x.name).join(", ")}`));
  let close = () => {};
  close = openDialog(
    h(
      "div",
      { class: "dialog tile-dialog" },
      info ? dialogHead(t.key, info.name, info.castle ? null : info.lairs.length ? `${info.lairs.length === 2 ? "two" : "one"} ${info.lairs[0]} lair${info.lairs.length > 1 ? "s" : ""}` : null) : dialogHead("unexplored", "Unexplored land"),
      lines,
      h("div", { class: "dialog-actions" }, h("button", { class: "btn ghost", onclick: () => close() }, "Close")),
    ),
  );
}

function monsterLine(m, big = false) {
  const info = S.cat.monsters[m.key];
  const left = m.toughness - m.damage;
  const reward = [];
  if (info.reward.coins) reward.push(h("span", { class: "rw" }, h("b", {}, info.reward.coins), coinIcon(16)));
  for (let i = 0; i < info.reward.equipment; i++) reward.push(h("span", { class: "rw", title: "equipment" }, symbolIcon("bag", 16)));
  for (let i = 0; i < info.reward.upgrades; i++) reward.push(h("span", { class: "rw", title: "upgrade" }, symbolIcon("upgrade", 16)));
  return h(
    "div",
    { class: `monster-line${big ? " big" : ""}` },
    monsterBadge(m.key, info, big ? 144 : 52, { detail: big, left, damage: m.damage }),
    h(
      "div",
      { class: "ml-body" },
      h("b", { class: "ml-name" }, info.name),
      h("small", { class: "ml-kind" }, `${info.size}${info.color ? ` · ${info.color}` : ""}`),
      h(
        "div",
        { class: "ml-stats" },
        h("span", { class: "ml-tough" }, heartIcon(16), `${left}/${m.toughness}`),
        h("span", { class: "ml-dice" }, ...Array.from({ length: info.black }, () => die("black", "claw", 20)), ...Array.from({ length: info.purple }, () => die("purple", "claw", 20))),
        reward.length ? h("span", { class: "reward" }, reward) : null,
      ),
      info.attribute_text ? h("div", { class: "note warn" }, info.attribute_text) : null,
    ),
  );
}

function showMonsterInfo(m) {
  let close = () => {};
  close = openDialog(h("div", { class: "dialog monster-dialog" }, monsterLine(m, true), h("div", { class: "dialog-actions" }, h("button", { class: "btn ghost", onclick: () => close() }, "Close"))));
}

// ------------------------------------------------------------------ game over
function renderSummary(g) {
  if (g.phase !== "game_over" || S.ui.summaryClosed || document.querySelector(".summary-dialog")) return;
  S.ui.summaryClosed = true;
  const won = g.result?.won;
  const isHost = S.state.host === S.me;
  let close = () => {};
  close = openDialog(
    h(
      "div",
      { class: `dialog summary-dialog ${won ? "won" : "lost"}` },
      h("div", { class: "summary-art" }, vista(won ? "won" : "lost", { heroes: won ? g.heroes.map((x) => x.color) : [], beast: !won })),
      h("h2", {}, won ? "Avel is saved!" : "The Healing Jewel is lost"),
      h("p", {}, won ? `Every monster — and the Beast — fell in ${g.result.rounds} rounds.` : `A monster broke into the castle in round ${g.result.rounds}.`),
      h(
        "div",
        { class: "dialog-actions" },
        isHost ? h("button", { class: "btn primary", onclick: () => (close(), send({ type: "play_again" })) }, "Play again") : null,
        isHost ? h("button", { class: "btn", onclick: () => (close(), send({ type: "to_lobby" })) }, "Lobby") : null,
        h("button", { class: "btn ghost", onclick: () => close() }, "Look at the map"),
      ),
    ),
  );
}

// ------------------------------------------------------------------ flashes & descriptions
function flashEvent(e, g) {
  const me = mySeat();
  switch (e.kind) {
    case "slain":
      if (e.key === "beast") toast("The Beast is slain!");
      break;
    case "stunned":
      if (e.seat === me) toast("You were stunned and woke up in the castle", true);
      break;
    case "black_moon":
      toast("The Black Moon rises! The Beast appears.");
      break;
    case "march":
      break;
    case "wall_broken":
      toast(`A wall fragment falls (${e.walls} left)`, true);
      break;
    case "turn":
      if (e.seat === me && g.n > 1) toast("Your turn!", false, "turn");
      break;
  }
}

function describeAction(a) {
  const g = game();
  switch (a.type) {
    case "move":
      return `Move to ${tileName(g, a.to)}`;
    case "battle": {
      const m = g.monsters.find((x) => x.id === a.monster);
      return `Battle the ${m ? monsterName(m.key) : "monster"}`;
    }
    case "fight":
      return "Roll the dice";
    case "retreat":
      return "Retreat";
    case "resolve":
      return "Resolve the clash";
    case "reroll":
      return `Reroll with the ${itemName(g.items[a.item]?.key)}`;
    case "bonus":
      return `Use the ${itemName(g.items[a.item]?.key)}`;
    case "drink":
      return `Drink the ${itemName(g.items[a.item]?.key)}`;
    case "rest":
      return "Rest";
    case "market":
      return `Market: ${a.sell.length ? `sell ${a.sell.map((i) => itemName(g.items[i]?.key)).join(", ")}` : ""}${a.sell.length && a.buy ? " and " : ""}${a.buy ? `buy ${a.buy}` : ""}`;
    case "seal":
      return `Seal the lair on ${tileName(g, a.at)}`;
    case "wall":
      return "Build a wall";
    case "trap":
      return `Set a level ${a.level} trap on ${tileName(g, a.at)}`;
    case "work":
      return "Work for 2 coins";
    case "upgrade":
      return `Upgrade the ${itemName(g.items[a.item]?.key)}`;
    case "wish":
      return "Make a wish";
    case "choose_upgrade":
      return `Upgrade the ${itemName(g.items[a.item]?.key)}`;
    case "equip":
      return `Put on the ${itemName(g.items[a.item]?.key)}`;
    case "unequip":
      return `Stow the ${itemName(g.items[a.item]?.key)}`;
    case "discard":
      return a.item ? `Discard the ${itemName(g.items[a.item]?.key)}` : "Drop a coin";
    case "give":
      return a.item ? `Give the ${itemName(g.items[a.item]?.key)} to ${g.heroes[a.to].name}` : `Give a coin to ${g.heroes[a.to].name}`;
    case "take":
      return a.item ? `Take the ${itemName(g.items[a.item]?.key)}` : "Take a coin";
    case "lose":
      return `Lose the ${itemName(g.items[a.item]?.key)}`;
    case "steer":
      return `Send it to ${tileName(g, a.to)}`;
    case "done":
      return "Done";
    case "end_turn":
      return "End your turn";
    default:
      return a.type;
  }
}

// ------------------------------------------------------------------ rules
function showRules() {
  let close = () => {};
  const sec = (title, ...ps) => h("section", {}, h("h3", {}, title), ps.map((p) => h("p", {}, p)));
  close = openDialog(
    h(
      "div",
      { class: "dialog rules" },
      dialogHead("castle", "How to play", "A cooperative game for 1–4 heroes", vista("home", { heroes: ["red", "blue", "green", "yellow"] })),
      sec("Goal", "Work together. When the Black Moon rises (end of the moon track) the Beast appears from the crater and every monster marches one tile towards the castle at the end of each round. Defeat all monsters, including the Beast, before any of them enters Avel Castle."),
      sec(
        "Your turn",
        "Take 2 actions (4 when playing solo), in any order, even the same one twice: Move to an adjacent tile (or between shortcut tiles), Battle a monster on your tile, use the Tile action, or Rest (+2 toughness).",
        "Free at any time on your turn: equip or stow gear, discard, drink the healing elixir, and trade items or coins with heroes on your tile (if no monster is there).",
      ),
      sec(
        "Battle",
        "Roll 2 green dice plus the extra dice your upgraded equipment gives, against the monster's black and purple dice. Each sword wounds the monster, each claw wounds you. Your shields block claws; the monster's parries block swords. Spells (yellow) count as swords or shields, your choice.",
        "Once per battle each item's one-time effect can reroll dice or add a symbol. A battle has up to 3 clashes; you may retreat between them. Wounds stay on the monster.",
        "Lose your last toughness and you're stunned: back to the castle, fully healed, but you lose all coins and one item. Your turn ends.",
      ),
      sec("Rewards & backpack", "Monsters give coins, equipment (random from the bag) or upgrades. Weapons, shields and helmets go on your hero; spares, elixirs and coins must fit in the 3×4 backpack — the game packs it for you, and asks you to discard if it overflows."),
      sec(
        "End of round",
        "The astrolabe moves along the moon track: a lair space spawns a monster on every empty, unsealed lair of face-up tiles; a heart space heals every hero by 1. Seals stop working near the end, then traps; walls can be built until the round after the Beast appears.",
        "Walls: a monster that would enter the castle destroys one wall instead (the Beast destroys them all).",
      ),
      h("div", { class: "dialog-actions" }, h("button", { class: "btn ghost", onclick: () => close() }, "Close")),
    ),
  );
}

// ------------------------------------------------------------------ boot
async function boot() {
  try {
    const res = await fetch(`${BASE}api/config`);
    const cfg = await res.json();
    S.cat = cfg;
    S.bots = cfg.bots;
  } catch {
    toast("Could not reach the server", true);
  }
  installSprite(S.cat);
  router();
}

setInterval(() => {
  const g = game();
  if (!g || g.time_left === null || g.time_left === undefined) return;
  g.time_left = Math.max(0, g.time_left - 1);
  const timer = document.querySelector(".prompt .timer");
  if (timer) timer.replaceWith(timerBar(g));
}, 1000);

boot();
