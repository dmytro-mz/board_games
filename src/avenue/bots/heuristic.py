"""Fast hand-written evaluation and policy. Used for the search bot's playouts and as a baseline opponent.

Everything here decides from one player's point of view and only reads what that player may know: their own
hand and discards, everything in play, the face-up card and the card counts. It never looks at other hands, the
deck order or a face-down card someone else played — so it can run inside determinised (sampled) games without
"cheating".
"""

from __future__ import annotations

import math
import random

from avenue.game.cards import (
    BRAINWASHING,
    CODEBREAKER,
    DAREDEVIL,
    DECK_COUNTS,
    DOUBLE_AGENT,
    DOUBLE_TROUBLE,
    GETAWAY,
    HOMES,
    LEADER,
    MARKET_SPACES,
    MASTERPLAN,
    N_AGENTS,
    OUTPOST,
    SECRET_RECRUIT,
    SECURITY,
    SENTINEL,
    SINISTER_TWIN,
    SMOKE_SCREEN,
    SPYCATION,
    SUPERCOMPUTER,
    TRACK,
    TRUCK,
    WATCHTOWER,
)
from avenue.game.engine import HIDDEN, Action, Game, Phase

# Evaluation: a logistic model over the features below (logit units), fitted on self-play games with
# scripts/fit_eval.py. Order matches `features()`.
FEATURES = (
    "distance",  # 7 - my distance to catch (0 at the start, +7 = caught)
    "potential",  # expected move of my next card minus theirs, times the turns that are left (max 3)
    "codebreakers2",  # I have 2 Codebreakers (minus: they have)
    "daredevils2",  # 2 Daredevils without Leader of the Pack
    "leader2",  # 2 Daredevils with Leader of the Pack
    "daredevils1",
    "sets",  # one more Sentinel / Double Agent gives +6
    "owned",  # ongoing black market cards
    "on_market",  # standing on a black market space (a 0-move won't trigger it)
    "endgame",  # distance advantage when the deck is almost empty
    "tempo",  # I move next
    "codebreakers1",
)
WEIGHTS = [0.379, 0.241, 0.610, -0.602, 0.5, -0.380, 0.168, 0.313, -0.059, -0.044, -0.020, 0.396]
POT_TURNS = 3.0

THIRD_WIN = 9.0  # "move value" of a card that wins on the spot when it is recruited
THIRD_LOSE = -9.0


def sigmoid(x: float) -> float:
    if x > 30:
        return 1.0
    if x < -30:
        return 0.0
    return 1.0 / (1.0 + math.exp(-x))


def distance(pos0: int, pos1: int, side: int) -> int:
    return pos1 - pos0 if side == 0 else pos0 + TRACK - pos1


def unseen(g: Game, player: int) -> list[int]:
    """Agent cards `player` can't see (other hands, the deck, other discards, a hidden face-down card)."""
    pool = list(DECK_COUNTS)
    for t in g.tableau:
        for c in range(N_AGENTS):
            pool[c] -= t[c]
    for c in g.hands[player]:
        pool[c] -= 1
    for c in g.discards[player]:
        pool[c] -= 1
    if g.up is not None:
        pool[g.up[1]] -= 1
    if g.down is not None and g.down[0] == player and g.down[1] != HIDDEN:
        pool[g.down[1]] -= 1
    return [max(0, n) for n in pool]


def card_value(g: Game, side: int, card: int, count: int) -> float:
    """Spaces moved for recruiting `card` as copy number `count`, with instant wins/losses as big numbers."""
    return value_table(g, side)[card][count if count < 3 else 3]


_SIMPLE_TABLE: list[list[float]] = []
_TABLES: dict[tuple[int, ...], list[list[float]]] = {}


def _build_table(g: Game, side: int, leader: bool) -> list[list[float]]:
    table = []
    for c in range(N_AGENTS):
        row = [0.0] + [float(g.move_value(side, c, n)) for n in (1, 2, 3)]
        if c == CODEBREAKER:
            row[3] = THIRD_WIN
        elif c == DAREDEVIL:
            row[3] = THIRD_WIN if leader else THIRD_LOSE
        table.append(row)
    return table


