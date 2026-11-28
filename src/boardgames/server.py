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

from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.routing import BaseRoute, Mount, Route, WebSocketRoute
from starlette.websockets import WebSocket, WebSocketDisconnect

from boardgames.games import Backend, GameRoom, GameSpec, load_games
from boardgames.net import CachedJSON, Connection, PageRewriter, StaticDir, client_origin, error
from boardgames.party import Party, PartyError
from boardgames.table import shutdown_bots

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


class TooManyRooms(Exception):
    pass


class Router:
    """Routes a game adds under /g/<key>/ (`Backend.routes`): `@router.get("/api/x")` on a handler that returns
    JSON-able data, with the path parameters as keyword arguments."""

    def __init__(self) -> None:
        self.routes: list[BaseRoute] = []

    def get(self, path: str, constant: bool = False) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
        """`constant`: the answer never changes while the server runs (encoded once, revalidated by ETag)."""
        return self._add(path, ["GET"], constant)

    def post(self, path: str) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
        return self._add(path, ["POST"])

    def _add(
        self, path: str, methods: list[str], constant: bool = False
    ) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
        def decorate(fn: Callable[..., Any]) -> Callable[..., Any]:
            cached: list[CachedJSON] = []

            async def endpoint(request: Request) -> Response:
                if cached:
                    return cached[0].response(request)
                out = await fn(**request.path_params)
                if isinstance(out, Response):
                    return out
                if constant:
                    cached.append(CachedJSON(out))
                    return cached[0].response(request)
                return JSONResponse(out)

            self.routes.append(Route(path, endpoint, methods=methods))
            return fn

        return decorate

    def websocket(self, path: str) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
        def decorate(fn: Callable[..., Any]) -> Callable[..., Any]:
            async def endpoint(ws: WebSocket) -> None:
                await fn(ws, **ws.path_params)

            self.routes.append(WebSocketRoute(path, endpoint))
            return fn

        return decorate


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
            raise TooManyRooms("Too many rooms open, try again later")
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


async def _socket_loop(ws: WebSocket, conn: Connection, handle: Callable[[dict[str, Any]], bool]) -> None:
    """Feed a socket's messages to `handle` (returns False to stop) until it closes."""
    try:
        while True:
            msg = await ws.receive_json()
            if isinstance(msg, dict) and not handle(msg):
                break
    except (WebSocketDisconnect, ValueError, RuntimeError):
        pass


def create_app(
    public_url: str | None = None,
    lan_url: str | None = None,
    delay_scale: float = 1.0,
    game_options: dict[str, dict[str, Any]] | None = None,
    only: Iterable[str] | None = None,
) -> Starlette:
    """`game_options` holds each game's extra server options ({"skyjo": {"model_dirs": [...]}}); `only` limits the
    catalogue to some games (tests)."""
    games = load_games(tuple(only)) if only is not None else load_games()
    options = game_options or {}
    backends = {key: spec.backend(delay_scale=delay_scale, **options.get(key, {})) for key, spec in games.items()}
    hub = Hub(games, backends)
    platform = StaticDir(STATIC, "/static")

    @contextlib.asynccontextmanager
    async def lifespan(_: Starlette) -> AsyncIterator[None]:
        sweeper = asyncio.create_task(hub.sweep())
        yield
        sweeper.cancel()
        hub.close()
        shutdown_bots()

    # ------------------------------------------------------------------ platform
    def tiles() -> list[dict[str, Any]]:
        out = []
        for spec in games.values():
            thumb = STATIC / "thumbs" / f"{spec.key}.avif"
            out.append({**spec.public(), "thumb": platform.url(f"thumbs/{spec.key}.avif") if thumb.exists() else None})
        return out

    async def config(request: Request) -> Response:
        return JSONResponse({"public_url": public_url, "lan_url": lan_url, "games": tiles()})

    async def create_room(request: Request) -> Response:
        try:
            return JSONResponse({"room": hub.create().id})
        except TooManyRooms as e:
            return error(503, str(e))

    async def room_info(request: Request) -> Response:
        party = hub.get(request.path_params["code"])
        if party is None:
            return error(404, "No room with that code")
        return JSONResponse(
            {"room": party.id, "phase": party.phase, "game": party.game_key, "players": len(party.online())}
        )

    async def party_socket(ws: WebSocket) -> None:
        await ws.accept()
        party = hub.get(ws.path_params["code"])
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

        def handle(msg: dict[str, Any]) -> bool:
            try:
                party.handle(member.id, msg)
            except PartyError as e:
                conn.send({"type": "error", "message": str(e)})
            except Exception:
                log.exception("room %s: request failed", party.id)
                conn.send({"type": "error", "message": "Server error"})
            return True

        try:
            await _socket_loop(ws, conn, handle)
        finally:
            party.disconnect(conn)
            pump.cancel()

    room_page = PageRewriter(STATIC / "index.html", platform)

    async def index(request: Request) -> Response:
        return room_page.response(request)

    routes: list[BaseRoute] = [
        Route("/api/config", config),
        Route("/api/rooms", create_room, methods=["POST"]),
        Route("/api/rooms/{code}", room_info),
        WebSocketRoute("/ws/{code}", party_socket),
        Route("/", index),
        Route("/r/{code}", index),
    ]
    # ------------------------------------------------------------------ games
    for spec in games.values():
        routes.append(
            Mount(f"/g/{spec.key}", routes=_game_routes(spec, backends[spec.key], hub, platform, public_url, lan_url))
        )
    routes.append(Mount("/static", app=platform))

    app = Starlette(routes=routes, lifespan=lifespan)
    app.state.hub = hub
    return app


