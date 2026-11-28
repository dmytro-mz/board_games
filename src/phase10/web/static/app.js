import { frameLoop, gameBase, leaveRoom, NAME_KEY, socketUrl, TOKEN_KEY } from "/static/shared/platform.js";
import { backEl, cardEl, checkGroup, chip, endsFor, groupTitle, isNum, isSkip, isWild, reqLabel, richText, sortByColor, sortByValue, whyNot } from "./cards.js";
import { copyText, h, openDialog, toast } from "./dom.js";
import { HandView } from "./hand.js";
import { getVolume, isMuted, setMuted, setVolume, sfx, unlockAudio } from "./sound.js";

// The turn timer only draws frames while a timer is running (`tickTimer`, kicked after every render).
const kickTimer = frameLoop(tickTimer, () => S.timer.endAt && S.state?.status === "playing");

const BASE = gameBase(import.meta.url); // /g/<key>/: this game's server routes

const SUMMARY_DELAY = 1500;
const SEAT_FILL = { coral: "#ff7a59", sky: "#4cb4ff", lime: "#8bd448", gold: "#ffc94a", violet: "#b48cff", teal: "#3fd1c2" };

const app = document.getElementById("app");
const overlay = document.getElementById("overlay");
const reducedMotion = window.matchMedia("(prefers-reduced-motion: reduce)");

const URL_TOKEN = takeTokenFromUrl();

const S = {
  config: { public_url: null, lan_url: null, bots: [], phases: [], reactions: [], max_seats: 6 },
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
  hand: null,
  ui: freshUi(),
  timer: { endAt: 0, total: 0, lastTick: 0 },
};
localStorage.setItem(TOKEN_KEY, S.token);

function freshUi() {
  return {
    sideOpen: false,
    unread: 0,
    menu: false,
    overlayHidden: false,
    summaryAt: 0,
    pending: false,
    selected: new Set(),
    slots: [],
    slotsKey: "",
    fresh: new Set(),
  };
}

// "Continue on another device" links carry the player's token: /r/CODE?me=TOKEN.
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

const ADJECTIVES = ["Lucky", "Wild", "Sly", "Swift", "Bold", "Clever", "Sunny", "Cosmic", "Jolly", "Daring"];
const NOUNS = ["Shuffler", "Dealer", "Runner", "Joker", "Ace", "Player", "Skipper", "Sharp", "Gambler", "Champ"];
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
const plural = (n, w) => `${n} ${n === 1 ? w : `${w}s`}`;
const seatName = (st, seat) => st.seats[seat]?.name || "?";
const seatFill = (color) => SEAT_FILL[color] || "#9aa7b8";
const phaseInfo = (n) => S.config.phases[n - 1];

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
  const letters = [..."PHASE"].map((ch, i) => h("span", { class: `lg l${i}` }, ch));
  return h("div", { class: `logo ${small ? "small" : ""}` }, h("span", { class: "logo-word" }, letters), h("span", { class: "logo-ten" }, "10"));
}

function homeFan() {
  const cards = [
    { id: -1, k: "n", v: 7, c: "red" },
    { id: -2, k: "n", v: 8, c: "blue" },
    { id: -3, k: "w", v: 0, c: null },
    { id: -4, k: "n", v: 10, c: "green" },
    { id: -5, k: "n", v: 11, c: "yellow" },
  ];
  return h("div", { class: "home-fan" }, cards.map((c, i) => cardEl(c, { attrs: { style: { "--i": i - 2 } } })));
}

function floatingCards() {
  const layer = h("div", { class: "home-float" });
  const colors = ["red", "blue", "green", "yellow"];
  let seed = 11;
  const rnd = () => ((seed = (seed * 16807) % 2147483647) / 2147483647);
  for (let i = 0; i < 16; i++) {
    const r = rnd();
    const c = r < 0.12 ? { id: -10 - i, k: "w" } : r < 0.18 ? { id: -10 - i, k: "s" } : { id: -10 - i, k: "n", v: 1 + Math.floor(rnd() * 12), c: colors[Math.floor(rnd() * 4)] };
    layer.append(cardEl(c, { attrs: { style: { left: `${rnd() * 96}%`, top: `${rnd() * 92}%`, "--rot": `${rnd() * 70 - 35}deg`, "--d": `${-rnd() * 12}s` } } }));
  }
  return layer;
}


// ------------------------------------------------------------------ room / socket
async function enterRoom(code) {
  closeSocket();
  Object.assign(S, { code, state: null, log: [], fatal: null, me: null, connected: false, retry: 0 });
  S.ui = freshUi();
  S.hand = null;
  document.title = `Phase 10 · ${code}`;
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
  S.ui.pending = true;
  closePopover();
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
      showFatal(msg.message);
      break;
  }
}

function showFatal(message) {
  app.replaceChildren(
    h(
      "div",
      { class: "center-msg" },
      h("div", {}, logo(true), h("h2", {}, message), h("p", {}, "Tables close a while after everyone has left."), h("button", { class: "btn primary big", onclick: () => leaveRoom() }, "Start a new table")),
    ),
  );
}

// ------------------------------------------------------------------ state
const myHand = (st) => st?.game?.hand || [];
const myReqs = (st) => {
  const seat = st.you.seat;
  if (seat == null || !st.game) return [];
  return phaseInfo(st.game.players[seat].phase).reqs;
};

// Staged groups live in the client until the phase is laid down; they reset with every new hand or phase.
function syncStaging(st) {
  const ui = S.ui;
  const g = st.game;
  const seat = st.you.seat;
  if (!g || seat == null) {
    ui.slots = [];
    ui.selected.clear();
    return;
  }
  const me = g.players[seat];
  const key = `${st.room}:${g.hand_no}:${me.phase}:${me.laid}`;
  const reqs = myReqs(st);
  if (ui.slotsKey !== key) {
    ui.slotsKey = key;
    ui.slots = me.laid ? [] : reqs.map(() => null);
  }
  const held = new Set(myHand(st).map((c) => c.id));
  ui.slots = ui.slots.map((s) => (s && s.ids.every((id) => held.has(id)) ? s : null));
  const staged = stagedIds();
  for (const id of [...ui.selected]) if (!held.has(id) || staged.has(id)) ui.selected.delete(id);
}

function stagedIds() {
  return new Set(S.ui.slots.flatMap((s) => (s ? s.ids : [])));
}

function applyState(next) {
  const prev = S.state;
  const live = prev && next.seq === prev.seq + 1 && !document.hidden && next.status !== "lobby";
  const before = live ? captureRects() : null;
  S.state = next;
  S.ui.pending = false;
  if (!prev) renderFeed();
  const g = next.game;
  if (g && g.time_left != null) {
    S.timer.endAt = performance.now() + g.time_left * 1000;
    S.timer.total = g.time_total;
  } else S.timer.endAt = 0;
  kickTimer();
  if (next.event?.kind === "game_start") {
    S.ui = { ...freshUi(), sideOpen: S.ui.sideOpen };
  }
  const events = next.event?.events || [];
  const prevIds = new Set(myHand(prev).map((c) => c.id));
  const sameHand = prev?.game && g && prev.game.hand_no === g.hand_no;
  S.ui.fresh = new Set(sameHand ? myHand(next).filter((c) => !prevIds.has(c.id)).map((c) => c.id) : []);
  const step = g?.step;
  if (step !== prev?.game?.step || next.status !== prev?.status) {
    if ((step === "hand_over" || step === "game_over") && live) {
      S.ui.overlayHidden = false;
      S.ui.summaryAt = performance.now() + SUMMARY_DELAY;
      setTimeout(renderOverlay, SUMMARY_DELAY + 20);
    } else if (step !== "hand_over" && step !== "game_over") {
      S.ui.summaryAt = 0;
      S.ui.overlayHidden = false;
    }
  }
  syncStaging(next);
  render();
  if (live) playEffects(next, events, before);
  afterApply(prev, next);
}

