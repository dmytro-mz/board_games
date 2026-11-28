"""Load benchmark: a real server (subprocess) with many rooms of bot games at real speed, each watched by websocket
clients that behave like players: a party socket and a table socket each, and a chat line every few seconds whose
echo gives the round trip. Measures message latency (p50/p95/p99), server CPU and RSS, messages and bytes.

  uv run python scripts/platform/bench_load.py --rooms 1,10,40 --clients 4 --secs 30 [--games ttr,karak]
"""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import json
import os
import random
import socket
import statistics
import subprocess
import sys
import time
import urllib.request
from pathlib import Path
from typing import Any

import websockets

sys.path.insert(0, str(Path(__file__).parent))
from bench_games import RECIPES

SERVER = """
import sys, uvicorn
from boardgames.server import create_app
uvicorn.run(create_app(delay_scale=float(sys.argv[2])), host="127.0.0.1", port=int(sys.argv[1]), log_level="warning")
"""


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def ps(pid: int) -> tuple[float, float]:
    """(cpu seconds, memory MB) of a process and its children (`uv run` starts the server as a child)."""
    pids, todo = [], [pid]
    while todo:  # the whole tree: the server, and its bot worker processes (children of a forkserver)
        p = todo.pop()
        pids.append(p)
        with contextlib.suppress(subprocess.CalledProcessError):
            todo += [int(c) for c in subprocess.check_output(["pgrep", "-P", str(p)], text=True).split()]
    cpu = mem = 0.0
    for p in pids:
        with contextlib.suppress(Exception):
            c, m = _ps1(p)
            cpu += c
            if not (p == pid and len(pids) > 1 and _is_uv(p)):
                mem += m
    return cpu, mem


def _is_uv(pid: int) -> bool:
    return "uv" in subprocess.check_output(["ps", "-o", "comm=", "-p", str(pid)], text=True).rsplit("/", 1)[-1]


def _ps1(pid: int) -> tuple[float, float]:
    """(cpu seconds, memory MB) of a process. Memory is the physical footprint where macOS reports it (RSS there
    shrinks when pages get compressed), else RSS."""
    out = subprocess.check_output(["ps", "-o", "time=,rss=", "-p", str(pid)], text=True).split()
    parts = [float(x) for x in out[0].replace("-", ":").split(":")]
    cpu = 0.0
    for p in parts:
        cpu = cpu * 60 + p
    mem = int(out[1]) / 1024
    if sys.platform == "darwin":
        with contextlib.suppress(Exception):
            fp = subprocess.check_output(["footprint", "-p", str(pid)], text=True, stderr=subprocess.DEVNULL)
            for line in fp.splitlines():
                if "phys_footprint:" in line:
                    num, unit = line.split("phys_footprint:")[1].split()[:2]
                    mem = float(num) * {"KB": 1 / 1024, "MB": 1.0, "GB": 1024.0}[unit]
    return cpu, mem


def _http(url: str, post: bool = False) -> bytes:
    req = urllib.request.Request(url, method="POST" if post else "GET")
    with urllib.request.urlopen(req, timeout=2) as r:
        return r.read()


class Stats:
    def __init__(self) -> None:
        self.rtts: list[float] = []
        self.msgs = 0
        self.bytes = 0
        self.errors = 0


async def client(base: str, code: str, key: str, i: int, host: bool, stats: Stats, stop: asyncio.Event) -> None:
    token = f"load-{code}-{i:02d}-" + "x" * 12
    ws_base = base.replace("http", "ws")
    hello = json.dumps({"type": "hello", "token": token, "name": f"P{i}"})
    async with websockets.connect(f"{ws_base}/ws/{code}", max_size=None) as party:
        await party.send(hello)
        async with websockets.connect(f"{ws_base}/g/{key}/ws/{code}", max_size=None) as table:
            await table.send(hello)
            pending: dict[str, float] = {}
            me: list[str] = []

            async def read(sock: Any) -> None:
                async for raw in sock:
                    stats.msgs += 1
                    stats.bytes += len(raw)
                    msg = json.loads(raw)
                    if msg.get("type") in ("error", "fatal") and stats.errors < 5:
                        print("   server says:", msg.get("message"), file=sys.stderr)
                    if msg.get("type") in ("error", "fatal"):
                        stats.errors += 1
                    if msg.get("type") == "welcome" and sock is table:
                        me.append(msg["you"])
                    if msg.get("type") == "log":
                        text = msg["entry"].get("text", "")
                        if text in pending:
                            stats.rtts.append(time.perf_counter() - pending.pop(text))

            readers = [asyncio.create_task(read(party)), asyncio.create_task(read(table))]
            await asyncio.sleep(1.0)
            if host:
                recipe = RECIPES[key]
                for _ in range(8):  # everyone who sat down on joining watches instead: the seats go to bots
                    await table.send(json.dumps({"type": "remove_seat", "seat": 0}))
                for _ in range(recipe.seats):
                    await table.send(json.dumps({"type": "add_bot", "bot": recipe.bot}))
                await table.send(json.dumps({"type": "start"}))
            n = 0
            await asyncio.sleep(random.random() * 3)
            while not stop.is_set():
                n += 1
                text = f"ping {i} {n}"
                pending[text] = time.perf_counter()
                await table.send(json.dumps({"type": "chat", "text": text}))
                with contextlib.suppress(TimeoutError):
                    await asyncio.wait_for(stop.wait(), 3.0)
            for r in readers:
                r.cancel()


