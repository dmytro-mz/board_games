"""Server benchmark: every bot game played headless through its real room and driver, with instrumented listeners.

For each game: a table with H seated humans (on autopilot, so their own per-seat view is built and sent) plus bots,
played to the end with delay_scale=0. Measures per game:

  events, messages, snapshot build time (state_for), encode time, bytes raw / on the wire (permessage-deflate as
  uvicorn negotiates it: 12-bit window, memLevel 5, context takeover), the longest synchronous event-loop callback
  (what stalls every other room), and CPU split between bot threads and the loop.

  uv run python scripts/platform/bench_server.py                 # all games, table in the terminal
  uv run python scripts/platform/bench_server.py --games ttr,karak --humans 2 --json tmp/bench/server.json

The wire codec is whatever `boardgames.net.encode` does (so before/after compare the real thing).
"""

from __future__ import annotations

import argparse
import asyncio
import asyncio.events
import json
import statistics
import sys
import threading
import time
import zlib
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).parent))
import contextlib

from bench_games import RECIPES, Recipe, finished

from boardgames import net
from boardgames.games import load_games

# ---------------------------------------------------------------------------------------------- loop instrumentation
_callback_times: list[float] = []
_orig_run = asyncio.events.Handle._run


_slowest: list[tuple[float, str]] = []


def _timed_run(self: asyncio.events.Handle) -> None:
    t0 = time.perf_counter()
    _orig_run(self)
    dt = time.perf_counter() - t0
    _callback_times.append(dt)
    if dt > 0.02:
        _slowest.append((dt, repr(self)[:160]))


asyncio.events.Handle._run = _timed_run  # type: ignore[method-assign]


class Wire:
    """What one websocket would carry: the encoded frames, deflated with context takeover like the browser link."""

    deflate_s = 0.0

    def __init__(self) -> None:
        self.z = zlib.compressobj(6, zlib.DEFLATED, -12, 5)
        self.raw = 0
        self.wire = 0
        self.frames = 0

    def add(self, data: bytes | str) -> None:
        b = data.encode() if isinstance(data, str) else data
        self.raw += len(b)
        t0 = time.perf_counter()
        out = self.z.compress(b) + self.z.flush(zlib.Z_SYNC_FLUSH)
        Wire.deflate_s += time.perf_counter() - t0
        self.wire += len(out) - 4 + 2 + (2 if len(out) > 125 else 0)  # deflate tail dropped; frame header
        self.frames += 1


class Probe:
    """A listener that does what `net.Connection` does with each message: encode it and put it on the wire."""

    def __init__(self, member_id: str, stats: dict[str, Any]) -> None:
        self.member_id = member_id
        self.wire = Wire()
        self.stats = stats

    def send(self, message: Any) -> None:
        t0 = time.perf_counter()
        data = ENCODE(self, message)
        self.stats["encode"] += time.perf_counter() - t0
        if data is not None:
            self.wire.add(data)
            self.stats["sizes"].append(len(data))


def _baseline_encode(conn: Any, message: Any) -> str:
    return json.dumps(message, separators=(",", ":"), ensure_ascii=False)  # what starlette's send_json does


ENCODE = getattr(net, "encode_for", _baseline_encode)


def _wrap_state_for(room: Any, stats: dict[str, Any]) -> None:
    for name in ("state_for", "snapshot"):
        fn = getattr(room, name, None)
        if fn is None:
            continue

        def timed(*a: Any, _fn: Any = fn, **k: Any) -> Any:
            t0 = time.perf_counter()
            out = _fn(*a, **k)
            stats["build"] += time.perf_counter() - t0
            stats["builds"] += 1
            return out

        setattr(room, name, timed)


def _thread_cpu() -> float:
    return time.thread_time()


