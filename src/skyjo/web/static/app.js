import { frameLoop, gameBase, leaveRoom, NAME_KEY, socketUrl, TOKEN_KEY } from "/static/shared/platform.js";
import { copyText, h, openDialog, sleep, toast } from "./dom.js";
import { isMuted, setMuted, sfx, unlockAudio } from "./sound.js";

// The turn timer only draws frames while a timer is running (`tickTimer`, kicked after every render).
const kickTimer = frameLoop(tickTimer, () => S.timer.endAt && S.state?.status === "playing");

const BASE = gameBase(import.meta.url); // /g/<key>/: this game's server routes

// Action ids, mirrored from skyjo.game.actions.
const FLIP = 12;
const DRAW = 24;
const TAKE = 25;
const HUES = [205, 2, 130, 42, 280, 172, 325, 85];
const REACTIONS = ["👍", "😂", "😱", "😡", "🎉", "🤔", "😭", "🔥", "👏", "🙈"];
const ANIMATED = new Set(["draw", "take", "replace", "discard_flip", "flip"]);
const SUMMARY_DELAY = 2200;

const app = document.getElementById("app");
const fx = document.getElementById("fx");
const overlay = document.getElementById("overlay");

const S = {
  config: { public_url: null, lan_url: null, bots: [] },
  token: localStorage.getItem(TOKEN_KEY) || newToken(),
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
  queue: [],
  busy: false,
  lastSeq: 0,
  awaitSeq: null,
  ui: freshUi(),
  timer: { endAt: 0, total: 0, lastTick: 0 },
};
localStorage.setItem(TOKEN_KEY, S.token);

function freshUi() {
  return { flipMode: false, hint: null, sideOpen: false, unread: 0, summaryHidden: false, summaryAt: 0, menu: false };
}

function newToken() {
  const bytes = new Uint8Array(16);
  crypto.getRandomValues(bytes);
  return Array.from(bytes, (b) => b.toString(16).padStart(2, "0")).join("");
}

const ADJECTIVES = ["Sunny", "Lucky", "Cosmic", "Sneaky", "Brave", "Fuzzy", "Witty", "Zippy", "Calm", "Jolly"];
const ANIMALS = ["Otter", "Panda", "Falcon", "Koala", "Fox", "Puffin", "Lynx", "Gecko", "Moose", "Yak"];
const pick = (xs) => xs[Math.floor(Math.random() * xs.length)];
const suggestName = () => `${pick(ADJECTIVES)} ${pick(ANIMALS)}`;

function saveName(name) {
  name = (name || "").trim().slice(0, 20);
  if (!name) return S.name;
  S.name = name;
  localStorage.setItem(NAME_KEY, name);
  return name;
}

// ------------------------------------------------------------------ cards
const vclass = (v) => (v < 0 ? "v-neg" : v === 0 ? "v-zero" : v <= 4 ? "v-low" : v <= 8 ? "v-mid" : "v-high");
const front = (v) =>
  h("div", { class: "face front" }, h("span", { class: "corner tl" }, v), h("span", { class: "num" }, v), h("span", { class: "corner br" }, v));

function cardEl(v, { cls = "", flipIn = false, ...attrs } = {}) {
  if (v === "ghost") return h("div", { class: `card ghost ${cls}`, ...attrs });
  if (v === "x") return h("div", { class: `card removed ${cls}`, ...attrs });
  if (v === null || v === undefined) return h("div", { class: `card down ${cls}`, ...attrs }, h("div", { class: "face back" }));
  if (flipIn) {
    return h("div", { class: `card flip-in ${vclass(v)} ${cls}`, ...attrs }, h("div", { class: "flipper" }, front(v), h("div", { class: "face back" })));
  }
  return h("div", { class: `card up ${vclass(v)} ${cls}`, ...attrs }, front(v));
}

const chip = (v) => h("span", { class: `mini ${vclass(v)}` }, v);

function richText(text) {
  return text.split(/\[(-?\d+)\]/).map((part, i) => (i % 2 ? chip(Number(part)) : part));
}

// ------------------------------------------------------------------ routing

function route() {
  const match = location.pathname.match(/\/r\/([A-Za-z0-9]{4,8})\/?$/);
  closeOverlay();
  if (match) enterRoom(match[1].toUpperCase());
  else leaveRoom();
}
window.addEventListener("popstate", route);

// ------------------------------------------------------------------ home

// ------------------------------------------------------------------ room / socket
async function enterRoom(code) {
  closeSocket();
  Object.assign(S, { code, state: null, log: [], queue: [], fatal: null, me: null, connected: false, retry: 0, lastSeq: 0, awaitSeq: null });
  S.ui = freshUi();
  document.title = `Skyjo · ${code}`;
  if (!S.name) await askName(`Join table ${code}`);
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

function onMessage(msg) {
  switch (msg.type) {
    case "welcome":
      S.me = msg.you;
      S.bots = msg.bots;
      S.log = msg.log;
      S.connected = true;
      S.retry = 0;
      S.awaitSeq = null;
      renderConn();
      renderFeed();
      break;
    case "state":
      S.lastSeq = msg.seq;
      S.queue.push(msg);
      if (!S.busy) drain();
      break;
    case "log":
      S.log.push(msg.entry);
      appendFeed(msg.entry);
      if (msg.entry.kind === "chat" && msg.entry.member !== S.me) {
        sfx.chat();
        if (!S.ui.sideOpen && window.matchMedia("(max-width: 1000px)").matches) {
          S.ui.unread++;
          renderTop();
        }
      }
      break;
    case "react":
      showReaction(msg);
      break;
    case "hint":
      S.ui.hint = msg.action;
      if (msg.action >= FLIP && msg.action < DRAW && S.state?.game?.phase === "PLACE_DRAWN") S.ui.flipMode = true;
      render();
      break;
    case "error":
      toast(msg.message, true);
      sfx.error();
      if (S.awaitSeq != null) {
        S.awaitSeq = null;
        if (!S.busy) render();
      }
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
      h(
        "div",
        {},
        h("h1", { class: "logo" }, "SKYJO"),
        h("h2", {}, message),
        h("p", {}, "Tables close a while after everyone has left."),
        h("button", { class: "btn primary big", onclick: () => leaveRoom() }, "Start a new table"),
      ),
    ),
  );
}

// ------------------------------------------------------------------ state queue + animation
async function drain() {
  S.busy = true;
  while (S.queue.length) {
    const next = S.queue.shift();
    const prev = S.state;
    beforeApply(prev, next);
    if (canAnimate(prev, next)) {
      try {
        await animate(prev, next);
      } catch (e) {
        console.error(e);
        commit(next);
      }
    } else {
      commit(next);
      if (next.event && !canAnimate(prev, next) && prev?.seq === next.seq - 1) eventSound(next.event);
    }
    afterApply(prev, next);
  }
  S.busy = false;
}

