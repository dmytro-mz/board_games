// The room page: level 1 create/join a room, level 2 vote for a game, level 3 the game itself (in an iframe).
import { NAME_KEY, TOKEN_KEY } from "./shared/platform.js";
import { copyText, h, morph, openDialog, s, toast } from "./shared/dom.js";

const app = document.getElementById("app");
const layer = document.getElementById("layer");

const S = {
  config: { games: [], public_url: null, lan_url: null },
  token: takeTokenFromUrl() || localStorage.getItem(TOKEN_KEY) || newToken(),
  name: localStorage.getItem(NAME_KEY) || "",
  code: null,
  ws: null,
  retry: 0,
  reconnectTimer: null,
  connected: false,
  fatal: null,
  state: null,
  filter: loadFilter(),
};
localStorage.setItem(TOKEN_KEY, S.token);

// "Continue on another device" links (made by the games) carry the player's token: /r/CODE?me=TOKEN.
function takeTokenFromUrl() {
  const t = new URLSearchParams(location.search).get("me");
  if (!t || !/^[0-9a-f]{16,64}$/.test(t)) return null;
  history.replaceState({}, "", location.pathname);
  return t;
}

function newToken() {
  const bytes = crypto.getRandomValues(new Uint8Array(16));
  return Array.from(bytes, (b) => b.toString(16).padStart(2, "0")).join("");
}

function loadFilter() {
  try {
    return { people: "group", noBots: false, ...JSON.parse(localStorage.getItem("bg.filter") || "{}") };
  } catch {
    return { people: "group", noBots: false };
  }
}

function saveFilter() {
  try {
    localStorage.setItem("bg.filter", JSON.stringify(S.filter));
  } catch {
    /* private mode */
  }
}

const ADJECTIVES = ["Lucky", "Sneaky", "Clever", "Bold", "Jolly", "Swift", "Cosy", "Wild", "Merry", "Canny"];
const NOUNS = ["Meeple", "Dice", "Pawn", "Rook", "Joker", "Token", "Knight", "Card Shark", "Strategist", "Bluffer"];
const pick = (xs) => xs[Math.floor(Math.random() * xs.length)];
const suggestName = () => `${pick(ADJECTIVES)} ${pick(NOUNS)}`;

function saveName(name) {
  name = (name || "").trim().slice(0, 20);
  if (!name) return S.name;
  S.name = name;
  localStorage.setItem(NAME_KEY, name);
  return name;
}

const game = (key) => S.config.games.find((g) => g.key === key);
const member = (id) => S.state?.members.find((m) => m.id === id);
const isLeader = () => S.state && S.state.leader === S.state.you;
const online = () => (S.state ? S.state.members.filter((m) => m.online) : []);
const initials = (name) => name.split(/\s+/).map((w) => w[0]).join("").slice(0, 2).toUpperCase();

function playersLabel(g) {
  if (g.max_players >= 10) return `${g.min_players}+ players`;
  if (g.min_players === g.max_players) return `${g.min_players} players`;
  return `${g.min_players}–${g.max_players} players`;
}

const KIND = { coop: "Co-op", teams: "Teams", versus: "Competitive" };

function fits(g, people, noBots) {
  if (people > g.max_players) return false;
  return people >= g.min_players || (g.bots && !noBots);
}

// ------------------------------------------------------------------ routing
function go(path) {
  history.pushState({}, "", path);
  router();
}

function router() {
  const match = location.pathname.match(/^\/r\/([A-Za-z0-9]{4,8})\/?$/);
  layer.replaceChildren();
  if (match) enterRoom(match[1].toUpperCase());
  else showHome();
}
window.addEventListener("popstate", router);

