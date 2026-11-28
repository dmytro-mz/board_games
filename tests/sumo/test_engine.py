"""Rules engine: the move generator against a brute-force reference, every push rule, captures, endings."""

from __future__ import annotations

import itertools
import random

import pytest

from sumo.game.board import CELLS, INDEX, LAYOUTS, N_CELLS, NEIGHBOR, RING, cell, cells, name
from sumo.game.engine import (
    EMPTY,
    MARBLES,
    BadAction,
    Game,
    IllegalMove,
    Move,
    apply,
    gen_moves,
    marbles_of,
    undo,
)


def reference_moves(board: list[int], side: int) -> set[tuple[tuple[int, ...], int]]:
    """Every legal move, straight from the rules (slow and obvious)."""
    opp = 1 - side
    groups: set[tuple[int, ...]] = set()
    for c in range(N_CELLS):
        if board[c] != side:
            continue
        groups.add((c,))
        for a in range(6):
            line = [c]
            for _ in range(2):
                n = NEIGHBOR[line[-1]][a]
                if n == -1 or board[n] != side:
                    break
                line.append(n)
                groups.add(tuple(sorted(line)))
    found: set[tuple[tuple[int, ...], int]] = set()
    for g in groups:
        for d in range(6):
            along = len(g) == 1 or any(NEIGHBOR[x][d] in g for x in g)
            if along:
                head = next(x for x in g if NEIGHBOR[x][d] not in g)
                c = NEIGHBOR[head][d]
                if c == -1 or board[c] == side:
                    continue
                if board[c] == EMPTY:
                    found.add((g, d))
                    continue
                run = 0
                while c != -1 and board[c] == opp:
                    run += 1
                    c = NEIGHBOR[c][d]
                if run < len(g) and (c == -1 or board[c] == EMPTY):
                    found.add((g, d))
            elif all(NEIGHBOR[x][d] != -1 and board[NEIGHBOR[x][d]] == EMPTY for x in g):
                found.add((g, d))
    return found


def generated(board: list[int], side: int) -> set[tuple[tuple[int, ...], int]]:
    moves = gen_moves(board, side)
    keys = [(tuple(sorted(marbles_of(mv))), mv[2]) for mv in moves]
    assert len(keys) == len(set(keys)), "duplicate moves"
    return set(keys)


BLACK_FILL = "A1 A2 A3 A4 A5 B1 B2 B3 B4 B5 B6 C1 C2 C3 C4 C5 C6 C7"
WHITE_FILL = "I5 I6 I7 I8 I9 H4 H5 H6 H7 H8 H9 G3 G4 G5 G6 G7 G8 G9"


def position(black: str, white: str, current: int = 0, out: tuple[int, int] = (0, 0)) -> Game:
    """A game with these marbles, `out` of each team already pushed out, and the rest of each team parked on its
    back rows (wherever those cells are free)."""
    g = Game()
    g.cells = [EMPTY] * N_CELLS
    g.ids = [None] * N_CELLS
    groups = [cells(black) if black else [], cells(white) if white else []]
    used = set(groups[0] + groups[1])
    for side, fill in enumerate((BLACK_FILL, WHITE_FILL)):
        free = [c for c in cells(fill) if c not in used]
        groups[side] += free[: MARBLES - out[side] - len(groups[side])]
        used |= set(groups[side])
    for side, group in enumerate(groups):
        assert len(group) == MARBLES - out[side]
        for i, c in enumerate(group):
            g.cells[c] = side
            g.ids[c] = side * MARBLES + i
        g.out[side] = out[side]
        g.lost[side] = [side * MARBLES + i for i in range(len(group), MARBLES)]
    g.current = current
    g.check()
    return g


def on(g: Game, side: int, labels: str) -> list[str]:
    """Which of these cells hold a marble of `side`."""
    return [x for x in labels.split() if g.cells[cell(x)] == side]


def move(labels: str, d: str) -> Move:
    dirs = {"E": 0, "NE": 1, "NW": 2, "W": 3, "SW": 4, "SE": 5}
    return Move(tuple(sorted(cells(labels))), dirs[d])


# ------------------------------------------------------------------ geometry
def test_board_has_61_cells_and_symmetric_neighbours() -> None:
    assert N_CELLS == 61
    assert sum(1 for r in RING if r == 4) == 24
    for c in range(N_CELLS):
        for d in range(6):
            n = NEIGHBOR[c][d]
            if n != -1:
                assert NEIGHBOR[n][(d + 3) % 6] == c
    assert name(INDEX[(0, 0)]) == "E5"
    assert {name(cell(x)) for x in ("A1", "A5", "I5", "I9", "E1", "E9")} == {"A1", "A5", "I5", "I9", "E1", "E9"}
    assert CELLS[cell("A1")] == (-4, 4)


