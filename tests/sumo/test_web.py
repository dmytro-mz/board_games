"""The multiplayer table (`Room`) driven through its protocol, and an HTTP/WebSocket smoke test."""

from __future__ import annotations

import asyncio
import random
from typing import Any

import pytest

from boardgames.testing import GameClient
from sumo.bots import REGISTRY
from sumo.game.board import LAYOUTS
from sumo.game.engine import MARBLES
from sumo.web.room import Room, RoomError

TOKENS = ["a" * 32, "b" * 32, "c" * 32]


class Inbox:
    def __init__(self, member_id: str) -> None:
        self.member_id = member_id
        self.messages: list[dict[str, Any]] = []

    def send(self, message: dict[str, Any]) -> None:
        self.messages.append(message)

    @property
    def last_state(self) -> dict[str, Any]:
        return next(m for m in reversed(self.messages) if m["type"] == "state")


def _join(room: Room, i: int) -> Inbox:
    member = room.join(TOKENS[i], f"Human {i}")
    inbox = Inbox(member.id)
    room.connect(inbox)
    return inbox


def _room(humans: int = 2, bot: str | None = None, **settings: Any) -> tuple[Room, list[Inbox]]:
    room = Room("TEST", delay_scale=0.0, seed=5, bot_budget=0.02)
    inboxes = [_join(room, i) for i in range(humans)]
    if bot:
        room.handle(inboxes[0].member_id, {"type": "add_bot", "bot": bot})
    if settings:
        room.handle(inboxes[0].member_id, {"type": "settings", "changes": settings})
    return room, inboxes


def _play(room: Room, inboxes: list[Inbox], limit: int = 3000) -> None:
    """Humans play pushes when they can (games end sooner), else random moves; bots answer."""
    rng = random.Random(1)
    for _ in range(limit):
        if room.status != "playing":
            return
        moved = False
        for inbox in inboxes:
            legal = inbox.last_state["game"]["legal"]
            if legal:
                game = room.game
                assert game is not None
                pushes = [m for m in game.legal_internal() if m[4]]
                if pushes and rng.random() < 0.8:
                    from sumo.game.engine import Move

                    action = Move.of(rng.choice(pushes)).to_json()
                else:
                    action = rng.choice(legal)
                room.handle(inbox.member_id, {"type": "action", "action": action})
                moved = True
                break
        if not moved:
            room.step_bots(limit=1)
    raise AssertionError("game did not finish")


# ------------------------------------------------------------------ flow
@pytest.mark.parametrize("layout", list(LAYOUTS))
def test_two_humans_play_a_whole_game(layout: str) -> None:
    room, inboxes = _room(layout=layout)
    room.handle(inboxes[0].member_id, {"type": "start"})
    assert room.status == "playing"
    _play(room, inboxes)
    assert room.status == "game_over"
    for inbox in inboxes:
        g = inbox.last_state["game"]
        assert g["result"] is not None and g["current"] is None and g["legal"] == []
        assert g["layout"] == layout
    room.game.check()  # type: ignore[union-attr]


def test_human_vs_bot_and_rematch() -> None:
    room, inboxes = _room(humans=1, bot="ozeki")
    room.handle(inboxes[0].member_id, {"type": "start"})
    _play(room, inboxes)
    assert room.status == "game_over"
    room.handle(inboxes[0].member_id, {"type": "play_again"})
    assert room.status == "playing" and room.game_no == 2 and room.game is not None and room.game.turn == 0
    room.handle(inboxes[0].member_id, {"type": "to_lobby"})
    assert room.status == "lobby" and room.game is None


def test_bots_play_each_other_to_the_end() -> None:
    room, inboxes = _room(humans=1, bot="rookie", move_limit=50)
    room.handle(inboxes[0].member_id, {"type": "stand"})
    room.handle(inboxes[0].member_id, {"type": "add_bot", "bot": "rookie"})
    assert [s.name for s in room.seats] == ["Rookie", "Rookie 2"]
    room.handle(inboxes[0].member_id, {"type": "start"})
    room.step_bots()
    assert room.status == "game_over"
    room.game.check()  # type: ignore[union-attr]
    assert inboxes[0].last_state["you"]["seat"] is None  # watching


def test_random_layout_is_drawn_at_start() -> None:
    room, inboxes = _room(layout="random")
    room.handle(inboxes[0].member_id, {"type": "start"})
    assert room.game is not None and room.game.layout in LAYOUTS
    assert inboxes[1].last_state["settings"]["layout"] == "random"