async def play(key: str, recipe: Recipe, humans: int, seed: int, timeout: float) -> dict[str, Any]:
    spec = load_games((key,))[key]
    backend = spec.backend(delay_scale=0.0, **recipe.options)
    room = backend.new_room(f"B{seed:04d}")
    if hasattr(room, "rng"):
        import random

        room.rng = random.Random(seed)
    stats: dict[str, Any] = {"build": 0.0, "builds": 0, "encode": 0.0, "sizes": []}
    _wrap_state_for(room, stats)
    members = [room.join(f"token-{key}-{i:02d}-xxxxxxxx", f"P{i}") for i in range(humans)]
    probes = [Probe(m.id, stats) for m in members]
    for p in probes:
        room.connect(p)
    recipe.setup(room, [m.id for m in members])
    for p in probes:  # fresh counters: measure the game, not the lobby
        p.wire = Wire()
    stats.update(build=0.0, builds=0, encode=0.0, sizes=[])
    events0 = getattr(room, "seq", 0)
    await asyncio.sleep(0)  # end this setup step (backend construction is server startup, not play) before measuring
    _callback_times.clear()
    Wire.deflate_s = 0.0
    loop_cpu0, wall0, proc0 = _thread_cpu(), time.perf_counter(), time.process_time()
    task = asyncio.create_task(room.drive())
    deadline = time.monotonic() + timeout
    while not finished(room) and time.monotonic() < deadline:
        await asyncio.sleep(0.02)
        recipe.nudge(room, [m.id for m in members])
    done = finished(room)
    wall, proc, loop_cpu = time.perf_counter() - wall0, time.process_time() - proc0, _thread_cpu() - loop_cpu0
    room.close()
    task.cancel()
    with contextlib.suppress(asyncio.CancelledError, Exception):
        await task
    cbs = sorted(_callback_times)
    sizes = stats["sizes"]
    raw = sum(p.wire.raw for p in probes)
    wire = sum(p.wire.wire for p in probes)
    msgs = sum(p.wire.frames for p in probes)
    return {
        "game": key,
        "humans": humans,
        "done": done,
        "events": getattr(room, "seq", 0) - events0,
        "messages": msgs,
        "builds": stats["builds"],
        "build_ms_total": stats["build"] * 1e3,
        "build_us_avg": stats["build"] / max(1, stats["builds"]) * 1e6,
        "encode_ms_total": stats["encode"] * 1e3,
        "deflate_ms_total": Wire.deflate_s * 1e3,
        "msg_kb_avg": statistics.mean(sizes) / 1024 if sizes else 0,
        "msg_kb_max": max(sizes) / 1024 if sizes else 0,
        "raw_kb_per_player": raw / 1024 / max(1, len(probes)),
        "wire_kb_per_player": wire / 1024 / max(1, len(probes)),
        "loop_cpu_ms": loop_cpu * 1e3,
        "bot_thread_cpu_ms": max(0.0, proc - loop_cpu) * 1e3,
        "wall_s": wall,
        "cb_max_ms": cbs[-1] * 1e3 if cbs else 0,
        "cb_p99_ms": cbs[int(len(cbs) * 0.99)] * 1e3 if cbs else 0,
        "cb_over_20ms": sum(1 for c in cbs if c > 0.02),
    }


COLS = [
    ("game", "{:<10}"),
    ("done", "{!s:<5}"),
    ("events", "{:>6}"),
    ("messages", "{:>6}"),
    ("build_us_avg", "{:>8.0f}"),
    ("build_ms_total", "{:>8.0f}"),
    ("encode_ms_total", "{:>8.0f}"),
    ("deflate_ms_total", "{:>8.0f}"),
    ("msg_kb_avg", "{:>7.1f}"),
    ("msg_kb_max", "{:>7.1f}"),
    ("raw_kb_per_player", "{:>8.0f}"),
    ("wire_kb_per_player", "{:>8.0f}"),
    ("loop_cpu_ms", "{:>8.0f}"),
    ("bot_thread_cpu_ms", "{:>8.0f}"),
    ("cb_max_ms", "{:>8.1f}"),
    ("cb_over_20ms", "{:>5}"),
]
HEAD = "game       done  events  msgs  build_us build_ms  enc_ms  defl_ms kb_avg  kb_max  raw_kb/p wire_kb/p loop_ms  bot_ms   cbmax  >20ms"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--games", default=",".join(RECIPES))
    ap.add_argument("--humans", type=int, default=2)
    ap.add_argument("--seeds", type=int, default=1)
    ap.add_argument("--timeout", type=float, default=240)
    ap.add_argument("--json", type=Path, default=None)
    ap.add_argument("--slow", action="store_true", help="name the slowest event-loop callbacks")
    args = ap.parse_args()
    threading.current_thread().name = "loop"
    results = []
    print(HEAD)
    for key in args.games.split(","):
        recipe = RECIPES[key]
        for seed in range(args.seeds):
            r = asyncio.run(play(key, recipe, min(args.humans, recipe.max_humans), seed + 1, args.timeout))
            results.append(r)
            print(" ".join(fmt.format(r[c]) for c, fmt in COLS), flush=True)
            if args.slow:
                for dt, what in sorted(_slowest, reverse=True)[:5]:
                    print(f"    {dt * 1e3:6.1f} ms  {what}")
            _slowest.clear()
    if args.json:
        args.json.parent.mkdir(parents=True, exist_ok=True)
        args.json.write_text(json.dumps(results, indent=1))


if __name__ == "__main__":
    main()
