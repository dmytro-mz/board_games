"""Click through a whole game against the bot in Chrome and fail on any JS error, a rebuilt board or a stuck table.

uv run python scripts/toybattle/ui_check.py [--terrain rug] [--size 1280x800] [--red] [--motion] [--headed]
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
from toybattle.web.room import Room

CHROME = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
FORCE = True  # pulsing targets never count as 'stable' for Playwright


async def visible(page: Page, selector: str) -> bool:
    loc = page.locator(selector)
    return await loc.count() > 0 and await loc.first.is_visible()


async def my_move(page: Page, rng: random.Random, drag: bool) -> bool:
    """One click-level step of our turn; False if there was nothing to do."""
    if await visible(page, ".backdrop .tile-btn"):  # revive picker
        await page.locator(".backdrop .tile-btn").first.click(force=FORCE)
        return True
    prompt = page.locator(".prompt-row .prompt")
    if not await prompt.count():
        return False
    cls = await prompt.first.get_attribute("class") or ""
    if "effect" in cls:
        picks = page.locator(".slot.pick, .slot.target")
        if await picks.count() and rng.random() < 0.85:
            await picks.nth(rng.randrange(await picks.count())).click(force=FORCE)
            return True
        usable = page.locator("#game .troop.usable")
        if await usable.count() and rng.random() < 0.8:
            await usable.nth(rng.randrange(await usable.count())).click(force=FORCE)
            await page.wait_for_timeout(40)
            targets = page.locator(".slot.target")
            if await targets.count():
                await targets.nth(rng.randrange(await targets.count())).click(force=FORCE)
            return True
        buttons = page.locator(".prompt-btns .btn.primary")
        if await buttons.count() and rng.random() < 0.8:
            await buttons.first.click(force=FORCE)
        else:
            await page.locator(".prompt-btns .btn.ghost").last.click(force=FORCE)
        return True
    if "yours" not in cls:
        return False
    usable = page.locator("#game .troop.usable")
    n = await usable.count()
    if n and (rng.random() < 0.8 or not await visible(page, ".bag.can-draw")):
        tile = usable.nth(rng.randrange(n))
        if drag and rng.random() < 0.5:
            await tile.click(force=FORCE)  # select, so targets show
            targets = page.locator(".slot.target")
            if await targets.count():
                box = await tile.bounding_box()
                dest = await targets.nth(rng.randrange(await targets.count())).bounding_box()
                await page.keyboard.press("Escape")
                if box and dest:
                    await page.mouse.move(box["x"] + box["width"] / 2, box["y"] + box["height"] / 2)
                    await page.mouse.down()
                    await page.mouse.move(dest["x"] + dest["width"] / 2, dest["y"] + dest["height"] / 2, steps=8)
                    await page.mouse.up()
                    return True
        await tile.click(force=FORCE)
        await page.wait_for_timeout(40)
        targets = page.locator(".slot.target")
        if await targets.count():
            await targets.nth(rng.randrange(await targets.count())).click(force=FORCE)
            return True
        return False
    if await visible(page, ".bag.can-draw"):
        await page.locator(".bag.can-draw").first.click(force=FORCE)
        return True
    return False


async def run(args: argparse.Namespace) -> int:
    room = Room("UICHK", delay_scale=0.05, seed=args.seed, bot_budget=0.15)
    me = room.join(TOKEN, "Tester")
    room.handle(me.id, {"type": "add_bot", "bot": "general"})
    if args.red:
        room.handle(me.id, {"type": "swap"})
    errors: list[str] = []
    rng = random.Random(args.seed)
    app = game_app("toybattle", delay_scale=0.05)
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
        # Picking a terrain and toggling a rule must patch the lobby in place, not rebuild it.
        await page.evaluate("() => { window.__keep = [...document.querySelectorAll('#main .panel')]; }")
        for selector in (f'.terrain-card[data-key="terrain-{args.terrain}"]', ".settings .switch", ".settings .switch"):
            seq = room.seq
            await page.locator(selector).first.click()
            for _ in range(100):
                if room.seq > seq:
                    break
                await page.wait_for_timeout(20)
            await page.wait_for_timeout(150)
        lost = await page.evaluate("() => window.__keep.filter((el) => !el.isConnected).length")
        if lost:
            errors.append(f"lobby changes rebuilt {lost} panels")
        if room.settings.terrain != args.terrain or not room.settings.special:
            errors.append(f"lobby settings not applied: {room.settings}")
        # the rule book opens from the lobby
        await page.locator(".lobby-actions .btn.ghost").click()
        await page.wait_for_selector(".modal.rules")
        for tab in ("Troops", "Terrains", "Fine print", "The game"):
            await page.locator(".rules-tabs .tab", has_text=tab).click()
        await page.keyboard.press("Escape")
        await page.locator(".lobby-actions .btn.primary").click()
        await page.wait_for_selector("#game")
        await page.evaluate("() => { window.__board = document.querySelector('#board'); }")
        idle = 0
        for _ in range(6000):
            if room.status == "game_over":
                break
            acted = await my_move(page, rng, drag=not args.motion)
            idle = 0 if acted else idle + 1
            if idle > 400:
                errors.append(f"stuck: status={room.status} phase={room.game and room.game.phase}")
                break
            await page.wait_for_timeout(50 if acted else 40)
        if not await page.evaluate("() => window.__board.isConnected"):
            errors.append("the board was rebuilt during the game")
        # rule book during the game
        await page.locator('.topbar [title="Rule book"]').click()
        await page.wait_for_selector(".modal.rules")
        await page.keyboard.press("Escape")
        await page.wait_for_selector("#overlay .modal.end", timeout=10000)
        Path("shots/toybattle").mkdir(parents=True, exist_ok=True)
        await page.screenshot(path=f"shots/toybattle/ui_check_{args.terrain}_{args.size}.png")
        await page.locator("#overlay .btn.ghost").click()
        await page.wait_for_timeout(300)
        await browser.close()
    if room.status != "game_over":
        errors.append(f"game did not finish (status {room.status})")
    for e in errors:
        print(e)
    result = room.game.result if room.game else None
    print("ok" if not errors else "FAILED", f"· {args.terrain} {args.size} · result {result}")
    return 1 if errors else 0


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--terrain", default="rug")
    ap.add_argument("--size", default="1280x800")
    ap.add_argument("--seed", type=int, default=7)
    ap.add_argument("--port", type=int, default=8772)
    ap.add_argument("--red", action="store_true")
    ap.add_argument("--headed", action="store_true")
    ap.add_argument("--motion", action="store_true", help="keep animations on")
    sys.exit(asyncio.run(run(ap.parse_args())))


if __name__ == "__main__":
    main()
