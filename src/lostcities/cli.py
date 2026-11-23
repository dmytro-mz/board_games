from __future__ import annotations

import time
from concurrent.futures import ProcessPoolExecutor
from typing import Annotated

import typer
from rich.console import Console
from rich.table import Table

app = typer.Typer(add_completion=False, help="Lost Cities: web game and bots")
console = Console()


def _match(args: tuple[str, str, int, int]) -> tuple[list[int], list[int]]:
    from lostcities.bots import make_bot
    from lostcities.runner import play_game

    a, b, rounds, seed = args
    game = play_game([make_bot(a, seed * 2), make_bot(b, seed * 2 + 1)], rounds=rounds, seed=seed, starter=seed % 2)
    assert game.result is not None
    return game.result.totals, game.result.winners


@app.command("eval")
def eval_cmd(
    bots: Annotated[str, typer.Option("-a", help="Two bot keys, e.g. pathfinder,scout")] = "pathfinder,scout",
    games: Annotated[int, typer.Option("-n", help="Number of matches")] = 1000,
    rounds: Annotated[int, typer.Option(help="Rounds per match")] = 3,
    workers: int = 8,
) -> None:
    """Head-to-head matches (the starting player alternates): win rate and mean score per bot."""
    keys = [k.strip() for k in bots.split(",") if k.strip()]
    if len(keys) != 2:
        raise typer.BadParameter("give exactly two bots")
    wins = [0.0, 0.0]
    totals = [0, 0]
    started = time.time()
    with ProcessPoolExecutor(workers) as ex:
        for score, winners in ex.map(_match, [(keys[0], keys[1], rounds, s) for s in range(games)], chunksize=16):
            for w in winners:
                wins[w] += 1 / len(winners)
            totals[0] += score[0]
            totals[1] += score[1]
    table = Table(title=f"{games} matches of {rounds} rounds · {time.time() - started:.1f}s")
    for col in ("bot", "win rate", "± 95%", "mean score"):
        table.add_column(col)
    for i, key in enumerate(keys):
        p = wins[i] / games
        table.add_row(key, f"{p:.3f}", f"{1.96 * (p * (1 - p) / games) ** 0.5:.3f}", f"{totals[i] / games:.1f}")
    console.print(table)
