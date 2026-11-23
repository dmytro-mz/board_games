"""Evaluate a lineup of agents over many full games, in parallel.

Seats rotate every game so no agent benefits from seat order; every game uses a
distinct, reproducible seed.
"""

from __future__ import annotations

import math
import os
from collections.abc import Sequence
from concurrent.futures import ProcessPoolExecutor
from dataclasses import asdict, dataclass, field

from skyjo.agents.base import Agent
from skyjo.game.config import RulesConfig
from skyjo.runner import play_game


@dataclass(slots=True)
class GameRecord:
    """One game, indexed by lineup position (not seat)."""

    totals: list[int]
    win_share: list[float]  # 1/k for each of k tied winners
    round_scores: list[list[int]]
    finished: list[int]  # rounds this agent ended
    doubled: list[int]  # rounds this agent ended and got doubled
    n_rounds: int


def _play_chunk(lineup: Sequence[Agent], rules: RulesConfig, game_ids: Sequence[int], seed: int) -> list[GameRecord]:
    n = len(lineup)
    records: list[GameRecord] = []
    for g in game_ids:
        shift = g % n
        seat_to_slot = [(seat + shift) % n for seat in range(n)]
        seated = [lineup[slot] for slot in seat_to_slot]
        for k, agent in enumerate(seated):
            agent.seed(seed * 1_000_003 + g * 31 + k)
        result = play_game(seated, rules, seed=seed * 1_000_003 + g)

        totals = [0] * n
        win_share = [0.0] * n
        round_scores: list[list[int]] = [[] for _ in range(n)]
        finished = [0] * n
        doubled = [0] * n
        for seat, slot in enumerate(seat_to_slot):
            totals[slot] = result.totals[seat]
            if seat in result.winners:
                win_share[slot] = 1.0 / len(result.winners)
            for r in result.rounds:
                round_scores[slot].append(r.scores[seat])
                if r.finisher == seat:
                    finished[slot] += 1
                    doubled[slot] += int(r.doubled)
        records.append(GameRecord(totals, win_share, round_scores, finished, doubled, len(result.rounds)))
    return records


def _mean_ci(xs: Sequence[float]) -> tuple[float, float]:
    n = len(xs)
    if n == 0:
        return math.nan, math.nan
    mean = sum(xs) / n
    if n == 1:
        return mean, math.nan
    var = sum((x - mean) ** 2 for x in xs) / (n - 1)
    return mean, 1.96 * math.sqrt(var / n)


@dataclass(slots=True)
class AgentSummary:
    label: str
    games: int
    win_rate: float
    win_rate_ci: float
    game_score: float
    game_score_ci: float
    round_score: float
    round_score_ci: float
    finish_rate: float  # share of rounds this agent ended
    doubled_rate: float  # share of its finishes that got doubled


@dataclass(slots=True)
class TournamentResult:
    labels: list[str]
    n_games: int
    n_players: int
    mean_rounds: float
    summaries: list[AgentSummary] = field(default_factory=list)

    def by_label(self) -> dict[str, AgentSummary]:
        return {s.label: s for s in self.summaries}

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


def unique_labels(lineup: Sequence[Agent]) -> list[str]:
    names = [a.name for a in lineup]
    return [f"{n}#{i}" if names.count(n) > 1 else n for i, n in enumerate(names)]


def summarize(lineup: Sequence[Agent], records: Sequence[GameRecord]) -> TournamentResult:
    n = len(lineup)
    labels = unique_labels(lineup)
    total_rounds = sum(r.n_rounds for r in records)
    result = TournamentResult(
        labels=labels,
        n_games=len(records),
        n_players=n,
        mean_rounds=total_rounds / max(len(records), 1),
    )
    for slot, label in enumerate(labels):
        wins = [r.win_share[slot] for r in records]
        totals = [float(r.totals[slot]) for r in records]
        rounds = [float(s) for r in records for s in r.round_scores[slot]]
        finished = sum(r.finished[slot] for r in records)
        doubled = sum(r.doubled[slot] for r in records)
        wr, wr_ci = _mean_ci(wins)
        gs, gs_ci = _mean_ci(totals)
        rs, rs_ci = _mean_ci(rounds)
        result.summaries.append(
            AgentSummary(
                label=label,
                games=len(records),
                win_rate=wr,
                win_rate_ci=wr_ci,
                game_score=gs,
                game_score_ci=gs_ci,
                round_score=rs,
                round_score_ci=rs_ci,
                finish_rate=finished / max(total_rounds, 1),
                doubled_rate=doubled / max(finished, 1),
            )
        )
    return result


def run_tournament(
    lineup: Sequence[Agent],
    n_games: int,
    rules: RulesConfig | None = None,
    seed: int = 0,
    workers: int | None = None,
    executor: ProcessPoolExecutor | None = None,
) -> TournamentResult:
    rules = rules or RulesConfig(n_players=len(lineup))
    workers = workers if workers is not None else max(1, (os.cpu_count() or 2) - 1)
    game_ids = list(range(n_games))
    if workers <= 1 or n_games < 8:
        return summarize(lineup, _play_chunk(lineup, rules, game_ids, seed))

    n_chunks = min(n_games, workers * 4)
    chunks = [game_ids[i::n_chunks] for i in range(n_chunks)]
    own_pool = executor is None
    pool = executor or ProcessPoolExecutor(max_workers=workers)
    try:
        futures = [pool.submit(_play_chunk, lineup, rules, chunk, seed) for chunk in chunks]
        records = [rec for f in futures for rec in f.result()]
    finally:
        if own_pool:
            pool.shutdown()
    return summarize(lineup, records)
