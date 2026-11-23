from __future__ import annotations

import time
from concurrent.futures import ProcessPoolExecutor
from typing import Annotated

import typer
from rich.console import Console
from rich.table import Table

app = typer.Typer(add_completion=False, help="Phase 10: web game and bots")
console = Console()


def _play(args: tuple[list[str], int]) -> tuple[list[str], list[int], int, list[int]]:
    from phase10.bots import make_bot
    from phase10.runner import play_game

    keys, seed = args
    shift = seed % len(keys)
    seated = keys[shift:] + keys[:shift]
    game = play_game([make_bot(k, seed * 31 + i) for i, k in enumerate(seated)], seed=seed)
    assert game.result is not None
    return seated, game.result.winners, game.hand_no, game.scores


@app.command("eval")
def eval_cmd(
    bots: Annotated[str, typer.Option("-a", help="Comma-separated bot keys, e.g. pro,regular")] = "pro,regular,rookie",
    games: Annotated[int, typer.Option("-n", help="Number of games")] = 300,
    workers: int = 8,
) -> None:
    """Bot tournament with rotating seats: win share and mean points per bot."""
    keys = [k.strip() for k in bots.split(",") if k.strip()]
    wins = dict.fromkeys(keys, 0.0)
    points = dict.fromkeys(keys, 0)
    hands: list[int] = []
    started = time.time()
    with ProcessPoolExecutor(workers) as ex:
        for seated, winners, hand_no, scores in ex.map(_play, [(keys, s) for s in range(games)], chunksize=4):
            for w in winners:
                wins[seated[w]] += 1 / len(winners)
            for k, p in zip(seated, scores, strict=True):
                points[k] += p
            hands.append(hand_no)
    table = Table(title=f"{games} games · {time.time() - started:.1f}s")
    for col in ("bot", "win share", "mean points"):
        table.add_column(col)
    per_key = {k: keys.count(k) for k in keys}
    for k in dict.fromkeys(keys):
        table.add_row(k, f"{wins[k] / games / per_key[k]:.3f}", f"{points[k] / games / per_key[k]:.0f}")
    console.print(table)
    console.print(f"mean hands per game {sum(hands) / len(hands):.1f}")
