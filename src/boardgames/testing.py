"""One game as if it were served alone, for each game's tests and browser-check scripts.

app = game_app("lostcities", delay_scale=0.0)    # the platform with only this game
app.state.manager.adopt(Room("DEMO", ...))       # open a prepared table: /g/lostcities/r/DEMO
with GameClient("lostcities") as client:         # /api, /ws, /r, /static are the game's own paths
    code = client.post("/api/rooms").json()["room"]
"""

from __future__ import annotations

from typing import Any

from starlette.applications import Starlette
from starlette.testclient import TestClient

from boardgames.games import GameRoom
from boardgames.server import Hub, create_app


class Tables:
    """One game's open tables (what each game's own server used to call its room manager)."""

    def __init__(self, hub: Hub, key: str) -> None:
        self.hub = hub
        self.key = key

    @property
    def rooms(self) -> dict[str, GameRoom]:
        return {code: p.room for code, p in self.hub.parties.items() if p.game_key == self.key and p.room is not None}

    def adopt(self, room: GameRoom) -> GameRoom:
        """Open a prepared table (needs a running event loop, e.g. inside a request or the server's loop)."""
        return self.hub.adopt(self.key, room)

    def create(self) -> GameRoom:
        return self.hub.create_table(self.key).room  # type: ignore[return-value]


def game_app(key: str, delay_scale: float = 1.0, **options: Any) -> Starlette:
    """The platform with only this game; `app.state.manager` holds its tables."""
    app = create_app(delay_scale=delay_scale, game_options={key: options}, only=[key])
    app.state.manager = Tables(app.state.hub, key)
    return app


class GameClient(TestClient):
    """A TestClient for one game: game-relative paths (/api/..., /ws/CODE, /r/CODE, /static/...) go to /g/<key>/."""

    def __init__(self, key: str, delay_scale: float = 1.0, **options: Any) -> None:
        super().__init__(game_app(key, delay_scale=delay_scale, **options))
        self.key = key

    def _game_path(self, url: Any) -> Any:
        if isinstance(url, str) and url.startswith("/") and not url.startswith("/g/"):
            return f"/g/{self.key}{url}"
        return url

    def request(self, method: str, url: Any, *args: Any, **kwargs: Any) -> Any:  # type: ignore[override]
        return super().request(method, self._game_path(url), *args, **kwargs)

    def websocket_connect(self, url: str, *args: Any, **kwargs: Any) -> Any:  # type: ignore[override]
        return super().websocket_connect(self._game_path(url), *args, **kwargs)
