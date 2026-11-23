"""The party: votes, launching a game, the leader, and going back to the game selection."""

from __future__ import annotations

import time
from typing import Any

import pytest

from boardgames import party as party_module
from boardgames.games import load_games
from boardgames.party import Party, PartyError
from lostcities.bots import REGISTRY

GAMES = load_games(("lostcities", "skyteam", "codenames"))


class Inbox:
    def __init__(self, member_id: str) -> None:
        self.member_id = member_id
        self.messages: list[dict[str, Any]] = []

    def send(self, message: dict[str, Any]) -> None:
        self.messages.append(message)

    @property
    def state(self) -> dict[str, Any]:
        return next(m for m in reversed(self.messages) if m["type"] == "state")


def _party(n: int = 3) -> tuple[Party, list[Inbox]]:
    backends = {key: spec.backend(delay_scale=0.0) for key, spec in GAMES.items()}
    running: list[Any] = []

    def run_game(room: Any) -> Any:
        running.append(room)
        return lambda: running.remove(room)

    party = Party("ROOM1", GAMES, backends, run_game=run_game)
    party.running = running  # type: ignore[attr-defined]
    inboxes = []
    for i in range(n):
        member = party.join(f"token-{i:02d}-xxxxxxxxxxxx", f"P{i}")
        inbox = Inbox(member.id)
        party.connect(inbox)
        inboxes.append(inbox)
    return party, inboxes


def test_first_member_leads() -> None:
    party, (a, b, _) = _party()
    assert party.leader_id == a.member_id
    assert b.state["leader"] == a.member_id
    assert b.state["phase"] == "select"
    with pytest.raises(PartyError, match="leader"):
        party.handle(b.member_id, {"type": "launch", "game": "lostcities"})


def test_rejoining_with_the_same_token_is_the_same_member() -> None:
    party, (a, *_) = _party()
    again = party.join("token-00-xxxxxxxxxxxx", "New name")
    assert again.id == a.member_id
    assert again.name == "New name"


def test_one_vote_each_click_again_takes_it_back() -> None:
    party, (_a, b, c) = _party()
    party.handle(b.member_id, {"type": "vote", "game": "lostcities"})
    assert party.tally() == {"lostcities": 1}
    party.handle(b.member_id, {"type": "vote", "game": "skyteam"})  # moves the vote
    assert party.tally() == {"skyteam": 1}
    party.handle(b.member_id, {"type": "vote", "game": "skyteam"})  # takes it back
    assert party.tally() == {}
    with pytest.raises(PartyError):
        party.handle(c.member_id, {"type": "vote", "game": "chess"})


def test_selected_is_the_leaders_vote_and_ties_have_no_most_voted() -> None:
    party, (a, b, c) = _party()
    party.handle(a.member_id, {"type": "vote", "game": "lostcities"})
    assert (party.selected(), party.most_voted()) == ("lostcities", "lostcities")
    party.handle(b.member_id, {"type": "vote", "game": "skyteam"})
    assert party.selected() == "lostcities"
    assert party.most_voted() is None  # 1 : 1
    party.handle(c.member_id, {"type": "vote", "game": "skyteam"})
    assert party.most_voted() == "skyteam"
    state = a.state
    assert (state["selected"], state["most_voted"]) == ("lostcities", "skyteam")
    assert state["tally"] == {"lostcities": 1, "skyteam": 2}


def test_votes_of_people_who_left_do_not_count() -> None:
    party, (_a, b, _c) = _party()
    party.handle(b.member_id, {"type": "vote", "game": "skyteam"})
    party.disconnect(b)
    assert party.tally() == {}


def test_leader_can_only_launch_the_selected_or_most_voted_game() -> None:
    party, (a, b, c) = _party()
    with pytest.raises(PartyError, match="Vote"):
        party.handle(a.member_id, {"type": "launch", "game": "lostcities"})
    party.handle(b.member_id, {"type": "vote", "game": "skyteam"})
    party.handle(a.member_id, {"type": "launch", "game": "skyteam"})
    assert party.phase == "game"
    assert c.state["game"] == {"key": "skyteam", "status": "lobby"}
    assert party.votes == {}
    assert party.running == [party.room]  # type: ignore[attr-defined]
    with pytest.raises(PartyError):
        party.handle(a.member_id, {"type": "vote", "game": "lostcities"})


def test_game_table_host_is_the_party_leader() -> None:
    party, (a, _b, _c) = _party()
    party.handle(a.member_id, {"type": "vote", "game": "lostcities"})
    party.handle(a.member_id, {"type": "launch", "game": "lostcities"})
    room = party.room
    assert room is not None
    # b reaches the table first, but the leader still hosts it
    b_table = room.join("token-01-xxxxxxxxxxxx", "P1")
    leader_table = next(m for m in room.members.values() if m.token == "token-00-xxxxxxxxxxxx")
    assert room.host_id == leader_table.id != b_table.id


