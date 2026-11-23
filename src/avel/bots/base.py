from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Callable
from dataclasses import dataclass

from avel.game.actions import Action
from avel.game.engine import View


class Bot(ABC):
    """A player that picks one of `view.legal` (it only ever sees what its seat may see)."""

    def __init__(self, seed: int | None = None) -> None:
        self.seed = seed

    @abstractmethod
    def act(self, view: View) -> Action: ...


@dataclass(frozen=True)
class BotType:
    key: str
    label: str
    stars: int
    description: str
    make: Callable[[int | None], Bot]
