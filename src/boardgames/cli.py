"""`bg serve` runs the web server for every game; `bg <game> ...` holds each game's bot and training tools."""

from __future__ import annotations

import importlib
import logging
from pathlib import Path
from typing import Annotated

import typer
from rich.console import Console

from boardgames.games import GAME_KEYS, UNFINISHED_KEYS

app = typer.Typer(add_completion=False, no_args_is_help=True, help="Board games: the web server and the bots")
console = Console()

# Games that have their own commands (bot matches, training…), mounted as `bg <key> <command>`.
GAME_TOOLS = {
    "avel": "Chronicles of Avel: bot win rates",
    "avenue": "Agent Avenue: bot matches",
    "karak": "Karak: bot matches and AI training",
    "lostcities": "Lost Cities: bot matches",
    "pandemic": "Pandemic: bot win rates",
    "phase10": "Phase 10: bot matches",
    "toybattle": "Toy Battle: bot matches and terrain balance",
    "skyjo": "Skyjo: strategies, tournaments and RL training",
    "ttr": "Ticket to Ride: Europe: bot matches",
}
for _key, _help in GAME_TOOLS.items():
    app.add_typer(importlib.import_module(f"{_key}.cli").app, name=_key, help=_help)


@app.command()
def serve(
    host: Annotated[str, typer.Option(help="Interface to bind; 0.0.0.0 lets your LAN join")] = "0.0.0.0",
    port: int = 8000,
    public_url: Annotated[str | None, typer.Option(help="Base URL used in invite links")] = None,
    tunnel: Annotated[bool, typer.Option(help="Open a public cloudflared tunnel and invite through it")] = False,
    unfinished: Annotated[
        bool, typer.Option(help=f"Also offer games still in the works ({', '.join(UNFINISHED_KEYS)})")
    ] = False,
    avenue_think: Annotated[float, typer.Option(help="Agent Avenue: max seconds the bot thinks per move")] = 1.0,
    codenames_pictures: Annotated[
        Path | None, typer.Option(help="Codenames: folder of your own images (20+), offered as an extra deck")
    ] = None,
    codenames_test: Annotated[
        bool, typer.Option(help="Codenames: fake players you can switch between, to try every role yourself")
    ] = False,
    skyjo_models: Annotated[
        list[Path] | None,
        typer.Option(help="Skyjo: folders with <run>/policy_best.npz offered as AI bots (default: shipped + runs/)"),
    ] = None,
    skyjo_bot: Annotated[
        list[str] | None, typer.Option(help="Skyjo: extra bot spec, e.g. 'ev:reveal_bonus=0.5'")
    ] = None,
    skyteam_progress: Annotated[
        Path | None, typer.Option(help="Sky Team: file that remembers finished scenarios (default ./progress.json)")
    ] = None,
) -> None:
    """Host every game. Create a room, share its link, vote for a game and play."""
    import uvicorn

    from boardgames.net import TunnelError, lan_ip, start_tunnel
    from boardgames.server import create_app

    ip = lan_ip() if host == "0.0.0.0" else None
    lan_url = f"http://{ip}:{port}" if ip else None
    proc = None
    if tunnel:
        try:
            proc, public_url = start_tunnel(port)
        except TunnelError as e:
            raise typer.BadParameter(str(e)) from None
    skyjo: dict[str, object] = {"bots": skyjo_bot or []}
    if skyjo_models:
        skyjo["model_dirs"] = skyjo_models
    options: dict[str, dict[str, object]] = {
        "avenue": {"think": avenue_think},
        "codenames": {"pictures": codenames_pictures, "test": codenames_test},
        "skyjo": skyjo,
        "skyteam": {"progress": skyteam_progress},
    }
    only = (*GAME_KEYS, *UNFINISHED_KEYS) if unfinished else None
    web = create_app(public_url=public_url, lan_url=lan_url, game_options=options, only=only)
    console.print("[bold yellow]Board games server[/]")
    console.print(f"  local:   http://localhost:{port}")
    if lan_url:
        console.print(f"  network: {lan_url}   (same Wi-Fi / LAN)")
    if public_url:
        console.print(f"  public:  {public_url}")
    elif not lan_url:
        console.print("[dim]  bind --host 0.0.0.0 or use --tunnel to invite people from other machines")
    console.print(f"  games:   {', '.join(g.title for g in web.state.hub.games.values())}")
    console.print("[dim]  room activity is logged below (Ctrl+C to stop)\n")
    _log_activity()
    try:
        uvicorn.run(web, host=host, port=port, log_level="warning")
    finally:
        if proc is not None:
            proc.terminate()


def _log_activity() -> None:
    """Rooms and tables log who joins, what starts and how it ends; print that on the console."""
    handler = logging.StreamHandler()
    handler.setFormatter(logging.Formatter("%(asctime)s  %(message)s", datefmt="%H:%M:%S"))
    for name in ("boardgames", *GAME_KEYS, *UNFINISHED_KEYS):
        logger = logging.getLogger(name)
        logger.addHandler(handler)
        logger.setLevel(logging.INFO)
        logger.propagate = False


def main() -> None:
    app()
