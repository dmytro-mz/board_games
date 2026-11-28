"""The multiplayer table (`Room`) driven through its protocol, hidden information, and an HTTP/WebSocket smoke test."""

from __future__ import annotations

import asyncio
import random
from typing import Any

import pytest

from boardgames.testing import GameClient
from toybattle.bots import REGISTRY
from toybattle.game.engine import Phase
from toybattle.game.terrains import TERRAINS
from toybattle.game.troops import army
from toybattle.web.room import Room, RoomError

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


def _room(humans: int = 2, bot: bool = False, **settings: Any) -> tuple[Room, list[Inbox]]:
    room = Room("TEST", delay_scale=0.0, seed=5, bot_budget=0.02)
    inboxes = [_join(room, i) for i in range(humans)]
    if bot:
        room.handle(inboxes[0].member_id, {"type": "add_bot", "bot": "general"})
    if settings:
        room.handle(inboxes[0].member_id, {"type": "settings", "changes": settings})
    return room, inboxes


def _play_randomly(room: Room, inboxes: list[Inbox], on_step: Any = None, limit: int = 3000) -> None:
    rng = random.Random(1)
    for _ in range(limit):
        if on_step:
            on_step()
        if room.status != "playing":
            return
        moved = False
        for inbox in inboxes:
            legal = inbox.last_state["game"]["legal"]
            if legal:
                room.handle(inbox.member_id, {"type": "action", "action": rng.choice(legal)})
                moved = True
                break
        if not moved:
            room.step_bots(limit=1)
    raise AssertionError("game did not finish")


def _rack_ids(state: dict[str, Any], side: int) -> list[int]:
    return state["game"]["racks"][side]["troops"]


# ------------------------------------------------------------------ flow
@pytest.mark.parametrize("terrain", list(TERRAINS))
def test_two_humans_play_a_whole_game(terrain: str) -> None:
    room, inboxes = _room(terrain=terrain)
    room.handle(inboxes[0].member_id, {"type": "start"})
    assert room.status == "playing"
    _play_randomly(room, inboxes)
    assert room.status == "game_over"
    for inbox in inboxes:
        g = inbox.last_state["game"]
        assert g["result"] is not None and g["phase"] == "over" and g["legal"] == []
        assert g["terrain"] == terrain


def test_human_vs_bot_and_rematch() -> None:
    room, inboxes = _room(humans=1, bot=True, special=False)
    room.handle(inboxes[0].member_id, {"type": "start"})
    assert room.game is not None and not room.game.special
    _play_randomly(room, inboxes)
    assert room.status == "game_over"
    room.handle(inboxes[0].member_id, {"type": "play_again"})
    assert room.status == "playing" and room.game_no == 2
    room.handle(inboxes[0].member_id, {"type": "to_lobby"})
    assert room.status == "lobby" and room.game is None


def test_bots_play_each_other_to_the_end() -> None:
    room, inboxes = _room(humans=1, bot=True)
    room.handle(inboxes[0].member_id, {"type": "stand"})
    room.handle(inboxes[0].member_id, {"type": "add_bot", "bot": "general"})
    assert [s.name for s in room.seats] == ["The General", "The General 2"]
    room.handle(inboxes[0].member_id, {"type": "start"})
    room.step_bots()
    assert room.status == "game_over"
    room.game.check()  # type: ignore[union-attr]


def test_random_terrain_is_drawn_at_start() -> None:
    room, inboxes = _room(terrain="random")
    room.handle(inboxes[0].member_id, {"type": "start"})
    assert room.game is not None and room.game.terrain_key in TERRAINS
    assert inboxes[1].last_state["settings"]["terrain"] == "random"


def test_settings_validation_is_all_or_nothing() -> None:
    room, inboxes = _room()
    host = inboxes[0].member_id
    for bad in (
        {"terrain": "moon"},
        {"special": "yes"},
        {"turn_timer": 7},
        {"bot_speed": "warp"},
        {"rounds": 3},
        {"turn_timer": True},
    ):
        with pytest.raises(RoomError):
            room.handle(host, {"type": "settings", "changes": {"terrain": "lava", **bad}})
    assert room.settings.terrain == "rug"
    room.handle(
        host,
        {"type": "settings", "changes": {"terrain": "lava", "special": False, "turn_timer": 60, "bot_speed": "fast"}},
    )
    assert (room.settings.terrain, room.settings.special, room.settings.turn_timer) == ("lava", False, 60)


