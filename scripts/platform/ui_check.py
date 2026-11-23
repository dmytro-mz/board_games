"""Click through the room page in Chrome with two players: create, join, vote, launch every game, go back.

    uv run python scripts/platform/ui_check.py [--games ttr,karak] [--size 1440x900] [--shots shots/platform]

Fails on any JavaScript error in the room page or in a game's frame. Screenshots land in --shots.
"""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import socket
import sys
from collections.abc import AsyncIterator
from pathlib import Path

import uvicorn
from playwright.async_api import Browser, Page, async_playwright

from boardgames.games import GAME_KEYS
from boardgames.server import create_app


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@contextlib.asynccontextmanager
async def serve() -> AsyncIterator[str]:
    port = _free_port()
    server = uvicorn.Server(
        uvicorn.Config(create_app(delay_scale=0.05), host="127.0.0.1", port=port, log_level="warning")
    )
    task = asyncio.create_task(server.serve())
    while not server.started:
        await asyncio.sleep(0.05)
    try:
        yield f"http://127.0.0.1:{port}"
    finally:
        server.should_exit = True
        await task


class Player:
    def __init__(self, page: Page, name: str, errors: list[str]) -> None:
        self.page = page
        self.name = name
        page.on("pageerror", lambda e: errors.append(f"{name}: {e}"))
        page.on("console", lambda m: m.type == "error" and errors.append(f"{name} console: {m.text}"))


async def player(browser: Browser, name: str, size: tuple[int, int], errors: list[str]) -> Player:
    context = await browser.new_context(viewport={"width": size[0], "height": size[1]})
    page = await context.new_page()
    return Player(page, name, errors)


async def check(base: str, games: list[str], size: tuple[int, int], shots: Path) -> list[str]:
    errors: list[str] = []
    shots.mkdir(parents=True, exist_ok=True)
    async with async_playwright() as pw:
        browser = await pw.chromium.launch()
        ann = await player(browser, "Ann", size, errors)
        bob = await player(browser, "Bob", size, errors)

        # level 1: Ann creates a room
        await ann.page.goto(base + "/")
        await ann.page.fill(".home-form input.text:not(.code)", "Ann")
        await ann.page.screenshot(path=shots / "1-home.png")
        await ann.page.click('button:has-text("Create a room")')
        await ann.page.wait_for_selector(".tiles .tile")
        code = ann.page.url.rstrip("/").split("/")[-1]

        # Bob joins with the code
        await bob.page.goto(base + "/")
        await bob.page.fill(".home-form input.text:not(.code)", "Bob")
        await bob.page.fill("input.code", code)
        await bob.page.click(".join-row button")
        await bob.page.wait_for_selector(".tiles .tile")
        await ann.page.wait_for_selector(".person >> text=Bob")
        # the player filter: two people can't play Codenames (4+, no bots); "Any" shows every game
        assert await ann.page.locator('[data-key="tile-codenames"]').count() == 0
        for p in (ann, bob):
            await p.page.click('.seg:has-text("Any")')
        await ann.page.wait_for_selector('[data-key="tile-codenames"]')

        for i, key in enumerate(games):
            # level 2: Bob votes for the game, Ann votes for another one first (a tie), then for the same one
            other = next(k for k in GAME_KEYS if k != key)
            await bob.page.click(f'[data-key="tile-{key}"]')
            await ann.page.click(f'[data-key="tile-{other}"]')
            await ann.page.wait_for_selector(".actionbar >> text=The votes are tied")
            assert await ann.page.locator(".launch .btn").count() == 1, "a tie leaves only 'Play selected'"
            await ann.page.click(f'[data-key="tile-{other}"]')  # take the vote back: Bob's game is the most voted
            await ann.page.wait_for_selector(".launch >> text=Play most voted")
            await ann.page.click(f'[data-key="tile-{key}"]')  # both buttons would launch the same game: one button
            await ann.page.wait_for_selector('.launch .btn:has-text("Play:")')
            assert await ann.page.locator(".launch .btn").count() == 1
            if i == 0:
                await ann.page.screenshot(path=shots / "2-select.png")
                await bob.page.screenshot(path=shots / "2-select-bob.png")
            await ann.page.click(".launch .btn")

            # level 3: both see the game's own lobby in the frame
            for p in (ann, bob):
                await p.page.wait_for_selector(f'iframe[src="/g/{key}/r/{code}"]')
                frame = p.page.frame_locator("#game-frame")
                await frame.locator("#app *").first.wait_for(timeout=15_000)
            await ann.page.wait_for_selector(".back-pill")
            await ann.page.wait_for_timeout(1200)  # fonts, art and the lobby's first animation
            await ann.page.screenshot(path=shots / f"3-{key}-lobby.png")
            assert await bob.page.locator(".back-pill").count() == 0, "only the leader may ask to go back"

            # back to the selection: Bob declines, then accepts (every other game), else Ann forces it
            await ann.page.click(".back-pill")
            await bob.page.wait_for_selector(".modal >> text=wants to choose another game")
            await bob.page.click('.modal button:has-text("Stay here")')
            await ann.page.wait_for_selector(".replies .declined")
            if i == 0:
                await ann.page.screenshot(path=shots / "4-back-leader.png")
                await bob.page.screenshot(path=shots / "4-back-bob.png")
            if i % 2 == 0:
                await bob.page.click(".modal .btn.primary")
            else:
                await ann.page.click('.modal button:has-text("Go back now")')
            for p in (ann, bob):
                await p.page.wait_for_selector(".tiles .tile")
            print(f"  {key}: lobby ok, back ok")
        await browser.close()
    return errors


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--games", default=",".join(GAME_KEYS))
    parser.add_argument("--size", default="1440x900")
    parser.add_argument("--shots", default="shots/platform")
    args = parser.parse_args()
    w, h = (int(x) for x in args.size.split("x"))

    async def run() -> list[str]:
        async with serve() as base:
            return await check(base, args.games.split(","), (w, h), Path(args.shots))

    errors = asyncio.run(run())
    if errors:
        print("JavaScript errors:", *errors, sep="\n  ")
        sys.exit(1)
    print("no JavaScript errors")


if __name__ == "__main__":
    main()