def value_table(g: Game, side: int) -> list[list[float]]:
    """value_table(g, side)[card][copies] — the card_value for copies 0..3 (cached per set of owned cards)."""
    owned = g.owned[side] if g.advanced else ()
    if not owned:
        if not _SIMPLE_TABLE:
            _SIMPLE_TABLE.extend(_build_table(g, side, False))
        return _SIMPLE_TABLE
    key = tuple(sorted(owned))
    table = _TABLES.get(key)
    if table is None:
        table = _TABLES[key] = _build_table(g, side, LEADER in owned)
    return table


def potential(g: Game, side: int, tab: list[int], pool: list[int], total: int) -> float:
    """Expected move of the next card `side` recruits (if it were a random unseen card)."""
    if total <= 0:
        return 0.0
    table = value_table(g, side)
    acc = 0.0
    for c in range(N_AGENTS):
        n = pool[c]
        if n:
            k = tab[c] + 1
            acc += n * table[c][k if k < 3 else 3]
    return acc / total


def features(
    g: Game, side: int, d_me: int, tab_me: list[int], tab_op: list[int], pos_me: int, pos_op: int, next_side: int
) -> list[float]:
    op = 1 - side
    pool = list(DECK_COUNTS)
    for c in range(N_AGENTS):
        pool[c] -= tab_me[c] + tab_op[c]
    total = sum(pool)
    horizon = min(POT_TURNS, len(g.deck) / 2.0 + 1.0)
    pot = horizon * (potential(g, side, tab_me, pool, total) - potential(g, op, tab_op, pool, total))
    leader_me, leader_op = g.has(side, LEADER), g.has(op, LEADER)
    dd_me, dd_op = tab_me[DAREDEVIL], tab_op[DAREDEVIL]
    sets = 0
    for c in (SENTINEL, DOUBLE_AGENT):
        if pool[c]:
            want = 2 if c == SENTINEL else 1
            sets += (tab_me[c] == want) - (tab_op[c] == want)
    owned = len(g.owned[side]) - len(g.owned[op]) if g.advanced else 0
    on_market = 0
    if g.advanced:
        on_market = (pos_me % TRACK in MARKET_SPACES) - (pos_op % TRACK in MARKET_SPACES)
    dist = 7.0 - d_me
    return [
        dist,
        pot,
        (tab_me[CODEBREAKER] == 2) - (tab_op[CODEBREAKER] == 2),
        (dd_me == 2 and not leader_me) - (dd_op == 2 and not leader_op),
        (dd_me == 2 and leader_me) - (dd_op == 2 and leader_op),
        (dd_me == 1 and not leader_me) - (dd_op == 1 and not leader_op),
        sets,
        owned,
        on_market,
        dist if len(g.deck) <= 6 else 0.0,
        1.0 if next_side == side else -1.0,
        (tab_me[CODEBREAKER] == 1) - (tab_op[CODEBREAKER] == 1),
    ]


def static_eval(
    g: Game,
    side: int,
    d_me: int,
    tab_me: list[int],
    tab_op: list[int],
    pos_me: int,
    pos_op: int,
    next_side: int | None = None,
) -> float:
    """Winning chance for `side` in a position without an immediate result."""
    if next_side is None:
        next_side = g.active
    f = features(g, side, d_me, tab_me, tab_op, pos_me, pos_op, next_side)
    score = 0.0
    for w, x in zip(WEIGHTS, f, strict=True):
        score += w * x
    return sigmoid(score)


def _moved(g: Game, side: int, pos: int, steps: int) -> int:
    pos += steps
    if steps and g.advanced and pos % TRACK in HOMES and GETAWAY in g.owned[side]:
        pos += 3
    return pos


def _wins(g: Game, side: int, tab: list[int], d: int, pos_op: int) -> bool:
    if d <= 0 or tab[CODEBREAKER] >= 3:
        return True
    if g.advanced and g.owned[side]:
        owned = g.owned[side]
        if MASTERPLAN in owned and sum(1 for n in tab if n) >= 7:
            return True
        if SECURITY in owned and pos_op % TRACK == HOMES[side]:
            return True
        if LEADER in owned and tab[DAREDEVIL] >= 3:
            return True
    return False


