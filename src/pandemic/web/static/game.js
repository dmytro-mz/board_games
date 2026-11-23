// The game screen: status strip, map, dock (actions + hand), side panel (team, infection discard, log, chat),
// the resolve panel for draws, epidemics and infections, and every dialog.
import { animatePawn, ensureVisible, fitView, highlightCity, legendHtml, queueMap, refit, renderMap, renderMapBase, showWholeMap, viewBox, zoom } from "./board.js";
import { CFG, CITIES, DCOLS, DIFFS, DNAME, EVENTS, LOSS, ROLES, SHAPES } from "./data.js";
import { act, send } from "./net.js";
import { cureOptions, dockActs, eventPlayable, modeTargets, moveOptions, movingPawn, myEvents, shareOptions, treatOptions } from "./rules.js";
import { isMuted, setMuted, sfx } from "./sound.js";
import { S, actionsLeft, cubeCount, cubesAt, cures, g, infectionRate, inviteUrl, isHost, me, mySeat, myTurn, need, over, players, seatName, stations } from "./store.js";
import { $, $$, cardHtml, cardName, chip, cityName, clamp, colorCounts, copyText, esc, glyph, icon, ichip, isEv, listText, pawnSvg, plural, setHtml, toast, vialSvg } from "./ui.js";

const HELP = {};
const roleOf = (p) => ROLES[p.role];
const who = (i) => (i === mySeat() ? "You" : esc(seatName(i)));
const whoLower = (i) => (i === mySeat() ? "you" : esc(seatName(i)));

/* ================================================================ shell */
export function mountGame(app, hooks) {
  app.innerHTML = `
  <section id="game" class="screen">
    <header class="status">
      <div class="turn-row" id="turn-row"></div>
      <div class="threat-row" id="threat-row"></div>
    </header>
    <main class="board" id="board">
      <svg id="map" preserveAspectRatio="xMidYMid meet" aria-label="World map. Tab to a city, arrow keys move between cities, Enter opens it."></svg>
      <div class="feed" id="feed"></div>
      <div class="mode-hint hidden" id="mode-hint"></div>
      <div class="map-tools">
        <button id="zin" aria-label="Zoom in" title="Zoom in">${icon("plus")}</button>
        <button id="zout" aria-label="Zoom out" title="Zoom out">${icon("minus")}</button>
        <button id="zfit" aria-label="Show the whole map" title="Whole map">${icon("fit")}</button>
        <button id="legend-btn" aria-label="Map legend" title="Map legend" aria-expanded="false">${icon("legend")}</button>
      </div>
      <div class="legend hidden" id="legend"></div>
      <div class="popover hidden" id="pop" role="dialog"></div>
      <section class="resolve hidden" id="resolve" aria-live="polite"></section>
      <div class="reactions" id="reactions" aria-hidden="true"></div>
    </main>
    <section class="dock" id="dock"></section>
    <aside class="side" id="side" aria-label="Team, infection discard and log">
      <div class="side-head"><b>Team &amp; log</b><button class="icon-btn" id="side-close" aria-label="Close panel">${icon("close")}</button></div>
      <section class="sec" id="team" aria-label="Team"></section>
      <section class="sec" id="discard"></section>
      <section class="sec log-sec" id="log-sec"><h2><button class="log-toggle" id="log-toggle" aria-expanded="true">${icon("down", 16)}Log</button></h2><div class="log" id="log"></div></section>
      <form class="chat" id="chat">
        <input id="chat-in" placeholder="Plan with your team…" aria-label="Chat message" maxlength="300" autocomplete="off">
        <button type="button" class="icon-btn" id="react-btn" aria-label="Quick reaction">${icon("smile")}</button>
        <button class="btn" aria-label="Send">${icon("send")}</button>
        <div class="react hidden" id="react"></div>
      </form>
    </aside>
    <div class="scrim hidden" id="scrim"></div>
  </section>`;
  renderMapBase({
    city: onCityClick,
    background: hidePop,
    viewChanged: () => {
      hidePop();
      placeResolve();
    },
  });
  S.ui.logOpen = localStorage.getItem("pandemic.log") !== "0";
  $("#side-close").onclick = () => toggleSide(false);
  $("#scrim").onclick = () => toggleSide(false);
  $("#log-toggle").onclick = () => {
    S.ui.logOpen = !S.ui.logOpen;
    localStorage.setItem("pandemic.log", S.ui.logOpen ? "1" : "0");
    renderLog();
  };
  $("#react").innerHTML = (S.config.reactions || []).map((r) => `<button type="button" aria-label="React ${r}">${r}</button>`).join("");
  $("#react-btn").onclick = (e) => {
    e.stopPropagation();
    $("#react").classList.toggle("hidden");
  };
  for (const b of $$("#react button")) {
    b.onclick = () => {
      send({ type: "react", emoji: b.textContent });
      $("#react").classList.add("hidden");
    };
  }
  $("#chat").onsubmit = (e) => {
    e.preventDefault();
    const v = $("#chat-in").value.trim();
    if (!v) return;
    if (send({ type: "chat", text: v })) $("#chat-in").value = "";
  };
  S.ui.hooks = hooks;
  renderGame();
  requestAnimationFrame(() => fitView());
}

/* ================================================================ state updates */
export function onGameState(prev, next, events, live) {
  const ui = S.ui;
  const game = next.game;
  if (next.event?.kind === "game_start") {
    Object.assign(ui, { mode: null, pawn: null, airlift: null, flow: false, turnEvents: [], infectPanel: null, fx: {}, overShown: false, prevT: null, feed: [], feedQueue: [], holding: false });
    closeModal();
  }
  trackTurn(events, prev?.game);
  if (!myTurn() && ["drive", "direct", "charter", "shuttle", "dispatch"].includes(ui.mode)) ui.mode = null;
  if (events.some((e) => e.kind === "turn")) {
    ui.pawn = null;
    ui.passArm = false;
  }
  renderGame();
  if (live) playEffects(events);
  // your turn starts
  const mine = (gm) => gm && gm.current === next.you.seat && gm.step === "actions" && !gm.result;
  if (live && mine(game) && !mine(prev?.game)) {
    sfx.turn();
    if (document.hidden) document.title = "Your turn! · Pandemic";
  }
  if (next.status === "game_over" && !ui.overShown) {
    ui.overShown = true;
    const won = game.result?.won;
    setTimeout(
      () => {
        if (S.state?.status !== "game_over") return;
        if (live) (won ? sfx.fanfare : sfx.lose)();
        overModal();
      },
      live ? 1400 : 0,
    );
  }
}

// Collect the events of the current turn's end (draw, epidemics, infections) for the resolve panel.
function trackTurn(events, prevGame) {
  const ui = S.ui;
  for (const ev of events) {
    if (ev.kind === "setup") continue;
    if (ev.kind === "draw") {
      ui.turnEvents = [ev];
      ui.infectPanel = null;
      continue;
    }
    if (ev.kind === "turn") {
      if (ui.turnEvents.some((e) => e.kind === "infect_step" || e.kind === "quiet_night")) {
        ui.infectPanel = { seat: prevGame?.current ?? null, events: ui.turnEvents, at: performance.now() };
        clearTimeout(ui.infectTimer);
        ui.infectTimer = setTimeout(() => {
          ui.infectPanel = null;
          renderResolve();
        }, 14000);
      }
      ui.turnEvents = [];
      continue;
    }
    if (ui.turnEvents.length) ui.turnEvents.push(ev);
  }
}

export function onLog(entry, live) {
  if (!S.state?.game) return;
  if (live && entry.kind === "game") feed(entry);
  renderLog();
}

/* ================================================================ effects */
function playEffects(events) {
  const fx = S.ui.fx;
  const now = performance.now();
  const flash = [];
  let flashKind = "inf";
  let sound = null;
  const prio = ["outbreak", "epidemic", "cure", "flight", "move", "infect", "treat", "build", "event", "card"];
  const want = (s) => {
    if (!sound || prio.indexOf(s) < prio.indexOf(sound)) sound = s;
  };
  for (const ev of events) {
    switch (ev.kind) {
      case "move":
        animatePawn(ev.pawn, ev.path);
        want(ev.by === "drive" ? "move" : "flight");
        break;
      case "treat":
      case "medic_clear":
        (fx.ghost ||= []).push({ id: ev.city, col: ev.color, n: ev.removed, at: now });
        want("treat");
        break;
      case "build":
        fx.newStation = { id: ev.city, at: now };
        want("build");
        break;
      case "infect":
        if (ev.setup) break;
        flash.push(ev.city);
        want("infect");
        break;
      case "outbreak":
        flash.push(ev.city, ...ev.to);
        flashKind = "";
        want("outbreak");
        break;
      case "epidemic":
        want("epidemic");
        break;
      case "cure":
        want("cure");
        break;
      case "event":
        want("event");
        break;
      case "draw":
      case "share":
      case "discard":
      case "take_event":
        want("card");
        break;
    }
  }
  if (flash.length) {
    fx.flash = [...new Set(flash)];
    fx.flashAt = now;
    fx.flashKind = flashKind;
  }
  if (sound) sfx[sound]();
  renderMap();
  if (fx.ghost?.length || fx.newStation) setTimeout(queueMap, 850);
  if (flash.length) setTimeout(queueMap, 2500);
}

// One move logs several lines at once: they join the feed together, so none of them shows for a single frame.
let feedId = 0;
let feedTimer = 0;
function feed(entry) {
  S.ui.feedQueue.push({ id: ++feedId, ...entry });
  $("#live").textContent = entry.text;
  if (!feedTimer) feedTimer = setTimeout(flushFeed, 60);
}

function flushFeed() {
  clearTimeout(feedTimer);
  feedTimer = 0;
  const ui = S.ui;
  const fresh = ui.feedQueue.splice(0).slice(-3);
  for (const f of fresh) {
    setTimeout(() => {
      $(`#feed [data-id="${f.id}"]`)?.classList.add("gone");
      setTimeout(() => {
        ui.feed = ui.feed.filter((x) => x.id !== f.id);
        renderFeed();
      }, 260);
    }, f.tone === "bad" ? 9000 : 6000);
  }
  ui.feed = [...ui.feed, ...fresh].slice(-3);
  renderFeed();
}

export function showReaction(msg) {
  const box = $("#reactions");
  if (!box) return;
  const name = msg.seat != null ? seatName(msg.seat) : S.state?.spectators.find((m) => m.member === msg.member)?.name || "";
  const el = document.createElement("div");
  el.className = "reaction";
  el.innerHTML = `<span class="emo">${esc(msg.emoji)}</span><span class="nm">${esc(name)}</span>`;
  el.style.right = `${16 + Math.random() * 60}px`;
  box.append(el);
  setTimeout(() => el.remove(), 2600);
}

/* ================================================================ render all */
export function renderGame() {
  if (!$("#game") || !g()) return;
  renderStatus();
  renderMap();
  renderDock();
  renderSide();
  if (S.ui.feedQueue.length) flushFeed(); // the server logs a move's lines just before its state
  else renderFeed();
  renderResolve();
  renderHint();
  placeFeed();
  syncForced();
  refreshPop();
}