def test_leader_hands_over_after_a_grace_period_and_the_table_follows(monkeypatch: pytest.MonkeyPatch) -> None:
    clock = [1000.0]
    monkeypatch.setattr(party_module.time, "monotonic", lambda: clock[0])
    party, (a, b, _c) = _party()
    party.handle(a.member_id, {"type": "vote", "game": "lostcities"})
    party.handle(a.member_id, {"type": "launch", "game": "lostcities"})
    party.disconnect(a)
    party.check_leader()
    assert party.leader_id == a.member_id  # still within the grace period
    clock[0] += party_module.LEADER_GRACE + 1
    party.check_leader()
    assert party.leader_id == b.member_id
    room = party.room
    assert room is not None
    host = room.members[room.host_id or ""]
    assert host.token == "token-01-xxxxxxxxxxxx"


def _in_game(n: int = 3) -> tuple[Party, list[Inbox]]:
    party, inboxes = _party(n)
    leader = inboxes[0]
    party.handle(leader.member_id, {"type": "vote", "game": "lostcities"})
    party.handle(leader.member_id, {"type": "launch", "game": "lostcities"})
    return party, inboxes


def test_back_needs_everyone_online_to_accept() -> None:
    party, (a, b, c) = _in_game()
    room = party.room
    party.handle(a.member_id, {"type": "back_request"})
    assert b.state["back"] == {"by": a.member_id, "accepted": [], "declined": [], "waiting": [b.member_id, c.member_id]}
    party.handle(b.member_id, {"type": "back_reply", "accept": True})
    assert party.phase == "game"
    party.handle(c.member_id, {"type": "back_reply", "accept": True})
    assert party.phase == "select"
    assert c.state["phase"] == "select" and c.state["back"] is None
    assert room is not None and room.closed
    assert party.running == []  # type: ignore[attr-defined]


def test_a_decline_is_shown_and_the_leader_can_still_force() -> None:
    party, (a, b, c) = _in_game()
    party.handle(a.member_id, {"type": "back_request"})
    party.handle(b.member_id, {"type": "back_reply", "accept": False})
    party.handle(c.member_id, {"type": "back_reply", "accept": True})
    back = a.state["back"]
    assert (back["declined"], back["accepted"], back["waiting"]) == ([b.member_id], [c.member_id], [b.member_id])
    assert party.phase == "game"
    with pytest.raises(PartyError, match="leader"):
        party.handle(b.member_id, {"type": "back_force"})
    party.handle(a.member_id, {"type": "back_force"})
    assert party.phase == "select"


def test_leader_can_cancel_the_request() -> None:
    party, (a, b, _) = _in_game()
    party.handle(a.member_id, {"type": "back_request"})
    party.handle(a.member_id, {"type": "back_cancel"})
    assert b.state["back"] is None and party.phase == "game"
    with pytest.raises(PartyError):
        party.handle(b.member_id, {"type": "back_reply", "accept": True})


def test_offline_players_do_not_block_going_back() -> None:
    party, (a, b, c) = _in_game()
    party.handle(a.member_id, {"type": "back_request"})
    party.handle(b.member_id, {"type": "back_reply", "accept": True})
    party.disconnect(c)  # the last one who had to answer leaves
    assert party.phase == "select"


def test_alone_the_leader_goes_back_at_once() -> None:
    party, (a,) = _in_game(1)
    party.handle(a.member_id, {"type": "back_request"})
    assert party.phase == "select"


def test_back_only_from_the_game_lobby() -> None:
    party, (a, _b, _) = _in_game()
    room = party.room
    assert room is not None
    host = next(m for m in room.members.values() if m.token == "token-00-xxxxxxxxxxxx")
    room.handle(host.id, {"type": "add_bot", "bot": next(iter(REGISTRY))})
    room.handle(host.id, {"type": "start"})
    party.game_changed()
    assert a.state["game"]["status"] == "playing"
    with pytest.raises(PartyError, match="game's menu"):
        party.handle(a.member_id, {"type": "back_request"})
    room.handle(host.id, {"type": "to_lobby"})
    party.game_changed()
    assert a.state["game"]["status"] == "lobby"
    party.handle(a.member_id, {"type": "back_request"})
    assert party.back is not None


def test_idle_counts_the_game_table_connections(monkeypatch: pytest.MonkeyPatch) -> None:
    party, inboxes = _in_game(1)
    room = party.room
    assert room is not None
    table = Inbox(room.join("token-00-xxxxxxxxxxxx", "P0").id)
    room.connect(table)
    party.disconnect(inboxes[0])
    real = time.monotonic
    monkeypatch.setattr(party_module.time, "monotonic", lambda: real() + 10_000)
    assert party.idle_for == 0.0
    room.disconnect(table)
    assert party.idle_for > 9_000
