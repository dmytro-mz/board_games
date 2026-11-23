// What you can do right now and why not. The server re-checks everything; these mirror the engine's rules.
import { ADJ, CFG, CITIES, DCOLS, DNAME } from "./data.js";
import { S, actionsLeft, cubesAt, cures, g, me, mySeat, need, players, stations } from "./store.js";
import { cityName, colorCounts, isEv, listText, plural } from "./ui.js";

export function bfs(from) {
  const dist = { [from]: 0 };
  const prev = {};
  const q = [from];
  while (q.length) {
    const a = q.shift();
    for (const b of ADJ[a]) {
      if (!(b in dist)) {
        dist[b] = dist[a] + 1;
        prev[b] = a;
        q.push(b);
      }
    }
  }
  return { dist, prev };
}

export function pathTo(from, to) {
  const { prev } = bfs(from);
  const p = [];
  let c = to;
  while (c && c !== from) {
    p.unshift(c);
    c = prev[c];
  }
  return [from, ...p];
}

const cityCards = (hand) => (hand || []).filter((c) => !isEv(c));

// The pawn your moves apply to: your own, or the one the Dispatcher picked.
export function movingPawn() {
  const seat = mySeat();
  const p = S.ui.pawn;
  if (p == null || p === seat || me()?.role !== "dispatcher" || !players()[p]) return seat;
  return p;
}

const pawnArg = (p) => (p === mySeat() ? {} : { pawn: p });

export function moveOptions(id) {
  const self = me();
  const p = movingPawn();
  const pawn = players()[p];
  const at = pawn.at;
  const left = actionsLeft();
  const hand = self.hand || [];
  const own = p === mySeat();
  const st = stations();
  const d = bfs(at).dist[id];
  const route = pathTo(at, id);
  const via = route.slice(1, -1).map(cityName);
  const yours = own ? "the" : "your";
  const opts = [
    {
      kind: "drive",
      icon: "drive",
      title: "Drive / Ferry",
      ok: d <= left,
      cost: d,
      sub: d === 1 ? "Next door" : `${d} steps via ${listText(via)}`,
      why: `${d} steps away: needs ${plural(d, "action")}, you have ${left}`,
      actions: route.slice(1).map((to) => ({ type: "drive", to, ...pawnArg(p) })),
    },
    {
      kind: "direct",
      icon: "direct",
      title: "Direct flight",
      ok: hand.includes(id),
      cost: 1,
      sub: `Discard ${yours} ${cityName(id)} card`,
      why: `Needs ${yours} ${cityName(id)} card`,
      actions: [{ type: "direct", to: id, ...pawnArg(p) }],
    },
    {
      kind: "charter",
      icon: "charter",
      title: "Charter flight",
      ok: hand.includes(at),
      cost: 1,
      sub: `Discard ${yours} ${cityName(at)} card`,
      why: `Needs ${yours} ${cityName(at)} card`,
      actions: [{ type: "charter", to: id, ...pawnArg(p) }],
    },
    {
      kind: "shuttle",
      icon: "shuttle",
      title: "Shuttle flight",
      ok: st.includes(at) && st.includes(id),
      cost: 1,
      sub: "Between research stations",
      why: "Needs a research station here and there",
      actions: [{ type: "shuttle", to: id, ...pawnArg(p) }],
    },
  ];
  if (self.role === "dispatcher") {
    const others = players().filter((o) => o.i !== p && o.at === id);
    opts.push({
      kind: "dispatch",
      icon: "dispatch",
      title: "Dispatch",
      ok: others.length > 0,
      cost: 1,
      sub: `Join ${listText(others.map((o) => o.name))}`,
      why: "Only to a city with another pawn",
      actions: [{ type: "dispatch", pawn: p, to: id }],
    });
  }
  if (self.role === "ops" && own) {
    const ok = st.includes(at) && !g().ops_flight_used && cityCards(hand).length > 0;
    opts.push({
      kind: "ops",
      icon: "charter",
      title: "Station flight",
      ok,
      cost: 1,
      sub: "Operations Expert: discard any city card",
      why: g().ops_flight_used ? "Used already this turn" : st.includes(at) ? "Needs a city card" : "Only from a research station",
      pick: true,
    });
  }
  return opts.sort((a, b) => b.ok - a.ok || a.cost - b.cost);
}

export function modeTargets(mode = S.ui.mode) {
  if (!mode || !g()) return [];
  const all = Object.keys(CITIES);
  if (mode === "airlift") {
    const at = players()[S.ui.airlift ?? mySeat()]?.at;
    return all.filter((c) => c !== at);
  }
  if (mode === "grant") return all.filter((c) => !stations().includes(c));
  const self = me();
  if (!self) return [];
  const p = movingPawn();
  const at = players()[p].at;
  const hand = self.hand || [];
  if (mode === "drive") return ADJ[at];
  if (mode === "direct") return cityCards(hand).filter((c) => c !== at);
  if (mode === "charter") return hand.includes(at) ? all.filter((c) => c !== at) : [];
  if (mode === "shuttle") return stations().includes(at) ? stations().filter((c) => c !== at) : [];
  if (mode === "dispatch") return [...new Set(players().filter((o) => o.i !== p && o.at !== at).map((o) => o.at))];
  return [];
}