function renderHint() {
  const hint = $("#mode-hint");
  const mode = S.ui.mode;
  hint.classList.toggle("hidden", !mode);
  $("#resolve")?.classList.toggle("picking", !!mode); // the panel would cover the cities to pick from
  if (!mode) {
    syncHold();
    setHtml(hint, "");
    return;
  }
  const p = movingPawn();
  const pl = players();
  const moving = mode !== "airlift" && mode !== "grant" && p !== mySeat() ? `Moving ${esc(pl[p].name)}'s pawn. ` : "";
  const at = pl[p] ? cityName(pl[p].at) : "";
  const lifted = pl[S.ui.airlift ?? mySeat()];
  const txt = {
    drive: "Drive / Ferry: click a connected city",
    direct: "Direct flight: click a city from your hand",
    charter: `Charter flight: click any city (discards ${at})`,
    shuttle: "Shuttle flight: click another research station",
    dispatch: "Dispatch: click a city with another pawn",
    airlift: `Airlift: click a city to move ${lifted?.i === mySeat() ? "your pawn" : `${esc(lifted?.name)}'s pawn`} there. Free, discards Airlift.`,
    grant: "Government Grant: click a city for the new research station. Free, discards the event.",
  }[mode];
  setHtml(hint, `<span>${moving}${txt}</span><button class="btn small" id="mode-cancel">Cancel</button>`);
  $("#mode-cancel").onclick = () => setMode(null);
}

export function setMode(m) {
  const ui = S.ui;
  ui.mode = ui.mode === m ? null : m;
  if (!ui.mode) {
    ui.flow = false;
    ui.airlift = null;
  }
  hidePop();
  renderGame();
}

/* ================================================================ status strip */
function renderStatus() {
  const game = g();
  const pl = players();
  const cp = pl[game.current];
  const r = roleOf(cp);
  const mine = game.current === mySeat();
  const res = game.result;
  const rate = infectionRate();
  const pi = { actions: 0, draw: 1, epidemic: 1, infect: 2 }[game.step] ?? 0;
  const phases = ["Actions", "Draw 2 cards", `Infect ${rate} cities`]
    .map((t, i) => `<li class="${i === pi ? "on" : i < pi ? "done" : ""}" ${i === pi ? 'aria-current="step"' : ""}>${i < pi ? icon("check", 14) : ""}${t}</li>`)
    .join("");
  const left = game.actions_left;
  const pips = Array.from({ length: 4 }, (_, i) => `<i class="${i < left ? "full" : ""}"></i>`).join("");
  const al = res
    ? ""
    : game.step === "actions"
      ? `<div class="al"><span class="pips" aria-hidden="true">${pips}</span><span><b>${left}</b> ${left === 1 ? "action" : "actions"}<span class="al-left"> left</span></span></div>`
      : `<div class="al"><span style="color:var(--muted)">Actions done</span></div>`;
  const title = res ? (res.won ? "Victory" : "Defeat") : mine ? "Your turn" : `${esc(cp.name)} is playing`;
  const sub = res ? `Game over · turn ${res.turn}` : `${esc(cp.name)} · ${r.name} · in ${cityName(cp.at)} · turn ${game.turn}`;
  const unread = S.ui.unread;
  setHtml($("#turn-row"), `
    <div class="who">${res ? vialSvg(res.won ? "blue" : "red", res.won ? "cured" : "none", 30) : pawnSvg(r.color, 30)}<div><b>${title}</b><span class="sub">${sub}</span></div></div>
    ${al}
    ${res ? "" : `<ol class="phases" aria-label="Turn phases">${phases}</ol>`}
    <span class="sp"></span>
    <div class="tools">
      <span class="room-code" title="Table code">${esc(S.code)}</span>
      <button class="btn ghost team-btn" id="team-btn" aria-label="Open team and log"><span class="pw">${pl.map((p) => pawnSvg(roleOf(p).color, 18)).join("")}</span><span class="team-label">Team &amp; log</span> ${unread ? `<span class="badge">${unread}</span>` : ""}</button>
      <button class="btn ghost" id="help-btn" aria-label="Help and shortcuts">${icon("help")}<span class="help-label">Help</span></button>
      <button class="icon-btn" id="menu-btn" aria-label="Menu" aria-haspopup="menu">${icon("menu")}</button>
    </div>`);
  $("#team-btn").onclick = () => toggleSide(true);
  $("#help-btn").onclick = openHelp;
  $("#menu-btn").onclick = (e) => {
    e.stopPropagation();
    openMenu(e.currentTarget);
  };

  const ob = Array.from({ length: 9 }, (_, i) =>
    i === 8
      ? `<span class="cell end" title="8th outbreak: you lose">${icon("skull", 14)}</span>`
      : `<span class="cell ${i <= game.outbreaks && i > 0 ? "hit" : ""} ${i === game.outbreaks + 1 ? "next" : ""}">${i}</span>`,
  ).join("");
  const ir = CFG.infectionRate.map((v, i) => `<span class="cell ${i === game.epidemics_drawn ? "now" : ""} ${i < game.epidemics_drawn ? "past" : ""}">${v}</span>`).join("");
  const cu = cures();
  const nCured = Object.values(cu).filter((v) => v !== "none").length;
  const vials = DCOLS.map(
    (c) => `<span title="${DNAME[c]}: ${cu[c] === "none" ? "not cured yet" : cu[c]}" class="${cu[c] === "eradicated" ? "erad" : ""}">${vialSvg(c, cu[c], 24)}</span>`,
  ).join("");
  const cl = DCOLS.map((c) => {
    const n = game.supply[c];
    const low = n <= 6;
    return `<span class="cl ${low ? "low" : ""}" title="${n} ${c} cubes left. If a colour runs out, you lose.">${low ? icon("warn") : glyph(c, 12)}${n}</span>`;
  }).join("");
  const deck = game.player_deck;
  const epis = Array.from({ length: game.epidemics }, (_, i) => `<i class="${i < game.epidemics_drawn ? "out" : ""}"></i>`).join("");
  const ep = `<span class="ep" title="${game.epidemics_drawn} of ${game.epidemics} Epidemic cards drawn"><span class="epi-pips" aria-hidden="true">${epis}</span>Epidemics ${game.epidemics_drawn} of ${game.epidemics} drawn</span>`;
  const T = { ob: game.outbreaks, ir: game.epidemics_drawn, cu: nCured, cl: DCOLS.map((c) => game.supply[c]).join(), dk: deck, st: stations().length };
  setHtml($("#threat-row"), `
    <div class="trk" data-t="ob"><div class="trk-l">Outbreaks <b>${game.outbreaks} of 8</b></div><div class="trk-v">${ob}</div></div>
    <div class="trk" data-t="ir"><div class="trk-l">Infection rate <b>${rate} per turn</b></div><div class="trk-v">${ir}</div></div>
    <div class="trk" data-t="cu"><div class="trk-l">Cures <b>${nCured} of 4</b></div><div class="trk-v" style="gap:8px">${vials}</div></div>
    <div class="trk" data-t="cl"><div class="trk-l">Cubes left</div><div class="trk-v">${cl}</div></div>
    <div class="trk deck-v" data-t="dk"><div class="trk-l">Player deck <b>${plural(deck, "card")}</b><span class="turns"> · about ${Math.floor(deck / 2)} turns</span><button class="info" data-help="player" aria-label="How the player deck works">${icon("info")}</button></div><div class="trk-v">${ep}</div></div>
    <div class="trk" data-t="st"><div class="trk-l">Stations</div><div class="trk-v"><svg width="16" height="16" viewBox="-8 -8 16 16" aria-hidden="true"><use href="#station"/></svg>&nbsp;<b>${stations().length} of 6</b></div></div>`);
  if (S.ui.prevT) for (const k in T) if (T[k] !== S.ui.prevT[k]) $(`.trk[data-t="${k}"]`)?.classList.add("bump");
  S.ui.prevT = T;

  HELP.player = `<p><b>Player deck · ${plural(deck, "card")}</b>, about ${Math.floor(deck / 2)} turns. You lose if someone has to draw and the deck is empty.</p>
    <p><b>Epidemic piles.</b> At setup the deck was split into ${game.epidemics} piles of about the same size, with one Epidemic shuffled into each pile.</p>`;
}

/* ================================================================ dock */
function renderDock() {
  const game = g();
  const self = me();
  const dock = $("#dock");
  if (!self) {
    renderWatchDock(dock);
    return;
  }
  const role = roleOf(self);
  const counts = colorCounts(self.hand);
  const n = need(self.role);
  const mine = myTurn();
  const left = actionsLeft();
  let body;
  if (game.result) {
    body = `<div class="wait"><p><b>Game over: ${game.result.won ? "victory" : "defeat"}.</b> The board stays as it ended so the team can look back.</p>
      <div class="row"><button class="btn" id="show-result">Show result</button>${isHost() ? '<button class="btn primary" id="again-btn">Play again</button><button class="btn" id="lobby-btn">Back to lobby</button>' : ""}</div></div>`;
  } else if (S.state.seats[self.i]?.autoplay) {
    body = `<div class="wait"><p><b>The autopilot is playing for you.</b> Your next action takes over again.</p></div>`;
  } else if (mine && left > 0) {
    const acts = dockActs();
    const p = movingPawn();
    for (const a of acts) {
      if (role.bonus[a.k] && a.ok) a.s = `<span class="bonus" style="--rc:${role.color}">${role.bonus[a.k]}</span>`;
      if (p !== self.i && ["build", "treat", "share", "cure"].includes(a.k) && a.ok) a.s += " (your pawn)";
    }
    body = `<div class="act-grid">${acts
      .map(
        (a) => `<button class="act ${S.ui.mode === a.k ? "on" : ""} ${a.ready ? "ready" : ""}" data-act="${a.k}" ${a.ok ? "" : "disabled"} aria-label="${a.t}${a.ok ? "" : `: ${a.no}`}" ${a.ok ? "" : `title="${a.no}"`}>
        <span class="t">${icon(a.i)}${a.t}</span><span class="s">${a.ok ? a.s : a.no}</span></button>`,
      )
      .join("")}</div>`;
  } else if (mine) {
    body = `<div class="wait"><p><b>No actions left.</b></p></div>`;
  } else if (game.step === "draw" && game.current === self.i && game.waiting_for === self.i) {
    body = `<div class="wait"><p><b>No actions left.</b> Draw 2 player cards to continue.</p><div class="row"><button class="btn primary big" id="draw-btn">${icon("cards")}Draw 2 player cards</button></div></div>`;
  } else if (game.over_limit === self.i) {
    body = `<div class="wait"><p><b>Hand limit.</b> Discard down to ${CFG.hand} cards, or play an event card.</p><div class="row"><button class="btn primary" id="limit-btn">Choose cards</button></div></div>`;
  } else if (game.current === self.i) {
    body = `<div class="wait"><p><b>${game.step === "epidemic" ? "Epidemic!" : "Infecting cities."}</b> Follow the panel on the map.</p></div>`;
  } else {
    const evs = myEvents();
    body = `<div class="wait"><p><b>${esc(seatName(game.current))} is playing.</b> ${evs.length ? "You can still play an event card or plan in the chat." : "Plan the next moves in the chat."}</p>
      ${evs.length ? `<div class="row">${evs.map((e) => `<button class="btn" data-event="${e.card}">${icon("event")}Play ${cardName(e.card)}</button>`).join("")}</div>` : ""}</div>`;
  }
  const passBtn = mine && left > 0 ? `<button class="btn small ${S.ui.passArm ? "alert" : ""}" id="pass-btn">${icon("skip", 16)}${S.ui.passArm ? `Skip ${plural(left, "action")}?` : "End actions"}</button>` : "";
  const undoBtn = mine ? `<button class="btn small" id="undo-btn" ${game.can_undo ? "" : "disabled"}>${icon("undo", 16)}Undo</button>` : "";
  let roleExtra = "";
  if (mine && left > 0 && self.role === "dispatcher") {
    const p = movingPawn();
    roleExtra = `<span class="pawn-pick" role="group" aria-label="Pawn to move">${players()
      .map((o) => `<button class="pp ${o.i === p ? "on" : ""}" data-pawn="${o.i}" aria-pressed="${o.i === p}" title="Move ${o.i === self.i ? "your pawn" : esc(o.name)}">${pawnSvg(roleOf(o).color, 18)}${o.i === self.i ? "You" : esc(o.name)}</button>`)
      .join("")}</span>`;
  }
  if (mine && left > 0 && self.role === "planner") {
    const evs = game.player_discard.filter(isEv);
    const ok = !self.stored && evs.length > 0;
    const why = self.stored ? "You already store an event" : "No event in the player discard";
    roleExtra = `<button class="btn small" id="store-btn" ${ok ? "" : `disabled title="${why}"`}>${icon("store", 16)}Take event</button>`;
  }
  const prog = DCOLS.filter((c) => cures()[c] === "none" && counts[c] > 0)
    .sort((a, b) => counts[b] - counts[a])
    .map(
      (c) =>
        `<button class="prog ${counts[c] >= n ? "ready" : ""}" data-col="${c}" title="${counts[c]} of ${n} ${c} cards needed for a cure">${glyph(c, 11)}${DNAME[c]} ${counts[c]}/${n}</button>`,
    )
    .join("");
  const hand = self.hand || [];
  const cards = hand.map((c) => cardHtml(c, { here: c === self.at })).join("") + (self.stored ? cardHtml(self.stored, { stored: true }) : "");
  setHtml(
    dock,
    `
    <div class="actions">
      <div class="act-head">
        <button class="role-chip" id="role-chip" aria-label="${role.name}: show role details">${pawnSvg(role.color, 22)}${role.name}${icon("info")}</button>
        ${roleExtra}<span class="sp"></span>${undoBtn}${passBtn}
      </div>
      ${body}
    </div>
    <div class="hand-panel">
      <div class="hand-head"><h2>Your hand</h2><span class="lim ${hand.length > CFG.hand ? "over" : ""}">${hand.length} of ${CFG.hand}</span>${prog}</div>
      <div class="hand" id="hand">${cards}</div>
    </div>`,
  );
  bindDock(self);
}

