"""`skyjo` command line: evaluate strategies, train, plot, watch games."""

from __future__ import annotations

import json
import time
from datetime import datetime
from itertools import combinations
from pathlib import Path
from typing import Annotated

import typer
from rich.console import Console
from rich.table import Table

from skyjo.agents import make_agent
from skyjo.evaluation.tournament import TournamentResult, run_tournament
from skyjo.game.actions import describe
from skyjo.game.cards import HIDDEN, REMOVED, column_positions
from skyjo.game.config import RulesConfig

app = typer.Typer(add_completion=False, no_args_is_help=True)
console = Console()

AgentsOpt = Annotated[str, typer.Option("--agents", "-a", help="Comma-separated agent specs, one per seat")]
GamesOpt = Annotated[int, typer.Option("--games", "-n", help="Number of full games")]
WorkersOpt = Annotated[int, typer.Option(help="Worker processes")]


def _split(specs: str) -> list[str]:
    return [s.strip() for s in specs.split(";" if ";" in specs else ",") if s.strip()]


def _print_result(result: TournamentResult, title: str) -> None:
    table = Table(title=f"{title} — {result.n_games} games, {result.mean_rounds:.2f} rounds/game")
    for col in ["agent", "win rate", "game score", "round score", "finish %", "doubled %"]:
        table.add_column(col, justify="right")
    for s in sorted(result.summaries, key=lambda s: -s.win_rate):
        table.add_row(
            s.label,
            f"{s.win_rate:.3f} ± {s.win_rate_ci:.3f}",
            f"{s.game_score:.1f} ± {s.game_score_ci:.1f}",
            f"{s.round_score:.2f} ± {s.round_score_ci:.2f}",
            f"{100 * s.finish_rate:.1f}",
            f"{100 * s.doubled_rate:.1f}",
        )
    console.print(table)


def _save(payload: dict[str, object], out_dir: Path, stem: str) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"{datetime.now():%Y%m%d-%H%M%S}_{stem}.json"
    path.write_text(json.dumps(payload, indent=2))
    return path


@app.command("eval")
def eval_cmd(
    agents: AgentsOpt = "ev,greedy",
    games: GamesOpt = 1000,
    seed: int = 0,
    workers: WorkersOpt = 8,
    out_dir: Path = Path("results"),
) -> None:
    """Play one lineup (seats rotate every game) and report per-agent stats.

    Separate specs with ';' when a spec itself contains commas, e.g.
    -a "ev:reveal_bonus=0.5,pair_weight=1;greedy".
    """
    lineup = [make_agent(s) for s in _split(agents)]
    t0 = time.time()
    result = run_tournament(lineup, games, RulesConfig(n_players=len(lineup)), seed=seed, workers=workers)
    _print_result(result, " vs ".join(result.labels))
    path = _save(result.to_dict(), out_dir, "eval")
    console.print(f"[dim]{time.time() - t0:.1f}s, saved {path}")


@app.command()
def league(
    agents: AgentsOpt = "random,greedy,ev",
    games: GamesOpt = 1000,
    players: Annotated[int, typer.Option(help="Seats per game for the free-for-all")] = 4,
    seed: int = 0,
    workers: WorkersOpt = 8,
    out_dir: Path = Path("results"),
) -> None:
    """Round-robin head-to-head win-rate matrix plus an N-player free-for-all."""
    specs = _split(agents)
    matrix: dict[str, dict[str, float]] = {s: {} for s in specs}
    for a, b in combinations(specs, 2):
        res = run_tournament(
            [make_agent(a), make_agent(b)], games, RulesConfig(n_players=2), seed=seed, workers=workers
        )
        matrix[a][b], matrix[b][a] = res.summaries[0].win_rate, res.summaries[1].win_rate

    table = Table(title=f"head-to-head win rate (row beats column), {games} games each")
    table.add_column("agent")
    for s in specs:
        table.add_column(s, justify="right")
    table.add_column("mean", justify="right")
    for a in specs:
        vals = [matrix[a][b] for b in specs if b != a]
        table.add_row(a, *[("—" if a == b else f"{matrix[a][b]:.3f}") for b in specs], f"{sum(vals) / len(vals):.3f}")
    console.print(table)

    payload: dict[str, object] = {"head_to_head": matrix}
    if players > 2:
        lineup = [make_agent(specs[i % len(specs)]) for i in range(players)]
        ffa = run_tournament(lineup, games, RulesConfig(n_players=players), seed=seed, workers=workers)
        _print_result(ffa, f"{players}-player free-for-all")
        payload["free_for_all"] = ffa.to_dict()
    console.print(f"[dim]saved {_save(payload, out_dir, 'league')}")


