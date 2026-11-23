"""Skyjo rules engine: a `Round` is one deal; a `Game` chains rounds to `end_score`.

The engine is a deterministic state machine driven by flat integer actions
(see `skyjo.game.actions`). Randomness comes only from the injected `random.Random`.
"""

from __future__ import annotations

import random
from dataclasses import dataclass

from skyjo.game.actions import (
    DRAW_DECK,
    FLIP_BASE,
    N_ACTIONS,
    TAKE_DISCARD,
    Phase,
)
from skyjo.game.board import FACE_UP, Board
from skyjo.game.cards import N_SLOTS, N_VALUES, build_deck, column_of, value_index
from skyjo.game.config import RulesConfig
from skyjo.game.observation import Observation


class IllegalActionError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class RoundResult:
    raw_scores: tuple[int, ...]
    scores: tuple[int, ...]  # after the finisher-doubling rule
    finisher: int | None  # None if the round hit max_turns_per_round
    doubled: bool
    turns: int


class Round:
    def __init__(
        self,
        rules: RulesConfig,
        rng: random.Random,
        starting_player: int | None = None,
        totals: tuple[int, ...] | None = None,
        round_index: int = 0,
    ) -> None:
        self.rules = rules
        self.rng = rng
        self.n_players = rules.n_players
        self.totals = totals or (0,) * self.n_players
        self.round_index = round_index
        self._forced_starter = starting_player

        self._composition_counts = [0] * N_VALUES
        for value, count in rules.composition.items():
            self._composition_counts[value_index(value)] = count

        self.deck = build_deck(rules.composition)
        rng.shuffle(self.deck)
        self.boards = [Board([self.deck.pop() for _ in range(N_SLOTS)]) for _ in range(self.n_players)]
        self.discard: list[int] = []
        self._discard_counts = [0] * N_VALUES
        self._push_discard(self.deck.pop())

        self.hand: int | None = None
        self.finisher: int | None = None
        self.final_turns_left = 0
        self.turn = 0
        self.result: RoundResult | None = None

        self._setup_done = [0] * self.n_players
        self.current = 0
        self.phase = Phase.SETUP
        if rules.setup_flips == 0:
            self._start_play()

    # ------------------------------------------------------------------ queries
    @property
    def is_over(self) -> bool:
        return self.phase == Phase.ROUND_OVER

    def legal_actions(self) -> list[int]:
        phase = self.phase
        board = self.boards[self.current]
        if phase == Phase.CHOOSE_SOURCE:
            actions = [TAKE_DISCARD]
            if self.deck or len(self.discard) > 1:
                actions.insert(0, DRAW_DECK)
            return actions
        if phase == Phase.PLACE_DRAWN:
            return board.active_positions() + [FLIP_BASE + p for p in board.hidden_positions()]
        if phase == Phase.PLACE_DISCARD:
            return board.active_positions()
        if phase == Phase.SETUP:
            return [FLIP_BASE + p for p in board.hidden_positions()]
        return []

    def legal_mask(self) -> list[bool]:
        mask = [False] * N_ACTIONS
        for a in self.legal_actions():
            mask[a] = True
        return mask

    def observe(self, player: int) -> Observation:
        views = tuple(b.view() for b in self.boards)
        unknown = list(self._composition_counts)
        for i, c in enumerate(self._discard_counts):
            unknown[i] -= c
        for b in self.boards:
            for v, s in zip(b.values, b.status, strict=True):
                if s == FACE_UP:
                    unknown[value_index(v)] -= 1
        hand = self.hand if player == self.current else None
        if hand is not None:
            unknown[value_index(hand)] -= 1
        return Observation(
            player=player,
            n_players=self.n_players,
            phase=self.phase,
            boards=views,
            discard_top=self.discard[-1] if self.discard else None,
            hand=hand,
            deck_size=len(self.deck),
            unknown_counts=tuple(unknown),
            finisher=self.finisher,
            totals=self.totals,
            round_index=self.round_index,
            turn=self.turn,
        )

    # ------------------------------------------------------------------ actions
    def step(self, action: int) -> None:
        phase = self.phase
        if phase == Phase.ROUND_OVER:
            raise IllegalActionError("round is over")
        if action not in self.legal_actions():
            raise IllegalActionError(f"action {action} illegal in phase {phase.name}")

        board = self.boards[self.current]
        if phase == Phase.SETUP:
            board.reveal(action - FLIP_BASE)
            self._advance_setup()
        elif phase == Phase.CHOOSE_SOURCE:
            if action == DRAW_DECK:
                self.hand = self._draw()
                self.phase = Phase.PLACE_DRAWN
            else:
                self.hand = self._pop_discard()
                self.phase = Phase.PLACE_DISCARD
        elif action < FLIP_BASE:  # REPLACE in PLACE_DRAWN / PLACE_DISCARD
            assert self.hand is not None
            old = board.put(action, self.hand)
            self.hand = None
            self._push_discard(old)
            self._clear_column(board, column_of(action))
            self._end_turn()
        else:  # discard the drawn card, flip a face-down one
            assert self.hand is not None
            self._push_discard(self.hand)
            self.hand = None
            pos = action - FLIP_BASE
            board.reveal(pos)
            self._clear_column(board, column_of(pos))
            self._end_turn()

    # ------------------------------------------------------------------ internals
    def _push_discard(self, card: int) -> None:
        self.discard.append(card)
        self._discard_counts[value_index(card)] += 1

    def _pop_discard(self) -> int:
        card = self.discard.pop()
        self._discard_counts[value_index(card)] -= 1
        return card

    def _draw(self) -> int:
        if not self.deck:
            top = self._pop_discard()
            self.deck = self.discard
            self.rng.shuffle(self.deck)
            self.discard = []
            self._discard_counts = [0] * N_VALUES
            self._push_discard(top)
        return self.deck.pop()

    def _clear_column(self, board: Board, col: int) -> None:
        if self.rules.column_clear:
            for card in board.clear_column_if_matching(col):
                self._push_discard(card)

    def _advance_setup(self) -> None:
        self._setup_done[self.current] += 1
        if self._setup_done[self.current] < self.rules.setup_flips:
            return
        if self.current + 1 < self.n_players:
            self.current += 1
            return
        self._start_play()

    def _start_play(self) -> None:
        if self._forced_starter is not None:
            starter = self._forced_starter
        else:
            sums = [b.visible_score() for b in self.boards]
            starter = sums.index(max(sums))
        self.current = starter
        self.phase = Phase.CHOOSE_SOURCE

    def _end_turn(self) -> None:
        p = self.current
        self.turn += 1
        if self.finisher is None:
            if self.boards[p].all_revealed():
                self.finisher = p
                self.final_turns_left = self.n_players - 1
        else:
            self.final_turns_left -= 1

        if (self.finisher is not None and self.final_turns_left == 0) or (self.turn >= self.rules.max_turns_per_round):
            self._finish()
            return
        self.current = (p + 1) % self.n_players
        self.phase = Phase.CHOOSE_SOURCE

    def _finish(self) -> None:
        for board in self.boards:
            board.reveal_all()
            if self.rules.column_clear:
                for card in board.clear_all_matching_columns():
                    self._push_discard(card)
        raw = tuple(b.score() for b in self.boards)
        scores = list(raw)
        doubled = False
        f = self.finisher
        if f is not None and self.rules.double_finisher_penalty and raw[f] > 0:
            others = [raw[i] for i in range(self.n_players) if i != f]
            best_other = min(others)
            beaten = best_other <= raw[f] if self.rules.double_on_tie else best_other < raw[f]
            if beaten:
                scores[f] *= 2
                doubled = True
        self.result = RoundResult(raw_scores=raw, scores=tuple(scores), finisher=f, doubled=doubled, turns=self.turn)
        self.hand = None
        self.phase = Phase.ROUND_OVER


