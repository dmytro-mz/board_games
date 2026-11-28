"""Serve a pre-played table and screenshot it (visual checks during development).

uv run python scripts/demo.py [--stage play|drawn|laid|handover|over|lobby|home] [--bots 3] [--size 1440x900]
                              [--out shots/game.png] [--serve]
"""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import sys
from collections.abc import AsyncIterator, Callable
from pathlib import Path

import uvicorn
from starlette.applications import Starlette

from boardgames.testing import game_app
from phase10.game.engine import Step
from phase10.web.room import Room

TOKEN = "d" * 32
PORT = 8765
STAGES = ["play", "drawn", "laid", "handover", "over", "lobby", "home"]


def prepare(stage: str = "play", bots: int = 3, seed: int = 3, delay_scale: float = 0.0, last_phase: int = 10) -> Room:
    """A room with one human ("Dima", token TOKEN) and bots, fast-forwarded to `stage`."""
    room = Room("DEMO", delay_scale=delay_scale, seed=seed)
    me = room.join(TOKEN, "Dima")
    for key in ["pro", "regular", "rookie", "pro", "regular"][:bots]:
        room.handle(me.id, {"type": "add_bot", "bot": key})
    room.settings.last_phase = last_phase
    if stage == "lobby":
        return room
    room.handle(me.id, {"type": "start"})
    seat = room.seat_of(me.id)
    game = room.game
    assert seat is not None and game is not None
    room.seats[seat].autoplay = True

    def run_until(done: Callable[[], bool], limit: int = 50_000) -> None:
        for _ in range(limit):
            if done() or room.status != "playing":
                return
            plan = room.plan()
            assert plan is not None
            plan[1]()

    my_draw = lambda: game.current == seat and game.step == Step.DRAW  # noqa: E731
    match stage:
        case "play":
            run_until(lambda: my_draw() and game.turn > 2 * game.n)
        case "drawn":
            run_until(lambda: my_draw() and game.turn > 2 * game.n)
        case "laid":
            run_until(lambda: my_draw() and game.laid[seat] and len(game.groups) >= 4 and game.hand_no >= 2)
        case "handover":
            run_until(lambda: game.step == Step.HAND_OVER and game.hand_no >= 2)
        case "over":
            run_until(lambda: room.status == "game_over")
    room.seats[seat].autoplay = False
    if stage == "drawn" and room.status == "playing":
        room.handle(me.id, {"type": "action", "action": {"type": "draw_deck"}})
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
        yield f"http://127.0.0.1:{port}/g/phase10/r/{room.id}?me={TOKEN}"
    finally:
        server.should_exit = True
        await task


async def run(args: argparse.Namespace) -> None:
    room = prepare(args.stage, args.bots, args.seed, last_phase=args.phases)
    room.delay_scale = 1.0
    app = game_app("phase10")
    async with serving(app, room, args.port) as url:
        w, h = args.size.split("x")
        Path(args.out).parent.mkdir(parents=True, exist_ok=True)
        shot = Path(__file__).with_name("shot.py")
        target = url if args.stage != "home" else url.split("/g/")[0] + "/"
        proc = await asyncio.create_subprocess_exec(sys.executable, str(shot), target, args.out, w, h)
        await proc.wait()
        if args.serve:
            print(f"serving {url}  (Ctrl+C to stop)")
            await asyncio.Event().wait()


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--bots", type=int, default=3)
    ap.add_argument("--stage", default="play", choices=STAGES)
    ap.add_argument("--size", default="1440x900")
    ap.add_argument("--out", default="shots/game.png")
    ap.add_argument("--serve", action="store_true", help="keep serving after the screenshot")
    ap.add_argument("--seed", type=int, default=3)
    ap.add_argument("--phases", type=int, default=10)
    ap.add_argument("--port", type=int, default=PORT)
    asyncio.run(run(ap.parse_args()))


if __name__ == "__main__":
    main()
