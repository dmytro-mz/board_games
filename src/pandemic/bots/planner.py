"""A heuristic planner: beam-searches the current turn's action sequences on a sandbox game and scores each
resulting board with `evaluate`. Events, discards and Forecast orders use the same judgement.

The evaluation is a weighted sum of: cures found, cube threat (3-cube cities and chains count most, cities whose
infection card is known to be on top of the deck even more), progress towards each cure (the best set in one hand
and the cards the team holds), how close each pawn is to useful work, how far a ready cure set is from a research
station, the spread of research stations and the cards still in hand.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass

from pandemic.bots.base import Bot
from pandemic.game.actions import (
    Action,
    Airlift,
    Build,
    CharterFlight,
    Continue,
    Cure,
    DirectFlight,
    Discard,
    DrawCards,
    Drive,
    Forecast,
    ForecastOrder,
    Give,
    GovernmentGrant,
    OneQuietNight,
    OpsFlight,
    Pass,
    ResilientPopulation,
    ShuttleFlight,
    Take,
    TakeEvent,
    Treat,
)
from pandemic.game.engine import Game, IllegalMove, Step, View
from pandemic.game.model import ADJ, CITIES, COLORS, DIST, EVENTS, MAX_STATIONS, Color, EventCard, Role, path

THREAT = (0.0, 1.0, 3.0, 9.0)  # by cubes on a city


@dataclass(frozen=True)
class Weights:
    cure: float = 2000.0
    eradicated: float = 150.0
    threat: float = 10.0
    chain: float = 2.0  # extra threat per neighbouring 3-cube city of a 3-cube city
    known_top: float = 2.5  # threat multiplier for cities known to be on top of the infection deck
    discarded: float = 0.5  # ... and for cities whose card is in the infection discard pile
    reach: float = 4.0
    set: float = 600.0
    team: float = 40.0
    ready: float = 500.0
    to_station: float = 60.0
    meet: float = 0.5
    coverage: float = 12.0
    card: float = 4.0
    cured_card: float = 1.0
    event: float = 35.0
    crowd: float = 0.0  # per card above 5 in a hand (the next draw may force a discard)


DEFAULT = Weights()
LOCAL = (Build, Treat, Give, Take, Cure, TakeEvent)  # actions that don't move a pawn


def color_counts(hand: Iterable[str]) -> dict[Color, int]:
    out = dict.fromkeys(COLORS, 0)
    for c in hand:
        city = CITIES.get(c)
        if city is not None:
            out[city.color] += 1
    return out


def evaluate(g: Game, w: Weights = DEFAULT) -> float:
    """How good the board is for the team (higher is better)."""
    if g.result is not None:
        return 1e6 if g.result.won else -1e6
    score = 0.0
    for v in g.cures.values():
        if v != "none":
            score += w.cure + (w.eradicated if v == "eradicated" else 0.0)

    known = set(g.known_top)
    gone = set(g.infection_discard)
    shield: set[str] = set()
    medics: set[str] = set()
    for s in range(g.n):
        at = g.location[s]
        if g.roles[s] == Role.QUARANTINE_SPECIALIST:
            shield.add(at)
            shield.update(ADJ[at])
        elif g.roles[s] == Role.MEDIC:
            medics.add(at)

    threat = 0.0
    hot: list[tuple[str, Color, int, float]] = []
    for city, cc in g.cubes.items():
        for color, n in cc.items():
            if not n or g.cures[color] == "eradicated":
                continue
            weight = w.known_top if city in known else w.discarded if city in gone else 1.0
            if city in shield or (city in medics and g.cures[color] != "none"):
                weight *= 0.15
            t = THREAT[n]
            if n == 3:
                t += w.chain * sum(1 for nb in ADJ[city] if g.cubes[nb][color] == 3)
            threat += t * weight
            hot.append((city, color, n, weight))
    score -= w.threat * threat
    for color, left in g.supply.items():
        if left < 8 and g.cures[color] != "eradicated":
            score -= 6.0 * (8 - left) ** 2

    stations = g.stations
    near = {c: min(DIST[c][s] for s in stations) for c in CITIES}
    hands = [set(h) for h in g.hands]

    def travel(p: int, target: str) -> int:
        at = g.location[p]
        d = DIST[at][target]
        if d <= 1:
            return d
        if target in hands[p] or at in hands[p]:
            return 1
        if len(stations) > 1:
            d = min(d, near[at] + 1 + near[target])
        return d

    for p in range(g.n):
        everything = g.roles[p] == Role.MEDIC
        best = second = 0.0
        for city, color, n, weight in hot:
            removed = n if everything or g.cures[color] != "none" else 1
            relief = (THREAT[n] - THREAT[n - removed]) * weight
            if relief < 0.5:
                continue
            v = relief / (1 + travel(p, city))
            if v > best:
                best, second = v, best
            elif v > second:
                second = v
        score += w.reach * (best + 0.3 * second)

    counts = [color_counts(h) for h in g.hands]
    me = g.current
    meet = 0.0
    for color in COLORS:
        if g.cures[color] != "none":
            continue
        best_f, holder, total = 0.0, 0, 0
        for p in range(g.n):
            k = counts[p][color]
            total += k
            f = k / g.need(p)
            if f > best_f:
                best_f, holder = f, p
        score += w.set * min(best_f, 1.0) ** 2 + w.team * min(total, 5)
        if best_f >= 1.0:
            score += w.ready
            at = g.location[holder]
            if at not in stations:
                d = near[at]
                if d > 1 and (at in hands[holder] or any(s in hands[holder] for s in stations)):
                    d = 1
                score -= w.to_station * (min(d, 6) + 0.5)
            continue
        if best_f < 0.4:
            continue
        need = g.need(holder)
        k = counts[holder][color]
        gain = w.set * (min(k + 1, need) ** 2 - k**2) / need**2 + (w.ready if k + 1 >= need else 0.0)
        givers = [me] if me != holder else [p for p in range(g.n) if p != me and counts[p][color]]
        for giver in givers:
            if not counts[giver][color]:
                continue
            if g.roles[giver] == Role.RESEARCHER:
                d = DIST[g.location[me]][g.location[giver if me == holder else holder]]
            else:
                d = min(
                    travel(me, c) + DIST[g.location[giver if me == holder else holder]][c]
                    for c in hands[giver]
                    if c in CITIES and CITIES[c].color == color
                )
            meet = max(meet, gain / (1 + d))
    score += w.meet * meet

    for p in range(g.n):
        crowd = len(g.hands[p]) - 5
        if crowd > 0:
            score -= w.crowd * crowd
        for c in g.hands[p]:
            city = CITIES.get(c)
            if city is not None:
                score += w.card if g.cures[city.color] == "none" else w.cured_card
            elif c in EVENTS:
                score += w.event
        if g.stored[p]:
            score += w.event

    if len(stations) < MAX_STATIONS:
        score -= w.coverage * sum(min(d, 5) for d in near.values()) / len(near)
    return score


def signature(g: Game) -> tuple:
    return (
        g.turn,
        g.step,
        g.actions_left,
        tuple(g.location),
        tuple(tuple(sorted(h)) for h in g.hands),
        tuple(g.stored),
        tuple(sorted(g.stations)),
        tuple(g.supply.values()),
        tuple(g.cures.values()),
        tuple((c, col, n) for c, cc in g.cubes.items() for col, n in cc.items() if n),
    )


def danger(g: Game, city: str) -> float:
    """How bad drawing this infection card would be now."""
    color = CITIES[city].color
    if g.cures[color] == "eradicated" or g._protected(city, color):
        return 0.0
    n = g.cubes[city][color]
    if n < 3:
        return float(n)
    return 10.0 + 3.0 * sum(1 for nb in ADJ[city] if g.cubes[nb][color] >= 2)


def expected_outbreaks(g: Game) -> float:
    rate = g.infection_rate
    known = [c for c in g.known_top]
    p_known = min(1.0, rate / len(known)) if known else 0.0
    rest = max(0, rate - len(known))
    unknown = len(g.infection_deck) - len(known)
    p_rest = min(1.0, rest / unknown) if unknown > 0 else 0.0
    gone = set(g.infection_discard)
    total = 0.0
    for city in CITIES:
        if city in gone or city in g.removed:
            continue
        d = danger(g, city)
        if d < 10:
            continue
        p = p_known if city in known else p_rest
        total += p * d / 10.0
    return total


class Planner(Bot):
    """Plans each turn with a beam search; `beam=1, noise>0` makes a weaker, greedier player."""

    def __init__(
        self,
        seed: int | None = None,
        beam: int = 8,
        noise: float = 0.0,
        events: bool = True,
        weights: Weights = DEFAULT,
    ) -> None:
        super().__init__(seed)
        self.beam = beam
        self.noise = noise
        self.events = events
        self.weights = weights
        self._plan: list[Action] = []
        self._expect: tuple | None = None

    # ------------------------------------------------------------------ entry points
    def act(self, view: View) -> Action:
        g = view.sandbox()
        seat = view.seat
        if view.forecast is not None:
            return ForecastOrder(tuple(self.forecast_order(g, view.forecast)))
        if g.over_limit() == seat:
            return self.discard(g, seat)
        if g.step == Step.ACTIONS:
            return self.turn_action(g, seat)
        if g.step == Step.DRAW:
            return DrawCards()
        return self.window(g, seat) or Continue()

    def react(self, view: View) -> Action | None:
        if not self.events or view.forecast is not None or view.waiting_for in (None, view.seat):
            return None
        g = view.sandbox()
        if g.over_limit() is not None or g.step not in (Step.EPIDEMIC, Step.INFECT):
            return None
        return self.window(g, view.seat)

    # ------------------------------------------------------------------ events between steps
    def holds(self, g: Game, seat: int, card: EventCard) -> bool:
        return card in g.hands[seat] or g.stored[seat] == card

    def window(self, g: Game, seat: int) -> Action | None:
        """Resilient Population during an epidemic; Forecast or One Quiet Night before the cities are infected."""
        if not self.events:
            return None
        if g.step == Step.EPIDEMIC:
            if not self.holds(g, seat, EventCard.RESILIENT_POPULATION) or not g.infection_discard:
                return None
            city = max(g.infection_discard, key=lambda c: (g.cubes[c][CITIES[c].color], danger(g, c)))
            if g.cubes[city][CITIES[city].color] >= 3 or len(g.infection_discard) <= 1:
                return ResilientPopulation(city)
            return None
        if g.step != Step.INFECT or g.quiet_night:
            return None
        risk = expected_outbreaks(g)
        if self.holds(g, seat, EventCard.FORECAST) and g.infection_deck and (risk >= 0.25 or g.known_top):
            return Forecast()
        if self.holds(g, seat, EventCard.ONE_QUIET_NIGHT) and risk >= 0.6:
            return OneQuietNight()
        return None

    def forecast_order(self, g: Game, cards: list[str]) -> list[str]:
        """Harmless cards on top, the dangerous ones as deep as possible (next players get to treat them)."""
        return sorted(cards, key=lambda c: (danger(g, c), c))

    def discard(self, g: Game, seat: int) -> Action:
        options: list[tuple[float, Action]] = []
        for card in dict.fromkeys(g.hands[seat]):
            c = g.clone()
            c.hands[seat].remove(card)
            c.player_discard.append(card)
            options.append((evaluate(c, self.weights), Discard(card)))
        options.sort(key=lambda o: o[0], reverse=True)
        best = options[0][1]
        if self.events and isinstance(best, Discard) and best.card in EVENTS:
            play = self.spend_event(g, seat, best.card)
            if play is not None:
                return play
        return best

    def spend_event(self, g: Game, seat: int, card: str) -> Action | None:
        """Play an event card that would otherwise be discarded."""
        epidemic = g.step == Step.EPIDEMIC
        if card == EventCard.RESILIENT_POPULATION and g.infection_discard:
            return ResilientPopulation(max(g.infection_discard, key=lambda c: danger(g, c)))
        if epidemic:
            return None
        if card == EventCard.FORECAST and g.infection_deck:
            return Forecast()
        if card == EventCard.ONE_QUIET_NIGHT and not g.quiet_night:
            return OneQuietNight()
        options = [a for a in self.event_moves(g, seat) if isinstance(a, (Airlift, GovernmentGrant))]
        return self.best(g, seat, options)

    def best(self, g: Game, seat: int, options: list[Action]) -> Action | None:
        top: tuple[float, Action] | None = None
        for a in options:
            c = g.clone()
            try:
                c.play(seat, a)
            except IllegalMove:
                continue
            v = evaluate(c, self.weights)
            if top is None or v > top[0]:
                top = (v, a)
        return top[1] if top else None

    # ------------------------------------------------------------------ turn planning
    def turn_action(self, g: Game, seat: int) -> Action:
        if self._plan and self._expect == signature(g):
            action = self._plan.pop(0)
            if self._try(g, seat, action):
                return action
        if self.noise and self.rng.random() < self.noise:
            moves = [a for a in g.turn_actions(seat) if not isinstance(a, Pass)]
            if moves:
                action = self.rng.choice(moves)
                self._plan = []
                return action
        plan = self.plan_turn(g, seat)
        action = plan[0] if plan else Pass()
        self._plan = plan[1:]
        if not self._try(g, seat, action):
            self._plan = []
            return Pass()
        return action

    def _try(self, g: Game, seat: int, action: Action) -> bool:
        c = g.clone()
        try:
            c.play(seat, action)
        except IllegalMove:
            return False
        self._expect = signature(c)
        return True

    def plan_turn(self, root: Game, seat: int) -> list[Action]:
        spots = self.interesting(root, seat)
        beam: list[tuple[float, Game, list[Action]]] = [(evaluate(root, self.weights), root, [])]
        done: list[tuple[float, Game, list[Action]]] = []
        for _ in range(root.actions_left + 2):
            grown: dict[tuple, tuple[float, Game, list[Action]]] = {}
            for _, g, seq in beam:
                if g.step != Step.ACTIONS or g.current != seat or g.result is not None:
                    continue
                for a in self.candidates(g, seat, spots, events=not seq or not self._played_event(seq)):
                    c = g.clone()
                    try:
                        c.play(seat, a)
                    except IllegalMove:
                        continue
                    item = (evaluate(c, self.weights), c, [*seq, a])
                    key = signature(c)
                    if key not in grown or grown[key][0] < item[0]:
                        grown[key] = item
            if not grown:
                break
            ranked = sorted(grown.values(), key=lambda t: t[0], reverse=True)
            done += [t for t in ranked if t[1].step != Step.ACTIONS or t[1].result is not None]
            beam = [t for t in ranked if t[1].step == Step.ACTIONS and t[1].result is None][: self.beam]
            if not beam:
                break
        pool = done + beam + self.errands(root, seat, spots)
        if not pool:
            return [Pass()]
        return max(pool, key=lambda t: t[0])[2]

    def errands(self, root: Game, seat: int, spots: set[str]) -> list[tuple[float, Game, list[Action]]]:
        """Drive straight to a destination, then do the best local actions there. These lines can dip in the
        middle (leaving a quarantined area, say), so the beam may lose them."""
        out = []
        at = root.location[seat]
        for target in spots:
            route = path(at, target)[1 : root.actions_left + 1]
            if not route:
                continue
            g = root.clone()
            seq: list[Action] = []
            for city in route:
                a = Drive(city)
                g.play(seat, a)
                seq.append(a)
            while g.step == Step.ACTIONS and g.result is None:
                best = None
                for a in g.turn_actions(seat):
                    if not isinstance(a, LOCAL):
                        continue
                    c = g.clone()
                    c.play(seat, a)
                    v = evaluate(c, self.weights)
                    if best is None or v > best[0]:
                        best = (v, c, a)
                if best is None or best[0] <= evaluate(g, self.weights):
                    break
                g = best[1]
                seq.append(best[2])
            out.append((evaluate(g, self.weights), g, seq))
        return out

    @staticmethod
    def _played_event(seq: list[Action]) -> bool:
        return any(isinstance(a, (Airlift, GovernmentGrant)) for a in seq)

    def interesting(self, g: Game, seat: int) -> set[str]:
        """Destinations worth a card: crowded or hot cities, stations, teammates."""
        out = set(g.stations) | set(g.location)
        scored = []
        for city, cc in g.cubes.items():
            m = max((n for col, n in cc.items() if g.cures[col] != "eradicated"), default=0)
            if m >= 2:
                out.add(city)
            if m:
                scored.append((sum(cc.values()) + m, city))
        out.update(c for _, c in sorted(scored, reverse=True)[:6])
        return out

    def candidates(self, g: Game, seat: int, spots: set[str], events: bool) -> list[Action]:
        out: list[Action] = []
        ops_card = self._cheapest(g, seat)
        for a in g.turn_actions(seat):
            if isinstance(a, (CharterFlight, OpsFlight)) and a.to not in spots:
                continue
            if isinstance(a, OpsFlight) and a.card != ops_card:
                continue
            if isinstance(a, (DirectFlight, ShuttleFlight)) and a.pawn is not None and a.to not in spots:
                continue
            out.append(a)
        if events and self.events:
            out += self.event_moves(g, seat, spots)
        return out

    def event_moves(self, g: Game, seat: int, spots: set[str] | None = None) -> list[Action]:
        """Airlift (own pawn, or a teammate with a cure set to a station) and Government Grant candidates."""
        out: list[Action] = []
        spots = spots if spots is not None else self.interesting(g, seat)
        if self.holds(g, seat, EventCard.AIRLIFT):
            out += [Airlift(seat, c) for c in spots if c != g.location[seat]]
            for p in range(g.n):
                if p != seat and g.location[p] not in g.stations:
                    out += [Airlift(p, s) for s in g.stations]
        if self.holds(g, seat, EventCard.GOVERNMENT_GRANT):
            full = len(g.stations) >= MAX_STATIONS
            for c in dict.fromkeys(g.location):
                if c in g.stations:
                    continue
                if full:
                    out += [GovernmentGrant(c, s) for s in g.stations]
                else:
                    out.append(GovernmentGrant(c))
        return out

    def _cheapest(self, g: Game, seat: int) -> str | None:
        cards = [c for c in g.hands[seat] if c in CITIES]
        if not cards:
            return None
        counts = color_counts(cards)
        return min(cards, key=lambda c: (g.cures[CITIES[c].color] == "none", counts[CITIES[c].color], c))


__all__ = ["DEFAULT", "Planner", "Weights", "danger", "evaluate", "expected_outbreaks"]