def test_only_the_host_runs_the_lobby() -> None:
    room, inboxes = _room()
    guest = inboxes[1].member_id
    for msg in (
        {"type": "start"},
        {"type": "settings", "changes": {"terrain": "lava"}},
        {"type": "add_bot", "bot": "general"},
        {"type": "swap"},
    ):
        with pytest.raises(RoomError):
            room.handle(guest, msg)


def test_swap_changes_armies() -> None:
    room, inboxes = _room()
    room.handle(inboxes[0].member_id, {"type": "swap"})
    assert room.seat_of(inboxes[0].member_id) == 1
    assert inboxes[0].last_state["seats"][1]["color"] == "red"


def test_illegal_and_out_of_turn_actions_are_rejected() -> None:
    room, inboxes = _room()
    room.handle(inboxes[0].member_id, {"type": "start"})
    game = room.game
    assert game is not None
    other = 1 - game.current
    waiting = next(i for i in inboxes if room.seat_of(i.member_id) == other)
    with pytest.raises(RoomError):
        room.handle(waiting.member_id, {"type": "action", "action": {"type": "draw"}})
    mover = next(i for i in inboxes if room.seat_of(i.member_id) == game.current)
    for bad in ({"type": "place", "troop": 999, "node": 0}, {"type": "nuke"}, "draw", {"type": "knock", "node": 1}):
        with pytest.raises(RoomError):
            room.handle(mover.member_id, {"type": "action", "action": bad})


def test_spectator_cannot_act() -> None:
    room, inboxes = _room()
    spectator = _join(room, 2)
    room.handle(inboxes[0].member_id, {"type": "start"})
    assert room.seat_of(spectator.member_id) is None
    with pytest.raises(RoomError):
        room.handle(spectator.member_id, {"type": "action", "action": {"type": "draw"}})
    assert spectator.last_state["game"]["legal"] == []


# ------------------------------------------------------------------ hidden information
def test_hidden_information_throughout_a_game() -> None:
    room, inboxes = _room(terrain="sandpit")
    spectator = _join(room, 2)
    room.handle(inboxes[0].member_id, {"type": "start"})
    game = room.game
    assert game is not None

    def check() -> None:
        if game.phase == Phase.OVER:
            return
        for inbox in [*inboxes, spectator]:
            state = room.state_for(inbox.member_id)
            g = state["game"]
            you = state["you"]["seat"]
            for side in (0, 1):
                rack = g["racks"][side]
                assert rack["count"] == len(game.rack[side])
                if side == you:
                    assert sorted(rack["troops"]) == sorted(game.rack[side])
                    assert sorted(rack["pinned"]) == sorted(game.pinned[side])
                    assert rack["hidden"] == 0
                else:
                    assert set(rack["troops"]) == game.known[side]
                    assert set(rack["pinned"]) <= game.known[side]
                    assert rack["hidden"] == len(game.rack[side]) - len(game.known[side])
            assert g["reserves"] == [len(r) for r in game.reserve]
            assert "removed_troops" not in g
            # no troop id of a hidden place appears anywhere in this viewer's state
            hidden = set()
            for side in (0, 1):
                hidden |= set(game.reserve[side]) | set(game.removed[side])
                if side != you:
                    hidden |= set(game.rack[side]) - game.known[side]
            assert not hidden & _ints(g)
        # events: drawn troops only for the drawer
        for inbox in [*inboxes, spectator]:
            last = inbox.last_state
            you = last["you"]["seat"]
            for ev in (last.get("event") or {}).get("events", []):
                if ev["kind"] == "draw" and ev["seat"] != you:
                    assert all(t is None for t in ev["troops"])
                if ev["kind"] == "pin" and ev["target"] != you and ev["troop"] is not None:
                    assert ev["troop"] in game.known[ev["target"]]

    _play_randomly(room, inboxes, on_step=check)
    final = inboxes[0].last_state["game"]
    assert final["phase"] == "over" and "removed_troops" in final
    for side in (0, 1):  # racks are revealed at the end
        assert sorted(final["racks"][side]["troops"]) == sorted(game.rack[side])


def _ints(value: Any, key: str = "") -> set[int]:
    """Troop ids anywhere in the game state (only under keys that hold troops)."""
    out: set[int] = set()
    if isinstance(value, dict):
        for k, v in value.items():
            out |= _ints(v, k)
    elif isinstance(value, list):
        if key in ("troops", "pinned", "known", "discard", "stacks", "removed_troops"):
            for v in value:
                if isinstance(v, int):
                    out.add(v)
                else:
                    out |= _ints(v, key)
        else:
            for v in value:
                out |= _ints(v, key)
    elif isinstance(value, int) and key == "troop":
        out.add(value)
    return out