function afterApply(prev, next) {
  const mine = (st) => st?.status === "playing" && st.game?.options?.draw_deck !== undefined && st.game.step === "draw";
  if (mine(next) && !mine(prev)) {
    sfx.turn();
    if (document.hidden) document.title = "🔔 Your turn! · Phase 10";
  }
  if (prev?.status === "playing" && next.status === "game_over") {
    const won = next.game.result?.winners.includes(next.you.seat);
    setTimeout(() => {
      if (won) {
        sfx.fanfare();
        confetti();
      } else sfx.lose();
    }, SUMMARY_DELAY);
  }
}

document.addEventListener("visibilitychange", () => {
  if (!document.hidden && S.code) document.title = `Phase 10 · ${S.code}`;
});

// ------------------------------------------------------------------ effects
function rectOf(sel) {
  const el = typeof sel === "string" ? $(sel) : sel;
  if (!el) return null;
  const r = el.getBoundingClientRect();
  return r.width ? r : null;
}

function seatAnchor(seat) {
  if (seat === S.state?.you.seat) return rectOf("#hand-anchor");
  return rectOf(`.opp[data-seat="${seat}"] .opp-count`) || rectOf(`.opp[data-seat="${seat}"]`);
}

function captureRects() {
  const seats = new Map();
  for (const s of S.state?.seats || []) seats.set(s.seat, seatAnchor(s.seat));
  return { hand: S.hand ? S.hand.rects() : new Map(), seats, deck: rectOf("#deck .card"), discard: rectOf("#discard .top") };
}

function fly(node, from, to, { delay = 0, dur = 420, hide = null } = {}) {
  if (!from || !to || reducedMotion.matches) return;
  node.classList.add("flyer");
  Object.assign(node.style, { left: `${to.left}px`, top: `${to.top}px`, width: `${to.width}px`, height: `${to.height}px` });
  node.style.setProperty("--cw", `${to.width}px`);
  document.body.append(node);
  const sx = from.width / to.width;
  const dx = from.left + from.width / 2 - (to.left + to.width / 2);
  const dy = from.top + from.height / 2 - (to.top + to.height / 2);
  if (hide) hide.style.visibility = "hidden";
  const anim = node.animate(
    [
      { transform: `translate(${dx}px, ${dy}px) scale(${sx}) rotate(-8deg)`, opacity: 0.85 },
      { transform: "none", opacity: 1 },
    ],
    { duration: dur, delay, easing: "cubic-bezier(.25,.8,.3,1)", fill: "backwards" },
  );
  anim.onfinish = () => {
    node.remove();
    if (hide) hide.style.visibility = "";
  };
}

function smallRect(r, w = 44) {
  if (!r) return null;
  const hgt = w * 1.45;
  return { left: r.left + r.width / 2 - w / 2, top: r.top + r.height / 2 - hgt / 2, width: w, height: hgt };
}

function banner(cls, title, sub = null, ms = 1800) {
  const wrap = $("#table-wrap");
  if (!wrap) return;
  const el = h("div", { class: `banner ${cls}` }, h("div", { class: "bn-title" }, title), sub ? h("div", { class: "bn-sub" }, sub) : null);
  wrap.append(el);
  setTimeout(() => el.remove(), ms);
}

function playEffects(st, events, before) {
  const me = st.you.seat;
  const g = st.game;
  for (const ev of events) {
    const name = seatName(st, ev.seat);
    switch (ev.kind) {
      case "deal": {
        sfx.shuffle();
        const deck = rectOf("#deck .card");
        [...(S.hand?.el.children || [])].forEach((el, i) => {
          const c = myHand(st).find((x) => x.id === Number(el.dataset.id));
          if (c) fly(cardEl(c), deck, el.getBoundingClientRect(), { delay: 80 + i * 55, dur: 380, hide: el });
        });
        break;
      }
      case "draw": {
        sfx.draw();
        const from = ev.from === "deck" ? before.deck : before.discard;
        if (ev.seat === me) {
          const el = S.hand?.el.querySelector(`[data-id="${ev.card.id}"]`);
          if (el) fly(cardEl(ev.card), from, el.getBoundingClientRect(), { hide: el });
        } else {
          fly(ev.card ? cardEl(ev.card) : backEl(), from, smallRect(seatAnchor(ev.seat)), { dur: 460 });
        }
        break;
      }
      case "discard": {
        sfx.snap();
        const top = $("#discard .top");
        const from = ev.seat === me ? before.hand.get(ev.card.id) : smallRect(before.seats.get(ev.seat));
        if (ev.target == null) fly(cardEl(ev.card), from, rectOf(top), { hide: top });
        else {
          const badge = $(ev.target === me ? ".mine .skip-badge" : `.opp[data-seat="${ev.target}"] .skip-badge`);
          fly(cardEl(ev.card), from, smallRect(rectOf(badge) || seatAnchor(ev.target), 34));
          setTimeout(sfx.skip, 250);
          banner("skip", `⛔ ${seatName(st, ev.target)} is skipped`, `${name} played a Skip`);
        }
        break;
      }
      case "hit": {
        sfx.snap();
        const el = $(`.group[data-group="${ev.group}"] .card[data-id="${ev.card.id}"]`);
        const from = ev.seat === me ? before.hand.get(ev.card.id) : smallRect(before.seats.get(ev.seat));
        if (el) fly(cardEl(ev.card), from, el.getBoundingClientRect(), { hide: el });
        break;
      }
      case "lay_down": {
        sfx.phase();
        let i = 0;
        for (const gid of ev.groups) {
          const group = g.groups.find((x) => x.id === gid);
          for (const c of group?.cards || []) {
            const el = $(`.group[data-group="${gid}"] .card[data-id="${c.id}"]`);
            const from = ev.seat === me ? before.hand.get(c.id) : smallRect(before.seats.get(ev.seat));
            if (el) fly(cardEl(c), from, el.getBoundingClientRect(), { hide: el, delay: i++ * 45 });
          }
        }
        if (ev.seat !== me) banner("phase", `${name} made phase ${ev.phase}!`, phaseInfo(ev.phase).label);
        break;
      }
      case "skipped": {
        if (ev.card) {
          const top = $("#discard .top");
          const from = ev.seat === me ? smallRect(rectOf("#hand-anchor"), 34) : smallRect(before.seats.get(ev.seat), 34);
          fly(cardEl(ev.card), from, rectOf(top), { hide: top, delay: 350 });
        }
        if (ev.seat === me) banner("skip", "⛔ You lose this turn", "Someone played a Skip on you");
        break;
      }
      case "reshuffle":
        sfx.shuffle();
        break;
      case "out":
        sfx.out();
        banner("out", ev.seat === me ? "🏁 You went out!" : `🏁 ${name} goes out!`, "The hand is over", 1500);
        break;
    }
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
      h("main", { class: "main", id: "main" }, h("div", { class: "center-msg" }, h("p", {}, "Shuffling the deck…"))),
      h(
        "aside",
        { class: "side", id: "side" },
        h("div", { class: "players", id: "players" }),
        h("div", { class: "side-head" }, "Table talk", h("button", { class: "icon-btn only-narrow", onclick: toggleSide, title: "Close" }, "✕")),
        h("div", { class: "feed", id: "feed" }),
        h("div", { class: "reactions" }, S.config.reactions.map((emoji) => h("button", { title: "React", onclick: () => send({ type: "react", emoji }) }, emoji))),
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
  const color = entry.seat != null && st?.seats[entry.seat] ? st.seats[entry.seat].color : null;
  const dot = color ? h("span", { class: "who", style: { background: seatFill(color) } }) : null;
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
      sfx.snap();
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
  range.addEventListener("change", () => sfx.snap());
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
  else if (g) info = `Hand ${g.hand_no} · ${g.last_phase === 10 ? "all 10 phases" : `phases 1–${g.last_phase}`} · ${seatName(st, g.dealer)} dealt`;
  const before = [
    h("span", { class: "brand", title: "Home", onclick: leaveTable }, h("span", {}, "Phase"), h("b", {}, "10")),
    h("span", { class: "chip code", title: "Copy table code", onclick: copyCode }, "📋 ", S.code),
    h("span", { class: "round-info" }, info),
    h("span", { class: "spacer" }),
    g ? iconBtn("📊", "Scores", showScores) : null,
    iconBtn("❓", "How to play", showRules),
  ].filter(Boolean);
  const after = [iconBtn("💬", "Table talk", toggleSide, "only-narrow", S.ui.unread), iconBtn("⋯", "Menu", toggleMenu)];
  if (volumeControl.parentNode !== top) top.append(volumeControl);
  for (const el of [...top.children]) if (el !== volumeControl) el.remove();
  volumeControl.before(...before);
  volumeControl.after(...after);
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
  toast(ok ? "Invite link copied. Send it to your friends!" : inviteUrl(), !ok);
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
      h("div", { class: "modal" }, h("h2", {}, title), h("p", { class: "sub" }, "Pick a name the other players will see."), h("form", { onsubmit: done }, input, h("div", { class: "actions" }, h("button", { class: "btn primary", type: "submit" }, "Take a seat")))),
      { dismissable, onClose: () => resolve(null) },
    );
    input.focus();
  });
}

