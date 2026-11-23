"""Walk through the whole app the way people do, with real typing, and fail on any glitch.

uv run python scripts/flow_check.py [--headed] [--closed]

Three fresh browsers (no saved name or token): Anna hosts on a desktop, Boris joins by typing the table code on a
phone, Carl opens the invite link on a tablet and watches. They type names, chat, rename, change every setting,
pick roles, add and remove bots, check host-only controls, then Anna and Boris play a whole game against the
clock with a bot (the Expert planner decides, the script clicks and types), with a reload in the middle. After
the game: play again, back to the lobby, leave. Any JS error or unexpected error toast fails the run.
"""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import sys
import time
import traceback
from collections.abc import AsyncIterator, Awaitable, Callable
from pathlib import Path

import uvicorn
from playwright.async_api import Browser, Page, async_playwright

sys.path.insert(0, str(Path(__file__).parent))
from shot import CHROME
from ui_check import Check, Failed, instrument

from boardgames.testing import game_app
from pandemic.web.room import Room

PORT = 8766
OUT = Path("shots/flow")


class Person:
    def __init__(self, name: str, page: Page) -> None:
        self.name, self.page = name, page
        self.errors: list[str] = []
        self.toasts: list[str] = []


class Flow:
    def __init__(self, browser: Browser, base: str, app, closed: bool) -> None:
        self.browser, self.base, self.app, self.closed = browser, base, app, closed
        self.people: list[Person] = []
        self.step = 0

    # ------------------------------------------------------------------ helpers
    async def person(self, name: str, w: int, h: int, phone: bool = False) -> Person:
        ctx = await self.browser.new_context(
            viewport={"width": w, "height": h}, reduced_motion="reduce", has_touch=phone, is_mobile=phone
        )
        await ctx.grant_permissions(["clipboard-read", "clipboard-write"])
        p = Person(name, await ctx.new_page())
        await instrument(p.page, p.errors, p.toasts)
        self.people.append(p)
        return p

    def check_clean(self, where: str) -> None:
        for p in self.people:
            if p.errors:
                raise Failed(f"{where}: JS error for {p.name}: {p.errors[0]}")
            if p.toasts:
                raise Failed(f"{where}: unexpected error toast for {p.name}: {p.toasts[0]}")

    async def shot(self, p: Person, label: str) -> None:
        self.step += 1
        await p.page.screenshot(path=str(OUT / f"{self.step:02d}-{p.name.lower()}-{label}.png"))

    async def until(self, cond: Callable[[], Awaitable[bool]] | Callable[[], bool], what: str, timeout=8.0) -> None:
        end = time.monotonic() + timeout
        while time.monotonic() < end:
            res = cond()
            if asyncio.iscoroutine(res):
                res = await res
            if res:
                return
            await asyncio.sleep(0.05)
        for p in self.people:
            await p.page.screenshot(path=str(OUT / f"fail-{p.name.lower()}.png"))
        raise Failed(f"timed out: {what} (screenshots: {OUT}/fail-*.png)")

    async def text(self, p: Person, sel: str) -> str:
        loc = p.page.locator(sel)
        return await loc.first.inner_text() if await loc.count() else ""

    async def has_text(self, p: Person, sel: str, want: str, what: str) -> None:
        await self.until(lambda: self._contains(p, sel, want), f"{p.name}: {what} ({want!r} in {sel})")

    async def _contains(self, p: Person, sel: str, want: str) -> bool:
        return want in await self.text(p, sel)

    async def type_into(self, p: Person, sel: str, text: str) -> None:
        """Click the field and type key by key, like a person (fill() would skip keydown handlers)."""
        await p.page.locator(sel).click()
        await p.page.keyboard.type(text, delay=15)
        value = await p.page.locator(sel).input_value()
        if not value.endswith(text):
            raise Failed(f"{p.name}: typed {text!r} into {sel} but it holds {value!r}")

    def room(self) -> Room:
        rooms = list(self.app.state.manager.rooms.values())
        assert len(rooms) == 1, rooms
        return rooms[0]

    async def state(self, p: Person, expr: str):
        return await p.page.evaluate(
            f"async () => {{ const {{ S }} = await import('/g/pandemic/static/store.js'); return {expr}; }}"
        )

    # ------------------------------------------------------------------ the walk
    async def run(self) -> None:
        OUT.mkdir(parents=True, exist_ok=True)
        anna = await self.person("Anna", 1440, 900)
        boris = await self.person("Boris", 390, 844, phone=True)
        carl = await self.person("Carl", 1024, 768)
        await self.home_and_create(anna)
        code = await self.lobby_host(anna)
        await self.join_by_code(boris, code)
        await self.join_by_link(carl, code)
        await self.lobby_together(anna, boris, carl)
        await self.start(anna, boris, carl)
        await self.in_game_basics(anna, boris, carl)
        await self.play_game(anna, boris, carl)
        await self.after_game(anna, boris, carl)
        self.check_clean("the end")

    async def home_and_create(self, anna: Person) -> None:
        """The room page creates rooms now; open a Pandemic table straight away and arrive by its link."""
        page = anna.page
        await page.goto(self.base + "/")
        code = await page.evaluate(
            "fetch('/g/pandemic/api/rooms', {method: 'POST'}).then((r) => r.json()).then((j) => j.room)"
        )
        await page.goto(f"{self.base}/g/pandemic/r/{code}")
        await page.wait_for_selector("#ask-name")
        await self.shot(anna, "ask-name-host")
        await page.keyboard.type("Annx")
        await page.keyboard.press("Backspace")
        await page.keyboard.type("a")
        assert await page.locator("#ask-name").input_value() == "Anna"
        await page.keyboard.press("Enter")
        await page.wait_for_selector("#lobby", timeout=8000)
        assert "/r/" in page.url, page.url
        self.check_clean("home")

    async def _gone(self, p: Person, sel: str) -> bool:
        return await p.page.locator(sel).count() == 0

    async def lobby_host(self, anna: Person) -> str:
        page = anna.page
        code = (await self.text(anna, ".room b")).strip()
        assert len(code) >= 4, code
        await self.has_text(anna, "#seats", "Anna", "sees herself seated")
        await self.has_text(anna, "#seats .seat", "host", "is the host")
        # chat with Enter
        await self.type_into(anna, "#lobby-chat-in", "hello team, d f c s are letters not shortcuts")
        await page.keyboard.press("Enter")
        await self.has_text(anna, "#lobby-log", "hello team", "lobby chat shows her message")
        assert await page.locator("#lobby-chat-in").input_value() == ""
        # rename: the field is preselected, typing replaces it; Escape cancels a second dialog
        await page.click("#rename-btn")
        await page.wait_for_selector("#rename-in")
        await page.keyboard.type("Anya")
        await page.keyboard.press("Enter")
        await self.has_text(anna, "#seats", "Anya", "rename shows in the seat")
        await page.click("#rename-btn")
        await page.wait_for_selector("#rename-in")
        await page.keyboard.press("Escape")
        await self.until(lambda: self._gone(anna, ".modal"), "rename dialog closes on Escape")
        await self.has_text(anna, "#seats", "Anya", "Escape keeps the name")
        anna.name = "Anya"
        # copy invite link
        await page.click("#copy-btn")
        clip = await page.evaluate("navigator.clipboard.readText()")
        assert clip.endswith(f"/r/{code}"), clip
        await self.shot(anna, "lobby")
        self.check_clean("lobby (host)")
        return code

    async def join_by_code(self, boris: Person, code: str) -> None:
        """Joining with a code happens on the room page now; Boris types the table link instead."""
        page = boris.page
        await page.goto(f"{self.base}/g/pandemic/r/{code.lower()}")
        await page.wait_for_selector("#ask-name")
        await page.keyboard.type("Boris")
        await page.keyboard.press("Enter")
        await page.wait_for_selector("#lobby", timeout=8000)
        await self.has_text(boris, "#seats", "Boris", "sees himself seated")
        await self.has_text(self.people[0], "#seats", "Boris", "host sees Boris arrive")
        # chat with the send button
        await self.type_into(boris, "#lobby-chat-in", "hi from my phone")
        await page.click("#lobby-chat button")
        await self.has_text(self.people[0], "#lobby-log", "hi from my phone", "host reads Boris' chat")
        # host-only controls are disabled for him
        assert await page.locator("#diffs .opt[disabled]").count() == 3
        assert await page.locator("#start-btn").count() == 0
        await self.shot(boris, "lobby-phone")
        self.check_clean("join by code")

    async def join_by_link(self, carl: Person, code: str) -> None:
        page = carl.page
        await page.goto(f"{self.base}/g/pandemic/r/{code}")
        await page.wait_for_selector("#ask-name")
        await self.shot(carl, "ask-name")
        await page.keyboard.type("Carl")  # the field has focus
        assert await page.locator("#ask-name").input_value() == "Carl"
        await page.keyboard.press("Enter")
        await page.wait_for_selector("#lobby", timeout=8000)
        await self.has_text(carl, "#seats", "Carl", "Carl is seated on arrival")
        await page.click("#stand-btn")
        await self.has_text(carl, "#watchers", "Carl (you)", "Carl watches")
        await self.has_text(self.people[0], "#watchers", "Carl", "host sees Carl watching")
        self.check_clean("join by link")

    async def lobby_together(self, anna: Person, boris: Person, carl: Person) -> None:
        a = anna.page
        for sel in (
            '#diffs .opt[data-n="4"]',
            '#hand-opts .opt[data-v="closed"]',
            '#role-opts .opt[data-v="choose"]',
            '#speed-opts .opt[data-v="fast"]',
        ):
            await a.click(sel)
            await self.until(lambda s=sel: self._pressed(boris, s), f"Boris sees {sel} selected")
        if not self.closed:
            await a.click('#hand-opts .opt[data-v="open"]')
            await self.until(lambda: self._pressed(boris, '#hand-opts .opt[data-v="open"]'), "open hands")
        # roles: Anna takes the Medic, Boris can't, so he takes the Scientist
        await a.click("#seats .role-pick:not(:disabled)")
        await a.click('#menu [data-role="medic"]')
        await self.has_text(anna, "#seats", "Medic", "Anna plays the Medic")
        await boris.page.click("#seats .role-pick:not(:disabled)")
        assert await boris.page.locator('#menu [data-role="medic"][disabled]').count() == 1
        await boris.page.click('#menu [data-role="scientist"]')
        await self.has_text(anna, "#seats", "Scientist", "Boris plays the Scientist")
        # bots: add, remove, add again
        await a.click('#seats [data-bot="rookie"]')
        await self.has_text(anna, "#seats", "Rookie", "a Rookie joins")
        await a.click('#seats [data-remove="2"]')
        await self.until(lambda: self._gone(anna, '#seats [data-remove="2"]'), "the Rookie leaves")
        await a.click('#seats [data-bot="expert"]')
        await self.has_text(carl, "#seats", "Expert", "Carl sees the Expert bot")
        await self.shot(anna, "lobby-ready")
        await self.shot(boris, "lobby-ready-phone")
        self.check_clean("lobby settings")

    async def _pressed(self, p: Person, sel: str) -> bool:
        return await p.page.locator(sel).get_attribute("aria-pressed") == "true"

    async def start(self, anna: Person, boris: Person, carl: Person) -> None:
        await anna.page.click("#start-btn")
        for p in (anna, boris, carl):
            await p.page.wait_for_selector("#game #dock", timeout=8000)
        room = self.room()
        assert room.game is not None
        assert room.game.roles[0].value == "medic" and room.game.roles[1].value == "scientist", room.game.roles
        # hidden information
        hands = await self.state(anna, "S.state.game.players.map((p) => p.hand)")
        if self.closed:
            assert hands[0] is not None and hands[1] is None and hands[2] is None, hands
            watch = await self.state(carl, "S.state.game.players.map((p) => p.hand)")
            assert all(h is None for h in watch), watch
        else:
            assert all(h is not None for h in hands)
        assert await carl.page.locator("#dock .watch, #dock").count()
        await self.shot(anna, "game-start")
        await self.shot(boris, "game-start-phone")
        await self.shot(carl, "game-start-watch")
        self.check_clean("start")

    async def in_game_basics(self, anna: Person, boris: Person, carl: Person) -> None:
        a = anna.page
        # chat letters must not trigger shortcuts
        await self.type_into(anna, "#chat-in", "dfcs btku zpn ? +-0")
        assert await a.locator("#mode-hint.hidden").count() == 1, "a shortcut fired while typing in the chat"
        assert await a.locator(".modal").count() == 0
        await a.keyboard.press("Enter")
        await self.has_text(anna, "#log", "dfcs btku", "chat lands in the game log")
        # Boris on the phone: unread badge, open the panel, read, close with Escape
        await self.until(lambda: self._count(boris, "#team-btn .badge"), "Boris gets an unread badge")
        await boris.page.click("#team-btn")
        await self.has_text(boris, "#log", "dfcs btku", "Boris reads the chat")
        await self.type_into(boris, "#chat-in", "ok!")
        await boris.page.keyboard.press("Enter")
        await self.has_text(anna, "#log", "ok!", "Anna reads Boris")
        await boris.page.keyboard.press("Escape")
        await self.until(lambda: self._gone(boris, "#side.open"), "the panel closes on Escape")
        # a quick reaction
        await a.click("#react-btn")
        await a.click("#react button >> nth=0")
        await self.until(lambda: self._count(boris, "#reactions .reaction"), "Boris sees the reaction")
        # help and menu
        await a.keyboard.press("?")
        await a.wait_for_selector(".modal")
        await a.keyboard.press("Escape")
        await self.until(lambda: self._gone(anna, ".modal"), "help closes")
        await a.click("#menu-btn")
        await a.click('#menu [data-m="stats"]')
        await a.wait_for_selector(".modal")
        await a.keyboard.press("Escape")
        await a.click("#menu-btn")
        await a.click('#menu [data-m="sound"]')
        # a player card opens its city; clicking a player shows the role
        await a.click("#team .pl >> nth=1")
        await a.wait_for_selector("#sheet:not(.hidden)")
        await self.has_text(anna, "#sheet", "Scientist", "Boris' role sheet")
        await a.keyboard.press("Escape")
        await self.map_gestures(anna, boris)
        # keyboard shortcuts on the current human's turn
        room = self.room()
        cur = room.game.current
        if cur in (0, 1):
            p = (anna, boris)[cur]
            await p.page.keyboard.press("Escape")
            await p.page.locator("#map").click(position={"x": 5, "y": 5})
            await p.page.keyboard.press("d")
            await self.until(lambda: self._gone(p, "#mode-hint.hidden"), "D starts driving")
            await p.page.keyboard.press("Escape")
            await self.until(lambda: self._count(p, "#mode-hint.hidden"), "Escape cancels")
        self.check_clean("in-game basics")

    async def view_width(self, p: Person) -> float:
        return float((await p.page.locator("#map").get_attribute("viewBox")).split()[2])

    async def map_gestures(self, anna: Person, boris: Person) -> None:
        # phone: pinch out zooms in, pinch in zooms out (two real touch points through CDP)
        page = boris.page
        if await page.locator("#ok-btn").count():
            await page.locator("#ok-btn").tap()  # the infection summary covers the map on a phone
        box = await page.locator("#map").bounding_box()
        cx, cy = box["x"] + box["width"] / 2, box["y"] + box["height"] / 2
        cdp = await page.context.new_cdp_session(page)

        async def pinch(d0: float, d1: float) -> None:
            def pts(d: float) -> list[dict]:
                return [{"x": cx - d, "y": cy, "id": 1}, {"x": cx + d, "y": cy, "id": 2}]

            await cdp.send("Input.dispatchTouchEvent", {"type": "touchStart", "touchPoints": pts(d0)})
            for k in range(1, 9):
                d = d0 + (d1 - d0) * k / 8
                await cdp.send("Input.dispatchTouchEvent", {"type": "touchMove", "touchPoints": pts(d)})
            await cdp.send("Input.dispatchTouchEvent", {"type": "touchEnd", "touchPoints": []})
            await page.wait_for_timeout(100)

        w0 = await self.view_width(boris)
        await pinch(30, 120)
        w1 = await self.view_width(boris)
        assert w1 < w0 * 0.6, f"pinch out should zoom in: {w0} -> {w1}"
        await pinch(120, 30)
        w2 = await self.view_width(boris)
        assert w2 > w1 * 1.6, f"pinch in should zoom out: {w1} -> {w2}"
        await page.locator("#zfit").tap()
        # a tap on a city right after a pinch opens it
        city = "atl"
        await page.evaluate("async (id) => (await import('/g/pandemic/static/board.js')).ensureVisible(id)", city)
        await page.locator(f'#map .city[data-id="{city}"] .node').tap()
        await page.wait_for_selector("#pop:not(.hidden)")
        await self.has_text(boris, "#pop", "Atlanta", "the tapped city opens")
        await page.locator("#pop .icon-btn").tap()
        await self.shot(boris, "after-pinch-phone")
        # desktop: drag the map and let go outside it, then click a city: the click must not be swallowed
        a = anna.page
        abox = await a.locator("#map").bounding_box()
        await a.mouse.move(abox["x"] + abox["width"] / 2, abox["y"] + abox["height"] / 2)
        await a.mouse.down()
        await a.mouse.move(abox["x"] + abox["width"] / 2 + 80, abox["y"] + abox["height"] - 5, steps=6)
        await a.mouse.move(abox["x"] + abox["width"] / 2 + 90, abox["y"] + abox["height"] + 60, steps=4)
        await a.mouse.up()
        await a.locator("#zfit").click()
        await a.wait_for_timeout(400)
        await a.locator('#map .city[data-id="lon"] .node').click()
        await self.has_text(anna, "#pop", "London", "a click after a drag opens the city")
        await a.keyboard.press("Escape")
        # mouse wheel zooms
        w0 = await self.view_width(anna)
        await a.mouse.move(abox["x"] + abox["width"] / 2, abox["y"] + abox["height"] / 2)
        await a.mouse.wheel(0, -300)
        await self.until(lambda: self._narrower(anna, w0), "the wheel zooms in")
        await a.locator("#zfit").click()
        self.check_clean("map gestures")

    async def _narrower(self, p: Person, w: float) -> bool:
        return await self.view_width(p) < w

    async def _count(self, p: Person, sel: str) -> bool:
        return await p.page.locator(sel).count() > 0

    async def play_game(self, anna: Person, boris: Person, carl: Person) -> None:
        room = self.room()
        lock = asyncio.Lock()
        checks = []
        for seat, p in enumerate((anna, boris)):
            c = Check(p.page, room, OUT, lock, touch=p is boris)
            c.seat = seat
            c.errors, c.toasts = p.errors, p.toasts
            checks.append(c)
        # half way: Boris reloads his page (reconnect) and Carl's tablet drops and comes back
        await asyncio.gather(*(c.play(stop_after_turn=6) for c in checks))
        if room.status == "playing":
            await boris.page.reload()
            await boris.page.wait_for_selector("#game #dock", timeout=8000)
            await carl.page.reload()
            await carl.page.wait_for_selector("#game #dock", timeout=8000)
            await self.shot(boris, "after-reload-phone")
            await asyncio.gather(*(c.play() for c in checks))
        for p in (anna, boris, carl):
            await p.page.wait_for_selector(".over-hero", timeout=10000)
        res = room.game.result
        print(f"game: {'won' if res.won else 'lost (' + res.reason + ')'} on turn {res.turn}")
        for c, p in zip(checks, (anna, boris), strict=True):
            print(f"  {p.name}: " + ", ".join(f"{k} {v}" for k, v in sorted(c.counts.items())))
        await self.shot(anna, "over")
        await self.shot(boris, "over-phone")
        await self.shot(carl, "over-watch")
        self.check_clean("the game")

    async def after_game(self, anna: Person, boris: Person, carl: Person) -> None:
        room = self.room()
        # "Look at the board" closes the result; Boris can still read the board
        await boris.page.click(".modal [data-close]")
        await self.until(lambda: self._gone(boris, ".over-hero"), "the result closes")
        # play again
        await anna.page.click("#over-again")
        await self.until(lambda: room.status == "playing", "a new game starts")
        for p in (anna, boris, carl):
            await self.until(lambda p=p: self._gone(p, ".over-hero"), f"{p.name} leaves the result")
            await p.page.wait_for_selector("#game #dock")
        # back to the lobby (the host confirms ending the game)
        await anna.page.click("#menu-btn")
        await anna.page.click('#menu [data-m="lobby"]')
        await anna.page.click(".modal .btn.primary")
        for p in (anna, boris, carl):
            await p.page.wait_for_selector("#lobby", timeout=8000)
        await self.has_text(boris, "#seats", "Anya", "everyone is back in the lobby")
        # Boris goes to the room page's start screen and keeps his name (one identity for every game)
        await boris.page.goto(self.base + "/")
        await boris.page.wait_for_selector(".home-form input.text:not(.code)")
        assert await boris.page.locator(".home-form input.text:not(.code)").input_value() == "Boris"
        await self.shot(boris, "home-again")