function canAnimate(prev, next) {
  return (
    prev?.game &&
    next.game &&
    prev.status === "playing" &&
    next.event &&
    ANIMATED.has(next.event.kind) &&
    next.seq === prev.seq + 1 &&
    S.queue.length < 3 &&
    !document.hidden
  );
}

function eventSound(ev) {
  if (ev.kind === "draw" || ev.kind === "take") sfx.card();
  else if (ev.kind === "replace") sfx.place();
  else if (ev.kind === "flip" || ev.kind === "discard_flip") sfx.flip();
  if (ev.cleared?.length) sfx.clear();
}

function beforeApply(prev, next) {
  const g0 = prev?.game;
  const g1 = next.game;
  const turnChanged = !g0 || !g1 || g0.phase !== g1.phase || g0.current !== g1.current || g0.round !== g1.round;
  if (turnChanged) {
    S.ui.flipMode = false;
    S.ui.hint = null;
  }
  if (next.status !== prev?.status) {
    S.ui.summaryHidden = false;
    if ((next.status === "round_over" || next.status === "game_over") && prev?.status === "playing") {
      S.ui.summaryAt = performance.now() + SUMMARY_DELAY;
      setTimeout(renderOverlay, SUMMARY_DELAY + 20);
    } else S.ui.summaryAt = 0;
  }
}

function afterApply(prev, next) {
  const mySeat = next.you.seat;
  const g = next.game;
  const myTurn = (st) => {
    const gg = st?.game;
    if (!gg || st.status !== "playing" || st.you.seat == null) return false;
    if (gg.phase === "SETUP") return gg.setup_left[st.you.seat] > 0;
    return gg.current === st.you.seat;
  };
  if (myTurn(next) && !myTurn(prev)) {
    sfx.turn();
    if (document.hidden) document.title = "🔔 Your turn! · Skyjo";
  }
  if (prev?.status === "playing" && next.status === "game_over") {
    const won = g.winners?.includes(mySeat);
    setTimeout(() => {
      if (won) {
        sfx.win();
        confetti();
      } else sfx.lose();
    }, SUMMARY_DELAY);
  } else if (prev?.status === "playing" && next.status === "round_over") {
    setTimeout(sfx.round, SUMMARY_DELAY - 400);
  }
}

document.addEventListener("visibilitychange", () => {
  if (!document.hidden && S.code) document.title = `Skyjo · ${S.code}`;
});

function commit(state, ov = {}) {
  S.state = state;
  if (S.awaitSeq != null && state.seq > S.awaitSeq) S.awaitSeq = null;
  const g = state.game;
  if (g && g.time_left != null) {
    S.timer.endAt = performance.now() + g.time_left * 1000;
    S.timer.total = g.time_total;
  } else S.timer.endAt = 0;
  kickTimer();
  render(ov);
}

const $ = (sel) => document.querySelector(sel);
const rectOf = (sel) => $(sel)?.getBoundingClientRect() ?? null;
const slotSel = (seat, pos) => `.board[data-seat="${seat}"] > .card[data-pos="${pos}"]`;
const key = (seat, pos) => `${seat}:${pos}`;

function fly(from, to, value, { flip = false, dur = 430, delay = 0 } = {}) {
  if (!from || !to || !from.width) return Promise.resolve();
  const wrap = h("div", { class: "fly", style: { "--cw": `${from.width}px`, width: `${from.width}px`, height: `${from.height}px` } });
  const card = flip
    ? h("div", { class: `card ${vclass(value)}` }, h("div", { class: "flipper" }, front(value), h("div", { class: "face back" })))
    : cardEl(value);
  wrap.append(card);
  fx.append(wrap);
  const sx = to.width / from.width;
  const sy = to.height / from.height;
  const midX = (from.left + to.left) / 2;
  const midY = Math.min(from.top, to.top) - 28;
  const lift = ((1 + sx) / 2) * 1.12;
  const anim = wrap.animate(
    [
      { transform: `translate(${from.left}px, ${from.top}px) scale(1)` },
      { transform: `translate(${midX}px, ${midY}px) scale(${lift})`, offset: 0.5 },
      { transform: `translate(${to.left}px, ${to.top}px) scale(${sx}, ${sy})` },
    ],
    { duration: dur, delay, easing: "cubic-bezier(.35,.6,.3,1)", fill: "both" },
  );
  if (flip) {
    card.querySelector(".flipper").animate([{ transform: "rotateY(180deg)" }, { transform: "rotateY(0deg)" }], {
      duration: dur,
      delay,
      easing: "ease-in-out",
      fill: "both",
    });
  }
  return anim.finished.then(
    () => wrap.remove(),
    () => wrap.remove(),
  );
}

