import { NAME_KEY, TOKEN_KEY, gameBase, leaveRoom, socketUrl } from "/static/shared/platform.js";
// Entry point: home screen, room connection, lobby, and handing game states to the game screen.
import { CFG, DIFFS, ROLES, SPEEDS, initData } from "./data.js";
import { RULES_HTML, closeModal, closeSheet, mountGame, onDocClick, onError, onGameState, onKey, onLog, onResize, showReaction, unreadChat } from "./game.js";
import { send } from "./net.js";
import { sfx, unlockAudio } from "./sound.js";
import { S, freshUi, inviteUrl, isHost } from "./store.js";
import { $, $$, clamp, copyText, esc, icon, pawnSvg, toast } from "./ui.js";

const BASE = gameBase(import.meta.url); // /g/<key>/: this game's server routes

const app = document.getElementById("app");

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

const ADJECTIVES = ["Brave", "Calm", "Swift", "Clever", "Steady", "Bold", "Kind", "Sharp", "Quick", "Wise"];
const NOUNS = ["Medic", "Doctor", "Courier", "Pilot", "Nurse", "Analyst", "Planner", "Scout", "Ranger", "Chemist"];
const pick = (xs) => xs[Math.floor(Math.random() * xs.length)];
const suggestName = () => `${pick(ADJECTIVES)} ${pick(NOUNS)}`;

function saveName(name) {
  name = (name || "").trim().slice(0, 20);
  if (!name) return S.name;
  S.name = name;
  localStorage.setItem(NAME_KEY, name);
  return name;
}

/* ================================================================ routing */

function router() {
  const match = location.pathname.match(/\/r\/([A-Za-z0-9]{4,8})\/?$/);
  closeOverlays();
  if (match) enterRoom(match[1].toUpperCase());
  else leaveRoom();
}
window.addEventListener("popstate", router);

function closeOverlays() {
  closeModal();
  if ($("#sheet")) closeSheet();
  for (const id of ["#menu", "#bubble"]) $(id)?.classList.add("hidden");
}

/* ================================================================ home */
function worldBackdrop() {
  const dots = Object.values(MAP.cities)
    .map(([x, y]) => `<circle cx="${x}" cy="${y}" r="4"/>`)
    .join("");
  return `<svg class="home-map" viewBox="0 40 ${MAP.W} 640" preserveAspectRatio="xMidYMid slice" aria-hidden="true">
    <path d="${MAP.land}" fill="#1a2d4c" fill-rule="evenodd" stroke="#2f4a74" stroke-width="1"/>
    <g fill="#7bd957" opacity=".55">${dots}</g></svg>`;
}


function showRules() {
  simpleModal(`<div class="modal-head"><h2>How to play</h2><div class="sub">Pandemic in one minute</div></div>
    <div class="modal-body rules">${RULES_HTML}</div>
    <div class="modal-foot"><button class="btn primary" data-close>Got it</button></div>`);
}

function simpleModal(html, cls = "narrow") {
  const root = $("#modal-root");
  root.innerHTML = `<div class="modal-bg"><div class="modal ${cls}" role="dialog" aria-modal="true">${html}</div></div>`;
  const bg = root.querySelector(".modal-bg");
  bg.onclick = (e) => {
    if (e.target === bg) closeModal();
  };
  for (const b of root.querySelectorAll("[data-close]")) b.onclick = closeModal;
  (bg.querySelector("input") || bg.querySelector(".btn.primary"))?.focus();
  return root;
}

function askName(title) {
  return new Promise((resolve) => {
    simpleModal(`<div class="modal-head"><h2>${esc(title)}</h2><div class="sub">Pick the name your team sees.</div></div>
      <div class="modal-body"><input class="text wide" id="ask-name" maxlength="20" autocomplete="nickname"></div>
      <div class="modal-foot"><button class="btn primary" id="ask-ok">Join</button></div>`);
    const input = $("#ask-name");
    input.placeholder = suggestName();
    input.value = S.name;
    const done = () => {
      saveName(input.value || input.placeholder);
      closeModal();
      unlockAudio();
      resolve();
    };
    $("#ask-ok").onclick = done;
    input.onkeydown = (e) => {
      if (e.key === "Enter") done();
    };
    input.focus();
  });
}