function renderWatchDock(dock) {
  const game = g();
  const cp = players()[game.current];
  const visible = cp.hand != null;
  setHtml(
    dock,
    `
    <div class="actions">
      <div class="act-head"><span class="watch">${icon("person", 16)}You are watching this game</span><span class="sp"></span></div>
      <div class="wait"><p>${game.result ? `<b>Game over: ${game.result.won ? "victory" : "defeat"}.</b>` : `<b>${esc(cp.name)} is playing.</b> Seats open up again in the lobby.`}</p>
      ${game.result ? '<div class="row"><button class="btn" id="show-result">Show result</button></div>' : ""}</div>
    </div>
    <div class="hand-panel">
      <div class="hand-head"><h2>${esc(cp.name)}'s hand</h2><span class="lim">${cp.count} of ${CFG.hand}</span></div>
      <div class="hand" id="hand">${visible ? cp.hand.map((c) => cardHtml(c)).join("") : `<span class="meta">${plural(cp.count, "card")} (closed hands)</span>`}</div>
    </div>`,
  );
  $("#show-result") && ($("#show-result").onclick = overModal);
  for (const cd of $$("#dock .pcard[data-card]")) {
    const c = cd.dataset.card;
    if (!isEv(c)) cd.onclick = () => showPop(c, true);
  }
  fitHand();
}

function bindDock(self) {
  const on = (id, fn) => {
    const el = $(id);
    if (el) el.onclick = fn;
  };
  on("#role-chip", (e) => openSheet(self.i, e.currentTarget));
  on("#pass-btn", passClick);
  on("#undo-btn", undo);
  on("#draw-btn", () => act({ type: "draw" }));
  on("#limit-btn", () => {
    S.ui.forced = null;
    S.ui.flow = false;
    syncForced(true);
  });
  on("#show-result", overModal);
  on("#again-btn", () => send({ type: "play_again" }));
  on("#lobby-btn", () => send({ type: "to_lobby" }));
  on("#store-btn", storeModal);
  for (const b of $$("#dock .act")) b.onclick = () => actKey(b.dataset.act);
  for (const b of $$("#dock [data-event]")) b.onclick = () => playEvent(b.dataset.event);
  for (const b of $$("#dock .pp")) {
    b.onclick = () => {
      S.ui.pawn = +b.dataset.pawn;
      if (S.ui.mode && S.ui.mode !== "airlift" && S.ui.mode !== "grant") S.ui.mode = null;
      hidePop();
      renderGame();
    };
  }
  const hand = $("#hand");
  for (const cd of $$("#dock .pcard[data-card]")) {
    const c = cd.dataset.card;
    cd.onclick = () => (isEv(c) ? playEvent(c) : showPop(c, true));
    if (!isEv(c)) {
      cd.onmouseenter = cd.onfocus = () => highlightCity(c, true);
      cd.onmouseleave = cd.onblur = () => highlightCity(c, false);
    }
  }
  for (const v of $$("#dock .prog")) {
    v.onmouseenter = v.onfocus = () => {
      hand.dataset.focus = v.dataset.col;
    };
    v.onmouseleave = v.onblur = () => {
      delete hand.dataset.focus;
    };
  }
  fitHand();
}

export function fitHand() {
  const hand = $("#hand");
  if (!hand) return;
  hand.classList.remove("tiles");
  const n = hand.children.length;
  const w = hand.children[0]?.offsetWidth || 96;
  if (n * w + (n - 1) * 8 > hand.clientWidth) {
    hand.classList.add("tiles");
    for (const h of hand.querySelectorAll(".here")) h.closest(".pcard").appendChild(h);
  }
}

function actKey(k) {
  if (!myTurn() || actionsLeft() <= 0) return;
  const b = $(`#dock .act[data-act="${k}"]`);
  if (!b || b.disabled) return;
  if (["drive", "direct", "charter", "shuttle"].includes(k)) setMode(k);
  else if (k === "treat") doTreat();
  else if (k === "build") doBuild();
  else if (k === "share") shareModal();
  else if (k === "cure") cureModal();
}

function passClick() {
  const ui = S.ui;
  if (!ui.passArm) {
    ui.passArm = true;
    renderDock();
    setTimeout(() => {
      if (ui.passArm) {
        ui.passArm = false;
        renderDock();
      }
    }, 4000);
    return;
  }
  ui.passArm = false;
  ui.mode = null;
  act({ type: "pass" });
}

function undo() {
  if (!g()?.can_undo) return;
  S.ui.mode = null;
  hidePop();
  send({ type: "undo" });
}

function doTreat(color) {
  const opts = treatOptions();
  if (!opts.length) return;
  if (!color && opts.length > 1) {
    showPop(me().at, true);
    return;
  }
  hidePop();
  act({ type: "treat", color: color || opts[0].col });
}

function doBuild() {
  hidePop();
  if (stations().length >= CFG.stations) {
    stationPick("Move a research station", `All ${CFG.stations} stations are built. Pick the one that moves to ${cityName(me().at)}.`, (remove) =>
      act({ type: "build", remove }),
    );
    return;
  }
  act({ type: "build" });
}

/* ================================================================ city popover */
export function hidePop() {
  $("#pop")?.classList.add("hidden");
}

function onCityClick(id, viaKey) {
  const ui = S.ui;
  if (ui.mode && modeTargets().includes(id)) {
    doModeTarget(ui.mode, id);
    return;
  }
  showPop(id, viaKey);
}

function doModeTarget(mode, id) {
  const ui = S.ui;
  const p = movingPawn();
  const pawn = p === mySeat() ? {} : { pawn: p };
  ui.mode = null;
  hidePop();
  if (mode === "airlift") {
    const who = ui.airlift ?? mySeat();
    ui.flow = false;
    ui.airlift = null;
    act({ type: "airlift", pawn: who, to: id });
  } else if (mode === "grant") {
    if (stations().length >= CFG.stations) {
      stationPick("Government Grant", `All ${CFG.stations} stations are built. Pick the one that moves to ${cityName(id)}.`, (remove) => {
        ui.flow = false;
        act({ type: "grant", city: id, remove });
      });
      return;
    }
    ui.flow = false;
    act({ type: "grant", city: id });
  } else if (mode === "dispatch") {
    act({ type: "dispatch", pawn: p, to: id });
  } else {
    act({ type: mode, to: id, ...pawn });
  }
  renderGame();
}

function refreshPop() {
  const pop = $("#pop");
  if (pop && !pop.classList.contains("hidden") && pop.dataset.id) showPop(pop.dataset.id, false, true);
}

