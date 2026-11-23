"""Play complete games between agents."""

from __future__ import annotations

from collections.abc import Callable, Sequence

from skyjo.agents.base import Agent
from skyjo.game.config import RulesConfig
from skyjo.game.engine import Game, GameResult, IllegalActionError
from skyjo.game.observation import Observation

StepHook = Callable[[Game, int, Observation, int], None]


def play_game(
    agents: Sequence[Agent],
    rules: RulesConfig | None = None,
    seed: int | None = None,
    on_step: StepHook | None = None,
) -> GameResult:
    rules = rules or RulesConfig(n_players=len(agents))
    if rules.n_players != len(agents):
        raise ValueError(f"{len(agents)} agents for a {rules.n_players}-player game")
    game = Game(rules, seed=seed)
    while not game.is_over:
        seat = game.current_player
        obs = game.observe(seat)
        legal = game.legal_actions()
        action = agents[seat].act(obs, legal)
        if action not in legal:
            raise IllegalActionError(f"{agents[seat]!r} chose illegal action {action}")
        if on_step is not None:
            on_step(game, seat, obs, action)
        game.step(action)
    assert game.result is not None
    return game.result
