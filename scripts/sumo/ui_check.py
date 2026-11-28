"""Click through a whole game against a bot in Chrome and fail on any JS error, a rebuilt board or a stuck table.

uv run python scripts/sumo/ui_check.py [--layout classic] [--bot rookie] [--size 1280x800] [--white] [--motion]
                                       [--headed] [--limit 0]

Our moves use every input path: tap marbles (also two or three in a line) then an arrow or a glowing dimple, and
drag a marble. A move limit (`--limit`, moves per player) keeps the run short against strong bots.
"""

from __future__ import annotations

import argparse
import asyncio
import random
import sys
from pathlib import Path

from playwright.async_api import ConsoleMessage, Page, async_playwright

sys.path.insert(0, str(Path(__file__).parent))
from demo import TOKEN, serving

from boardgames.testing import game_app
from sumo.web.room import Room

CHROME = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
FORCE = True  # pulsing targets never count as 'stable' for Playwright


async def my_move(page: Page, room: Room, rng: random.Random, motion: bool) -> bool:
    """One whole move of ours; False if it isn't our turn (or the UI isn't ready)."""
    prompt = page.locator(".prompt-row .prompt.yours")
    if not await prompt.count():
        return False
    usable = page.locator("#board .cell.usable")
    n = await usable.count()
    if not n:
        return False
    turn = room.game.turn if room.game else -1
    how = rng.random()
    if how < 0.3:
        # drag a usable marble in a random direction
        cell = usable.nth(rng.randrange(n))
        box = await cell.bounding_box()
        if box:
            import math

            ang = math.radians(rng.choice([0, -60, -120, 180, 120, 60]) + rng.uniform(-12, 12))
            x, y = box["x"] + box["width"] / 2, box["y"] + box["height"] / 2
            dist = box["width"] * 0.9
            await page.mouse.move(x, y)
            await page.mouse.down()
            await page.mouse.move(x + math.cos(ang) * dist, y + math.sin(ang) * dist, steps=6)
            await page.mouse.up()
    else:
        first = usable.nth(rng.randrange(n))
        await first.click(force=FORCE)
        if rng.random() < 0.6:
            # extend the selection with a neighbour (the page decides whether it forms a line)
            await page.wait_for_timeout(30)
            more = page.locator("#board .cell.usable:not(.sel)")
            m = await more.count()
            if m:
                await more.nth(rng.randrange(m)).click(force=FORCE)
        await page.wait_for_timeout(40)
        arrows = page.locator("#board .dir-arrow")
        targets = page.locator("#board .cell.target")
        a, t = await arrows.count(), await targets.count()
        if a and (not t or rng.random() < 0.6):
            await arrows.nth(rng.randrange(a)).click(force=FORCE)
        elif t:
            await targets.nth(rng.randrange(t)).click(force=FORCE)
        else:
            await page.keyboard.press("Escape")
            return False
    for _ in range(60):
        if not room.game or room.game.turn != turn or room.status != "playing":
            return True
        await page.wait_for_timeout(20)
    return False  # e.g. a drag in a direction with no move: nothing happened


async def run(args: argparse.Namespace) -> int:
    room = Room("UICHK", delay_scale=0.05, seed=args.seed, bot_budget=0.1)
    me = room.join(TOKEN, "Tester")
    room.handle(me.id, {"type": "add_bot", "bot": args.bot})
    if args.white:
        room.handle(me.id, {"type": "swap"})
    errors: list[str] = []
    rng = random.Random(args.seed)
    app = game_app("sumo", delay_scale=0.05)
    async with serving(app, room, args.port) as url, async_playwright() as pw:
        browser = await pw.chromium.launch(executable_path=CHROME, headless=not args.headed)
        w, h = (int(x) for x in args.size.split("x"))
        motion = "no-preference" if args.motion else "reduce"
        page = await browser.new_page(viewport={"width": w, "height": h}, reduced_motion=motion)
        page.on("pageerror", lambda e: errors.append(f"pageerror: {e}"))

        def console(m: ConsoleMessage) -> None:
            if m.type == "error":
                errors.append(f"console: {m.text}")

        page.on("console", console)
        await page.goto(url)
        await page.wait_for_selector(".lobby")
        # Picking an opening and a rule must patch the lobby in place, not rebuild it.
        await page.evaluate("() => { window.__keep = [...document.querySelectorAll('#main .panel')]; }")
        await page.locator(f'.layout-card[data-key="layout-{args.layout}"]').click()
        await page.select_option('select[data-setting="move_limit"]', str(args.limit))
        for _ in range(100):
            if room.settings.layout == args.layout and room.settings.move_limit == args.limit:
                break
            await page.wait_for_timeout(20)
        await page.wait_for_timeout(200)
        lost = await page.evaluate("() => window.__keep.filter((el) => !el.isConnected).length")
        if lost:
            errors.append(f"lobby changes rebuilt {lost} panels")
        if room.settings.layout != args.layout or room.settings.move_limit != args.limit:
            errors.append(f"lobby settings not applied: {room.settings}")
        # the rule book opens from the lobby, every tab
        await page.locator(".lobby-actions .btn.ghost").click()
        await page.wait_for_selector(".modal.rules")
        for tab in ("Moving & pushing", "Openings", "At this table", "The game"):
            await page.locator(".rules-tabs .tab", has_text=tab).click()
        await page.keyboard.press("Escape")
        await page.locator(".lobby-actions .btn.primary").click()
        await page.wait_for_selector("#board")
        await page.evaluate("() => { window.__board = document.querySelector('#board'); }")
        idle = 0
        moves = 0
        for _ in range(8000):
            if room.status == "game_over":
                break
            acted = await my_move(page, room, rng, args.motion)
            moves += acted
            idle = 0 if acted else idle + 1
            if idle > 600:
                errors.append(f"stuck: status={room.status} turn={room.game and room.game.turn}")
                break
            await page.wait_for_timeout(30 if acted else 25)
        if not await page.evaluate("() => window.__board.isConnected"):
            errors.append("the board was rebuilt during the game")
        await page.locator('.topbar [title="Rule book"]').click()
        await page.wait_for_selector(".modal.rules")
        await page.keyboard.press("Escape")
        await page.wait_for_selector("#overlay .modal.end", timeout=10000)
        Path("shots/sumo").mkdir(parents=True, exist_ok=True)
        await page.screenshot(path=f"shots/sumo/ui_check_{args.layout}_{args.size}.png")
        await page.locator("#overlay .btn.ghost").click()
        await page.wait_for_timeout(300)
        await page.screenshot(path=f"shots/sumo/ui_check_{args.layout}_{args.size}_board.png")
        await browser.close()
    if room.status != "game_over":
        errors.append(f"game did not finish (status {room.status})")
    for e in errors:
        print(e)
    result = room.game.result if room.game else None
    print("ok" if not errors else "FAILED", f"· {args.layout} {args.size} · {moves} moves by us · result {result}")
    return 1 if errors else 0


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--layout", default="classic")
    ap.add_argument("--bot", default="rookie")
    ap.add_argument("--size", default="1280x800")
    ap.add_argument("--seed", type=int, default=7)
    ap.add_argument("--port", type=int, default=8773)
    ap.add_argument("--limit", type=int, default=0, help="move limit per player (0 = play until six are out)")
    ap.add_argument("--white", action="store_true")
    ap.add_argument("--headed", action="store_true")
    ap.add_argument("--motion", action="store_true", help="keep animations on")
    sys.exit(asyncio.run(run(ap.parse_args())))


if __name__ == "__main__":
    main()
