"""Client benchmark: the room page and each game in Chrome, measured with CDP.

Per game, one browser player sits at a table with bots (the server is in-process, so the script seats bots and
flips the player's autopilot directly):

  load     cold (empty cache) and warm (reload) load of /r/CODE with the game's iframe: requests that went to the
           network, bytes transferred, time until the game's first state is on screen
  idle     10 s at the table while the bots wait for the player's move: CPU (task time) per second, wakeups
  play     20 s of bots playing at real speed (the player's seat on autopilot): CPU, script/layout/style time,
           frame times (avg/p95/worst), long tasks and total blocking time, DOM nodes, JS heap
  long     (--long N) N seconds of fast bot play: JS heap and DOM nodes after GC, start vs end (leaks)

  uv run python scripts/platform/bench_client.py [--games ttr,karak] [--size 1440x900] [--json tmp/bench/client.json]
"""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import json
import socket
import statistics
import sys
import time
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

import uvicorn
from playwright.async_api import CDPSession, Frame, Page, async_playwright

sys.path.insert(0, str(Path(__file__).parent))
from bench_games import RECIPES, autopilot

from boardgames.games import GAME_KEYS
from boardgames.server import create_app

TOKEN = "bench-player-token-0001"
NETS = {"tunnel": (60, 9, 3), "lan": (2, 100, 100)}  # round-trip ms, Mbit/s down, up

INIT = """
window.__lt = [];
try {
  new PerformanceObserver((l) => { for (const e of l.getEntries()) window.__lt.push(e.duration); })
    .observe({ type: "longtask", buffered: true });
} catch (e) {}
"""

FRAMES_START = """() => {
  window.__frames = []; let last = performance.now(); window.__fon = true;
  const tick = (t) => { window.__frames.push(t - last); last = t; if (window.__fon) requestAnimationFrame(tick); };
  requestAnimationFrame(tick);
}"""
FRAMES_STOP = "() => { window.__fon = false; return window.__frames; }"


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@contextlib.asynccontextmanager
async def serve(delay_scale: float) -> AsyncIterator[tuple[str, Any]]:
    port = _free_port()
    app = create_app(delay_scale=delay_scale)
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning"))
    task = asyncio.create_task(server.serve())
    while not server.started:
        await asyncio.sleep(0.05)
    try:
        yield f"http://127.0.0.1:{port}", app.state.hub
    finally:
        server.should_exit = True
        await task


class Net:
    """Network accounting from CDP: what went over the wire, what came from the cache."""

    def __init__(self, cdp: CDPSession) -> None:
        self.reqs: dict[str, dict[str, Any]] = {}
        cdp.on("Network.requestWillBeSent", self._sent)
        cdp.on("Network.responseReceived", self._resp)
        cdp.on("Network.loadingFinished", self._done)
        cdp.on("Network.requestServedFromCache", self._cache)

    def _sent(self, e: dict[str, Any]) -> None:
        self.reqs[e["requestId"]] = {"url": e["request"]["url"], "bytes": 0, "status": None, "cache": False}

    def _resp(self, e: dict[str, Any]) -> None:
        r = self.reqs.setdefault(e["requestId"], {"url": e["response"]["url"], "bytes": 0, "cache": False})
        r["status"] = e["response"]["status"]
        if e["response"].get("fromDiskCache") or e["response"].get("fromPrefetchCache"):
            r["cache"] = True

    def _cache(self, e: dict[str, Any]) -> None:
        if e["requestId"] in self.reqs:
            self.reqs[e["requestId"]]["cache"] = True

    def _done(self, e: dict[str, Any]) -> None:
        if e["requestId"] in self.reqs:
            self.reqs[e["requestId"]]["bytes"] = e["encodedDataLength"]

    def reset(self) -> None:
        self.reqs.clear()

    def summary(self) -> dict[str, Any]:
        rs = [r for r in self.reqs.values() if not r["url"].startswith("data:")]
        net = [r for r in rs if not r["cache"]]
        return {
            "requests": len(rs),
            "network_requests": len(net),
            "revalidated_304": sum(1 for r in net if r.get("status") == 304),
            "kb": sum(r["bytes"] for r in rs) / 1024,
            "kb_local": sum(r["bytes"] for r in rs if "127.0.0.1" in r["url"]) / 1024,
            "kb_fonts": sum(r["bytes"] for r in rs if "fonts.g" in r["url"]) / 1024,
            "kb_game": sum(r["bytes"] for r in rs if "/g/" in r["url"]) / 1024,
            "kb_shell": sum(
                r["bytes"]
                for r in rs
                if "127.0.0.1" in r["url"] and "/g/" not in r["url"] and "/thumbs/" not in r["url"]
            )
            / 1024,
            "kb_thumbs": sum(r["bytes"] for r in rs if "/thumbs/" in r["url"]) / 1024,
            "game_requests": sum(1 for r in net if "/g/" in r["url"]),
        }