async function animate(prev, next) {
  const ev = next.event;
  if (ev.kind === "flip") {
    commit(next, { flipIn: new Set([key(ev.seat, ev.pos)]) });
    sfx.flip();
    await sleep(140);
    return;
  }
  if (ev.kind === "draw" || ev.kind === "take") {
    const from = rectOf(ev.kind === "draw" ? "#deck .card" : "#discard .card");
    commit(next, { hideHand: true });
    sfx.card();
    await fly(from, rectOf("#hand .card"), ev.card, { flip: ev.kind === "draw" });
    commit(next);
    return;
  }

  // replace / discard_flip: animate against the previous boards, then settle on the new state.
  const boards = prev.game.boards.map((cells) => [...cells]);
  let discard = prev.game.discard;
  const fromHand = rectOf("#hand .card");
  const fromSlot = rectOf(slotSel(ev.seat, ev.pos));
  const base = { hideHand: true, boards };
  if (ev.kind === "replace") {
    boards[ev.seat][ev.pos] = "ghost";
    commit(next, { ...base, discard });
    sfx.card();
    await Promise.all([
      fly(fromHand, rectOf(slotSel(ev.seat, ev.pos)), ev.card),
      fly(fromSlot, rectOf("#discard .card"), ev.old, { flip: ev.was_hidden, delay: 80 }),
    ]);
    boards[ev.seat][ev.pos] = ev.card;
    discard = ev.old;
    commit(next, { ...base, discard });
    sfx.place();
  } else {
    commit(next, { ...base, discard });
    sfx.card();
    await fly(fromHand, rectOf("#discard .card"), ev.card);
    boards[ev.seat][ev.pos] = ev.revealed;
    discard = ev.card;
    commit(next, { ...base, discard, flipIn: new Set([key(ev.seat, ev.pos)]) });
    sfx.flip();
    await sleep(420);
  }

  if (ev.cleared?.length) {
    const cells = ev.cleared.flatMap((c) => [0, 1, 2].map((r) => [ev.seat, c.col * 3 + r, c.card]));
    commit(next, { ...base, discard, glow: new Set(cells.map(([s, p]) => key(s, p))) });
    sfx.clear();
    await sleep(700);
    const rects = cells.map(([s, p]) => rectOf(slotSel(s, p)));
    cells.forEach(([s, p]) => (boards[s][p] = "x"));
    commit(next, { ...base, discard });
    const target = rectOf("#discard .card");
    await Promise.all(rects.map((r, i) => fly(r, target, cells[i][2], { delay: i * 70, dur: 380 })));
    discard = cells[0][2];
  }
  if (ev.finished) sfx.alert();

  if (ev.round_over) {
    const flipIn = new Set();
    next.game.boards.forEach((cells, s) =>
      cells.forEach((v, p) => {
        if (boards[s][p] === null && v !== null && v !== "x") flipIn.add(key(s, p));
      }),
    );
    commit(next, { flipIn });
    sfx.reveal();
    await sleep(500);
    return;
  }
  commit(next);
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
      h("main", { class: "main", id: "main" }, h("div", { class: "center-msg" }, h("p", {}, "Connecting…"))),
      h(
        "aside",
        { class: "side", id: "side" },
        h("div", { class: "side-head" }, "Table talk", h("button", { class: "icon-btn only-narrow", onclick: toggleSide, title: "Close" }, "✕")),
        h("div", { class: "feed", id: "feed" }),
        h(
          "div",
          { class: "reactions" },
          REACTIONS.map((emoji) => h("button", { title: "React", onclick: () => send({ type: "react", emoji }) }, emoji)),
        ),
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

const seatHue = (seat) => HUES[seat % HUES.length];

function feedEntry(entry) {
  if (entry.kind === "chat") return h("div", { class: "entry chat", title: new Date(entry.ts * 1000).toLocaleTimeString() }, h("b", {}, entry.name), ": ", entry.text);
  const dot = entry.seat != null ? h("span", { class: "who", style: { background: `hsl(${seatHue(entry.seat)} 70% 55%)` } }) : null;
  return h("div", { class: "entry game", title: new Date(entry.ts * 1000).toLocaleTimeString() }, dot, richText(entry.text));
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
  while (feed.children.length > 300) feed.firstChild.remove();
  if (atBottom || entry.member === S.me) feed.scrollTop = feed.scrollHeight;
}

function iconBtn(icon, title, onclick, cls = "", badge = 0) {
  return h("button", { class: `icon-btn ${cls}`, title, "aria-label": title, onclick }, icon, badge ? h("span", { class: "badge-dot" }, badge) : null);
}

function renderTop() {
  const top = $("#topbar");
  if (!top) return;
  const st = S.state;
  const g = st?.game;
  let info = "";
  if (st?.status === "lobby") info = "Lobby";
  else if (g) info = `Round ${g.round + 1} · lowest score wins · game ends at ${g.end_score}`;
  top.replaceChildren(
    ...[
      h("span", { class: "brand", title: "Home", onclick: leaveTable }, "SKYJO"),
      h("span", { class: "chip code", title: "Copy table code", onclick: copyCode }, "📋 ", S.code),
      h("span", { class: "round-info" }, info),
      h("span", { class: "spacer" }),
      g ? iconBtn("📊", "Scores", showScores) : null,
      iconBtn("❓", "How to play", showRules),
      iconBtn(isMuted() ? "🔇" : "🔊", isMuted() ? "Unmute" : "Mute", () => {
        setMuted(!isMuted());
        renderTop();
      }),
      iconBtn("💬", "Chat", toggleSide, "only-narrow", S.ui.unread),
      iconBtn("⋯", "Menu", toggleMenu),
    ].filter(Boolean),
  );
  // The menu lives outside the topbar: the bar clips overflow, and its backdrop-filter would
  // also clip a position: fixed child.
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
  S.code = null;
  S.state = null;
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

// ------------------------------------------------------------------ dialogs
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
        h("form", { onsubmit: done }, input, h("div", { class: "actions" }, h("button", { class: "btn primary", type: "submit" }, "Let's play"))),
      ),
      { dismissable, onClose: () => resolve(null) },
    );
    input.focus();
  });
}

function showRules() {
  const legend = h("div", { class: "legend" }, [-2, -1, 0, 1, 4, 5, 8, 9, 12].map((v) => cardEl(v)));
  let close = null;
  close = openDialog(
    h(
      "div",
      { class: "modal wide" },
      h("h2", {}, "How to play Skyjo"),
      h(
        "div",
        { class: "rules-text" },
        h("p", {}, h("b", {}, "Goal: "), "have the lowest score. The game ends when someone reaches the target (100 by default); the lowest total wins."),
        legend,
        h("h4", {}, "Each round"),
        h(
          "ul",
          {},
          h("li", {}, "Everyone gets 12 face-down cards in a 3 × 4 grid and flips 2 of them. The highest flipped total starts."),
          h("li", {}, "On your turn, ", h("b", {}, "draw from the deck"), " or ", h("b", {}, "take the top discard"), "."),
          h("li", {}, "A drawn card can be swapped with any card in your grid — or thrown on the discard pile, then you flip one face-down card."),
          h("li", {}, "A card taken from the discard must be swapped into your grid."),
          h("li", {}, "Three equal face-up cards in a column are removed. 🎉"),
        ),
        h("h4", {}, "End of a round"),
        h(
          "ul",
          {},
          h("li", {}, "When someone has all cards face up, everyone else plays one last turn."),
          h("li", {}, "All cards are revealed and summed. If the player who ended the round doesn't have the strictly lowest score, their (positive) score is doubled!"),
        ),
        h("h4", {}, "Controls"),
        h(
          "ul",
          {},
          h("li", {}, "Click the deck or discard pile, then click a card in your grid to swap. Click the discard pile while holding a drawn card to throw it away and flip a card."),
          h("li", {}, "Keyboard: ", h("b", {}, "D"), " draw, ", h("b", {}, "T"), " take discard, ", h("b", {}, "X"), " throw away & flip, ", h("b", {}, "H"), " hint, ", h("b", {}, "Esc"), " cancel."),
        ),
      ),
      h("div", { class: "actions" }, h("button", { class: "btn primary", onclick: () => close() }, "Got it")),
    ),
  );
}

