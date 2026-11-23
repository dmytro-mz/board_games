"""Play whole games in a real browser, through clicks and keys only, and fail on any glitch.

uv run python scripts/ui_check.py [--size 1280x720] [--bots 2] [--seed 1] [--games 1] [--closed] [--headed]

The Expert planner decides what the human seat should do; the script then does it the way a player would: open a
city on the map (keyboard focus + Enter) and pick a move in its popover, or use the action buttons and click a
highlighted city, share and cure in their dialogs, play event cards from the hand, discard in the hand-limit
dialog, arrange the Forecast with the arrow buttons, draw and continue from the dock and the resolve panel.
Any JS error, server-side error toast or a move that doesn't land fails the run (a screenshot is saved in shots/).
"""

from __future__ import annotations

import argparse
import asyncio
import faulthandler
import sys
import time
from pathlib import Path

from playwright.async_api import Locator, Page, async_playwright
from playwright.async_api import TimeoutError as PlaywrightTimeout

sys.path.insert(0, str(Path(__file__).parent))
from demo import TOKEN, serving
from shot import CHROME

from boardgames.testing import game_app
from pandemic.bots import make_bot
from pandemic.game import actions as A
from pandemic.game.engine import Game, View
from pandemic.game.model import CITIES, EVENT_NAMES, EventCard
from pandemic.web.room import Room

EVENT_CARD = {
    A.Airlift: "airlift",
    A.GovernmentGrant: "grant",
    A.OneQuietNight: "quiet",
    A.Forecast: "forecast",
    A.ResilientPopulation: "resilient",
}


class Failed(Exception):
    pass


# window.__seq follows the rendered state; error toasts are reported to window.__toast (survives reloads)
INIT_JS = """
window.__seq = 0;
const W = window.WebSocket;
window.WebSocket = class extends W { constructor(...a) { super(...a);
  this.addEventListener('message', (e) => { try { const m = JSON.parse(e.data); if (m.seq != null) setTimeout(() => (window.__seq = m.seq), 0); } catch {} }); } };
document.addEventListener('DOMContentLoaded', () => new MutationObserver((ms) => {
  for (const m of ms) for (const n of m.addedNodes) if (n.classList?.contains('err') && window.__toast) window.__toast(n.textContent);
}).observe(document.getElementById('toasts'), { childList: true }));
"""


async def instrument(page: Page, errors: list[str], toasts: list[str]) -> None:
    await page.add_init_script(INIT_JS)
    await page.expose_function("__toast", lambda text: toasts.append(text))
    page.on("pageerror", lambda e: errors.append(str(e)))
    page.on("console", lambda m: m.type == "error" and errors.append(m.text))


