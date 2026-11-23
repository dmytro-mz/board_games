"""Screenshot the game at several screen sizes, with and without a city popover open (layout checks).

uv run python scripts/sizes.py [--stage play] [--sizes 390x844,844x390,768x1024,1024x700,1280x720,1440x900,1920x1080]
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

from playwright.async_api import async_playwright

sys.path.insert(0, str(Path(__file__).parent))
from demo import STAGES, prepare, serving
from shot import CHROME

from boardgames.testing import game_app

SIZES = "390x844,844x390,768x1024,1024x700,1280x720,1440x900,1920x1080"


async def run(args: argparse.Namespace) -> int:
    room = prepare(args.stage, args.bots, args.seed)
    room.close()  # frozen: no bot moves
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    errors: list[str] = []
    async with serving(game_app("pandemic"), room) as url, async_playwright() as pw:
        browser = await pw.chromium.launch(executable_path=CHROME)
        for size in args.sizes.split(","):
            w, h = (int(v) for v in size.split("x"))
            page = await browser.new_page(viewport={"width": w, "height": h}, reduced_motion="reduce")
            page.on("pageerror", lambda e: errors.append(str(e)))
            page.on("console", lambda m: m.type == "error" and errors.append(m.text))
            await page.goto(url if args.stage != "home" else url.split("/g/")[0] + "/")
            await page.wait_for_timeout(1200)
            await page.screenshot(path=str(out / f"{args.stage}-{size}.png"))
            if room.game is not None and room.status == "playing":
                seat = room.seat_of(room.seats[0].member_id or "") or 0
                at = room.game.location[seat]
                target = next(iter(sorted(c for c in room.game.cubes if c != at)), at)
                await page.locator(f'#map .city[data-id="{target}"]').focus()
                await page.keyboard.press("Enter")
                await page.wait_for_timeout(300)
                await page.screenshot(path=str(out / f"{args.stage}-{size}-pop.png"))
            await page.close()
        await browser.close()
    for e in errors:
        print("JS error:", e)
    print(f"screenshots in {out}/")
    return 1 if errors else 0


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--stage", default="play", choices=STAGES)
    ap.add_argument("--sizes", default=SIZES)
    ap.add_argument("--bots", type=int, default=2)
    ap.add_argument("--seed", type=int, default=3)
    ap.add_argument("--out", default="shots/sizes")
    sys.exit(asyncio.run(run(ap.parse_args())))


if __name__ == "__main__":
    main()