function showScores() {
  const st = S.state;
  if (!st?.game) return;
  let close = null;
  close = openDialog(
    h(
      "div",
      { class: "modal wide" },
      h("h2", {}, "Scoreboard"),
      h("p", { class: "sub" }, `Lowest total wins. The game ends when someone reaches ${st.game.end_score}.`),
      scoreTable(st),
      h("div", { class: "actions" }, h("button", { class: "btn primary", onclick: () => close() }, "Close")),
    ),
  );
}

function scoreTable(st, { latest = false } = {}) {
  const g = st.game;
  const leader = Math.min(...g.totals);
  const rows = st.seats.map((s, seat) =>
    h(
      "tr",
      { class: g.rounds.length && g.totals[seat] === leader ? "lead" : "" },
      h("td", { class: "pl" }, s.name, seat === st.you.seat ? " (you)" : ""),
      g.rounds.map((r, i) => {
        const doubled = r.doubled && r.finisher === seat;
        const isLatest = latest && i === g.rounds.length - 1;
        return h(
          "td",
          { class: isLatest ? "latest" : "" },
          doubled ? h("span", { class: "dbl", title: `${r.raw[seat]} doubled` }, `${r.scores[seat]}`) : r.scores[seat],
          r.finisher === seat ? h("span", { class: "fin", title: "Ended the round" }, " 🏁") : null,
          doubled ? h("span", { class: "fin dbl" }, " ×2") : null,
        );
      }),
      h(
        "td",
        { class: "total" },
        g.totals[seat],
        h("div", { class: "bar" }, h("div", { style: { width: `${Math.min(100, (100 * Math.max(0, g.totals[seat])) / g.end_score)}%` } })),
      ),
    ),
  );
  return h(
    "div",
    { class: "scores-wrap" },
    h(
      "table",
      { class: "scores" },
      h("thead", {}, h("tr", {}, h("th", {}, "Player"), g.rounds.map((_, i) => h("th", {}, `R${i + 1}`)), h("th", {}, "Total"))),
      h("tbody", {}, rows),
    ),
  );
}

// ------------------------------------------------------------------ rendering
function render(ov = {}) {
  renderView(ov);
  kickTimer();
}

function renderView(ov = {}) {
  renderTop();
  const st = S.state;
  const main = $("#main");
  if (!st || !main) return;
  if (st.status === "lobby") renderLobby(st, main);
  else renderTable(st, main, ov);
  renderOverlay();
}

let resizeTimer = null;
let lastSize = `${innerWidth}x${innerHeight}`;
window.addEventListener("resize", () => {
  clearTimeout(resizeTimer);
  resizeTimer = setTimeout(() => {
    const size = `${innerWidth}x${innerHeight}`;
    if (size === lastSize || S.busy || !S.state) return;
    lastSize = size;
    render();
  }, 150);
});

function avatar(seat, s, online) {
  const label = s.bot ? "🤖" : (s.name || "?").trim().charAt(0).toUpperCase();
  return h("span", { class: `avatar ${s.bot ? "" : online ? "online" : "offline"}`, style: { "--hue": seatHue(seat) } }, label);
}

function botInfo(keyName) {
  return S.bots.find((b) => b.key === keyName);
}

function renderLobby(st, main) {
  const isHost = st.host === S.me;
  const mySeat = st.you.seat;
  const n = st.seats.length;
  const hostName = st.seats.find((s) => s.member === st.host)?.name || st.spectators.find((s) => s.member === st.host)?.name || "the host";
  const local = ["localhost", "127.0.0.1", "[::1]"].includes(location.hostname);
  let note = null;
  if (!S.config.public_url) {
    if (local && !S.config.lan_url) note = "This link only works on this computer. Restart with `uv run bg serve --tunnel` to invite people over the internet.";
    else if (!location.hostname.endsWith("trycloudflare.com")) note = "Works for people on the same network. For friends elsewhere, run `uv run bg serve --tunnel`.";
  }

  const linkInput = h("input", { class: "text", readonly: true, value: inviteUrl(), onclick: (e) => e.target.select() });
  const invite = h(
    "div",
    { class: "invite" },
    h("div", {}, h("h2", {}, "Invite friends"), h("p", {}, "Anyone who opens the link joins this table. Fill the remaining seats with bots."), note ? h("p", { style: { marginTop: "6px", fontSize: "0.8rem" } }, "ℹ️ ", note) : null),
    h(
      "div",
      { class: "link-box" },
      linkInput,
      h("button", { class: "btn primary", onclick: copyInvite }, "Copy link"),
      navigator.share ? h("button", { class: "btn", onclick: () => navigator.share({ title: "Play Skyjo with me", url: inviteUrl() }).catch(() => {}) }, "Share") : null,
    ),
  );

  const seatRows = st.seats.map((s, i) => {
    const bot = s.bot ? botInfo(s.bot) : null;
    const isMe = i === mySeat;
    return h(
      "div",
      { class: "seat-row" },
      avatar(i, s, s.connected),
      h("span", { class: "name" }, s.name),
      s.member === st.host ? h("span", { class: "tag host" }, "Host") : null,
      isMe ? h("span", { class: "tag you" }, "You") : null,
      bot ? h("span", { class: "tag", title: bot.description }, "★".repeat(bot.stars)) : null,
      !s.bot && !s.connected ? h("span", { class: "tag" }, "offline") : null,
      isMe ? h("button", { class: "btn small ghost", onclick: () => send({ type: "stand" }) }, "Leave seat") : null,
      isHost && !isMe ? h("button", { class: "icon-btn", title: "Remove", onclick: () => send({ type: "remove_seat", seat: i }) }, "✕") : null,
    );
  });
  if (n < 8) seatRows.push(h("div", { class: "seat-empty" }, `${8 - n} empty seat${n === 7 ? "" : "s"} — invite someone or add a bot`));
  const spectators = st.spectators.filter((s) => s.connected);
  const seatsPanel = h(
    "div",
    { class: "panel" },
    h("h3", {}, "Players", h("small", {}, `${n} / 8`)),
    h("div", { class: "seat-list" }, seatRows),
    spectators.length ? h("p", { class: "waiting", style: { fontSize: "0.85rem" } }, "Watching: ", spectators.map((s) => s.name).join(", ")) : null,
    mySeat == null && n < 8 ? h("div", { style: { marginTop: "10px" } }, h("button", { class: "btn primary", onclick: () => send({ type: "sit" }) }, "Take a seat")) : null,
  );

  const botsPanel = h(
    "div",
    { class: "panel" },
    h("h3", {}, "Add a bot", isHost ? null : h("small", {}, "host only")),
    h(
      "div",
      { class: "bot-grid" },
      S.bots.map((b) =>
        h(
          "button",
          { class: "bot-btn", disabled: !isHost || n >= 8, title: b.description, onclick: () => send({ type: "add_bot", bot: b.key }) },
          h("span", { class: "bname" }, b.label),
          h("span", { class: "stars" }, "★".repeat(b.stars), h("span", { style: { opacity: 0.3 } }, "★".repeat(5 - b.stars))),
          h("span", { class: "bdesc" }, b.description),
          b.n_players ? h("span", { class: "bnote" }, `${b.n_players}-player tables only`) : null,
        ),
      ),
    ),
  );

  const set = st.settings;
  const change = (k, v) => send({ type: "settings", changes: { [k]: v } });
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
    "div",
    { class: "panel" },
    h("h3", {}, "Table rules", isHost ? null : h("small", {}, "set by the host")),
    h(
      "div",
      { class: "settings" },
      row("Game ends at", "Lowest total wins once someone hits it", select("end_score", [50, 100, 150, 200].map((v) => [v, `${v} points`]))),
      row("Turn timer", "The autopilot moves when time runs out", select("turn_timer", [[0, "Off"], [15, "15 s"], [30, "30 s"], [60, "1 min"], [120, "2 min"]])),
      row("Bot speed", "How fast bots play their moves", select("bot_speed", [["slow", "Relaxed"], ["normal", "Normal"], ["fast", "Fast"]])),
      row("Column clear", "Three equal cards in a column are removed", toggle("column_clear")),
      row("Double penalty", "Ending the round without the lowest score doubles it", toggle("double_finisher")),
      row("Hints", "Players may ask the Expert bot for advice", toggle("hints")),
    ),
  );

  const actions = isHost
    ? h(
        "div",
        { class: "lobby-actions" },
        h("button", { class: "btn", disabled: n < 2, onclick: () => send({ type: "shuffle" }) }, "🔀 Shuffle seats"),
        h("button", { class: "btn primary big", disabled: n < 2, onclick: () => send({ type: "start" }) }, n < 2 ? "Need 2+ players" : `Start game · ${n} players`),
      )
    : h("div", { class: "lobby-actions" }, h("span", { class: "waiting" }, `Waiting for ${hostName} to start the game…`));

  main.replaceChildren(h("section", { class: "lobby" }, invite, h("div", { class: "lobby-grid" }, seatsPanel, botsPanel, settingsPanel), actions));
}