function phaseList() {
  return h(
    "ol",
    { class: "phase-list" },
    S.config.phases.map((p) => h("li", {}, h("span", { class: "pl-num" }, p.phase), h("span", {}, p.label))),
  );
}

function showRules() {
  let close = null;
  const sample = (k, v, c) => cardEl({ id: -1, k, v, c }, { cls: "mini" });
  close = openDialog(
    h(
      "div",
      { class: "modal wide rules" },
      h("h2", {}, "How to play Phase 10"),
      h(
        "div",
        { class: "rules-text" },
        h("p", {}, h("b", {}, "Goal: "), "complete all ten phases, one per hand, in order. The first player to complete phase 10 ends the game; if several do it in the same hand, the one with the fewest penalty points wins. If they are tied on points too, only they replay phase 10 and the first to go out wins."),
        h("h4", {}, "The phases"),
        phaseList(),
        h("p", { class: "small" }, h("b", {}, "Set"), ": cards of the same number (e.g. 7 7 7). ", h("b", {}, "Run"), ": numbers in order, any colors (e.g. 3 4 5 6). ", h("b", {}, "Color"), ": cards of one color, any numbers. A group may have more cards than it asks for."),
        h("h4", {}, "Your turn"),
        h(
          "ol",
          {},
          h("li", {}, h("b", {}, "Draw"), " one card: from the face-down deck, or the top of the discard pile."),
          h("li", {}, h("b", {}, "Lay down your phase"), " if you hold it: select the cards for each group and press its button (", h("i", {}, "＋ Set of 3"), ", ", h("i", {}, "＋ Run of 4"), " …), then ", h("i", {}, "Lay down"), ". The whole phase goes down at once."),
          h("li", {}, h("b", {}, "Hit"), ": once your phase is down, add cards to any group on the table, yours or anyone's. Select cards and click the group, or drag a card onto it."),
          h("li", {}, h("b", {}, "Discard"), " one card to end your turn: select it and press ", h("i", {}, "Discard"), ", or drag it onto the discard pile."),
        ),
        h("p", {}, "Get rid of all your cards to ", h("b", {}, "go out"), " and end the hand. Everyone who laid down their phase moves on to the next one; the others try the same phase again."),
        h("h4", {}, "Special cards"),
        h(
          "div",
          { class: "rule-cards" },
          h("div", { class: "rule-card" }, sample("w"), h("div", {}, h("b", {}, "Wild"), ": stands for any number or color in a group. Each group needs at least one real number card.")),
          h("div", { class: "rule-card" }, sample("s"), h("div", {}, h("b", {}, "Skip"), ": discard it in front of a player of your choice instead of on the discard pile; it ends your turn. That player loses their next turn, and the Skip then goes onto the discard pile. A player with a Skip in front of them can't be skipped again. A Skip can't be picked up from the discard pile, nor used in a group. If the first discard is a Skip, the first player loses their turn.")),
        ),
        h("h4", {}, "Penalty points for cards left in your hand"),
        h(
          "div",
          { class: "rule-cards" },
          h("div", { class: "rule-card" }, sample("n", 4, "green"), "1–9: 5 points"),
          h("div", { class: "rule-card" }, sample("n", 11, "blue"), "10–12: 10 points"),
          h("div", { class: "rule-card" }, sample("s"), "Skip: 15 points"),
          h("div", { class: "rule-card" }, sample("w"), "Wild: 25 points"),
        ),
        h("h4", {}, "Your hand"),
        h("p", {}, "Cards arrive in the order you draw them. Drag them to arrange your hand however you like, or use the ", h("i", {}, "1–12"), " and ", h("i", {}, "Colors"), " buttons to sort. Nothing is grouped for you: spotting your phase is the game!"),
        h("p", { class: "small" }, h("b", {}, "Keys: "), "D draws from the deck, T takes the discard, Esc clears your selection."),
      ),
      h("div", { class: "actions" }, h("button", { class: "btn primary", onclick: () => close() }, "Let's play!")),
    ),
  );
}

function showScores() {
  const st = S.state;
  if (!st?.game) return;
  let close = null;
  close = openDialog(h("div", { class: "modal wide" }, h("h2", {}, "Scoreboard"), historyTable(st), h("div", { class: "actions" }, h("button", { class: "btn primary", onclick: () => close() }, "Close"))));
}

function historyTable(st) {
  const g = st.game;
  const nameCell = (s) => h("th", { class: "who" }, h("span", { class: "dot", style: { background: seatFill(s.color) } }), s.name);
  return h(
    "div",
    { class: "table-scroll" },
    h(
      "table",
      { class: "scores" },
      h("thead", {}, h("tr", {}, h("th", {}, "Hand"), st.seats.map(nameCell))),
      h(
        "tbody",
        {},
        g.history.map((hr) =>
          h(
            "tr",
            {},
            h("td", { class: "hand-no" }, hr.hand),
            hr.points.map((p, i) => h("td", { class: hr.made[i] ? "made" : "missed", title: `Phase ${hr.phases[i]} ${hr.made[i] ? "made" : "missed"}` }, h("span", { class: "mark" }, hr.made[i] ? "✓" : "✗"), ` P${hr.phases[i]} · `, h("b", {}, p ? `+${p}` : hr.went_out === i ? "out" : "0"))),
          ),
        ),
        g.history.length ? null : h("tr", {}, h("td", { colspan: st.seats.length + 1, class: "empty" }, "No hand finished yet")),
      ),
      h(
        "tfoot",
        {},
        h("tr", {}, h("td", {}, "Phase"), g.players.map((p) => h("td", {}, h("span", { class: "phase-pill" }, p.phase)))),
        h("tr", {}, h("td", {}, "Points"), g.players.map((p) => h("td", { class: "big" }, p.score))),
      ),
    ),
  );
}

// ------------------------------------------------------------------ rendering
function render() {
  renderView();
  kickTimer();
}

function renderView() {
  renderTop();
  const st = S.state;
  const main = $("#main");
  if (!st || !main) return;
  if (st.status === "lobby") {
    S.hand = null;
    renderPlayers(st);
    renderLobby(st, main);
  } else renderGame(st, main);
  renderOverlay();
}

function avatar(s, size = 32) {
  const label = s.bot ? "🤖" : (s.name || "?").trim().charAt(0).toUpperCase();
  return h("span", { class: `avatar ${s.bot ? "bot" : s.connected ? "online" : "offline"}`, style: { background: seatFill(s.color), width: `${size}px`, height: `${size}px` } }, label);
}

const botInfo = (key) => S.bots.find((b) => b.key === key);