async def metrics(cdp: CDPSession) -> dict[str, float]:
    m = await cdp.send("Performance.getMetrics")
    return {x["name"]: x["value"] for x in m["metrics"]}


def delta(a: dict[str, float], b: dict[str, float], secs: float) -> dict[str, float]:
    d = {k: b[k] - a[k] for k in ("TaskDuration", "ScriptDuration", "LayoutDuration", "RecalcStyleDuration")}
    return {
        "cpu_ms_per_s": d["TaskDuration"] * 1e3 / secs,
        "script_ms_per_s": d["ScriptDuration"] * 1e3 / secs,
        "layout_ms_per_s": d["LayoutDuration"] * 1e3 / secs,
        "style_ms_per_s": d["RecalcStyleDuration"] * 1e3 / secs,
        "layouts_per_s": (b["LayoutCount"] - a["LayoutCount"]) / secs,
        "styles_per_s": (b["RecalcStyleCount"] - a["RecalcStyleCount"]) / secs,
        "nodes": b["Nodes"],
        "heap_mb": b["JSHeapUsedSize"] / 2**20,
        "listeners": b["JSEventListeners"],
    }


def game_frame(page: Page) -> Frame | None:
    for f in page.frames:
        if "/g/" in f.url:
            return f
    return None


async def wait_game(page: Page, timeout: float = 15.0) -> Frame:
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        f = game_frame(page)
        if f is not None:
            with contextlib.suppress(Exception):
                if await f.evaluate("document.readyState") == "complete":
                    return f
        await asyncio.sleep(0.05)
    raise RuntimeError("game frame did not load")


async def table_member(room: Any, timeout: float = 10.0) -> str:
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        for m in room.members.values():
            if m.token == TOKEN and (getattr(m, "connections", 0) or getattr(m, "conns", None)):
                return m.id
        await asyncio.sleep(0.05)
    raise RuntimeError("the browser never joined the table")