function isMyTurn(st) {
  const g = st.game;
  const me = st.you.seat;
  if (me == null || st.status !== "playing" || st.seats[me].autoplay || S.awaitSeq != null) return false;
  if (g.phase === "SETUP") return g.setup_left[me] > 0;
  return g.current === me;
}

function hasLastTurn(g, seat, n) {
  if (g.finisher == null || g.current == null || seat === g.finisher) return false;
  const dist = (seat - g.finisher + n) % n;
  const cur = (g.current - g.finisher + n) % n;
  return dist >= cur;
}

function renderTable(st, main, ov) {
  const n = st.seats.length;
  const me = st.you.seat;
  const order = me == null ? [...Array(n).keys()] : Array.from({ length: n - 1 }, (_, i) => (me + 1 + i) % n);
  const opponents = h(
    "div",
    { class: `opponents n${Math.min(order.length, 7)}` },
    order.map((seat) => playerPanel(st, seat, ov, false)),
  );
  const bottom =
    me == null
      ? h("div", { class: "watching" }, "👀 You're watching this game. You'll get a seat when the host returns to the lobby.")
      : h("div", { class: "me" }, playerPanel(st, me, ov, true));
  const section = h("section", { class: "table" }, opponents, renderCenter(st, ov), bottom);
  main.replaceChildren(section);
  fitTable(section);
}

// Opponent card size relative to yours, indexed by number of opponents - 1.
const OPP_RATIO = [0.7, 0.6, 0.52, 0.46, 0.42, 0.4, 0.4];
const BOARD_H = 4.4; // 3 cards of 1.4·cw + 2 gaps of 0.1·cw
const BOARD_W = 4.3; // 4 cards + 3 gaps
const PILE_RATIO = 0.78;
let fitCache = { key: null, fit: null };

// Sizes every card from the space the table really has, so all players fit on one screen.
// Depends only on the viewport and seat count (panel chrome has fixed height), so the layout
// never changes mid-game; it's computed once and reused until the window is resized.
function fitTable(section) {
  const opp = section.querySelector(".opponents");
  const k = opp.children.length;
  const cs = getComputedStyle(section);
  const W = section.offsetWidth - parseFloat(cs.paddingLeft) - parseFloat(cs.paddingRight) - 2;
  const H = section.offsetHeight - parseFloat(cs.paddingTop) - parseFloat(cs.paddingBottom) - 2;
  const meBoard = section.querySelector(".me .board");
  const key = `${W}x${H}|${k}|${meBoard ? 1 : 0}`;
  if (fitCache.key !== key) fitCache = { key, fit: computeFit(section, opp, meBoard, k, W, H, cs) };
  const { cols, ocw, pcw, mcw } = fitCache.fit;
  opp.style.setProperty("--cols", cols);
  section.style.setProperty("--ocw", `${ocw}px`);
  section.style.setProperty("--pcw", `${pcw}px`);
  section.style.setProperty("--mcw", `${mcw}px`);
}

