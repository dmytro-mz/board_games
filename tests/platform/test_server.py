"""The platform over HTTP and WebSockets: rooms, the shell, every game's table behind /g/<key>/."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

import pytest
from fastapi.testclient import TestClient
from starlette.testclient import WebSocketTestSession

from boardgames.games import GAME_KEYS
from boardgames.server import create_app

TOKENS = ["a" * 32, "b" * 32]


@pytest.fixture(scope="module")
def client() -> Any:
    with TestClient(create_app(delay_scale=0.0)) as c:
        yield c


def _until(ws: WebSocketTestSession, kind: str, when: Any = None, **match: Any) -> dict[str, Any]:
    """The next message of this type whose fields match (and for which `when(msg)` holds)."""
    for _ in range(50):
        msg = ws.receive_json()
        if msg["type"] == kind and all(msg.get(k) == v for k, v in match.items()) and (when is None or when(msg)):
            return msg
    raise AssertionError(f"no {kind} {match}")


def test_pages_and_config(client: TestClient) -> None:
    assert client.get("/").status_code == 200
    assert client.get("/r/ABCDE").status_code == 200
    assert client.get("/static/app.js").status_code == 200
    assert client.get("/static/shared/platform.js").status_code == 200
    config = client.get("/api/config").json()
    assert [g["key"] for g in config["games"]] == list(GAME_KEYS)
    for g in config["games"]:
        assert g["min_players"] <= g["max_players"]
        assert g["thumb"] is None or client.get(g["thumb"]).status_code == 200
    assert client.get("/api/rooms/NOPE1").status_code == 404


@pytest.mark.parametrize("key", GAME_KEYS)
def test_every_game_is_served_under_its_prefix(client: TestClient, key: str) -> None:
    html = client.get(f"/g/{key}/r/ABCDE").text
    assert f'"/g/{key}/static/app.js"' in html
    assert client.get(f"/g/{key}/static/app.js").status_code == 200
    assert client.get(f"/g/{key}/api/config").status_code == 200


@contextmanager
def _launch(client: TestClient, key: str) -> Iterator[tuple[str, WebSocketTestSession]]:
    """A new room whose leader Ann voted for `key` and started it."""
    code = client.post("/api/rooms").json()["room"]
    with client.websocket_connect(f"/ws/{code}") as ws:
        ws.send_json({"type": "hello", "token": TOKENS[0], "name": "Ann"})
        _until(ws, "welcome")
        ws.send_json({"type": "vote", "game": key})
        _until(ws, "state", selected=key)
        ws.send_json({"type": "launch", "game": key})
        _until(ws, "state", phase="game")
        yield code, ws


@pytest.mark.parametrize("key", GAME_KEYS)
def test_every_game_table_plays_through_the_platform(client: TestClient, key: str) -> None:
    with _launch(client, key) as (code, _):
        assert client.get(f"/g/{key}/api/rooms/{code}").json()["status"] == "lobby"
        with client.websocket_connect(f"/g/{key}/ws/{code}") as table:
            table.send_json({"type": "hello", "token": TOKENS[0], "name": "Ann"})
            state = _until(table, "state")
            assert state["room"] == code
        # another game's socket for this room doesn't exist
        other = next(k for k in GAME_KEYS if k != key)
        with client.websocket_connect(f"/g/{other}/ws/{code}") as wrong:
            assert wrong.receive_json()["type"] == "fatal"


def test_the_party_leader_hosts_the_table(client: TestClient) -> None:
    with _launch(client, "lostcities") as (code, _), client.websocket_connect(f"/g/lostcities/ws/{code}") as guest:
        guest.send_json({"type": "hello", "token": TOKENS[1], "name": "Bob"})  # Bob reaches the table first
        welcome = _until(guest, "welcome")
        state = _until(guest, "state")
        assert state["host"] != welcome["you"]
        guest.send_json({"type": "start"})
        assert _until(guest, "error")["message"] == "Only the host can do that"


def test_back_to_selection_closes_the_table(client: TestClient) -> None:
    with _launch(client, "lostcities") as (code, ann):
        with client.websocket_connect(f"/ws/{code}") as bob:
            bob.send_json({"type": "hello", "token": TOKENS[1], "name": "Bob"})
            _until(bob, "welcome")
            ann.send_json({"type": "back_request"})
            back = _until(bob, "state", when=lambda m: m["back"])["back"]
            assert len(back["waiting"]) == 1
            bob.send_json({"type": "back_reply", "accept": True})
            assert _until(bob, "state", phase="select")["game"] is None
        with client.websocket_connect(f"/g/lostcities/ws/{code}") as table:
            assert table.receive_json()["type"] == "fatal"


def test_bad_handshakes(client: TestClient) -> None:
    with client.websocket_connect("/ws/NOPE1") as ws:
        assert ws.receive_json()["type"] == "fatal"
    code = client.post("/api/rooms").json()["room"]
    with client.websocket_connect(f"/ws/{code}") as ws:
        ws.send_json({"type": "hello", "token": "short"})
        assert ws.receive_json() == {"type": "fatal", "message": "Bad handshake"}
