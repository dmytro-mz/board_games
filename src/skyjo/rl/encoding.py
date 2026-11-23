"""Observation -> fixed-size float vector. numpy only (runs inside env workers).

Every layout is versioned. Saved policies record the version they were trained on, so
add a new version instead of editing an existing one, and bump `OBS_VERSION` (the default
for new runs).

- v1: one-hot boards, discard/hand, phase, card counts, per-player summaries.
- v2: v1 + per-own-slot "relational" features for the hand and discard cards
  (column matches, value delta) — equality tests an MLP otherwise has to learn.
- v3: v2 + the `expert` heuristic's value of every action (gap to the best legal action,
  the "prior" block a residual policy adds to its logits), its best value, and game
  context (total-score gaps, distance to the end score, round turn).
- v4: v3 for any table size. Per-seat blocks are padded to `MAX_PLAYERS` seats (absent seats
  are all zero), plus a table-size one-hot and opponent summaries (best / mean / previous
  player). At 2 players every v3 feature appears unchanged (`input_feature_map`), so v3
  weights transplant exactly.
"""

from __future__ import annotations

from collections.abc import Sequence

import numpy as np

from skyjo.agents.expert import ExpertAgent
from skyjo.game.actions import DRAW_DECK, FLIP_BASE, N_ACTIONS, N_DECISION_PHASES, TAKE_DISCARD, Phase
from skyjo.game.cards import (
    COLS,
    HIDDEN,
    MAX_VALUE,
    MIN_VALUE,
    N_SLOT_CODES,
    N_SLOTS,
    N_VALUES,
    REMOVED,
    ROWS,
    STANDARD_COMPOSITION,
)
from skyjo.game.observation import Observation

OBS_VERSION = 4
SUPPORTED_VERSIONS = (1, 2, 3, 4)
MAX_PLAYERS = 8

_SLOT_EYE = np.eye(N_SLOT_CODES, dtype=np.float32)
_CARD_EYE = np.eye(N_VALUES + 1, dtype=np.float32)  # last row = "no card"
_PHASE_EYE = np.eye(N_DECISION_PHASES, dtype=np.float32)
_COMPOSITION = np.array([STANDARD_COMPOSITION[v] for v in range(MIN_VALUE, MAX_VALUE + 1)], dtype=np.float32)
_VALUES = np.arange(MIN_VALUE, MAX_VALUE + 1, dtype=np.float32)
_N_RELATIONAL = 2 * 2 * N_SLOTS  # (hand, discard) x (column matches, delta) x slots


def _relational(own: np.ndarray, card: int | None, mean_unknown: float) -> np.ndarray:
    """For each own slot: other visible cards in its column equal to `card` (/2), and
    (slot value - card) / 12 using the unknown mean for hidden slots."""
    if card is None:
        return np.zeros(2 * N_SLOTS, dtype=np.float32)
    visible = own <= MAX_VALUE
    eq = (visible & (own == card)).reshape(COLS, ROWS)
    matches = (eq.sum(axis=1, keepdims=True) - eq).reshape(-1) / 2.0
    value = np.where(visible, own, mean_unknown)
    delta = np.where(own == REMOVED, 0.0, (value - card) / MAX_VALUE)
    return np.concatenate([matches, delta]).astype(np.float32)


PRIOR_UNIT = 10.0  # points per unit of the prior block
PRIOR_FLOOR = -3.0  # value of illegal actions / clip for very bad ones, in units


def _legal_from_obs(obs: Observation) -> list[int]:
    """Legal actions as far as the observation can tell (drawing is assumed possible)."""
    board = obs.board
    hidden = [FLIP_BASE + p for p, s in enumerate(board) if s == HIDDEN]
    if obs.phase == Phase.SETUP:
        return hidden
    if obs.phase == Phase.CHOOSE_SOURCE:
        return [DRAW_DECK, TAKE_DISCARD]
    active = [p for p, s in enumerate(board) if s != REMOVED]
    return active + hidden if obs.phase == Phase.PLACE_DRAWN else active


def expert_prior(expert: ExpertAgent, obs: Observation) -> tuple[np.ndarray, float]:
    """Expert action values as (value - best legal value) / PRIOR_UNIT, and the best value."""
    prior = np.full(N_ACTIONS, PRIOR_FLOOR, dtype=np.float32)
    if obs.phase == Phase.ROUND_OVER:
        return prior, 0.0
    values = expert.action_values(obs, _legal_from_obs(obs))
    best = max(values.values())
    for a, v in values.items():
        prior[a] = max(PRIOR_FLOOR, (v - best) / PRIOR_UNIT)
    return prior, best


_N_SUMMARY = 8  # v4 opponent summaries, see `ObsEncoder._encode_v4`


