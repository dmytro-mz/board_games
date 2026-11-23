from __future__ import annotations

import logging
import random
import time
from collections.abc import Callable
from typing import Any

import pytest

from boardgames.testing import GameClient
from skyjo.game import DRAW_DECK, FLIP_BASE, Phase
from skyjo.game.board import FACE_UP
from skyjo.web.bots import BotCatalog, BotType
from skyjo.web.room import Room, RoomError


class Inbox:
    def __init__(self, member_id: str) -> None:
        self.member_id = member_id
        self.messages: list[dict[str, Any]] = []

    def send(self, message: dict[str, Any]) -> None:
        self.messages.append(message)

    def states(self) -> list[dict[str, Any]]:
        return [m for m in self.messages if m["type"] == "state"]


def _room(**kw: Any) -> Room:
    return Room("TEST", BotCatalog(), delay_scale=0.0, seed=1, **kw)


def _player(room: Room, name: str) -> Inbox:
    member = room.join(f"token-{name}-0123456789", name)
    inbox = Inbox(member.id)
    room.connect(inbox)
    return inbox


def _run(room: Room, humans: list[Inbox], rng: random.Random, on_step: Callable[[], None] | None = None) -> None:
    """Drive the room like the async driver would, with humans picking random legal moves."""
    for _ in range(20_000):
        if room.status == "game_over":
            return
        if on_step is not None:
            on_step()
        plan = room.plan()
        if plan is not None:
            plan[1]()
            continue
        moved = False
        for inbox in humans:
            state = room.state_for(inbox.member_id)
            if room.status == "round_over":
                if not room.seats[state["you"]["seat"]].ready:
                    room.handle(inbox.member_id, {"type": "ready"})
                    moved = True
            elif state["game"]["legal"]:
                room.handle(inbox.member_id, {"type": "action", "action": rng.choice(state["game"]["legal"])})
                moved = True
                break
        assert moved, "room is stuck"
    raise AssertionError("game did not finish")


def _assert_no_hidden_leak(room: Room, inbox: Inbox) -> None:
    if room.status != "playing":
        return
    rnd = room.ended_round or room.game.round  # type: ignore[union-attr]
    state = room.state_for(inbox.member_id)
    for seat, cells in enumerate(state["game"]["boards"]):
        shown = sum(1 for c in cells if isinstance(c, int))
        face_up = sum(1 for s in rnd.boards[seat].status if s == FACE_UP)
        pending = len(room.pending.get(seat, ())) if rnd.phase == Phase.SETUP else 0
        assert shown == face_up + pending


def test_full_game_with_bots_and_a_human() -> None:
    room = _room()
    alice = _player(room, "alice")
    room.handle(alice.member_id, {"type": "add_bot", "bot": "expert"})
    room.handle(alice.member_id, {"type": "add_bot", "bot": "greedy"})
    room.handle(alice.member_id, {"type": "start"})
    assert room.status == "playing"
    _run(room, [alice], random.Random(0), on_step=lambda: _assert_no_hidden_leak(room, alice))
    assert room.status == "game_over"
    final = alice.states()[-1]["game"]
    assert final["winners"]
    assert max(final["totals"]) >= 100
    kinds = {s["event"]["kind"] for s in alice.states() if s["event"]}
    assert {"draw", "replace", "flip", "game_start", "round_start"} <= kinds
    room.handle(alice.member_id, {"type": "play_again"})
    assert room.status == "playing" and room.game_no == 2


def test_console_log_says_who_is_at_which_table(caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.INFO, logger="skyjo.web")
    room = _room()
    alice = room.join("token-alice-0123456789", "alice", "10.0.0.5")
    room.connect(Inbox(alice.id))
    bob = _player(room, "bob")
    room.handle(alice.id, {"type": "add_bot", "bot": "expert"})
    room.handle(alice.id, {"type": "start"})
    _run(room, [Inbox(alice.id), bob], random.Random(0))
    text = caplog.text
    assert "table TEST opened by alice from 10.0.0.5" in text
    assert "table TEST: bob joined" in text
    assert "game 1 started with alice, bob, Expert (bot)" in text
    assert "game 1 won by" in text
    assert room.describe() == "TEST · game over · host alice · alice, bob, Expert (bot) · 2 online"