function showPop(id, viaKey, keepPlace = false) {
  const c = CITIES[id];
  const pop = $("#pop");
  const m = cubesAt(id);
  const game = g();
  const st = stations();
  pop.dataset.id = id;
  const cubeHtml =
    Object.entries(m)
      .filter(([, v]) => v)
      .map(([col, v]) => `<span>${glyph(col, 12)} ${v} ${col}</span>`)
      .join("") || '<span style="color:var(--muted)">No disease here</span>';
  const here = players().filter((p) => p.at === id);
  let html = `<div class="pop-head">${glyph(c.color, 16)}<div><b>${c.name}</b><small>${DNAME[c.color]} city · ${c.country}</small></div>
      <button class="icon-btn" id="pop-close" aria-label="Close">${icon("close")}</button></div>
    <div class="pop-sec"><div class="facts">${cubeHtml}
      ${st.includes(id) ? `<span><svg width="14" height="14" viewBox="-8 -8 16 16" aria-hidden="true"><use href="#station"/></svg> Research station</span>` : ""}
      ${here.map((p) => `<span>${pawnSvg(roleOf(p).color, 16)} ${esc(p.name)}</span>`).join("")}</div>
      ${Object.values(m).some((v) => v >= 3) ? `<div class="note-line alert">${icon("warn")}One more cube here causes an outbreak.</div>` : ""}
    </div>`;
  const self = me();
  const mine = myTurn();
  const left = actionsLeft();
  const opts = [];
  if (!self) {
    html += "";
  } else if (!mine) {
    const note = game.result
      ? "The game is over."
      : game.current === self.i
        ? "No actions in this phase."
        : `It's ${esc(seatName(game.current))}'s turn.${myEvents().length ? " You can still play an event card." : ""}`;
    html += `<div class="pop-sec"><div class="note-line">${icon("info")}${note}</div></div>`;
  } else {
    const p = movingPawn();
    const pawnAt = players()[p].at;
    if (id === self.at && p === self.i) {
      const role = roleOf(self);
      const treats = treatOptions()
        .map((t) => {
          const why =
            self.role === "medic"
              ? `<span class="bonus" style="--rc:${role.color}">Medic bonus:</span> removes all ${t.n}`
              : cures()[t.col] !== "none"
                ? "Cured disease: all cubes go"
                : "Removes 1 cube";
          opts.push({ color: t.col });
          return `<button class="move-opt" data-treat="${t.col}">${icon("treat")}<span class="mt"><b>Treat ${t.col} · ${t.n} → ${t.left}</b><small>${why}</small></span><span class="cost">1 action</span></button>`;
        })
        .join("");
      const has = (self.hand || []).includes(id);
      const canBuild = !st.includes(id) && (has || self.role === "ops");
      const buildSub = self.role === "ops" ? "Operations Expert: no card needed" : has ? `Discard the ${c.name} card` : `Needs the ${c.name} card`;
      html += `<div class="pop-sec"><div class="t">You are here · ${plural(left, "action")} left</div>${treats}
        ${!st.includes(id) ? `<button class="move-opt" data-build ${canBuild ? "" : "disabled"}>${icon("build")}<span class="mt"><b>Build research station</b><small>${buildSub}</small></span><span class="cost">${canBuild ? "1 action" : ""}</span></button>` : ""}
        ${!treats && st.includes(id) ? '<div class="note-line">Nothing to do here. Pick another city to move.</div>' : ""}</div>`;
    } else if (id === pawnAt) {
      html += `<div class="pop-sec"><div class="note-line">${icon("info")}${esc(players()[p].name)}'s pawn is here. Pick another city to move it.</div></div>`;
    } else {
      const moves = moveOptions(id);
      const whose = p === self.i ? "" : ` ${esc(players()[p].name)}`;
      html += `<div class="pop-sec"><div class="t">Move${whose} here · ${plural(left, "action")} left</div>
        ${moves
          .map(
            (o, k) =>
              `<button class="move-opt" data-move="${k}" ${o.ok ? "" : "disabled"}>${icon(o.icon)}<span class="mt"><b>${o.title}</b><small>${o.ok ? o.sub : o.why}</small></span><span class="cost">${o.ok ? plural(o.cost, "action") : ""}</span></button>`,
          )
          .join("")}</div>`;
      opts.push(...moves);
    }
  }
  setHtml(pop, html);
  pop.classList.remove("hidden");
  $("#pop-close").onclick = hidePop;
  for (const b of $$("#pop [data-treat]")) b.onclick = () => doTreat(b.dataset.treat);
  $("#pop [data-build]") && ($("#pop [data-build]").onclick = doBuild);
  for (const b of $$("#pop [data-move]")) {
    const o = opts[+b.dataset.move];
    b.onclick = () => {
      hidePop();
      S.ui.mode = null;
      if (o.pick) opsFlight(id);
      else act(...o.actions);
    };
  }
  if (keepPlace) return;
  const node = $(`#map .city[data-id="${id}"] .node`);
  if (!node) return;
  const r = node.getBoundingClientRect();
  const wr = $("#board").getBoundingClientRect();
  pop.classList.toggle("sheet-like", wr.width <= 720);
  if (wr.width > 720) {
    let lx = r.right - wr.left + 16;
    const ty = r.top - wr.top - 30;
    if (lx + 310 > wr.width - 50) lx = r.left - wr.left - 316;
    pop.style.left = `${clamp(lx, 8, wr.width - 308)}px`;
    pop.style.top = `${clamp(ty, 8, wr.height - pop.offsetHeight - 8)}px`;
  } else {
    pop.style.left = "";
    pop.style.top = "";
  }
  if (viaKey) (pop.querySelector(".move-opt:not(:disabled)") || pop.querySelector(".icon-btn")).focus();
}

/* ================================================================ side: team, discard, log */
function renderSide() {
  const game = g();
  const pl = players();
  const host = isHost();
  const teamChanged = setHtml(
    $("#team"),
    "<h2>Team</h2>" +
      pl
        .map((p) => {
          const r = roleOf(p);
          const open = p.hand != null;
          const counts = colorCounts(p.hand);
          const n = need(p.role);
          const near = open
            ? DCOLS.filter((c) => cures()[c] === "none" && counts[c] >= n - 1)
                .map(
                  (c) =>
                    `<span class="cure-prog ${counts[c] >= n ? "ready" : ""}" title="${esc(p.name)} holds ${counts[c]} of the ${n} ${c} cards needed for a cure">${glyph(c, 12)}${counts[c]}/${n}</span>`,
                )
                .join(" ")
            : "";
          const stored = p.stored ? ` <span class="chip event">${icon("store", 12)}${cardName(p.stored)}</span>` : "";
          const cards =
            p.i === mySeat()
              ? `<span class="meta">${plural(p.count, "card")}, shown below${stored}</span>`
              : open
                ? `<span class="chips">${p.hand.map((c) => chip(c)).join("")}${stored}</span>`
                : `<span class="meta">${plural(p.count, "card")} (closed hands)${stored}</span>`;
          const seat = S.state.seats[p.i];
          const away = !p.bot && !seat?.connected;
          const tags = `${p.i === mySeat() ? ' <span class="tag you">you</span>' : ""}${p.bot ? ` ${icon("bot")}` : ""}${away ? ' <span class="tag off">away</span>' : ""}${seat?.autoplay ? ' <span class="tag">autopilot</span>' : ""}`;
          const auto =
            host && away && !game.result && !seat?.autoplay
              ? `<span class="autopilot" role="button" tabindex="0" data-auto="${p.i}">${icon("bot", 14)}Let a bot play for ${esc(p.name)}</span>`
              : "";
          return `<div class="pl ${p.i === game.current ? "cur" : ""}" data-i="${p.i}" role="button" tabindex="0" aria-label="${esc(p.name)}, ${r.name}, in ${cityName(p.at)}. Show role details">
          <span class="pl-top">${pawnSvg(r.color, 22)}
            <span class="pl-id"><b>${esc(p.name)}</b>${tags}<small>${r.name}</small></span>
            <span style="text-align:right">${p.i === game.current && !game.result ? '<span class="playing">Playing</span><br>' : ""}<span class="pl-loc">${icon("pin")}${cityName(p.at)}</span></span>
          </span>${cards}${near ? `<span>${near}</span>` : ""}${auto}</div>`;
        })
        .join(""),
  );
  // the pulse keeps its phase when the panel is rebuilt
  if (teamChanged) for (const el of $$("#team .cure-prog.ready .gl")) el.style.animationDelay = `${-(performance.now() % 1800)}ms`;
  for (const b of $$("#team .pl")) {
    const p = pl[+b.dataset.i];
    b.onclick = (e) => {
      if (e.target.closest("[data-auto]")) return;
      openSheet(p.i, b);
    };
    b.onkeydown = (e) => {
      if (e.key === "Enter" || e.key === " ") {
        e.preventDefault();
        openSheet(p.i, b);
      }
    };
    b.onmouseenter = () => highlightCity(p.at, true);
    b.onmouseleave = () => highlightCity(p.at, false);
  }
  for (const b of $$("#team [data-auto]")) b.onclick = () => send({ type: "autoplay", seat: +b.dataset.auto, on: true });

  const inf = game.infection_discard;
  const pd = game.player_discard;
  setHtml(
    $("#discard"),
    `<h2 class="inf-head">${icon("bio")}Infection discard <span class="n">${inf.length}</span> · deck ${game.infection_deck}<button class="info" data-help="infection" aria-label="How the infection discard works">${icon("info")}</button></h2>
    <div class="chips">${inf.length ? [...inf].reverse().map(ichip).join("") : '<span class="meta" style="color:var(--muted)">Empty: everything went back on top of the deck.</span>'}</div>
    <details class="pdisc" ${S.ui.pdiscOpen ? "open" : ""}><summary>Player discard · ${plural(pd.filter((c) => c !== "epidemic").length, "card")}</summary>
      <div class="chips">${[...pd]
        .reverse()
        .filter((c) => c !== "epidemic")
        .map((c) => chip(c))
        .join("")}</div></details>
    ${game.removed.length ? `<div class="meta removed">Out of the game: ${game.removed.map(cardName).join(", ")}</div>` : ""}`,
  );
  const pdisc = $("#discard .pdisc");
  pdisc.ontoggle = () => (S.ui.pdiscOpen = pdisc.open);
  for (const b of $$("#discard .ichip")) {
    const id = b.dataset.id;
    b.onmouseenter = b.onfocus = () => highlightCity(id, true);
    b.onmouseleave = b.onblur = () => highlightCity(id, false);
    b.onclick = () => {
      if (innerWidth < 1280) toggleSide(false);
      ensureVisible(id);
      showPop(id, true);
    };
  }
  HELP.infection = `<p><b>Infection deck · ${plural(game.infection_deck, "card")}.</b> At the end of every turn ${infectionRate()} cards are flipped and each city gets one cube.</p>
    <p><b>Discard pile.</b> Cities infected since the last Epidemic, newest first. They can't be drawn again until the next Epidemic, which shuffles this pile and puts it <b>on top</b> of the deck.</p>`;
  renderLog();
}

function renderLog() {
  const log = $("#log");
  if (!log) return;
  const open = S.ui.logOpen;
  $("#log-sec").classList.toggle("closed", !open);
  $("#log-toggle").setAttribute("aria-expanded", String(open));
  if (!open) {
    setHtml(log, "");
    return;
  }
  const pl = players();
  const entries = S.log.slice(-150);
  const atEnd = log.scrollHeight - log.scrollTop - log.clientHeight < 40;
  const html = entries
    .map((e) => {
      if (e.kind === "chat") return `<div class="e chat">${icon("chat", 16)}<span><b>${esc(e.name)}</b> ${esc(e.text)}</span></div>`;
      if (e.tone === "turn") return `<div class="turn">${esc(e.text)}</div>`;
      const ic = e.tone === "bad" ? icon("warn", 16) : e.tone === "good" ? icon("cure", 16) : e.seat != null && pl[e.seat] ? pawnSvg(roleOf(pl[e.seat]).color, 16) : icon("info", 16);
      const k = e.tone === "bad" ? "ob" : e.tone === "good" ? "cure" : "";
      return `<div class="e ${k}">${ic}<span>${esc(e.text)}</span></div>`;
    })
    .join("");
  if (setHtml(log, html) && atEnd) log.scrollTop = log.scrollHeight; // someone scrolled back to read stays there
}

