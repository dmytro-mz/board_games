"""Film a push that knocks a marble out, and the bot's answer, frame by frame (animations on) into shots/sumo/anim/.

uv run python scripts/sumo/anim_frames.py [--size 1280x800] [--white] [--frames 40] [--every 60]
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
from sumo.game.board import cells
from sumo.game.engine import EMPTY, MARBLES
from sumo.web.room import Room

CHROME = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
BLACK = "A1 A2 A3 A4 B2 B3 B4 B5 C3 C4 D4 E6 E7 E8"
WHITE = "E9 I5 I6 I7 I8 H5 H6 H7 G5 G6 F6"  # 11 on the board: 3 already out


def position(room: Room, white_moves: bool) -> None:
    """Black (or White, with the colours swapped below) can push E9 out with E7-E8 → east."""
    game = room.game
    assert game is not None
    black, white = cells(BLACK), cells(WHITE)
    if white_moves:  # the human plays White: mirror the colours
        black, white = white, black
    game.cells = [EMPTY] * len(game.cells)
    game.ids = [None] * len(game.cells)
    for side, group in enumerate((black, white)):
        for i, c in enumerate(group):
            game.cells[c] = side
            game.ids[c] = side * MARBLES + i
    for side, group in enumerate((black, white)):
        game.out[side] = MARBLES - len(group)
        game.lost[side] = [side * MARBLES + i for i in range(len(group), MARBLES)]
    game.current = 1 if white_moves else 0
    game.check()


async def run(args: argparse.Namespace) -> None:
    room = prepare("play", 0, args.seed, "classic", args.white)
    position(room, args.white)
    room.delay_scale = 1.0
    out = Path("shots/sumo/anim")
    out.mkdir(parents=True, exist_ok=True)
    for old in out.glob("*.png"):
        old.unlink()
    async with serving(game_app("sumo"), room, args.port) as url, async_playwright() as pw:
        browser = await pw.chromium.launch(executable_path=CHROME)
        w, h = (int(x) for x in args.size.split("x"))
        page = await browser.new_page(viewport={"width": w, "height": h})
        errors: list[str] = []
        page.on("pageerror", lambda e: errors.append(str(e)))
        await page.goto(url)
        await page.wait_for_selector(".prompt.yours")
        e7, e8 = cells("E7 E8")
        await page.locator(f'#board .cell[data-cell="{e7}"]').click()
        await page.locator(f'#board .cell[data-cell="{e8}"]').click()
        await page.screenshot(path=str(out / "selected.png"))
        await page.locator("#board .dir-arrow.push").first.click(force=True)
        for i in range(args.frames):
            await page.screenshot(path=str(out / f"f{i:03d}.png"))
            await page.wait_for_timeout(args.every)
        await browser.close()
        print("errors:", errors)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--size", default="1280x800")
    ap.add_argument("--white", action="store_true")
    ap.add_argument("--seed", type=int, default=3)
    ap.add_argument("--frames", type=int, default=40)
    ap.add_argument("--every", type=int, default=60)
    ap.add_argument("--port", type=int, default=8794)
    asyncio.run(run(ap.parse_args()))


if __name__ == "__main__":
    main()
