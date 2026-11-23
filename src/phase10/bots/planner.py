"""The rule-based player behind every bot level (and the autopilot).

Before laying down it keeps the cards that bring it closest to its phase (see `solver`) and throws away the rest,
highest penalty first. Once down it adds everything it can to the table and dumps its most expensive card. The
stronger levels also avoid feeding the next player and aim their Skips at whoever is closest to going out.
"""

from __future__ import annotations

from dataclasses import dataclass

from phase10.bots.base import Bot
from phase10.bots.solver import evaluate, lay_down
from phase10.game.actions import Action, Discard, DrawDeck, DrawDiscard, Hit
from phase10.game.engine import Step, View
from phase10.game.model import Card
from phase10.game.rules import Group


@dataclass(frozen=True)
class PlannerConfig:
    smart_draw: bool = True  # take the discard only when it helps (else: only wilds)
    deny: bool = True  # don't discard what the next player could use
    skip_leader: bool = True  # skip the most dangerous player (else: random)
    noise: float = 0.0  # chance of a random (non-wild) discard before laying down


def hit_for(card: Card, groups: list[Group], prefer_owner: int | None = None) -> Hit | None:
    fits = [(g, g.ends_for(card)) for g in groups]
    fits = [(g, ends) for g, ends in fits if ends]
    if not fits:
        return None
    fits.sort(key=lambda f: f[0].owner != prefer_owner)
    g, ends = fits[0]
    return Hit(g.id, card.id, None if ends == ["any"] else ends[-1])


class PlannerBot(Bot):
    def __init__(self, seed: int | None = None, config: PlannerConfig | None = None) -> None:
        super().__init__(seed)
        self.config = config or PlannerConfig()

    def act(self, view: View) -> Action:
        if view.step == Step.DRAW:
            return self._draw(view)
        me = view.seat
        if not view.laid[me]:
            laid = lay_down(view.hand, view.reqs)
            if laid is not None:
                return laid
        else:
            hit = self._hit(view)
            if hit is not None:
                return hit
        return self._discard(view)

    # ------------------------------------------------------------------ draw
    def _draw(self, view: View) -> Action:
        top = view.discard_top
        if top is None or top.skip:
            return DrawDeck() if view.draw_size or len(view.discards) > 1 else DrawDiscard()
        if view.draw_size == 0 and len(view.discards) <= 1:
            return DrawDiscard()
        if top.wild:
            return DrawDiscard()
        if view.laid[view.seat]:
            return DrawDiscard() if any(g.ends_for(top) for g in view.groups) else DrawDeck()
        if not self.config.smart_draw:
            return DrawDeck()
        now = evaluate(view.hand, view.reqs).deficit
        with_top = min(self._keep_score(view, [*view.hand, top], skip=c)[0] for c in view.hand if c.id != top.id)
        return DrawDiscard() if with_top < now else DrawDeck()

    # ------------------------------------------------------------------ play
    def _hit(self, view: View) -> Hit | None:
        hand = sorted(view.hand, key=lambda c: (c.wild, -c.points))
        for card in hand:
            hit = hit_for(card, view.groups, view.seat)
            if hit is not None:
                return hit
        return None

    def _keep_score(self, view: View, hand: list[Card], skip: Card) -> tuple[int, int, int]:
        rest = [c for c in hand if c.id != skip.id]
        ev = evaluate(rest, view.reqs)
        return ev.deficit, -ev.flex, -skip.points

    def _discard(self, view: View) -> Discard:
        hand = view.hand
        skips = [c for c in hand if c.skip]
        if skips:
            return Discard(skips[0].id, self._skip_target(view))
        me = view.seat
        candidates = [c for c in hand if not c.wild] or list(hand)
        if view.laid[me]:
            scored = [(self._danger(view, c), -c.points, c.id, c) for c in candidates]
            return Discard(min(scored, key=lambda s: s[:3])[3].id)
        if self.config.noise and self.rng.random() < self.config.noise:
            return Discard(self.rng.choice(candidates).id)
        scored = []
        for c in candidates:
            deficit, flex, points = self._keep_score(view, hand, c)
            scored.append((deficit, self._danger(view, c), flex, points, c.id, c))
        return Discard(min(scored, key=lambda s: s[:5])[5].id)

    def _danger(self, view: View, card: Card) -> int:
        """1 if the next player could pick this card up and add it to the table."""
        if not self.config.deny:
            return 0
        nxt = (view.seat + 1) % view.n
        while (nxt in view.skipped or not view.active[nxt]) and nxt != view.seat:
            nxt = (nxt + 1) % view.n
        if nxt == view.seat or not view.laid[nxt]:
            return 0
        return 1 if any(g.ends_for(card) for g in view.groups) else 0

    def _skip_target(self, view: View) -> int | None:
        targets = view.skip_targets
        if not targets:
            return None
        if not self.config.skip_leader:
            return self.rng.choice(targets)

        def threat(i: int) -> tuple[int, int, int, int]:
            return (view.laid[i], -view.hand_counts[i], view.phases[i], -view.scores[i])

        return max(targets, key=threat)
