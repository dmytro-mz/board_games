from __future__ import annotations

import time
from collections import Counter

import typer

from avel.bots import BOT_TYPES, DEFAULT_BOT
from avel.game.engine import Game, Phase

app = typer.Typer(add_completion=False, no_args_is_help=True)


def play(players: int, seed: int, crater: str = "easy", bot: str = DEFAULT_BOT, limit: int = 50_000) -> Game:
    """One bot-only game to the end."""
    game = Game(players, seed=seed, crater=crater)
    bots = [BOT_TYPES[bot].make(seed * 10 + i) for i in range(players)]
    steps = 0
    while game.phase != Phase.GAME_OVER:
        seat = game.actor
        assert seat is not None
        game.step(seat, bots[seat].act(game.view(seat)))
        steps += 1
        if steps > limit:
            raise RuntimeError(f"seed {seed}: no end after {limit} steps")
    return game


@app.command("eval")
def evaluate(
    games: int = 50,
    players: int = 2,
    crater: str = "easy",
    bot: str = DEFAULT_BOT,
    seed: int = 0,
) -> None:
    """Bot-only games: win rate and how they ended."""
    endings: Counter[str] = Counter()
    rounds = 0
    started = time.perf_counter()
    for i in range(games):
        game = play(players, seed + i, crater, bot)
        assert game.result is not None
        endings[game.result.reason] += 1
        rounds += game.result.rounds
    wins = endings["victory"]
    took = time.perf_counter() - started
    typer.echo(
        f"{players}p {crater} {bot}: won {wins}/{games} ({100 * wins / games:.0f}%), "
        f"avg rounds {rounds / games:.1f}, endings {dict(endings)}, {took / games:.2f}s/game"
    )
