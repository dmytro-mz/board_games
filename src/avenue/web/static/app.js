import { NAME_KEY, TOKEN_KEY, gameBase, leaveRoom, socketUrl } from "/static/shared/platform.js";
import { meepleSvg } from "./art.js";
import { Board } from "./board.js";
import { AGENTS, AGENT_ORDER, MARKET, agentCard, cardBack, iconSvg, marketBack, marketCard, richText } from "./cards.js";
import { copyText, h, openDialog, toast } from "/static/shared/dom.js";
import { showRules } from "./rules.js";
import { getVolume, isMuted, setMuted, setVolume, sfx, unlockAudio } from "./sound.js";

const BASE = gameBase(import.meta.url); // /g/<key>/: this game's server routes

const REACTIONS = ["👍", "😂", "😱", "😡", "🎉", "🤔", "😭", "🔥", "👏", "🕵️"];
const TEAM = ["Green", "Blue"];
const MAX_TEAM = 2;

const app = document.getElementById("app");
const fx = document.getElementById("fx");

const store = {
  get: (k) => {
    try {
      return localStorage.getItem(k);
    } catch {
      return null;
    }
  },
  set: (k, v) => {
    try {
      localStorage.setItem(k, v);
    } catch {
      /* private mode */
    }
  },
};

const URL_TOKEN = takeTokenFromUrl();
const S = {
  config: { public_url: null, lan_url: null },
  token: URL_TOKEN || store.get(TOKEN_KEY) || newToken(),
  name: store.get(NAME_KEY) || "",
  code: null,
  ws: null,
  retry: 0,
  reconnectTimer: null,
  connected: false,
  fatal: null,
  me: null,
  log: [],
  state: null,
  timer: { endAt: 0, total: 0, lastTick: 0 },
  pending: [],
  busyUntil: 0,
  board: null,
  gameEl: null,
  gameNo: null,
  ui: freshUi(),
};
store.set(TOKEN_KEY, S.token);

function freshUi() {
  return { sel: [], discardMode: false, sideOpen: false, unread: 0, menu: false, flyFrom: null, overDismissed: false, sending: false, moving: new Set(), hold: {} };
}

function takeTokenFromUrl() {
  const params = new URLSearchParams(location.search);
  const token = params.get("me");
  if (!token || !/^[0-9a-f]{16,64}$/.test(token)) return null;
  history.replaceState({}, "", location.pathname);
  return token;
}

function newToken() {
  const bytes = new Uint8Array(16);
  crypto.getRandomValues(bytes);
  return Array.from(bytes, (b) => b.toString(16).padStart(2, "0")).join("");
}

const ADJ = ["Sly", "Silent", "Shady", "Secret", "Sneaky", "Swift", "Velvet", "Midnight", "Masked", "Clever"];
const NOUN = ["Fox", "Owl", "Raccoon", "Squirrel", "Wolf", "Pigeon", "Otter", "Mole", "Badger", "Lynx"];
const pick = (xs) => xs[Math.floor(Math.random() * xs.length)];
const suggestName = () => `${pick(ADJ)} ${pick(NOUN)}`;

function saveName(name) {
  name = (name || "").trim().slice(0, 20);
  if (!name) return S.name;
  S.name = name;
  store.set(NAME_KEY, name);
  return name;
}

const $ = (sel) => document.querySelector(sel);
const plural = (n, w) => `${n} ${w}${n === 1 ? "" : "s"}`;
const agentName = (k) => AGENTS[k]?.name || "a card";

// ------------------------------------------------------------------ routing

function router() {
  const match = location.pathname.match(/\/r\/([A-Za-z0-9]{4,8})\/?$/);
  if (match) enterRoom(match[1].toUpperCase());
  else leaveRoom();
}
window.addEventListener("popstate", router);

// ------------------------------------------------------------------ home
function logo() {
  const el = h("div", { class: "logo" }, h("span", { class: "logo-hat" }), h("span", { class: "logo-top" }, "Agent"), h("span", { class: "logo-sub" }, "Avenue"));
  el.firstChild.innerHTML = meepleSvg(0);
  return el;
}

// ------------------------------------------------------------------ room / socket
async function enterRoom(code) {
  closeSocket();
  Object.assign(S, { code, state: null, log: [], fatal: null, me: null, connected: false, retry: 0, pending: [], busyUntil: 0, gameEl: null, board: null, gameNo: null });
  S.ui = freshUi();
  document.title = `Agent Avenue · ${code}`;
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
  else toast("Not connected — reconnecting…", true);
}

function act(action) {
  unlockAudio();
  S.ui.sending = true;
  send({ type: "action", action });
}

function onMessage(msg) {
  switch (msg.type) {
    case "welcome":
      S.me = msg.you;
      S.log = msg.log;
      S.connected = true;
      S.retry = 0;
      renderConn();
      renderFeed();
      break;
    case "state":
      S.pending.push(msg);
      pump();
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
      S.ui.sending = false;
      toast(msg.message, true);
      sfx.error();
      if (S.state) render();
      break;
    case "fatal":
      S.fatal = msg.message;
      closeSocket();
      showFatal(msg.message);
      break;
  }
}

function showFatal(message) {
  app.replaceChildren(
    h(
      "div",
      { class: "center-msg" },
      h("div", {}, logo(), h("h2", {}, message), h("p", {}, "Tables close a while after everyone has left."), h("button", { class: "btn primary big", onclick: () => leaveRoom() }, "Start a new table")),
    ),
  );
}

// States are applied one after the other; each waits until the animations of the previous one are done.
let pumpTimer = null;
function pump() {
  clearTimeout(pumpTimer);
  while (S.pending.length) {
    const wait = S.busyUntil - performance.now();
    const next = S.pending[0];
    const urgent = S.pending.length > 4 || document.hidden || next.event?.kind !== "move";
    if (wait > 0 && !urgent) {
      pumpTimer = setTimeout(pump, wait);
      return;
    }
    S.pending.shift();
    applyState(next, S.pending.length > 4 || document.hidden);
  }
}

function captureRects() {
  const rects = {};
  for (const el of document.querySelectorAll("[data-fly]")) rects[el.dataset.fly] = el.getBoundingClientRect();
  return rects;
}

function applyState(next, instant = false) {
  const prev = S.state;
  const rects = captureRects();
  S.state = next;
  S.ui.sending = false;
  if (!prev) renderFeed();
  const g = next.game;
  if (g && g.time_left != null) {
    S.timer.endAt = performance.now() + g.time_left * 1000;
    S.timer.total = g.time_total;
  } else S.timer.endAt = 0;
  // joining (or coming back to) a table whose game is over: show the result
  if (next.status === "game_over" && (!prev || prev.status === "lobby")) S.ui.overShown = true;
  if (next.event?.kind === "game_start" || (g && S.gameNo !== null && prev?.game?.turn > (g?.turn ?? 0))) {
    S.ui = { ...freshUi(), sideOpen: S.ui.sideOpen };
  }
  const events = next.event?.kind === "move" ? next.event.events : [];
  const animate = !instant && prev && next.seq === prev.seq + 1 && events.length && prev.game && g;
  const dealing = !instant && prev && next.event?.kind === "game_start" && g && next.status === "playing";
  S.ui.moving = new Set();
  S.ui.hold = {};
  if (dealing) {
    g.players.forEach((pl, p) => {
      for (let i = 0; i < pl.hand; i++) S.ui.hold[p === next.you.seat && g.me ? `h-${i}` : `hc-${p}-${i}`] = true;
    });
  }
  if (animate) for (const ev of events) if (ev.kind === "move" && ev.steps) S.ui.moving.add(ev.side);
  if (g && (!g.me || g.phase !== "play" || !g.me.legal.some((a) => a.type === "play"))) S.ui.sel = [];
  if (!g?.me?.can_discard) S.ui.discardMode = false;
  if (animate) prepareHolds(prev, next, events);
  // a first estimate so this render already knows the table is busy; playEvents sets the exact time
  S.busyUntil = animate ? performance.now() + estimateMs(events) : dealing ? performance.now() + 2500 : performance.now();
  render();
  if (animate) {
    slideKept(rects);
    playEvents(prev, next, events, rects);
  } else if (dealing) {
    dealIn(next);
    S.busyUntil = flyEnd + 100;
  }
  if (animate || dealing) {
    if (next.status !== "lobby" && $("#prompt")) renderPrompt(next);
    scheduleUnlock(next);
  }
  afterApply(prev, next, animate || dealing);
}