def layout(version: int, n_players: int | None) -> list[tuple[str, int]]:
    """Ordered (block, width) pairs of an observation vector. v4 ignores `n_players`."""
    if version >= 4:
        seats = MAX_PLAYERS
    elif n_players is None:
        raise ValueError(f"obs version {version} needs a fixed n_players")
    else:
        seats = n_players
    blocks = [
        ("boards", seats * N_SLOTS * N_SLOT_CODES),  # one-hot, seat-relative
        ("discard", N_VALUES + 1),
        ("hand", N_VALUES + 1),
        ("phase", N_DECISION_PHASES),
        ("unknown", N_VALUES),  # unknown-card fractions
        ("deck", 2),  # deck size, expected unknown value
        ("finisher", seats + 1),  # relative seat that finished, or nobody (last)
        ("hidden", seats),
        ("vis_sum", seats),
        ("est", seats),  # estimated board score
        ("totals", seats),
    ]
    if version >= 2:
        blocks.append(("relational", _N_RELATIONAL))
    if version >= 3:
        blocks += [("prior", N_ACTIONS), ("best", 1), ("gaps", seats - 1), ("context", 3)]
    if version >= 4:
        blocks += [("table", MAX_PLAYERS - 1), ("summary", _N_SUMMARY)]
    return blocks


def _offsets(blocks: list[tuple[str, int]]) -> dict[str, int]:
    out, pos = {}, 0
    for name, width in blocks:
        out[name] = pos
        pos += width
    return out


def input_feature_map(src_version: int, n_players: int, dst_version: int = OBS_VERSION) -> np.ndarray:
    """Index in the `dst_version` vector of every `src_version` feature, for an `n_players` game.

    Lets a policy trained on an older layout be transplanted: copy input-weight row i to
    `map[i]` and zero the rest, and the new network computes the same function.
    """
    if dst_version < 4 and src_version != dst_version:
        raise ValueError("only v4 (seat-padded) can host another layout")
    src = layout(src_version, n_players)
    dst = _offsets(layout(dst_version, n_players))
    seats = MAX_PLAYERS if dst_version >= 4 else n_players
    parts = []
    for name, width in src:
        if name not in dst:
            raise ValueError(f"block {name!r} of v{src_version} is missing in v{dst_version}")
        idx = dst[name] + np.arange(width)
        if name == "finisher":
            idx[-1] = dst[name] + seats  # "nobody" is the last slot
        parts.append(idx)
    return np.concatenate(parts)