def test_legal_only_for_the_player_to_move() -> None:
    room, inboxes = _room()
    room.handle(inboxes[0].member_id, {"type": "start"})
    game = room.game
    assert game is not None
    for inbox in inboxes:
        legal = room.state_for(inbox.member_id)["game"]["legal"]
        assert bool(legal) == (room.seat_of(inbox.member_id) == game.current)


def test_all_troops_accounted_for_in_the_owner_view() -> None:
    room, inboxes = _room()
    room.handle(inboxes[0].member_id, {"type": "start"})
    state = room.state_for(inboxes[0].member_id)
    g = state["game"]
    assert set(_rack_ids(state, 0)) <= set(army(0))
    assert sum(g["reserves"]) + sum(r["count"] for r in g["racks"]) + sum(g["removed"]) == 48


# ------------------------------------------------------------------ automation
def test_autoplay_for_a_disconnected_player() -> None:
    room, inboxes = _room()
    room.handle(inboxes[0].member_id, {"type": "start"})
    with pytest.raises(RoomError):  # still connected
        room.handle(inboxes[0].member_id, {"type": "autoplay", "seat": 1, "on": True})
    room.disconnect(inboxes[1])
    room.handle(inboxes[0].member_id, {"type": "autoplay", "seat": room.seat_of(inboxes[1].member_id), "on": True})
    _play_randomly(room, [inboxes[0]])
    assert room.status == "game_over"


def test_driver_plays_bot_moves_in_a_thread() -> None:
    async def run() -> None:
        room, inboxes = _room(humans=1, bot=True)
        room.handle(inboxes[0].member_id, {"type": "stand"})
        room.handle(inboxes[0].member_id, {"type": "add_bot", "bot": "general"})
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


def test_turn_timer_hands_the_turn_to_the_autopilot() -> None:
    room, inboxes = _room(turn_timer=30)
    room.handle(inboxes[0].member_id, {"type": "start"})
    game = room.game
    assert game is not None and room._deadline is not None
    seat = game.current
    turn = game.turn
    room._timeout()
    assert room._is_auto(seat)
    mover = next(i for i in inboxes if room.seat_of(i.member_id) == seat)
    with pytest.raises(RoomError):
        room.handle(mover.member_id, {"type": "action", "action": {"type": "draw"}})
    room.step_bots()
    assert (game.turn > turn and game.current != seat) or room.status == "game_over"
    assert not room._is_auto(game.current)


# ------------------------------------------------------------------ server
def test_http_config_and_rooms() -> None:
    with GameClient("toybattle", delay_scale=0.0) as client:
        config = client.get("/api/config").json()
        assert {b["key"] for b in config["bots"]} == set(REGISTRY) == {"general"}
        assert [t["key"] for t in config["terrains"]] == list(TERRAINS)
        assert len(config["kinds"]) == 8 and config["max_seats"] == 2 and config["reactions"]
        code = client.post("/api/rooms").json()["room"]
        assert client.get(f"/api/rooms/{code}").json()["status"] == "lobby"
        page = client.get(f"/r/{code}")
        assert page.status_code == 200 and "/g/toybattle/static/app.js" in page.text
        for name in ("app.js", "art.js", "board.js", "rules.js", "sound.js", "style.css"):
            assert client.get(f"/static/{name}").status_code == 200


def test_websocket_handshake_and_first_moves() -> None:
    with GameClient("toybattle", delay_scale=0.0) as client:
        code = client.post("/api/rooms").json()["room"]
        with client.websocket_connect(f"/ws/{code}") as ws:
            ws.send_json({"token": TOKENS[0], "name": "Ada"})
            welcome = ws.receive_json()
            assert welcome["type"] == "welcome" and welcome["bots"]
            state = ws.receive_json()
            assert state["type"] == "state" and state["status"] == "lobby"
            ws.send_json({"type": "start"})
            assert ws.receive_json()["type"] == "error"  # one player is not enough
            ws.send_json({"type": "add_bot", "bot": "general"})
            ws.send_json({"type": "start"})
            seen = []
            for _ in range(80):
                msg = ws.receive_json()
                seen.append(msg)
                if msg["type"] == "state" and msg["status"] == "playing" and msg["game"]["legal"]:
                    break
            playing = [m for m in seen if m["type"] == "state" and m["status"] == "playing"]
            assert playing
            g = playing[-1]["game"]
            assert len(g["racks"][0]["troops"]) in (3, 4, 5, 6)
            assert g["racks"][1]["troops"] == [] or set(g["racks"][1]["troops"]) <= set(g["racks"][1]["known"])
