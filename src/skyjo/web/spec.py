"""Skyjo on the platform: its tile, its table and the bot catalogue (heuristics and trained policies)."""

from __future__ import annotations

from collections.abc import Iterable
from pathlib import Path
from typing import Any

from boardgames.games import GameSpec
from skyjo.web.bots import BotCatalog
from skyjo.web.room import MAX_SEATS, Room, RoomError

# Shipped trained policies; `runs/` holds the ones you train yourself (`bg skyjo train`).
MODEL_DIRS = (Path(__file__).parents[1] / "models", Path("runs"))


class Backend:
    def __init__(
        self, delay_scale: float = 1.0, model_dirs: Iterable[Path] = MODEL_DIRS, bots: Iterable[str] = ()
    ) -> None:
        """`model_dirs`: folders scanned for <run>/policy_best.npz.
        `bots`: extra agent specs, e.g. 'ev:reveal_bonus=0.5'."""
        self.delay_scale = delay_scale
        self.catalog = BotCatalog([d for d in model_dirs if Path(d).is_dir()], bots)

    def new_room(self, code: str) -> Room:
        return Room(code, self.catalog, delay_scale=self.delay_scale)

    def config(self) -> dict[str, Any]:
        return {"bots": self.catalog.public()}


GAME = GameSpec(
    key="skyjo",
    title="Skyjo",
    tagline="Flip, swap and clear columns of cards to finish each round with the lowest score.",
    min_players=2,
    max_players=MAX_SEATS,
    bots=True,
    kind="versus",
    minutes="30–45",
    weight=1.07,
    static=Path(__file__).parent / "static",
    backend=Backend,
    error=RoomError,
    accent="#2f9e8f",
)
