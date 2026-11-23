"""Serve a pre-played table and screenshot it (visual checks during development).

uv run python scripts/demo.py [--stage lobby|play|recruit|over] [--mode simple|advanced] [--players 2|3|4]
                              [--turns 4] [--size 1440x900] [--out shots/game.png] [--serve]
"""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import sys
from collections.abc import AsyncIterator
from pathlib import Path

import uvicorn
from fastapi import FastAPI

from avenue.game.engine import Phase
from avenue.web.room import Room
from boardgames.testing import game_app

TOKEN = "d" * 32
PORT = 8766


def prepare(stage: str = "play", mode: str = "simple", players: int = 2, turns: int = 4, seed: int = 3) -> Room:
    """A room with one human ("Dima", token TOKEN) and bots, fast-forwarded to `stage` (tries more seeds if needed)."""
    for attempt in range(40):
        room = _prepare(stage, mode, players, turns, seed + attempt * 101)
        if stage in ("lobby", "over") or room.status == "playing":
            return room
    return room


def _prepare(stage: str, mode: str, players: int, turns: int, seed: int) -> Room:
    room = Room("DEMO", delay_scale=0.0, seed=seed)
    me = room.join(TOKEN, "Dima")
    room.handle(me.id, {"type": "settings", "changes": {"mode": mode, "bot_speed": "fast"}})
    teams = {2: [1], 3: [0, 1], 4: [0, 1, 1]}[players]
    for team in teams:
        room.handle(me.id, {"type": "add_bot", "team": team})
    if stage == "lobby":
        return room
    room.handle(me.id, {"type": "start"})
    seat = room.seat_of(me.id)
    game = room.game
    assert seat is not None and game is not None
    for bot in room.seats:
        if bot.agent is not None:
            bot.agent.budget = 0.05  # type: ignore[attr-defined]
    room.seats[seat].autoplay = True
    room._autopilot.budget = 0.05
    target = 10_000 if stage == "over" else turns
    while room.status == "playing" and game.turn < target:
        room.step_bots(1)
    room.seats[seat].autoplay = False
    want = {"play": Phase.PLAY, "recruit": Phase.RECRUIT}.get(stage)
    for _ in range(200):
        if room.status != "playing" or want is None:
            break
        if seat in game.waiting() and game.phase == want and (want != Phase.PLAY or game.active == game.side_of[seat]):
            break
        if room.bot_turn() is None:
            room.seats[seat].autoplay = True
            room.step_bots(1)
            room.seats[seat].autoplay = False
        else:
            room.step_bots(1)
    return room


@contextlib.asynccontextmanager
async def serving(app: FastAPI, room: Room, port: int = PORT) -> AsyncIterator[str]:
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning"))
    task = asyncio.create_task(server.serve())
    while not server.started:
        await asyncio.sleep(0.05)
    app.state.manager.adopt(room)
    try:
        yield f"http://127.0.0.1:{port}/g/avenue/r/{room.id}?me={TOKEN}"
    finally:
        server.should_exit = True
        await task


async def run(args: argparse.Namespace) -> None:
    room = prepare(args.stage, args.mode, args.players, args.turns, args.seed)
    room.delay_scale = 1.0
    app = game_app("avenue")
    async with serving(app, room, args.port) as url:
        w, h = args.size.split("x")
        Path(args.out).parent.mkdir(parents=True, exist_ok=True)
        shot = Path(__file__).with_name("shot.py")
        proc = await asyncio.create_subprocess_exec(sys.executable, str(shot), url, args.out, w, h)
        await proc.wait()
        if args.serve:
            print(f"serving {url}  (Ctrl+C to stop)")
            await asyncio.Event().wait()


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--stage", default="play", choices=["lobby", "play", "recruit", "over"])
    ap.add_argument("--mode", default="simple", choices=["simple", "advanced"])
    ap.add_argument("--players", type=int, default=2, choices=[2, 3, 4])
    ap.add_argument("--turns", type=int, default=4)
    ap.add_argument("--size", default="1440x900")
    ap.add_argument("--out", default="shots/game.png")
    ap.add_argument("--serve", action="store_true", help="keep serving after the screenshot")
    ap.add_argument("--seed", type=int, default=3)
    ap.add_argument("--port", type=int, default=PORT)
    asyncio.run(run(ap.parse_args()))


if __name__ == "__main__":
    main()