def test_settings_validation_is_all_or_nothing() -> None:
    room, inboxes = _room()
    host = inboxes[0].member_id
    for bad in (
        {"layout": "moon"},
        {"move_limit": 7},
        {"move_limit": True},
        {"turn_timer": 7},
        {"bot_speed": "warp"},
        {"rounds": 3},
    ):
        with pytest.raises(RoomError):
            room.handle(host, {"type": "settings", "changes": {"layout": "daisy", **bad}})
    assert room.settings.layout == "classic"
    room.handle(host, {"type": "settings", "changes": {"layout": "wide", "move_limit": 100, "turn_timer": 60}})
    assert (room.settings.layout, room.settings.move_limit, room.settings.turn_timer) == ("wide", 100, 60)
    room.handle(host, {"type": "start"})
    with pytest.raises(RoomError):
        room.handle(host, {"type": "settings", "changes": {"layout": "classic"}})
    assert room.game is not None and room.game.move_limit == 100


def test_only_the_host_runs_the_lobby() -> None:
    room, inboxes = _room()
    guest = inboxes[1].member_id
    for msg in (
        {"type": "start"},
        {"type": "settings", "changes": {"layout": "daisy"}},
        {"type": "add_bot", "bot": "rookie"},
        {"type": "swap"},
        {"type": "to_lobby"},
    ):
        with pytest.raises(RoomError):
            room.handle(guest, msg)


def test_seats_bots_and_swap() -> None:
    room, inboxes = _room(humans=1)
    host = inboxes[0].member_id
    with pytest.raises(RoomError):
        room.handle(host, {"type": "start"})  # one player
    with pytest.raises(RoomError):
        room.handle(host, {"type": "add_bot", "bot": "general"})
    room.handle(host, {"type": "add_bot", "bot": "yokozuna"})
    with pytest.raises(RoomError):
        room.handle(host, {"type": "add_bot", "bot": "rookie"})  # full
    room.handle(host, {"type": "swap"})
    assert room.seat_of(host) == 1
    st = inboxes[0].last_state
    assert st["seats"][1]["color"] == "white" and st["seats"][0]["bot"] == "yokozuna"
    room.handle(host, {"type": "remove_seat", "seat": 0})
    assert len(room.seats) == 1 and room.seat_of(host) == 0
    with pytest.raises(RoomError):
        room.handle(host, {"type": "remove_seat", "seat": 5})


def test_illegal_and_out_of_turn_actions_are_rejected() -> None:
    room, inboxes = _room()
    room.handle(inboxes[0].member_id, {"type": "start"})
    black, white = (next(i for i in inboxes if room.seat_of(i.member_id) == s) for s in (0, 1))
    legal = black.last_state["game"]["legal"]
    with pytest.raises(RoomError):
        room.handle(white.member_id, {"type": "action", "action": legal[0]})  # not White's turn
    for bad in (None, {"type": "move", "marbles": [0], "dir": 9}, {"type": "move", "marbles": [30], "dir": 0}):
        with pytest.raises(RoomError):
            room.handle(black.member_id, {"type": "action", "action": bad})
    with pytest.raises(RoomError):
        room.handle(black.member_id, {"type": "bogus"})
    room.handle(black.member_id, {"type": "action", "action": legal[0]})
    assert room.game is not None and room.game.turn == 1


def test_spectator_cannot_act_or_resign() -> None:
    room, inboxes = _room(humans=3)
    room.handle(inboxes[0].member_id, {"type": "start"})
    spectator = inboxes[2]
    assert spectator.last_state["you"]["seat"] is None and spectator.last_state["game"]["legal"] == []
    with pytest.raises(RoomError):
        room.handle(spectator.member_id, {"type": "action", "action": inboxes[0].last_state["game"]["legal"][0]})
    with pytest.raises(RoomError):
        room.handle(spectator.member_id, {"type": "resign"})


def test_resign_ends_the_game_for_everyone() -> None:
    room, inboxes = _room()
    room.handle(inboxes[0].member_id, {"type": "start"})
    room.handle(inboxes[1].member_id, {"type": "resign"})  # even when it isn't your turn
    assert room.status == "game_over"
    seat = room.seat_of(inboxes[1].member_id)
    assert seat is not None
    assert inboxes[0].last_state["game"]["result"] == {"winner": 1 - seat, "reason": "resign", "out": [0, 0]}
    with pytest.raises(RoomError):
        room.handle(inboxes[0].member_id, {"type": "resign"})


def test_state_has_every_marble_and_the_last_move() -> None:
    room, inboxes = _room()
    room.handle(inboxes[0].member_id, {"type": "start"})
    g = inboxes[0].last_state["game"]
    assert g["last"] is None and g["out"] == [0, 0]
    assert sorted(i for i in g["ids"] if i is not None) == list(range(2 * MARBLES))
    room.handle(inboxes[0].member_id, {"type": "action", "action": g["legal"][0]})
    st = inboxes[1].last_state
    assert st["event"]["kind"] == "move" and st["event"]["events"][0]["kind"] == "move"
    assert st["game"]["last"] == st["event"]["events"][0]
    assert bool(st["game"]["legal"]) == (room.seat_of(inboxes[1].member_id) == 1)