@app.command()
def train(
    config: Annotated[Path | None, typer.Option("--config", "-c", help="YAML config")] = None,
    overrides: Annotated[
        list[str] | None, typer.Option("--set", "-s", help="Dotted override, e.g. ppo.learning_rate=1e-4")
    ] = None,
    resume: Annotated[Path | None, typer.Option(help="checkpoints/latest.pt to continue from")] = None,
) -> None:
    """Train a masked-PPO agent. Watch with: uv run tensorboard --logdir runs"""
    from skyjo.rl.config import load_config
    from skyjo.rl.ppo import train as run_training

    cfg = load_config(config, overrides)
    run_dir = run_training(cfg, resume=resume)
    from skyjo.plotting import plot_run

    console.print(f"dashboard: {plot_run(run_dir)}")


@app.command()
def plot(run_dir: Path, out: Path | None = None) -> None:
    """Write a dashboard PNG (learning rate, losses, eval win rates) for a run."""
    from skyjo.plotting import plot_run

    console.print(f"wrote {plot_run(run_dir, out)}")


def _render_board(view: tuple[int, ...]) -> list[str]:
    def cell(v: int) -> str:
        return " ##" if v == HIDDEN else "  ." if v == REMOVED else f"{v:3d}"

    return ["".join(cell(view[column_positions(c)[r]]) for c in range(4)) for r in range(3)]


@app.command()
def watch(agents: AgentsOpt = "ev,greedy", seed: int = 0, rounds: int = 1) -> None:
    """Print a game turn by turn (debugging aid for humans and agents)."""
    from skyjo.game.engine import Game

    lineup = [make_agent(s, seed=seed + i) for i, s in enumerate(_split(agents))]
    game = Game(RulesConfig(n_players=len(lineup)), seed=seed)
    while not game.is_over and len(game.rounds) < rounds:
        seat = game.current_player
        obs = game.observe(seat)
        action = lineup[seat].act(obs, game.legal_actions())
        console.print(
            f"[bold]r{obs.round_index} t{obs.turn}[/] seat {seat} ({lineup[seat].name}) "
            f"{obs.phase.name:<13} discard={obs.discard_top} hand={obs.hand} -> {describe(action)}"
        )
        result = game.step(action)
        if obs.phase.name.startswith("PLACE"):
            for line in _render_board(game.observe(seat).boards[seat]):
                console.print("      " + line)
        if result:
            console.print(
                f"[green]round over[/] scores={result.scores} raw={result.raw_scores} "
                f"finisher={result.finisher} doubled={result.doubled}"
            )


@app.command()
def bench(steps: int = 20_000, workers: int = 0, num_envs: int = 64) -> None:
    """Measure environment throughput (learner steps / second)."""
    import numpy as np

    from skyjo.rl.env import EnvConfig
    from skyjo.rl.vec_env import make_vec_env

    envs = make_vec_env(EnvConfig(opponents={"greedy": 1.0}), num_envs, workers)
    _, masks = envs.reset()
    rng = np.random.default_rng(0)
    t0 = time.time()
    n = 0
    while n < steps:
        actions = np.array([rng.choice(np.flatnonzero(m)) for m in masks])
        _, masks, _, _, _ = envs.step(actions)
        n += num_envs
    dt = time.time() - t0
    envs.close()
    console.print(f"{n / dt:,.0f} learner steps/s  (workers={workers}, num_envs={num_envs})")
