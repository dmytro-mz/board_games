"""Serve a pre-played Toy Battle table and screenshot it (visual checks during development).

uv run python scripts/toybattle/demo.py [--stage lobby|play|effect|over] [--terrain rug] [--turns 12] [--size 1440x900]
                                    [--out shots/toybattle/game.png] [--serve] [--spectator] [--red]
"""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import sys
from collections.abc import AsyncIterator
from pathlib import Path

import uvicorn
from starlette.applications import Starlette

from boardgames.testing import game_app
from toybattle.game.engine import Phase
from toybattle.web.room import Room

TOKEN = "d" * 32
PORT = 8766


def prepare(stage: str = "play", turns: int = 12, seed: int = 3, terrain: str = "rug", red: bool = False) -> Room:
    """A room with one human ("Dima", token TOKEN) and the bot, fast-forwarded to `stage`."""
    room = Room("DEMO", delay_scale=0.0, seed=seed, bot_budget=0.05)
    me = room.join(TOKEN, "Dima")
    room.handle(me.id, {"type": "add_bot", "bot": "general"})
    room.handle(me.id, {"type": "settings", "changes": {"terrain": terrain}})
    if red:
        room.handle(me.id, {"type": "swap"})
    if stage == "lobby":
        return room
    room.handle(me.id, {"type": "start"})
    seat = room.seat_of(me.id)
    game = room.game
    assert seat is not None and game is not None
    room.seats[seat].autoplay = True

    def step() -> None:
        room._apply(game.current, room._agent(game.current).act(game.view(game.current)))

    if stage == "over":
        while room.status == "playing":
            step()
    elif stage == "effect":
        for _ in range(400):
            if room.status != "playing":
                break
            pending = game.pending
            useful = pending is not None and pending.kind in ("knock", "recall", "move", "extra", "revive")
            if game.current == seat and game.phase == Phase.EFFECT and useful and game.turn >= turns // 2:
                break
            step()
    else:
        while room.status == "playing" and (game.turn < turns or game.current != seat or game.phase != Phase.TURN):
            step()
    room.seats[seat].autoplay = False
    room.delay_scale = 1.0
    room.busy_until = 0.0
    return room


@contextlib.asynccontextmanager
async def serving(app: Starlette, room: Room, port: int = PORT) -> AsyncIterator[str]:
    """Run the app in this event loop with `room` adopted; yields the player's personal URL."""
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning"))
    task = asyncio.create_task(server.serve())
    while not server.started:
        await asyncio.sleep(0.05)
    app.state.manager.adopt(room)
    try:
        yield f"http://127.0.0.1:{port}/g/toybattle/r/{room.id}?me={TOKEN}"
    finally:
        server.should_exit = True
        await task


async def run(args: argparse.Namespace) -> None:
    room = prepare(args.stage, args.turns, args.seed, args.terrain, args.red)
    app = game_app("toybattle")
    async with serving(app, room, args.port) as url:
        w, h = args.size.split("x")
        Path(args.out).parent.mkdir(parents=True, exist_ok=True)
        shot = Path(__file__).with_name("shot.py")
        target = url.split("?")[0] if args.spectator else url
        proc = await asyncio.create_subprocess_exec(sys.executable, str(shot), target, args.out, w, h)
        await proc.wait()
        if args.serve:
            print(f"serving {url}  (Ctrl+C to stop)")
            await asyncio.Event().wait()


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--turns", type=int, default=12)
    ap.add_argument("--stage", default="play", choices=["play", "effect", "over", "lobby"])
    ap.add_argument("--terrain", default="rug")
    ap.add_argument("--size", default="1440x900")
    ap.add_argument("--out", default="shots/toybattle/game.png")
    ap.add_argument("--serve", action="store_true", help="keep serving after the screenshot")
    ap.add_argument("--spectator", action="store_true", help="open the table as a fresh visitor")
    ap.add_argument("--red", action="store_true", help="the human plays Red (board turned around)")
    ap.add_argument("--seed", type=int, default=3)
    ap.add_argument("--port", type=int, default=PORT)
    asyncio.run(run(ap.parse_args()))


if __name__ == "__main__":
    main()
