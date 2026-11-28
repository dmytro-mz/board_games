"""Film a placement and the bot's answer frame by frame (animations on) into shots/toybattle/anim/.

uv run python scripts/toybattle/anim_frames.py [--terrain rug] [--size 1280x800]
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

from playwright.async_api import async_playwright

sys.path.insert(0, str(Path(__file__).parent))
from demo import prepare, serving

from boardgames.testing import game_app

CHROME = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"


async def run(args: argparse.Namespace) -> None:
    room = prepare("play", args.turns, args.seed, args.terrain)
    room.delay_scale = 1.0
    out = Path("shots/toybattle/anim")
    out.mkdir(parents=True, exist_ok=True)
    for old in out.glob("*.png"):
        old.unlink()
    async with serving(game_app("toybattle"), room, args.port) as url, async_playwright() as pw:
        browser = await pw.chromium.launch(executable_path=CHROME)
        w, h = (int(x) for x in args.size.split("x"))
        page = await browser.new_page(viewport={"width": w, "height": h})
        errors: list[str] = []
        page.on("pageerror", lambda e: errors.append(str(e)))
        await page.goto(url)
        await page.wait_for_selector(".prompt.yours")
        if not await page.locator("#game .troop.usable").count():
            await page.locator(".bag.can-draw").click()  # an empty rack: draw first, place next turn
        await page.wait_for_selector("#game .troop.usable", timeout=60000)
        await page.locator("#game .troop.usable").last.click()
        await page.locator(".slot.target").first.click(force=True)
        for i in range(args.frames):
            await page.screenshot(path=str(out / f"f{i:03d}.png"))
            await page.wait_for_timeout(args.every)
        await browser.close()
        print("errors:", errors)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--terrain", default="rug")
    ap.add_argument("--size", default="1280x800")
    ap.add_argument("--turns", type=int, default=10)
    ap.add_argument("--seed", type=int, default=3)
    ap.add_argument("--frames", type=int, default=40)
    ap.add_argument("--every", type=int, default=90)
    ap.add_argument("--port", type=int, default=8793)
    asyncio.run(run(ap.parse_args()))


if __name__ == "__main__":
    main()