function renderPlayers(st) {
  const box = $("#players");
  if (!box) return;
  if (st.status === "lobby" || !st.game) {
    box.replaceChildren();
    return;
  }
  const g = st.game;
  const isHost = st.host === S.me;
  box.replaceChildren(
    ...st.seats.map((s, seat) => {
      const p = g.players[seat];
      const takeOver = isHost && st.status === "playing" && !s.bot && !s.connected && !s.autoplay ? h("button", { class: "btn small", onclick: () => send({ type: "autoplay", seat, on: true }) }, "🤖 Let a bot play") : null;
      return h(
        "div",
        { class: `pl-row ${g.current === seat ? "current" : ""}`, "data-seat": seat },
        avatar(s, 26),
        h("span", { class: "pl-name" }, s.name, seat === st.you.seat ? h("small", {}, " (you)") : null, s.autoplay ? h("small", {}, " · autopilot") : null, !s.bot && !s.connected ? h("small", {}, " · offline") : null),
        h("span", { class: "phase-pill", title: `Working on phase ${p.phase}` }, p.phase),
        h("span", { class: "pl-score", title: "Penalty points" }, p.score),
        takeOver,
      );
    }),
  );
}

function renderLobby(st, main) {
  const isHost = st.host === S.me;
  const mySeat = st.you.seat;
  const n = st.seats.length;
  const max = S.config.max_seats;
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
    h("div", {}, h("h2", {}, "Gather the players"), h("p", {}, `Anyone who opens the link joins this table. Fill the other seats with bots (2–${max} players).`), note ? h("p", { class: "note" }, "ℹ️ ", note) : null),
    h(
      "div",
      { class: "link-box" },
      linkInput,
      h("button", { class: "btn primary", onclick: copyInvite }, "Copy link"),
      navigator.share ? h("button", { class: "btn", onclick: () => navigator.share({ title: "Play Phase 10 with me", url: inviteUrl() }).catch(() => {}) }, "Share") : null,
    ),
  );
  const seatRows = st.seats.map((s, i) => {
    const bot = s.bot ? botInfo(s.bot) : null;
    const isMe = i === mySeat;
    return h(
      "div",
      { class: "seat-row" },
      avatar(s, 34),
      h("span", { class: "name" }, s.name),
      s.member === st.host ? h("span", { class: "tag host" }, "Host") : null,
      isMe ? h("span", { class: "tag you" }, "You") : null,
      bot ? h("span", { class: "tag stars", title: bot.description }, "★".repeat(bot.stars)) : null,
      !s.bot && !s.connected ? h("span", { class: "tag" }, "offline") : null,
      isMe ? h("button", { class: "icon-btn", title: "Leave seat (watch instead)", onclick: () => send({ type: "stand" }) }, "⏏") : null,
      isHost && !isMe ? h("button", { class: "icon-btn", title: "Remove", onclick: () => send({ type: "remove_seat", seat: i }) }, "✕") : null,
    );
  });
  if (n < max) seatRows.push(h("div", { class: "seat-empty" }, `${max - n} empty seat${max - n === 1 ? "" : "s"}. Invite someone or add a bot`));
  const spectators = st.spectators.filter((s) => s.connected);
  const seatsPanel = h(
    "div",
    { class: "panel" },
    h("h3", {}, "Players", h("small", {}, `${n} / ${max}`)),
    h("div", { class: "seat-list" }, seatRows),
    spectators.length ? h("p", { class: "waiting" }, "Watching: ", spectators.map((s) => s.name).join(", ")) : null,
    mySeat == null && n < max ? h("div", { style: { marginTop: "10px" } }, h("button", { class: "btn primary", onclick: () => send({ type: "sit" }) }, "Take a seat")) : null,
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
          { class: "bot-btn", disabled: !isHost || n >= max, title: b.description, onclick: () => send({ type: "add_bot", bot: b.key }) },
          h("span", { class: "bname" }, b.label),
          h("span", { class: "stars" }, "★".repeat(b.stars), h("span", { style: { opacity: 0.3 } }, "★".repeat(5 - b.stars))),
          h("span", { class: "bdesc" }, b.description),
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
  const row = (label, help, control) => h("div", { class: "setting" }, h("span", { class: "label" }, label, h("small", {}, help)), control);
  const settingsPanel = h(
    "div",
    { class: "panel" },
    h("h3", {}, "Table rules", isHost ? null : h("small", {}, "set by the host")),
    h(
      "div",
      { class: "settings" },
      row("Game length", "The game ends when someone completes the last phase", select("last_phase", [[10, "All 10 phases"], [5, "Phases 1–5"], [3, "Phases 1–3 (quick)"]])),
      row("Turn timer", "The autopilot finishes your turn when time runs out", select("turn_timer", [[0, "Off"], [30, "30 s"], [60, "1 min"], [90, "90 s"], [180, "3 min"]])),
      row("Bot speed", "How fast bots play", select("bot_speed", [["slow", "Relaxed"], ["normal", "Normal"], ["fast", "Fast"]])),
      row(
        "Skip cooldown",
        "House rule: a skipped player must play a turn before they can be skipped again",
        h(
          "select",
          { class: "select", disabled: !isHost, onchange: (e) => change("skip_cooldown", e.target.value === "on") },
          [["off", "Off (official)"], ["on", "On"]].map(([value, label]) => {
            const opt = h("option", { value }, label);
            opt.selected = (set.skip_cooldown ? "on" : "off") === value;
            return opt;
          }),
        ),
      ),
    ),
  );
  const phasesPanel = h("details", { class: "panel phases-panel" }, h("summary", {}, h("span", { class: "pp-title" }, "The ten phases"), h("small", {}, "click to show")), phaseList());
  const actions = isHost
    ? h(
        "div",
        { class: "lobby-actions" },
        h("button", { class: "btn", disabled: n < 2, onclick: () => send({ type: "shuffle" }) }, "🔀 Shuffle seats"),
        h("button", { class: "btn primary big", disabled: n < 2, onclick: () => send({ type: "start" }) }, n < 2 ? "Add a bot or invite a friend" : `🃏 Deal · ${plural(n, "player")}`),
      )
    : h("div", { class: "lobby-actions" }, h("span", { class: "waiting" }, `Waiting for ${hostName} to start the game…`));
  main.replaceChildren(h("section", { class: "lobby" }, invite, h("div", { class: "lobby-grid" }, seatsPanel, h("div", { class: "lobby-col" }, botsPanel, settingsPanel)), actions, phasesPanel));
}

// ------------------------------------------------------------------ game view
const opts = (st) => (st.status === "playing" && !S.ui.pending ? st.game.options : null) || {};

function ensureGame(main) {
  if (S.hand && main.querySelector(".game")) return;
  S.hand = new HandView({ onToggle: toggleSelect, onReorder: reorder, onDrop: onHandDrop, canDrop });
  main.replaceChildren(
    h(
      "section",
      { class: "game" },
      h(
        "div",
        { class: "table-wrap", id: "table-wrap" },
        h("div", { class: "table", id: "table" }, h("div", { class: "opps", id: "opps" }), h("div", { class: "center", id: "center" }), h("div", { class: "mine", id: "mine" })),
      ),
      h(
        "div",
        { class: "dock", id: "dock" },
        h("div", { class: "dock-top" }, h("div", { class: "status", id: "status" }), h("div", { class: "acts", id: "acts" })),
        h("div", { class: "hand-row" }, h("span", { id: "hand-anchor", class: "hand-anchor" }), S.hand.el, h("div", { class: "hand-tools", id: "tools" })),
      ),
    ),
  );
}

function renderGame(st, main) {
  ensureGame(main);
  renderPlayers(st);
  renderOpps(st);
  renderCenter(st);
  renderMine(st);
  renderDock(st);
}

function opponentSeats(st) {
  const n = st.seats.length;
  const me = st.you.seat;
  if (me == null) return st.seats.map((_, i) => i);
  return Array.from({ length: n - 1 }, (_, i) => (me + 1 + i) % n);
}

