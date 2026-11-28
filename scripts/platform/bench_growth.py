"""Which parts of a game's page grow over a long fast session (leak hunting): live DOM nodes per top-level
container of the game's frame, sampled every few seconds while bots play several games back to back.

  uv run python scripts/platform/bench_growth.py --game toybattle --secs 90
"""

from __future__ import annotations

import argparse
import asyncio
import sys
import time
from pathlib import Path

from playwright.async_api import async_playwright

sys.path.insert(0, str(Path(__file__).parent))
from bench_client import TOKEN, serve, table_member, wait_game
from bench_games import RECIPES, autopilot

COUNT = """() => {
  const out = { total: document.getElementsByTagName('*').length, detachedHint: 0 };
  const walk = (el, depth) => {
    for (const c of el.children) {
      const n = c.getElementsByTagName('*').length + 1;
      if (n > 150) {
        const key = c.tagName.toLowerCase() + (c.id ? '#' + c.id : '') + (c.classList.length ? '.' + [...c.classList].slice(0, 2).join('.') : '');
        out[key] = (out[key] || 0) + n;
        if (depth < 3) walk(c, depth + 1);
      }
    }
  };
  walk(document.body, 0);
  return out;
}"""


async def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--game", required=True)
    ap.add_argument("--secs", type=float, default=90)
    ap.add_argument("--every", type=float, default=15)
    ap.add_argument("--delay-scale", type=float, default=0.15)
    args = ap.parse_args()
    async with serve(args.delay_scale) as (base, hub), async_playwright() as pw:
        browser = await pw.chromium.launch()
        ctx = await browser.new_context(viewport={"width": 1440, "height": 900})
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
        recipe = RECIPES[args.game]
        recipe.setup(room, [mid])
        t0 = time.monotonic()
        games = 1
        samples = []
        next_at = 0.0
        while time.monotonic() - t0 < args.secs:
            await asyncio.sleep(0.25)
            recipe.nudge(room, [mid])
            if room.status in ("game_over", "over"):
                room.handle(room.host_id, {"type": "play_again"})
                autopilot(room, [mid])
                games += 1
            if time.monotonic() - t0 >= next_at:
                next_at += args.every
                samples.append((round(time.monotonic() - t0), games, room.status, await frame.evaluate(COUNT)))
        await browser.close()
    keys = sorted({k for *_, c in samples for k in c if k != "detachedHint"}, key=lambda k: -samples[-1][3].get(k, 0))
    for k in keys[:12]:
        print(f"{k[:44]:<44} " + " ".join(f"{c.get(k, 0):>6}" for *_, c in samples))
    print(f"{'(seconds / game no / status)':<44} " + " ".join(f"{t:>4}s{g:>1}" for t, g, *_ in samples))


if __name__ == "__main__":
    asyncio.run(main())
