from __future__ import annotations

from typing import Any

import pytest

from boardgames.testing import GameClient
from pandemic.bots import make_bot
from pandemic.game.actions import to_json
from pandemic.game.engine import Step
from pandemic.game.model import EPIDEMIC, Color, Role
from pandemic.web.room import Room, RoomError

TOKENS = ["a" * 32, "b" * 32, "c" * 32, "d" * 32]


class Inbox:
    def __init__(self, member_id: str) -> None:
        self.member_id = member_id
        self.messages: list[dict[str, Any]] = []

    def send(self, message: dict[str, Any]) -> None:
        self.messages.append(message)

    @property
    def last_state(self) -> dict[str, Any]:
        return next(m for m in reversed(self.messages) if m["type"] == "state")

    def texts(self) -> list[str]:
        return [m["entry"]["text"] for m in self.messages if m["type"] == "log" and m["entry"]["kind"] == "game"]


def _room(
    humans: int = 2, bots: tuple[str, ...] = ("expert",), seed: int = 5, **settings: Any
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
    if settings:
        room.handle(host, {"type": "settings", "changes": settings})
    return room, inboxes


def _human_move(room: Room, inbox: Inbox, brains: dict[str, Any]) -> bool:
    """Play this human's move through the protocol (a bot decides which) if the game waits for them."""
    game = room.game
    assert game is not None
    seat = room.seat_of(inbox.member_id)
    if seat is None or game.waiting_for() != seat:
        return False
    brain = brains.setdefault(inbox.member_id, make_bot("expert", seat))
    action = brain.act(game.view(seat))
    room.handle(inbox.member_id, {"type": "action", "action": to_json(action)})
    return True


def _run(room: Room, inboxes: list[Inbox], limit: int = 5_000) -> None:
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


def _seat_of(room: Room, inbox: Inbox) -> int:
    seat = room.seat_of(inbox.member_id)
    assert seat is not None
    return seat


def test_full_game_with_humans_and_a_bot() -> None:
    room, inboxes = _room(epidemics=4)
    room.handle(inboxes[0].member_id, {"type": "start"})
    assert room.status == "playing"
    _run(room, inboxes)
    assert room.status == "game_over"
    state = inboxes[1].last_state["game"]
    assert state["result"] is not None
    texts = inboxes[0].texts()
    assert any(t.startswith("Setup infections") for t in texts)
    assert any(t.startswith("Turn 1:") for t in texts)
    assert any("team" in t for t in texts[-2:])


def test_bots_only_table_plays_itself() -> None:
    room, (a,) = _room(humans=1, bots=("rookie", "rookie"))
    room.handle(a.member_id, {"type": "stand"})
    room.handle(a.member_id, {"type": "start"})
    _run(room, [a])
    assert room.status == "game_over"


def test_open_hands_show_everything() -> None:
    room, (a, b) = _room(bots=())
    room.handle(a.member_id, {"type": "start"})
    players = b.last_state["game"]["players"]
    assert all(p["hand"] is not None for p in players)
    assert players[_seat_of(room, a)]["hand"] == room.game.hands[_seat_of(room, a)]


def test_closed_hands_hide_other_cards_and_draws() -> None:
    room, (a, b, c) = _room(humans=3, bots=(), open_hands=False)
    room.handle(a.member_id, {"type": "start"})
    game = room.game
    sa = _seat_of(room, a)
    players = a.last_state["game"]["players"]
    assert players[sa]["hand"] == game.hands[sa]
    assert all(p["hand"] is None for i, p in enumerate(players) if i != sa)
    assert [p["count"] for p in players] == [len(h) for h in game.hands]
    # the current player passes and draws: only they see the cards (Epidemics are public)
    mover = next(i for i in (a, b, c) if _seat_of(room, i) == game.current)
    other = next(i for i in (a, b, c) if i is not mover)
    game.player_deck[-2:] = [EPIDEMIC, "par"]
    room.handle(mover.member_id, {"type": "action", "action": {"type": "pass"}})
    room.handle(mover.member_id, {"type": "action", "action": {"type": "draw"}})
    mine = next(e for e in mover.last_state["event"]["events"] if e["kind"] == "draw")
    theirs = next(e for e in other.last_state["event"]["events"] if e["kind"] == "draw")
    assert sorted(mine["cards"]) == sorted(["par", EPIDEMIC])
    assert sorted(theirs["cards"], key=str) == sorted([None, EPIDEMIC], key=str)
    assert None in other.last_state["game"]["drawn"]
    # a reload during the epidemic still gets the turn's end so far, filtered the same way
    kinds = [e["kind"] for e in other.last_state["game"]["turn_end"]]
    assert kinds[:3] == ["draw", "epidemic", "infect"]
    assert other.last_state["game"]["turn_end"][0] == theirs
    assert mover.last_state["game"]["turn_end"][0] == mine
    room.handle(mover.member_id, {"type": "action", "action": {"type": "continue"}})
    room.handle(mover.member_id, {"type": "action", "action": {"type": "continue"}})
    assert other.last_state["game"]["turn_end"] == []


def test_spectators_see_no_hands_when_closed() -> None:
    room, (a, _b, c) = _room(humans=3, bots=(), open_hands=False)
    room.handle(c.member_id, {"type": "stand"})
    room.handle(a.member_id, {"type": "start"})
    assert all(p["hand"] is None for p in c.last_state["game"]["players"])


def test_settings_are_validated_and_host_only() -> None:
    room, (a, b) = _room()
    with pytest.raises(RoomError):
        room.handle(a.member_id, {"type": "settings", "changes": {"epidemics": 7}})
    with pytest.raises(RoomError):
        room.handle(b.member_id, {"type": "settings", "changes": {"epidemics": 4}})
    room.handle(a.member_id, {"type": "settings", "changes": {"epidemics": 6, "open_hands": False}})
    assert a.last_state["settings"]["epidemics"] == 6
    assert a.last_state["settings"]["open_hands"] is False


def test_roles_can_be_chosen() -> None:
    room, (a, b) = _room()
    with pytest.raises(RoomError, match="random"):
        room.handle(a.member_id, {"type": "pick_role", "seat": 0, "role": "medic"})
    room.handle(a.member_id, {"type": "settings", "changes": {"roles": "choose"}})
    room.handle(a.member_id, {"type": "pick_role", "seat": _seat_of(room, a), "role": "medic"})
    with pytest.raises(RoomError, match="already plays the Medic"):
        room.handle(b.member_id, {"type": "pick_role", "seat": _seat_of(room, b), "role": "medic"})
    with pytest.raises(RoomError, match="your own seat"):
        room.handle(b.member_id, {"type": "pick_role", "seat": _seat_of(room, a), "role": "scientist"})
    room.handle(a.member_id, {"type": "pick_role", "seat": 2, "role": "scientist"})  # the host picks for the bot
    room.handle(a.member_id, {"type": "start"})
    roles = room.game.roles
    assert roles[_seat_of(room, a)] == Role.MEDIC
    assert roles[2] == Role.SCIENTIST


def test_undo_through_the_protocol() -> None:
    room, (a, b) = _room(bots=())
    room.handle(a.member_id, {"type": "start"})
    game = room.game
    mover, other = (a, b) if _seat_of(room, a) == game.current else (b, a)
    seat = game.current
    room.handle(mover.member_id, {"type": "action", "action": {"type": "drive", "to": "chi"}})
    assert game.location[seat] == "chi"
    assert mover.last_state["game"]["can_undo"]
    assert not other.last_state["game"]["can_undo"]
    with pytest.raises(RoomError):
        room.handle(other.member_id, {"type": "undo"})
    room.handle(mover.member_id, {"type": "undo"})
    assert game.location[seat] == "atl"
    assert game.actions_left == 4


def test_illegal_actions_explain_themselves() -> None:
    room, (a, b) = _room(bots=())
    room.handle(a.member_id, {"type": "start"})
    game = room.game
    mover, other = (a, b) if _seat_of(room, a) == game.current else (b, a)
    with pytest.raises(RoomError, match="isn't connected"):
        room.handle(mover.member_id, {"type": "action", "action": {"type": "drive", "to": "tok"}})
    with pytest.raises(RoomError, match="not your turn"):
        room.handle(other.member_id, {"type": "action", "action": {"type": "drive", "to": "chi"}})
    with pytest.raises(RoomError, match="unknown action"):
        room.handle(mover.member_id, {"type": "action", "action": {"type": "teleport"}})


def test_a_bot_plays_resilient_population_during_a_human_epidemic() -> None:
    room, (a,) = _room(humans=1, bots=("expert",))
    room.handle(a.member_id, {"type": "start"})
    game = room.game
    human, bot = _seat_of(room, a), 1 - _seat_of(room, a)
    game.current = human
    game.hands[bot] = ["resilient"]
    game.step = Step.EPIDEMIC
    game.infection_discard = ["par"]
    game.cubes["par"][Color.BLUE] = 3
    room._step += 1
    plan = room.plan()
    assert plan is not None
    plan[1]()
    assert "par" in game.removed
    assert any("Resilient Population" in t for t in a.texts())
    assert room.plan() is None  # now the human continues


def test_bots_wait_while_a_human_picks_an_event() -> None:
    room, (a, b) = _room(humans=2, bots=("expert",))
    room.handle(a.member_id, {"type": "start"})
    game = room.game
    sa, sb = _seat_of(room, a), _seat_of(room, b)
    game.current = 3 - sa - sb
    game.hands[sa] = ["resilient", "par"]
    game.hands[sb] = ["mad"]
    game.step = Step.EPIDEMIC
    game.infection_discard = ["par", "mad"]
    room._step += 1
    room.handle(b.member_id, {"type": "hold", "on": True})  # no event card: no pause
    assert room.plan()[0] == 0
    room.handle(a.member_id, {"type": "hold", "on": True})
    delay, step = room.plan()
    assert delay > 20
    step()
    assert game.step == Step.EPIDEMIC  # the bot didn't continue
    room.handle(a.member_id, {"type": "hold", "on": False})
    assert room.plan()[0] <= 1.0  # a short grace for the action on its way
    room.handle(a.member_id, {"type": "hold", "on": True})  # once per step
    assert room.plan()[0] <= 1.0
    room.handle(a.member_id, {"type": "action", "action": {"type": "resilient", "city": "par"}})
    assert room.plan()[0] == 0  # the game moved on: the bot continues


def test_autopilot_takes_over_a_disconnected_human() -> None:
    room, (a, b) = _room(bots=())
    room.handle(a.member_id, {"type": "start"})
    seat_b = _seat_of(room, b)
    with pytest.raises(RoomError, match="still connected"):
        room.handle(a.member_id, {"type": "autoplay", "seat": seat_b, "on": True})
    room.disconnect(b)
    room.handle(a.member_id, {"type": "autoplay", "seat": seat_b, "on": True})
    assert room.seats[seat_b].autoplay
    _run(room, [a])
    assert room.status == "game_over"


def test_chat_and_reactions() -> None:
    room, (a, b) = _room()
    room.handle(a.member_id, {"type": "chat", "text": "  <b>hello</b>   team "})
    entry = b.messages[-1]["entry"]
    assert entry["kind"] == "chat" and entry["text"] == "<b>hello</b> team"
    room.handle(b.member_id, {"type": "react", "emoji": "👍"})
    assert a.messages[-1] == {"type": "react", "member": b.member_id, "seat": 1, "emoji": "👍"}
    with pytest.raises(RoomError):
        room.handle(b.member_id, {"type": "react", "emoji": "x"})


def test_server_config_and_websocket() -> None:
    with GameClient("pandemic", delay_scale=0.0) as client:
        config = client.get("/api/config").json()
        assert len(config["cities"]) == 48
        assert {r["key"] for r in config["roles"]} >= {"medic", "scientist"}
        assert [b["key"] for b in config["bots"]] == ["rookie", "expert"]
        code = client.post("/api/rooms").json()["room"]
        assert client.get(f"/api/rooms/{code}").json()["status"] == "lobby"
        assert client.get("/api/rooms/ZZZZ").status_code == 404
        assert "Pandemic" in client.get(f"/r/{code}").text
        with client.websocket_connect(f"/ws/{code}") as ws:
            ws.send_json({"token": TOKENS[0], "name": "Ana"})
            assert ws.receive_json()["type"] == "welcome"
            state = ws.receive_json()
            assert state["type"] == "state" and state["seats"][0]["name"] == "Ana"
            ws.send_json({"type": "start"})
            error = ws.receive_json()
            assert error["type"] == "error" and error["message"].startswith("Pandemic needs at least 2 players")
