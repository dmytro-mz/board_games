"""Room protocol: lobby, teams, hidden information in snapshots, bots driving a whole game, the HTTP server."""

from __future__ import annotations

import asyncio
import json
import time
from typing import Any

import pytest

from avenue.game.engine import Phase
from avenue.web.room import Room, RoomError
from boardgames.testing import GameClient


class Sink:
    def __init__(self, member_id: str) -> None:
        self.member_id = member_id
        self.messages: list[dict[str, Any]] = []

    def send(self, message: dict[str, Any]) -> None:
        self.messages.append(message)


def fast(room: Room) -> None:
    for seat in room.seats:
        if seat.agent is not None:
            seat.agent.budget = 0.01  # type: ignore[attr-defined]
            seat.agent.max_iters = 6  # type: ignore[attr-defined]
    room._autopilot.budget = 0.01
    room._autopilot.max_iters = 6


def two_humans() -> tuple[Room, Any, Any, Sink, Sink]:
    room = Room("TEST", delay_scale=0.0, seed=1)
    a = room.join("a" * 32, "Ann")
    b = room.join("b" * 32, "Bob")
    sa, sb = Sink(a.id), Sink(b.id)
    room.connect(sa)
    room.connect(sb)
    return room, a, b, sa, sb


def test_lobby_teams_and_settings():
    room, a, b, _, _ = two_humans()
    assert [s.team for s in room.seats] == [0, 1]
    with pytest.raises(RoomError):
        room.handle(b.id, {"type": "settings", "changes": {"mode": "advanced"}})
    room.handle(a.id, {"type": "settings", "changes": {"mode": "advanced"}})
    assert room.settings.mode == "advanced"
    room.handle(a.id, {"type": "add_bot", "team": 1})
    room.handle(a.id, {"type": "add_bot", "team": 0})
    with pytest.raises(RoomError):
        room.handle(a.id, {"type": "add_bot", "team": 0})  # a team has at most 2 players
    assert len(room.seats) == 4
    room.handle(a.id, {"type": "remove_seat", "seat": 3})
    room.handle(b.id, {"type": "sit", "team": 0})
    assert [s.team for s in room.seats] == [0, 0, 1]


def test_start_needs_both_teams():
    room = Room("T", delay_scale=0.0)
    a = room.join("a" * 32, "Ann")
    with pytest.raises(RoomError):
        room.handle(a.id, {"type": "start"})
    room.handle(a.id, {"type": "add_bot"})
    room.handle(a.id, {"type": "start"})
    assert room.status == "playing" and room.game is not None


def find_down_hidden(messages: list[dict[str, Any]]) -> None:
    for m in messages:
        if m["type"] != "state" or not m.get("game"):
            continue
        g = m["game"]
        me = m["you"]["seat"]
        if g["down"] is not None and g["down"]["player"] != me:
            assert g["down"]["card"] is None
        ev = m.get("event") or {}
        for e in ev.get("events", []):
            if e.get("player") == me:
                continue
            if e["kind"] == "draw":
                assert all(c is None for c in e["cards"])
            if e["kind"] == "discard":
                assert e["card"] is None
            if e["kind"] == "play":
                assert e["down"] is None


def test_hidden_information_never_reaches_the_other_player():
    room, a, b, sa, sb = two_humans()
    room.handle(a.id, {"type": "start"})
    game = room.game
    assert game is not None
    for _ in range(200):
        if room.status != "playing":
            break
        seat = game.waiting()[0]
        member = a if seat == 0 else b
        legal = game.legal(seat)
        action = legal[0]
        from avenue.game import actions

        room.handle(member.id, {"type": "action", "action": actions.to_json(action)})
    for sink, seat in ((sa, 0), (sb, 1)):
        find_down_hidden(sink.messages)
        for m in sink.messages:
            if m["type"] == "state" and m.get("game") and m["game"]["me"]:
                assert m["game"]["me"]["hand"] is not None
                other = 1 - seat
                if m["status"] == "playing":
                    assert m["game"]["players"][other]["hand_cards"] is None
        blob = json.dumps([m for m in sink.messages if m["type"] == "state"][-1])
        assert "token" not in blob


