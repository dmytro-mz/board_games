"""A party: the people in one room, their leader, the game vote and the game they are playing.

Level 1 is creating the party (`/`), level 2 the game selection (phase "select"), level 3 the chosen game's own
table (phase "game"), whose lobby and play are entirely the game's. The party owns who is leader: the game table's
host always follows it (`GameRoom.set_host`).

All mutations are synchronous and run on the event loop thread; every change is pushed to each listener as a full
per-viewer snapshot (`Party.state_for`). Starting and stopping a game table's driver is delegated to `run_game`, so
this module stays free of asyncio and is tested with plain calls.
"""

from __future__ import annotations

import logging
import secrets
import time
from collections import Counter
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any, Protocol

from boardgames.games import Backend, GameRoom, GameSpec

log = logging.getLogger(__name__)

MAX_NAME = 20
MAX_MEMBERS = 40
LEADER_GRACE = 20.0  # seconds a disconnected leader keeps the role before it moves on

# Starts driving a game table (bots, timers) and returns the function that stops it.
GameRunner = Callable[[GameRoom], Callable[[], None]]


class PartyError(Exception):
    """A rejected request; the message is shown to the user."""


class Listener(Protocol):
    member_id: str

    def send(self, message: dict[str, Any]) -> None: ...


@dataclass
class Member:
    id: str
    token: str
    name: str
    connections: int = 0
    disconnected_at: float | None = None

    @property
    def online(self) -> bool:
        return self.connections > 0


@dataclass
class BackRequest:
    """The leader asked to go back to game selection; everyone else online has to accept."""

    by: str
    replies: dict[str, bool] = field(default_factory=dict)  # member id -> accepted


def clean_name(text: object) -> str:
    if not isinstance(text, str):
        return ""
    return " ".join(text.split())[:MAX_NAME]


