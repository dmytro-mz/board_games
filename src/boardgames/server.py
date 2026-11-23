"""HTTP + WebSocket server for the platform and every game. Rooms live in memory; anyone with the link can join.

/                      create or join a room                       (platform client, static/)
/r/CODE                the room: game selection, then the game in an iframe
/ws/CODE               the party socket (members, votes, leader, back-to-selection)
/g/<game>/r/CODE       the game's own client for that room's table
/g/<game>/ws/CODE      the game table's socket (the game's own protocol, unchanged)
/g/<game>/api/config   the game's static data
POST /g/<game>/api/rooms  a room that opens this game's table right away (tests and browser checks)
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import secrets
import time
from collections.abc import AsyncIterator, Callable, Iterable
from pathlib import Path
from typing import Any

from fastapi import APIRouter, FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse

from boardgames.games import Backend, GameRoom, GameSpec, load_games
from boardgames.net import Connection, RevalidatedStatic, client_origin
from boardgames.party import Party, PartyError

log = logging.getLogger(__name__)

STATIC = Path(__file__).parent / "static"
CODE_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
CODE_LENGTH = 5
MAX_ROOMS = 500
ROOM_TTL = 3 * 3600.0  # seconds without any connection before a room is dropped
SWEEP_INTERVAL = 2.0
OVERVIEW_INTERVAL = 600.0


def run_game(room: GameRoom) -> Callable[[], None]:
    """Drive a game table (bots, timers, round transitions) until it is stopped."""
    task = asyncio.create_task(room.drive(), name=f"table-{room.id}")
    return task.cancel


class Hub:
    """All parties of this server."""

    def __init__(self, games: dict[str, GameSpec], backends: dict[str, Backend]) -> None:
        self.games = games
        self.backends = backends
        self.parties: dict[str, Party] = {}

    def _code(self) -> str:
        while True:
            code = "".join(secrets.choice(CODE_ALPHABET) for _ in range(CODE_LENGTH))
            if code not in self.parties:
                return code

    def create(self, code: str | None = None) -> Party:
        if len(self.parties) >= MAX_ROOMS:
            raise HTTPException(503, "Too many rooms open, try again later")
        party = Party(code or self._code(), self.games, self.backends, run_game=run_game)
        self.parties[party.id] = party
        return party

    def create_table(self, key: str) -> Party:
        """A room that skips the game selection and opens this game's table right away."""
        party = self.create()
        party.start_game(key)
        return party

    def adopt(self, key: str, room: GameRoom) -> GameRoom:
        """Open a prepared game table as its own room (tests and scripts; needs a running event loop)."""
        party = self.create(room.id)
        party.start_game(key, room)
        return room

    def get(self, code: str) -> Party | None:
        return self.parties.get(code.upper())

    def table(self, key: str, code: str) -> tuple[Party, GameRoom] | None:
        party = self.get(code)
        if party is None or party.room is None or party.game_key != key:
            return None
        return party, party.room

    def drop(self, code: str) -> None:
        party = self.parties.pop(code, None)
        if party is not None:
            party.close()
            if party.members:
                log.info("room %s closed · %d rooms open", code, len(self.parties))

    def overview(self) -> str:
        live = [party for party in self.parties.values() if party.online()]
        if not live:
            return "no rooms open"
        return "\n".join([f"{len(live)} rooms open:", *(f"  {party.describe()}" for party in live)])

    async def sweep(self) -> None:
        last_overview, last_text = time.monotonic(), "no rooms open"
        while True:
            await asyncio.sleep(SWEEP_INTERVAL)
            for code, party in list(self.parties.items()):
                if party.idle_for > ROOM_TTL:
                    self.drop(code)
                    continue
                party.check_leader()
                party.game_changed()
            if time.monotonic() - last_overview >= OVERVIEW_INTERVAL:
                last_overview, text = time.monotonic(), self.overview()
                if text != last_text:
                    log.info(text)
                    last_text = text

    def close(self) -> None:
        for code in list(self.parties):
            self.drop(code)


async def _hello(ws: WebSocket) -> dict[str, Any] | None:
    """The first message of every socket: {token, name}. None if it is missing or malformed."""
    try:
        hello = await ws.receive_json()
    except (WebSocketDisconnect, ValueError):
        return None
    token = hello.get("token") if isinstance(hello, dict) else None
    if not isinstance(token, str) or not 16 <= len(token) <= 64:
        await ws.send_json({"type": "fatal", "message": "Bad handshake"})
        await ws.close()
        return None
    return hello


def _seated(room: GameRoom) -> int:
    """How many seats are taken (games without seats count their members)."""
    seats = getattr(room, "seats", None)
    if isinstance(seats, dict):
        return sum(1 for s in seats.values() if s)
    return len(seats) if seats is not None else len(room.members)


def _index(path: Path) -> Callable[..., Any]:
    async def index(code: str | None = None) -> FileResponse:
        return FileResponse(path, headers={"Cache-Control": "no-cache"})

    return index