def split_value(g: Game, side: int, mine: int, theirs: int) -> float:
    """Winning chance for `side` once it recruits `mine` and the other side recruits `theirs` this turn."""
    op = 1 - side
    tab_me = g.tableau[side][:]
    tab_op = g.tableau[op][:]
    tab_me[mine] += 1
    tab_op[theirs] += 1
    pos_me = _moved(g, side, g.pos[side], g.move_value(side, mine, tab_me[mine]))
    pos_op = _moved(g, op, g.pos[op], g.move_value(op, theirs, tab_op[theirs]))
    d_me = pos_op - pos_me if side == 0 else pos_op + TRACK - pos_me
    d_op = TRACK - d_me
    me_claims = _wins(g, side, tab_me, d_me, pos_op) or (tab_op[DAREDEVIL] >= 3 and not g.has(op, LEADER))
    op_claims = _wins(g, op, tab_op, d_op, pos_me) or (tab_me[DAREDEVIL] >= 3 and not g.has(side, LEADER))
    if me_claims or op_claims:
        if me_claims and op_claims:
            return 1.0 if g.active == side else 0.0
        return 1.0 if me_claims else 0.0
    value = static_eval(g, side, d_me, tab_me, tab_op, pos_me, pos_op, 1 - g.active)
    if g.advanced and g.supply:
        if pos_me % TRACK in MARKET_SPACES and pos_me != g.pos[side]:
            value += (1 - value) * 0.06
        if pos_op % TRACK in MARKET_SPACES and pos_op != g.pos[op]:
            value -= value * 0.06
    return value


# ---------------------------------------------------------------------- policy
def down_weights(g: Game, recruiter: int, up_card: int, pool: list[int]) -> list[float]:
    """Belief about the face-down card: unseen cards, minus the face-up name (they must differ)."""
    w = [float(n) for n in pool]
    if w[up_card] and sum(w) > w[up_card]:
        w[up_card] *= 0.02
    return w


def recruit_scores(g: Game, player: int) -> tuple[float, float]:
    """Expected winning chance for `player`'s side when taking the face-up card / the face-down card."""
    assert g.up is not None
    side = g.side_of[player]
    up = g.up[1]
    pool = unseen(g, player)
    w = down_weights(g, player, up, pool)
    total = sum(w)
    if total <= 0:
        return 0.5, 0.5
    take_up = take_down = 0.0
    for c in range(N_AGENTS):
        if w[c]:
            take_up += w[c] * split_value(g, side, up, c)
            take_down += w[c] * split_value(g, side, c, up)
    return take_up / total, take_down / total


def play_scores(g: Game, player: int, plays: list[Action]) -> list[float]:
    """Score each ("play", up, down) option for the active side (robust against the recruit choice)."""
    side = g.side_of[player]
    scores = []
    if g.solo(side) or (g.up is not None and g.down is None):
        fixed_up = g.up[1] if g.up is not None else None
        for _, a, b in plays:
            up = fixed_up if a < 0 else a
            assert up is not None
            # opponent takes the face-up card (I keep the face-down one) / takes the face-down card
            v_up = split_value(g, side, b, up)
            v_down = split_value(g, side, up, b)
            scores.append(0.55 * min(v_up, v_down) + 0.45 * (v_up + v_down) / 2)
        return scores
    # Team variant, first card (face up): the teammate's face-down card is unknown — average over the unseen cards.
    pool = unseen(g, player)
    for _, a, _b in plays:
        acc = 0.0
        weight = 0.0
        for c in range(N_AGENTS):
            n = pool[c] - (1 if c == a else 0)
            if n <= 0 or c == a:
                continue
            v_up = split_value(g, side, c, a)
            v_down = split_value(g, side, a, c)
            acc += n * (0.55 * min(v_up, v_down) + 0.45 * (v_up + v_down) / 2)
            weight += n
        scores.append(acc / weight if weight else 0.5)
    return scores


MARKET_PRIOR = {
    "base": [0.25, 0.45, 0.2, 0.2, 0.15, 0.4, 0.2, 0.3, 0.15, 0.2, 0.3, 0.25, 0.2, 0.25, 0.3],
}