def test_setup_is_simultaneous_for_humans() -> None:
    room = _room()
    alice, bob = _player(room, "alice"), _player(room, "bob")
    room.handle(alice.member_id, {"type": "start"})
    bob_seat = room.seat_of(bob.member_id)
    alice_seat = room.seat_of(alice.member_id)
    assert (alice_seat, bob_seat) == (0, 1)
    room.handle(bob.member_id, {"type": "action", "action": FLIP_BASE + 0})
    room.handle(bob.member_id, {"type": "action", "action": FLIP_BASE + 3})
    with pytest.raises(RoomError):
        room.handle(bob.member_id, {"type": "action", "action": FLIP_BASE + 6})
    assert room.game.round.phase == Phase.SETUP  # type: ignore[union-attr]
    shown = room.state_for(alice.member_id)["game"]["boards"][1]
    assert isinstance(shown[0], int) and isinstance(shown[3], int)
    room.handle(alice.member_id, {"type": "action", "action": FLIP_BASE + 1})
    room.handle(alice.member_id, {"type": "action", "action": FLIP_BASE + 2})
    rnd = room.game.round  # type: ignore[union-attr]
    assert rnd.phase == Phase.CHOOSE_SOURCE
    assert room.state_for(alice.member_id)["event"] is None
    assert alice.states()[-1]["event"]["starter"] == rnd.current
    _assert_no_hidden_leak(room, alice)


def test_only_the_current_player_may_move() -> None:
    room = _room()
    alice, bob = _player(room, "alice"), _player(room, "bob")
    room.handle(alice.member_id, {"type": "start"})
    for inbox, positions in ((alice, (0, 1)), (bob, (0, 1))):
        for p in positions:
            room.handle(inbox.member_id, {"type": "action", "action": FLIP_BASE + p})
    current = room.game.round.current  # type: ignore[union-attr]
    waiting = bob if current == 0 else alice
    with pytest.raises(RoomError, match="not your turn"):
        room.handle(waiting.member_id, {"type": "action", "action": DRAW_DECK})


def test_host_only_requests_and_spectators() -> None:
    room = _room()
    alice, bob = _player(room, "alice"), _player(room, "bob")
    with pytest.raises(RoomError, match="host"):
        room.handle(bob.member_id, {"type": "add_bot", "bot": "ev"})
    room.handle(alice.member_id, {"type": "settings", "changes": {"end_score": 50, "turn_timer": 30}})
    assert room.settings.end_score == 50
    with pytest.raises(RoomError):
        room.handle(alice.member_id, {"type": "settings", "changes": {"end_score": 7}})
    room.handle(alice.member_id, {"type": "start"})
    carol = _player(room, "carol")
    assert room.seat_of(carol.member_id) is None
    assert room.state_for(carol.member_id)["game"]["legal"] == []
    with pytest.raises(RoomError, match="watching"):
        room.handle(carol.member_id, {"type": "action", "action": FLIP_BASE})


def test_policy_bots_are_limited_to_their_table_size() -> None:
    room = _room()
    room.catalog._bots["two"] = BotType("two", "random", "Two", "", 1, n_players=2)
    alice = _player(room, "alice")
    room.handle(alice.member_id, {"type": "add_bot", "bot": "two"})
    room.handle(alice.member_id, {"type": "add_bot", "bot": "random"})
    with pytest.raises(RoomError, match="2-player"):
        room.handle(alice.member_id, {"type": "start"})
    room.handle(alice.member_id, {"type": "remove_seat", "seat": 2})
    room.handle(alice.member_id, {"type": "start"})


