"""Bots offered in the lobby: the built-in heuristics, extra registry entries and trained policies."""

from __future__ import annotations

import json
import re
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path

from skyjo.agents import REGISTRY, Agent, make_agent


@dataclass(frozen=True, slots=True)
class BotType:
    key: str  # public id sent to clients
    spec: str  # `make_agent` spec, never exposed (it may contain file paths)
    label: str
    description: str
    stars: int  # rough strength, 1..5
    n_players: int | None = None  # learned policies only work at the table size they were trained for

    def public(self) -> dict[str, object]:
        return {
            "key": self.key,
            "label": self.label,
            "description": self.description,
            "stars": self.stars,
            "n_players": self.n_players,
        }


BUILTIN: tuple[BotType, ...] = (
    BotType("random", "random", "Rookie", "Plays random legal moves. Good for learning the rules.", 1),
    BotType("greedy", "greedy", "Casual", "Keeps low cards, dumps high ones. No card counting.", 2),
    BotType("ev", "ev", "Card Counter", "Counts cards and maximises the expected score one move ahead.", 3),
    BotType(
        "expert",
        "expert",
        "Expert",
        "Card counting, discard denial, pair odds and exact doubling risk.",
        4,
    ),
)

_RUN_PREFIX = re.compile(r"^\d{8}-\d{6}_")
# Older layouts are tied to the table size they were trained on; the lobby lets people pick any.
MIN_WEB_OBS_VERSION = 4


def _policy_bot(path: Path) -> BotType | None:
    """Lobby entry for a trained policy, or None if it is unreadable or not a v4+ policy."""
    import numpy as np

    from skyjo.rl.encoding import SUPPORTED_VERSIONS

    try:
        meta = json.loads(str(np.load(path)["meta"]))
    except (OSError, KeyError, ValueError):
        return None
    version = meta.get("obs_version")
    if version not in SUPPORTED_VERSIONS or version < MIN_WEB_OBS_VERSION:
        return None
    run = path.parent.name
    name = _RUN_PREFIX.sub("", run) or run
    n_players = meta.get("n_players")
    description = f"Neural network trained with PPO (run {run}), plays at any table size."
    best = path.parent / "best.json"
    if best.exists():
        try:
            stats = json.loads(best.read_text())
        except ValueError:
            stats = {}
        for opponent in ("expert", "ev", "greedy"):
            rate = stats.get(f"eval/{opponent}/win_rate")
            if rate is not None:
                description += f" Wins {100 * rate:.0f}% 1-on-1 vs {opponent}."
                break
    return BotType(
        key=f"ppo:{run}:{path.stem}",
        spec=f"ppo:{path}",
        label=f"AI {name}",
        description=description,
        stars=5,
        n_players=None if n_players is None else int(n_players),
    )


class BotCatalog:
    def __init__(self, model_dirs: Iterable[Path] = (), extra_specs: Iterable[str] = ()) -> None:
        bots = list(BUILTIN)
        known = {b.key for b in bots}
        for name in REGISTRY:
            if name not in known and name != "ppo":
                bots.append(BotType(name, name, name.title(), f"Registry strategy `{name}`.", 3))
        for spec in extra_specs:
            if spec.startswith("ppo:"):
                path = Path(spec.split(":", 1)[1])
                bot = _policy_bot(path)
                if bot is None:
                    raise ValueError(f"{path}: not a readable obs v{MIN_WEB_OBS_VERSION}+ policy (e.g. ppo_v4)")
                bots.append(bot)
                continue
            make_agent(spec)  # fail fast on a typo
            bots.append(BotType(spec, spec, spec, f"Custom strategy `{spec}`.", 3))
        for directory in model_dirs:
            for path in sorted(Path(directory).glob("*/policy_best.npz"), reverse=True):
                bot = _policy_bot(path)
                if bot is not None:
                    bots.append(bot)
        self._bots = {b.key: b for b in bots}

    def get(self, key: str) -> BotType | None:
        return self._bots.get(key)

    def make(self, key: str, seed: int) -> Agent:
        return make_agent(self._bots[key].spec, seed=seed)

    def public(self) -> list[dict[str, object]]:
        return [b.public() for b in self._bots.values()]
