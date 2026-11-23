"""Sky Team on the platform: its tile, its table, the scenarios and the local progress file."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from boardgames.games import GameSpec
from skyteam.game.scenarios import ABILITIES, DIFFICULTIES, SCENARIOS
from skyteam.progress import Progress
from skyteam.web.room import Room, RoomError


class Backend:
    def __init__(self, delay_scale: float = 1.0, progress: Path | None = None) -> None:
        """`progress`: local file that remembers finished scenarios (default ./progress.json, gitignored)."""
        self.progress = Progress(progress)

    def new_room(self, code: str) -> Room:
        return Room(code, self.progress)

    def config(self) -> dict[str, Any]:
        return {
            "scenarios": [s.public() for s in SCENARIOS],
            "levels": DIFFICULTIES,
            "abilities": {k: {"name": v[0], "text": v[1]} for k, v in ABILITIES.items()},
            "progress": self.progress.finished(),
        }


GAME = GameSpec(
    key="skyteam",
    title="Sky Team",
    tagline="Pilot and co-pilot place dice in silence to land the plane together, 21 scenarios.",
    min_players=2,
    max_players=2,
    bots=False,
    kind="coop",
    minutes="15–20",
    static=Path(__file__).parent / "static",
    backend=Backend,
    error=RoomError,
    accent="#4b6fb5",
)