function computeFit(section, opp, meBoard, k, W, H, cs) {
  const panel = opp.querySelector(".player");
  const center = section.querySelector(".center");
  const bottom = section.querySelector(".me, .watching");
  const ocs = getComputedStyle(opp);
  const colGap = parseFloat(ocs.columnGap) || 0;
  const rowGap = parseFloat(ocs.rowGap) || 0;
  const oppBoard = panel?.querySelector(".board");
  const oppChromeH = panel ? panel.offsetHeight - oppBoard.offsetHeight : 0;
  const oppChromeW = panel ? panel.offsetWidth - oppBoard.offsetWidth : 0;
  // Reserve a second status line on narrow screens, where long messages wrap.
  const centerChromeH = center.offsetHeight - center.querySelector("#deck .card").offsetHeight + (W < 600 ? 22 : 0);
  const bottomChromeH = bottom.offsetHeight - (meBoard?.offsetHeight ?? 0);
  const meK = meBoard ? BOARD_H : 0;
  const pileK = 1.4 * PILE_RATIO;
  const r = OPP_RATIO[Math.min(k, 7) - 1];
  const tMax = Math.min(92, (W - 40) / BOARD_W);

  let best = null;
  for (const cols of k <= 4 ? [k] : [k, Math.ceil(k / 2)]) {
    const rows = Math.ceil(k / cols);
    const ocwMax = Math.min(60, ((W - (cols - 1) * colGap) / cols - oppChromeW) / BOARD_W);
    const free = H - 2 * (parseFloat(cs.rowGap) || 0) - rows * oppChromeH - (rows - 1) * rowGap - centerChromeH - bottomChromeH;
    let t = free / (rows * BOARD_H * r + pileK + meK);
    if (r * t > ocwMax) t = (free - rows * BOARD_H * ocwMax) / (pileK + meK);
    t = Math.max(30, Math.min(t, tMax));
    const ocw = Math.max(12, Math.min(ocwMax, (free - (pileK + meK) * t) / (rows * BOARD_H)));
    const score = Math.min(t, ocw / r);
    if (!best || score > best.score) best = { score, cols, t, ocw };
  }
  const floor = (x) => Math.floor(x * 10) / 10;
  return {
    cols: best.cols,
    ocw: floor(best.ocw),
    mcw: floor(best.t),
    pcw: floor(Math.max(34, Math.min(72, PILE_RATIO * best.t, (W - 90) / 3))),
  };
}

function playerPanel(st, seat, ov, mine) {
  const g = st.game;
  const s = st.seats[seat];
  const n = st.seats.length;
  const playing = st.status === "playing";
  const current = playing && g.current === seat;
  const total = g.totals[seat];
  const bot = s.bot ? botInfo(s.bot) : null;
  const boardCells = ov.boards ? ov.boards[seat] : g.boards[seat];
  const visible = boardCells.reduce((acc, v) => acc + (typeof v === "number" ? v : 0), 0);

  let flag = null;
  if (playing && g.phase === "SETUP" && g.setup_left[seat] > 0) flag = h("span", { class: "turn-flag" }, mine ? "Flip 2 cards" : "Flipping…");
  else if (current) flag = h("span", { class: `turn-flag ${g.finisher != null ? "last" : ""}` }, g.finisher != null ? "Last turn" : mine ? "Your turn" : "Playing");
  else if (playing && hasLastTurn(g, seat, n)) flag = h("span", { class: "turn-flag last", style: { opacity: 0.7 } }, "1 turn left");

  const badges = [];
  if (bot && !s.name.startsWith(bot.label)) badges.push(bot.label);
  if (s.autoplay) badges.push("autopilot");
  if (!s.bot && !s.connected) badges.push("offline");

  const isHost = st.host === S.me;
  const takeOver =
    isHost && playing && !s.bot && !s.connected && !s.autoplay
      ? h("button", { class: "btn small take-over", onclick: () => send({ type: "autoplay", seat, on: true }) }, "🤖 Let a bot play")
      : null;

  return h(
    "div",
    {
      class: `player ${current ? "current" : ""} ${g.finisher === seat ? "finisher" : ""}`,
      "data-seat": seat,
      style: { "--hue": seatHue(seat) },
    },
    flag,
    h(
      "div",
      { class: "pinfo" },
      avatar(seat, s, s.connected),
      h("span", { class: "pname", title: s.name }, s.name, mine ? " (you)" : ""),
      badges.length ? h("span", { class: "pbadge" }, badges.join(" · ")) : null,
      h(
        "span",
        { class: `pscore ${total >= g.end_score * 0.8 ? "danger" : ""}`, title: "Total score · visible cards this round" },
        h("b", {}, total),
        h("small", {}, `round: ${visible >= 0 ? "+" : ""}${visible}`),
      ),
    ),
    h(
      "div",
      { class: "board", "data-seat": seat },
      boardCells.map((v, pos) => slotCard(st, seat, pos, v, ov, mine)),
    ),
    takeOver,
  );
}

function slotCard(st, seat, pos, v, ov, mine) {
  const g = st.game;
  const k = key(seat, pos);
  const legal = g.legal;
  const myTurn = mine && isMyTurn(st);
  const opts = { "data-pos": pos, flipIn: ov.flipIn?.has(k) };
  const classes = [];
  if (ov.glow?.has(k)) classes.push("glow");
  let onclick = null;
  if (myTurn && v !== "x" && v !== "ghost") {
    if (g.phase === "SETUP") {
      if (legal.includes(FLIP + pos)) {
        classes.push("clickable", "flip-target");
        onclick = () => act(FLIP + pos);
      }
    } else if (g.phase === "PLACE_DRAWN" && S.ui.flipMode) {
      if (legal.includes(FLIP + pos)) {
        classes.push("clickable", "flip-target");
        onclick = () => act(FLIP + pos);
      }
    } else if ((g.phase === "PLACE_DRAWN" || g.phase === "PLACE_DISCARD") && legal.includes(pos)) {
      classes.push("clickable");
      onclick = () => act(pos);
      if (typeof v === "number" && g.hand != null) {
        const delta = g.hand - v;
        opts["data-delta"] = delta === 0 ? "±0" : delta > 0 ? `+${delta}` : `${delta}`;
        if (delta < 0) classes.push("better");
        if (delta > 0) classes.push("worse");
      } else if (v === null) opts["data-delta"] = "?";
    }
    const hint = S.ui.hint;
    if (hint != null && (hint === pos || (hint === FLIP + pos && (g.phase !== "PLACE_DRAWN" || S.ui.flipMode)))) classes.push("hint");
  }
  const el = cardEl(v, { ...opts, cls: classes.join(" ") });
  if (onclick) el.addEventListener("click", onclick);
  return el;
}

// After sending a move, ignore input until the server's answer is on screen: the board may
// still show an older state while animations drain, and a second click would be stale.
function act(action) {
  if (S.awaitSeq != null) return;
  S.ui.hint = null;
  S.awaitSeq = S.lastSeq;
  send({ type: "action", action });
}

