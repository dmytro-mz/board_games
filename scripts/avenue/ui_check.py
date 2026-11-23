"""Click through whole games in Chrome like a player would; fails on any JS error or a stuck table.

uv run python scripts/ui_check.py [--mode simple|advanced] [--players 2|4] [--games 1] [--size 1440x900]
                                  [--shots shots/ui] [--headed]
"""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import random
import sys
import time
from collections.abc import AsyncIterator
from pathlib import Path

import uvicorn
from playwright.async_api import Page, async_playwright

from boardgames.testing import game_app

CHROME = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
PORT = 8771


@contextlib.asynccontextmanager
async def serving(port: int) -> AsyncIterator[str]:
    app = game_app("avenue", delay_scale=0.35, think=0.15)
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning"))
    task = asyncio.create_task(server.serve())
    while not server.started:
        await asyncio.sleep(0.05)
    try:
        yield f"http://127.0.0.1:{port}"
    finally:
        server.should_exit = True
        await task


async def my_move(page: Page, rng: random.Random) -> str | None:
    """Make one move if the table waits for me; returns what was done."""
    if await page.evaluate("window.agentAvenue.busy()"):
        return None
    prompt = page.locator(".prompt.mine")
    if not await prompt.count():
        return None
    # black market choice / recruit / market
    if await page.locator(".prompt.mine .choice-card").count():
        cards = page.locator(".prompt.mine .choice-card")
        await cards.nth(rng.randrange(await cards.count())).click()
        return "choose"
    if await page.locator(".slot.pickable").count():
        slots = page.locator(".slot.pickable")
        await slots.nth(rng.randrange(await slots.count())).click()
        return "recruit"
    if await page.locator(".supply.pickable").count():
        supply = page.locator(".supply.pickable")
        await supply.nth(rng.randrange(await supply.count())).click()
        return "market"
    text = await prompt.inner_text()
    if "again right away" in text:
        await page.locator(".prompt.mine .btn").nth(rng.randrange(2)).click()
        return "spycation"
    me = await page.evaluate("window.agentAvenue.state()?.game?.me")
    plays = [a for a in (me or {}).get("legal", []) if a["type"] == "play"]
    if not plays:
        return None
    hand = page.locator(".hand-card")
    discard = page.locator(".prompt.mine button", has_text="Discard & draw")
    if await discard.count() and rng.random() < 0.15:
        await discard.click()
        await page.locator(".hand.discarding .hand-card").nth(rng.randrange(len(me["hand"]))).click()
        return "discard"
    action = rng.choice(plays)
    used: set[int] = set()
    for which in ("up", "down"):
        key = action[which]
        if key is None:
            continue
        i = next(i for i, k in enumerate(me["hand"]) if k == key and i not in used)
        used.add(i)
        await hand.nth(i).click()
        await page.wait_for_timeout(80)
    await page.locator(".prompt.mine button.primary").first.click()
    return "play"


async def run(args: argparse.Namespace) -> int:
    errors: list[str] = []
    rng = random.Random(args.seed)
    shots = Path(args.shots)
    shots.mkdir(parents=True, exist_ok=True)
    w, h = (int(x) for x in args.size.split("x"))
    async with serving(PORT) as base, async_playwright() as pw:
        browser = await pw.chromium.launch(executable_path=CHROME, headless=not args.headed)
        page = await browser.new_page(viewport={"width": w, "height": h})
        page.on("pageerror", lambda e: errors.append(f"pageerror: {e}"))
        page.on("console", lambda m: m.type == "error" and errors.append(f"console: {m.text}"))
        await page.goto(base)  # the room page; then a table of this game straight away (no voting)
        await page.evaluate("localStorage.setItem('bg.name', 'Tester')")
        code = await page.evaluate(
            "fetch('/g/avenue/api/rooms', {method: 'POST'}).then((r) => r.json()).then((j) => j.room)"
        )
        await page.goto(f"{base}/g/avenue/r/{code}")
        await page.wait_for_selector(".lobby")
        if args.mode == "advanced":
            await page.click(".seg-btn:has-text('Advanced')")
        await page.wait_for_timeout(200)
        await page.locator(".team-col.t1 .bot-add").first.click()
        if args.players == 4:
            await page.wait_for_timeout(200)
            await page.locator(".team-col.t1 .bot-add").first.click()
            await page.wait_for_timeout(200)
            await page.locator(".team-col.t0 .bot-add").first.click()
        await page.wait_for_timeout(300)
        await page.screenshot(path=str(shots / "lobby.png"))
        moves = 0
        for game_no in range(args.games):
            await page.click(".btn.start" if game_no == 0 else ".game-over .btn.primary")
            await page.wait_for_selector(".game-over", state="detached")
            await page.wait_for_selector(".board")
            started = time.time()
            last_progress = time.time()
            shot_at = {3, 12, 25}
            while True:
                if await page.locator(".game-over").count():
                    break
                did = await my_move(page, rng)
                if did:
                    moves += 1
                    last_progress = time.time()
                    if moves in shot_at:
                        await page.wait_for_timeout(450)
                        await page.screenshot(path=str(shots / f"g{game_no}_move{moves}.png"))
                await page.wait_for_timeout(250)
                status = (
                    await page.locator(".prompt-text").inner_text()
                    if await page.locator(".prompt-text").count()
                    else ""
                )
                if "won" in status.lower() or "wins" in status.lower():
                    await page.wait_for_selector(".game-over", timeout=15000)
                    break
                if time.time() - last_progress > 60:
                    errors.append(f"stuck: {status!r}")
                    await page.screenshot(path=str(shots / "stuck.png"))
                    break
            await page.wait_for_timeout(600)
            await page.screenshot(path=str(shots / f"g{game_no}_over.png"))
            print(f"game {game_no + 1}: {moves} moves so far, {time.time() - started:.0f}s")
        # back to the lobby: the result window must go away with the table
        if await page.locator(".game-over").count():
            await page.click(".game-over .btn:has-text('Back to lobby')")
            await page.wait_for_selector(".lobby")
            await page.wait_for_timeout(400)
            if await page.locator(".game-over").count():
                errors.append("the result window stays open over the lobby")
            await page.screenshot(path=str(shots / "back_in_lobby.png"))
        else:
            errors.append("no result window after the last game")
        await browser.close()
    for e in errors:
        print(e)
    print("OK" if not errors else f"{len(errors)} problems")
    return 1 if errors else 0


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--mode", default="simple", choices=["simple", "advanced"])
    ap.add_argument("--players", type=int, default=2, choices=[2, 4])
    ap.add_argument("--games", type=int, default=1)
    ap.add_argument("--size", default="1440x900")
    ap.add_argument("--shots", default="shots/ui")
    ap.add_argument("--seed", type=int, default=1)
    ap.add_argument("--headed", action="store_true")
    sys.exit(asyncio.run(run(ap.parse_args())))


if __name__ == "__main__":
    main()
