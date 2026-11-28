"""Alpha-beta search over the engine's own move generator.

Negamax with iterative deepening, a transposition table (Zobrist hashes), killer moves and a capture-only
quiescence search. The evaluation is incremental (updated on every cell change) and antisymmetric:

    1000 · (rival marbles out − own marbles out)
  +   W_RING · (rival distance from the centre − own distance)   (summed over the marbles on the board)
  +   W_ADJ  · (own touching pairs − rival touching pairs)        (cohesion: a tight group is hard to push)

A bot sees only the `View` (the position); there is no hidden information in this game.
"""

from __future__ import annotations

import random
import time

from sumo.bots.base import Bot
from sumo.game.board import N_CELLS, NEIGHBOR, RING
from sumo.game.engine import EMPTY, TO_WIN, Move, Mv, View, gen_moves, marbles_of

WIN = 1_000_000
W_OUT = 1000
W_RING = 12
W_ADJ = 4
INF = 10 * WIN

_zrng = random.Random(20261128)
ZOBRIST = [[_zrng.getrandbits(64) for _ in range(2)] for _ in range(N_CELLS)]
Z_SIDE = _zrng.getrandbits(64)
EXACT, LOWER, UPPER = 0, 1, 2


class Timeout(Exception):
    pass


def gen_captures(cells: list[int], side: int) -> list[Mv]:
    """Only the inline pushes that push a rival marble out."""
    opp = 1 - side
    nbr = NEIGHBOR
    out: list[Mv] = []
    for m in range(N_CELLS):
        if cells[m] != side:
            continue
        for d in range(6):
            c = nbr[m][d]
            k = 1
            while c != -1 and cells[c] == side:
                k += 1
                if k > 3:
                    break
                c = nbr[c][d]
            if k > 3 or k == 1 or c == -1 or cells[c] != opp:
                continue
            j = 1
            e = nbr[c][d]
            while e != -1 and cells[e] == opp and j < k:
                j += 1
                e = nbr[e][d]
            if j < k and e == -1:
                out.append((m, k, d, -1, j, True))
    return out