function afterApply(prev, next, animated) {
  const mine = (st) => {
    const g = st?.game;
    if (!g || st.status !== "playing" || st.you.seat == null) return false;
    return g.waiting.includes(st.you.seat);
  };
  if (mine(next) && !mine(prev)) {
    const delay = animated ? Math.max(0, S.busyUntil - performance.now()) : 0;
    setTimeout(() => {
      if (window.innerWidth <= 760) {
        const target = next.game.phase === "play" ? $("#zone-bottom") : next.game.phase === "market" ? $("#market") : $("#prompt");
        target?.scrollIntoView({ behavior: "smooth", block: next.game.phase === "play" ? "end" : "center" });
      }
      sfx.turn();
      if (document.hidden) document.title = "🔔 Your move! · Agent Avenue";
    }, delay);
  }
  if (prev?.status === "playing" && next.status === "game_over") {
    const won = next.game.result && next.you.seat != null && next.seats[next.you.seat].team === next.game.result.winner;
    const delay = Math.max(600, S.busyUntil - performance.now() + 300);
    setTimeout(() => {
      if (next.you.seat == null) sfx.win();
      else if (won) {
        sfx.win();
        confetti();
      } else sfx.lose();
      renderOverlay();
    }, delay);
  }
}

document.addEventListener("visibilitychange", () => {
  if (!document.hidden && S.code) document.title = `Agent Avenue · ${S.code}`;
});