class Check:
    def __init__(
        self, page: Page, room: Room, out: Path, lock: asyncio.Lock | None = None, touch: bool = False
    ) -> None:
        self.page, self.room, self.out, self.touch = page, room, out, touch
        self.lock = lock or asyncio.Lock()  # shared by several humans so their moves don't race
        self.seat = 0
        self.brain = make_bot("expert", 7)
        self.errors: list[str] = []
        self.toasts: list[str] = []
        self.counts: dict[str, int] = {}
        self.n = 0

    @property
    def game(self) -> Game:
        assert self.room.game is not None
        return self.room.game

    def count(self, key: str) -> None:
        self.counts[key] = self.counts.get(key, 0) + 1

    async def fail(self, why: str) -> None:
        path = self.out / "ui-fail.png"
        await self.page.screenshot(path=str(path))
        g = self.game
        raise Failed(
            f"{why} (screenshot: {path}; step {g.step} turn {g.turn} current {g.current} at {g.location}; "
            f"doing {getattr(self, 'doing', None)}; moves {self.counts})"
        )

    async def until(self, cond, what: str, timeout: float = 10.0) -> None:
        end = time.monotonic() + timeout
        while time.monotonic() < end:
            if self.errors:
                await self.fail(f"JS error: {self.errors[0]}")
            if self.toasts:
                await self.fail(f"error toast: {self.toasts[0]}")
            if cond():
                return
            await asyncio.sleep(0.03)
        await self.fail(f"timed out waiting for {what}")

    async def settle(self) -> None:
        """Wait until the browser has rendered the latest state."""
        seq = self.room.seq
        await self.page.wait_for_function("(seq) => window.__seq >= seq", arg=seq, timeout=10000)
        await asyncio.sleep(0.05)
        if self.toasts:
            await self.fail(f"error toast: {self.toasts[0]}")

    async def landed(self, before: int, what: str) -> None:
        await self.until(lambda: self.room.seq > before, what)
        await self.settle()

    async def press(self, loc: Locator, what: str) -> None:
        try:
            await (loc.tap(timeout=6000) if self.touch else loc.click(timeout=6000))
        except PlaywrightTimeout as e:
            log = [line.strip() for line in str(e).splitlines() if line.strip()][-4:]
            await self.fail(f"can't {'tap' if self.touch else 'click'} {what}: {' | '.join(log)}")

    async def click(self, selector: str) -> None:
        await self.press(self.page.locator(selector).first, selector)

    async def city(self, city: str) -> None:
        """Pick a city on the map: tap or click its dot (panned into view first), or keyboard focus + Enter."""
        self.cities = getattr(self, "cities", 0) + 1
        if not self.touch and self.cities % 2:
            await self.page.locator(f'#map .city[data-id="{city}"]').focus()
            await self.page.keyboard.press("Enter")
            return
        ok = self.page.locator("#resolve:not(.hidden) #ok-btn")
        if await ok.count() and await ok.is_visible():
            await self.press(ok, "OK under the turn summary")  # on a phone it covers the map; a player reads it first
        await self.page.evaluate("async (id) => (await import('/g/pandemic/static/board.js')).ensureVisible(id)", city)
        await self.press(self.page.locator(f'#map .city[data-id="{city}"] .node'), f"the {city} dot")

    async def open_city(self, city: str) -> None:
        await self.page.keyboard.press("Escape")
        await self.city(city)

    async def pick_pawn(self, pawn: int | None) -> None:
        if pawn is None or pawn == self.seat:
            if await self.page.locator(f'.pp[data-pawn="{self.seat}"]').count():
                await self.click(f'.pp[data-pawn="{self.seat}"]')
            return
        await self.click(f'.pp[data-pawn="{pawn}"]')

    # -------------------------------------------------------------- moves
    async def move(self, action: A.Action) -> None:
        kind = {A.Drive: "Drive / Ferry", A.DirectFlight: "Direct flight", A.CharterFlight: "Charter flight"}
        kind |= {A.ShuttleFlight: "Shuttle flight", A.Dispatch: "Dispatch", A.OpsFlight: "Station flight"}
        title = kind[type(action)]
        await self.pick_pawn(getattr(action, "pawn", None))
        mode = {A.Drive: "drive", A.DirectFlight: "direct", A.CharterFlight: "charter", A.ShuttleFlight: "shuttle"}
        before = self.room.seq
        self.n += 1
        if type(action) in mode and self.n % 2 == 0:
            # the action button, then the highlighted city
            await self.page.keyboard.press("Escape")
            await self.click(f'#dock .act[data-act="{mode[type(action)]}"]')
            await self.page.locator(f'#map .city.target[data-id="{action.to}"]').wait_for(
                state="attached", timeout=4000
            )
            await self.city(action.to)
            self.count(f"{mode[type(action)]} (button)")
        else:
            await self.open_city(action.to)
            await self.click(f'#pop .move-opt:has-text("{title}")')
            if isinstance(action, A.OpsFlight):
                await self.click(f'.modal .pcard[data-card="{action.card}"]')
                await self.click("#pick-ok")
            self.count(f"{title} (map)")
        await self.landed(before, title)
        pawn = getattr(action, "pawn", None)
        if self.game.location[self.seat if pawn is None else pawn] != action.to:
            await self.fail(f"{action} did not land")

    async def turn_action(self, action: A.Action) -> None:
        before = self.room.seq
        if isinstance(action, A.MOVES):
            await self.move(action)
            return
        if isinstance(action, A.Treat):
            here = self.game.location[self.seat]
            colors = [c for c, n in self.game.cubes[here].items() if n]
            if len(colors) > 1:
                await self.open_city(here)
                await self.click(f'#pop [data-treat="{action.color.value}"]')
            else:
                await self.click('#dock .act[data-act="treat"]')
            self.count("treat")
        elif isinstance(action, A.Build):
            await self.click('#dock .act[data-act="build"]')
            if action.remove:
                await self.click(f'.modal [data-st="{action.remove}"]')
            self.count("build")
        elif isinstance(action, (A.Give, A.Take)):
            await self.click('#dock .act[data-act="share"]')
            card = CITIES[action.card].name
            if isinstance(action, A.Give):
                text = f"Give {card} to {self.room.seats[action.to].name}"
            else:
                giver = self.room.seats[action.giver].name
                text = f"Take {card} from {giver}"
                if not self.room.open_hands and action.card != self.game.location[self.seat]:
                    text = f"Take another city card from {giver}"
            await self.click(f'.modal .move-opt:has-text("{text}")')
            if "another" in text:
                await self.click(f'.modal .ichip[data-id="{action.card}"]')
            self.count("share")
        elif isinstance(action, A.Cure):
            await self.click('#dock .act[data-act="cure"]')
            color = CITIES[action.cards[0]].color.value
            if await self.page.locator(f'.modal [data-col="{color}"]').count():
                await self.click(f'.modal [data-col="{color}"]')
            for c in action.cards:
                if await self.page.locator(f'.modal .pcard[data-card="{c}"][aria-pressed="false"]').count():
                    await self.click(f'.modal .pcard[data-card="{c}"]')
            await self.click("#pick-ok")
            self.count("cure")
        elif isinstance(action, A.TakeEvent):
            await self.click("#store-btn")
            await self.click(f'.modal .pcard[data-card="{action.card}"]')
            self.count("take event")
        elif isinstance(action, A.Pass):
            await self.click("#pass-btn")
            await self.click("#pass-btn")
            self.count("pass")
        else:
            await self.fail(f"unexpected turn action {action}")
        await self.landed(before, str(action))

    async def event(self, action: A.Action) -> None:
        card = EVENT_CARD[type(action)]
        before = self.room.seq
        await self.page.keyboard.press("Escape")
        if await self.page.locator(f'.modal [data-event="{card}"]').count():
            await self.click(f'.modal [data-event="{card}"]')
        elif await self.page.locator(f'#hand .pcard[data-card="{card}"]').count():
            await self.click(f'#hand .pcard[data-card="{card}"]')
        else:
            await self.click(f'[data-event="{card}"]')
        match action:
            case A.Airlift(pawn, to):
                if len(self.room.seats) > 1:
                    await self.click(f'.modal [data-p="{pawn}"]')
                await self.city(to)
            case A.GovernmentGrant(city, remove):
                await self.city(city)
                if remove:
                    await self.click(f'.modal [data-st="{remove}"]')
            case A.OneQuietNight() | A.Forecast():
                await self.click(".modal #ok")
            case A.ResilientPopulation(city):
                await self.click(f'.modal [data-id="{city}"]')
        self.count(EVENT_NAMES[EventCard(card)])
        await self.landed(before, str(action))

    async def discard(self) -> None:
        g = self.game.clone()
        cards: list[str] = []
        while g.over_limit() == self.seat:
            a = self.brain.act(g.view(self.seat, open_hands=True))
            if not isinstance(a, A.Discard):
                if not cards:
                    await self.event(a)
                    return
                a = A.Discard(EVENT_CARD[type(a)])  # one dialog discards all: drop the event it wanted to spend
            g.play(self.seat, a)
            cards.append(a.card)
        await self.page.locator(".modal .pick").wait_for(timeout=6000)
        for c in cards:
            await self.click(f'.modal .pcard[data-card="{c}"]')
        before = self.room.seq
        await self.click("#pick-ok")
        self.count("discard")
        await self.landed(before, "the discard")

    async def forecast(self, action: A.ForecastOrder) -> None:
        await self.page.locator(".fc-list").wait_for(timeout=6000)
        order = list(action.order)
        for i, want in enumerate(order):
            current = await self.page.locator(".fc-list .ichip").evaluate_all("els => els.map(e => e.dataset.id)")
            j = current.index(want)
            for k in range(j, i, -1):
                await self.click(f'.modal [data-up="{k}"]')
        current = await self.page.locator(".fc-list .ichip").evaluate_all("els => els.map(e => e.dataset.id)")
        if current != order:
            await self.fail(f"forecast order {current} != {order}")
        before = self.room.seq
        await self.click("#fc-ok")
        self.count("forecast order")
        await self.landed(before, "the forecast")

    # -------------------------------------------------------------- the loop
    async def play(self, stop_after_turn: int | None = None) -> None:
        while True:
            await self.settle()
            if self.room.status != "playing":
                await self.page.wait_for_selector(".over-hero", timeout=10000)
                return
            if stop_after_turn is not None and self.game.turn > stop_after_turn:
                return
            async with self.lock:
                await self.settle()
                before = self.room.seq
                acted = self.room.status == "playing" and await self.step()
            if not acted:
                await self.until(lambda b=before: self.room.seq > b or self.room.status != "playing", "the others", 60)

    async def step(self) -> bool:
        """Do this seat's next move if it has one (also an event out of turn); False if it waits for others."""
        g = self.game
        view = g.view(self.seat, open_hands=True)
        if g.waiting_for() != self.seat:
            react = self.brain.react(view)
            if react is not None and g.over_limit() is None and g.forecast is None:
                try:
                    g.clone().play(self.seat, react)
                except Exception:
                    react = None
            if react is None:
                return False
            self.doing = react
            step_was = self.room._step
            try:
                await self.event(react)
            except Failed:
                # at test speed a bot can resolve the step before the card is picked; the server says why
                if self.room._step == step_was or not self.toasts:
                    raise
                self.toasts.clear()
                self.count("event too late")
                await self.page.keyboard.press("Escape")
            return True
        await self.own_move(g, view)
        return True

    async def own_move(self, g: Game, view: View) -> None:
        if g.forecast is not None:
            action = self.brain.act(view)
            assert isinstance(action, A.ForecastOrder)
            await self.forecast(action)
            return
        if g.over_limit() == self.seat:
            await self.discard()
            return
        action = self.doing = self.brain.act(view)
        if isinstance(action, A.EVENT_ACTIONS):
            await self.event(action)
        elif isinstance(action, A.DrawCards):
            before = self.room.seq
            await self.click("#draw-btn")
            self.count("draw")
            await self.landed(before, "the draw")
        elif isinstance(action, A.Continue):
            before = self.room.seq
            await self.click("#continue-btn")
            self.count("continue")
            await self.landed(before, "continue")
        else:
            await self.turn_action(action)
        if self.counts.get("undo", 0) < 3 and g.can_undo(self.seat) and self.n % 11 == 5:
            before = self.room.seq
            await self.click("#undo-btn")
            self.count("undo")
            await self.landed(before, "undo")