// ------------------------------------------------------------------ level 1: home
function showHome() {
  closeSocket();
  Object.assign(S, { code: null, state: null });
  document.title = "Game night";
  const nameInput = h("input", { class: "text", value: S.name, placeholder: suggestName(), maxlength: 20, autocomplete: "nickname" });
  const codeInput = h("input", { class: "text code", placeholder: "CODE", maxlength: 8, autocapitalize: "characters", autocomplete: "off" });
  const create = async () => {
    saveName(nameInput.value || nameInput.placeholder);
    try {
      const res = await fetch("/api/rooms", { method: "POST" });
      if (!res.ok) throw new Error((await res.json()).detail || "Could not create a room");
      go(`/r/${(await res.json()).room}`);
    } catch (e) {
      toast(e.message, true);
    }
  };
  const join = async () => {
    const code = codeInput.value.trim().toUpperCase();
    if (!code) return codeInput.focus();
    saveName(nameInput.value || nameInput.placeholder);
    const res = await fetch(`/api/rooms/${encodeURIComponent(code)}`);
    if (!res.ok) return toast("No room with that code", true);
    go(`/r/${code}`);
  };
  nameInput.addEventListener("keydown", (e) => e.key === "Enter" && create());
  codeInput.addEventListener("keydown", (e) => e.key === "Enter" && join());
  const covers = S.config.games.filter((g) => g.thumb).slice(0, 5);
  app.replaceChildren(
    h(
      "main",
      { class: "home" },
      h(
        "div",
        { class: "home-card" },
        h("div", { class: "brand" }, diceMark(), h("h1", {}, "Game night")),
        h("p", { class: "tagline" }, `${S.config.games.length} board games, one room. Create a room, send the link to your friends, vote for a game and play — bots fill the empty seats.`),
        h("div", { class: "home-fan", "aria-hidden": "true" }, covers.map((g, i) => h("img", { src: g.thumb, alt: "", style: { "--i": i - (covers.length - 1) / 2 } }))),
        h(
          "div",
          { class: "home-form" },
          h("label", {}, "Your name", nameInput),
          h("button", { class: "btn primary big", onclick: create }, "Create a room"),
          h("div", { class: "or" }, "or join with a code"),
          h("div", { class: "join-row" }, codeInput, h("button", { class: "btn", onclick: join }, "Join")),
        ),
      ),
    ),
  );
  nameInput.focus();
}

// The logo: a die showing five.
function diceMark() {
  const pips = [[10, 10], [22, 10], [16, 16], [10, 22], [22, 22]];
  return s(
    "svg",
    { class: "dice-mark", viewBox: "0 0 32 32", "aria-hidden": "true" },
    s("rect", { x: 2, y: 2, width: 28, height: 28, rx: 7, class: "die" }),
    pips.map(([cx, cy]) => s("circle", { cx, cy, r: 2.6, class: "pip" })),
  );
}

// ------------------------------------------------------------------ room socket
async function enterRoom(code) {
  closeSocket();
  Object.assign(S, { code, state: null, fatal: null, connected: false, retry: 0 });
  document.title = `Game night · ${code}`;
  if (!S.name) await askName(`Join room ${code}`);
  app.replaceChildren(h("div", { class: "center-msg" }, h("p", {}, "Connecting…")));
  connect();
}