def _game_routes(
    spec: GameSpec, backend: Backend, hub: Hub, platform: StaticDir, public_url: str | None, lan_url: str | None
) -> list[BaseRoute]:
    error_type = spec.error
    on_connect = getattr(backend, "on_connect", None)
    on_message = getattr(backend, "on_message", None)
    own = StaticDir(spec.static, f"/g/{spec.key}/static")
    page = PageRewriter(spec.static / "index.html", own, platform)
    game_config = CachedJSON({"public_url": public_url, "lan_url": lan_url, **backend.config()})

    async def config(request: Request) -> Response:
        return game_config.response(request)

    async def quick_table(request: Request) -> Response:
        """Open a table of this game without voting (browser checks, tests; the room page uses /api/rooms)."""
        try:
            return JSONResponse({"room": hub.create_table(spec.key).id})
        except TooManyRooms as e:
            return error(503, str(e))

    async def room_info(request: Request) -> Response:
        found = hub.table(spec.key, request.path_params["code"])
        if found is None:
            return error(404, "No table with that code")
        room = found[1]
        return JSONResponse({"room": room.id, "status": room.status, "players": _seated(room)})

    async def table_socket(ws: WebSocket) -> None:
        await ws.accept()
        found = hub.table(spec.key, ws.path_params["code"])
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
        except error_type as e:
            await ws.send_json({"type": "fatal", "message": str(e)})
            await ws.close()
            return
        conn = Connection(ws, member.id)
        pump = asyncio.create_task(conn.pump())
        room.connect(conn)
        if on_connect is not None:
            on_connect(room, conn)

        def handle(msg: dict[str, Any]) -> bool:
            if party.room is not room:
                conn.send({"type": "fatal", "message": "The room went back to choosing a game."})
                return False
            try:
                if on_message is not None and on_message(room, conn, msg):
                    return True
                reply = room.handle(conn.member_id, msg)
            except error_type as e:
                conn.send({"type": "error", "message": str(e)})
            except Exception:
                log.exception("table %s: request failed", room.id)
                conn.send({"type": "error", "message": "Server error"})
            else:
                if reply is not None:
                    conn.send(reply)
            party.game_changed()
            return True

        try:
            await _socket_loop(ws, conn, handle)
        finally:
            conn.member_id = member.id  # test tools may have switched the socket to another member
            room.disconnect(conn)
            pump.cancel()

    async def index(request: Request) -> Response:
        return page.response(request)

    router = Router()
    if hasattr(backend, "routes"):
        backend.routes(router)
    routes: list[BaseRoute] = [
        Route("/api/config", config),
        Route("/api/rooms", quick_table, methods=["POST"]),
        Route("/api/rooms/{code}", room_info),
        WebSocketRoute("/ws/{code}", table_socket),
        Route("/", index),
        Route("/r/{code}", index),
        *router.routes,
    ]
    mounts = getattr(backend, "mounts", dict)()
    for name, folder in mounts.items():
        routes.append(Mount(f"/{name}", app=StaticDir(folder, f"/g/{spec.key}/{name}")))
    routes.append(Mount("/static", app=own))
    return routes
