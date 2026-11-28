"""Serve a pre-played table and screenshot it (visual checks during development).

uv run python scripts/demo.py [--stage play|draw|epidemic|infect|discard|over|lobby|home] [--bots 2]
                              [--size 1440x900] [--out shots/game.png] [--closed] [--serve]
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
from pandemic.game.engine import Step
from pandemic.web.room import Room

TOKEN = "d" * 32
PORT = 8765
STAGES = ["play", "draw", "epidemic", "infect", "discard", "over", "lobby", "home"]


def prepare(
    stage: str = "play",
    bots: int = 2,
    seed: int = 3,
    delay_scale: float = 0.0,
    closed: bool = False,
    epidemics: int = 5,
) -> Room:
    """A room with one human ("Dima", token TOKEN) and bots, fast-forwarded to `stage`."""
    for attempt in range(40):
        room = _try(stage, bots, seed + attempt * 101, delay_scale, closed, epidemics)
        if room is not None:
            return room
    raise SystemExit(f"could not reach stage {stage!r}")


def _try(stage: str, bots: int, seed: int, delay_scale: float, closed: bool, epidemics: int) -> Room | None:
    room = Room("DEMO", delay_scale=delay_scale, seed=seed)
    me = room.join(TOKEN, "Dima")
    room.handle(me.id, {"type": "sit"})
    for key in ["expert", "rookie", "expert"][:bots]:
        room.handle(me.id, {"type": "add_bot", "bot": key})
    room.handle(me.id, {"type": "settings", "changes": {"open_hands": not closed, "epidemics": epidemics}})
    if stage in ("lobby", "home"):
        return room
    room.handle(me.id, {"type": "start"})
    seat = room.seat_of(me.id)
    game = room.game
    assert seat is not None and game is not None
    room.seats[seat].autoplay = True

    def run_until(done: Callable[[], bool], limit: int = 20_000) -> bool:
        for _ in range(limit):
            if done():
                return True
            if room.status != "playing":
                return False
            plan = room.plan()
            assert plan is not None
            plan[1]()
        return False

    mine = lambda step: game.current == seat and game.step == step  # noqa: E731
    ok = {
        "play": lambda: run_until(lambda: mine(Step.ACTIONS) and game.turn > 2 * game.n),
        "draw": lambda: run_until(lambda: mine(Step.DRAW) and game.turn > 2 * game.n),
        "epidemic": lambda: run_until(lambda: mine(Step.EPIDEMIC)),
        "infect": lambda: run_until(lambda: mine(Step.INFECT) and game.epidemics_drawn >= 1),
        "discard": lambda: run_until(lambda: game.over_limit() == seat),
        "over": lambda: run_until(lambda: room.status == "game_over"),
    }[stage]()
    if not ok:
        return None
    room.seats[seat].autoplay = False
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
        yield f"http://127.0.0.1:{port}/g/pandemic/r/{room.id}?me={TOKEN}"
    finally:
        server.should_exit = True
        await task


async def run(args: argparse.Namespace) -> None:
    room = prepare(args.stage, args.bots, args.seed, closed=args.closed, epidemics=args.epidemics)
    room.delay_scale = 0.0 if args.freeze else 1.0
    if args.freeze:
        room.close()  # no bot moves while the screenshot is taken
    app = game_app("pandemic")
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
    ap.add_argument("--bots", type=int, default=2)
    ap.add_argument("--stage", default="play", choices=STAGES)
    ap.add_argument("--size", default="1440x900")
    ap.add_argument("--out", default="shots/game.png")
    ap.add_argument("--serve", action="store_true", help="keep serving after the screenshot")
    ap.add_argument("--closed", action="store_true", help="closed hands")
    ap.add_argument("--freeze", action="store_true", help="bots don't move")
    ap.add_argument("--seed", type=int, default=3)
    ap.add_argument("--epidemics", type=int, default=5)
    ap.add_argument("--port", type=int, default=PORT)
    asyncio.run(run(ap.parse_args()))


if __name__ == "__main__":
    main()