function connect() {
  const proto = location.protocol === "https:" ? "wss" : "ws";
  const ws = new WebSocket(`${proto}://${location.host}/ws/${S.code}`);
  S.ws = ws;
  ws.onopen = () => ws.send(JSON.stringify({ type: "hello", token: S.token, name: S.name }));
  ws.onmessage = (e) => onMessage(JSON.parse(e.data));
  ws.onclose = () => {
    if (S.ws !== ws) return;
    S.connected = false;
    renderStatus();
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

function onMessage(msg) {
  switch (msg.type) {
    case "welcome":
      S.connected = true;
      S.retry = 0;
      break;
    case "state":
      applyState(msg);
      break;
    case "error":
      toast(msg.message, true);
      break;
    case "fatal":
      S.fatal = msg.message;
      closeSocket();
      showFatal(msg.message);
      break;
  }
}

function showFatal(message) {
  layer.replaceChildren();
  app.replaceChildren(
    h("div", { class: "center-msg" }, h("div", { class: "home-card" }, h("h2", {}, message), h("p", { class: "muted" }, "Rooms close a few hours after everyone has left."), h("button", { class: "btn primary big", onclick: () => go("/") }, "Start a new room"))),
  );
}

function applyState(next) {
  const prev = S.state;
  S.state = next;
  if (next.phase !== prev?.phase || next.game?.key !== prev?.game?.key) app.replaceChildren();
  render();
}

// ------------------------------------------------------------------ render
function render() {
  const st = S.state;
  if (!st) return;
  if (st.phase === "game") renderGame(st);
  else renderSelect(st);
  renderBack(st);
}

function renderStatus() {
  document.body.classList.toggle("offline", !S.connected && !S.fatal);
}

// ------------------------------------------------------------------ level 2: game selection
function renderSelect(st) {
  document.title = `Game night · ${st.room}`;
  const people = online().length;
  const want = S.filter.people === "group" ? people : S.filter.people === "any" ? null : Number(S.filter.people);
  const shown = S.config.games.filter((g) => want === null || fits(g, want, S.filter.noBots));
  const hidden = S.config.games.length - shown.length;
  const voters = (key) => st.members.filter((m) => m.online && m.vote === key);
  const mine = st.members.find((m) => m.id === st.you)?.vote;
  morph(app, [
    topBar(st),
    h(
      "main",
      { class: "select", "data-key": "select" },
      h(
        "div",
        { class: "select-head" },
        h("div", {}, h("h2", {}, "Choose a game"), h("p", { class: "muted" }, mine ? `You voted for ${game(mine)?.title}. Click it again to take your vote back.` : "Click a game to vote for it. Click again to take your vote back.")),
        filterBar(people),
      ),
      h(
        "div",
        { class: "tiles" },
        shown.map((g) => tile(g, voters(g.key), mine === g.key, st)),
      ),
      hidden ? h("p", { class: "muted hidden-note" }, `${hidden} game${hidden === 1 ? "" : "s"} hidden by the filter. `, h("button", { class: "linklike", onclick: () => setFilter({ people: "any", noBots: false }) }, "Show all")) : null,
    ),
    actionBar(st),
  ]);
}

function topBar(st) {
  return h(
    "header",
    { class: "topbar", "data-key": "top" },
    h("a", { class: "brand small", href: "/", title: "Leave the room", onclick: (e) => (e.preventDefault(), leaveRoom()) }, diceMark(), h("span", {}, "Game night")),
    h("button", { class: "chip code-chip", title: "Copy the invite link", onclick: copyInvite }, "Room ", h("b", {}, st.room), " · 🔗 Invite"),
    h(
      "div",
      { class: "people" },
      st.members
        .filter((m) => m.online || m.id === st.leader)
        .map((m) =>
          h(
            "span",
            { class: `person${m.online ? "" : " away"}${m.id === st.you ? " me" : ""}`, "data-key": `p-${m.id}`, title: `${m.name}${m.id === st.leader ? " (leader)" : ""}${m.online ? "" : " — away"}` },
            m.id === st.leader ? h("span", { class: "crown", "aria-label": "leader" }, "👑") : null,
            h("span", { class: "avatar" }, initials(m.name)),
            h("span", { class: "pname" }, m.name),
          ),
        ),
    ),
    h("button", { class: "chip", title: "Change your name", onclick: rename }, "✏️ ", S.name || "Me"),
  );
}

function filterBar(people) {
  const opts = [
    ["group", `Fits us (${people})`],
    ["any", "Any"],
    ["1", "1"],
    ["2", "2"],
    ["3", "3"],
    ["4", "4"],
    ["5", "5"],
    ["6", "6+"],
  ];
  return h(
    "div",
    { class: "filter", role: "group", "aria-label": "Filter by number of players" },
    h("span", { class: "filter-label" }, "Players"),
    opts.map(([value, label]) =>
      h("button", { class: `seg${S.filter.people === value ? " on" : ""}`, "aria-pressed": String(S.filter.people === value), onclick: () => setFilter({ people: value }) }, label),
    ),
    h(
      "label",
      { class: `toggle${S.filter.people === "any" ? " disabled" : ""}`, title: "Only games this many people can play without bots" },
      h("input", { type: "checkbox", checked: S.filter.noBots, disabled: S.filter.people === "any", onchange: (e) => setFilter({ noBots: e.target.checked }) }),
      "No bots",
    ),
  );
}

function setFilter(changes) {
  S.filter = { ...S.filter, ...changes };
  saveFilter();
  render();
}

function tile(g, voters, mine, st) {
  const selected = st.selected === g.key;
  const top = st.most_voted === g.key;
  return h(
    "button",
    {
      class: `tile${mine ? " voted" : ""}${selected ? " selected" : ""}`,
      "data-key": `tile-${g.key}`,
      style: { "--accent": g.accent },
      "aria-pressed": String(mine),
      title: mine ? "Take your vote back" : `Vote for ${g.title}`,
      onclick: () => send({ type: "vote", game: g.key }),
    },
    h(
      "div",
      { class: "thumb" },
      g.thumb ? h("img", { src: g.thumb, alt: "", loading: "lazy" }) : h("div", { class: "thumb-fallback" }, g.title),
      h(
        "div",
        { class: "badges" },
        selected ? h("span", { class: "badge leader-pick" }, "👑 Leader's pick") : null,
        top ? h("span", { class: "badge top" }, "★ Most votes") : null,
      ),
      voters.length ? h("span", { class: "votes" }, String(voters.length), h("small", {}, voters.length === 1 ? "vote" : "votes")) : null,
    ),
    h(
      "div",
      { class: "tile-body" },
      h("h3", {}, g.title),
      h("p", { class: "tile-tag" }, g.tagline),
      h(
        "div",
        { class: "facts" },
        h("span", { class: "fact" }, "👥 ", playersLabel(g)),
        h("span", { class: `fact ${g.bots ? "bots" : "nobots"}` }, g.bots ? "🤖 Bots available" : "🙋 People only"),
        h("span", { class: "fact" }, KIND[g.kind] || g.kind),
        h("span", { class: "fact" }, "⏱ ", g.minutes, " min"),
      ),
      voters.length ? h("div", { class: "voters" }, voters.map((m) => h("span", { class: "avatar sm", title: m.name, "data-key": `v-${m.id}` }, initials(m.name)))) : null,
    ),
  );
}

function actionBar(st) {
  const leader = member(st.leader);
  if (!isLeader()) {
    const choice = st.selected ? ` · leader's pick: ${game(st.selected)?.title}` : "";
    return h("footer", { class: "actionbar", "data-key": "actions" }, h("p", {}, `Waiting for ${leader?.name || "the leader"} to start a game${choice}`));
  }
  const buttons = [];
  const { selected, most_voted: top } = st;
  if (selected && selected === top) buttons.push(launchButton(selected, "Play", "your pick and the most votes"));
  else {
    if (selected) buttons.push(launchButton(selected, "Play selected", "your pick"));
    if (top) buttons.push(launchButton(top, "Play most voted", `${st.tally[top]} vote${st.tally[top] === 1 ? "" : "s"}`));
  }
  const hint = buttons.length ? null : h("p", {}, "You lead this room. Vote for a game to select it, or wait for the others to vote.");
  const tie = !top && Object.keys(st.tally).length > 1 ? h("p", { class: "muted" }, "The votes are tied: no most voted game.") : null;
  return h("footer", { class: "actionbar", "data-key": "actions" }, hint, tie, h("div", { class: "launch" }, buttons));
}

function launchButton(key, label, why) {
  const g = game(key);
  return h("button", { class: "btn primary big", "data-key": `launch-${label}`, style: { "--accent": g.accent }, onclick: () => send({ type: "launch", game: key }) }, `▶ ${label}: `, h("b", {}, g.title), h("small", {}, why));
}

// ------------------------------------------------------------------ level 3: the game
function renderGame(st) {
  const g = game(st.game.key);
  document.title = `${g.title} · ${st.room}`;
  let frame = document.getElementById("game-frame");
  const src = `/g/${g.key}/r/${st.room}`;
  if (!frame || frame.dataset.src !== src) {
    frame = h("iframe", { id: "game-frame", class: "game-frame", src, title: g.title, allow: "clipboard-write; fullscreen; autoplay" });
    frame.dataset.src = src;
    frame.addEventListener("load", () => frame.contentWindow?.focus());
    app.replaceChildren(frame, h("div", { id: "back-pill-slot" }));
  }
  const slot = document.getElementById("back-pill-slot");
  const showPill = isLeader() && st.game.status === "lobby" && !st.back;
  morph(slot, showPill ? h("button", { class: "back-pill", "data-key": "pill", title: "Ask everyone to go back to the game selection", onclick: () => send({ type: "back_request" }) }, "← Choose another game") : null);
}

// ------------------------------------------------------------------ back to game selection
function renderBack(st) {
  const back = st.back;
  if (!back || st.phase !== "game") {
    morph(layer, []);
    return;
  }
  const by = member(back.by);
  const others = online().filter((m) => m.id !== back.by);
  const status = (m) => (back.accepted.includes(m.id) ? "accepted" : back.declined.includes(m.id) ? "declined" : "waiting");
  const list = h(
    "ul",
    { class: "replies" },
    others.map((m) => {
      const s = status(m);
      return h("li", { class: s, "data-key": `r-${m.id}` }, h("span", { class: "mark" }, s === "accepted" ? "✓" : s === "declined" ? "✕" : "…"), h("span", {}, m.name), h("small", {}, s));
    }),
  );
  let body;
  if (isLeader()) {
    body = [
      h("h2", {}, "Back to the game selection?"),
      h("p", { class: "muted" }, "Everyone has to agree. You can also go back right away."),
      list,
      h("div", { class: "actions" }, h("button", { class: "btn", onclick: () => send({ type: "back_cancel" }) }, "Cancel"), h("button", { class: "btn primary", onclick: () => send({ type: "back_force" }) }, "Go back now")),
    ];
  } else {
    const mine = status({ id: st.you });
    body = [
      h("h2", {}, `${by?.name || "The leader"} wants to choose another game`),
      h("p", { class: "muted" }, mine === "waiting" ? "This closes the current game table for everyone." : mine === "accepted" ? "You agreed. Waiting for the others…" : "You said no. The leader can still decide to go back."),
      list,
      h(
        "div",
        { class: "actions" },
        h("button", { class: `btn${mine === "declined" ? " on" : ""}`, onclick: () => send({ type: "back_reply", accept: false }) }, "Stay here"),
        h("button", { class: `btn primary${mine === "accepted" ? " on" : ""}`, onclick: () => send({ type: "back_reply", accept: true }) }, "OK, let's choose"),
      ),
    ];
  }
  morph(layer, h("div", { class: "backdrop", "data-key": "back" }, h("div", { class: "modal" }, body)));
}

// ------------------------------------------------------------------ helpers
function inviteUrl() {
  const local = ["localhost", "127.0.0.1", "[::1]"].includes(location.hostname);
  const base = S.config.public_url || (local && S.config.lan_url) || location.origin;
  return `${base.replace(/\/$/, "")}/r/${S.code}`;
}

async function copyInvite() {
  const ok = await copyText(inviteUrl());
  toast(ok ? "Invite link copied. Send it to your friends!" : inviteUrl(), !ok);
}

function leaveRoom() {
  if (S.state && !confirm("Leave this room?")) return;
  go("/");
}

async function rename() {
  const name = await askName("Change your name", true);
  if (name) send({ type: "rename", name });
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
    close = openDialog(h("div", { class: "modal" }, h("h2", {}, title), h("p", { class: "muted" }, "Pick the name the others will see."), h("form", { onsubmit: done }, input, h("div", { class: "actions" }, h("button", { class: "btn primary", type: "submit" }, "OK")))), { dismissable, onClose: () => resolve(null) });
    input.focus();
  });
}

// ------------------------------------------------------------------ boot
async function boot() {
  S.config = await fetch("/api/config").then((r) => r.json());
  router();
}
boot().catch((e) => {
  console.error(e);
  app.replaceChildren(h("div", { class: "center-msg" }, h("p", {}, "Could not load the page. Is the server running?")));
});