// ------------------------------------------------------------------ shell
function buildShell() {
  const input = h("input", { class: "text", placeholder: "Say something…", maxlength: 240, enterkeyhint: "send", "aria-label": "Chat message" });
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
      h("main", { class: "main", id: "main" }, h("div", { class: "center-msg" }, h("p", {}, "Connecting…"))),
      h(
        "aside",
        { class: "side", id: "side" },
        h("div", { class: "players", id: "players" }),
        h("div", { class: "side-head" }, "Table talk", h("button", { class: "icon-btn only-narrow", onclick: toggleSide, title: "Close" }, "✕")),
        h("div", { class: "feed", id: "feed" }),
        h("div", { class: "reactions" }, REACTIONS.map((emoji) => h("button", { title: "React", onclick: () => send({ type: "react", emoji }) }, emoji))),
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
  const team = entry.seat != null && st?.seats[entry.seat] ? st.seats[entry.seat].team : null;
  const dot = team != null ? h("span", { class: `who t${team}` }) : null;
  return h("div", { class: "entry log", title: time }, dot, richText(entry.text));
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

function iconBtn(icon, title, onclick, cls = "", badge = 0) {
  return h("button", { class: `icon-btn ${cls}`, title, "aria-label": title, onclick }, icon, badge ? h("span", { class: "badge-dot" }, badge) : null);
}

const volumeControl = (() => {
  const btn = h("button", { class: "icon-btn" });
  const range = h("input", { type: "range", min: 0, max: 100, step: 1, class: "vol-range", "aria-label": "Volume" });
  const sync = () => {
    const vol = getVolume();
    const off = isMuted() || vol === 0;
    btn.textContent = off ? "🔇" : vol < 0.4 ? "🔉" : "🔊";
    btn.title = off ? "Sound off — click to turn on" : "Click to mute";
    btn.setAttribute("aria-label", btn.title);
    range.value = String(Math.round(vol * 100));
  };
  btn.addEventListener("click", () => {
    unlockAudio();
    if (isMuted() || getVolume() === 0) {
      setMuted(false);
      if (getVolume() === 0) setVolume(0.85);
      sync();
      sfx.card();
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
  range.addEventListener("change", () => sfx.card());
  sync();
  return h("div", { class: "vol" }, btn, h("div", { class: "vol-pop" }, range));
})();

function renderTop() {
  const top = $("#topbar");
  if (!top) return;
  const st = S.state;
  const g = st?.game;
  let info = "";
  if (st?.status === "lobby") info = "Lobby";
  else if (g) info = `${g.advanced ? "Advanced" : "Simple"} · Turn ${g.turn} · ${plural(g.deck, "card")} in the deck`;
  const before = [
    h("span", { class: "brand", title: "Home", onclick: leaveTable }, h("span", { class: "brand-ico" }), h("span", { class: "brand-text" }, "Agent Avenue")),
    h("span", { class: "chip code", title: "Copy table code", onclick: copyCode }, "# ", S.code),
    h("span", { class: "round-info" }, info),
    h("span", { class: "spacer" }),
    h("button", { class: "btn small ghost rules-btn", onclick: () => showRules(g?.advanced ? "advanced" : "simple") }, iconSvg("book"), h("span", { class: "hide-xs" }, "Rule book")),
  ];
  const after = [iconBtn("💬", "Chat & players", toggleSide, "only-narrow", S.ui.unread), iconBtn("⋯", "Menu", toggleMenu)];
  if (volumeControl.parentNode !== top) top.append(volumeControl);
  for (const el of [...top.children]) if (el !== volumeControl) el.remove();
  volumeControl.before(...before);
  volumeControl.after(...after);
  top.querySelector(".brand-ico").innerHTML = meepleSvg(0);
  document.getElementById("menu")?.remove();
  if (S.ui.menu) document.body.append(renderMenu());
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
    item("🔗 Copy invite link", copyInvite),
    item("📱 Continue on another device", async () => {
      const url = `${inviteUrl()}?me=${S.token}`;
      const ok = await copyText(url);
      toast(ok ? "Personal link copied — open it on your other device (don't share it!)" : url, !ok);
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
  toast(ok ? "Invite link copied — send it to your friends!" : inviteUrl(), !ok);
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
    close = openDialog(
      h(
        "div",
        { class: "modal" },
        h("h2", {}, title),
        h("p", { class: "sub" }, "Pick a name the other players will see."),
        h("form", { onsubmit: done }, input, h("div", { class: "actions" }, h("button", { class: "btn primary", type: "submit" }, "Let's go"))),
      ),
      { dismissable, onClose: () => resolve(null) },
    );
    input.focus();
  });
}

// ------------------------------------------------------------------ rendering
function render() {
  renderTop();
  const st = S.state;
  const main = $("#main");
  if (!st || !main) return;
  const feed = $("#feed");
  const atBottom = feed && feed.scrollHeight - feed.scrollTop - feed.clientHeight < 60;
  renderPlayers(st);
  if (atBottom) feed.scrollTop = feed.scrollHeight;
  if (st.status === "lobby") {
    S.gameEl = null;
    S.board = null;
    S.ui.overShown = false;
    $(".game-over")?.remove();
    renderLobby(st, main);
  } else renderGame(st, main);
}

function avatar(s) {
  const label = s.bot ? "🤖" : (s.name || "?").trim().charAt(0).toUpperCase();
  return h("span", { class: `avatar t${s.team} ${s.bot ? "bot" : s.connected ? "online" : "offline"}` }, label);
}

function teamNames(st, side) {
  const names = st.seats.filter((s) => s.team === side).map((s) => s.name);
  return names.length ? names.join(" & ") : `Team ${TEAM[side]}`;
}

function meepleIcon(team, cls = "") {
  const el = h("span", { class: `mini-meeple ${cls}` });
  el.innerHTML = meepleSvg(team);
  return el;
}

// ------------------------------------------------------------------ lobby
function renderLobby(st, main) {
  const isHost = st.host === S.me;
  const mySeat = st.you.seat;
  const myTeam = mySeat != null ? st.seats[mySeat].team : null;
  const set = st.settings;
  const hostName = st.seats.find((s) => s.member === st.host)?.name || st.spectators.find((s) => s.member === st.host)?.name || "the host";
  const change = (k, v) => send({ type: "settings", changes: { [k]: v } });

  const linkInput = h("input", { class: "text", readonly: true, value: inviteUrl(), onclick: (e) => e.target.select(), "aria-label": "Invite link" });
  const invite = h(
    "div",
    { class: "lobby-invite" },
    h("span", { class: "lbl" }, "Invite link"),
    h(
      "div",
      { class: "link-box" },
      linkInput,
      h("button", { class: "btn primary", onclick: copyInvite }, "📋 Copy link"),
      navigator.share ? h("button", { class: "btn", onclick: () => navigator.share({ title: "Play Agent Avenue with me", url: inviteUrl() }).catch(() => {}) }, "Share") : null,
    ),
  );
  const modeBtn = (value, title, sub) =>
    h(
      "button",
      { class: `seg-btn${set.mode === value ? " on" : ""}`, disabled: !isHost && set.mode !== value, "aria-pressed": set.mode === value ? "true" : "false", onclick: () => isHost && set.mode !== value && change("mode", value) },
      h("b", {}, title),
      h("small", {}, sub),
    );
  const mode = h(
    "div",
    { class: "lobby-mode" },
    h("span", { class: "lbl" }, "Mode", isHost ? null : h("small", {}, " · set by the host")),
    h("div", { class: "seg" }, modeBtn("simple", "Simple", "Pure bluffing — recommended to learn"), modeBtn("advanced", "Advanced", "With black market cards")),
  );

  const teamCol = (team) => {
    const members = st.seats.filter((s) => s.team === team);
    const rows = members.map((s) => {
      const isMe = s.seat === mySeat;
      return h(
        "div",
        { class: "seat-row" },
        avatar(s),
        h("span", { class: "name" }, s.name),
        s.member === st.host ? h("span", { class: "tag host" }, "Host") : null,
        isMe ? h("span", { class: "tag you" }, "You") : null,
        s.bot ? h("span", { class: "tag bot", title: S.bots?.[0]?.description || "" }, "Bot") : null,
        !s.bot && !s.connected ? h("span", { class: "tag" }, "offline") : null,
        h("span", { class: "grow" }),
        (isHost || isMe) && st.seats.filter((x) => x.team === 1 - team).length < MAX_TEAM
          ? h("button", { class: "icon-btn", title: `Move to team ${TEAM[1 - team]}`, onclick: () => (isMe ? send({ type: "sit", team: 1 - team }) : send({ type: "move_seat", seat: s.seat, team: 1 - team })) }, team === 0 ? "→" : "←")
          : null,
        isMe ? h("button", { class: "icon-btn", title: "Leave seat (watch instead)", onclick: () => send({ type: "stand" }) }, "⏏") : null,
        isHost && !isMe ? h("button", { class: "icon-btn", title: "Remove", onclick: () => send({ type: "remove_seat", seat: s.seat }) }, "✕") : null,
      );
    });
    for (let i = members.length; i < MAX_TEAM; i++) {
      const canJoin = myTeam !== team && st.seats.length < 4;
      rows.push(
        h(
          "div",
          { class: "seat-empty" },
          h("span", {}, i === 0 ? "Empty seat" : "Optional teammate"),
          h("span", { class: "grow" }),
          canJoin ? h("button", { class: "btn small", onclick: () => send({ type: "sit", team }) }, mySeat == null ? "Sit here" : "Switch here") : null,
          isHost ? h("button", { class: "btn small bot-add", onclick: () => send({ type: "add_bot", team }) }, "🤖 Add bot") : null,
        ),
      );
    }
    return h("div", { class: `team-col t${team}` }, h("div", { class: "team-head" }, meepleIcon(team), h("div", {}, h("b", {}, `Team ${TEAM[team]}`), h("small", {}, team === 0 ? "Green home" : "Blue home"))), h("div", { class: "seat-list" }, rows));
  };

  const sizes = [0, 1].map((t) => st.seats.filter((s) => s.team === t).length);
  const ready = sizes[0] > 0 && sizes[1] > 0;
  const total = st.seats.length;
  const select = (k, options) =>
    h(
      "select",
      { class: "select", disabled: !isHost, onchange: (e) => change(k, typeof set[k] === "number" ? Number(e.target.value) : e.target.value) },
      options.map(([value, label]) => {
        const opt = h("option", { value }, label);
        opt.selected = String(set[k]) === String(value);
        return opt;
      }),
    );
  const spectators = st.spectators.filter((s) => s.connected);
  const options = h(
    "div",
    { class: "lobby-options" },
    h("label", { class: "opt" }, h("span", {}, "First player"), select("first", [["random", "Random"], ["green", "Team Green"], ["blue", "Team Blue"]])),
    h("label", { class: "opt" }, h("span", {}, "Bot speed"), select("bot_speed", [["slow", "Relaxed"], ["normal", "Normal"], ["fast", "Fast"]])),
    h(
      "label",
      { class: "opt", title: "The autopilot moves when time runs out" },
      h("span", {}, "Turn timer"),
      select("turn_timer", [[0, "Off"], [30, "30 s"], [60, "1 min"], [90, "90 s"], [180, "3 min"]]),
    ),
    h("button", { class: "btn ghost", onclick: () => showRules(set.mode) }, iconSvg("book"), " Rule book"),
  );
  const variant = total > 2 ? "Team variant" : "1 vs 1";
  const actions = isHost
    ? [
        h("button", { class: "btn shuffle", disabled: total < 2, title: "Deal the players into the teams at random", onclick: () => send({ type: "shuffle" }) }, "🔀 Shuffle teams"),
        h("button", { class: "btn primary big start", disabled: !ready, onclick: () => send({ type: "start" }) }, ready ? `🕵️ Start · ${variant} · ${set.mode}` : "Each team needs a player or a bot"),
      ]
    : h("span", { class: "waiting" }, `Waiting for ${hostName} to start the game…`);
  main.replaceChildren(
    h(
      "section",
      { class: "lobby" },
      h("div", { class: "lobby-top" }, invite, mode),
      h("div", { class: "teams" }, teamCol(0), h("div", { class: "vs" }, "VS"), teamCol(1)),
      spectators.length ? h("p", { class: "waiting" }, "Watching: ", spectators.map((s) => s.name).join(", ")) : null,
      mySeat == null ? h("p", { class: "waiting" }, "You are watching. Pick a free seat to play.") : null,
      h("div", { class: "lobby-bottom" }, options, h("div", { class: "lobby-actions" }, actions)),
      agentsStrip(set.mode),
    ),
  );
}

function agentsStrip(mode) {
  const cards = AGENT_ORDER.map((k, i) => {
    const c = agentCard(k, { cls: "strip-card" });
    c.style.setProperty("--i", i);
    return c;
  });
  return h(
    "div",
    { class: "agents-strip", title: "Open the card reference", onclick: () => showRules("cards") },
    h("div", { class: "strip-head" }, h("b", {}, "Meet the neighbours"), h("small", {}, mode === "advanced" ? "38 agents · 15 black market cards" : "38 agents in 8 kinds")),
    h("div", { class: "strip-cards" }, cards),
  );
}

// ------------------------------------------------------------------ side panel: players
function renderPlayers(st) {
  const box = $("#players");
  if (!box) return;
  const g = st.game;
  const isHost = st.host === S.me;
  box.replaceChildren(
    ...st.seats.map((s) => {
      const p = g?.players[s.seat];
      const active = g && st.status === "playing" && g.waiting.includes(s.seat);
      return h(
        "div",
        { class: `pl-row t${s.team}${active ? " active" : ""}`, "data-seat": s.seat },
        avatar(s),
        h("div", { class: "pl-main" }, h("div", { class: "pl-name" }, s.name, s.seat === st.you.seat ? h("small", {}, " (you)") : null), p ? h("div", { class: "pl-sub" }, `${plural(p.hand, "card")} · ${plural(p.discards_left, "discard")} left`) : h("div", { class: "pl-sub" }, `Team ${TEAM[s.team]}`)),
        st.thinking === s.seat ? h("span", { class: "dots", title: "Thinking" }, h("i"), h("i"), h("i")) : null,
        isHost && st.status === "playing" && !s.bot && (!s.connected || s.autoplay)
          ? h("button", { class: "btn small", onclick: () => send({ type: "autoplay", seat: s.seat, on: !s.autoplay }) }, s.autoplay ? "Stop autopilot" : "Autopilot")
          : null,
      );
    }),
  );
}

// ------------------------------------------------------------------ game
function viewerSide(st) {
  return st.you.seat != null ? st.seats[st.you.seat].team : 0;
}

function ensureGame(main) {
  if (S.gameEl && main.contains(S.gameEl)) return;
  S.board = new Board();
  S.gameEl = h(
    "div",
    { class: "game" },
    h("section", { class: "zone top", id: "zone-top" }),
    h("section", { class: "mid" }, h("div", { class: "board-wrap" }, S.board.el), h("aside", { class: "market-col", id: "market" })),
    h("div", { class: "prompt", id: "prompt" }),
    h("section", { class: "zone bottom", id: "zone-bottom" }),
  );
  main.replaceChildren(S.gameEl);
}

// Rough length of the animations for these events (the exact one comes from playEvents).
function estimateMs(events) {
  let t = 0;
  for (const ev of events) {
    if (ev.kind === "play") t += 900;
    else if (ev.kind === "recruit") t += 1360;
    else if (ev.kind === "move") t += ev.steps ? Math.abs(ev.steps) * 190 + 260 : 120;
    else if (ev.kind === "market") t += 1500;
    else if (ev.kind === "draw") t += 300;
    else if (ev.kind === "discard") t += 380;
    else if (["ability_recruit", "steal", "spycation"].includes(ev.kind)) t += 760;
    else if (ev.kind === "reveal") t += 600;
  }
  return t + 150;
}

// While animations run, nothing on the table is clickable; re-render once they are over.
let unlockTimer = null;
function scheduleUnlock(st) {
  clearTimeout(unlockTimer);
  const wait = S.busyUntil - performance.now();
  if (wait > 30) unlockTimer = setTimeout(() => S.state === st && render(), wait + 20);
}

const locked = () => performance.now() < S.busyUntil - 30;

function renderGame(st, main) {
  ensureGame(main);
  const g = st.game;
  const vs = viewerSide(st);
  S.gameEl.classList.toggle("advanced", g.advanced);
  S.gameEl.classList.toggle("teams", st.seats.length > 2);
  S.board.setView(vs, g.advanced);
  for (const side of [0, 1]) if (!S.ui.moving.has(side)) S.board.place(side, g.sides[side].pos);
  renderZone($("#zone-top"), st, 1 - vs, false);
  renderZone($("#zone-bottom"), st, vs, true);
  renderCenter(st);
  renderMarket(st);
  renderPrompt(st);
  if (st.status !== "game_over") $(".game-over")?.remove();
  else if (S.ui.overShown) renderOverlay();
}

function stackEl(side, key, count) {
  const shown = Math.min(count, 3);
  const el = h("div", { class: "stack", "data-fly": `stack-${side}-${key}`, "data-agent": key, title: `${AGENTS[key].name} × ${count}` });
  for (let i = shown - 1; i > 0; i--) el.append(h("div", { class: "stack-under", style: { "--i": i } }));
  el.append(agentCard(key, { size: "mini", level: count }));
  el.append(h("span", { class: "stack-n" }, `×${count}`));
  return el;
}

function tableauEl(st, side) {
  const g = st.game;
  const t = g.sides[side].tableau;
  const keys = AGENT_ORDER.filter((k) => t[k]);
  const owned = g.sides[side].owned;
  const crowd = keys.length + owned.length;
  return h(
    "div",
    { class: `tableau${crowd >= 8 ? " crowded2" : crowd >= 6 ? " crowded" : ""}`, "data-fly": `tab-${side}` },
    keys.length ? keys.map((k) => stackEl(side, k, t[k])) : h("div", { class: "empty-tab" }, "No agents recruited yet"),
    owned.length ? h("div", { class: "owned" }, owned.map((k) => h("div", { class: "owned-card", "data-fly": `owned-${side}-${k}` }, marketCard(k, { size: "mini" })))) : null,
  );
}

function oppHandEl(st, p) {
  const g = st.game;
  const info = g.players[p];
  const seat = st.seats[p];
  const n = info.hand;
  const backs = h("div", { class: "fan", "data-fly": `hand-${p}` });
  const known = (info.known || []).slice(0, n);
  for (let i = 0; i < n; i++) {
    const held = S.ui.hold[`hc-${p}-${i}`] ? " arriving" : "";
    const card = i < known.length ? agentCard(known[i], { size: "tiny", cls: `fan-card known${held}` }) : cardBack({ size: "tiny", cls: `fan-card${held}` });
    if (i < known.length) card.title = `Everyone knows this card is in ${seat.name}'s hand`;
    card.dataset.fly = `hc-${p}-${i}`;
    card.style.setProperty("--i", i);
    backs.append(card);
  }
  backs.style.setProperty("--n", Math.max(1, n));
  const thinking = st.thinking === p;
  const turn = g.waiting.includes(p) && st.status === "playing";
  return h(
    "div",
    { class: `opp-hand${turn ? " turn" : ""}` },
    h("div", { class: "opp-name" }, avatar(seat), h("span", {}, seat.name), thinking ? h("span", { class: "dots" }, h("i"), h("i"), h("i")) : null),
    backs,
    h("div", { class: "disc", "data-fly": `disc-${p}`, title: `${plural(info.discards, "discarded card")} · ${plural(info.discards_left, "discard")} left` }, discardPips(info)),
  );
}

function discardPips(info) {
  return h(
    "div",
    { class: "pips" },
    h("span", { class: "pip-label" }, "Discards"),
    Array.from({ length: info.discards + info.discards_left }, (_, i) => h("i", { class: i < info.discards ? "used" : "" })),
  );
}

function renderZone(el, st, side, bottom) {
  const g = st.game;
  const you = st.you.seat;
  const members = g.sides[side].members;
  const active = g.active === side && st.status === "playing";
  const recruiting = g.phase === "recruit" && g.active !== side && st.status === "playing";
  let badge = null;
  if (st.status === "playing") {
    if (active && g.phase === "play") badge = "Playing";
    else if (recruiting) badge = "Recruiting";
    else if (g.phase === "market" && g.queue[0] === side) badge = "Black market";
    else if (g.phase === "choice" && g.choice?.side === side) badge = MARKET[g.choice.card]?.name;
  } else if (st.status === "game_over" && g.result?.winner === side) badge = "Winner!";
  el.className = `zone ${bottom ? "bottom" : "top"} t${side}${badge ? " live" : ""}`;
  const tag = h(
    "div",
    { class: "zone-tag" },
    h("div", { class: "zone-title" }, meepleIcon(side), h("b", {}, `Team ${TEAM[side]}`)),
    h("span", { class: "zone-names" }, teamNames(st, side)),
    badge ? h("span", { class: "zone-badge" }, badge) : null,
  );
  const others = members.filter((p) => p !== you);
  const hands = others.length ? h("div", { class: "hands" }, others.map((p) => oppHandEl(st, p))) : null;
  const mine = bottom && you != null && members.includes(you);
  const content = mine ? [tableauEl(st, side), hands, myHandEl(st)] : bottom ? [tableauEl(st, side), hands] : [hands, tableauEl(st, side)];
  el.replaceChildren(tag, h("div", { class: "zone-content" }, content));
}

// ---------------------------------------------------------------- my hand and playing cards
function playOptions(g) {
  return g.me.legal.filter((a) => a.type === "play");
}

function myHandEl(st) {
  const g = st.game;
  const me = g.me;
  const info = g.players[st.you.seat];
  const plays = locked() ? [] : playOptions(g);
  const solo = g.sides[g.players[st.you.seat].side].members.length === 1;
  const sel = S.ui.sel;
  const hand = h("div", { class: `hand${S.ui.discardMode ? " discarding" : ""}${plays.length ? " can-play" : ""}`, "data-fly": `hand-${st.you.seat}` });
  me.hand.forEach((key, i) => {
    const pos = sel.indexOf(i);
    let role = null;
    if (pos >= 0) {
      if (solo) role = pos === 0 ? "up" : "down";
      else role = g.up ? "down" : "up";
    }
    const card = agentCard(key, { cls: `hand-card${role ? ` sel sel-${role}` : ""}${S.ui.hold[`h-${i}`] ? " arriving" : ""}` });
    card.dataset.fly = `h-${i}`;
    card.style.setProperty("--i", i);
    card.style.setProperty("--n", me.hand.length);
    if (role) card.append(h("span", { class: "sel-tag" }, role === "up" ? "Face up" : "Face down"));
    const clickable = S.ui.discardMode || plays.length;
    if (clickable) {
      card.tabIndex = 0;
      card.addEventListener("click", () => onHandClick(i));
      card.addEventListener("keydown", (e) => (e.key === "Enter" || e.key === " ") && onHandClick(i));
    }
    hand.append(card);
  });
  if (!me.hand.length) hand.append(h("div", { class: "empty-hand" }, "No cards in hand"));
  return h("div", { class: "my-hand" }, hand, h("div", { class: "disc mine", "data-fly": `disc-${st.you.seat}`, title: me.discards.length ? `Discarded: ${me.discards.map(agentName).join(", ")}` : "No discards yet" }, discardPips(info)));
}

function selectionValid(g, sel) {
  const plays = playOptions(g);
  const keys = sel.map((i) => g.me.hand[i]);
  const solo = g.sides[g.players[S.state.you.seat].side].members.length === 1;
  if (solo) {
    if (keys.length === 1) return plays.some((a) => a.up === keys[0]);
    if (keys.length === 2) return plays.some((a) => a.up === keys[0] && a.down === keys[1]);
    return false;
  }
  if (keys.length !== 1) return false;
  return g.up ? plays.some((a) => a.down === keys[0]) : plays.some((a) => a.up === keys[0]);
}

function onHandClick(i) {
  const st = S.state;
  const g = st?.game;
  if (!g?.me || S.ui.sending) return;
  unlockAudio();
  if (S.ui.discardMode) {
    if (!g.me.can_discard) return;
    S.ui.discardMode = false;
    S.ui.flyFrom = { discard: i };
    act({ type: "discard", card: g.me.hand[i] });
    return;
  }
  const solo = g.sides[g.players[st.you.seat].side].members.length === 1;
  let sel = [...S.ui.sel];
  if (sel.includes(i)) sel = sel.filter((x) => x !== i);
  else if (!solo) sel = [i];
  else if (sel.length < 2) sel.push(i);
  else sel = [sel[0], i];
  if (sel.length && !selectionValid(g, sel)) {
    // a second card with the same name as the face-up one: start over with this card face up
    if (solo && sel.length === 2 && selectionValid(g, [i])) sel = [i];
    else {
      toast(solo && sel.length === 2 ? "The two cards must have different names" : "You can't play that card now", true);
      sfx.error();
      return;
    }
  }
  S.ui.sel = sel;
  sfx.card();
  render();
}

function confirmPlay() {
  const g = S.state.game;
  const sel = S.ui.sel;
  if (!selectionValid(g, sel)) return;
  const solo = g.sides[g.players[S.state.you.seat].side].members.length === 1;
  const keys = sel.map((i) => g.me.hand[i]);
  if (solo) {
    S.ui.flyFrom = { up: sel[0], down: sel[1] };
    act({ type: "play", up: keys[0], down: keys[1] });
  } else if (g.up) {
    S.ui.flyFrom = { down: sel[0] };
    act({ type: "play", up: null, down: keys[0] });
  } else {
    S.ui.flyFrom = { up: sel[0] };
    act({ type: "play", up: keys[0], down: null });
  }
  S.ui.sel = [];
}

// ---------------------------------------------------------------- centre: deck and the two played cards
function renderCenter(st) {
  const g = st.game;
  const c = S.board.center;
  const iRecruit = !locked() && g.phase === "recruit" && st.you.seat != null && g.waiting.includes(st.you.seat) && st.status === "playing";
  const deck = h("div", { class: "pile", "data-fly": "deck" }, g.deck ? cardBack({ cls: "deck-card" }) : h("div", { class: "slot-empty" }, "Empty"), h("span", { class: "pile-n" }, g.deck));
  const slot = (which) => {
    const played = g[which];
    let card;
    if (!played) {
      card = h("div", { class: "slot-empty" }, which === "up" ? "Face up" : "Face down");
    } else if (which === "up" || played.card) {
      card = agentCard(played.card, { cls: which === "down" ? "peek" : "" });
    } else card = cardBack();
    if (S.ui.hold[`slot-${which}`]) card.classList.add("arriving");
    const el = h("div", { class: `slot ${which}${played ? " filled" : ""}${iRecruit ? " pickable" : ""}`, "data-fly": `slot-${which}` }, card, which === "down" && played?.card ? h("span", { class: "peek-tag" }, "Face down") : null);
    if (iRecruit) {
      el.tabIndex = 0;
      el.title = `Recruit the ${which === "up" ? "face-up" : "face-down"} card`;
      const go = () => {
        if (S.ui.sending) return;
        act({ type: "recruit", take: which });
      };
      el.addEventListener("click", go);
      el.addEventListener("keydown", (e) => (e.key === "Enter" || e.key === " ") && go());
      el.append(h("span", { class: "recruit-tag" }, "Recruit"));
    }
    return el;
  };
  c.replaceChildren(h("div", { class: "table-row" }, deck, slot("up"), slot("down")));
}

function renderMarket(st) {
  const g = st.game;
  const box = $("#market");
  if (!g.advanced) {
    box.replaceChildren();
    box.hidden = true;
    return;
  }
  box.hidden = false;
  const mine = !locked() && g.phase === "market" && st.you.seat != null && g.waiting.includes(st.you.seat);
  const supply = g.supply.map((k, i) => {
    const card = marketCard(k, { cls: S.ui.hold[`supply-${i}`] ? "arriving" : "" });
    const el = h("div", { class: `supply${mine ? " pickable" : ""}`, "data-fly": `supply-${i}` }, card);
    if (mine) {
      el.tabIndex = 0;
      const go = () => !S.ui.sending && act({ type: "market", index: i });
      el.addEventListener("click", go);
      el.addEventListener("keydown", (e) => (e.key === "Enter" || e.key === " ") && go());
      el.append(h("span", { class: "recruit-tag" }, "Take"));
    }
    return el;
  });
  const used = g.market_discard.map((k) => MARKET[k]?.name).join(", ");
  box.replaceChildren(
    h(
      "div",
      { class: "market-head" },
      iconSvg("cart"),
      h("b", {}, "Black market"),
      h("span", { class: "mcount", "data-fly": "mdeck", title: "Cards left in the black market deck" }, h("span", { class: "mback" }), `${g.market_deck}`),
      g.market_discard.length ? h("span", { class: "mused", "data-fly": "mdiscard", title: `Used: ${used}` }, `${g.market_discard.length} used`) : h("span", { "data-fly": "mdiscard" }),
    ),
    h("div", { class: "supply-row" }, supply.length ? supply : h("div", { class: "slot-empty" }, "Sold out")),
  );
}

// ---------------------------------------------------------------- the prompt bar
function waitingText(st) {
  const g = st.game;
  const names = g.waiting.map((p) => st.seats[p].name);
  const who = names.length ? names.join(" or ") : teamNames(st, g.active);
  switch (g.phase) {
    case "play":
      return g.up ? `${who} chooses a card to play face down…` : `${who} ${g.sides[g.active].members.length > 1 ? "plays a card face up…" : "plays 2 cards…"}`;
    case "recruit":
      return `${who} decides which card to recruit…`;
    case "market":
      return `${who} is shopping at the black market…`;
    case "choice":
      return `${who} resolves ${MARKET[g.choice.card]?.name}…`;
    default:
      return "";
  }
}

let promptTimer = null;
function renderPrompt(st) {
  const el = $("#prompt");
  const g = st.game;
  // While the last moves are still animating, the next prompt waits (so it doesn't spoil what's coming).
  clearTimeout(promptTimer);
  const wait = S.busyUntil - performance.now();
  if (wait > 30 && ["move", "game_start"].includes(S.state?.event?.kind)) {
    el.className = "prompt";
    el.replaceChildren(h("span", { class: "prompt-text" }, "…"));
    promptTimer = setTimeout(() => S.state === st && renderPrompt(st), wait);
    return;
  }
  const me = g.me;
  const seat = st.you.seat;
  let text = "";
  let buttons = [];
  let cls = "";
  if (st.status === "game_over") {
    const res = g.result;
    const won = seat != null && st.seats[seat].team === res.winner;
    text = seat == null ? `Team ${TEAM[res.winner]} wins!` : won ? "You won! 🎉" : `Team ${TEAM[res.winner]} wins.`;
    cls = won ? "good" : "";
    buttons.push(h("button", { class: "btn small", onclick: () => ((S.ui.overShown = true), renderOverlay()) }, "Show result"));
    if (st.host === S.me) buttons.push(h("button", { class: "btn primary small", onclick: () => send({ type: "play_again" }) }, "Play again"), h("button", { class: "btn small", onclick: () => send({ type: "to_lobby" }) }, "Lobby"));
  } else if (seat != null && me && g.waiting.includes(seat)) {
    cls = "mine";
    const solo = g.sides[g.players[seat].side].members.length === 1;
    if (g.phase === "play") {
      const valid = selectionValid(g, S.ui.sel);
      if (S.ui.discardMode) {
        text = `Click a card to discard it face down and draw a new one (${plural(g.players[seat].discards_left, "discard")} left).`;
        buttons.push(h("button", { class: "btn small", onclick: () => ((S.ui.discardMode = false), render()) }, "Cancel"));
      } else {
        if (solo) {
          const n = S.ui.sel.length;
          text = n === 0 ? "Your turn — pick a card to play face up" : n === 1 ? "Now pick a card to play face down" : "Ready? Your opponent will recruit one of them.";
          buttons.push(h("button", { class: "btn primary", disabled: !valid || n < 2, onclick: confirmPlay }, "Play cards"));
          if (n === 2) buttons.push(h("button", { class: "btn small", onclick: () => ((S.ui.sel = [S.ui.sel[1], S.ui.sel[0]]), selectionValid(g, S.ui.sel) || (S.ui.sel = [S.ui.sel[1], S.ui.sel[0]]), render()) }, "⇄ Swap"));
        } else if (g.up) {
          text = `Your teammate played ${agentName(g.up.card)} face up — pick a card to play face down`;
          buttons.push(h("button", { class: "btn primary", disabled: !valid, onclick: confirmPlay }, "Play face down"));
        } else {
          text = "Your team's turn — pick a card to play face up";
          buttons.push(h("button", { class: "btn primary", disabled: !valid, onclick: confirmPlay }, "Play face up"));
          if (me.can_lead) buttons.push(h("button", { class: "btn small", onclick: () => send({ type: "lead" }) }, "Let teammate lead"));
        }
        if (me.can_discard) buttons.push(h("button", { class: "btn small ghost", onclick: () => ((S.ui.discardMode = true), (S.ui.sel = []), render()) }, `🗑 Discard & draw (${g.players[seat].discards_left})`));
      }
    } else if (g.phase === "recruit") {
      text = `Recruit ${agentName(g.up.card)} (face up) or the face-down card`;
      buttons.push(h("button", { class: "btn primary small", onclick: () => act({ type: "recruit", take: "up" }) }, `Take ${agentName(g.up.card)}`), h("button", { class: "btn primary small", onclick: () => act({ type: "recruit", take: "down" }) }, "Take the face-down card"));
    } else if (g.phase === "market") {
      text = "Black market! Take one of the 3 cards";
      cls += " bm";
    } else if (g.phase === "choice") {
      ({ text, buttons } = choicePrompt(st));
      cls += " bm";
    }
  } else if (st.status === "playing") {
    text = waitingText(st);
    if (g.lead != null && g.phase === "play" && !g.up) text = `${st.seats[g.lead].name} plays the face-up card…`;
  }
  el.className = `prompt ${cls}`;
  el.replaceChildren(h("span", { class: "prompt-text" }, text));
  if (buttons.length) el.append(h("span", { class: "prompt-btns" }, buttons));
  if (st.status === "playing") el.append(h("div", { class: "timer", id: "timer", style: { width: "0" } }));
}

function choicePrompt(st) {
  const g = st.game;
  const ch = g.choice;
  const name = MARKET[ch.card]?.name;
  const pickAgent = (k) => {
    const card = agentCard(k, { size: "mini", cls: "choice-card" });
    card.tabIndex = 0;
    card.title = AGENTS[k].name;
    const go = () => !S.ui.sending && act({ type: "choose", option: k });
    card.addEventListener("click", go);
    card.addEventListener("keydown", (e) => (e.key === "Enter" || e.key === " ") && go());
    return card;
  };
  switch (ch.stage) {
    case "steal":
      return { text: `${name}: choose an agent of the other team to put into your hand`, buttons: ch.options.map(pickAgent) };
    case "spy_pick":
      return { text: `${name}: choose one of your agents to take back into your hand`, buttons: ch.options.map(pickAgent) };
    case "spy_recruit":
      return {
        text: `${name}: recruit ${agentName(ch.agent)} again right away?`,
        buttons: [h("button", { class: "btn primary small", onclick: () => act({ type: "choose", option: true }) }, "Recruit it"), h("button", { class: "btn small", onclick: () => act({ type: "choose", option: false }) }, "Keep it in hand")],
      };
    case "secret":
      return { text: `${name}: recruit an agent from your hand you don't have in play yet`, buttons: ch.options.map(pickAgent) };
    case "double":
      return { text: `${name}: reveal a pair from your hand and recruit one of them`, buttons: ch.options.map(pickAgent) };
    default:
      return { text: name, buttons: [] };
  }
}

// ---------------------------------------------------------------- game over
const REASON_TEXT = {
  caught: "caught the other spy",
  codebreakers: "recruited 3 Codebreakers",
  masterplan: "had 7 different agents (Masterplan)",
  security_system: "had the other spy on their home space (Security System)",
  leader_of_the_pack: "had 3 Daredevils (Leader of the Pack)",
  opponent_daredevils: "the other team recruited 3 Daredevils",
  opponent_caught: "",
  out_of_cards: "the cards ran out and they were closer",
};

function renderOverlay() {
  const st = S.state;
  $(".game-over")?.remove();
  if (!st || st.status !== "game_over" || !st.game?.result) return;
  S.ui.overShown = true;
  const res = st.game.result;
  const seat = st.you.seat;
  const won = seat != null && st.seats[seat].team === res.winner;
  const lost = seat != null && !won;
  const reasons = res.reasons.map((r) => REASON_TEXT[r]).filter(Boolean);
  const loserReasons = (res.claims?.[1 - res.winner] || []).map((r) => REASON_TEXT[r]).filter(Boolean);
  const isHost = st.host === S.me;
  const close = () => {
    S.ui.overShown = false;
    $(".game-over")?.remove();
  };
  const g = st.game;
  const handsReveal = st.seats.map((s) =>
    h("div", { class: "reveal-row" }, h("span", { class: `who t${s.team}` }), h("b", {}, s.name), h("span", { class: "reveal-cards" }, (g.players[s.seat].hand_cards || []).map((k) => agentCard(k, { size: "tiny" })))),
  );
  const panel = h(
    "div",
    { class: `game-over ${won ? "won" : lost ? "lost" : ""}` },
    h(
      "div",
      { class: "go-card" },
      h("div", { class: "go-meeple" }, meepleIcon(res.winner, "big")),
      h("h2", {}, won ? "Mission accomplished!" : lost ? "Your cover is blown!" : `Team ${TEAM[res.winner]} wins!`),
      h("p", { class: "go-sub" }, `${teamNames(st, res.winner)} won: ${reasons.join(", ") || "the game"}.`),
      res.tie
        ? h("p", { class: "go-tie" }, loserReasons.length && res.reasons[0] !== "out_of_cards" ? `${teamNames(st, 1 - res.winner)} also ${loserReasons.join(", ")} — a tie goes to the team whose turn it was.` : "Both spies were equally far apart — a tie goes to the team whose turn it was.")
        : null,
      h("p", { class: "go-turns" }, `After ${plural(res.turn, "turn")}.`),
      h("div", { class: "reveal" }, h("small", {}, "Cards left in hand"), handsReveal),
      h(
        "div",
        { class: "actions" },
        h("button", { class: "btn", onclick: close }, "Look at the table"),
        isHost ? h("button", { class: "btn", onclick: () => send({ type: "to_lobby" }) }, "Back to lobby") : null,
        isHost ? h("button", { class: "btn primary", onclick: () => send({ type: "play_again" }) }, "Play again") : h("span", { class: "waiting" }, "The host can start a new game"),
      ),
    ),
  );
  document.body.append(panel);
}

function confetti() {
  const colors = ["#2f9a5a", "#2d7fd0", "#f2c443", "#ef7a43", "#e8708e", "#9b78c9"];
  for (let i = 0; i < 90; i++) {
    const piece = h("i", { class: "confetti", style: { left: `${Math.random() * 100}vw`, background: colors[i % colors.length], animationDelay: `${Math.random() * 0.6}s`, animationDuration: `${2.2 + Math.random() * 1.6}s`, transform: `rotate(${Math.random() * 360}deg)` } });
    fx.append(piece);
    setTimeout(() => piece.remove(), 4500);
  }
}

function showReaction(msg) {
  const st = S.state;
  let target = msg.seat != null ? $(`.pl-row[data-seat="${msg.seat}"]`) : null;
  if (msg.seat != null && st?.status !== "lobby") {
    const zone = msg.seat === st?.you?.seat ? $("#zone-bottom .zone-head") : $(`.opp-name`)?.closest(".opp-hand");
    target = (msg.seat === st?.you?.seat ? zone : document.querySelector(`[data-fly="hand-${msg.seat}"]`)) || target;
  }
  const r = (target || $("#topbar")).getBoundingClientRect();
  const el = h("div", { class: "reaction", style: { left: `${r.left + r.width / 2}px`, top: `${r.top + r.height / 2}px` } }, msg.emoji);
  fx.append(el);
  setTimeout(() => el.remove(), 2200);
}

// ---------------------------------------------------------------- animations
// Elements that appear because of an event stay invisible until the flying card lands on them.
// Follows every card that leaves or enters a hand in this update: which card of the old layout it flies
// from (`ev._from`, a data-fly key) and which card of the new layout it lands on (`ev._to[i].ref`).
// Cards still on their way in stay hidden (S.ui.hold) and the ones that stay slide to their new place.
function prepareHolds(prev, next, events) {
  const hold = S.ui.hold;
  const g = next.game;
  const you = next.you.seat;
  const pick = S.ui.flyFrom || {};
  S.ui.slide = [];
  for (let p = 0; p < g.players.length; p++) {
    const isMe = p === you && g.me && prev.game.me;
    const prefix = isMe ? "h-" : `hc-${p}-`;
    const cards = isMe ? prev.game.me.hand.map((key, i) => ({ key, old: i })) : Array.from({ length: prev.game.players[p]?.hand ?? 0 }, (_, i) => ({ key: null, old: i }));
    const take = (key, prefer) => {
      const matches = (c) => !isMe || c.key === key;
      let j = prefer != null ? cards.findIndex((c) => c.old === prefer && matches(c)) : -1;
      if (j < 0) j = isMe ? cards.findIndex((c) => c.old != null && matches(c)) : cards.findLastIndex((c) => c.old != null);
      if (j < 0) j = cards.findLastIndex(matches);
      if (j < 0) return null;
      const [c] = cards.splice(j, 1);
      return c.old != null ? `${prefix}${c.old}` : null;
    };
    const arrive = (key) => {
      const c = { key: isMe ? key : null, old: null };
      cards.push(c);
      return c;
    };
    const mine = events.filter((ev) => ev.player === p);
    for (const ev of mine) {
      if (ev.kind === "play") {
        ev._from = {};
        for (const which of ev.slots) ev._from[which] = take(ev[which], isMe ? pick[which] : null);
      } else if (ev.kind === "discard") ev._from = take(ev.card, isMe ? pick.discard : null);
      else if (ev.kind === "ability_recruit" && ev.source !== "smoke_screen") ev._from = take(ev.card, null);
      else if (ev.kind === "draw") ev._to = ev.cards.map(arrive);
      else if (ev.kind === "steal" || ev.kind === "spycation") ev._to = [arrive(ev.card)];
    }
    const final = isMe ? g.me.hand : null;
    const ok = isMe ? cards.length === final.length && cards.every((c, i) => c.key === final[i]) : cards.length === g.players[p].hand;
    if (!ok) {
      // the hand changed in a way we can't follow: no holds, cards fly from and to the whole hand
      for (const ev of mine) ev._from = ev._to = undefined;
      continue;
    }
    cards.forEach((c, i) => {
      c.ref = `${prefix}${i}`;
      if (c.old == null) hold[c.ref] = true;
      else S.ui.slide.push([c.ref, `${prefix}${c.old}`]);
    });
  }
  for (const ev of events) {
    if (ev.kind === "play") for (const which of ev.slots) hold[`slot-${which}`] = true;
    if (ev.kind === "market" && ev.refill) hold[`supply-${ev.index}`] = true;
  }
}

// Cards that stayed in a hand glide from where they were to where they are now.
function slideKept(rects) {
  for (const [now, before] of S.ui.slide || []) {
    const el = flyTarget(now);
    const r0 = rects[before];
    if (!el || !r0) continue;
    const r1 = el.getBoundingClientRect();
    const dx = r0.left + r0.width / 2 - (r1.left + r1.width / 2);
    const dy = r0.top + r0.height / 2 - (r1.top + r1.height / 2);
    if (Math.abs(dx) + Math.abs(dy) < 2) continue;
    el.animate([{ translate: `${dx}px ${dy}px` }, { translate: "0px 0px" }], { duration: 420, easing: "cubic-bezier(.3,.7,.3,1)" });
  }
  S.ui.slide = [];
}

// A held card has arrived: show it (and keep it shown if the table is drawn again meanwhile).
function land(key) {
  delete S.ui.hold[key];
  reveal(flyTarget(key));
}

// At the start of a game the hands are dealt from the deck, one card at a time around the table.
function dealIn(st) {
  const g = st.game;
  const you = st.you.seat;
  const keyOf = (p, i) => (p === you && g.me ? `h-${i}` : `hc-${p}-${i}`);
  const deckEl = flyTarget("deck");
  const deckRect = deckEl?.getBoundingClientRect();
  const counter = deckEl?.querySelector(".pile-n");
  const order = [];
  const most = Math.max(...g.players.map((pl) => pl.hand));
  for (let i = 0; i < most; i++) for (let p = 0; p < g.players.length; p++) if (i < g.players[p].hand) order.push([p, i]);
  let left = g.deck + order.length;
  if (counter) counter.textContent = left;
  const gap = order.length > 8 ? 95 : 120;
  order.forEach(([p, i], n) => {
    const key = keyOf(p, i);
    const face = p === you && g.me ? g.me.hand[i] : null;
    setTimeout(() => {
      if (counter && S.state === st) counter.textContent = --left;
      sfx.card();
    }, n * gap);
    fly(deckRect, () => flyTarget(key), cardBack(), {
      delay: n * gap,
      dur: 520,
      arc: 30,
      flip: face ? (wrap) => flipTo(wrap, agentCard(face)) : null,
      done: () => land(key),
    });
  });
}

// A card-sized box in the middle of `rect` (when a card leaves a whole hand or tableau, not one card).
function cardSized(rect) {
  if (rect.width / rect.height <= 0.85) return rect;
  const h = Math.min(rect.height, 150);
  const w = h / 1.4;
  const left = rect.left + rect.width / 2 - w / 2;
  const top = rect.top + rect.height / 2 - h / 2;
  return { left, top, width: w, height: h, right: left + w, bottom: top + h };
}

// Fly a copy of `node` from `fromRect` to the element `toEl` (or a function returning it, looked up when the
// flight starts, so it lands where the target is by then). Until `delay` has passed the copy waits at its origin.
let flyEnd = 0; // when the last card in the air lands
function fly(fromRect, toEl, node, { delay = 0, dur = 560, flip = null, arc = 50, done = null, fade = false } = {}) {
  flyEnd = Math.max(flyEnd, performance.now() + delay + dur);
  if (!fromRect || !fromRect.width) {
    if (done) setTimeout(done, delay);
    return;
  }
  fromRect = cardSized(fromRect);
  const wrap = flyBox(fromRect, node);
  wrap.style.transform = `translate(${fromRect.left}px, ${fromRect.top}px)`;
  fx.append(wrap);
  setTimeout(() => {
    const el = typeof toEl === "function" ? toEl() : toEl;
    const to = el ? cardSized(el.getBoundingClientRect()) : null;
    const tx = to ? to.left + to.width / 2 - fromRect.width / 2 : fromRect.left;
    const ty = to ? to.top + to.height / 2 - fromRect.height / 2 : fromRect.top - 60;
    const scale = to && to.width ? to.width / fromRect.width : 1;
    const frames = [
      { transform: `translate(${fromRect.left}px, ${fromRect.top}px) scale(1) rotate(0deg)`, opacity: 1 },
      { transform: `translate(${(fromRect.left + tx) / 2}px, ${Math.min(fromRect.top, ty) - arc}px) scale(${(1 + scale) / 2 + 0.08}) rotate(${tx > fromRect.left ? 4 : -4}deg)`, opacity: 1, offset: 0.5 },
      { transform: `translate(${tx}px, ${ty}px) scale(${scale}) rotate(0deg)`, opacity: fade ? 0 : 1 },
    ];
    const anim = wrap.animate(frames, { duration: dur, easing: "cubic-bezier(.4,.1,.25,1)", fill: "both" });
    if (flip) setTimeout(() => flip(wrap), dur * 0.35);
    anim.finished.then(
      () => {
        wrap.remove();
        done?.();
      },
      () => wrap.remove(),
    );
  }, delay);
}

// A fixed box at `rect` holding a card sized to it (cards scale their text with --w).
function flyBox(rect, node) {
  if (node.classList?.contains("card")) node.style.setProperty("--w", `${rect.width}px`);
  return h("div", { class: "fly", style: { width: `${rect.width}px`, height: `${rect.height}px`, "--w": `${rect.width}px` } }, node);
}

function flipTo(wrap, faceNode) {
  if (faceNode.classList?.contains("card")) faceNode.style.setProperty("--w", wrap.style.width);
  const inner = wrap.firstChild;
  inner.animate([{ transform: "rotateY(0deg)" }, { transform: "rotateY(90deg)" }], { duration: 150, fill: "forwards" }).finished.then(() => {
    inner.replaceWith(faceNode);
    faceNode.animate([{ transform: "rotateY(-90deg)" }, { transform: "rotateY(0deg)" }], { duration: 170 });
  });
}

function reveal(el) {
  if (!el) return;
  el.classList.remove("arriving");
  el.animate([{ scale: "1.08" }, { scale: "1" }], { duration: 220, easing: "ease-out" });
}

function bump(el) {
  if (!el) return;
  el.animate([{ scale: "1" }, { scale: "1.1" }, { scale: "1" }], { duration: 280, easing: "ease-out" });
}

const flyTarget = (key) => document.querySelector(`[data-fly="${key}"]`);
const handTarget = (st, player) => flyTarget(`hand-${player}`) || flyTarget(`zone-${player}`);

function playEvents(prev, next, events, rects) {
  const g = next.game;
  const you = next.you.seat;
  const start = performance.now();
  let t = 0;
  const at = (ms, fn) => setTimeout(fn, ms);
  const mine = (p) => p === you;
  // stack counts animate up when their card lands
  const stackHold = {};
  const holdStack = (side, key) => {
    const id = `stack-${side}-${key}`;
    stackHold[id] = (stackHold[id] || 0) + 1;
    const el = flyTarget(id);
    if (!el) return;
    const n = (g.sides[side].tableau[key] || 0) - stackHold[id];
    if (n <= 0) el.classList.add("arriving");
    else el.querySelector(".stack-n").textContent = `×${n}`;
  };
  const landStack = (side, key) => {
    const id = `stack-${side}-${key}`;
    const el = flyTarget(id);
    stackHold[id] = Math.max(0, (stackHold[id] || 1) - 1);
    if (!el) return;
    el.classList.remove("arriving");
    const n = (g.sides[side].tableau[key] || 0) - stackHold[id];
    el.querySelector(".stack-n").textContent = `×${Math.max(1, n)}`;
    bump(el);
    sfx.place();
  };
  for (const ev of events) {
    switch (ev.kind) {
      case "discard": {
        const from = rects[ev._from] || rects[`hand-${ev.player}`];
        fly(from, flyTarget(`disc-${ev.player}`), ev.card ? agentCard(ev.card) : cardBack(), { delay: t, dur: 480, fade: true });
        at(t, () => sfx.card());
        t += 380;
        break;
      }
      case "draw": {
        ev.cards.forEach((card, i) => {
          const ref = ev._to?.[i]?.ref;
          const target = () => (ref && flyTarget(ref)) || handTarget(next, ev.player);
          fly(rects.deck, target, cardBack(), {
            delay: t + i * 110,
            dur: 520,
            flip: card ? (wrap) => flipTo(wrap, agentCard(card)) : null,
            done: () => (ref ? land(ref) : bump(target())),
          });
        });
        at(t, () => sfx.deal(ev.cards.length));
        t += 160 + ev.cards.length * 110;
        break;
      }
      case "play": {
        for (const which of ev.slots) {
          const card = which === "up" ? ev.up : ev.down;
          const from = rects[ev._from?.[which]] || rects[`hand-${ev.player}`];
          const target = flyTarget(`slot-${which}`);
          fly(from, target, card ? agentCard(card) : cardBack(), {
            delay: t,
            dur: 600,
            done: () => {
              delete S.ui.hold[`slot-${which}`];
              reveal(flyTarget(`slot-${which}`)?.firstChild);
            },
          });
          at(t, () => sfx.card());
          t += 260;
        }
        t += 360;
        break;
      }
      case "recruit": {
        const active = 1 - ev.side;
        const takenFrom = ev.take === "up" ? "slot-up" : "slot-down";
        const leftFrom = ev.take === "up" ? "slot-down" : "slot-up";
        holdStack(ev.side, ev.card);
        holdStack(active, ev.other);
        // the face-down card turns over first
        const downRect = rects["slot-down"];
        const flipMs = 420;
        if (downRect) {
          const ghost = flyBox(downRect, cardBack());
          ghost.style.transform = `translate(${downRect.left}px, ${downRect.top}px)`;
          fx.append(ghost);
          at(t, () => {
            sfx.flip();
            flipTo(ghost, agentCard(ev.down));
          });
          at(t + flipMs + 120, () => ghost.remove());
        }
        const upRect = rects["slot-up"];
        if (upRect) {
          const ghost = flyBox(upRect, agentCard(ev.take === "up" ? ev.card : ev.other));
          ghost.style.transform = `translate(${upRect.left}px, ${upRect.top}px)`;
          fx.append(ghost);
          at(t + flipMs + 120, () => ghost.remove());
        }
        t += flipMs + 120;
        const t0 = t;
        fly(rects[takenFrom], flyTarget(`stack-${ev.side}-${ev.card}`) || flyTarget(`tab-${ev.side}`), agentCard(ev.card), { delay: t0, dur: 620, arc: 30, done: () => landStack(ev.side, ev.card) });
        fly(rects[leftFrom], flyTarget(`stack-${active}-${ev.other}`) || flyTarget(`tab-${active}`), agentCard(ev.other), { delay: t0 + 140, dur: 620, arc: 30, done: () => landStack(active, ev.other) });
        at(t0, () => sfx.card());
        t += 820;
        break;
      }
      case "move": {
        if (!ev.steps) {
          at(t, () => S.board.hop(ev.side, ev.from, ev.to));
          t += 120;
          break;
        }
        const n = Math.abs(ev.steps);
        const hopMs = n > 8 ? 150 : 190;
        at(t, () => {
          if (ev.why === "getaway_car" || ev.why === "surveillance_truck") sfx.ability();
          S.board.hop(ev.side, ev.from, ev.to, { hopMs, onStep: (i) => (ev.steps > 0 ? sfx.hop(i) : sfx.back()) }).then(() => {
            sfx.land();
            S.board.glow(ev.to);
          });
        });
        t += n * hopMs + 260;
        break;
      }
      case "market": {
        const owner = ev.side;
        const ongoing = MARKET[ev.card]?.ongoing;
        const target = ongoing ? flyTarget(`owned-${owner}-${ev.card}`) || flyTarget(`tab-${owner}`) : null;
        if (target && ongoing) target.classList.add("arriving");
        at(t, () => sfx.market());
        const from = rects[`supply-${ev.index}`];
        if (ongoing) fly(from, target, marketCard(ev.card), { delay: t, dur: 700, done: () => reveal(target) });
        else showBanner(ev.card, from, t);
        if (ev.refill) {
          const slot = flyTarget(`supply-${ev.index}`);
          const r = rects[`supply-${ev.index}`];
          if (r && slot) {
            const ghost = flyBox(r, marketBack());
            ghost.style.transform = `translate(${r.left}px, ${r.top}px)`;
            at(t + 650, () => {
              fx.append(ghost);
              ghost.animate([{ opacity: 0, transform: `translate(${r.left}px, ${r.top - 30}px) scale(.8)` }, { opacity: 1, transform: `translate(${r.left}px, ${r.top}px) scale(1)` }], { duration: 260, easing: "ease-out" });
              sfx.flip();
            });
            at(t + 950, () => flipTo(ghost, marketCard(ev.refill)));
            at(t + 1300, () => {
              ghost.remove();
              delete S.ui.hold[`supply-${ev.index}`];
              reveal(flyTarget(`supply-${ev.index}`)?.firstChild);
            });
          }
        }
        t += ongoing ? 900 : 1500;
        break;
      }
      case "ability_recruit": {
        holdStack(ev.side, ev.card);
        const from = ev.source === "smoke_screen" ? rects.deck : rects[ev._from] || rects[`hand-${ev.player}`];
        at(t, () => sfx.ability());
        fly(from, flyTarget(`stack-${ev.side}-${ev.card}`) || flyTarget(`tab-${ev.side}`), agentCard(ev.card), { delay: t, dur: 640, done: () => landStack(ev.side, ev.card) });
        t += 760;
        break;
      }
      case "steal":
      case "spycation": {
        const from = rects[`stack-${ev.kind === "steal" ? ev.from : ev.side}-${ev.card}`];
        at(t, () => (ev.kind === "steal" ? sfx.sneaky() : sfx.ability()));
        const ref = ev._to?.[0]?.ref;
        const target = () => (ref && flyTarget(ref)) || handTarget(next, ev.player);
        fly(from, target, agentCard(ev.card), { delay: t, dur: 640, done: () => (ref ? land(ref) : bump(target())) });
        t += 760;
        break;
      }
      case "reveal": {
        at(t, () => sfx.reveal());
        const target = handTarget(next, ev.player);
        if (target) {
          const r = target.getBoundingClientRect();
          const pair = h("div", { class: "reveal-pop", style: { left: `${r.left + r.width / 2}px`, top: `${r.top}px` } }, ev.cards.map((k) => agentCard(k, { size: "mini" })));
          at(t, () => fx.append(pair));
          at(t + 1300, () => pair.remove());
        }
        t += 600;
        break;
      }
      case "turn":
        if (next.you.seat != null && next.seats[next.you.seat].team === ev.side) at(t, () => turnBanner("Your turn"));
        break;
      case "game_over":
        t += 300;
        break;
    }
  }
  S.busyUntil = Math.max(start + t + 150, flyEnd + 60);
  S.ui.flyFrom = null;
  // safety: whatever is still held becomes visible at the end
  at(S.busyUntil - start + 300, () => {
    if (S.state !== next) return;
    S.ui.hold = {};
    for (const el of document.querySelectorAll(".arriving")) el.classList.remove("arriving");
  });
}

function showBanner(key, fromRect, delay) {
  setTimeout(() => {
    const card = marketCard(key, { cls: "banner-card" });
    const wrap = h("div", { class: "ability-pop" }, card);
    fx.append(wrap);
    if (fromRect) {
      const r = wrap.getBoundingClientRect();
      wrap.animate(
        [
          { transform: `translate(${fromRect.left - r.left}px, ${fromRect.top - r.top}px) scale(${fromRect.width / r.width})`, opacity: 0.6 },
          { transform: "translate(0, 0) scale(1)", opacity: 1, offset: 0.35 },
          { transform: "translate(0, 0) scale(1)", opacity: 1, offset: 0.8 },
          { transform: "translate(0, -20px) scale(.9)", opacity: 0 },
        ],
        { duration: 1500, easing: "ease-out", fill: "forwards" },
      );
    }
    setTimeout(() => wrap.remove(), 1550);
  }, delay);
}

function turnBanner(text) {
  const el = h("div", { class: "turn-banner" }, text);
  fx.append(el);
  setTimeout(() => el.remove(), 1500);
}

// ------------------------------------------------------------------ turn timer
function tickTimer() {
  const bar = $("#timer");
  if (bar) {
    const st = S.state;
    if (S.timer.endAt && st?.status === "playing") {
      const left = Math.max(0, S.timer.endAt - performance.now());
      const frac = S.timer.total ? Math.min(1, left / (S.timer.total * 1000)) : 0;
      bar.style.width = `${(frac * 100).toFixed(2)}%`;
      bar.classList.toggle("low", left < 8000);
      const mine = st.you.seat != null && st.game?.waiting.includes(st.you.seat);
      if (left > 0 && left < 5000 && mine) {
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
  try {
    const res = await fetch(`${BASE}api/config`);
    if (res.ok) S.config = await res.json();
    S.bots = S.config.bots;
  } catch {
    /* offline: defaults */
  }
  router();
}

window.addEventListener("resize", () => {
  if (S.state && S.state.status !== "lobby") render();
});
document.addEventListener("pointerdown", unlockAudio, { once: true });
// Read-only hook for the browser checks in scripts/ (ui_check.py).
window.agentAvenue = { state: () => S.state, busy: () => S.ui.sending || S.pending.length > 0 || locked() };
boot();