function groupEl(st, g, size = "small") {
  const o = opts(st);
  const canHit = !!o.hit;
  return h(
    "div",
    {
      class: `group ${size} ${canHit ? "hittable" : ""}`,
      "data-group": g.id,
      "data-drop": `group:${g.id}`,
      title: canHit ? `${groupTitle(g)}: click to add the selected cards` : groupTitle(g),
      onclick: (e) => {
        if (canHit && S.ui.selected.size) hitWith(g.id, [...S.ui.selected], e);
        else if (canHit) toast("Select cards in your hand first, then click the group");
      },
    },
    h("span", { class: "g-label" }, groupTitle(g)),
    h("div", { class: "g-cards", style: { "--n": g.cards.length } }, g.cards.map((c, i) => cardEl(c, { as: g.as[i], cls: size === "small" ? "mini" : "" }))),
  );
}

function renderOpps(st) {
  const box = $("#opps");
  if (!box) return;
  const g = st.game;
  const seats = opponentSeats(st);
  box.dataset.n = seats.length;
  box.replaceChildren(
    ...seats.map((seat) => {
      const s = st.seats[seat];
      const p = g.players[seat];
      const groups = g.groups.filter((x) => x.owner === seat);
      const info = phaseInfo(p.phase);
      const tags = [];
      if (s.bot) tags.push(`bot ${"★".repeat(botInfo(s.bot)?.stars || 1)}`);
      if (s.autoplay) tags.push("autopilot");
      if (!s.bot && !s.connected) tags.push("offline");
      return h(
        "div",
        { class: `opp ${g.current === seat ? "current" : ""} ${p.skipped ? "skipped" : ""} ${p.laid ? "laid" : ""} ${p.active ? "" : "sitting-out"}`, "data-seat": seat, style: { "--pc": seatFill(s.color) } },
        h(
          "div",
          { class: "opp-head" },
          avatar(s, 30),
          h("div", { class: "opp-id" }, h("span", { class: "opp-name" }, s.name), h("span", { class: "opp-tags" }, tags.join(" · "))),
          p.skipped ? h("span", { class: "skip-badge", title: "Loses their next turn" }, "⛔") : null,
          h("span", { class: "opp-count", title: `${plural(p.count, "card")} in hand` }, h("span", { class: "fan" }, Array.from({ length: Math.min(p.count, 5) }, () => backEl("tiny"))), h("b", {}, p.count)),
          h("span", { class: "opp-score", title: "Penalty points" }, p.score, h("small", {}, "pts")),
        ),
        h(
          "div",
          { class: "opp-phase" },
          h("span", { class: `phase-pill ${p.laid ? "done" : ""}` }, `Phase ${p.phase}`),
          h("span", { class: "opp-need" }, !p.active ? "sits out the tie-break" : p.laid ? "✓ laid down" : info.label),
        ),
        groups.length ? h("div", { class: "opp-groups" }, groups.map((x) => groupEl(st, x, "small"))) : null,
      );
    }),
  );
}

function renderCenter(st) {
  const box = $("#center");
  if (!box) return;
  const g = st.game;
  const o = opts(st);
  const canDiscard = !!o.discard && S.ui.selected.size === 1;
  const deck = h(
    "div",
    {
      class: `pile deck ${o.draw_deck ? "can" : ""}`,
      id: "deck",
      title: o.draw_deck ? "Draw from the deck (D)" : "Draw pile",
      onclick: () => o.draw_deck && act({ type: "draw_deck" }),
    },
    h("div", { class: "stack" }, g.draw_size > 1 ? backEl("under") : null, g.draw_size ? backEl() : h("div", { class: "card empty-pile" }, "empty")),
    h("span", { class: "pile-label" }, `Deck · ${g.draw_size}`),
  );
  const top = g.discard_top;
  const discard = h(
    "div",
    {
      class: `pile discard ${o.draw_discard ? "can" : ""} ${canDiscard ? "can-drop" : ""}`,
      id: "discard",
      "data-drop": "discard",
      title: o.draw_discard ? "Take this card (T)" : canDiscard ? "Discard the selected card" : top && isSkip(top) ? "A Skip can't be picked up" : "Discard pile",
      onclick: (e) => {
        if (o.draw_discard) act({ type: "draw_discard" });
        else if (canDiscard) discardCard([...S.ui.selected][0], e);
      },
    },
    h("div", { class: "stack" }, g.discard_under ? cardEl(g.discard_under, { cls: "under" }) : null, top ? cardEl(top, { cls: "top" }) : h("div", { class: "card empty-pile top" }, "empty")),
    h("span", { class: "pile-label" }, "Discard"),
  );
  const track = h(
    "div",
    { class: "track", title: "Who is on which phase" },
    h("div", { class: "track-title" }, "Phase race"),
    h(
      "div",
      { class: "track-steps", style: { "--steps": g.last_phase } },
      Array.from({ length: g.last_phase }, (_, i) => {
        const here = st.seats.map((s, seat) => ({ s, seat })).filter(({ seat }) => g.players[seat].phase === i + 1);
        return h(
          "div",
          { class: "track-step", title: phaseInfo(i + 1).label },
          h("span", { class: "ts-num" }, i + 1),
          h("span", { class: "ts-dots" }, here.map(({ s, seat }) => h("span", { class: `ts-dot ${g.players[seat].laid ? "laid" : ""}`, title: `${s.name}${g.players[seat].laid ? " (laid down)" : ""}`, style: { background: seatFill(s.color) } }))),
        );
      }),
    ),
  );
  box.replaceChildren(h("div", { class: "piles" }, deck, discard), track);
}

function renderMine(st) {
  const box = $("#mine");
  if (!box) return;
  const g = st.game;
  const seat = st.you.seat;
  if (seat == null) {
    box.replaceChildren(h("div", { class: "watching" }, "👀 You're watching this game. You'll get a seat when the host returns to the lobby."));
    box.className = "mine watching-zone";
    return;
  }
  const s = st.seats[seat];
  const p = g.players[seat];
  const info = phaseInfo(p.phase);
  box.className = `mine ${g.current === seat ? "current" : ""} ${p.skipped ? "skipped" : ""}`;
  box.style.setProperty("--pc", seatFill(s.color));
  const head = h(
    "div",
    { class: "mine-head" },
    h("span", { class: `phase-pill big ${p.laid ? "done" : ""}` }, `Phase ${p.phase}`),
    h("span", { class: "mine-need" }, info.label),
    p.laid ? h("span", { class: "laid-tag" }, "✓ Laid down") : null,
    p.skipped ? h("span", { class: "skip-badge", title: "You lose your next turn" }, "⛔ skipped next") : null,
    h("span", { class: "spacer" }),
    h("span", { class: "mine-score", title: "Your penalty points" }, p.score, h("small", {}, " pts")),
  );
  let body;
  if (!p.active) {
    const names = g.tied.map((i) => st.seats[i].name).join(" & ");
    body = h("div", { class: "watching" }, `🤝 ${names} replay phase ${g.last_phase} after a tie. The first to go out wins the game.`);
  } else if (p.laid) {
    const mine = g.groups.filter((x) => x.owner === seat);
    body = h("div", { class: "mine-groups" }, mine.map((x) => groupEl(st, x, "medium")));
  } else {
    const reqs = info.reqs;
    body = h(
      "div",
      { class: "mine-groups slots" },
      reqs.map((r, i) => {
        const slot = S.ui.slots[i];
        const cards = slot ? slot.ids.map((id) => myHand(st).find((c) => c.id === id)).filter(Boolean) : [];
        return h(
          "div",
          {
            class: `slot-box ${slot ? "filled" : ""}`,
            "data-slot": i,
            "data-drop": `slot:${i}`,
            onclick: () => !slot && S.ui.selected.size && stageInto(i),
          },
          h("span", { class: "g-label" }, reqLabel(r), slot && r.kind === "run" ? ` · ${slot.low}–${slot.low + slot.ids.length - 1}` : ""),
          slot
            ? h("div", { class: "g-cards", style: { "--n": cards.length } }, stagedCards(r, slot, cards))
            : h("span", { class: "slot-hint" }, S.ui.selected.size ? "click to put the selected cards here" : "select cards, then press ", S.ui.selected.size ? null : h("b", {}, `＋ ${reqLabel(r)}`)),
          slot ? h("button", { class: "icon-btn unstage", title: "Take these cards back", onclick: (e) => (e.stopPropagation(), unstage(i)) }, "✕") : null,
        );
      }),
    );
  }
  box.replaceChildren(head, body);
}

