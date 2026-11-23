"""Fit the evaluation weights (bots/heuristic.py WEIGHTS) by logistic regression on self-play games.

uv run python scripts/fit_eval.py [--games 20000] [--advanced-share 0.5] [--search-games 0]
States are taken at the start of every turn, from both sides' point of view; the label is who won in the end.
"""

from __future__ import annotations

import argparse
import random
import time
from concurrent.futures import ProcessPoolExecutor

import numpy as np

from avenue.bots import HeuristicBot, SearchBot
from avenue.bots import heuristic as H
from avenue.game.engine import Game, Phase


def play(args: tuple[int, bool, bool]) -> list[tuple[list[float], int]]:
    seed, advanced, search = args
    rng = random.Random(seed)
    if search:
        bots = [SearchBot(seed=seed * 2 + i, budget=0.02, max_iters=10) for i in range(2)]
    else:
        bots = [HeuristicBot(seed * 2 + i, noise=rng.choice([0.0, 0.03, 0.08])) for i in range(2)]
    g = Game([0, 1], advanced=advanced, seed=seed, first=seed % 2)
    rows: list[tuple[list[float], int]] = []
    seen_turn = 0
    while g.result is None:
        if g.phase == Phase.PLAY and g.turn != seen_turn and g.up is None:
            seen_turn = g.turn
            for side in (0, 1):
                f = H.features(
                    g,
                    side,
                    g.distance(side),
                    g.tableau[side],
                    g.tableau[1 - side],
                    g.pos[side],
                    g.pos[1 - side],
                    g.active,
                )
                rows.append((f, side))
        p = g.waiting()[0]
        g.step(p, bots[p].act(g.redacted(p), p))
    winner = g.result["winner"]
    return [(f, int(side == winner)) for f, side in rows]


def fit(x: np.ndarray, y: np.ndarray, l2: float = 1.0, iters: int = 30) -> np.ndarray:
    w = np.zeros(x.shape[1])
    for _ in range(iters):  # Newton / IRLS
        p = 1 / (1 + np.exp(-(x @ w)))
        grad = x.T @ (p - y) + l2 * w
        hess = (x * (p * (1 - p))[:, None]).T @ x + l2 * np.eye(x.shape[1])
        w -= np.linalg.solve(hess, grad)
    return w


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--games", type=int, default=20000)
    ap.add_argument("--advanced-share", type=float, default=0.5)
    ap.add_argument("--search-games", type=int, default=0)
    args = ap.parse_args()
    t = time.time()
    jobs = [(s, s % 100 < args.advanced_share * 100, False) for s in range(args.games)]
    jobs += [(10**6 + s, s % 2 == 0, True) for s in range(args.search_games)]
    rows = []
    with ProcessPoolExecutor(8) as ex:
        for part in ex.map(play, jobs, chunksize=50):
            rows.extend(part)
    x = np.array([r[0] for r in rows], dtype=float)
    y = np.array([r[1] for r in rows], dtype=float)
    w = fit(x, y)
    p = 1 / (1 + np.exp(-(x @ w)))
    old = np.array(H.WEIGHTS)
    p_old = 1 / (1 + np.exp(-(x @ old)))
    ll = lambda q: -np.mean(y * np.log(q + 1e-9) + (1 - y) * np.log(1 - q + 1e-9))  # noqa: E731
    print(f"{len(rows)} samples from {len(jobs)} games in {time.time() - t:.0f}s")
    print(f"log loss: fitted {ll(p):.4f}  current {ll(p_old):.4f}")
    for name, a, b in zip(H.FEATURES, w, old, strict=True):
        print(f"  {name:15s} {a:+.3f}   (current {b:+.3f})")
    print("WEIGHTS = [" + ", ".join(f"{v:.3f}" for v in w) + "]")


if __name__ == "__main__":
    main()