function renderCenter(st, ov) {
  const g = st.game;
  const me = st.you.seat;
  const myTurn = isMyTurn(st);
  const legal = myTurn ? g.legal : [];
  const hint = S.ui.hint;
  const playing = st.status === "playing";

  const deckCls = [];
  if (legal.includes(DRAW)) deckCls.push("clickable");
  if (hint === DRAW && myTurn) deckCls.push("hint");
  const deckCard = g.deck > 0 ? cardEl(null, { cls: deckCls.join(" ") }) : h("div", { class: "card empty" }, "empty");
  if (legal.includes(DRAW)) deckCard.addEventListener("click", () => act(DRAW));

  const discardValue = ov.discard !== undefined ? ov.discard : g.discard;
  const discardCls = [];
  let discardClick = null;
  let discardLabel = "Discard";
  if (legal.includes(TAKE)) {
    discardCls.push("clickable");
    discardClick = () => act(TAKE);
    if (hint === TAKE) discardCls.push("hint");
  } else if (myTurn && g.phase === "PLACE_DRAWN") {
    discardCls.push("clickable", "flip-target");
    discardLabel = S.ui.flipMode ? "Cancel" : "Throw away";
    discardClick = () => {
      S.ui.flipMode = !S.ui.flipMode;
      render();
    };
    if (hint != null && hint >= FLIP && hint < DRAW && !S.ui.flipMode) discardCls.push("hint");
  }
  const discardCard = discardValue == null ? h("div", { class: "card empty" }, "empty") : cardEl(discardValue, { cls: discardCls.join(" ") });
  if (discardClick) discardCard.addEventListener("click", discardClick);

  const holder = g.current;
  const handValue = ov.hideHand ? "ghost" : g.hand;
  let handCard;
  if (handValue == null) handCard = cardEl("ghost");
  else {
    handCard = cardEl(handValue, { cls: myTurn && S.ui.flipMode ? "clickable" : "" });
    if (myTurn && S.ui.flipMode) {
      handCard.addEventListener("click", () => {
        S.ui.flipMode = false;
        render();
      });
    }
  }
  const handLabel = g.hand == null && !ov.hideHand ? "In hand" : holder === me ? "Your card" : `${st.seats[holder]?.name ?? ""}'s card`;

  const piles = h(
    "div",
    { class: "piles" },
    h("div", { class: "pile deck", id: "deck" }, h("div", { class: "deck-stack" }, deckCard), h("span", { class: "plabel" }, `Deck · ${g.deck}`)),
    h("div", { class: "pile discard", id: "discard" }, discardCard, h("span", { class: "plabel" }, discardLabel)),
    h("div", { class: `pile hand ${g.hand == null && !ov.hideHand ? "empty-hand" : ""}`, id: "hand" }, h("div", { class: "hand-slot" }, handCard), h("span", { class: "plabel" }, handLabel)),
  );

  const info = statusInfo(st);
  const status = h(
    "div",
    { class: `status ${info.mine ? "mine" : ""} ${info.final ? "final" : ""}` },
    info.final ? h("span", { class: "final-banner" }, info.final) : null,
    h("span", { class: "stext" }, info.parts),
    info.mine && st.settings.hints && playing && me != null
      ? h("button", { class: "btn small", title: "Ask the Expert bot (H)", onclick: () => send({ type: "hint" }) }, "💡 Hint")
      : null,
    h("div", { class: "timer", id: "timer", style: { width: "0" } }),
  );
  return h("div", { class: "center" }, piles, status);
}

function statusInfo(st) {
  const g = st.game;
  const me = st.you.seat;
  const n = st.seats.length;
  if (st.status === "round_over") return { parts: ["Round over — all cards revealed"] };
  if (st.status === "game_over") return { parts: ["Game over"] };
  if (g.phase === "SETUP") {
    if (me != null && g.setup_left[me] > 0 && !st.seats[me].autoplay) {
      const left = g.setup_left[me];
      return { mine: true, parts: [`Flip ${left} card${left > 1 ? "s" : ""} in your grid to start the round`] };
    }
    const waiting = st.seats.filter((_, i) => g.setup_left[i] > 0).map((s) => s.name);
    return { parts: [waiting.length ? `Waiting for ${waiting.join(", ")} to flip…` : "Starting…"] };
  }
  const cur = g.current;
  const s = st.seats[cur];
  let final = null;
  if (g.finisher != null) {
    final = cur === me ? "⚠️ Last turn!" : `🏁 ${st.seats[g.finisher].name} revealed everything — final turns`;
  }
  if (cur === me && !s.autoplay) {
    if (g.phase === "CHOOSE_SOURCE") {
      const parts = ["Your turn — draw from the deck"];
      if (g.discard != null) parts.push(" or take the ", chip(g.discard));
      return { mine: true, final, parts };
    }
    if (g.phase === "PLACE_DRAWN") {
      return S.ui.flipMode
        ? { mine: true, final, parts: ["Pick a face-down card to flip (click your card to cancel)"] }
        : { mine: true, final, parts: ["Swap the ", chip(g.hand), " into your grid — or click the discard pile to throw it away and flip a card"] };
    }
    return { mine: true, final, parts: ["Swap the ", chip(g.hand), " with any card in your grid"] };
  }
  const who = s.bot ? `${s.name} 🤖` : s.autoplay ? `${s.name} (autopilot)` : s.name;
  if (g.phase === "CHOOSE_SOURCE") return { final, parts: [`${who} is thinking…`] };
  return { final, parts: [`${who} is placing the `, chip(g.hand), "…"] };
}

// ------------------------------------------------------------------ round / game summaries
function closeOverlay() {
  overlay.replaceChildren();
}

function renderOverlay() {
  const st = S.state;
  if (!st || !st.game || (st.status !== "round_over" && st.status !== "game_over") || performance.now() < S.ui.summaryAt) {
    closeOverlay();
    return;
  }
  if (S.ui.summaryHidden) {
    overlay.replaceChildren(
      h(
        "div",
        { class: "mini-bar" },
        st.status === "game_over" ? "🏆 Game over" : "Round over",
        h("button", { class: "btn small primary", onclick: () => ((S.ui.summaryHidden = false), renderOverlay()) }, "Show scores"),
      ),
    );
    return;
  }
  overlay.replaceChildren(h("div", { class: "backdrop" }, st.status === "game_over" ? gameOverModal(st) : roundModal(st)));
}