// Staged cards in the order they will lie on the table (runs low to high, wilds where they fill in).
function stagedCards(req, slot, cards) {
  if (req.kind !== "run") return cards.map((c) => cardEl(c, { cls: "" }));
  const nat = new Map(cards.filter(isNum).map((c) => [c.v, c]));
  const wilds = cards.filter(isWild);
  const out = [];
  for (let v = slot.low; v < slot.low + cards.length; v++) {
    const c = nat.get(v) || wilds.pop();
    out.push(cardEl(c, { as: v }));
  }
  return out;
}

function renderDock(st) {
  renderStatus(st);
  renderActs(st);
  renderHand(st);
}

function renderHand(st) {
  if (!S.hand) return;
  S.hand.render(myHand(st), { selected: S.ui.selected, fresh: S.ui.fresh, hidden: stagedIds() });
  const tools = $("#tools");
  if (tools) {
    const has = myHand(st).length > 1;
    tools.replaceChildren(
      h("button", { class: "btn small ghost", title: "Sort by number (S)", disabled: !has, onclick: () => sortHand("value") }, "1–12"),
      h("button", { class: "btn small ghost", title: "Sort by color (C)", disabled: !has, onclick: () => sortHand("color") }, h("span", { class: "dots4" }, h("i", { class: "r" }), h("i", { class: "b" }), h("i", { class: "g" }), h("i", { class: "y" })), "Colors"),
    );
  }
  document.body.classList.toggle("has-selection", S.ui.selected.size > 0);
}

function statusText(st) {
  const g = st.game;
  const seat = st.you.seat;
  if (st.status === "game_over") return { parts: ["🏁 Game over"] };
  if (g.step === "hand_over") return { parts: ["🏁 The hand is over"] };
  const cur = g.current;
  if (seat != null && !g.players[seat].active && cur !== seat) {
    return { parts: [`🤝 Tie-break: you sit this hand out. ${st.seats[cur]?.name} is playing…`] };
  }
  const o = opts(st);
  if (cur === seat && st.game.options) {
    const me = g.players[seat];
    if (g.step === "draw") return { mine: true, parts: ["Your turn: ", h("b", {}, "draw a card"), " from the deck or take the discard"] };
    if (me.laid) return { mine: true, parts: ["Add cards to any group on the table, then ", h("b", {}, "discard"), " to end your turn"] };
    const full = S.ui.slots.length && S.ui.slots.every(Boolean);
    if (full && o.lay_down) return { mine: true, parts: ["Your phase is ready: press ", h("b", {}, "Lay down"), " (or keep it and discard)"] };
    return { mine: true, parts: ["Build your phase if you can, then ", h("b", {}, "discard"), " a card to end your turn"] };
  }
  const s = st.seats[cur];
  const who = s?.bot ? `${s.name} 🤖` : s?.name;
  return { parts: [`${who} ${g.step === "draw" ? "is about to draw…" : "is playing…"}`] };
}

function renderStatus(st) {
  const box = $("#status");
  if (!box) return;
  const info = statusText(st);
  const cur = st.game.current;
  box.className = `status ${info.mine ? "mine" : ""}`;
  const dot = cur != null ? h("span", { class: "dot", style: { background: seatFill(st.seats[cur]?.color) } }) : null;
  box.replaceChildren(...[dot, h("span", { class: "stext" }, info.parts), h("div", { class: "timer", id: "timer", style: { width: "0" } })].filter(Boolean));
}

function renderActs(st) {
  const box = $("#acts");
  if (!box) return;
  const g = st.game;
  const seat = st.you.seat;
  if (seat == null || st.status !== "playing" || g.step === "hand_over") {
    box.replaceChildren();
    return;
  }
  const o = opts(st);
  const me = g.players[seat];
  const sel = S.ui.selected.size;
  const buttons = [];
  if (!me.laid) {
    const reqs = phaseInfo(me.phase).reqs;
    const shown = new Set();
    reqs.forEach((r, i) => {
      const key = `${r.kind}${r.size}`;
      if (S.ui.slots[i] || shown.has(key)) return;
      shown.add(key);
      buttons.push(h("button", { class: "btn stage", disabled: !sel, title: sel ? `Use the ${plural(sel, "selected card")} as a ${reqLabel(r).toLowerCase()}` : "Select cards first", onclick: (e) => stageKind(r, e) }, `＋ ${reqLabel(r)}`));
    });
    if (S.ui.slots.length && S.ui.slots.every(Boolean)) {
      buttons.push(h("button", { class: "btn primary lay", disabled: !o.lay_down, title: o.lay_down ? "Lay down your phase" : g.current === seat ? "Draw a card first" : "Wait for your turn", onclick: layDown }, `✓ Lay down phase ${me.phase}`));
    }
  }
  buttons.push(h("button", { class: "btn discard-btn", disabled: !(o.discard && sel === 1), title: o.discard ? (sel === 1 ? "Discard the selected card and end your turn" : "Select exactly one card to discard") : "You can discard after drawing, on your turn", onclick: (e) => discardCard([...S.ui.selected][0], e) }, "Discard ↘"));
  if (sel) buttons.push(h("button", { class: "btn ghost small", title: "Clear selection (Esc)", onclick: clearSelection }, `✕ ${sel}`));
  box.replaceChildren(...buttons);
}

// ------------------------------------------------------------------ interactions
function cardById(id) {
  return myHand(S.state).find((c) => c.id === id);
}

function toggleSelect(id) {
  const sel = S.ui.selected;
  if (sel.has(id)) sel.delete(id);
  else sel.add(id);
  sfx.select();
  refreshInteractive();
}

function clearSelection() {
  S.ui.selected.clear();
  refreshInteractive();
}

function refreshInteractive() {
  const st = S.state;
  if (!st?.game) return;
  renderHand(st);
  renderActs(st);
  renderCenter(st);
  renderMine(st);
}

function fullOrder(visible) {
  const hidden = stagedIds();
  const it = visible[Symbol.iterator]();
  return myHand(S.state).map((c) => (hidden.has(c.id) ? c.id : it.next().value));
}

function reorder(visible) {
  const order = fullOrder(visible);
  applyOrder(order);
  sfx.drag();
}

function applyOrder(order) {
  const g = S.state.game;
  const byId = new Map(g.hand.map((c) => [c.id, c]));
  g.hand = order.map((id) => byId.get(id));
  S.ui.fresh = new Set();
  renderHand(S.state);
  send({ type: "arrange", order });
}

function sortHand(how) {
  const hand = myHand(S.state);
  const sorted = how === "value" ? sortByValue(hand) : sortByColor(hand);
  if (sorted.map((c) => c.id).join() === hand.map((c) => c.id).join()) return;
  applyOrder(sorted.map((c) => c.id));
  sfx.shuffle();
}

function selectedCards() {
  return [...S.ui.selected].map(cardById).filter(Boolean);
}

function stageKind(req, e) {
  const reqs = myReqs(S.state);
  const i = reqs.findIndex((r, j) => !S.ui.slots[j] && r.kind === req.kind && r.size === req.size);
  if (i >= 0) stageInto(i, e);
}