export function treatOptions() {
  const self = me();
  const m = cubesAt(self.at);
  return DCOLS.filter((c) => m[c]).map((col) => {
    const n = m[col];
    const all = self.role === "medic" || cures()[col] !== "none";
    return { col, n, removed: all ? n : 1, left: all ? 0 : n - 1 };
  });
}

// Give and take options with the teammates in your city. Closed hands: you can only ask for the card of this city.
export function shareOptions() {
  const self = me();
  const here = self.at;
  const out = [];
  for (const mate of players()) {
    if (mate.i === self.i || mate.at !== here) continue;
    for (const c of cityCards(self.hand)) {
      if (c === here || self.role === "researcher") out.push({ kind: "give", card: c, mate, action: { type: "give", card: c, to: mate.i } });
    }
    const theirs = mate.hand ? cityCards(mate.hand) : [here];
    for (const c of theirs) {
      if (c === here || mate.role === "researcher") out.push({ kind: "take", card: c, mate, unsure: !mate.hand, action: { type: "take", card: c, giver: mate.i } });
    }
    if (!mate.hand && mate.role === "researcher") out.push({ kind: "take-any", mate });
  }
  return out;
}

export function cureOptions() {
  const self = me();
  const n = need(self.role);
  const counts = colorCounts(self.hand);
  return DCOLS.filter((c) => cures()[c] === "none" && counts[c] >= n).map((col) => ({
    col,
    need: n,
    cards: cityCards(self.hand).filter((c) => CITIES[c].color === col),
  }));
}

export function dockActs() {
  const self = me();
  const p = movingPawn();
  const pawn = players()[p];
  const hand = self.hand || [];
  const st = stations();
  const here = cityName(self.at);
  const pawnAt = cityName(pawn.at);
  const counts = colorCounts(hand);
  const n = need(self.role);
  const atSt = st.includes(self.at);
  const mates = players().filter((o) => o.i !== self.i && o.at === self.at);
  const cureCol = DCOLS.find((c) => counts[c] >= n && cures()[c] === "none");
  const best = DCOLS.filter((c) => cures()[c] === "none").sort((a, b) => counts[b] - counts[a])[0];
  const hasHere = hand.includes(self.at);
  const acts = [
    { k: "drive", i: "drive", t: "Drive / Ferry", ok: true, s: "To a neighbour" },
    { k: "direct", i: "direct", t: "Direct flight", ok: cityCards(hand).some((c) => c !== pawn.at), s: "Fly to a card", no: "No city cards" },
    { k: "charter", i: "charter", t: "Charter flight", ok: hand.includes(pawn.at), s: `Discard ${pawnAt}`, no: `Needs ${pawnAt}` },
    { k: "shuttle", i: "shuttle", t: "Shuttle flight", ok: st.includes(pawn.at) && st.length > 1, s: "Station to station", no: "No station here" },
    {
      k: "build",
      i: "build",
      t: "Build station",
      ok: !atSt && (hasHere || self.role === "ops"),
      s: self.role === "ops" ? "No card needed" : `Discard ${here}`,
      no: atSt ? "Already built" : `Needs ${here}`,
    },
    { k: "treat", i: "treat", t: "Treat disease", ok: Object.values(cubesAt(self.at)).some(Boolean), s: "Remove 1 cube", no: "No cubes here" },
    {
      k: "share",
      i: "share",
      t: "Share knowledge",
      ok: mates.length > 0 && shareOptions().length > 0,
      s: "Give or take",
      no: mates.length ? `Only the ${here} card` : "No teammate here",
    },
    {
      k: "cure",
      i: "cure",
      t: "Discover cure",
      ok: !!(atSt && cureCol),
      ready: !!(atSt && cureCol),
      s: cureCol ? `Cure ${cureCol}` : "",
      no: best ? `${DNAME[best]} ${counts[best]}/${n}${atSt ? "" : ", no station"}` : "All cured",
    },
  ];
  return acts;
}

// Can you play this event card now? Mirrors Game._event.
export function eventPlayable(card) {
  const game = g();
  const seat = mySeat();
  if (!game || seat == null || game.result) return { ok: false, why: "The game is over" };
  if (game.forecast) return { ok: false, why: "Wait until the Forecast cards are back on the deck" };
  if (game.over_limit != null && game.over_limit !== seat) return { ok: false, why: "Wait: a player is over the hand limit" };
  if (game.step === "epidemic" && card !== "resilient") return { ok: false, why: "During an epidemic only Resilient Population can be played" };
  if (card === "resilient" && !game.infection_discard.length) return { ok: false, why: "The infection discard pile is empty" };
  if (card === "forecast" && !game.infection_deck) return { ok: false, why: "The infection deck is empty" };
  if (card === "quiet" && game.quiet_night) return { ok: false, why: "The next Infect Cities step is already skipped" };
  return { ok: true };
}

// Event cards you could play now: from your hand and your stored card.
export function myEvents() {
  const self = me();
  if (!self) return [];
  const evs = (self.hand || []).filter(isEv).map((c) => ({ card: c, stored: false }));
  if (self.stored) evs.push({ card: self.stored, stored: true });
  return evs;
}

export const handLimit = () => CFG.hand;