async def bench_game(pw: Any, base: str, hub: Any, key: str, size: tuple[int, int], args: Any) -> dict[str, Any]:
    browser = await pw.chromium.launch(args=["--disable-renderer-backgrounding"])
    ctx = await browser.new_context(viewport={"width": size[0], "height": size[1]})
    await ctx.add_init_script(f"localStorage.setItem('bg.token', '{TOKEN}'); localStorage.setItem('bg.name', 'Ann');")
    await ctx.add_init_script(INIT)
    page = await ctx.new_page()
    errors: list[str] = []
    page.on("pageerror", lambda e: errors.append(str(e)))
    cdp = await ctx.new_cdp_session(page)
    await cdp.send("Network.enable")
    await cdp.send("Performance.enable")
    net = Net(cdp)
    out: dict[str, Any] = {"game": key}
    if args.net:
        latency, down, up = NETS[args.net]
        await cdp.send(
            "Network.emulateNetworkConditions",
            {
                "offline": False,
                "latency": latency,
                "downloadThroughput": down * 125_000,
                "uploadThroughput": up * 125_000,
            },
        )

    # ---- cold load: the room page, then the leader launches the game (as after a vote)
    party = hub.create()
    t0 = time.perf_counter()
    await page.goto(f"{base}/r/{party.id}", wait_until="load")
    while not party.online():
        await asyncio.sleep(0.02)
    out["room_load_ms"] = (time.perf_counter() - t0) * 1e3
    t1 = time.perf_counter()
    party.start_game(key)
    party._emit()
    frame = await wait_game(page)
    room = party.room
    mid = await table_member(room)
    out["game_load_ms"] = (time.perf_counter() - t1) * 1e3
    await asyncio.sleep(1.0)
    out["cold"] = net.summary()

    # ---- warm load: reload the whole page (same browser cache)
    net.reset()
    t0 = time.perf_counter()
    await page.reload(wait_until="load")
    frame = await wait_game(page)
    out["warm_load_ms"] = (time.perf_counter() - t0) * 1e3
    await asyncio.sleep(1.0)
    out["warm"] = net.summary()

    if args.load_only:
        out["errors"] = errors
        await browser.close()
        hub.drop(party.id)
        return out

    # ---- lobby idle
    await asyncio.sleep(1.0)
    a = await metrics(cdp)
    await asyncio.sleep(args.idle)
    out["lobby_idle"] = delta(a, await metrics(cdp), args.idle)

    recipe = RECIPES.get(key)
    if recipe is not None:
        recipe.setup(room, [])  # bots fill the seats; the player keeps their own seat
        # ---- idle at the table: bots play up to the player's turn, then everyone waits for them
        await asyncio.sleep(args.settle)
        a = await metrics(cdp)
        seq = getattr(room, "seq", 0)
        await asyncio.sleep(args.idle)
        out["table_idle"] = delta(a, await metrics(cdp), args.idle)
        out["table_idle"]["events"] = getattr(room, "seq", 0) - seq

        # ---- play: the autopilot takes the player's seat, bots and animations at real speed
        autopilot(room, [mid])
        frame = game_frame(page) or frame
        with contextlib.suppress(Exception):
            await frame.evaluate("window.__lt = []")
        await frame.evaluate(FRAMES_START)
        a = await metrics(cdp)
        seq = getattr(room, "seq", 0)
        t0 = time.perf_counter()
        while time.perf_counter() - t0 < args.play:
            await asyncio.sleep(0.25)
            recipe.nudge(room, [mid])
        secs = time.perf_counter() - t0
        b = await metrics(cdp)
        frames = sorted((await frame.evaluate(FRAMES_STOP))[1:])
        lts = await frame.evaluate("window.__lt")
        play = delta(a, b, secs)
        play["events"] = getattr(room, "seq", 0) - seq
        if frames:
            play["frame_avg_ms"] = statistics.mean(frames)
            play["frame_p95_ms"] = frames[int(len(frames) * 0.95)]
            play["frame_max_ms"] = frames[-1]
            play["frames_over_33ms"] = sum(1 for f in frames if f > 33.4)
        play["long_tasks"] = len(lts)
        play["tbt_ms"] = sum(max(0.0, d - 50) for d in lts)
        play["longest_task_ms"] = max(lts) if lts else 0.0
        out["play"] = play

        if args.long:
            room.delay_scale = 0.15
            await cdp.send("HeapProfiler.collectGarbage")
            a = await metrics(cdp)
            t0 = time.perf_counter()
            while time.perf_counter() - t0 < args.long:
                await asyncio.sleep(0.25)
                recipe.nudge(room, [mid])
                if room.status in ("game_over", "over"):
                    room.handle(room.host_id, {"type": "play_again"})
                    autopilot(room, [mid])
            await cdp.send("HeapProfiler.collectGarbage")
            await asyncio.sleep(0.5)
            b = await metrics(cdp)
            out["long"] = {
                "secs": time.perf_counter() - t0,
                "heap_mb_start": a["JSHeapUsedSize"] / 2**20,
                "heap_mb_end": b["JSHeapUsedSize"] / 2**20,
                "nodes_start": a["Nodes"],
                "nodes_end": b["Nodes"],
                "listeners_start": a["JSEventListeners"],
                "listeners_end": b["JSEventListeners"],
                "documents_end": b["Documents"],
            }

    # ---- back to game selection: what stays behind once the game's iframe is gone
    party.handle(party.leader_id, {"type": "back_force"})
    await asyncio.sleep(1.5)
    await cdp.send("HeapProfiler.collectGarbage")
    await asyncio.sleep(0.5)
    m = await metrics(cdp)
    out["after_back"] = {
        "nodes": m["Nodes"],
        "heap_mb": m["JSHeapUsedSize"] / 2**20,
        "documents": m["Documents"],
        "frames": m["Frames"],
        "listeners": m["JSEventListeners"],
    }
    a = await metrics(cdp)
    await asyncio.sleep(args.idle / 2)
    out["select_idle"] = delta(a, await metrics(cdp), args.idle / 2)
    out["errors"] = errors
    await browser.close()
    hub.drop(party.id)
    return out