// Keyed: a line that stays on screen keeps its element, so its entry animation doesn't replay on every update.
function renderFeed() {
  const el = $("#feed");
  if (!el) return;
  const items = S.ui.feed;
  const keep = new Set(items.map((f) => String(f.id)));
  for (const n of [...el.children]) if (!keep.has(n.dataset.id)) n.remove();
  const last = items.length - 1;
  items.forEach((f, i) => {
    let n = el.querySelector(`[data-id="${f.id}"]`);
    if (!n) {
      n = document.createElement("div");
      n.dataset.id = f.id;
      n.className = `f ${f.tone === "bad" ? "ob" : f.tone === "good" ? "cure" : ""}`;
      n.innerHTML = `${f.tone === "bad" ? icon("warn") : f.tone === "good" ? icon("cure") : ""}<span>${esc(f.text)}</span>`;
      el.append(n);
    }
    const canUndo = i === last && f.seat === mySeat() && g()?.can_undo && myTurn();
    const b = n.querySelector("[data-undo]");
    if (canUndo && !b) {
      n.insertAdjacentHTML("beforeend", `<button class="btn small" data-undo>${icon("undo", 14)}Undo</button>`);
      n.lastElementChild.onclick = undo;
    } else if (!canUndo && b) b.remove();
  });
}

export function toggleSide(open) {
  $("#side")?.classList.toggle("open", open);
  $("#scrim")?.classList.toggle("hidden", !open);
  if (open) {
    S.ui.unread = 0;
    renderStatus();
    $("#side-close").focus();
  }
}

export function sideOpen() {
  return $("#side")?.classList.contains("open") || innerWidth >= 1280;
}

/* ================================================================ resolve panel (draw / epidemic / infect) */
function splitTurn(evts) {
  const draw = evts.find((e) => e.kind === "draw");
  const blocks = [];
  let cur = null;
  let infect = null;
  for (const e of evts) {
    if (e.kind === "epidemic") {
      cur = { ep: e, hits: [], intensify: null };
      blocks.push(cur);
    } else if (e.kind === "intensify") {
      if (cur) cur.intensify = e;
      cur = null;
    } else if (e.kind === "infect_step" || e.kind === "quiet_night") {
      infect = { start: e, hits: [] };
      cur = null;
    } else if (["infect", "outbreak", "prevented"].includes(e.kind)) {
      (cur || infect)?.hits.push(e);
    }
  }
  return { draw, blocks, infect };
}

const PROTECT = { quarantine: "the Quarantine Specialist", medic: "the Medic", eradicated: "eradicated: nothing happens" };

// Facts about what was hit, as rows; also the cities to ring and the outbreak lines to draw.
function hitModel(hits) {
  const rows = [];
  const focus = [];
  const lines = [];
  const direct = new Map();
  hits.forEach((e, k) => {
    if (e.kind === "outbreak") {
      for (const t of e.to) lines.push([e.city, t]);
      focus.push(e.city);
      const spread = hits.slice(k + 1).filter((x) => x.via === e.city);
      const arrow = `<span class="boom">Outbreak ${e.count} of 8</span> → ${listText(e.to.map(cityName)) || "no neighbours left"}`;
      const protectedTxt = spread.filter((x) => x.kind === "prevented").map((x) => cityName(x.city));
      const sub = arrow + (protectedTxt.length ? `. Protected: ${listText(protectedTxt)}` : "");
      const row = direct.get(e.city);
      if (row) row.sub = sub;
      else rows.push({ id: e.city, title: `${cityName(e.city)} · chain outbreak`, sub });
      return;
    }
    if (e.via) return;
    focus.push(e.city);
    if (e.kind === "prevented") {
      rows.push({ id: e.city, title: `${cityName(e.city)} · no cubes`, sub: e.by === "eradicated" ? `${DNAME[e.color]} is eradicated: nothing happens` : `Protected by ${PROTECT[e.by]}` });
      return;
    }
    const before = e.cubes - e.placed;
    const row = e.outbreak
      ? { id: e.city, title: `${cityName(e.city)} · had ${before} ${e.color}`, sub: '<span class="boom">Outbreak</span>' }
      : { id: e.city, title: `${cityName(e.city)} · ${e.color} ${before} → ${e.cubes}`, sub: e.epidemic ? `${plural(e.placed, "cube")} added` : "One cube added" };
    direct.set(e.city, row);
    rows.push(row);
  });
  return { rows, focus, lines };
}

const hitRow = (r) => `<button class="hit-row" data-id="${r.id}">${glyph(CITIES[r.id].color, 12)}<span><b>${r.title}</b><small>${r.sub}</small></span></button>`;

function drawSection(draw) {
  if (!draw) return "";
  const self = draw.seat === mySeat();
  const epis = draw.cards.filter((c) => c === "epidemic").length;
  const names = draw.cards.filter((c) => c && c !== "epidemic").map(cardName);
  const txt = self
    ? `${names.length ? `${listText(names)} ${names.length > 1 ? "go" : "goes"} to your hand.` : ""}${epis ? ` ${epis === 2 ? "Both cards are Epidemics!" : names.length ? "The other card is an Epidemic." : "An Epidemic!"}` : ""}`
    : epis
      ? epis === 2
        ? "Both cards are Epidemics!"
        : "One card is an Epidemic."
      : "";
  return `<div class="draw-sec"><div class="t">${who(draw.seat)} drew 2 player cards</div><div class="drawn">${draw.cards.map((c) => cardHtml(c)).join("")}</div>${txt ? `<p class="dtxt">${txt}</p>` : ""}</div>`;
}

function epidemicHtml(b, game) {
  const m = hitModel(b.hits);
  const total = game.epidemics;
  const step3 = b.intensify
    ? `<p>The infection discard pile was shuffled and put <b>on top</b> of the infection deck:</p><div class="chips">${b.intensify.cities.map(ichip).join("")}</div>`
    : "<p>When the game continues, the infection discard pile is shuffled and put <b>on top</b> of the infection deck.</p>";
  return {
    html: `<div class="epi-block"><div class="epi-title"><span class="bio">☣︎</span><b>Epidemic ${b.ep.number} of ${total}</b></div>
      <div class="step"><span class="num">1</span><h3>Increase</h3><p>The infection rate is now <b>${b.ep.rate} cities per turn</b>.</p></div>
      <div class="step"><span class="num">2</span><h3>Infect</h3><p>The bottom card of the infection deck gets 3 cubes.</p>
        <div class="hits">${m.rows.map(hitRow).join("")}</div></div>
      <div class="step"><span class="num">3</span><h3>Intensify</h3>${step3}</div></div>`,
    focus: m.focus,
    lines: m.lines,
  };
}

function eventNote() {
  const pl = players();
  const holders = [];
  for (const p of pl) {
    const evs = [...(p.hand || []).filter(isEv), ...(p.stored ? [p.stored] : [])];
    for (const c of evs) holders.push(`${p.i === mySeat() ? "you hold" : `${esc(p.name)} holds`} <b>${cardName(c)}</b>`);
  }
  return holders.length ? `Anyone can still play an event: ${listText(holders)}.` : "";
}

