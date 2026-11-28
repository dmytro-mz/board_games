"""Table's bot plumbing: thinking off the event loop, and search bots thinking in worker processes."""

from __future__ import annotations

import asyncio
import threading
import time
from typing import Any

from boardgames.table import Plan, Table, think_apart


class Thinker(Table):
    """A table whose 'bot' takes 0.2 s to decide each of three moves."""

    def __init__(self) -> None:
        super().__init__("T", delay_scale=0.0)
        self.moves: list[tuple[int, str]] = []
        self.threads: list[str] = []

    def _slow(self, n: int) -> int:
        self.threads.append(threading.current_thread().name)
        time.sleep(0.2)
        return n * 10

    def plan(self) -> Plan | None:
        if len(self.moves) >= 3:
            return None
        n = len(self.moves)
        return 0.0, lambda: self.moves.append((self.think(("move", n), lambda: self._slow(n)), "applied"))


def test_think_runs_inline_when_called_directly() -> None:
    table = Thinker()
    for _ in range(3):
        plan = table.plan()
        assert plan is not None
        plan[1]()
    assert table.moves == [(0, "applied"), (10, "applied"), (20, "applied")]
    assert set(table.threads) == {threading.current_thread().name}


def test_drive_thinks_in_a_thread_and_keeps_the_loop_free() -> None:
    async def run() -> tuple[Thinker, float]:
        table = Thinker()
        task = asyncio.create_task(table.drive())
        worst, last = 0.0, time.perf_counter()
        while len(table.moves) < 3:
            await asyncio.sleep(0.005)
            now = time.perf_counter()
            worst, last = max(worst, now - last), now
        table.close()
        await task
        return table, worst

    table, worst = asyncio.run(run())
    assert table.moves == [(0, "applied"), (10, "applied"), (20, "applied")]
    assert threading.current_thread().name not in table.threads
    assert worst < 0.1, f"the event loop stalled for {worst * 1000:.0f} ms while the bot thought"


def test_a_thought_for_an_older_position_is_never_used() -> None:
    table = Thinker()
    table._thought = (("move", 5), 999)  # what a thread returned for a position the game has left
    plan = table.plan()
    assert plan is not None
    plan[1]()
    assert table.moves == [(0, "applied")]


class Counter:
    """A bot whose answers depend on its random state, like the search bots."""

    def __init__(self, seed: int) -> None:
        import random

        self.rng = random.Random(seed)

    def act(self, view: Any) -> int:
        return view * 1000 + self.rng.randrange(1000)


def test_thinking_apart_continues_the_bot_exactly() -> None:
    here = Counter(7)
    expected = [here.act(v) for v in range(4)]

    class Room(Table):
        pass

    async def run() -> list[int]:
        room = Room("P")
        room._autopilot = Counter(7)
        out = []
        for v in range(4):
            agent = room._autopilot
            action, thought = await think_apart(agent, "act", v)
            room._keep_agent(agent, thought)
            out.append(action)
        return out

    assert asyncio.run(run()) == expected
