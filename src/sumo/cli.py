from __future__ import annotations

import time
from concurrent.futures import ProcessPoolExecutor
from typing import Annotated

import typer
from rich.console import Console
from rich.table import Table

app = typer.Typer(add_completion=False, help="Marble Sumo: bot matches")
console = Console()


def _match(args: tuple[str, str, str, int, float | None, int]) -> tuple[int | None, str, int, tuple[int, int]]:
    """(winning bot index or None, reason, moves, marbles lost by bot a / bot b)."""
    from sumo.bots import make_bot
    from sumo.runner import play_game

    a, b, layout, seed, budget, limit = args
    swap = seed % 2 == 1  # bot `a` plays Black in even matches, White in odd ones
    keys = [b, a] if swap else [a, b]
    bots = [make_bot(keys[0], seed * 2, budget), make_bot(keys[1], seed * 2 + 1, budget)]
    game = play_game(bots, layout=layout, move_limit=limit)
    assert game.result is not None
    w = game.result.winner
    winner = None if w is None else (1 - w if swap else w)
    lost = (game.out[1], game.out[0]) if swap else (game.out[0], game.out[1])
    return winner, game.result.reason, game.turn, lost


@app.command("eval")
def eval_cmd(
    bots: Annotated[str, typer.Option("-a", help="Two bots, e.g. yokozuna,ozeki (or d3, t0.5)")] = "ozeki,rookie",
    games: Annotated[int, typer.Option("-n", help="Number of matches per layout")] = 40,
    layouts: Annotated[str, typer.Option("-l", help="Layout keys, comma separated, or 'all'")] = "all",
    budget: Annotated[float | None, typer.Option(help="Seconds per move for timed bots")] = None,
    limit: Annotated[int, typer.Option(help="Move limit per player")] = 150,
    workers: int = 8,
) -> None:
    """Head-to-head matches (colours alternate): wins, draws, marbles pushed out, game length."""
    from sumo.game.board import LAYOUTS

    keys = [k.strip() for k in bots.split(",") if k.strip()]
    if len(keys) != 2:
        raise typer.BadParameter("give exactly two bots")
    lkeys = list(LAYOUTS) if layouts == "all" else [x.strip() for x in layouts.split(",")]
    table = Table(title=f"{keys[0]} vs {keys[1]} · {games} matches per layout")
    for col in ("layout", f"{keys[0]} wins", "draws", f"{keys[1]} wins", "out a/b", "by limit", "moves"):
        table.add_column(col)
    started = time.time()
    with ProcessPoolExecutor(workers) as ex:
        for lk in lkeys:
            jobs = [(keys[0], keys[1], lk, s, budget, limit) for s in range(games)]
            wins = [0, 0]
            draws = by_limit = moves = 0
            lost = [0, 0]
            for winner, reason, n, out in ex.map(_match, jobs):
                if winner is None:
                    draws += 1
                else:
                    wins[winner] += 1
                by_limit += reason == "limit"
                moves += n
                lost[0] += out[0]
                lost[1] += out[1]
            table.add_row(
                lk,
                str(wins[0]),
                str(draws),
                str(wins[1]),
                f"{lost[1] / games:.1f} / {lost[0] / games:.1f}",
                str(by_limit),
                f"{moves / games:.0f}",
            )
    console.print(table)
    console.print(f"{time.time() - started:.0f}s")