def line(r: dict[str, Any]) -> str:
    c, w = r["cold"], r["warm"]
    ti, pl, li = r.get("table_idle", {}), r.get("play", {}), r.get("lobby_idle", {"cpu_ms_per_s": 0, "nodes": 0})
    if "kb_game" in c:
        return (
            f"{r['game']:<10} cold game {c['game_requests']:>3}req {c['kb_game']:>5.0f}kB shell {c['kb_shell']:>4.0f}kB"
            f" thumbs {c['kb_thumbs']:>4.0f}kB fonts {c['kb_fonts']:>4.0f}kB {r['room_load_ms'] + r['game_load_ms']:>5.0f}ms"
            f" | warm {w['network_requests']:>3}req ({w['revalidated_304']:>2}×304) {w['kb_local']:>5.0f}kB {r['warm_load_ms']:>5.0f}ms"
            + (
                f" | idle lobby {li['cpu_ms_per_s']:>5.1f} table {ti.get('cpu_ms_per_s', 0):>5.1f} ms/s | play {pl.get('cpu_ms_per_s', 0):>4.0f}ms/s"
                f" fr {pl.get('frame_avg_ms', 0):>4.1f}/{pl.get('frame_p95_ms', 0):>4.1f}/{pl.get('frame_max_ms', 0):>4.0f} nodes {pl.get('nodes', li['nodes']):>5.0f}"
                if "lobby_idle" in r
                else ""
            )
            + f" | errs {len(r['errors'])}"
        )
    return (
        f"{r['game']:<10} cold {c['network_requests']:>3}req {c['kb_local']:>6.0f}kB {r['room_load_ms'] + r['game_load_ms']:>5.0f}ms"
        f" | warm {w['network_requests']:>3}req ({w['revalidated_304']:>2}×304) {w['kb_local']:>5.0f}kB {r['warm_load_ms']:>5.0f}ms"
        f" | idle lobby {li['cpu_ms_per_s']:>5.1f} table {ti.get('cpu_ms_per_s', 0):>5.1f} ms/s"
        f" | play {pl.get('cpu_ms_per_s', 0):>5.0f}ms/s fr {pl.get('frame_avg_ms', 0):>4.1f}/{pl.get('frame_p95_ms', 0):>4.1f}/{pl.get('frame_max_ms', 0):>5.0f}"
        f" tbt {pl.get('tbt_ms', 0):>4.0f} nodes {pl.get('nodes', li['nodes']):>5.0f} heap {pl.get('heap_mb', 0):>4.1f}"
        f" | errs {len(r['errors'])}"
    )


async def run(args: Any) -> list[dict[str, Any]]:
    size = tuple(int(v) for v in args.size.split("x"))
    results = []
    async with serve(args.delay_scale) as (base, hub), async_playwright() as pw:
        for key in args.games.split(","):
            r = await bench_game(pw, base, hub, key, size, args)  # type: ignore[arg-type]
            results.append(r)
            print(line(r), flush=True)
    return results


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--games", default=",".join(GAME_KEYS))
    ap.add_argument("--size", default="1440x900")
    ap.add_argument("--idle", type=float, default=8.0)
    ap.add_argument("--settle", type=float, default=8.0)
    ap.add_argument("--play", type=float, default=20.0)
    ap.add_argument("--long", type=float, default=0.0)
    ap.add_argument("--delay-scale", type=float, default=1.0)
    ap.add_argument("--json", type=Path, default=None)
    ap.add_argument("--net", choices=sorted(NETS), default=None, help="emulate a network (load times)")
    ap.add_argument("--load-only", action="store_true")
    args = ap.parse_args()
    results = asyncio.run(run(args))
    if args.json:
        args.json.parent.mkdir(parents=True, exist_ok=True)
        args.json.write_text(json.dumps(results, indent=1))


if __name__ == "__main__":
    main()