async def run(args: argparse.Namespace) -> int:
    out = Path("shots")
    out.mkdir(exist_ok=True)
    results = []
    w, h = (int(v) for v in args.size.split("x"))
    for gi in range(args.games):
        room = Room("UICHK", delay_scale=args.speed, seed=args.seed + gi)
        me = room.join(TOKEN, "Dima")
        room.handle(me.id, {"type": "sit"})
        for key in ["expert", "expert", "rookie"][: args.bots]:
            room.handle(me.id, {"type": "add_bot", "bot": key})
        room.handle(
            me.id, {"type": "settings", "changes": {"open_hands": not args.closed, "epidemics": args.epidemics}}
        )
        if args.role:
            room.handle(me.id, {"type": "settings", "changes": {"roles": "choose"}})
            room.handle(me.id, {"type": "pick_role", "seat": 0, "role": args.role})
        async with serving(game_app("pandemic"), room, args.port) as url, async_playwright() as pw:
            browser = await pw.chromium.launch(executable_path=CHROME, headless=not args.headed)
            page = await browser.new_page(viewport={"width": w, "height": h})
            check = Check(page, room, out)
            await instrument(page, check.errors, check.toasts)
            await page.goto(url)
            await page.wait_for_selector("#lobby", timeout=8000)
            await page.locator("#start-btn").click()
            await page.wait_for_selector("#game #dock", timeout=8000)
            check.seat = room.seat_of(me.id) or 0
            started = time.monotonic()
            try:
                await check.play()
            except Failed as e:
                print(f"FAILED: {e}")
                return 1
            finally:
                await page.screenshot(path=str(out / f"ui-end-{gi}.png"))
                await browser.close()
            res = room.game.result if room.game else None
            role = room.game.roles[check.seat].value if room.game else "?"
            results.append(res and res.won)
            print(
                f"game {gi + 1}: {'won' if res and res.won else f'lost ({res and res.reason})'} on turn {res and res.turn}"
                f" as {role} in {time.monotonic() - started:.0f}s; moves: "
                + ", ".join(f"{k} {v}" for k, v in sorted(check.counts.items())),
                flush=True,
            )
            if check.errors:
                print("JS errors:", check.errors)
                return 1
    print(f"{sum(bool(r) for r in results)} of {len(results)} won")
    return 0


def main() -> None:
    faulthandler.dump_traceback_later(3000, exit=True)
    ap = argparse.ArgumentParser()
    ap.add_argument("--size", default="1280x720")
    ap.add_argument("--bots", type=int, default=2)
    ap.add_argument("--seed", type=int, default=1)
    ap.add_argument("--games", type=int, default=1)
    ap.add_argument("--epidemics", type=int, default=4)
    ap.add_argument("--role", default=None, help="the human's role (e.g. dispatcher)")
    ap.add_argument("--closed", action="store_true")
    ap.add_argument("--speed", type=float, default=0.03, help="bot delay scale")
    ap.add_argument("--port", type=int, default=8777)
    ap.add_argument("--headed", action="store_true")
    sys.exit(asyncio.run(run(ap.parse_args())))


if __name__ == "__main__":
    main()