class Party:
    def __init__(
        self,
        party_id: str,
        games: dict[str, GameSpec],
        backends: dict[str, Backend],
        run_game: GameRunner | None = None,
    ) -> None:
        self.id = party_id
        self.games = games
        self.backends = backends
        self.run_game = run_game or (lambda room: lambda: None)
        self.members: dict[str, Member] = {}
        self.leader_id: str | None = None
        self.votes: dict[str, str] = {}  # member id -> game key
        self.game_key: str | None = None
        self.room: GameRoom | None = None
        self.back: BackRequest | None = None
        self.listeners: set[Listener] = set()
        self.seq = 0
        self.last_activity = time.monotonic()
        self.closed = False
        self._stop_game: Callable[[], None] | None = None
        self._game_status: str | None = None

    # ------------------------------------------------------------------ members
    @property
    def phase(self) -> str:
        return "game" if self.room is not None else "select"

    def join(self, token: str, name: object, origin: str = "") -> Member:
        name = clean_name(name)
        member = next((m for m in self.members.values() if m.token == token), None)
        if member is None:
            if len(self.members) >= MAX_MEMBERS:
                raise PartyError("This room is full")
            member = Member(id=secrets.token_hex(4), token=token, name=name or f"Player {len(self.members) + 1}")
            self.members[member.id] = member
            where = f" from {origin}" if origin else ""
            if self.leader_id is None:
                self.leader_id = member.id
                log.info("room %s opened by %s%s", self.id, member.name, where)
            else:
                log.info("room %s: %s joined%s", self.id, member.name, where)
        elif name and name != member.name:
            log.info("room %s: %s is now called %s", self.id, member.name, name)
            member.name = name
        return member

    def connect(self, listener: Listener) -> None:
        member = self.members[listener.member_id]
        if not member.online and member.disconnected_at is not None:
            log.info("room %s: %s is back", self.id, member.name)
        member.connections += 1
        member.disconnected_at = None
        self.listeners.add(listener)
        self.last_activity = time.monotonic()
        listener.send({"type": "welcome", "you": member.id})
        self._emit()

    def disconnect(self, listener: Listener) -> None:
        self.listeners.discard(listener)
        member = self.members.get(listener.member_id)
        if member is None:
            return
        member.connections = max(0, member.connections - 1)
        if not member.online:
            member.disconnected_at = time.monotonic()
            log.info("room %s: %s left", self.id, member.name)
        self.last_activity = time.monotonic()
        self._check_back()
        self._emit()

    def online(self) -> list[Member]:
        return [m for m in self.members.values() if m.online]

    def check_leader(self) -> None:
        """Hand the leader role to a connected member once the leader has been gone a while."""
        leader = self.members.get(self.leader_id or "")
        if leader is not None and leader.online:
            return
        if leader is not None and leader.disconnected_at and time.monotonic() - leader.disconnected_at < LEADER_GRACE:
            return
        online = self.online()
        if not online:
            return
        self._set_leader(online[0])

    def _set_leader(self, member: Member) -> None:
        self.leader_id = member.id
        log.info("room %s: %s is now the leader", self.id, member.name)
        self.back = None
        self._sync_host()
        self._emit()

    @property
    def idle_for(self) -> float:
        busy = self.listeners or (self.room is not None and getattr(self.room, "listeners", None))
        return 0.0 if busy else time.monotonic() - self.last_activity

    def describe(self) -> str:
        """One line for the server console."""
        leader = self.members.get(self.leader_id or "")
        parts = [self.id, f"leader {leader.name if leader else '-'}", f"{len(self.online())} online"]
        if self.room is not None and self.game_key is not None:
            parts.append(f"{self.games[self.game_key].title}: {self.room.describe()}")
        else:
            parts.append("choosing a game")
        return " · ".join(parts)

    # ------------------------------------------------------------------ requests
    def handle(self, member_id: str, msg: dict[str, Any]) -> None:
        member = self.members[member_id]
        kind = msg.get("type")
        self.last_activity = time.monotonic()
        leader_only = {"launch", "back_request", "back_cancel", "back_force"}
        if kind in leader_only and member_id != self.leader_id:
            raise PartyError("Only the room leader can do that")
        match kind:
            case "rename":
                name = clean_name(msg.get("name"))
                if name and name != member.name:
                    log.info("room %s: %s is now called %s", self.id, member.name, name)
                    member.name = name
            case "vote":
                self._vote(member, msg.get("game"))
            case "launch":
                self._launch(msg.get("game"))
            case "back_request":
                self._request_back(member)
            case "back_reply":
                self._reply_back(member, msg.get("accept"))
            case "back_cancel":
                if self.back is not None:
                    self.back = None
            case "back_force":
                if self.room is None:
                    raise PartyError("You are already choosing a game")
                self._to_selection(forced=True)
                return
            case _:
                raise PartyError(f"unknown request {kind!r}")
        self._emit()

    def _vote(self, member: Member, key: object) -> None:
        if self.room is not None:
            raise PartyError("A game is already running")
        if not isinstance(key, str) or key not in self.games:
            raise PartyError("Unknown game")
        if self.votes.get(member.id) == key:
            del self.votes[member.id]
        else:
            self.votes[member.id] = key

    def tally(self) -> dict[str, int]:
        """Votes of the members who are here; votes of people who left don't count."""
        online = {m.id for m in self.online()}
        return dict(Counter(key for mid, key in self.votes.items() if mid in online))

    def selected(self) -> str | None:
        """The leader's own vote."""
        return self.votes.get(self.leader_id or "")

    def most_voted(self) -> str | None:
        """The game with the most votes, or None on a tie (or no votes)."""
        ranked = sorted(self.tally().items(), key=lambda kv: -kv[1])
        if not ranked or (len(ranked) > 1 and ranked[0][1] == ranked[1][1]):
            return None
        return ranked[0][0]

    def _launch(self, key: object) -> None:
        if self.room is not None:
            raise PartyError("A game is already running")
        if not isinstance(key, str) or key not in self.games:
            raise PartyError("Unknown game")
        if key not in (self.selected(), self.most_voted()):
            raise PartyError("Vote for that game first")
        self.start_game(key)

    def start_game(self, key: str, room: GameRoom | None = None) -> GameRoom:
        """Open the game's table for this party (a prepared `room` is used as is, for tests and scripts)."""
        spec = self.games[key]
        if room is None:
            room = self.backends[key].new_room(self.id)
        self.room, self.game_key = room, key
        self.votes.clear()
        self.back = None
        self._sync_host()
        self._game_status = room.status
        self._stop_game = self.run_game(room)
        log.info("room %s: playing %s", self.id, spec.title)
        return room

    def _sync_host(self) -> None:
        """The game table's host is always the party leader (joining them to the table if needed)."""
        leader = self.members.get(self.leader_id or "")
        if self.room is None or leader is None:
            return
        member = next((m for m in self.room.members.values() if m.token == leader.token), None)
        if member is None:
            member = self.room.join(leader.token, leader.name)
        if self.room.host_id != member.id:
            self.room.set_host(member.id)

    # ------------------------------------------------------------------ back to game selection
    def _request_back(self, leader: Member) -> None:
        if self.room is None:
            raise PartyError("You are already choosing a game")
        if self.room.status != "lobby":
            raise PartyError("Finish the game or end it from the game's menu first")
        self.back = BackRequest(by=leader.id)
        self._check_back()

    def _reply_back(self, member: Member, accept: object) -> None:
        if self.back is None:
            raise PartyError("Nobody asked to go back")
        if member.id == self.back.by:
            return
        self.back.replies[member.id] = bool(accept)
        self._check_back()

    def waiting_for(self) -> list[Member]:
        """Online members (other than the leader) who haven't accepted yet."""
        if self.back is None:
            return []
        return [m for m in self.online() if m.id != self.back.by and not self.back.replies.get(m.id)]

    def _check_back(self) -> None:
        if self.back is not None and self.room is not None and not self.waiting_for():
            self._to_selection(forced=False)

    def _to_selection(self, forced: bool) -> None:
        stop, self._stop_game = self._stop_game, None
        room = self.room
        self.room, self.game_key, self.back = None, None, None
        self._game_status = None
        self.votes.clear()
        if stop is not None:
            stop()
        if room is not None:
            room.close()
        log.info("room %s: back to game selection%s", self.id, " (forced)" if forced else "")
        self._emit()

    def game_changed(self) -> None:
        """Re-check the game table (after a game message or a timer); tell everyone if its status changed."""
        if self.room is None:
            return
        status = self.room.status
        if status != self._game_status:
            self._game_status = status
            if status != "lobby":
                self.back = None
            self._emit()

    def close(self) -> None:
        self.closed = True
        stop, self._stop_game = self._stop_game, None
        if stop is not None:
            stop()
        if self.room is not None:
            self.room.close()

    # ------------------------------------------------------------------ output
    def _emit(self) -> None:
        self.seq += 1
        for listener in list(self.listeners):
            listener.send(self.state_for(listener.member_id))

    def state_for(self, member_id: str) -> dict[str, Any]:
        game = None
        if self.room is not None and self.game_key is not None:
            game = {"key": self.game_key, "status": self.room.status}
        back = None
        if self.back is not None:
            back = {
                "by": self.back.by,
                "accepted": [mid for mid, ok in self.back.replies.items() if ok],
                "declined": [mid for mid, ok in self.back.replies.items() if not ok],
                "waiting": [m.id for m in self.waiting_for()],
            }
        return {
            "type": "state",
            "seq": self.seq,
            "room": self.id,
            "you": member_id,
            "leader": self.leader_id,
            "phase": self.phase,
            "members": [
                {"id": m.id, "name": m.name, "online": m.online, "vote": self.votes.get(m.id)}
                for m in self.members.values()
            ],
            "tally": self.tally(),
            "selected": self.selected(),
            "most_voted": self.most_voted(),
            "game": game,
            "back": back,
        }