function stageInto(i, e, cards = selectedCards()) {
  const req = myReqs(S.state)[i];
  let res;
  try {
    res = checkGroup(req.kind, cards, req.size);
  } catch (err) {
    toast(err.message, true);
    sfx.error();
    return;
  }
  const commit = (low) => {
    S.ui.slots[i] = { ids: cards.map((c) => c.id), low };
    S.ui.selected.clear();
    sfx.place();
    refreshInteractive();
  };
  if (req.kind === "run" && res.lows.length > 1) {
    const n = cards.length;
    const pt = e ? { x: e.clientX, y: e.clientY } : centerOf("#mine");
    openPopover(
      pt.x,
      pt.y,
      h("div", {}, h("h4", {}, "Which run?"), h("p", { class: "why" }, "Your wilds can sit at either end."), h("div", { class: "pay-list" }, res.lows.map((low) => h("button", { class: "btn", onclick: () => (closePopover(), commit(low)) }, `${low}–${low + n - 1}`)))),
    );
    return;
  }
  commit(req.kind === "run" ? res.lows[0] : null);
}

function centerOf(sel) {
  const r = $(sel)?.getBoundingClientRect();
  return r ? { x: r.left + r.width / 2, y: r.top + r.height / 3 } : { x: innerWidth / 2, y: innerHeight / 2 };
}

function unstage(i) {
  S.ui.slots[i] = null;
  sfx.drag();
  refreshInteractive();
}

function layDown() {
  const reqs = myReqs(S.state);
  if (!S.ui.slots.every(Boolean)) return;
  act({ type: "lay_down", groups: S.ui.slots.map((s, i) => ({ kind: reqs[i].kind, cards: s.ids, low: s.low ?? null })) });
}

// Add cards to a group, naturals first so a run grows towards them; a lone wild on a run asks which end.
function hitWith(gid, ids, e) {
  const group = S.state.game.groups.find((x) => x.id === gid);
  if (!group) return;
  const sim = { ...group };
  const rest = ids.map(cardById).filter(Boolean);
  const plan = [];
  while (rest.length) {
    let i = rest.findIndex((c) => isNum(c) && endsFor(sim, c).length);
    if (i < 0) i = rest.findIndex((c) => isWild(c) && endsFor(sim, c).length);
    if (i < 0) {
      toast(whyNot(sim, rest[0]), true);
      sfx.error();
      return;
    }
    const c = rest.splice(i, 1)[0];
    const ends = endsFor(sim, c);
    let end = ends.includes("high") ? "high" : ends[0];
    if (end === "any") end = null;
    plan.push({ c, end, ends });
    if (sim.kind === "run") {
      if (end === "low") sim.low -= 1;
      else sim.high += 1;
    }
  }
  const commit = () => {
    S.ui.selected.clear();
    for (const p of plan) act({ type: "hit", group: gid, card: p.c.id, end: p.end });
  };
  if (plan.length === 1 && group.kind === "run" && plan[0].ends.length === 2) {
    const pt = e ? { x: e.clientX, y: e.clientY } : centerOf(`.group[data-group="${gid}"]`);
    openPopover(
      pt.x,
      pt.y,
      h(
        "div",
        {},
        h("h4", {}, "Where does the wild go?"),
        h(
          "div",
          { class: "pay-list" },
          h("button", { class: "btn", onclick: () => ((plan[0].end = "low"), commit()) }, `As ${group.low - 1} (low end)`),
          h("button", { class: "btn", onclick: () => ((plan[0].end = "high"), commit()) }, `As ${group.high + 1} (high end)`),
        ),
      ),
    );
    return;
  }
  commit();
}

function discardCard(id, e) {
  const st = S.state;
  const o = opts(st);
  const c = cardById(id);
  if (!c || !o.discard) return;
  if (isSkip(c)) {
    const targets = o.skip_targets || [];
    if (targets.length > 1) {
      const pt = e ? { x: e.clientX, y: e.clientY } : centerOf("#discard");
      openPopover(
        pt.x,
        pt.y,
        h(
          "div",
          {},
          h("h4", {}, "⛔ Who loses their next turn?"),
          h(
            "div",
            { class: "pay-list" },
            targets.map((t) => {
              const s = st.seats[t];
              const p = st.game.players[t];
              return h("button", { class: "btn skip-target", onclick: () => act({ type: "discard", card: id, target: t }) }, avatar(s, 22), ` ${s.name} `, h("small", {}, `P${p.phase} · ${plural(p.count, "card")}`));
            }),
          ),
        ),
      );
      return;
    }
    act({ type: "discard", card: id, target: targets[0] ?? null });
    return;
  }
  act({ type: "discard", card: id });
}

function canDrop(drop, id) {
  const st = S.state;
  const o = opts(st);
  if (drop === "discard") return !!o.discard;
  if (drop.startsWith("group:")) return !!o.hit;
  if (drop.startsWith("slot:")) {
    const i = Number(drop.slice(5));
    return st.game.players[st.you.seat] && !st.game.players[st.you.seat].laid && i < S.ui.slots.length && cardById(id) != null;
  }
  return false;
}

function onHandDrop(id, drop, rect, e) {
  if (drop === "discard") return discardCard(id, e);
  if (drop.startsWith("group:")) {
    const ids = S.ui.selected.has(id) ? [...S.ui.selected] : [id];
    return hitWith(Number(drop.slice(6)), ids, e);
  }
  if (drop.startsWith("slot:")) {
    const i = Number(drop.slice(5));
    const slot = S.ui.slots[i];
    const extra = S.ui.selected.has(id) ? [...S.ui.selected] : [id];
    const ids = [...(slot ? slot.ids : []), ...extra.filter((x) => !(slot?.ids || []).includes(x))];
    if (slot) S.ui.slots[i] = null;
    const before = slot;
    stageInto(i, e, ids.map(cardById).filter(Boolean));
    if (!S.ui.slots[i] && before) S.ui.slots[i] = before;
    refreshInteractive();
  }
}

// ------------------------------------------------------------------ popovers
let popoverEl = null;

function closePopover() {
  popoverEl?.remove();
  popoverEl = null;
}

function openPopover(x, y, content) {
  closePopover();
  popoverEl = h("div", { class: "popover" }, h("button", { class: "icon-btn close", onclick: closePopover, title: "Close" }, "✕"), content);
  document.body.append(popoverEl);
  const r = popoverEl.getBoundingClientRect();
  const left = Math.min(innerWidth - r.width - 8, Math.max(8, x - r.width / 2));
  const top = y - r.height - 16 > 60 ? y - r.height - 16 : Math.min(innerHeight - r.height - 8, y + 18);
  popoverEl.style.left = `${left}px`;
  popoverEl.style.top = `${top}px`;
}

document.addEventListener("pointerdown", (e) => {
  if (popoverEl && !e.target.closest(".popover") && !e.target.closest(".btn")) closePopover();
});

// ------------------------------------------------------------------ hand over / game over
function renderOverlay() {
  const st = S.state;
  const g = st?.game;
  if (!st || !g || !["hand_over", "game_over"].includes(g.step) || st.status === "lobby" || performance.now() < S.ui.summaryAt) {
    overlay.replaceChildren();
    return;
  }
  const over = g.step === "game_over";
  if (S.ui.overlayHidden) {
    overlay.replaceChildren(h("div", { class: "mini-bar" }, over ? "🏁 Game over" : "🏁 Hand over", h("button", { class: "btn small primary", onclick: () => ((S.ui.overlayHidden = false), renderOverlay()) }, over ? "Show results" : "Show the hand")));
    return;
  }
  overlay.replaceChildren(h("div", { class: "backdrop" }, over ? gameOverModal(st) : handOverModal(st)));
}

function leftCards(cards) {
  if (!cards.length) return h("span", { class: "none" }, "—");
  return h("span", { class: "left-cards" }, cards.map((c) => chip(c)));
}

