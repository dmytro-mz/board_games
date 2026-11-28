"""Where a game's client spends its time while the table waits for the player (or while bots play): a Chrome
trace of N seconds, summarised by trace event (timers, animation frames, style, layout, paint...) and by the
CSS animations that were running.

  uv run python scripts/platform/bench_trace.py --game karak [--phase idle|play] [--secs 5]
"""

from __future__ import annotations

import argparse
import asyncio
import collections
import json
import sys
from pathlib import Path
from typing import Any

from playwright.async_api import async_playwright

sys.path.insert(0, str(Path(__file__).parent))
from bench_client import TOKEN, serve, table_member, wait_game
from bench_games import RECIPES, autopilot

ANIMS = """() => document.getAnimations().map(a => {
  const t = a.effect && a.effect.target; const kf = a.effect && a.effect.getKeyframes ? a.effect.getKeyframes() : [];
  const props = [...new Set(kf.flatMap(k => Object.keys(k).filter(p => !['offset','easing','composite','computedOffset'].includes(p))))];
  return { name: a.animationName || a.constructor.name, target: t ? (t.tagName + '.' + (t.getAttribute('class') || '').split(' ').join('.')) : '', props, state: a.playState };
})"""


async def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--game", required=True)
    ap.add_argument("--phase", default="idle")
    ap.add_argument("--secs", type=float, default=5)
    ap.add_argument("--settle", type=float, default=8)
    ap.add_argument("--size", default="1440x900")
    ap.add_argument("--out", type=Path, default=Path("tmp/bench/trace.json"))
    ap.add_argument("--css", default="", help="CSS injected into the game before tracing (experiments)")
    ap.add_argument("--shot", type=Path, default=None, help="screenshot before tracing")
    ap.add_argument("--seed", type=int, default=None)
    ap.add_argument("--ab-js", default="", help="A/B: CPU as is vs after evaluating this JS in the game frame")
    args = ap.parse_args()
    w, h = (int(v) for v in args.size.split("x"))
    async with serve(1.0) as (base, hub), async_playwright() as pw:
        browser = await pw.chromium.launch()
        ctx = await browser.new_context(viewport={"width": w, "height": h})
        await ctx.add_init_script(
            f"localStorage.setItem('bg.token', '{TOKEN}'); localStorage.setItem('bg.name', 'Ann');"
        )
        page = await ctx.new_page()
        party = hub.create()
        await page.goto(f"{base}/r/{party.id}")
        while not party.online():
            await asyncio.sleep(0.05)
        party.start_game(args.game)
        party._emit()
        frame = await wait_game(page)
        room = party.room
        mid = await table_member(room)
        recipe = RECIPES.get(args.game)
        if args.phase != "lobby" and recipe is not None:
            recipe.setup(room, [])
            await asyncio.sleep(args.settle)
            if args.phase == "play":
                autopilot(room, [mid])
        else:
            await asyncio.sleep(1)
        if args.css:
            await frame.add_style_tag(content=args.css)
            await asyncio.sleep(0.5)
        if args.shot:
            await page.screenshot(path=args.shot)
        anims = await frame.evaluate(ANIMS)
        if args.ab_js:  # A/B in the same state: trace as is, then again with the injected script running
            cdp0 = await ctx.new_cdp_session(page)
            await cdp0.send("Performance.enable")
            m0 = {x["name"]: x["value"] for x in (await cdp0.send("Performance.getMetrics"))["metrics"]}
            await asyncio.sleep(args.secs)
            m1 = {x["name"]: x["value"] for x in (await cdp0.send("Performance.getMetrics"))["metrics"]}
            await frame.evaluate(args.ab_js)
            await asyncio.sleep(0.5)
            m2 = {x["name"]: x["value"] for x in (await cdp0.send("Performance.getMetrics"))["metrics"]}
            await asyncio.sleep(args.secs)
            m3 = {x["name"]: x["value"] for x in (await cdp0.send("Performance.getMetrics"))["metrics"]}
            a = (m1["TaskDuration"] - m0["TaskDuration"]) * 1e3 / args.secs
            b = (m3["TaskDuration"] - m2["TaskDuration"]) * 1e3 / args.secs
            print(f"A/B {args.game}: as is {a:.1f} ms CPU/s · with the injected script {b:.1f} ms CPU/s")
        cdp = await ctx.new_cdp_session(page)
        events: list[dict[str, Any]] = []
        done = asyncio.Event()
        cdp.on("Tracing.dataCollected", lambda e: events.extend(e["value"]))
        cdp.on("Tracing.tracingComplete", lambda e: done.set())
        await cdp.send(
            "Tracing.start",
            {"categories": "devtools.timeline,disabled-by-default-devtools.timeline", "transferMode": "ReportEvents"},
        )
        await asyncio.sleep(args.secs)
        await cdp.send("Tracing.end")
        await done.wait()
        await browser.close()
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps({"traceEvents": events}))
    main_tids = {
        (e["pid"], e["tid"])
        for e in events
        if e.get("name") == "thread_name" and e["args"].get("name") == "CrRendererMain"
    }
    total: collections.Counter[str] = collections.Counter()
    count: collections.Counter[str] = collections.Counter()
    for e in events:
        if (e.get("pid"), e.get("tid")) in main_tids and e.get("ph") == "X" and "dur" in e:
            total[e["name"]] += e["dur"] / 1000
            count[e["name"]] += 1
    print(f"{args.game} {args.phase}: main-thread trace events over {args.secs:.0f}s (ms total, count)")
    for name, ms in total.most_common(14):
        print(f"  {name:<28} {ms:8.1f} ms  {count[name]:6d}")
    print("running animations:")
    seen = collections.Counter(
        (a["name"], a["target"][:60], ",".join(a["props"])) for a in anims if a["state"] == "running"
    )
    for (name, target, props), n in seen.most_common(20):
        print(f"  {n:3d}× {name:<18} {props:<30} {target}")


if __name__ == "__main__":
    asyncio.run(main())
