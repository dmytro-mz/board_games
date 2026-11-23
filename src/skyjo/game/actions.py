"""Flat discrete action space shared by every agent (heuristic or learned).

| id      | meaning                                                         |
|---------|-----------------------------------------------------------------|
| 0..11   | REPLACE slot p with the card in hand                            |
| 12..23  | FLIP slot p (setup flip, or discard the drawn card then flip p) |
| 24      | DRAW from the face-down deck                                    |
| 25      | TAKE the top discard                                            |
"""

from __future__ import annotations

from enum import IntEnum

from skyjo.game.cards import N_SLOTS

REPLACE_BASE = 0
FLIP_BASE = N_SLOTS
DRAW_DECK = 2 * N_SLOTS
TAKE_DISCARD = DRAW_DECK + 1
N_ACTIONS = TAKE_DISCARD + 1


class Phase(IntEnum):
    SETUP = 0
    CHOOSE_SOURCE = 1
    PLACE_DRAWN = 2  # drew from deck: replace a slot, or discard and flip
    PLACE_DISCARD = 3  # took the discard: must replace a slot
    ROUND_OVER = 4


N_DECISION_PHASES = 4


def replace(pos: int) -> int:
    return REPLACE_BASE + pos


def flip(pos: int) -> int:
    return FLIP_BASE + pos


def describe(action: int) -> str:
    if action == DRAW_DECK:
        return "draw deck"
    if action == TAKE_DISCARD:
        return "take discard"
    if FLIP_BASE <= action < DRAW_DECK:
        return f"flip {action - FLIP_BASE}"
    if 0 <= action < FLIP_BASE:
        return f"replace {action}"
    raise ValueError(f"unknown action {action}")
