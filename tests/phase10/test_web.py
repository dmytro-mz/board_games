from __future__ import annotations

from typing import Any

import pytest

from boardgames.testing import GameClient
from phase10.bots import make_bot
from phase10.game.actions import to_json
from phase10.game.engine import Step
from phase10.web.room import Room, RoomError

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


def _room(
    humans: int = 2, bots: tuple[str, ...] = ("pro",), seed: int = 5, last_phase: int = 3
) -> tuple[Room, list[Inbox]]:
    room = Room("TEST", delay_scale=0.0, seed=seed)
    inboxes = []
    for i in range(humans):
        member = room.join(TOKENS[i], f"Human {i}")
        inbox = Inbox(member.id)
        room.connect(inbox)
        inboxes.append(inbox)
    host = inboxes[0].member_id
    for key in bots:
        room.handle(host, {"type": "add_bot", "bot": key})
    room.handle(host, {"type": "settings", "changes": {"last_phase": last_phase}})
    return room, inboxes


def _human_move(room: Room, inbox: Inbox, brains: dict[str, Any]) -> bool:
    """Play this human's move through the protocol (a bot decides which), if it's their turn or a hand is over."""
    game = room.game
    assert game is not None
    seat = room.seat_of(inbox.member_id)
    if seat is None:
        return False
    if game.step == Step.HAND_OVER:
        if seat in room.ready:
            return False
        room.handle(inbox.member_id, {"type": "ready"})
        return True
    if game.current != seat:
        return False
    brain = brains.setdefault(inbox.member_id, make_bot("regular", seat))
    action = brain.act(game.view(seat))
    room.handle(inbox.member_id, {"type": "action", "action": to_json(action)})
    return True


def _run(room: Room, inboxes: list[Inbox], limit: int = 20_000) -> None:
    brains: dict[str, Any] = {}
    for _ in range(limit):
        if room.status != "playing":
            return
        if any(_human_move(room, inbox, brains) for inbox in inboxes):
            continue
        plan = room.plan()
        assert plan is not None, "nobody can move"
        plan[1]()
    raise AssertionError("game did not finish")


def test_full_game_with_humans_and_a_bot():
    room, inboxes = _room()
    room.handle(inboxes[0].member_id, {"type": "start"})
    assert room.status == "playing"
    _run(room, inboxes)
    assert room.status == "game_over"
    state = inboxes[1].last_state["game"]
    assert state["result"]["winners"]
    assert state["history"]


def test_other_hands_stay_hidden():
    room, (a, _b) = _room()
    room.handle(a.member_id, {"type": "start"})
    st = a.last_state["game"]
    seat_a = room.seat_of(a.member_id)
    assert len(st["hand"]) == 10
    assert {c["id"] for c in st["hand"]} == {c.id for c in room.game.hands[seat_a]}
    assert all("hand" not in p for p in st["players"])
    assert [p["count"] for p in st["players"]] == [10, 10, 10]


def test_deck_draws_are_hidden_from_the_others():
    room, (a, b) = _room(bots=())
    room.handle(a.member_id, {"type": "start"})
    game = room.game
    current = game.current
    mover, other = (a, b) if room.seat_of(a.member_id) == current else (b, a)
    room.handle(mover.member_id, {"type": "action", "action": {"type": "draw_deck"}})
    mine = next(e for e in mover.last_state["event"]["events"] if e["kind"] == "draw")
    theirs = next(e for e in other.last_state["event"]["events"] if e["kind"] == "draw")
    assert mine["card"] is not None and theirs["card"] is None


def test_options_only_for_the_player_on_turn():
    room, (a, b) = _room(bots=())
    room.handle(a.member_id, {"type": "start"})
    current = room.game.current
    on, off = (a, b) if room.seat_of(a.member_id) == current else (b, a)
    assert on.last_state["game"]["options"]["draw_deck"]
    assert not off.last_state["game"]["options"]
    with pytest.raises(RoomError, match="not your turn"):
        room.handle(off.member_id, {"type": "action", "action": {"type": "draw_deck"}})
    with pytest.raises(RoomError):
        room.handle(on.member_id, {"type": "action", "action": {"type": "teleport"}})


def test_arrange_is_private_and_validated():
    room, (a, b) = _room(bots=())
    room.handle(a.member_id, {"type": "start"})
    seat = room.seat_of(a.member_id)
    order = [c["id"] for c in reversed(a.last_state["game"]["hand"])]
    seq = room.seq
    n_b = len(b.messages)
    room.handle(a.member_id, {"type": "arrange", "order": order})
    assert [c.id for c in room.game.hands[seat]] == order
    assert [c["id"] for c in a.last_state["game"]["hand"]] == order
    assert room.seq == seq and len(b.messages) == n_b  # nobody else hears about it
    with pytest.raises(RoomError):
        room.handle(a.member_id, {"type": "arrange", "order": order[:-1]})
    with pytest.raises(RoomError):
        room.handle(a.member_id, {"type": "arrange", "order": "nope"})


