from __future__ import annotations

import random
from typing import Any

import pytest

from avel.web.room import Room, RoomError
from boardgames.testing import GameClient

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


def make_room(humans: int = 1, bots: tuple[str, ...] = ("knight",), seed: int = 5) -> tuple[Room, list[Inbox]]:
    room = Room("TEST", delay_scale=0.0, seed=seed)
    inboxes = []
    for i in range(humans):
        member = room.join(TOKENS[i], f"Human {i}")
        inbox = Inbox(member.id)
        room.connect(inbox)
        inboxes.append(inbox)
    for key in bots:
        room.handle(inboxes[0].member_id, {"type": "add_bot", "bot": key})
    return room, inboxes


def human_move(room: Room, inbox: Inbox, rng: random.Random) -> bool:
    legal = room.state_for(inbox.member_id)["game"]["legal"]
    if not legal:
        return False
    # prefer actions that move the game along so random play finishes
    busy = [a for a in legal if a["type"] not in ("discard", "give", "take", "equip", "unequip", "drink")]
    room.handle(inbox.member_id, {"type": "action", "action": rng.choice(busy or legal)})
    return True


def run(room: Room, inboxes: list[Inbox], limit: int = 30_000) -> None:
    rng = random.Random(1)
    for _ in range(limit):
        if room.status != "playing":
            return
        if any(human_move(room, inbox, rng) for inbox in inboxes):
            continue
        plan = room.plan()
        assert plan is not None, "nobody can move"
        plan[1]()
    raise AssertionError("game did not finish")


def test_full_game_with_humans_and_bots() -> None:
    room, inboxes = make_room(humans=2, bots=("knight", "squire"))
    room.handle(inboxes[0].member_id, {"type": "start"})
    assert room.status == "playing"
    run(room, inboxes)
    assert room.status == "game_over"
    state = inboxes[1].last_state
    assert state["game"]["result"] is not None
    assert any("Round 2" in e["text"] for e in room.log if e["kind"] == "game")


def test_solo_game_following_hints() -> None:
    room, inboxes = make_room(humans=1, bots=())
    host = inboxes[0].member_id
    room.handle(host, {"type": "start"})
    assert room.game is not None and room.game.per_turn == 4
    for _ in range(5_000):
        if room.status != "playing":
            break
        hint = room.handle(host, {"type": "hint"})
        assert hint is not None
        room.handle(host, {"type": "action", "action": hint["action"]})
    assert room.status == "game_over"


def test_autopilot_plays_for_a_player_who_left() -> None:
    room, inboxes = make_room(humans=2, bots=())
    host = inboxes[0].member_id
    room.handle(host, {"type": "start"})
    with pytest.raises(RoomError):
        room.handle(host, {"type": "autoplay", "seat": 1, "on": True})
    room.disconnect(inboxes[1])
    room.handle(host, {"type": "autoplay", "seat": 1, "on": True})
    run(room, inboxes[:1])
    assert room.status == "game_over"


def test_only_the_acting_human_sees_legal_actions() -> None:
    room, inboxes = make_room(humans=2, bots=())
    room.handle(inboxes[0].member_id, {"type": "start"})
    first, second = (inbox.last_state["game"] for inbox in inboxes)
    assert first["legal"] and not second["legal"]
    with pytest.raises(RoomError):
        room.handle(inboxes[1].member_id, {"type": "action", "action": {"type": "end_turn"}})


def test_bad_actions_are_rejected_cleanly() -> None:
    room, inboxes = make_room()
    host = inboxes[0].member_id
    room.handle(host, {"type": "start"})
    for bad in ({"type": "nope"}, {"type": "move", "to": "x"}, {"type": "wall"}, {"type": "give", "to": [1, 2]}, "x"):
        with pytest.raises(RoomError):
            room.handle(host, {"type": "action", "action": bad})