function roundModal(st) {
  const g = st.game;
  const r = g.rounds[g.rounds.length - 1];
  const me = st.you.seat;
  let note = "The round hit the turn limit.";
  if (r.finisher != null) {
    const name = st.seats[r.finisher].name;
    if (r.doubled) note = `🏁 ${name} ended the round but didn't have the lowest score — ${r.raw[r.finisher]} doubled to ${r.scores[r.finisher]}! 😬`;
    else if (r.raw[r.finisher] <= 0) note = `🏁 ${name} ended the round with ${r.raw[r.finisher]} points — no penalty.`;
    else note = `🏁 ${name} ended the round with the lowest score. Well played!`;
  }
  const humans = st.seats.map((s, i) => ({ ...s, i })).filter((s) => !s.bot && !s.autoplay);
  const meReady = me != null && st.seats[me].ready;
  const isHost = st.host === S.me;
  const waitingFor = humans.filter((s) => !s.ready && s.connected).map((s) => s.name);
  return h(
    "div",
    { class: "modal wide" },
    h("h2", {}, `Round ${g.rounds.length} complete`),
    h("p", { class: "round-note" }, note),
    scoreTable(st, { latest: true }),
    humans.length
      ? h(
          "div",
          { class: "ready-list", style: { marginTop: "14px" } },
          humans.map((s) => h("span", { class: `chip ${s.ready ? "ok" : ""}` }, s.ready ? "✅" : s.connected ? "⏳" : "📴", " ", s.name)),
        )
      : h("p", { class: "sub", style: { marginTop: "12px" } }, "Next round starts automatically…"),
    h(
      "div",
      { class: "actions" },
      h("span", { class: "grow" }, waitingFor.length ? `Waiting for ${waitingFor.join(", ")}` : ""),
      h("button", { class: "btn ghost", onclick: () => ((S.ui.summaryHidden = true), renderOverlay()) }, "👀 Look at the boards"),
      isHost && waitingFor.length && !(waitingFor.length === 1 && !meReady && me != null)
        ? h("button", { class: "btn", onclick: () => send({ type: "continue" }) }, "Skip waiting")
        : null,
      me != null && !meReady ? h("button", { class: "btn primary", onclick: () => send({ type: "ready" }) }, "Next round ▶") : null,
    ),
  );
}

function gameOverModal(st) {
  const g = st.game;
  const me = st.you.seat;
  const isHost = st.host === S.me;
  const ranking = st.seats.map((s, i) => ({ ...s, i, total: g.totals[i] })).sort((a, b) => a.total - b.total);
  const winners = g.winners.map((w) => st.seats[w].name);
  let title = winners.length > 1 ? `🤝 ${winners.join(" & ")} share the win!` : `🏆 ${winners[0]} wins!`;
  if (me != null && g.winners.includes(me)) title = winners.length > 1 ? "🤝 You share the win!" : "🏆 You win!";
  const podiumOrder = [ranking[1], ranking[0], ranking[2]].filter(Boolean);
  const place = (p) => ranking.findIndex((x) => x.total === p.total) + 1;
  return h(
    "div",
    { class: "modal wide" },
    h("h2", { style: { textAlign: "center" } }, title),
    h(
      "div",
      { class: "podium" },
      podiumOrder.map((p) =>
        h(
          "div",
          { class: `step p${place(p)}` },
          h("span", { class: "pname" }, p.name),
          h("span", { class: "pts" }, `${p.total} pts`),
          h("div", { class: "block" }, place(p)),
        ),
      ),
    ),
    scoreTable(st, { latest: true }),
    h(
      "div",
      { class: "actions" },
      h("button", { class: "btn ghost", onclick: () => ((S.ui.summaryHidden = true), renderOverlay()) }, "👀 Look at the boards"),
      isHost ? h("button", { class: "btn", onclick: () => send({ type: "to_lobby" }) }, "Back to lobby") : null,
      isHost
        ? h("button", { class: "btn primary", onclick: () => send({ type: "play_again" }) }, "Play again ↻")
        : h("span", { class: "grow", style: { textAlign: "right" } }, "Waiting for the host to start a rematch…"),
    ),
  );
}

function confetti() {
  const layer = h("div", { class: "confetti" });
  const colors = ["#3443b5", "#46c4f0", "#5cc04a", "#f6d23a", "#e64a3c", "#ffffff"];
  for (let i = 0; i < 90; i++) {
    layer.append(
      h("i", {
        style: {
          left: `${Math.random() * 100}%`,
          background: pick(colors),
          animationDuration: `${2.2 + Math.random() * 2}s`,
          animationDelay: `${Math.random() * 0.8}s`,
          transform: `rotate(${Math.random() * 360}deg)`,
        },
      }),
    );
  }
  document.body.append(layer);
  setTimeout(() => layer.remove(), 5200);
}

// ------------------------------------------------------------------ reactions
function showReaction(msg) {
  const st = S.state;
  const name = st?.seats.find((s) => s.member === msg.member)?.name || st?.spectators.find((s) => s.member === msg.member)?.name || "";
  let rect = msg.seat != null ? rectOf(`.player[data-seat="${msg.seat}"]`) : null;
  if (!rect) rect = rectOf(".seat-list") || rectOf("#main");
  if (!rect) return;
  const bubble = h(
    "div",
    { class: "bubble", style: { left: `${rect.left + rect.width / 2 + (Math.random() - 0.5) * 40}px`, top: `${rect.top + 10}px` } },
    msg.emoji,
    h("small", {}, name),
  );
  document.body.append(bubble);
  setTimeout(() => bubble.remove(), 2300);
}

// ------------------------------------------------------------------ timer + keyboard
function tickTimer() {
  const bar = $("#timer");
  if (bar) {
    const st = S.state;
    if (S.timer.endAt && st?.status === "playing") {
      const left = Math.max(0, S.timer.endAt - performance.now());
      const frac = S.timer.total ? left / (S.timer.total * 1000) : 0;
      bar.style.width = `${(frac * 100).toFixed(2)}%`;
      bar.classList.toggle("low", left < 5000);
      if (left > 0 && left < 5000 && isMyTurn(st)) {
        const sec = Math.ceil(left / 1000);
        if (sec !== S.timer.lastTick) {
          S.timer.lastTick = sec;
          sfx.tick();
        }
      }
    } else bar.style.width = "0";
  }
}

document.addEventListener("keydown", (e) => {
  if (e.target.closest("input, textarea, select") || e.metaKey || e.ctrlKey || e.altKey) return;
  const st = S.state;
  if (!st?.game || !isMyTurn(st)) return;
  const g = st.game;
  const k = e.key.toLowerCase();
  if (k === "d" && g.legal.includes(DRAW)) act(DRAW);
  else if (k === "t" && g.legal.includes(TAKE)) act(TAKE);
  else if (k === "x" && g.phase === "PLACE_DRAWN") {
    S.ui.flipMode = !S.ui.flipMode;
    render();
  } else if (k === "h" && st.settings.hints) send({ type: "hint" });
  else if (k === "escape" && S.ui.flipMode) {
    S.ui.flipMode = false;
    render();
  }
});

for (const ev of ["pointerdown", "keydown"]) window.addEventListener(ev, unlockAudio, { capture: true });

// ------------------------------------------------------------------ boot
fetch(`${BASE}api/config`)
  .then((r) => r.json())
  .then((config) => {
    S.config = config;
    if (S.state?.status === "lobby") render();
  })
  .catch(() => {});
route();