async def run_level(base: str, pid: int, rooms: int, clients: int, secs: float, games: list[str]) -> dict[str, Any]:
    stats = Stats()
    stop = asyncio.Event()
    tasks = []
    codes = [json.loads(_http(base + "/api/rooms", post=True))["room"] for _ in range(rooms)]
    for r, code in enumerate(codes):
        key = games[r % len(games)]
        # the leader opens the game the way the room page does after a vote
        async with websockets.connect(base.replace("http", "ws") + f"/ws/{code}") as leader:
            await leader.send(json.dumps({"type": "hello", "token": f"load-{code}-00-" + "x" * 12, "name": "P0"}))
            await leader.send(json.dumps({"type": "vote", "game": key}))
            await leader.send(json.dumps({"type": "launch", "game": key}))
            while json.loads(await leader.recv()).get("phase") != "game":
                pass
        for i in range(clients):
            tasks.append(asyncio.create_task(client(base, code, key, i, i == 0, stats, stop)))
    await asyncio.sleep(3.0)  # everyone connected, games started
    cpu0, rss0 = ps(pid)
    stats.rtts.clear()
    msgs0, bytes0 = stats.msgs, stats.bytes
    t0 = time.perf_counter()
    await asyncio.sleep(secs)
    wall = time.perf_counter() - t0
    cpu1, rss1 = ps(pid)
    stop.set()
    for out in await asyncio.gather(*tasks, return_exceptions=True):
        if isinstance(out, BaseException):
            stats.errors += 1
            print("   client failed:", repr(out)[:200], file=sys.stderr)
    rtts = sorted(stats.rtts)
    q = lambda p: rtts[min(len(rtts) - 1, int(len(rtts) * p))] * 1e3 if rtts else 0.0  # noqa: E731
    return {
        "rooms": rooms,
        "clients": rooms * clients,
        "cpu_pct": (cpu1 - cpu0) / wall * 100,
        "rss_mb": rss1,
        "rss_start_mb": rss0,
        "rtt_p50_ms": q(0.5),
        "rtt_p95_ms": q(0.95),
        "rtt_p99_ms": q(0.99),
        "rtt_max_ms": rtts[-1] * 1e3 if rtts else 0.0,
        "pings": len(rtts),
        "msgs_per_s": (stats.msgs - msgs0) / wall,
        "kb_per_s": (stats.bytes - bytes0) / wall / 1024,
        "mean_rtt_ms": statistics.mean(rtts) * 1e3 if rtts else 0.0,
    }


async def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--rooms", default="1,10,40")
    ap.add_argument("--clients", type=int, default=4)
    ap.add_argument("--secs", type=float, default=30)
    ap.add_argument("--games", default="ttr,pandemic,karak,skyjo,phase10,lostcities,toybattle,sumo,avenue")
    ap.add_argument("--delay-scale", type=float, default=1.0)
    ap.add_argument("--json", type=Path, default=None)
    ap.add_argument("--project", type=Path, default=None, help="serve from another checkout (e.g. the baseline)")
    args = ap.parse_args()
    results = []
    print("rooms clients  cpu%   rss_MB  rtt p50   p95    p99    max   msgs/s   kB/s")
    for rooms in (int(x) for x in args.rooms.split(",")):
        port = free_port()
        cmd = (
            [sys.executable] if args.project is None else ["uv", "run", "-q", "--project", str(args.project), "python"]
        )
        proc = subprocess.Popen([*cmd, "-c", SERVER, str(port), str(args.delay_scale)], env=os.environ.copy())
        base = f"http://127.0.0.1:{port}"
        for _ in range(100):
            with contextlib.suppress(Exception):
                _http(base + "/api/config")
                break
            await asyncio.sleep(0.1)
        idle_cpu0, idle_rss = ps(proc.pid)
        await asyncio.sleep(5)
        idle_cpu1, _ = ps(proc.pid)
        try:
            r = await run_level(base, proc.pid, rooms, args.clients, args.secs, args.games.split(","))
        finally:
            proc.terminate()
            proc.wait()
        r["idle_cpu_pct"] = (idle_cpu1 - idle_cpu0) / 5 * 100
        r["idle_rss_mb"] = idle_rss
        results.append(r)
        print(
            f"{r['rooms']:>5} {r['clients']:>7} {r['cpu_pct']:>5.1f} {r['rss_mb']:>8.1f} {r['rtt_p50_ms']:>7.1f} "
            f"{r['rtt_p95_ms']:>6.1f} {r['rtt_p99_ms']:>6.1f} {r['rtt_max_ms']:>6.0f} {r['msgs_per_s']:>8.0f} "
            f"{r['kb_per_s']:>6.0f}   (idle server: {r['idle_rss_mb']:.1f} MB, {r['idle_cpu_pct']:.2f}% cpu)",
            flush=True,
        )
    if args.json:
        args.json.parent.mkdir(parents=True, exist_ok=True)
        args.json.write_text(json.dumps(results, indent=1))


if __name__ == "__main__":
    asyncio.run(main())