function renderResolve() {
  const el = $("#resolve");
  if (!el) return;
  const game = g();
  const ui = S.ui;
  let html = "";
  let focus = [];
  let lines = [];
  let epi = false;
  const resolving = !game.result && (game.step === "epidemic" || game.step === "infect");
  if (resolving) {
    const t = splitTurn(game.turn_end);
    const parts = t.blocks.map((b) => epidemicHtml(b, game));
    for (const p of parts) {
      focus.push(...p.focus);
      lines.push(...p.lines);
    }
    epi = game.step === "epidemic";
    const cur = game.current;
    const waiting = game.waiting_for;
    let foot;
    const evBtns = myEvents()
      .filter((e) => eventPlayable(e.card).ok)
      .map((e) => `<button class="btn" data-event="${e.card}">${icon("event")}Play ${cardName(e.card)}</button>`)
      .join("");
    if (game.over_limit != null) {
      foot = `<span class="note">${game.over_limit === mySeat() ? "Discard down to 7 cards first." : `Waiting for ${esc(seatName(game.over_limit))} to discard down to 7 cards.`}</span>`;
    } else if (game.forecast) {
      foot = `<span class="note">${game.forecast.seat === mySeat() ? "Arrange the Forecast cards." : `${esc(seatName(game.forecast.seat))} is arranging the Forecast cards.`}</span>`;
    } else if (waiting === mySeat() && cur === mySeat()) {
      const label = game.step === "epidemic" ? "Continue: Intensify" : game.quiet_night ? "Continue: One Quiet Night, no infection" : `Continue: infect ${infectionRate()} cities`;
      foot = `<span class="note">${eventNote()}</span>${evBtns}<button class="btn primary" id="continue-btn">${label}</button>`;
    } else {
      const bot = S.state.seats[cur]?.bot || S.state.seats[cur]?.autoplay;
      foot = `<span class="note">${eventNote()} ${bot ? `${esc(seatName(cur))} continues in a moment.` : `Waiting for ${esc(seatName(cur))} to continue.`}</span>${evBtns}`;
    }
    const title = epi ? "Epidemic!" : game.quiet_night ? "Cards drawn · One Quiet Night" : "Cards drawn";
    const sub = epi ? `Drawn by ${whoLower(cur)}. The ringed cities on the map were hit.` : `Next: infect ${infectionRate()} cities${game.quiet_night ? " (skipped tonight)" : ""}.`;
    html = `<div class="res-head">${epi ? '<span class="bio">☣︎</span>' : icon("cards", 24)}<div><h2>${title}</h2><div class="sub">${sub}</div></div></div>
      <div class="res-body">${drawSection(t.draw)}${parts.map((p) => p.html).join("")}</div>
      <div class="res-foot">${foot}</div>`;
  } else if (ui.infectPanel && !game.result) {
    const t = splitTurn(ui.infectPanel.events);
    const seat = ui.infectPanel.seat;
    if (t.infect?.start.kind === "quiet_night") {
      html = `<div class="res-head">${icon("event", 24)}<div><h2>One Quiet Night</h2><div class="sub">No cities were infected after ${seat === mySeat() ? "your" : `${esc(seatName(seat))}'s`} turn.</div></div></div>
        <div class="res-foot"><button class="btn primary" id="ok-btn">OK</button></div>`;
    } else if (t.infect) {
      const m = hitModel(t.infect.hits);
      focus = m.focus;
      lines = m.lines;
      const n = t.infect.start.rate;
      html = `<div class="res-head"><span class="bio">☣︎</span><div><h2>Infected cities · ${plural(n, "card")}</h2><div class="sub">At the end of ${seat === mySeat() ? "your" : `${esc(seatName(seat))}'s`} turn.</div></div></div>
        <div class="res-body" style="gap:6px">${m.rows.map(hitRow).join("") || '<p class="meta">No cards were left to draw.</p>'}</div>
        <div class="res-foot"><button class="btn primary" id="ok-btn">OK</button></div>`;
    }
  }
  const fx = ui.fx;
  fx.focus = focus;
  fx.lines = lines;
  if (!html) {
    el.classList.add("hidden");
    setHtml(el, "");
    placeFeed();
    return;
  }
  setHtml(el, html);
  el.classList.remove("hidden");
  el.classList.toggle("epi", epi);
  placeResolve();
  const on = (sel, fn) => {
    const b = el.querySelector(sel);
    if (b) b.onclick = fn;
  };
  on("#continue-btn", () => act({ type: "continue" }));
  on("#ok-btn", () => {
    ui.infectPanel = null;
    renderResolve();
    renderMap();
  });
  for (const b of el.querySelectorAll("[data-event]")) b.onclick = () => playEvent(b.dataset.event);
  for (const b of el.querySelectorAll("[data-id]")) {
    const id = b.dataset.id;
    b.onmouseenter = b.onfocus = () => highlightCity(id, true);
    b.onmouseleave = b.onblur = () => highlightCity(id, false);
    b.onclick = () => {
      ensureVisible(id);
      showPop(id, true);
    };
  }
}

function placeResolve() {
  const el = $("#resolve");
  if (el && !el.classList.contains("hidden")) {
    const focus = S.ui.fx.focus || [];
    const vb = viewBox();
    const avg = focus.length ? focus.reduce((a, id) => a + CITIES[id].x, 0) / focus.length : 0;
    el.classList.toggle("left", avg > vb.x + vb.w / 2);
    el.classList.toggle("right", !(avg > vb.x + vb.w / 2));
  }
  placeFeed();
}

// The feed sits centred over the map, or beside the resolve panel when that panel reaches up to it.
function placeFeed() {
  const feedEl = $("#feed");
  const res = $("#resolve");
  if (!feedEl || !res) return;
  const board = $("#board").getBoundingClientRect();
  let lo = 12;
  let hi = board.width - 12;
  if (!res.classList.contains("hidden") && !res.classList.contains("picking")) {
    const r = res.getBoundingClientRect();
    const left = r.left - board.left - 10;
    const right = r.right - board.left + 10;
    const room = Math.max(left - lo, hi - right);
    if (r.width && r.top - board.top < 60 && room >= 240) {
      if (left - lo > hi - right) hi = left;
      else lo = right;
    }
  }
  feedEl.style.left = `${(lo + hi) / 2}px`;
  feedEl.style.width = `${Math.min(460, hi - lo)}px`;
}

/* ================================================================ events */
// bots wait while you pick what an event card does, so the board doesn't change under the dialog
function holdBots(on) {
  if (S.ui.holding === on) return;
  S.ui.holding = on;
  send({ type: "hold", on });
}
function syncHold() {
  if (S.ui.holding && !S.ui.mode && !$("#modal-root")?.innerHTML) holdBots(false);
}

function playEvent(card) {
  const can = eventPlayable(card);
  if (!can.ok) {
    toast(can.why, true);
    return;
  }
  holdBots(true);
  const ui = S.ui;
  hidePop();
  const pl = players();
  if (card === "airlift") {
    const start = (i) => {
      ui.flow = true;
      ui.airlift = i;
      ui.mode = "airlift";
      closeModal();
      renderGame();
    };
    if (pl.length === 1) return start(mySeat());
    modal(
      `<div class="modal-head"><h2>Airlift</h2><div class="sub">${EVENTS.airlift.text} Pick the pawn, then the city.</div></div>
      <div class="modal-body"><div class="pawn-list">${pl
        .map((p) => `<button class="move-opt" data-p="${p.i}">${pawnSvg(roleOf(p).color, 22)}<span class="mt"><b>${p.i === mySeat() ? "Your pawn" : esc(p.name)}</b><small>${roleOf(p).name} · in ${cityName(p.at)}</small></span></button>`)
        .join("")}</div></div>
      <div class="modal-foot"><button class="btn" data-close>Cancel</button></div>`,
      "narrow",
      true,
    );
    for (const b of $$("#modal-root [data-p]")) b.onclick = () => start(+b.dataset.p);
    return;
  }
  if (card === "grant") {
    ui.flow = true;
    ui.mode = "grant";
    renderGame();
    return;
  }
  if (card === "quiet" || card === "forecast") {
    const ev = EVENTS[card];
    const extra = card === "forecast" ? "You will put them back in any order you like." : "The next Infect Cities step is skipped.";
    confirmModal(ev.name, `${ev.text} ${extra}`, `Play ${ev.name}`, () => act({ type: card }));
    return;
  }
  if (card === "resilient") {
    const inf = [...g().infection_discard].reverse();
    modal(
      `<div class="modal-head"><h2>Resilient Population</h2><div class="sub">${EVENTS.resilient.text} The card leaves the game for good.</div></div>
      <div class="modal-body"><div class="chips big">${inf.map((id) => `<button class="ichip" data-id="${id}">${glyph(CITIES[id].color, 10)}${CITIES[id].name}</button>`).join("")}</div></div>
      <div class="modal-foot"><button class="btn" data-close>Cancel</button></div>`,
      "narrow",
      true,
    );
    for (const b of $$("#modal-root [data-id]")) {
      b.onclick = () => {
        closeModal();
        act({ type: "resilient", city: b.dataset.id });
      };
    }
  }
}

/* ================================================================ dialogs */
export function closeModal() {
  const root = $("#modal-root");
  if (root) root.innerHTML = "";
  queueMicrotask(syncHold);
}

function modal(html, cls = "", dismiss = false) {
  const root = $("#modal-root");
  root.innerHTML = `<div class="modal-bg"><div class="modal ${cls}" role="dialog" aria-modal="true">${html}</div></div>`;
  const bg = root.querySelector(".modal-bg");
  if (dismiss) {
    bg.onclick = (e) => {
      if (e.target === bg) closeModal();
    };
  }
  for (const b of root.querySelectorAll("[data-close]")) b.onclick = closeModal;
  (bg.querySelector(".btn.primary:not(:disabled)") || bg.querySelector("button"))?.focus();
  return root;
}

function confirmModal(title, text, label, fn) {
  modal(
    `<div class="modal-head"><h2>${title}</h2></div><div class="modal-body"><p>${text}</p></div>
    <div class="modal-foot"><button class="btn" data-close>Cancel</button><button class="btn primary" id="ok">${label}</button></div>`,
    "narrow",
    true,
  );
  $("#ok").onclick = () => {
    closeModal();
    fn();
  };
}

function stationPick(title, text, fn) {
  const st = stations();
  modal(
    `<div class="modal-head"><h2>${title}</h2><div class="sub">${text}</div></div>
    <div class="modal-body"><div class="pawn-list">${st
      .map((id) => `<button class="move-opt" data-st="${id}">${glyph(CITIES[id].color, 14)}<span class="mt"><b>${cityName(id)}</b><small>${cubeCount(id) ? plural(cubeCount(id), "cube") : "No cubes"}</small></span></button>`)
      .join("")}</div></div>
    <div class="modal-foot"><button class="btn" data-close>Cancel</button></div>`,
    "narrow",
    true,
  );
  for (const b of $$("#modal-root [data-st]")) {
    b.onclick = () => {
      closeModal();
      fn(b.dataset.st);
    };
  }
}

// Pick exactly `count` cards. `onDone(cards)` runs on confirm.
function pickCards({ title, sub, text, cards, count, confirm, onDone, extra = "", dismiss = true, fixed = false }) {
  const sel = new Set(fixed ? cards : []);
  const draw = () => {
    const n = sel.size;
    modal(
      `<div class="modal-head"><h2>${title}</h2>${sub ? `<div class="sub">${sub}</div>` : ""}</div>
      <div class="modal-body">${text ? `<p>${text}</p>` : ""}
        <div class="pick">${cards.map((c) => cardHtml(c, { pick: !fixed, sel: sel.has(c) })).join("")}</div>${extra}</div>
      <div class="modal-foot">${dismiss ? '<button class="btn" data-close>Cancel</button>' : ""}
        ${fixed ? "" : `<span class="counter ${n === count ? "ok" : ""}">${n} of ${count} selected</span>`}
        <button class="btn primary" id="pick-ok" ${n === count ? "" : "disabled"}>${confirm(n)}</button></div>`,
      "narrow",
      dismiss,
    );
    if (!fixed) {
      for (const cd of $$(".modal .pcard[data-card]")) {
        cd.onclick = () => {
          const c = cd.dataset.card;
          if (sel.has(c)) sel.delete(c);
          else if (count === 1) {
            sel.clear();
            sel.add(c);
          } else if (sel.size < count) sel.add(c);
          draw();
          $(`.modal .pcard[data-card="${c}"]`)?.focus();
        };
      }
    }
    $("#pick-ok").onclick = () => {
      closeModal();
      onDone([...sel]);
    };
    for (const b of $$("#modal-root [data-event]")) {
      b.onclick = () => {
        closeModal();
        S.ui.forced = "paused";
        playEvent(b.dataset.event);
      };
    }
  };
  draw();
}

function opsFlight(to) {
  const cards = (me().hand || []).filter((c) => !isEv(c));
  pickCards({
    title: `Station flight to ${cityName(to)}`,
    sub: "Operations Expert, once per turn: from a research station to any city.",
    text: "Pick the city card to discard.",
    cards,
    count: 1,
    confirm: () => "Fly · 1 action",
    onDone: ([card]) => act({ type: "ops_flight", to, card }),
  });
}

function storeModal() {
  const evs = [...new Set(g().player_discard.filter(isEv))];
  modal(
    `<div class="modal-head"><h2>Take an event card</h2><div class="sub">Contingency Planner: store one event from the player discard pile. When you play it, it leaves the game.</div></div>
    <div class="modal-body"><div class="pick">${evs.map((c) => cardHtml(c)).join("")}</div></div>
    <div class="modal-foot"><button class="btn" data-close>Cancel</button></div>`,
    "narrow",
    true,
  );
  for (const cd of $$(".modal .pcard[data-card]")) {
    cd.onclick = () => {
      closeModal();
      act({ type: "take_event", card: cd.dataset.card });
    };
  }
}

function shareModal() {
  const opts = shareOptions();
  const here = cityName(me().at);
  modal(
    `<div class="modal-head"><h2>Share knowledge in ${here}</h2><div class="sub">Give or take the card of the city you are in. The Researcher can give any city card.</div></div>
    <div class="modal-body"><div class="pawn-list">${opts
      .map((o, k) => {
        if (o.kind === "take-any")
          return `<button class="move-opt" data-k="${k}">${icon("share", 16)}<span class="mt"><b>Take another city card from ${esc(o.mate.name)}</b><small>The Researcher can give any city card. Ask which ones they hold.</small></span><span class="cost">1 action</span></button>`;
        const title = o.kind === "give" ? `Give ${cardName(o.card)} to ${esc(o.mate.name)}` : `Take ${cardName(o.card)} from ${esc(o.mate.name)}`;
        const sub = o.unsure ? `If ${esc(o.mate.name)} holds it (closed hands)` : o.kind === "give" ? `${esc(o.mate.name)} will hold ${plural(o.mate.count + 1, "card")}` : "";
        return `<button class="move-opt" data-k="${k}">${glyph(CITIES[o.card].color, 14)}<span class="mt"><b>${title}</b><small>${sub}</small></span><span class="cost">1 action</span></button>`;
      })
      .join("")}</div></div>
    <div class="modal-foot"><button class="btn" data-close>Cancel</button></div>`,
    "narrow",
    true,
  );
  for (const b of $$("#modal-root [data-k]")) {
    b.onclick = () => {
      const o = opts[+b.dataset.k];
      if (o.kind === "take-any") return takeAnyModal(o.mate);
      closeModal();
      act(o.action);
    };
  }
}

function takeAnyModal(mate) {
  const gone = new Set([...(me().hand || []), ...g().player_discard, me().at]);
  const groups = DCOLS.map((col) => {
    const ids = Object.keys(CITIES)
      .filter((id) => CITIES[id].color === col && !gone.has(id))
      .sort((a, b) => CITIES[a].name.localeCompare(CITIES[b].name));
    return `<div class="chips big">${ids.map((id) => `<button class="ichip" data-id="${id}">${glyph(col, 10)}${CITIES[id].name}</button>`).join("")}</div>`;
  }).join("");
  modal(
    `<div class="modal-head"><h2>Take a card from ${esc(mate.name)}</h2><div class="sub">Hands are closed: pick the card ${esc(mate.name)} told you about. If they don't hold it, no action is used.</div></div>
    <div class="modal-body take-any">${groups}</div>
    <div class="modal-foot"><button class="btn" data-close>Cancel</button></div>`,
    "narrow",
    true,
  );
  for (const b of $$("#modal-root [data-id]")) {
    b.onclick = () => {
      closeModal();
      act({ type: "take", card: b.dataset.id, giver: mate.i });
    };
  }
}

function cureModal(col) {
  const opts = cureOptions();
  if (!opts.length) return;
  const o = opts.find((x) => x.col === col) || opts[0];
  const self = me();
  const switcher =
    opts.length > 1
      ? `<div class="row" style="margin-top:12px">${opts.map((x) => `<button class="btn small" data-col="${x.col}">${glyph(x.col, 11)}${DNAME[x.col]} instead</button>`).join("")}</div>`
      : "";
  const exact = o.cards.length === o.need;
  pickCards({
    title: `Discover a cure for ${o.col}`,
    sub: `${roleOf(self).name} at the ${cityName(self.at)} research station`,
    text: exact
      ? `These <b>${o.need} cards</b> will be discarded${self.role === "scientist" ? " (the Scientist needs 4 instead of 5)" : ""}.`
      : `Pick the <b>${o.need} ${o.col} cards</b> to discard. The others stay in your hand.`,
    cards: o.cards,
    count: o.need,
    fixed: exact,
    confirm: () => "Discover cure · 1 action",
    onDone: (cards) => act({ type: "cure", cards }),
    extra: `<p style="margin-top:14px">After the cure, treating ${o.col} removes <b>all</b> ${o.col} cubes in a city. Once no ${o.col} cubes are left on the board, ${o.col} is <b>eradicated</b> and its infection cards do nothing.</p>${switcher}`,
  });
  for (const b of $$("#modal-root [data-col]")) b.onclick = () => cureModal(b.dataset.col);
}

// The hand limit and Forecast dialogs open by themselves and stay until the game moves on.
function syncForced(force = false) {
  const game = g();
  const ui = S.ui;
  const seat = mySeat();
  let want = null;
  if (game && seat != null && !game.result && !S.state.seats[seat]?.autoplay) {
    if (game.forecast?.seat === seat && game.forecast.cards.length) want = `forecast:${game.forecast.cards.join()}`;
    else if (game.over_limit === seat) want = `discard:${game.players[seat].hand.join()}`;
  }
  if (ui.sent) {
    const hand = seat != null && game ? game.players[seat].hand || [] : [];
    const pending = want && (want.startsWith("forecast") ? want === ui.sent.key : ui.sent.cards.some((c) => hand.includes(c)));
    if (pending) return;
    ui.sent = null;
  }
  if (!want) {
    if (ui.forced && ui.forced !== "paused") closeModal();
    ui.forced = null;
    return;
  }
  if (ui.flow && !force) return;
  if (ui.forced === "paused" && !force && $("#modal-root").innerHTML) return;
  if (ui.forced === want && !force) return;
  ui.forced = want;
  if (want.startsWith("forecast")) forecastModal(game.forecast.cards);
  else discardModal();
}

function discardModal() {
  const self = me();
  const hand = self.hand;
  const count = hand.length - CFG.hand;
  const evs = myEvents().filter((e) => eventPlayable(e.card).ok);
  pickCards({
    title: `Hand limit: discard ${count}`,
    sub: `You hold ${plural(hand.length, "card")}; the limit is ${CFG.hand}.`,
    text: `Click <b>${count}</b> ${count === 1 ? "card" : "cards"} to discard. You can also play an event card instead of discarding it.`,
    cards: hand,
    count,
    dismiss: false,
    confirm: () => `Discard ${plural(count, "card")}`,
    onDone: (cards) => {
      S.ui.forced = null;
      S.ui.sent = { cards };
      act(...cards.map((card) => ({ type: "discard", card })));
    },
    extra: evs.length ? `<div class="row" style="margin-top:12px">${evs.map((e) => `<button class="btn" data-event="${e.card}">${icon("event")}Play ${cardName(e.card)} instead</button>`).join("")}</div>` : "",
  });
}

function forecastModal(cards) {
  let order = [...cards];
  const draw = () => {
    modal(
      `<div class="modal-head"><h2>Forecast</h2><div class="sub">The top ${order.length} infection cards. Put them back in any order: the first card is drawn first.</div></div>
      <div class="modal-body"><ol class="fc-list">${order
        .map((id, i) => {
          const m = cubesAt(id);
          const cubes = DCOLS.filter((c) => m[c]).map((c) => `${glyph(c, 10)} ${m[c]}`).join(" ") || '<span class="meta">no cubes</span>';
          return `<li><span class="fc-n">${i + 1}</span>${ichip(id)}<span class="fc-cubes">${cubes}</span>
            <button class="icon-btn" data-up="${i}" ${i === 0 ? "disabled" : ""} aria-label="Move ${cityName(id)} up">${icon("up")}</button>
            <button class="icon-btn" data-down="${i}" ${i === order.length - 1 ? "disabled" : ""} aria-label="Move ${cityName(id)} down">${icon("down")}</button></li>`;
        })
        .join("")}</ol><p class="meta">Top of the deck first. Cards further down come up in later turns.</p></div>
      <div class="modal-foot"><button class="btn primary" id="fc-ok">Put the cards back</button></div>`,
      "narrow",
    );
    const swap = (i, j) => {
      [order[i], order[j]] = [order[j], order[i]];
      draw();
      $(`#modal-root [data-${j < i ? "up" : "down"}="${j}"]`)?.focus();
    };
    for (const b of $$("#modal-root [data-up]")) b.onclick = () => swap(+b.dataset.up, +b.dataset.up - 1);
    for (const b of $$("#modal-root [data-down]")) b.onclick = () => swap(+b.dataset.down, +b.dataset.down + 1);
    for (const b of $$("#modal-root .ichip")) {
      const id = b.dataset.id;
      b.onmouseenter = () => highlightCity(id, true);
      b.onmouseleave = () => highlightCity(id, false);
    }
    $("#fc-ok").onclick = () => {
      closeModal();
      S.ui.forced = null;
      S.ui.sent = { key: `forecast:${cards.join()}`, cards: [] };
      act({ type: "forecast_order", order });
    };
  };
  draw();
}