class ObsEncoder:
    """Seat-relative encoding: the observing player is always board 0.

    `n_players` is None for table-size-agnostic layouts (v4+), which accept any game.
    """

    def __init__(self, n_players: int | None, version: int = OBS_VERSION) -> None:
        if version not in SUPPORTED_VERSIONS:
            raise ValueError(f"unsupported obs version {version}; supported: {SUPPORTED_VERSIONS}")
        self.version = version
        self.n_players = None if version >= 4 else n_players
        blocks = layout(version, self.n_players)
        self.dim = sum(width for _, width in blocks)
        # Start of the N_ACTIONS-wide expert prior block, or None if the layout has none.
        self.prior_offset: int | None = _offsets(blocks).get("prior")
        if version >= 3:
            self.expert = ExpertAgent()

    def supports(self, n_players: int) -> bool:
        return n_players == self.n_players if self.n_players is not None else 2 <= n_players <= MAX_PLAYERS

    def encode(self, obs: Observation) -> np.ndarray:
        if self.version >= 4:
            return self._encode_v4(obs)
        n = self.n_players
        assert n is not None
        boards = np.asarray(obs.boards, dtype=np.int64)
        boards = np.roll(boards, -obs.player, axis=0)
        onehot = _SLOT_EYE[boards - MIN_VALUE].reshape(-1)

        discard = _CARD_EYE[N_VALUES if obs.discard_top is None else obs.discard_top - MIN_VALUE]
        hand = _CARD_EYE[N_VALUES if obs.hand is None else obs.hand - MIN_VALUE]
        phase = _PHASE_EYE[int(obs.phase)]

        unknown = np.asarray(obs.unknown_counts, dtype=np.float32)
        n_unknown = float(unknown.sum())
        mean_unknown = float(unknown @ _VALUES) / n_unknown if n_unknown else 0.0

        finisher = np.zeros(n + 1, dtype=np.float32)
        finisher[n if obs.finisher is None else (obs.finisher - obs.player) % n] = 1.0

        visible = boards <= MAX_VALUE
        hidden = (boards == HIDDEN).sum(axis=1).astype(np.float32)
        vis_sum = np.where(visible, boards, 0).sum(axis=1).astype(np.float32)
        est = vis_sum + hidden * mean_unknown
        totals = np.roll(np.asarray(obs.totals, dtype=np.float32), -obs.player)

        parts = [
            onehot,
            discard,
            hand,
            phase,
            unknown / _COMPOSITION,
            np.array([obs.deck_size / 150.0, mean_unknown / MAX_VALUE], dtype=np.float32),
            finisher,
            hidden / N_SLOTS,
            vis_sum / 60.0,
            est / 60.0,
            totals / 100.0,
        ]
        if self.version >= 2:
            parts.append(_relational(boards[0], obs.hand, mean_unknown))
            parts.append(_relational(boards[0], obs.discard_top, mean_unknown))
        if self.version >= 3:
            prior, best = expert_prior(self.expert, obs)
            gaps = (totals[1:] - totals[0]) / 50.0
            end_distance = (100.0 - totals.max()) / 100.0
            parts += [
                prior,
                np.array([best / 30.0], dtype=np.float32),
                gaps,
                np.array([end_distance, float(end_distance <= 0.25), obs.turn / 100.0], dtype=np.float32),
            ]
        return np.concatenate(parts)

    def _encode_v4(self, obs: Observation) -> np.ndarray:
        n, seats = obs.n_players, MAX_PLAYERS
        if not 2 <= n <= seats:
            raise ValueError(f"obs v4 supports 2..{seats} players, got {n}")
        boards = np.roll(np.asarray(obs.boards, dtype=np.int64), -obs.player, axis=0)
        onehot = np.zeros(seats * N_SLOTS * N_SLOT_CODES, dtype=np.float32)
        onehot[: n * N_SLOTS * N_SLOT_CODES] = _SLOT_EYE[boards - MIN_VALUE].reshape(-1)

        discard = _CARD_EYE[N_VALUES if obs.discard_top is None else obs.discard_top - MIN_VALUE]
        hand = _CARD_EYE[N_VALUES if obs.hand is None else obs.hand - MIN_VALUE]
        phase = _PHASE_EYE[int(obs.phase)]

        unknown = np.asarray(obs.unknown_counts, dtype=np.float32)
        n_unknown = float(unknown.sum())
        mean_unknown = float(unknown @ _VALUES) / n_unknown if n_unknown else 0.0

        finisher = np.zeros(seats + 1, dtype=np.float32)
        finisher[seats if obs.finisher is None else (obs.finisher - obs.player) % n] = 1.0

        visible = boards <= MAX_VALUE
        hidden = (boards == HIDDEN).sum(axis=1).astype(np.float32)
        vis_sum = np.where(visible, boards, 0).sum(axis=1).astype(np.float32)
        est = vis_sum + hidden * mean_unknown
        totals = np.roll(np.asarray(obs.totals, dtype=np.float32), -obs.player)
        # (hidden, vis_sum, est, totals) per seat, absent seats zero
        per_seat = np.zeros((4, seats), dtype=np.float32)
        per_seat[:, :n] = np.stack([hidden / N_SLOTS, vis_sum / 60.0, est / 60.0, totals / 100.0])

        prior, best = expert_prior(self.expert, obs)
        gaps = np.zeros(seats - 1, dtype=np.float32)
        gaps[: n - 1] = (totals[1:] - totals[0]) / 50.0
        end_distance = (100.0 - totals.max()) / 100.0
        table = np.zeros(seats - 1, dtype=np.float32)
        table[n - 2] = 1.0
        opp_est, opp_gaps = est[1:] / 60.0, gaps[: n - 1]
        summary = np.array(
            [
                opp_est.min(),
                opp_est.mean(),
                hidden[1:].min() / N_SLOTS,
                opp_gaps.min(),
                opp_gaps.mean(),
                est[-1] / 60.0,  # previous player: whose discards I see
                hidden[-1] / N_SLOTS,
                obs.turn / n / 50.0,  # own turns this round
            ],
            dtype=np.float32,
        )
        return np.concatenate(
            [
                onehot,
                discard,
                hand,
                phase,
                unknown / _COMPOSITION,
                np.array([obs.deck_size / 150.0, mean_unknown / MAX_VALUE], dtype=np.float32),
                finisher,
                per_seat.reshape(-1),
                _relational(boards[0], obs.hand, mean_unknown),
                _relational(boards[0], obs.discard_top, mean_unknown),
                prior,
                np.array([best / 30.0], dtype=np.float32),
                gaps,
                np.array([end_distance, float(end_distance <= 0.25), obs.turn / 100.0], dtype=np.float32),
                table,
                summary,
            ]
        )


def legal_mask(legal: Sequence[int]) -> np.ndarray:
    mask = np.zeros(N_ACTIONS, dtype=bool)
    mask[list(legal)] = True
    return mask
