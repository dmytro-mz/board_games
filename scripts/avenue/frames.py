"""Record the animation after one click as a contact sheet (visual checks of the animations).

uv run python scripts/frames.py [--stage recruit|play] [--mode simple|advanced] [--out shots/frames.png]
"""

from __future__ import annotations

import argparse
import asyncio
import io
import sys
from pathlib import Path

from PIL import Image
from playwright.async_api import async_playwright

sys.path.insert(0, str(Path(__file__).parent))
from demo import prepare, serving

from boardgames.testing import game_app

CHROME = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"


async def run(args: argparse.Namespace) -> None:
    room = prepare(args.stage, args.mode, 2, args.turns, args.seed)
    room.delay_scale = 1.0
    for seat in room.seats:
        if seat.agent is not None:
            seat.agent.budget = 0.2  # type: ignore[attr-defined]
    app = game_app("avenue")
    frames: list[Image.Image] = []
    async with serving(app, room, 8790) as url, async_playwright() as pw:
        browser = await pw.chromium.launch(executable_path=CHROME)
        page = await browser.new_page(viewport={"width": 1280, "height": 800})
        await page.goto(url)
        await page.wait_for_selector(".board")
        await page.wait_for_timeout(1200)
        if args.stage == "recruit":
            await page.locator(".slot.pickable").nth(args.pick).click()
        else:
            me = await page.evaluate("window.agentAvenue.state().game.me")
            play = next(a for a in me["legal"] if a["type"] == "play")
            used: set[int] = set()
            for which in ("up", "down"):
                i = next(i for i, k in enumerate(me["hand"]) if k == play[which] and i not in used)
                used.add(i)
                await page.locator(".hand-card").nth(i).click()
            await page.locator(".prompt.mine button.primary").first.click()
        for _ in range(args.n):
            png = await page.screenshot()
            frames.append(Image.open(io.BytesIO(png)).convert("RGB"))
            await page.wait_for_timeout(args.every)
        await browser.close()
    cols = 4
    w, h = frames[0].size
    scale = 0.36
    tw, th = int(w * scale), int(h * scale)
    rows = (len(frames) + cols - 1) // cols
    sheet = Image.new("RGB", (tw * cols, th * rows), "white")
    for i, f in enumerate(frames):
        sheet.paste(f.resize((tw, th)), ((i % cols) * tw, (i // cols) * th))
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    sheet.save(args.out)
    for i, f in enumerate(frames):
        f.save(Path(args.out).with_name(f"frame{i:02d}.png"))
    print(args.out)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--stage", default="recruit", choices=["recruit", "play"])
    ap.add_argument("--mode", default="simple")
    ap.add_argument("--turns", type=int, default=3)
    ap.add_argument("--seed", type=int, default=5)
    ap.add_argument("--pick", type=int, default=1)
    ap.add_argument("--n", type=int, default=16)
    ap.add_argument("--every", type=int, default=150)
    ap.add_argument("--out", default="shots/frames/sheet.png")
    asyncio.run(run(ap.parse_args()))


if __name__ == "__main__":
    main()