/* ================================================================ sheet, bubble, menu, help */
export function openSheet(i, anchor) {
  const sh = $("#sheet");
  if (!sh.classList.contains("hidden") && sh.dataset.i === String(i)) {
    closeSheet();
    return;
  }
  const p = players()[i];
  const r = roleOf(p);
  const visible = p.hand != null;
  const counts = colorCounts(p.hand);
  const n = need(p.role);
  sh.dataset.i = i;
  sh._anchor = anchor;
  const prog = DCOLS.filter((c) => cures()[c] === "none" && counts[c])
    .map((c) => `<span class="prog ${counts[c] >= n ? "ready" : ""}">${glyph(c, 11)}${DNAME[c]} ${counts[c]}/${n}</span>`)
    .join(" ");
  const stored = p.stored ? `<div class="chips" style="margin-top:8px"><span class="chip event">${icon("store", 12)}Stored: ${cardName(p.stored)}</span></div>` : "";
  sh.innerHTML = `
    <div class="sheet-head">${pawnSvg(r.color, 40)}<div class="t"><b style="color:${r.color}">${r.name}</b><small>${esc(p.name)}${i === mySeat() ? " (you)" : ""}${p.bot ? " · bot" : ""} · in ${cityName(p.at)}</small></div>
      <button class="icon-btn" id="sheet-close" aria-label="Close">${icon("close")}</button></div>
    <div class="sheet-sec"><div class="t">Role ability</div><ul>${r.abilities.map((a) => `<li>${a}</li>`).join("")}</ul><div class="example"><b>Example.</b> ${r.example}</div></div>
    <div class="sheet-sec"><div class="t">Hand · ${p.count} of ${CFG.hand}</div>
      ${visible ? `<div class="chips">${p.hand.map((c) => chip(c)).join("")}</div>${prog ? `<div class="chips" style="margin-top:8px">${prog}</div>` : ""}` : `<span style="color:var(--muted)">Hidden (closed hands). Ask ${esc(p.name)} in the chat.</span>`}${stored}</div>
    <div class="sheet-foot"><button class="btn small" id="sheet-locate">${icon("pin", 16)}Show on map</button></div>`;
  sh.classList.remove("hidden");
  $("#sheet-close").onclick = closeSheet;
  $("#sheet-locate").onclick = () => locate(p.at);
  const a = anchor.getBoundingClientRect();
  const sw = sh.offsetWidth;
  const shh = sh.offsetHeight;
  const inSide = anchor.closest(".side");
  const left = inSide ? $("#side").getBoundingClientRect().left - sw - 10 : a.left;
  const top = inSide ? a.top : a.top - shh - 10;
  sh.style.left = `${clamp(left, 8, innerWidth - sw - 8)}px`;
  sh.style.top = `${clamp(top, 8, innerHeight - shh - 8)}px`;
  $("#sheet-close").focus();
}

export function closeSheet() {
  const sh = $("#sheet");
  if (sh.classList.contains("hidden")) return;
  sh.classList.add("hidden");
  sh._anchor?.focus?.();
}

function locate(id) {
  closeSheet();
  if (innerWidth < 1280) toggleSide(false);
  ensureVisible(id);
  highlightCity(id, true);
  setTimeout(() => highlightCity(id, false), 1800);
}

export function showBubble(btn) {
  const hb = $("#bubble");
  if (!hb.classList.contains("hidden") && hb.dataset.k === btn.dataset.help) {
    hb.classList.add("hidden");
    return;
  }
  hb.dataset.k = btn.dataset.help;
  hb.innerHTML = `<button class="icon-btn" id="bubble-close" aria-label="Close">${icon("close")}</button>${HELP[btn.dataset.help] || ""}`;
  hb.classList.remove("hidden");
  $("#bubble-close").onclick = () => hb.classList.add("hidden");
  const r = btn.getBoundingClientRect();
  hb.style.left = `${clamp(r.left - 20, 8, innerWidth - hb.offsetWidth - 8)}px`;
  hb.style.top = `${r.bottom + 8 + hb.offsetHeight < innerHeight ? r.bottom + 8 : Math.max(8, r.top - hb.offsetHeight - 8)}px`;
}