@dataclass(frozen=True, slots=True)
class GameResult:
    totals: tuple[int, ...]
    winners: tuple[int, ...]  # seats sharing the lowest total
    rounds: tuple[RoundResult, ...]


class Game:
    """Multi-round Skyjo. Rounds advance automatically inside `step`."""

    def __init__(self, rules: RulesConfig | None = None, seed: int | None = None) -> None:
        self.rules = rules or RulesConfig()
        self.rng = random.Random(seed)
        self.totals = [0] * self.rules.n_players
        self.rounds: list[RoundResult] = []
        self.round = Round(self.rules, self.rng, totals=tuple(self.totals), round_index=0)
        self.result: GameResult | None = None

    @property
    def is_over(self) -> bool:
        return self.result is not None

    @property
    def current_player(self) -> int:
        return self.round.current

    @property
    def phase(self) -> Phase:
        return self.round.phase

    def legal_actions(self) -> list[int]:
        return [] if self.is_over else self.round.legal_actions()

    def observe(self, player: int) -> Observation:
        return self.round.observe(player)

    def step(self, action: int) -> RoundResult | None:
        """Apply an action; return the RoundResult if this action ended a round."""
        if self.is_over:
            raise IllegalActionError("game is over")
        self.round.step(action)
        if not self.round.is_over:
            return None
        result = self.round.result
        assert result is not None
        self.rounds.append(result)
        for i, s in enumerate(result.scores):
            self.totals[i] += s
        if max(self.totals) >= self.rules.end_score or len(self.rounds) >= self.rules.max_rounds:
            best = min(self.totals)
            self.result = GameResult(
                totals=tuple(self.totals),
                winners=tuple(i for i, t in enumerate(self.totals) if t == best),
                rounds=tuple(self.rounds),
            )
        else:
            self.round = Round(
                self.rules,
                self.rng,
                starting_player=result.finisher,
                totals=tuple(self.totals),
                round_index=len(self.rounds),
            )
        return result
