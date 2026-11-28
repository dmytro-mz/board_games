"""Marble Sumo rules: 14 marbles a side on a 61-cell hexagon; push six of the rival's marbles off the edge.

A turn moves one, two or three own marbles that stand in a straight line, one step in one of the six directions:

- *inline* (along the line): the front marble steps forward and the others follow. Into an empty cell, or against
  rival marbles in the same line when the mover is stronger: 2 push 1, 3 push 1 or 2. The pushed marbles must have
  an empty cell or the edge behind them (never an own marble); a rival marble pushed over the edge is out.
- *sideways* (two or three marbles, any of the other four directions): every marble steps into an empty cell.
  Sideways moves never push.
A marble may not move off the board by itself. Black moves first. The first to push out six rival marbles wins.
An optional move limit ends the game after that many moves each: fewer marbles lost wins, else it is a draw.

The move generator works on a plain list of cells (EMPTY / 0 / 1), so the bots search with the same code
(`gen_moves`, `apply`, `undo`). Internal moves are tuples `Mv = (tail, k, d, axis, j, cap)`:
  inline:   axis = -1; marbles tail, tail+d, … (k of them) step in d; j rival marbles are pushed, cap: one goes out
  sideways: axis = 0..2 (E, NE, NW); marbles tail, tail+axis, … step in d; j = 0, cap = False
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from sumo.game.board import DEFAULT_LAYOUT, LAYOUTS, N_CELLS, NEIGHBOR, name

EMPTY = -1
MARBLES = 14
TO_WIN = 6
SIDE_NAMES = ("Black", "White")

Mv = tuple[int, int, int, int, int, bool]
Event = dict[str, Any]


class IllegalMove(Exception):
    pass


class BadAction(Exception):
    pass


# ------------------------------------------------------------------ fast move generation (shared with the bots)
def gen_moves(cells: list[int], side: int) -> list[Mv]:
    """Every legal move of `side`, pushes first."""
    opp = 1 - side
    pushes: list[Mv] = []
    quiet: list[Mv] = []
    nbr = NEIGHBOR
    for m in range(N_CELLS):
        if cells[m] != side:
            continue
        row = nbr[m]
        for d in range(6):
            # inline, with m as the tail
            c = row[d]
            k = 1
            while c != -1 and cells[c] == side:
                k += 1
                if k > 3:
                    break
                c = nbr[c][d]
            if k <= 3 and c != -1:
                v = cells[c]
                if v == EMPTY:
                    quiet.append((m, k, d, -1, 0, False))
                elif k > 1:  # v == opp: a lone marble never pushes
                    j = 1
                    e = nbr[c][d]
                    while e != -1 and cells[e] == opp and j < k:
                        j += 1
                        e = nbr[e][d]
                    if j < k and (e == -1 or cells[e] == EMPTY):
                        pushes.append((m, k, d, -1, j, e == -1))
            # sideways groups along the axes E, NE, NW (d < 3 doubles as the axis), every other direction
            if d < 3:
                b = row[d]
                if b == -1 or cells[b] != side:
                    continue
                c3 = nbr[b][d]
                groups = [(m, b)]
                if c3 != -1 and cells[c3] == side:
                    groups.append((m, b, c3))
                for g in groups:
                    for md in range(6):
                        if md == d or md == d + 3:
                            continue
                        ok = True
                        for x in g:
                            t = nbr[x][md]
                            if t == -1 or cells[t] != EMPTY:
                                ok = False
                                break
                        if ok:
                            quiet.append((m, len(g), md, d, 0, False))
    pushes.sort(key=lambda mv: (not mv[5], -mv[4]))
    return pushes + quiet


def marbles_of(mv: Mv) -> list[int]:
    tail, k, d, axis, _, _ = mv
    step = d if axis == -1 else axis
    out = [tail]
    for _ in range(k - 1):
        out.append(NEIGHBOR[out[-1]][step])
    return out


def apply(cells: list[int], mv: Mv, side: int) -> None:
    """Make the move in place (no legality check)."""
    tail, k, d, axis, j, cap = mv
    nbr = NEIGHBOR
    if axis == -1:
        head = tail
        for _ in range(k):
            head = nbr[head][d]
        cells[tail] = EMPTY
        cells[head] = side
        if j:
            e = head
            for _ in range(j):
                e = nbr[e][d]
            if not cap:
                cells[e] = 1 - side
        return
    group = marbles_of(mv)
    for x in group:
        cells[x] = EMPTY
    for x in group:
        cells[nbr[x][d]] = side


def undo(cells: list[int], mv: Mv, side: int) -> None:
    tail, k, d, axis, j, cap = mv
    nbr = NEIGHBOR
    if axis == -1:
        head = tail
        for _ in range(k):
            head = nbr[head][d]
        cells[tail] = side
        if j:
            cells[head] = 1 - side
            if not cap:
                e = head
                for _ in range(j):
                    e = nbr[e][d]
                cells[e] = EMPTY
        else:
            cells[head] = EMPTY
        return
    group = marbles_of(mv)
    for x in group:
        cells[nbr[x][d]] = EMPTY
    for x in group:
        cells[x] = side


# ------------------------------------------------------------------ public moves
@dataclass(frozen=True)
class Move:
    """What a player sends: the marbles that move (in any order) and the direction (0..5, see board.DIRS)."""

    marbles: tuple[int, ...]
    dir: int

    @staticmethod
    def of(mv: Mv) -> Move:
        return Move(tuple(sorted(marbles_of(mv))), mv[2])

    def to_json(self) -> dict[str, Any]:
        return {"type": "move", "marbles": list(self.marbles), "dir": self.dir}

    @staticmethod
    def from_json(data: object) -> Move:
        if not isinstance(data, dict) or data.get("type", "move") != "move":
            raise BadAction("invalid action")
        marbles, d = data.get("marbles"), data.get("dir")
        if not isinstance(marbles, list) or not 1 <= len(marbles) <= 3:
            raise BadAction("pick one to three marbles")
        if any(not isinstance(x, int) or isinstance(x, bool) or not 0 <= x < N_CELLS for x in marbles):
            raise BadAction("no such cell")
        if not isinstance(d, int) or isinstance(d, bool) or not 0 <= d < 6:
            raise BadAction("no such direction")
        if len(set(marbles)) != len(marbles):
            raise BadAction("a marble was picked twice")
        return Move(tuple(sorted(marbles)), d)


@dataclass(frozen=True)
class Result:
    winner: int | None  # None: a draw
    reason: str  # "push" | "resign" | "limit"
    out: tuple[int, int]  # marbles each side lost


@dataclass(frozen=True)
class View:
    """Everything about a position (there is no hidden information): what a bot gets."""

    cells: tuple[int, ...]
    side: int  # the side to move
    out: tuple[int, int]
    turn: int
    move_limit: int


@dataclass
class Game:
    layout: str = DEFAULT_LAYOUT
    move_limit: int = 0  # moves per player, 0 = no limit
    cells: list[int] = field(default_factory=list)
    ids: list[int | None] = field(default_factory=list)  # marble id per cell (stable, for the client's animations)
    out: list[int] = field(default_factory=lambda: [0, 0])  # marbles each side lost
    lost: list[list[int]] = field(default_factory=lambda: [[], []])  # ids of the lost marbles, in order
    current: int = 0
    turn: int = 0  # moves played
    result: Result | None = None
    last: Event | None = None  # the last move event

    def __post_init__(self) -> None:
        if self.layout not in LAYOUTS:
            raise ValueError(f"unknown layout {self.layout!r}")
        if not self.cells:
            lay = LAYOUTS[self.layout]
            self.cells = [EMPTY] * N_CELLS
            self.ids = [None] * N_CELLS
            for side, group in enumerate((lay.black, lay.white)):
                for i, c in enumerate(group):
                    self.cells[c] = side
                    self.ids[c] = side * MARBLES + i

    @property
    def over(self) -> bool:
        return self.result is not None

    def view(self) -> View:
        return View(tuple(self.cells), self.current, (self.out[0], self.out[1]), self.turn, self.move_limit)

    def legal_internal(self) -> list[Mv]:
        return [] if self.over else gen_moves(self.cells, self.current)

    def legal_moves(self) -> list[Move]:
        return [Move.of(mv) for mv in self.legal_internal()]

    def find(self, move: Move) -> Mv | None:
        for mv in self.legal_internal():
            if mv[2] == move.dir and tuple(sorted(marbles_of(mv))) == move.marbles:
                return mv
        return None

    def step(self, seat: int, move: Move) -> list[Event]:
        if self.over:
            raise IllegalMove("The game is over")
        if seat != self.current:
            raise IllegalMove("It's not your turn")
        mv = self.find(move)
        if mv is None:
            raise IllegalMove("That move is not allowed")
        _, _, d, axis, j, cap = mv
        group = marbles_of(mv)
        paths: list[list[int | None]] = []  # [marble id, from cell, to cell or None]
        nbr = NEIGHBOR
        pushed: list[int] = []
        if axis == -1:
            line = list(group)
            c = nbr[group[-1]][d]
            for _ in range(j):
                pushed.append(c)
                line.append(c)
                c = nbr[c][d]
            moved = line
        else:
            moved = group
        new_ids = list(self.ids)
        for x in moved:
            new_ids[x] = None
        out_cell: int | None = None
        for x in moved:
            to = nbr[x][d]
            mid = self.ids[x]
            assert mid is not None
            paths.append([mid, x, to if to != -1 else None])
            if to == -1:
                out_cell = x
                self.lost[1 - seat].append(mid)
            else:
                new_ids[to] = mid
        apply(self.cells, mv, seat)
        self.ids = new_ids
        if cap:
            self.out[1 - seat] += 1
        event: Event = {
            "kind": "move",
            "seat": seat,
            "marbles": sorted(group),
            "dir": d,
            "inline": axis == -1,
            "pushed": pushed,
            "out": out_cell,
            "paths": paths,
        }
        events = [event]
        self.last = event
        self.turn += 1
        self.current = 1 - seat
        if self.out[1 - seat] >= TO_WIN:
            events.append(self._finish(seat, "push"))
        elif self.move_limit and self.turn >= 2 * self.move_limit:
            a, b = self.out
            events.append(self._finish(None if a == b else (0 if a < b else 1), "limit"))
        return events

    def resign(self, seat: int) -> list[Event]:
        if self.over:
            raise IllegalMove("The game is over")
        return [{"kind": "resign", "seat": seat}, self._finish(1 - seat, "resign")]

    def _finish(self, winner: int | None, reason: str) -> Event:
        self.result = Result(winner, reason, (self.out[0], self.out[1]))
        return {"kind": "game_over", "winner": winner, "reason": reason, "out": list(self.out)}

    def check(self) -> None:
        """Invariants: marble counts, ids follow the marbles, every id exactly once (on the board or lost)."""
        for side in (0, 1):
            on_board = sum(1 for v in self.cells if v == side)
            assert on_board + self.out[side] == MARBLES, (side, on_board, self.out)
            assert len(self.lost[side]) == self.out[side]
        seen: list[int] = []
        for c in range(N_CELLS):
            assert (self.cells[c] == EMPTY) == (self.ids[c] is None), name(c)
            mid = self.ids[c]
            if mid is not None:
                assert mid // MARBLES == self.cells[c], name(c)
                seen.append(mid)
        seen += self.lost[0] + self.lost[1]
        assert sorted(seen) == list(range(2 * MARBLES))
        assert all(m // MARBLES == side for side in (0, 1) for m in self.lost[side])
        assert max(self.out) <= TO_WIN


def describe(mv: Mv) -> str:
    """A short move notation for logs and tests: "C3-C5 NE", "A1 E", "B2-B4 x2"."""
    from sumo.game.board import DIR_NAMES

    group = sorted(marbles_of(mv))
    cells_txt = name(group[0]) if len(group) == 1 else f"{name(group[0])}-{name(group[-1])}"
    return f"{cells_txt} {DIR_NAMES[mv[2]]}"