def test_give_and_take_go_through_the_protocol() -> None:
    room, inboxes = make_room(humans=2, bots=())
    a, _b = (inbox.member_id for inbox in inboxes)
    room.handle(a, {"type": "start"})
    legal = inboxes[0].last_state["game"]["legal"]
    give = next(x for x in legal if x["type"] == "give" and x.get("item"))
    room.handle(a, {"type": "action", "action": give})
    game = inboxes[1].last_state["game"]
    assert give["item"] in game["heroes"][1]["pack"] + [v for v in game["heroes"][1]["slots"].values() if v]


def test_hint_returns_a_legal_action() -> None:
    room, inboxes = make_room()
    host = inboxes[0].member_id
    room.handle(host, {"type": "start"})
    reply = room.handle(host, {"type": "hint"})
    assert reply is not None and reply["type"] == "hint"
    assert reply["action"] in inboxes[0].last_state["game"]["legal"]


def test_lobby_controls() -> None:
    room, inboxes = make_room(humans=2, bots=("knight",))
    host, guest = (inbox.member_id for inbox in inboxes)
    with pytest.raises(RoomError):
        room.handle(guest, {"type": "start"})
    room.handle(host, {"type": "settings", "changes": {"crater": "difficult", "turn_timer": 60}})
    assert room.settings.crater == "difficult" and room.settings.turn_timer == 60
    room.handle(host, {"type": "shuffle"})
    assert len(room.seats) == 3
    room.handle(guest, {"type": "stand"})
    assert room.seat_of(guest) is None
    room.handle(guest, {"type": "sit"})
    assert room.seat_of(guest) is not None
    room.handle(host, {"type": "add_bot", "bot": "squire"})
    with pytest.raises(RoomError):
        room.handle(host, {"type": "add_bot", "bot": "squire"})  # 4 seats max
    room.handle(host, {"type": "start"})
    assert room.game is not None and room.game.n == 4 and room.game.crater.key == "difficult"


def test_turn_timer_hands_the_turn_to_the_autopilot() -> None:
    room, inboxes = make_room(humans=1, bots=("knight",))
    host = inboxes[0].member_id
    room.handle(host, {"type": "settings", "changes": {"turn_timer": 60}})
    room.handle(host, {"type": "start"})
    assert room.game is not None and room.game.actor == 0
    assert inboxes[0].last_state["game"]["time_left"] > 0
    room._timeout()
    assert room.game.current != 0 or room.game.round > 1 or room.status != "playing"


def test_chat_and_rename() -> None:
    room, inboxes = make_room()
    host = inboxes[0].member_id
    room.handle(host, {"type": "chat", "text": "hello"})
    assert any(m["type"] == "log" and m["entry"].get("text") == "hello" for m in inboxes[0].messages)
    room.handle(host, {"type": "rename", "name": "Ada"})
    assert room.seats[0].name == "Ada"


def test_http_and_websocket() -> None:
    with GameClient("avel", delay_scale=0.0) as client:
        assert client.get("/").status_code == 200
        cfg = client.get("/api/config").json()
        assert {"tiles", "monsters", "equipment", "moon_track", "craters"} <= set(cfg)
        assert len(cfg["monsters"]) == 31 and len(cfg["equipment"]) >= 20
        code = client.post("/api/rooms").json()["room"]
        assert client.get(f"/api/rooms/{code}").status_code == 200
        assert client.get("/api/rooms/NOPE1").status_code == 404
        assert client.get(f"/r/{code}").status_code == 200
        with client.websocket_connect(f"/ws/{code}") as ws:
            ws.send_json({"type": "hello", "token": TOKENS[0], "name": "Ada"})
            kinds = []
            while "state" not in kinds:
                kinds.append(ws.receive_json()["type"])
            assert "welcome" in kinds
            ws.send_json({"type": "add_bot", "bot": "knight"})
            ws.send_json({"type": "start"})
            state = None
            while state is None or state["status"] != "playing":
                msg = ws.receive_json()
                if msg["type"] == "state":
                    state = msg
            assert state["game"]["legal"]
            ws.send_json({"type": "action", "action": {"type": "wall"}})
            while (msg := ws.receive_json())["type"] != "error":
                pass
            assert msg["message"]
