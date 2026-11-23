from __future__ import annotations

import time
from collections import Counter
from concurrent.futures import ProcessPoolExecutor
from typing import Annotated

import typer
from rich.console import Console
from rich.table import Table

app = typer.Typer(add_completion=False, help="Pandemic: web game and bots")
console = Console()


def _play(args: tuple[str, int, int, int]) -> tuple[bool, str, int, int, int]:
    from pandemic.bots import make_bot
    from pandemic.game.engine import RulesConfig
    from pandemic.runner import play_game

    key, players, epidemics, seed = args
    bots = [make_bot(key, seed * 31 + i) for i in range(players)]
    game = play_game(bots, seed=seed, rules=RulesConfig(epidemics=epidemics))
    assert game.result is not None
    cured = sum(v != "none" for v in game.cures.values())
    return game.result.won, game.result.reason, game.turn, cured, game.outbreaks


@app.command("eval")
def eval_cmd(
    bots: Annotated[str, typer.Option("-a", help="Comma-separated bot keys")] = "expert,rookie",
    players: Annotated[str, typer.Option("-p", help="Comma-separated team sizes")] = "2,3,4",
    epidemics: Annotated[str, typer.Option("-e", help="Comma-separated epidemic counts (4, 5, 6)")] = "4,5,6",
    games: Annotated[int, typer.Option("-n", help="Games per combination")] = 100,
    workers: int = 8,
) -> None:
    """Win rate of all-bot teams per bot, team size and difficulty."""
    keys = [k.strip() for k in bots.split(",") if k.strip()]
    sizes = [int(p) for p in players.split(",")]
    levels = [int(e) for e in epidemics.split(",")]
    started = time.time()
    table = Table(title=f"{games} games per row")
    for col in ("bot", "players", "epidemics", "win rate", "cures", "outbreaks", "turns", "losses"):
        table.add_column(col)
    with ProcessPoolExecutor(workers) as ex:
        for key in keys:
            for n in sizes:
                for e in levels:
                    jobs = [(key, n, e, seed) for seed in range(games)]
                    rows = list(ex.map(_play, jobs, chunksize=2))
                    wins = sum(r[0] for r in rows)
                    losses = Counter(r[1] for r in rows if not r[0])
                    table.add_row(
                        key,
                        str(n),
                        str(e),
                        f"{wins / games:.2f}",
                        f"{sum(r[3] for r in rows) / games:.1f}",
                        f"{sum(r[4] for r in rows) / games:.1f}",
                        f"{sum(r[2] for r in rows) / games:.0f}",
                        " ".join(f"{k} {v}" for k, v in losses.most_common()),
                    )
    console.print(table)
    console.print(f"[dim]{time.time() - started:.1f}s")
