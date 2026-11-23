"""Head-to-head bot comparison with swapped seats: uv run python scripts/duel.py A B N [advanced] [k=v ...]"""

from __future__ import annotations

import sys
import time
from concurrent.futures import ProcessPoolExecutor

from avenue.bots import heuristic as H
from avenue.bots import make_bot
from avenue.runner import play_game

NEW = [0.379, 0.241, 0.610, -0.602, 0.5, -0.380, 0.168, 0.313, -0.059, -0.044, -0.020, 0.396]
OLD = [0.30, 0.20, 0.75, -0.70, 0.75, -0.10, 0.25, 0.12, -0.05, 0.0, 0.0, 0.0]


class Weighted:
    """Plays with its own evaluation weights (swapped in around each decision)."""

    def __init__(self, bot, weights: list[float]) -> None:
        self.bot = bot
        self.weights = weights

    def act(self, view, player):
        saved = H.WEIGHTS[:]
        H.WEIGHTS[:] = self.weights
        try:
            return self.bot.act(view, player)
        finally:
            H.WEIGHTS[:] = saved


def one(args: tuple[str, str, int, bool, dict[str, float], dict[str, float]]) -> tuple[int, str]:
    a, b, seed, adv, ka, kb = args
    swap = seed % 2
    keys = [b, a] if swap else [a, b]
    kws = [kb, ka] if swap else [ka, kb]
    bots = []
    for i, (k, kw) in enumerate(zip(keys, kws, strict=True)):
        kw = dict(kw)
        weights = {1.0: NEW, 0.0: OLD}.get(kw.pop("w", -1.0))
        bot = make_bot(k, seed * 7 + i, **kw)
        bots.append(Weighted(bot, weights) if weights else bot)
    g = play_game(bots, advanced=adv, seed=seed // 2)
    assert g.result is not None
    winner = g.result["winner"]
    a_won = int((winner == 0) != bool(swap))
    return a_won, g.result["reasons"][0]


def parse(xs: list[str]) -> dict[str, float]:
    return {k: float(v) for k, v in (x.split("=") for x in xs)}


if __name__ == "__main__":
    a, b, n = sys.argv[1], sys.argv[2], int(sys.argv[3])
    adv = len(sys.argv) > 4 and sys.argv[4] == "advanced"
    rest = sys.argv[5 if adv else 4 :]
    ka = parse([x[2:] for x in rest if x.startswith("a.")])
    kb = parse([x[2:] for x in rest if x.startswith("b.")])
    t = time.time()
    with ProcessPoolExecutor(8) as ex:
        res = list(ex.map(one, [(a, b, s, adv, ka, kb) for s in range(n)], chunksize=2))
    wins = sum(r[0] for r in res)
    reasons: dict[str, int] = {}
    for _, r in res:
        reasons[r] = reasons.get(r, 0) + 1
    se = (wins / n * (1 - wins / n) / n) ** 0.5
    print(f"{a} vs {b}: {wins}/{n} = {wins / n:.3f} ± {se:.3f}  ({time.time() - t:.0f}s) {reasons}")