/* ================================================================ room / socket */
async function enterRoom(code) {
  closeSocket();
  Object.assign(S, { code, state: null, log: [], fatal: null, me: null, connected: false, retry: 0, ui: freshUi() });
  document.title = `Pandemic · ${code}`;
  app.innerHTML = `<div class="center-msg"><div><div class="logo">Pandemic</div><p>Connecting to table ${esc(code)}…</p></div></div>`;
  if (!S.name && !S.tokenFromUrl) await askName(`Join table ${code}`);
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

function renderConn() {
  let el = $("#conn");
  if (S.connected || !S.code || S.fatal) {
    el?.remove();
    return;
  }
  if (!el) {
    el = document.createElement("div");
    el.id = "conn";
    el.className = "conn";
    el.textContent = "Connection lost. Reconnecting…";
    document.body.append(el);
  }
}

function onMessage(msg) {
  switch (msg.type) {
    case "welcome":
      S.me = msg.you;
      S.log = msg.log;
      S.connected = true;
      S.retry = 0;
      renderConn();
      break;
    case "state":
      applyState(msg);
      break;
    case "log":
      S.log.push(msg.entry);
      if (S.log.length > 400) S.log.splice(0, S.log.length - 400);
      if (msg.entry.kind === "chat" && msg.entry.member !== S.me) {
        sfx.chat();
        unreadChat();
      }
      if (S.state?.status === "lobby") renderLobbyChat();
      else onLog(msg.entry, true);
      break;
    case "react":
      showReaction(msg);
      break;
    case "error":
      toast(msg.message, true);
      sfx.error();
      onError();
      break;
    case "fatal":
      S.fatal = msg.message;
      closeSocket();
      app.innerHTML = `<div class="center-msg"><div><div class="logo">Pandemic</div><h2>${esc(msg.message)}</h2><p>Tables close a while after everyone has left.</p><button class="btn primary big" id="home-btn">Start a new table</button></div></div>`;
      $("#home-btn").onclick = () => leaveRoom();
      break;
  }
}

function applyState(next) {
  const prev = S.state;
  const live = !!prev && next.seq === prev.seq + 1 && !document.hidden;
  S.state = next;
  const events = next.event?.events || [];
  if (next.status === "lobby") {
    if (!$("#lobby")) {
      closeOverlays();
      S.ui = freshUi();
      mountLobby();
    }
    renderLobby();
    return;
  }
  const fresh = !$("#game");
  if (fresh) {
    closeOverlays();
    S.ui = freshUi();
    mountGame(app, { leave: () => leaveRoom() });
  }
  onGameState(fresh ? null : prev, next, events, live && !fresh);
}

document.addEventListener("visibilitychange", () => {
  if (!document.hidden && S.code) document.title = `Pandemic · ${S.code}`;
});

/* ================================================================ lobby */
function mountLobby() {
  app.innerHTML = `
  <section id="lobby" class="screen">
    <div class="lobby-card">
      <div class="lobby-head">
        <div class="logo">Pandemic</div>
        <div class="sub">Classic edition · cooperative · 2–4 players</div>
        <div class="room">Table<b>${esc(S.code)}</b></div>
      </div>
      <div class="lobby-body">
        <div class="lobby-col">
          <h2 class="sec">Team</h2>
          <p class="sec-note">Everyone wins or loses together.</p>
          <div id="seats"></div>
          <div class="invite">
            <input id="invite-url" readonly aria-label="Invite link">
            <button class="btn" id="copy-btn">${icon("copy", 16)}Copy link</button>
          </div>
          <div id="watchers"></div>
          <h2 class="sec">Chat</h2>
          <div class="log lobby-log" id="lobby-log"></div>
          <form class="chat lobby-chat" id="lobby-chat">
            <input id="lobby-chat-in" placeholder="Say hello…" aria-label="Chat message" maxlength="300" autocomplete="off">
            <button class="btn" aria-label="Send">${icon("send")}</button>
          </form>
        </div>
        <div class="lobby-col">
          <h2 class="sec">Difficulty</h2>
          <p class="sec-note">How many Epidemic cards are shuffled into the player deck.</p>
          <div class="opts" id="diffs"></div>
          <h2 class="sec">Cards in hand</h2>
          <div class="opts" id="hand-opts"></div>
          <h2 class="sec">Roles</h2>
          <div class="opts" id="role-opts"></div>
          <h2 class="sec">Bot speed</h2>
          <div class="opts three" id="speed-opts"></div>
          <div class="setup-sum" id="setup-sum"></div>
        </div>
      </div>
      <div class="lobby-foot" id="lobby-foot"></div>
    </div>
  </section>`;
  $("#invite-url").value = inviteUrl();
  $("#copy-btn").onclick = async () => toast((await copyText(inviteUrl())) ? "Link copied" : "Copy the link from the box", false);
  $("#lobby-chat").onsubmit = (e) => {
    e.preventDefault();
    const v = $("#lobby-chat-in").value.trim();
    if (v && send({ type: "chat", text: v })) $("#lobby-chat-in").value = "";
  };
  renderLobbyChat();
}

function renderLobbyChat() {
  const log = $("#lobby-log");
  if (!log) return;
  const entries = S.log.slice(-40);
  log.innerHTML =
    entries
      .map((e) => (e.kind === "chat" ? `<div class="e chat">${icon("chat", 16)}<span><b>${esc(e.name)}</b> ${esc(e.text)}</span></div>` : `<div class="e">${icon("info", 16)}<span>${esc(e.text)}</span></div>`))
      .join("") || '<div class="e"><span class="meta">Nothing said yet.</span></div>';
  log.scrollTop = log.scrollHeight;
}

function renderLobby() {
  const state = S.state;
  const seats = state.seats;
  const host = isHost();
  const you = state.you.seat;
  const set = state.settings;
  const choose = set.roles === "choose";
  const hostName = seats.find((s) => s.member === state.host)?.name || state.spectators.find((m) => m.member === state.host)?.name || "the host";
  const botLabel = (key) => S.config.bots.find((b) => b.key === key);
  $("#seats").innerHTML =
    seats
      .map((s, i) => {
        const mine = i === you;
        const role = s.role ? ROLES[s.role] : null;
        const canPick = choose && (mine || (s.bot && host));
        const bot = s.bot ? botLabel(s.bot) : null;
        const status = s.bot ? `Bot · ${bot?.label || s.bot} ${"★".repeat(bot?.stars || 1)}` : s.connected ? "Online" : "Away";
        const roleBtn = choose
          ? `<button class="role-pick" data-seat="${i}" ${canPick ? "" : "disabled"} style="${role ? `--rc:${role.color}` : ""}">${role ? `${pawnSvg(role.color, 16)}${role.name}` : canPick ? "Pick a role" : "No role yet"}</button>`
          : '<small class="dealt">Role dealt at the start</small>';
        const lead = role ? pawnSvg(role.color, 30) : `<span style="color:var(--muted)">${icon(s.bot ? "bot" : "person", 24)}</span>`;
        const tags = `${s.member === state.host ? '<span class="tag">host</span> ' : ""}${mine ? '<span class="tag you">you</span>' : ""}`;
        const rename = mine ? `<button class="icon-btn" id="rename-btn" aria-label="Change your name" title="Change your name">${icon("edit", 16)}</button>` : "";
        const remove = host && !mine ? `<button class="icon-btn" data-remove="${i}" aria-label="Remove ${esc(s.name)}">${icon("close")}</button>` : "";
        const stand = mine ? `<button class="btn small" id="stand-btn">Watch instead</button>` : "";
        return `<div class="seat">${lead}
          <div class="who"><b>${esc(s.name)}</b>${tags}<small>${status}</small>${roleBtn}</div>${rename}${stand}${remove}</div>`;
      })
      .join("") + emptySeats(seats.length, host, you);
  for (const b of $$("#seats [data-remove]")) b.onclick = () => send({ type: "remove_seat", seat: +b.dataset.remove });
  for (const b of $$("#seats [data-bot]")) b.onclick = () => send({ type: "add_bot", bot: b.dataset.bot });
  for (const b of $$("#seats .role-pick:not(:disabled)")) b.onclick = (e) => roleMenu(+b.dataset.seat, e.currentTarget);
  $("#stand-btn") && ($("#stand-btn").onclick = () => send({ type: "stand" }));
  $("#sit-btn") && ($("#sit-btn").onclick = () => send({ type: "sit" }));
  $("#rename-btn") && ($("#rename-btn").onclick = renameModal);

  const watchers = state.spectators;
  $("#watchers").innerHTML = watchers.length
    ? `<p class="sec-note watchers">${icon("person", 14)}Watching: ${watchers.map((m) => esc(m.name) + (m.member === S.me ? " (you)" : "")).join(", ")}</p>`
    : "";

  const dis = host ? "" : "disabled";
  $("#diffs").innerHTML = DIFFS.map(
    (d) =>
      `<button class="opt" aria-pressed="${set.epidemics === d.n}" data-n="${d.n}" ${dis}><b>${d.name}</b><span class="epis" aria-hidden="true">${"<i></i>".repeat(d.n)}</span><small><b style="display:inline;font-size:12px;color:var(--text)">${d.n} Epidemic cards.</b> ${d.desc}</small></button>`,
  ).join("");
  $("#hand-opts").innerHTML = `
    <button class="opt" aria-pressed="${set.open_hands}" data-v="open" ${dis}><b>Open</b><small>Everyone sees every hand, as in the rulebook. Default.</small></button>
    <button class="opt" aria-pressed="${!set.open_hands}" data-v="closed" ${dis}><b>Closed</b><small>Only you see your cards. You have to communicate and cooperate MORE!</small></button>`;
  $("#role-opts").innerHTML = `
    <button class="opt" aria-pressed="${!choose}" data-v="random" ${dis}><b>Random</b><small>Roles are dealt at the start of the game. Default.</small></button>
    <button class="opt" aria-pressed="${choose}" data-v="choose" ${dis}><b>Choose</b><small>Each player picks a role in the lobby; the host picks for bots. Seats without a role get a random one.</small></button>`;
  $("#speed-opts").innerHTML = SPEEDS.map((sp) => `<button class="opt" aria-pressed="${set.bot_speed === sp.key}" data-v="${sp.key}" ${dis}><b>${sp.name}</b><small>${sp.desc}</small></button>`).join("");
  const settings = (changes) => send({ type: "settings", changes });
  for (const b of $$("#diffs .opt")) b.onclick = () => settings({ epidemics: +b.dataset.n });
  for (const b of $$("#hand-opts .opt")) b.onclick = () => settings({ open_hands: b.dataset.v === "open" });
  for (const b of $$("#role-opts .opt")) b.onclick = () => settings({ roles: b.dataset.v });
  for (const b of $$("#speed-opts .opt")) b.onclick = () => settings({ bot_speed: b.dataset.v });

  const n = clamp(seats.length, 2, 4);
  const handN = CFG.startingHand[n];
  const deck = 48 + 5 - n * handN;
  $("#setup-sum").innerHTML = `<b>Setup preview.</b> ${n} players each start with <b>${handN} cards</b>. The remaining ${deck} cards are split into <b>${set.epidemics} piles</b> with one Epidemic each, so the deck holds <b>${deck + set.epidemics}</b> cards (about ${Math.floor((deck + set.epidemics) / 2)} turns). The game starts with 9 infected cities, and every pawn starts at the research station in Atlanta.`;

  const enough = seats.length >= (S.config.min_seats || 2);
  $("#lobby-foot").innerHTML = host
    ? `<span class="note">${enough ? "You are the host. Only the host can change settings." : "Pandemic needs at least 2 players: invite someone or add a bot."}</span>
       <button class="btn primary big" id="start-btn" ${enough ? "" : "disabled"}>Start game</button>`
    : `<span class="note">Waiting for ${esc(hostName)} to start the game. Only the host can change settings.</span>`;
  $("#start-btn") && ($("#start-btn").onclick = () => send({ type: "start" }));
  renderLobbyChat();
}

function emptySeats(count, host, you) {
  const max = S.config.max_seats || 4;
  if (count >= max) return "";
  const bots = S.config.bots
    .map((b) => `<button class="btn small" data-bot="${b.key}" title="${esc(b.description)}">${icon("bot", 16)}Add ${b.label} ${"★".repeat(b.stars)}</button>`)
    .join("");
  const sit = you == null ? '<button class="btn small primary" id="sit-btn">Take a seat</button>' : "";
  const rows = [];
  for (let i = count; i < max; i++) {
    const first = i === count;
    rows.push(`<div class="seat empty"><span>Open seat</span>${first ? `<span class="sp"></span>${sit}${host ? bots : ""}` : ""}</div>`);
  }
  return rows.join("");
}

function roleMenu(seat, btn) {
  const m = $("#menu");
  const seats = S.state.seats;
  const taken = Object.fromEntries(seats.filter((s, i) => s.role && i !== seat).map((s) => [s.role, s.name]));
  m.innerHTML =
    `<button role="menuitem" data-role="">${icon("help")}Random role</button>` +
    Object.entries(ROLES)
      .map(
        ([key, r]) =>
          `<button role="menuitem" data-role="${key}" ${taken[key] ? "disabled" : ""} title="${r.short}">${pawnSvg(r.color, 18)}<span>${r.name}<small>${taken[key] ? `${esc(taken[key])} plays it` : r.short}</small></span></button>`,
      )
      .join("");
  m.classList.remove("hidden");
  const r = btn.getBoundingClientRect();
  m.style.left = `${clamp(r.left, 8, innerWidth - m.offsetWidth - 8)}px`;
  m.style.top = `${r.bottom + 6 + m.offsetHeight < innerHeight ? r.bottom + 6 : Math.max(8, r.top - m.offsetHeight - 6)}px`;
  m.querySelector("button:not(:disabled)")?.focus();
  m.onclick = (e) => {
    const b = e.target.closest("[data-role]");
    if (!b || b.disabled) return;
    m.classList.add("hidden");
    send({ type: "pick_role", seat, role: b.dataset.role || null });
  };
}

function renameModal() {
  simpleModal(`<div class="modal-head"><h2>Your name</h2></div>
    <div class="modal-body"><input class="text wide" id="rename-in" maxlength="20" autocomplete="nickname"></div>
    <div class="modal-foot"><button class="btn" data-close>Cancel</button><button class="btn primary" id="rename-ok">Save</button></div>`);
  const input = $("#rename-in");
  input.value = S.name;
  input.select();
  const done = () => {
    const name = saveName(input.value);
    closeModal();
    if (name) send({ type: "rename", name });
  };
  $("#rename-ok").onclick = done;
  input.onkeydown = (e) => {
    if (e.key === "Enter") done();
  };
}

/* ================================================================ global wiring */
document.addEventListener("click", (e) => {
  unlockAudio();
  if (!e.target.closest("#menu, #menu-btn, .role-pick")) $("#menu")?.classList.add("hidden");
  onDocClick(e);
});
addEventListener("keydown", (e) => {
  if (e.key === "Escape" && !$("#game") && $("#modal-root").innerHTML) {
    closeModal();
    return;
  }
  if (e.key === "Escape" && !$("#game")) $("#menu")?.classList.add("hidden");
  onKey(e);
});
let rsz = 0;
addEventListener("resize", () => {
  cancelAnimationFrame(rsz);
  rsz = requestAnimationFrame(onResize);
});

async function boot() {
  const fromUrl = takeTokenFromUrl();
  S.tokenFromUrl = !!fromUrl;
  S.token = fromUrl || localStorage.getItem(TOKEN_KEY) || newToken();
  localStorage.setItem(TOKEN_KEY, S.token);
  S.name = localStorage.getItem(NAME_KEY) || "";
  try {
    const res = await fetch(`${BASE}api/config`);
    S.config = await res.json();
  } catch {
    app.innerHTML = '<div class="center-msg"><div><div class="logo">Pandemic</div><p>The server can’t be reached.</p></div></div>';
    return;
  }
  initData(S.config);
  router();
}

boot();