def test_catalog_only_offers_any_table_size_policies(tmp_path) -> None:  # type: ignore[no-untyped-def]
    pytest.importorskip("torch")  # builds the test policies with the training network
    from skyjo.game import N_ACTIONS
    from skyjo.rl.encoding import ObsEncoder
    from skyjo.rl.network import ActorCritic
    from skyjo.rl.policy_agent import PolicyAgent

    for run, version in (("20260101-000000_ppo_v3", 3), ("20260102-000000_ppo_v4", 4)):
        enc = ObsEncoder(2, version)
        layers = ActorCritic(enc.dim, N_ACTIONS, (8,)).actor_layers()
        (tmp_path / run).mkdir()
        PolicyAgent(layers, n_players=2, obs_version=version).save(tmp_path / run / "policy_best.npz")

    catalog = BotCatalog([tmp_path])
    policies = [b for b in catalog.public() if str(b["key"]).startswith("ppo:")]
    assert [(b["label"], b["n_players"]) for b in policies] == [("AI ppo_v4", None)]
    with pytest.raises(ValueError, match="v4"):
        BotCatalog(extra_specs=[f"ppo:{tmp_path / '20260101-000000_ppo_v3' / 'policy_best.npz'}"])

    room = Room("TEST", catalog, delay_scale=0.0, seed=1)
    alice = _player(room, "alice")
    for _ in range(4):
        room.handle(alice.member_id, {"type": "add_bot", "bot": policies[0]["key"]})
    room.handle(alice.member_id, {"type": "start"})
    _run(room, [alice], random.Random(2))
    assert room.status == "game_over"


def test_turn_timer_lets_the_autopilot_move() -> None:
    room = _room()
    alice, bob = _player(room, "alice"), _player(room, "bob")
    room.handle(alice.member_id, {"type": "settings", "changes": {"turn_timer": 15}})
    room.handle(alice.member_id, {"type": "start"})
    assert room.state_for(alice.member_id)["game"]["time_left"] == pytest.approx(15, abs=1)
    assert room.plan() is not None and room.plan()[0] > 10  # type: ignore[index]
    key = room._deadline[0]  # type: ignore[index]
    room._deadline = (key, time.monotonic() - 1)
    room.plan()[1]()  # type: ignore[index]
    rnd = room.game.round  # type: ignore[union-attr]
    assert rnd.phase == Phase.CHOOSE_SOURCE
    turn = rnd.turn
    room._deadline = (room._deadline[0], time.monotonic() - 1)  # type: ignore[index]
    while rnd.turn == turn:
        room.plan()[1]()  # type: ignore[index]
    assert any("ran out of time" in e.get("text", "") for e in room.log)
    del bob


def test_disconnected_player_can_be_handed_to_the_autopilot() -> None:
    room = _room()
    alice, bob = _player(room, "alice"), _player(room, "bob")
    room.handle(alice.member_id, {"type": "start"})
    with pytest.raises(RoomError, match="connected"):
        room.handle(alice.member_id, {"type": "autoplay", "seat": 1, "on": True})
    room.disconnect(bob)
    room.handle(alice.member_id, {"type": "autoplay", "seat": 1, "on": True})
    _run(room, [alice], random.Random(1))
    assert room.status == "game_over"
    room.connect(bob)
    assert not room.seats[1].autoplay


def test_hint_returns_a_legal_action() -> None:
    room = _room()
    alice = _player(room, "alice")
    room.handle(alice.member_id, {"type": "add_bot", "bot": "random"})
    room.handle(alice.member_id, {"type": "start"})
    reply = room.handle(alice.member_id, {"type": "hint"})
    assert reply is not None and reply["action"] in room.state_for(alice.member_id)["game"]["legal"]


def test_websocket_roundtrip() -> None:
    with GameClient("skyjo", model_dirs=(), delay_scale=0.0) as client:
        assert client.get("/").status_code == 200
        assert client.get("/r/ABCDE").status_code == 200
        static = client.get("/static/app.js")
        assert static.status_code == 200
        assert static.headers["cache-control"] == "no-cache"
        code = client.post("/api/rooms").json()["room"]
        assert client.get(f"/api/rooms/{code}").json()["status"] == "lobby"
        with client.websocket_connect(f"/ws/{code}") as ws:
            ws.send_json({"type": "hello", "token": "x" * 20, "name": "Alice"})
            assert ws.receive_json()["type"] == "welcome"
            state = ws.receive_json()
            assert state["status"] == "lobby" and state["host"] == state["you"]["member"]
            ws.send_json({"type": "add_bot", "bot": "expert"})
            while (msg := ws.receive_json())["type"] != "state":
                pass
            assert len(msg["seats"]) == 2
            ws.send_json({"type": "start"})
            while not ((msg := ws.receive_json())["type"] == "state" and msg["status"] == "playing"):
                pass
            ws.send_json({"type": "action", "action": 999})
            while (msg := ws.receive_json())["type"] != "error":
                pass
        with client.websocket_connect("/ws/NOPE1") as ws:
            assert ws.receive_json()["type"] == "fatal"