# ------------------------------------------------------------------ automation
def test_autoplay_for_a_disconnected_player() -> None:
    room, inboxes = _room(move_limit=50)
    room.handle(inboxes[0].member_id, {"type": "start"})
    seat1 = room.seat_of(inboxes[1].member_id)
    with pytest.raises(RoomError):  # still connected
        room.handle(inboxes[0].member_id, {"type": "autoplay", "seat": seat1, "on": True})
    room.disconnect(inboxes[1])
    room.handle(inboxes[0].member_id, {"type": "autoplay", "seat": seat1, "on": True})
    _play(room, [inboxes[0]])
    assert room.status == "game_over"


def test_driver_plays_bot_moves_in_a_thread() -> None:
    async def run() -> None:
        room, inboxes = _room(humans=1, bot="rookie", move_limit=50)
        room.handle(inboxes[0].member_id, {"type": "stand"})
        room.handle(inboxes[0].member_id, {"type": "add_bot", "bot": "ozeki"})
        room.handle(inboxes[0].member_id, {"type": "start"})
        task = asyncio.create_task(room.drive())
        for _ in range(4000):
            if room.status == "game_over":
                break
            await asyncio.sleep(0.005)
        room.close()
        await task
        assert room.status == "game_over"

    asyncio.run(run())


def test_turn_timer_hands_the_move_to_the_autopilot() -> None:
    room, inboxes = _room(turn_timer=30)
    room.handle(inboxes[0].member_id, {"type": "start"})
    game = room.game
    assert game is not None and room._deadline is not None
    assert inboxes[0].last_state["game"]["time_left"] is not None
    seat = game.current
    room._timeout()
    assert room._is_auto(seat)
    mover = next(i for i in inboxes if room.seat_of(i.member_id) == seat)
    with pytest.raises(RoomError):
        room.handle(mover.member_id, {"type": "action", "action": game.legal_moves()[0].to_json()})
    room.step_bots()
    assert game.turn == 1 and game.current != seat
    assert not room._is_auto(game.current)


# ------------------------------------------------------------------ server
def test_http_config_and_rooms() -> None:
    with GameClient("sumo", delay_scale=0.0) as client:
        config = client.get("/api/config").json()
        assert [b["key"] for b in config["bots"]] == list(REGISTRY)
        assert [x["key"] for x in config["layouts"]] == list(LAYOUTS)
        assert len(config["board"]["cells"]) == 61 and config["max_seats"] == 2 and config["reactions"]
        code = client.post("/api/rooms").json()["room"]
        assert client.get(f"/api/rooms/{code}").json()["status"] == "lobby"
        page = client.get(f"/r/{code}")
        assert page.status_code == 200 and "/g/sumo/static/app.js" in page.text
        for name in ("app.js", "board.js", "rules.js", "sound.js", "style.css"):
            assert client.get(f"/static/{name}").status_code == 200


def test_websocket_handshake_and_first_moves() -> None:
    with GameClient("sumo", delay_scale=0.0) as client:
        code = client.post("/api/rooms").json()["room"]
        with client.websocket_connect(f"/ws/{code}") as ws:
            ws.send_json({"token": TOKENS[0], "name": "Ada"})
            welcome = ws.receive_json()
            assert welcome["type"] == "welcome" and welcome["bots"]
            state = ws.receive_json()
            assert state["type"] == "state" and state["status"] == "lobby"
            ws.send_json({"type": "start"})
            assert ws.receive_json()["type"] == "error"  # one player is not enough
            ws.send_json({"type": "add_bot", "bot": "rookie"})
            ws.send_json({"type": "swap"})  # the bot plays Black and moves first
            ws.send_json({"type": "start"})
            seen = []
            for _ in range(80):
                msg = ws.receive_json()
                seen.append(msg)
                if msg["type"] == "state" and msg["status"] == "playing" and msg["game"]["legal"]:
                    break
            playing = [m for m in seen if m["type"] == "state" and m["status"] == "playing"]
            assert playing[-1]["game"]["turn"] == 1  # the bot has moved
            ws.send_json({"type": "action", "action": playing[-1]["game"]["legal"][0]})
            for _ in range(20):
                msg = ws.receive_json()
                if msg["type"] == "state" and msg["game"]["turn"] >= 2:
                    break
            assert msg["game"]["turn"] >= 2