def test_bots_play_a_whole_team_game():
    for mode in ("simple", "advanced"):
        room = Room("BOTS", delay_scale=0.0, seed=3)
        a = room.join("a" * 32, "Ann")
        room.handle(a.id, {"type": "settings", "changes": {"mode": mode}})
        room.handle(a.id, {"type": "add_bot", "team": 0})
        room.handle(a.id, {"type": "add_bot", "team": 1})
        room.handle(a.id, {"type": "add_bot", "team": 1})
        room.handle(a.id, {"type": "start"})
        fast(room)
        room.seats[0].autoplay = True
        room.step_bots()
        assert room.status == "game_over", mode
        assert room.game is not None and room.game.result is not None


def test_human_in_a_bot_team_leads_unless_they_hand_over():
    room = Room("LEAD", delay_scale=0.0, seed=2)
    a = room.join("a" * 32, "Ann")
    room.handle(a.id, {"type": "add_bot", "team": 0})
    room.handle(a.id, {"type": "add_bot", "team": 1})
    room.handle(a.id, {"type": "settings", "changes": {"first": "green"}})
    room.handle(a.id, {"type": "start"})
    fast(room)
    game = room.game
    assert game is not None and game.active == 0 and game.phase == Phase.PLAY
    assert room.bot_turn() is None  # waits for the human
    room.handle(a.id, {"type": "lead"})
    assert room.bot_turn() == 1
    room.step_bots()  # the bot may discard first; it stops once it played face up
    assert game.up is not None and game.up[0] == 1
    assert game.waiting() == [0]


def test_server_endpoints():
    with GameClient("avenue") as client:
        assert client.get("/").status_code == 200
        assert client.get("/static/app.js").status_code == 200
        code = client.post("/api/rooms").json()["room"]
        assert client.get(f"/api/rooms/{code}").json()["status"] == "lobby"
        assert client.get("/api/rooms/NOPE1").status_code == 404
        with client.websocket_connect(f"/ws/{code}") as ws:
            ws.send_json({"type": "hello", "token": "c" * 32, "name": "Cid"})
            assert ws.receive_json()["type"] == "welcome"
            assert ws.receive_json()["type"] == "state"


def test_shuffle_keeps_team_sizes():
    room, a, b, _, _ = two_humans()
    room.handle(a.id, {"type": "add_bot", "team": 1})
    with pytest.raises(RoomError):
        room.handle(b.id, {"type": "shuffle"})
    for _ in range(6):
        room.handle(a.id, {"type": "shuffle"})
        assert sorted(s.team for s in room.seats) == [0, 1, 1]
    assert {s.name for s in room.seats} == {"Ann", "Bob", "Mastermind"}


def test_turn_timer_lets_the_autopilot_move():

    room, a, _, sa, _ = two_humans()
    with pytest.raises(RoomError):
        room.handle(a.id, {"type": "settings", "changes": {"turn_timer": 45}})
    room.handle(a.id, {"type": "settings", "changes": {"turn_timer": 30, "first": "green"}})
    room.handle(a.id, {"type": "start"})
    fast(room)
    state = sa.messages[-1]["game"]
    assert state["time_total"] == 30 and 0 < state["time_left"] <= 30
    assert room._deadline is not None
    key = room._deadline[0]
    room._deadline = (key, 0.0)  # time is up for Ann

    async def run() -> None:
        task = asyncio.create_task(room.drive())
        for _ in range(200):
            await asyncio.sleep(0.01)
            if room.game is not None and room.game.phase == Phase.RECRUIT:
                break
        room.close()
        await task

    asyncio.run(run())
    game = room.game
    assert game is not None and game.phase == Phase.RECRUIT  # Ann's cards were played for her
    assert any("ran out of time" in e.get("text", "") for e in room.log)
    assert room._deadline is not None and room._deadline[0] != key  # Bob's own clock is running


def test_autopilot_does_not_move_after_the_player_is_back():

    room, a, b, _, sb = two_humans()
    room.handle(a.id, {"type": "settings", "changes": {"first": "blue"}})
    room.handle(a.id, {"type": "start"})
    fast(room)
    room.disconnect(sb)
    room.handle(a.id, {"type": "autoplay", "seat": 1, "on": True})
    room.busy_until = time.monotonic() + 0.3  # the browsers are still animating while the autopilot thinks

    version = room.version

    async def run() -> None:
        task = asyncio.create_task(room.drive())
        await asyncio.sleep(0.1)
        room.connect(Sink(b.id))  # Bob is back before the autopilot's move is due
        await asyncio.sleep(0.6)
        room.close()
        await task

    asyncio.run(run())
    assert room.version == version  # nothing was played for Bob: it is still his decision