class Searcher:
    """A mutable position with incremental evaluation terms, plus the search itself."""

    def __init__(self, view: View, deadline: float | None, rng: random.Random) -> None:
        self.cells = list(view.cells)
        self.out = list(view.out)
        self.ring = [0, 0]
        self.adj = [0, 0]
        self.hash = 0
        self.deadline = deadline
        self.rng = rng
        self.nodes = 0
        self.tt: dict[int, tuple[int, int, int, Mv | None]] = {}
        self.killers: list[list[Mv | None]] = [[None, None] for _ in range(64)]
        for c, v in enumerate(self.cells):
            if v != EMPTY:
                self.ring[v] += RING[c]
                self.hash ^= ZOBRIST[c][v]
                for d in range(3):
                    n = NEIGHBOR[c][d]
                    if n != -1 and self.cells[n] == v:
                        self.adj[v] += 1

    # ------------------------------------------------------------------ position
    def _set(self, c: int, v: int) -> None:
        cells = self.cells
        old = cells[c]
        if old == v:
            return
        if old != EMPTY:
            self.ring[old] -= RING[c]
            self.hash ^= ZOBRIST[c][old]
            for n in NEIGHBOR[c]:
                if n != -1 and cells[n] == old:
                    self.adj[old] -= 1
        cells[c] = v
        if v != EMPTY:
            self.ring[v] += RING[c]
            self.hash ^= ZOBRIST[c][v]
            for n in NEIGHBOR[c]:
                if n != -1 and cells[n] == v:
                    self.adj[v] += 1

    def make(self, mv: Mv, side: int) -> list[tuple[int, int]]:
        tail, k, d, axis, j, cap = mv
        nbr = NEIGHBOR
        cells = self.cells
        if axis == -1:
            head = tail
            for _ in range(k):
                head = nbr[head][d]
            changes = [(tail, EMPTY), (head, side)]
            if j:
                if cap:
                    self.out[1 - side] += 1
                else:
                    e = head
                    for _ in range(j):
                        e = nbr[e][d]
                    changes.append((e, 1 - side))
        else:
            group = marbles_of(mv)
            changes = [(x, EMPTY) for x in group] + [(nbr[x][d], side) for x in group]
        undo = [(c, cells[c]) for c, _ in changes]
        for c, v in changes:
            self._set(c, v)
        return undo

    def unmake(self, mv: Mv, side: int, undo: list[tuple[int, int]]) -> None:
        for c, v in reversed(undo):
            self._set(c, v)
        if mv[5]:
            self.out[1 - side] -= 1

    def evaluate(self, side: int) -> int:
        o = 1 - side
        return (
            W_OUT * (self.out[o] - self.out[side])
            + W_RING * (self.ring[o] - self.ring[side])
            + W_ADJ * (self.adj[side] - self.adj[o])
        )

    # ------------------------------------------------------------------ search
    def _tick(self) -> None:
        self.nodes += 1
        if self.deadline is not None and self.nodes & 511 == 0 and time.perf_counter() > self.deadline:
            raise Timeout

    def quiesce(self, alpha: int, beta: int, side: int, ply: int, depth: int) -> int:
        self._tick()
        stand = self.evaluate(side)
        if depth == 0 or stand >= beta:
            return stand
        alpha = max(alpha, stand)
        for mv in gen_captures(self.cells, side):
            undo = self.make(mv, side)
            if self.out[1 - side] >= TO_WIN:
                score = WIN - ply
            else:
                score = -self.quiesce(-beta, -alpha, 1 - side, ply + 1, depth - 1)
            self.unmake(mv, side, undo)
            if score >= beta:
                return score
            alpha = max(alpha, score)
        return alpha

    def _ordered(self, moves: list[Mv], best: Mv | None, ply: int) -> list[Mv]:
        killers = self.killers[ply] if ply < len(self.killers) else [None, None]
        nbr = NEIGHBOR

        def key(mv: Mv) -> int:
            if mv == best:
                return -100_000
            if mv[5]:
                return -50_000
            if mv[4]:
                return -20_000 - mv[4]
            if mv == killers[0] or mv == killers[1]:
                return -10_000
            tail, k, d, axis, _, _ = mv
            if axis == -1:
                head = tail
                for _ in range(k):
                    head = nbr[head][d]
                return RING[head] - RING[tail]
            return sum(RING[nbr[x][d]] - RING[x] for x in marbles_of(mv))

        return sorted(moves, key=key)

    def negamax(self, depth: int, alpha: int, beta: int, side: int, ply: int) -> int:
        if depth <= 0:
            return self.quiesce(alpha, beta, side, ply, 3)
        self._tick()
        key = self.hash ^ (Z_SIDE if side else 0)
        entry = self.tt.get(key)
        best_mv: Mv | None = None
        if entry is not None:
            e_depth, flag, value, best_mv = entry
            if e_depth >= depth:
                if flag == EXACT:
                    return value
                if flag == LOWER and value >= beta:
                    return value
                if flag == UPPER and value <= alpha:
                    return value
        moves = gen_moves(self.cells, side)
        if not moves:
            return 0
        a0 = alpha
        best = -INF
        best_found: Mv | None = None
        for mv in self._ordered(moves, best_mv, ply):
            undo = self.make(mv, side)
            if self.out[1 - side] >= TO_WIN:
                score = WIN - ply
            else:
                score = -self.negamax(depth - 1, -beta, -alpha, 1 - side, ply + 1)
            self.unmake(mv, side, undo)
            if score > best:
                best = score
                best_found = mv
            if score > alpha:
                alpha = score
            if alpha >= beta:
                if not mv[4] and ply < len(self.killers):
                    ks = self.killers[ply]
                    if ks[0] != mv:
                        ks[1] = ks[0]
                        ks[0] = mv
                break
        flag = UPPER if best <= a0 else LOWER if best >= beta else EXACT
        self.tt[key] = (depth, flag, best, best_found)
        return best

    def root(self, depth: int, side: int, order: list[Mv], spread: int) -> list[tuple[int, Mv]]:
        """Scores of the root moves at `depth` (exact for the best ones, within `spread` of the best)."""
        scored: list[tuple[int, Mv]] = []
        best = -INF
        for mv in order:
            undo = self.make(mv, side)
            if self.out[1 - side] >= TO_WIN:
                score = WIN
            else:
                # moves that can't come within `spread` of the best only need a bound
                alpha = best - spread - 1
                score = -self.negamax(depth - 1, -INF, -alpha, 1 - side, 1)
            self.unmake(mv, side, undo)
            scored.append((score, mv))
            best = max(best, score)
        scored.sort(key=lambda x: -x[0])
        return scored


class SearchBot(Bot):
    """depth: fixed search depth, or None for iterative deepening within `budget` seconds.
    spread: plays a random move among those scoring within `spread` points of the best (variety, weaker play)."""

    def __init__(
        self,
        seed: int | None = None,
        depth: int | None = None,
        budget: float | None = 1.5,
        spread: int = 0,
        max_depth: int = 8,
    ) -> None:
        super().__init__(seed)
        self.depth = depth
        self.budget = budget
        self.spread = spread
        self.max_depth = max_depth
        self.last_depth = 0

    def act(self, view: View) -> Move:
        moves = gen_moves(list(view.cells), view.side)
        if not moves:
            raise RuntimeError("no legal move")
        if len(moves) == 1:
            return Move.of(moves[0])
        started = time.perf_counter()
        deadline = None if self.depth is not None or self.budget is None else started + self.budget
        s = Searcher(view, None, self.rng)
        self.rng.shuffle(moves)  # equal moves: no fixed preference
        order = s._ordered(moves, None, 0)
        scored = s.root(1, view.side, order, self.spread)
        self.last_depth = 1
        target = self.depth if self.depth is not None else self.max_depth
        s.deadline = deadline
        for depth in range(2, target + 1):
            if deadline is not None and time.perf_counter() > started + self.budget * 0.45:  # type: ignore[operator]
                break  # the next iteration would not finish in time
            try:
                scored = s.root(depth, view.side, [mv for _, mv in scored], self.spread)
            except Timeout:
                break
            self.last_depth = depth
            if scored[0][0] >= WIN - 64:
                break
        best = scored[0][0]
        if best >= WIN - 64:
            near = [mv for score, mv in scored if score == best]
        else:
            near = [mv for score, mv in scored if score >= best - self.spread]
        return Move.of(self.rng.choice(near))