@contextlib.asynccontextmanager
async def serving(app, port: int) -> AsyncIterator[str]:
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning"))
    task = asyncio.create_task(server.serve())
    while not server.started:
        await asyncio.sleep(0.05)
    try:
        yield f"http://127.0.0.1:{port}"
    finally:
        server.should_exit = True
        await task


async def main(args: argparse.Namespace) -> int:
    app = game_app("pandemic", delay_scale=0.03)
    async with serving(app, args.port) as base, async_playwright() as pw:
        browser = await pw.chromium.launch(executable_path=CHROME, headless=not args.headed)
        flow = Flow(browser, base, app, args.closed)
        started = time.monotonic()
        try:
            await flow.run()
        except Exception as e:
            for p in flow.people:
                await p.page.screenshot(path=str(OUT / f"fail-{p.name.lower()}.png"))
            where = next(
                (f"line {f.lineno}" for f in reversed(traceback.extract_tb(e.__traceback__)) if f.filename == __file__),
                "?",
            )
            print(f"FAILED at flow_check.py {where}: {type(e).__name__}: {str(e).splitlines()[0]}")
            return 1
        finally:
            await browser.close()
    print(f"flow ok in {time.monotonic() - started:.0f}s (screenshots in {OUT}/)")
    return 0


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--headed", action="store_true")
    ap.add_argument("--closed", action="store_true")
    ap.add_argument("--port", type=int, default=PORT)
    sys.exit(asyncio.run(main(ap.parse_args())))