function openMenu(btn) {
  const m = $("#menu");
  if (!m.classList.contains("hidden")) {
    m.classList.add("hidden");
    return;
  }
  const host = isHost();
  m.innerHTML = `
    <button role="menuitem" data-m="stats">${icon("stats")}Statistics</button>
    <button role="menuitem" data-m="sound">${icon("sound")}Sound: ${isMuted() ? "off" : "on"}</button>
    <button role="menuitem" data-m="help">${icon("help")}Rules and shortcuts</button>
    <button role="menuitem" data-m="invite">${icon("copy")}Copy invite link</button>
    ${mySeat() != null ? `<button role="menuitem" data-m="device">${icon("person")}Continue on another device</button>` : ""}
    ${host ? `<button role="menuitem" data-m="lobby">${icon("exit")}Back to the lobby</button>` : ""}
    <button role="menuitem" data-m="leave">${icon("exit")}Leave the table</button>`;
  m.classList.remove("hidden");
  const r = btn.getBoundingClientRect();
  m.style.left = `${clamp(r.right - m.offsetWidth, 8, innerWidth - m.offsetWidth - 8)}px`;
  m.style.top = `${r.bottom + 6}px`;
  m.querySelector("button").focus();
  m.onclick = (e) => {
    const b = e.target.closest("[data-m]");
    if (!b) return;
    m.classList.add("hidden");
    const k = b.dataset.m;
    if (k === "stats") (over() ? overModal : statsModal)();
    if (k === "sound") setMuted(!isMuted());
    if (k === "help") openHelp();
    if (k === "invite") copyText(inviteUrl()).then((ok) => toast(ok ? "Invite link copied" : inviteUrl()));
    if (k === "device") {
      const url = `${inviteUrl()}?me=${S.token}`;
      copyText(url).then((ok) => toast(ok ? "Personal link copied. Open it on your other device, and don't share it: it is your seat." : url));
    }
    if (k === "lobby") {
      if (over()) send({ type: "to_lobby" });
      else confirmModal("Back to the lobby", "This ends the game for everyone at the table.", "End the game", () => send({ type: "to_lobby" }));
    }
    if (k === "leave") S.ui.hooks?.leave();
  };
}

export const RULES_HTML = `
  <h3>Goal</h3><p>Four diseases spread around the world. The team wins together by discovering all four cures. Everyone loses together after the 8th outbreak, when a disease runs out of cubes, or when the player deck runs out.</p>
  <h3>Your turn</h3><p><b>1. Four actions.</b> Drive to a connected city, fly with your city cards, build research stations, treat disease, share knowledge, or discover a cure with 5 cards of one colour at a research station.</p>
  <p><b>2. Draw 2 player cards.</b> Epidemic cards make a city at the bottom of the infection deck very sick and put the infected cities back on top. Hand limit: 7 cards.</p>
  <p><b>3. Infect cities.</b> Flip infection cards; each city gets one cube. A 4th cube causes an outbreak: every connected city gets a cube instead, and outbreaks can chain.</p>
  <h3>Roles and events</h3><p>Every player has a role with a special ability: click a player to read it. Event cards can be played at any time, even on someone else's turn, without using an action.</p>`;

export function openHelp() {
  $("#menu")?.classList.add("hidden");
  const keys = [
    ["D F C S", "Drive, direct flight, charter flight, shuttle flight"],
    ["B T K U", "Build station, treat, share knowledge, discover cure"],
    ["Z", "Undo the last action"],
    ["P", "End actions early (press twice)"],
    ["N", "Draw 2 cards when no actions are left"],
    ["Space", "Continue after an epidemic or the infection"],
    ["Tab", "Move between cities, cards and players"],
    ["Arrow keys", "Jump to the nearest city in that direction"],
    ["Enter", "Open the focused city"],
    ["+ − 0", "Zoom in, zoom out, whole map"],
    ["Esc", "Cancel or close"],
  ];
  modal(
    `<div class="modal-head"><h2>Help</h2><div class="sub">Rules, shortcuts, map symbols and colours</div></div>
    <div class="modal-body"><div class="help-cols">
      <div class="rules">${RULES_HTML}</div>
      <div><h3>Keyboard</h3><div class="kbd-table">${keys.map(([k, t]) => `<kbd>${k}</kbd><span>${t}</span>`).join("")}</div>
        <h3>Diseases</h3><p style="margin:0 0 8px">Each disease has its own shape as well as a colour.</p>
        ${DCOLS.map((c) => `<div class="row">${glyph(c, 14)}<span><b style="color:var(--text)">${DNAME[c]}</b> · ${SHAPES[c]}</span></div>`).join("")}
        <div class="row"><span class="chip event">${icon("event", 12)}Event</span><span>Play any time, even on another player's turn.</span></div></div>
      <div><h3>Map</h3><div class="legend" style="position:static;border:0;padding:0;background:none">${legendHtml()}</div></div>
    </div></div>
    <div class="modal-foot"><button class="btn primary" data-close>Close</button></div>`,
    "",
    true,
  );
}

function statsBlock() {
  const game = g();
  const stats = game.stats;
  const pl = players();
  const sum = (k) => (stats[k] || []).reduce((a, b) => a + b, 0);
  const best = (k, verb, unit) => {
    const arr = stats[k] || [];
    const top = Math.max(0, ...arr);
    if (!top) return null;
    const i = arr.indexOf(top);
    return `${esc(pl[i].name)} ${verb} ${plural(top, unit)}`;
  };
  const lines = [best("cured", "discovered", "cure"), best("treated", "removed", "cube"), best("built", "built", "station"), best("shared", "shared", "card"), best("events", "played", "event")].filter(Boolean);
  const diff = DIFFS.find((d) => d.n === game.epidemics);
  return `<div class="stats">
      <div class="stat"><b>${game.turn}</b><small>turns</small></div>
      <div class="stat"><b>${game.outbreaks}</b><small>outbreaks</small></div>
      <div class="stat"><b>${sum("treated")}</b><small>cubes treated</small></div>
      <div class="stat"><b>${game.epidemics}</b><small>epidemics (${diff?.name || ""})</small></div>
    </div>
    <div class="stat-lines">${lines.join(" · ")}</div>`;
}

function statsModal() {
  modal(
    `<div class="modal-head"><h2>Statistics</h2><div class="sub">This game so far</div></div>${statsBlock()}
    <div class="modal-foot"><button class="btn primary" data-close>Close</button></div>`,
    "narrow",
    true,
  );
}

export function overModal() {
  const game = g();
  if (!game?.result) return;
  const res = game.result;
  const win = res.won;
  const reasons = Object.entries(LOSS);
  const text = win
    ? `The team cured every disease on turn ${res.turn}, with ${plural(game.player_deck, "player card")} to spare.`
    : res.reason === "cubes"
      ? `${DNAME[res.color] || "A disease"} ran out of cubes on turn ${res.turn}.`
      : res.reason === "outbreaks"
        ? `The 8th outbreak hit on turn ${res.turn}.`
        : `The player deck ran out on turn ${res.turn}.`;
  const host = isHost();
  modal(
    `<div class="over-hero ${win ? "win" : "lose"}"><div class="vials">${DCOLS.map((c) => vialSvg(c, cures()[c], 56)).join("")}</div>
      <h2>${win ? "Victory: all four cures found" : "Defeat"}</h2><p>${text}</p></div>
    ${win ? "" : `<ul class="why">${reasons.map(([k, t]) => `<li class="${k === res.reason ? "hit" : ""}">${k === res.reason ? icon("warn") : icon("check")}${t.replace("The 8th outbreak ended the game", "8 outbreaks")}${k === res.reason ? ": this ended the game" : ": not reached"}</li>`).join("")}</ul>`}
    ${statsBlock()}
    <div class="modal-foot"><button class="btn" data-close>Look at the board</button>${host ? '<button class="btn" id="over-lobby">Back to lobby</button><button class="btn primary" id="over-again">Play again</button>' : '<span class="note">The host can start another game.</span>'}</div>`,
    "narrow",
    true,
  );
  $("#over-lobby") && ($("#over-lobby").onclick = () => send({ type: "to_lobby" }));
  $("#over-again") && ($("#over-again").onclick = () => send({ type: "play_again" }));
}

/* ================================================================ global wiring */
export function onDocClick(e) {
  if (!$("#game")) return;
  const hb = e.target.closest("[data-help]");
  if (hb) {
    e.stopPropagation();
    showBubble(hb);
    return;
  }
  if (!e.target.closest("#bubble")) $("#bubble").classList.add("hidden");
  if (!e.target.closest("#menu, #menu-btn")) $("#menu").classList.add("hidden");
  if (!e.target.closest("#legend, #legend-btn")) $("#legend")?.classList.add("hidden");
  if (!e.target.closest("#react, #react-btn")) $("#react")?.classList.add("hidden");
  if (!e.target.closest("#sheet, .pl, #role-chip")) closeSheet();
}

export function onKey(e) {
  if (!$("#game") || !g()) return;
  if (e.target.matches?.("input, textarea")) {
    if (e.key !== "Escape") return;
    e.target.blur();
  }
  if (e.metaKey || e.ctrlKey || e.altKey) return;
  const modalOpen = !!$("#modal-root").innerHTML;
  if (e.key === "Escape") {
    if (modalOpen) {
      if (!S.ui.forced) closeModal();
      return;
    }
    if (!$("#menu").classList.contains("hidden")) return $("#menu").classList.add("hidden");
    if (!$("#bubble").classList.contains("hidden")) return $("#bubble").classList.add("hidden");
    if (!$("#sheet").classList.contains("hidden")) return closeSheet();
    if (!$("#pop").classList.contains("hidden")) {
      const id = $("#pop").dataset.id;
      hidePop();
      $(`#map .city[data-id="${id}"]`)?.focus({ preventScroll: true });
      return;
    }
    if (S.ui.mode) return setMode(null);
    if ($("#side").classList.contains("open")) return toggleSide(false);
    if (S.ui.passArm) {
      S.ui.passArm = false;
      renderDock();
    }
    return;
  }
  if (modalOpen) return;
  const game = g();
  const k = e.key.toLowerCase();
  const map = { d: "drive", f: "direct", c: "charter", s: "shuttle", b: "build", t: "treat", k: "share", u: "cure" };
  if (map[k]) {
    e.preventDefault();
    actKey(map[k]);
  } else if (k === "z") undo();
  else if (k === "p" && myTurn() && actionsLeft() > 0) passClick();
  else if (k === "n" && game.step === "draw" && game.waiting_for === mySeat() && game.current === mySeat()) act({ type: "draw" });
  else if (e.key === " " && $("#continue-btn") && !e.target.closest("button, .city")) {
    e.preventDefault();
    act({ type: "continue" });
  } else if (e.key === "+" || e.key === "=") zoom(0.75);
  else if (e.key === "-") zoom(1 / 0.75);
  else if (e.key === "0") showWholeMap();
  else if (e.key === "?") openHelp();
}

export function onResize() {
  if (!$("#game")) return;
  refit();
  fitHand();
  placeResolve();
}

export function unreadChat() {
  if (!$("#game") || !g() || sideOpen()) return;
  S.ui.unread++;
  renderStatus();
}

// The server refused a request: let the forced dialogs come back.
export function onError() {
  S.ui.sent = null;
  S.ui.forced = null;
  if ($("#game") && g()) renderGame();
}