function handOverModal(st) {
  const g = st.game;
  const hr = g.history[g.history.length - 1];
  const me = st.you.seat;
  const tie = hr.tiebreak || [];
  const tieNames = tie.map((i) => (i === me ? "you" : seatName(st, i))).join(" & ");
  const title = tie.length && hr.went_out != null ? "🤝 It's a tie!" : hr.went_out == null ? "The cards ran out" : hr.went_out === me ? "🏁 You went out!" : `🏁 ${seatName(st, hr.went_out)} went out`;
  const sub = tie.length
    ? `${tieNames} finished phase ${g.last_phase} with the same score. Next hand only ${tieNames} play phase ${g.last_phase} again: the first to go out wins.`
    : `Hand ${hr.hand} is over. Players who laid down their phase move on; the others try it again.`;
  const ready = me != null && g.ready.includes(me);
  const waiting = g.waiting_for.map((i) => seatName(st, i));
  const played = hr.played || st.seats.map(() => true);
  const phaseCell = (i) => {
    if (!played[i]) return h("td", { class: "missed" }, "sat out");
    if (!hr.made[i]) return h("td", { class: "missed" }, `✗ ${hr.phases[i]} again`);
    return h("td", { class: "made" }, `✓ ${hr.phases[i]}${hr.phases[i] < g.last_phase ? ` → ${hr.phases[i] + 1}` : ""}`);
  };
  return h(
    "div",
    { class: "modal wide result" },
    h("h2", {}, title),
    h("p", { class: "sub" }, sub),
    h(
      "div",
      { class: "table-scroll" },
      h(
        "table",
        { class: "scores hand-result" },
        h("thead", {}, h("tr", {}, ["Player", "Phase", "Cards left", "Points", "Total"].map((t) => h("th", { class: t === "Cards left" ? "left-col" : "" }, t)))),
        h(
          "tbody",
          {},
          st.seats.map((s, i) =>
            h(
              "tr",
              { class: hr.went_out === i ? "win" : "" },
              h("td", { class: "who" }, h("div", { class: "who-in" }, avatar(s, 24), h("span", {}, s.name, i === me ? h("small", {}, " (you)") : null))),
              phaseCell(i),
              h("td", { class: "left-col" }, leftCards(hr.left[i])),
              h("td", { class: "big" }, hr.points[i] ? `+${hr.points[i]}` : "0"),
              h("td", { class: "big" }, g.players[i].score),
            ),
          ),
        ),
      ),
    ),
    h(
      "div",
      { class: "actions" },
      h("button", { class: "btn ghost", onclick: () => ((S.ui.overlayHidden = true), renderOverlay()) }, "👀 Look at the table"),
      waiting.length && (ready || me == null) ? h("span", { class: "grow" }, `Waiting for ${waiting.join(", ")}…`) : h("span", { class: "grow" }),
      me != null && !ready ? h("button", { class: "btn primary", onclick: () => send({ type: "ready" }) }, `Ready for hand ${hr.hand + 1} ▸`) : null,
    ),
  );
}

function gameOverModal(st) {
  const g = st.game;
  const res = g.result;
  const me = st.you.seat;
  const isHost = st.host === S.me;
  const winners = res.winners.map((w) => st.seats[w].name);
  let title = winners.length > 1 ? `🤝 ${winners.join(" & ")} share the win!` : `🏆 ${winners[0]} wins!`;
  if (me != null && res.winners.includes(me)) title = winners.length > 1 ? "🤝 You share the win!" : "🏆 You win!";
  const order = st.seats.map((_, i) => i).sort((a, b) => res.winners.includes(b) - res.winners.includes(a) || res.finishers.includes(b) - res.finishers.includes(a) || g.players[b].phase - g.players[a].phase || g.players[a].score - g.players[b].score);
  return h(
    "div",
    { class: "modal wide result" },
    h("h2", {}, title),
    h(
      "p",
      { class: "sub" },
      `${plural(g.history.length, "hand")} played. ${
        (g.history.at(-1)?.played || []).includes(false)
          ? "Tied on points, so the tied players replayed the last phase; the first to go out won."
          : res.finishers.length > 1
            ? "Several players finished; the fewest points won."
            : "First to finish the last phase."
      }`,
    ),
    h(
      "div",
      { class: "table-scroll" },
      h(
        "table",
        { class: "scores" },
        h("thead", {}, h("tr", {}, ["#", "Player", "Phase", "Points"].map((t) => h("th", {}, t)))),
        h(
          "tbody",
          {},
          order.map((i, rank) =>
            h(
              "tr",
              { class: res.winners.includes(i) ? "win" : "" },
              h("td", {}, rank + 1),
              h("td", { class: "who" }, h("div", { class: "who-in" }, avatar(st.seats[i], 24), h("span", {}, st.seats[i].name, i === me ? h("small", {}, " (you)") : null, res.winners.includes(i) ? " 🏆" : ""))),
              h("td", {}, res.finishers.includes(i) ? `✓ all ${g.last_phase}` : `phase ${g.players[i].phase}`),
              h("td", { class: "big" }, g.players[i].score),
            ),
          ),
        ),
      ),
    ),
    h("details", { class: "history" }, h("summary", {}, "Hand by hand"), historyTable(st)),
    h(
      "div",
      { class: "actions" },
      h("button", { class: "btn ghost", onclick: () => ((S.ui.overlayHidden = true), renderOverlay()) }, "👀 Look at the table"),
      isHost ? h("button", { class: "btn", onclick: () => send({ type: "to_lobby" }) }, "Back to lobby") : null,
      isHost ? h("button", { class: "btn primary", onclick: () => send({ type: "play_again" }) }, "Play again ↻") : h("span", { class: "grow", style: { textAlign: "right" } }, "Waiting for the host to start a rematch…"),
    ),
  );
}

function confetti() {
  const layer = h("div", { class: "confetti" });
  const colors = ["#e23b3b", "#2f6fe0", "#2fa84f", "#f2b705", "#ffffff"];
  for (let i = 0; i < 90; i++) {
    layer.append(h("i", { style: { left: `${Math.random() * 100}%`, background: pick(colors), animationDuration: `${2.2 + Math.random() * 2}s`, animationDelay: `${Math.random() * 0.8}s`, transform: `rotate(${Math.random() * 360}deg)` } }));
  }
  document.body.append(layer);
  setTimeout(() => layer.remove(), 5200);
}

function showReaction(msg) {
  const st = S.state;
  const name = st?.seats.find((s) => s.member === msg.member)?.name || st?.spectators.find((s) => s.member === msg.member)?.name || "";
  let rect = msg.seat != null ? ($(`.opp[data-seat="${msg.seat}"]`) || (msg.seat === st?.you.seat ? $("#mine") : null))?.getBoundingClientRect() : null;
  if (!rect) rect = $("#main")?.getBoundingClientRect();
  if (!rect) return;
  const bubble = h("div", { class: "bubble", style: { left: `${rect.left + rect.width / 2 + (Math.random() - 0.5) * 40}px`, top: `${rect.top + 10}px` } }, msg.emoji, h("small", {}, name));
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
      bar.classList.toggle("low", left < 8000);
      if (left > 0 && left < 5000 && st.game?.options) {
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
  if (e.key === "Escape") {
    if (popoverEl) closePopover();
    else if (S.ui.selected.size) clearSelection();
  }
  if (!st?.game || st.status === "lobby") return;
  const k = e.key.toLowerCase();
  if (k === "s") sortHand("value");
  if (k === "c") sortHand("color");
  const o = opts(st);
  if (k === "d" && o.draw_deck) act({ type: "draw_deck" });
  if (k === "t" && o.draw_discard) act({ type: "draw_discard" });
});

for (const ev of ["pointerdown", "keydown"]) window.addEventListener(ev, unlockAudio, { capture: true });

// ------------------------------------------------------------------ boot
async function boot() {
  S.config = await fetch(`${BASE}api/config`).then((r) => r.json());
  router();
}
boot().catch((e) => {
  console.error(e);
  app.replaceChildren(h("div", { class: "center-msg" }, h("p", {}, "Could not load the game. Is the server running?")));
});