@pytest.mark.parametrize("key", list(LAYOUTS))
def test_layouts_have_fourteen_marbles_each_and_mirror_each_other(key: str) -> None:
    lay = LAYOUTS[key]
    assert len(lay.black) == len(set(lay.black)) == MARBLES
    assert len(lay.white) == len(set(lay.white)) == MARBLES
    assert not set(lay.black) & set(lay.white)

    def images(group: tuple[int, ...]) -> list[set[int]]:
        """`group` under each of the hexagon's 12 symmetries (cube coordinates: permute, maybe negate)."""
        out = []
        for perm in itertools.permutations(range(3)):
            for sign in (1, -1):
                img = set()
                for c in group:
                    q, r = CELLS[c]
                    cube = (q, -q - r, r)
                    x, _, z = (sign * cube[i] for i in perm)
                    img.add(INDEX[(x, z)])
                out.append(img)
        return out

    assert set(lay.white) in images(lay.black)  # the same shape for both colours
    g = Game(key)
    g.check()
    assert len(gen_moves(g.cells, 0)) == len(gen_moves(g.cells, 1))


def test_classic_opening_has_44_moves() -> None:
    g = Game("classic")
    assert len(g.legal_moves()) == 44
    assert generated(g.cells, 0) == reference_moves(g.cells, 0)


# ------------------------------------------------------------------ generator vs reference
def test_generator_matches_the_rules_in_random_games() -> None:
    rng = random.Random(7)
    checked = 0
    for layout in LAYOUTS:
        for _ in range(4):
            g = Game(layout)
            for _ in range(160):
                if g.over:
                    break
                assert generated(g.cells, g.current) == reference_moves(g.cells, g.current)
                assert generated(g.cells, 1 - g.current) == reference_moves(g.cells, 1 - g.current)
                moves = g.legal_internal()
                pushes = [mv for mv in moves if mv[4]]
                mv = rng.choice(pushes) if pushes and rng.random() < 0.7 else rng.choice(moves)
                g.step(g.current, Move.of(mv))
                g.check()
                checked += 1
    assert checked > 1000


def test_apply_and_undo_round_trip() -> None:
    rng = random.Random(3)
    g = Game("daisy")
    for _ in range(300):
        if g.over:
            break
        before = list(g.cells)
        for mv in gen_moves(g.cells, g.current):
            apply(g.cells, mv, g.current)
            undo(g.cells, mv, g.current)
            assert g.cells == before
        g.step(g.current, Move.of(rng.choice(g.legal_internal())))


# ------------------------------------------------------------------ moves and pushes
def test_inline_and_sideways_moves() -> None:
    g = position("E3 E4 E5", "")
    g.step(0, move("E3 E4 E5", "E"))
    assert on(g, 0, "E3 E4 E5 E6") == ["E4", "E5", "E6"]
    g = position("E3 E4 E5", "")
    g.step(0, move("E3 E4 E5", "NE"))
    assert on(g, 0, "E3 E4 E5 F4 F5 F6") == ["F4", "F5", "F6"]
    g.check()


@pytest.mark.parametrize(
    ("black", "white", "labels", "d", "legal"),
    [
        ("E4 E5", "E6", "E4 E5", "E", True),  # 2 push 1
        ("E3 E4 E5", "E6", "E3 E4 E5", "E", True),  # 3 push 1
        ("E3 E4 E5", "E6 E7", "E3 E4 E5", "E", True),  # 3 push 2
        ("E4 E5", "E6 E7", "E4 E5", "E", False),  # 2 against 2
        ("E3 E4 E5", "E6 E7 E8", "E3 E4 E5", "E", False),  # 3 against 3
        ("E5", "E6", "E5", "E", False),  # one never pushes
        ("E4 E5 E7", "E6", "E4 E5", "E", False),  # own marble behind the rival
        ("E4 E5", "E6 E8", "E4 E5", "E", True),  # an empty cell behind the pushed marble is all it needs
        ("E3 E4 E5", "E6 E8", "E3 E4 E5", "E", True),
        ("E4 E5", "F5 F6", "E4 E5", "NE", False),  # sideways never pushes
        ("E8 E9", "A1", "E8 E9", "E", False),  # own marbles never leave the ring
        ("E9", "A1", "E9", "E", False),
        ("E1 E2 E3 E4", "E5", "E2 E3 E4", "E", True),  # the front three of four may push
    ],
)
def test_push_rules(black: str, white: str, labels: str, d: str, legal: bool) -> None:
    g = position(black, white)
    assert (g.find(move(labels, d)) is not None) == legal


