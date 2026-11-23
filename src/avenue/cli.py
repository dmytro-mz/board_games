from __future__ import annotations

import time
from concurrent.futures import ProcessPoolExecutor
from typing import Annotated

import typer
from rich.console import Console
from rich.table import Table

app = typer.Typer(add_completion=False, help="Agent Avenue — web game and bot")
console = Console()


def _play(args: tuple[str, str, int, bool]) -> int:
    from avenue.bots import make_bot
    from avenue.runner import play_game

    a, b, seed, advanced = args
    swap = seed % 2
    keys = [b, a] if swap else [a, b]
    game = play_game([make_bot(k, seed * 31 + i) for i, k in enumerate(keys)], advanced=advanced, seed=seed // 2)
    assert game.result is not None
    return int((game.result["winner"] == 0) != bool(swap))


@app.command("eval")
def eval_cmd(
    a: Annotated[str, typer.Option("-a", help="Bot key")] = "mastermind",
    b: Annotated[str, typer.Option("-b", help="Opponent bot key (mastermind, heuristic, random)")] = "heuristic",
    games: Annotated[int, typer.Option("-n", help="Number of games")] = 100,
    advanced: Annotated[bool, typer.Option(help="Play the advanced mode")] = False,
    workers: int = 8,
) -> None:
    """Head-to-head bot match with alternating seats and starting players."""
    started = time.time()
    with ProcessPoolExecutor(workers) as ex:
        wins = sum(ex.map(_play, [(a, b, s, advanced) for s in range(games)], chunksize=2))
    table = Table(title=f"{games} games · {'advanced' if advanced else 'simple'} · {time.time() - started:.1f}s")
    for col in ("bot", "wins", "win share"):
        table.add_column(col)
    table.add_row(a, str(wins), f"{wins / games:.3f}")
    table.add_row(b, str(games - wins), f"{(games - wins) / games:.3f}")
    console.print(table)