def test_hand_over_waits_for_ready_players():
    room, (a, b) = _room(bots=(), last_phase=10)
    room.handle(a.member_id, {"type": "start"})
    game = room.game
    brains: dict[str, Any] = {}
    while game.step != Step.HAND_OVER:
        assert any(_human_move(room, x, brains) for x in (a, b))
    assert room.plan() is None  # nobody ready yet
    with pytest.raises(RoomError, match="unknown"):
        room.handle(a.member_id, {"type": "deal"})  # not even the host can deal before everyone is ready
    room.handle(a.member_id, {"type": "ready"})
    assert room.plan() is None and a.last_state["game"]["waiting_for"]
    room.handle(b.member_id, {"type": "ready"})
    plan = room.plan()
    assert plan is not None
    plan[1]()
    assert game.hand_no == 2 and game.step == Step.DRAW


def test_turn_timer_never_deals_the_next_hand():
    room, (a, b) = _room(bots=(), last_phase=10)
    room.settings.turn_timer = 30
    room.handle(a.member_id, {"type": "start"})
    game = room.game
    brains: dict[str, Any] = {}
    while game.step != Step.HAND_OVER:
        assert any(_human_move(room, x, brains) for x in (a, b))
    assert room.plan() is None and a.last_state["game"]["time_left"] is None


def test_skip_cooldown_setting_reaches_the_game():
    room, (a, _b) = _room(bots=())
    with pytest.raises(RoomError, match="invalid"):
        room.handle(a.member_id, {"type": "settings", "changes": {"skip_cooldown": "yes"}})
    room.handle(a.member_id, {"type": "settings", "changes": {"skip_cooldown": True}})
    room.handle(a.member_id, {"type": "start"})
    assert room.game is not None and room.game.rules.skip_cooldown


def test_lobby_rules():
    room, (a, b) = _room(bots=())
    with pytest.raises(RoomError, match="host"):
        room.handle(b.member_id, {"type": "add_bot", "bot": "pro"})
    for _ in range(4):
        room.handle(a.member_id, {"type": "add_bot", "bot": "rookie"})
    assert [s.name for s in room.seats][2:] == ["Rookie", "Rookie 2", "Rookie 3", "Rookie 4"]
    with pytest.raises(RoomError, match="full"):
        room.handle(a.member_id, {"type": "add_bot", "bot": "pro"})
    with pytest.raises(RoomError):
        room.handle(a.member_id, {"type": "settings", "changes": {"last_phase": 7}})
    solo = Room("SOLO", delay_scale=0)
    m = solo.join(TOKENS[2], "Alone")
    with pytest.raises(RoomError, match="at least 2"):
        solo.handle(m.id, {"type": "start"})


def test_autoplay_takes_over_a_disconnected_player():
    room, (a, b) = _room(bots=())
    room.handle(a.member_id, {"type": "start"})
    seat_b = room.seat_of(b.member_id)
    room.disconnect(b)
    room.handle(a.member_id, {"type": "autoplay", "seat": seat_b, "on": True})
    brains: dict[str, Any] = {}
    for _ in range(5000):
        if room.status != "playing":
            break
        if _human_move(room, a, brains):
            continue
        plan = room.plan()
        assert plan is not None
        plan[1]()
    assert room.status == "game_over"


def test_websocket_flow():
    with GameClient("phase10") as client:
        config = client.get("/api/config").json()
        assert len(config["phases"]) == 10 and config["bots"]
        room_id = client.post("/api/rooms").json()["room"]
        with client.websocket_connect(f"/ws/{room_id}") as ws:
            ws.send_json({"token": TOKENS[0], "name": "Ann"})
            welcome = ws.receive_json()
            assert welcome["type"] == "welcome"
            assert ws.receive_json()["type"] == "state"
            ws.send_json({"type": "add_bot", "bot": "pro"})
            st = ws.receive_json()
            assert len(st["seats"]) == 2
            ws.send_json({"type": "start"})
            while True:
                msg = ws.receive_json()
                if msg["type"] == "state" and msg["status"] == "playing":
                    break
            assert len(msg["game"]["hand"]) == 10
            ws.send_json({"type": "fly"})
            while (err := ws.receive_json())["type"] != "error":
                pass
            assert "unknown" in err["message"]
