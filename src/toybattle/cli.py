from __future__ import annotations

import time
from concurrent.futures import ProcessPoolExecutor
from typing import Annotated

import typer
from rich.console import Console
from rich.table import Table

app = typer.Typer(add_completion=False, help="Toy Battle: bot matches and terrain balance")
console = Console()


def _match(args: tuple[str, str, str, bool, int]) -> tuple[int, str, int, int]:
    """(winning bot index, reason, turns, starter)."""
    from toybattle.bots import make_bot
    from toybattle.runner import play_game

    a, b, terrain, special, seed = args
    swap = seed % 2 == 1  # bot `a` plays Blue in even matches, Red in odd ones
    keys = [b, a] if swap else [a, b]
    bots = [make_bot(keys[0], seed * 2), make_bot(keys[1], seed * 2 + 1)]
    game = play_game(bots, terrain=terrain, special=special, seed=seed, starter=(seed // 2) % 2)
    assert game.result is not None
    winner_seat = game.result.winner
    winner_bot = (1 - winner_seat) if swap else winner_seat
    return winner_bot * 2 + winner_seat, game.result.reason, game.turn, game.starter or 0


@app.command("eval")
def eval_cmd(
    bots: Annotated[str, typer.Option("-a", help="Two bot keys, e.g. general,greedy")] = "general-fast,greedy",
    games: Annotated[int, typer.Option("-n", help="Number of matches per terrain")] = 100,
    terrains: Annotated[str, typer.Option("-t", help="Terrain keys, comma separated, or 'all'")] = "all",
    special: Annotated[bool, typer.Option(help="Special base effects on")] = True,
    workers: int = 8,
) -> None:
    """Head-to-head matches (colours and starting player alternate): win rate per bot, per colour, per reason."""
    from toybattle.game.terrains import TERRAINS

    keys = [k.strip() for k in bots.split(",") if k.strip()]
    if len(keys) != 2:
        raise typer.BadParameter("give exactly two bots")
    tkeys = list(TERRAINS) if terrains == "all" else [t.strip() for t in terrains.split(",")]
    table = Table(title=f"{keys[0]} vs {keys[1]} · {games} matches per terrain")
    for col in ("terrain", f"{keys[0]} wins", "± 95%", "Blue wins", "starter wins", "hq / medals / stuck", "turns"):
        table.add_column(col)
    started = time.time()
    with ProcessPoolExecutor(workers) as ex:
        for tk in tkeys:
            jobs = [(keys[0], keys[1], tk, special, s) for s in range(games)]
            wins = blue = starter = turns = 0
            reasons = {"hq": 0, "medals": 0, "stuck": 0}
            for code, reason, n_turns, first in ex.map(_match, jobs, chunksize=2):
                bot, seat = divmod(code, 2)
                wins += bot == 0
                blue += seat == 0
                starter += seat == first
                reasons[reason] += 1
                turns += n_turns
            p = wins / games
            table.add_row(
                tk,
                f"{p:.3f}",
                f"{1.96 * (p * (1 - p) / games) ** 0.5:.3f}",
                f"{blue / games:.2f}",
                f"{starter / games:.2f}",
                f"{reasons['hq']}/{reasons['medals']}/{reasons['stuck']}",
                f"{turns / games:.0f}",
            )
    console.print(table)
    console.print(f"{time.time() - started:.0f}s")