def market_score(g: Game, player: int, card: int) -> float:
    side = g.side_of[player]
    op = 1 - side
    tab, tab_op = g.tableau[side], g.tableau[op]
    hand = g.hands[player]
    s = MARKET_PRIOR["base"][card]
    if card == SUPERCOMPUTER:
        s += 0.3 + 0.15 * tab[CODEBREAKER]
    elif card == LEADER:
        s += 0.25 * tab[DAREDEVIL] + (0.6 if tab[DAREDEVIL] == 2 else 0)
    elif card == MASTERPLAN:
        distinct = sum(1 for n in tab if n)
        s += max(0.0, (distinct - 3) * 0.2)
    elif card == SINISTER_TWIN:
        s += 0.4 if tab[DOUBLE_AGENT] == 1 else (-0.1 if tab[DOUBLE_AGENT] >= 2 else 0.1)
    elif card == WATCHTOWER:
        s += 0.15
    elif card == SECURITY:
        s += 0.1
    elif card == TRUCK:
        if distance(g.pos[0], g.pos[1], side) == 1:
            s += 3.0
    elif card == BRAINWASHING:
        if tab_op[CODEBREAKER] >= 2 or tab_op[DAREDEVIL] >= 3:
            s += 1.0
        s += 0.1 * sum(1 for n in tab_op if n)
    elif card == OUTPOST:
        if SENTINEL in hand:
            s += 0.2 + (0.8 if tab[SENTINEL] == 2 else 0.3 if tab[SENTINEL] == 1 else 0)
        else:
            s -= 0.2
    elif card == SMOKE_SCREEN:
        s += 0.05
    elif card == DOUBLE_TROUBLE:
        if any(hand.count(c) >= 2 for c in set(hand)):
            s += 0.3
        else:
            s -= 0.2
    elif card == SECRET_RECRUIT:
        if any(tab[c] == 0 for c in hand):
            s += 0.3
    elif card == SPYCATION and tab[DOUBLE_AGENT] == 2:
        s += 0.6
    return s


def choice_option(g: Game, player: int, options: list[int]) -> int:
    ch = g.choice
    assert ch is not None
    side = g.side_of[player]
    stage = ch["stage"]
    if stage == "steal":
        tab_op = g.tableau[1 - side]

        def harm(c: int) -> float:
            if c == CODEBREAKER and tab_op[c] >= 2:
                return 10.0
            if c == DAREDEVIL:
                return -2.0 if tab_op[c] == 2 else 0.5
            return tab_op[c] + 0.3 * abs(g.move_value(1 - side, c, tab_op[c] + 1))

        return max(options, key=harm)
    if stage == "spy_recruit":
        agent = ch["agent"]
        value = card_value(g, side, agent, g.tableau[side][agent] + 1)
        return 1 if value > 0 else 0
    if stage == "spy_pick":
        tab = g.tableau[side]
        return max(options, key=lambda c: card_value(g, side, c, tab[c]) - (0.5 if c == CODEBREAKER else 0))
    tab = g.tableau[side]
    return max(options, key=lambda c: card_value(g, side, c, tab[c] + 1))


def heuristic_action(g: Game, player: int, rng: random.Random, noise: float = 0.0) -> Action:
    legal = g.legal(player)
    if len(legal) == 1:
        return legal[0]
    phase = g.phase
    if phase == Phase.PLAY:
        plays = [a for a in legal if a[0] == "play"]
        scores = play_scores(g, player, plays)
        if noise:
            scores = [s + rng.gauss(0, noise) for s in scores]
        return plays[max(range(len(plays)), key=scores.__getitem__)]
    if phase == Phase.RECRUIT:
        up, down = recruit_scores(g, player)
        if noise:
            up += rng.gauss(0, noise)
            down += rng.gauss(0, noise)
        return ("recruit", 0 if up >= down else 1)
    if phase == Phase.MARKET:
        best = max(range(len(g.supply)), key=lambda i: market_score(g, player, g.supply[i]) + rng.random() * 0.05)
        return ("market", best)
    if phase == Phase.CHOICE:
        return ("choose", choice_option(g, player, [a[1] for a in legal]))
    return rng.choice(legal)
