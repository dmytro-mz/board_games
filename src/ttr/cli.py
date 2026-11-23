from __future__ import annotations

import time
from concurrent.futures import ProcessPoolExecutor
from typing import Annotated

import typer
from rich.console import Console
from rich.table import Table

app = typer.Typer(add_completion=False, help="Ticket to Ride: Europe — web game and bots")
console = Console()


def _play(args: tuple[list[str], int]) -> tuple[list[str], list[int], list[int]]:
    from ttr.bots import make_bot
    from ttr.runner import play_game

    keys, seed = args
    shift = seed % len(keys)
    seated = keys[shift:] + keys[:shift]
    game = play_game([make_bot(k, seed * 31 + i) for i, k in enumerate(seated)], seed=seed)
    assert game.result is not None
    return seated, game.result.winners, [p.total for p in game.result.players]


@app.command("eval")
def eval_cmd(
    bots: Annotated[
        str, typer.Option("-a", help="Comma-separated bot keys, e.g. expert,conductor")
    ] = "expert,conductor",
    games: Annotated[int, typer.Option("-n", help="Number of games")] = 400,
    workers: int = 8,
) -> None:
    """Bot tournament with rotating seats: win share and mean score per bot."""
    keys = [k.strip() for k in bots.split(",") if k.strip()]
    wins = dict.fromkeys(keys, 0.0)
    scores: dict[str, list[int]] = {k: [] for k in keys}
    started = time.time()
    with ProcessPoolExecutor(workers) as ex:
        for seated, winners, totals in ex.map(_play, [(keys, s) for s in range(games)], chunksize=8):
            for w in winners:
                wins[seated[w]] += 1 / len(winners)
            for k, t in zip(seated, totals, strict=True):
                scores[k].append(t)
    table = Table(title=f"{games} games · {time.time() - started:.1f}s")
    for col in ("bot", "win share", "mean score"):
        table.add_column(col)
    per_key = {k: keys.count(k) for k in keys}
    for k in dict.fromkeys(keys):
        table.add_row(k, f"{wins[k] / games / per_key[k]:.3f}", f"{sum(scores[k]) / len(scores[k]):.1f}")
    console.print(table)