def create_app(
    public_url: str | None = None,
    lan_url: str | None = None,
    delay_scale: float = 1.0,
    game_options: dict[str, dict[str, Any]] | None = None,
    only: Iterable[str] | None = None,
) -> FastAPI:
    """`game_options` holds each game's extra server options ({"skyjo": {"model_dirs": [...]}}); `only` limits the
    catalogue to some games (tests)."""
    games = load_games(tuple(only)) if only is not None else load_games()
    options = game_options or {}
    backends = {key: spec.backend(delay_scale=delay_scale, **options.get(key, {})) for key, spec in games.items()}
    hub = Hub(games, backends)

    @contextlib.asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        sweeper = asyncio.create_task(hub.sweep())
        yield
        sweeper.cancel()
        hub.close()

    app = FastAPI(title="Board games", lifespan=lifespan, docs_url=None, redoc_url=None)
    app.state.hub = hub

    # ------------------------------------------------------------------ platform
    tiles = []
    for spec in games.values():
        thumb = STATIC / "thumbs" / f"{spec.key}.jpg"
        tiles.append({**spec.public(), "thumb": f"/static/thumbs/{spec.key}.jpg" if thumb.exists() else None})

    @app.get("/api/config")
    async def config() -> dict[str, Any]:
        return {"public_url": public_url, "lan_url": lan_url, "games": tiles}

    @app.post("/api/rooms")
    async def create_room() -> dict[str, str]:
        return {"room": hub.create().id}

    @app.get("/api/rooms/{code}")
    async def room_info(code: str) -> dict[str, Any]:
        party = hub.get(code)
        if party is None:
            raise HTTPException(404, "No room with that code")
        return {"room": party.id, "phase": party.phase, "game": party.game_key, "players": len(party.online())}

    @app.websocket("/ws/{code}")
    async def party_socket(ws: WebSocket, code: str) -> None:
        await ws.accept()
        party = hub.get(code)
        if party is None:
            await ws.send_json({"type": "fatal", "message": "This room doesn't exist (anymore)."})
            await ws.close()
            return
        hello = await _hello(ws)
        if hello is None:
            return
        try:
            member = party.join(hello["token"], hello.get("name"), client_origin(ws))
        except PartyError as e:
            await ws.send_json({"type": "fatal", "message": str(e)})
            await ws.close()
            return
        conn = Connection(ws, member.id)
        pump = asyncio.create_task(conn.pump())
        party.connect(conn)
        try:
            while True:
                msg = await ws.receive_json()
                if not isinstance(msg, dict):
                    continue
                try:
                    party.handle(member.id, msg)
                except PartyError as e:
                    conn.send({"type": "error", "message": str(e)})
                except Exception:
                    log.exception("room %s: request failed", party.id)
                    conn.send({"type": "error", "message": "Server error"})
        except (WebSocketDisconnect, ValueError, RuntimeError):
            pass
        finally:
            party.disconnect(conn)
            pump.cancel()

    index = _index(STATIC / "index.html")
    app.get("/")(index)
    app.get("/r/{code}")(index)

    # ------------------------------------------------------------------ games
    for spec in games.values():
        app.include_router(_game_router(spec, backends[spec.key], hub, public_url, lan_url), prefix=f"/g/{spec.key}")
        mounts = getattr(backends[spec.key], "mounts", dict)()
        for name, folder in mounts.items():
            app.mount(f"/g/{spec.key}/{name}", RevalidatedStatic(directory=folder), name=f"{spec.key}-{name}")
        app.mount(f"/g/{spec.key}/static", RevalidatedStatic(directory=spec.static), name=f"{spec.key}-static")

    app.mount("/static", RevalidatedStatic(directory=STATIC), name="static")
    return app


def _game_router(spec: GameSpec, backend: Backend, hub: Hub, public_url: str | None, lan_url: str | None) -> APIRouter:
    router = APIRouter()
    error = spec.error
    on_connect = getattr(backend, "on_connect", None)
    on_message = getattr(backend, "on_message", None)

    @router.get("/api/config")
    async def config() -> dict[str, Any]:
        return {"public_url": public_url, "lan_url": lan_url, **backend.config()}

    @router.post("/api/rooms")
    async def quick_table() -> dict[str, str]:
        """Open a table of this game without voting (browser checks, tests; the room page uses /api/rooms)."""
        return {"room": hub.create_table(spec.key).id}

    @router.get("/api/rooms/{code}")
    async def room_info(code: str) -> dict[str, Any]:
        found = hub.table(spec.key, code)
        if found is None:
            raise HTTPException(404, "No table with that code")
        room = found[1]
        return {"room": room.id, "status": room.status, "players": _seated(room)}

    @router.websocket("/ws/{code}")
    async def table_socket(ws: WebSocket, code: str) -> None:
        await ws.accept()
        found = hub.table(spec.key, code)
        if found is None:
            await ws.send_json({"type": "fatal", "message": "This table doesn't exist (anymore)."})
            await ws.close()
            return
        party, room = found
        hello = await _hello(ws)
        if hello is None:
            return
        try:
            member = room.join(hello["token"], hello.get("name"), client_origin(ws))
        except error as e:
            await ws.send_json({"type": "fatal", "message": str(e)})
            await ws.close()
            return
        conn = Connection(ws, member.id)
        pump = asyncio.create_task(conn.pump())
        room.connect(conn)
        if on_connect is not None:
            on_connect(room, conn)
        try:
            while True:
                msg = await ws.receive_json()
                if not isinstance(msg, dict):
                    continue
                if party.room is not room:
                    conn.send({"type": "fatal", "message": "The room went back to choosing a game."})
                    break
                try:
                    if on_message is not None and on_message(room, conn, msg):
                        continue
                    reply = room.handle(conn.member_id, msg)
                except error as e:
                    conn.send({"type": "error", "message": str(e)})
                except Exception:
                    log.exception("table %s: request failed", room.id)
                    conn.send({"type": "error", "message": "Server error"})
                else:
                    if reply is not None:
                        conn.send(reply)
                party.game_changed()
        except (WebSocketDisconnect, ValueError, RuntimeError):
            pass
        finally:
            conn.member_id = member.id  # test tools may have switched the socket to another member
            room.disconnect(conn)
            pump.cancel()

    index = _index(spec.static / "index.html")
    router.get("/")(index)
    router.get("/r/{code}")(index)
    if hasattr(backend, "routes"):
        backend.routes(router)
    return router