def test_four_in_a_row_cannot_move_as_one() -> None:
    g = position("E1 E2 E3 E4", "")
    assert g.find(Move(tuple(sorted(cells("E1 E2 E3 E4")[:3])), 0)) is None  # the back three: the fourth is in the way
    with pytest.raises(BadAction):
        Move.from_json({"type": "move", "marbles": cells("E1 E2 E3 E4"), "dir": 0})


def test_push_moves_the_rival_and_ids_follow() -> None:
    g = position("E3 E4 E5", "E6 E7")
    ids = {c: g.ids[c] for c in cells("E3 E4 E5 E6 E7")}
    events = g.step(0, move("E3 E4 E5", "E"))
    ev = events[0]
    assert ev["pushed"] == cells("E6 E7") and ev["out"] is None and ev["inline"]
    assert on(g, 1, "E6 E7 E8") == ["E7", "E8"]
    assert g.ids[cell("E8")] == ids[cell("E7")] and g.ids[cell("E7")] == ids[cell("E6")]
    assert g.ids[cell("E4")] == ids[cell("E3")] and g.ids[cell("E3")] is None
    g.check()


def test_push_out_of_the_ring_counts() -> None:
    g = position("E7 E8", "E9")
    out_id = g.ids[cell("E9")]
    events = g.step(0, move("E7 E8", "E"))
    assert events[0]["out"] == cell("E9")
    assert [p for p in events[0]["paths"] if p[2] is None] == [[out_id, cell("E9"), None]]
    assert g.out == [0, 1] and g.lost[1] == [out_id]
    g.check()


def test_sixth_marble_out_wins() -> None:
    g = position("E6 E7 E8", "E9", out=(0, 5))
    events = g.step(0, move("E6 E7 E8", "E"))
    assert events[-1] == {"kind": "game_over", "winner": 0, "reason": "push", "out": [0, 6]}
    assert g.over and g.result is not None and g.result.winner == 0
    assert g.legal_moves() == []
    with pytest.raises(IllegalMove):
        g.step(1, move("A1", "E"))


def test_turns_alternate_and_out_of_turn_is_rejected() -> None:
    g = Game()
    with pytest.raises(IllegalMove):
        g.step(1, g.legal_moves()[0])
    g.step(0, g.legal_moves()[0])
    assert g.current == 1 and g.turn == 1
    with pytest.raises(IllegalMove):
        g.step(1, move("A1", "E"))  # a black marble


def test_move_limit_ends_the_game() -> None:
    g = Game(move_limit=2)
    rng = random.Random(1)
    for _ in range(4):
        g.step(g.current, rng.choice(g.legal_moves()))
    assert g.over and g.result is not None and g.result.reason == "limit"
    assert g.result.winner is None  # nobody lost a marble in four opening moves
    g = position("E7 E8", "E9")
    g.move_limit = 1
    g.step(0, move("E7 E8", "E"))
    g.step(1, move("G3", "SW"))
    assert g.result is not None and g.result.winner == 0 and g.result.reason == "limit"


def test_resign() -> None:
    g = Game()
    events = g.resign(0)
    assert events[0] == {"kind": "resign", "seat": 0}
    assert g.result is not None and g.result.winner == 1 and g.result.reason == "resign"
    with pytest.raises(IllegalMove):
        g.resign(1)


@pytest.mark.parametrize(
    "data",
    [
        None,
        "move",
        {"type": "place"},
        {"marbles": [], "dir": 0},
        {"marbles": [1, 2, 3, 4], "dir": 0},
        {"marbles": [1, 1], "dir": 0},
        {"marbles": [99], "dir": 0},
        {"marbles": [True], "dir": 0},
        {"marbles": [1], "dir": 6},
        {"marbles": [1], "dir": "0"},
        {"marbles": "1", "dir": 0},
    ],
)
def test_bad_actions(data: object) -> None:
    with pytest.raises(BadAction):
        Move.from_json(data)


def test_move_json_round_trip() -> None:
    m = Move.from_json({"type": "move", "marbles": [12, 3], "dir": 4})
    assert m == Move((3, 12), 4)
    assert Move.from_json(m.to_json()) == m
