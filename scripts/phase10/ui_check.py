"""Play a whole game in a real browser, through clicks and drags only, and fail on any glitch.

uv run python scripts/ui_check.py [--size 1280x720] [--bots 2] [--phases 10] [--seed 1] [--headed]

The Pro bot's planner decides what the human seat should do; the script then does it the way a player would:
click the deck or the discard, select cards in the hand, stage them with the "+ Set of 3" buttons or the slots,
lay the phase down, hit groups on the table, pick a Skip target, and press Ready between hands. Along the way it
reorders the hand by dragging and uses both sort buttons. Any JS error, server-side error toast or a move that
doesn't land fails the run (a screenshot of the moment is saved in shots/).
"""

from __future__ import annotations

import argparse
import asyncio
import faulthandler
import sys
import time
from pathlib import Path

from playwright.async_api import Page, async_playwright

sys.path.insert(0, str(Path(__file__).parent))
from demo import TOKEN, serving
from shot import CHROME

from boardgames.testing import game_app
from phase10.bots import make_bot
from phase10.game.actions import Discard, DrawDeck, DrawDiscard, Hit, LayDown
from phase10.game.engine import Game, Step
from phase10.web.room import Room


class Failed(Exception):
    pass


class Check:
    def __init__(self, page: Page, room: Room, seat: int, out: Path) -> None:
        self.page, self.room, self.seat, self.out = page, room, seat, out
        self.brain = make_bot("pro", 7)
        self.errors: list[str] = []
        self.toasts: list[str] = []
        self.counts = {
            "draw_deck": 0,
            "draw_discard": 0,
            "lay_down": 0,
            "hit": 0,
            "discard": 0,
            "skip": 0,
            "drag": 0,
            "sort": 0,
        }

    @property
    def game(self) -> Game:
        assert self.room.game is not None
        return self.room.game

    def snap(self) -> tuple[object, ...]:
        g = self.game
        return (
            self.room.status,
            g.hand_no,
            g.turn,
            g.step,
            g.current,
            len(g.hands[self.seat]),
            len(g.groups),
            g.laid[self.seat],
        )

    async def fail(self, why: str) -> None:
        path = self.out / "ui-fail.png"
        await self.page.screenshot(path=str(path))
        dom = await self.page.evaluate(
            "() => ({focus: document.activeElement?.outerHTML.slice(0, 90), deck: document.querySelector('#deck')?.className,"
            " popover: !!document.querySelector('.popover'), modal: !!document.querySelector('.modal')})"
        )
        raise Failed(f"{why} (screenshot: {path}; moves so far: {self.counts}; dom {dom})")

    async def until(self, cond, what: str, timeout: float = 8.0) -> None:
        end = time.monotonic() + timeout
        while time.monotonic() < end:
            if self.errors:
                await self.fail(f"JS error: {self.errors[0]}")
            if cond():
                return
            await asyncio.sleep(0.03)
        await self.fail(f"timed out waiting for {what}")

    async def changed(self, before: tuple[object, ...], what: str) -> None:
        await self.until(lambda: self.snap() != before, what)
        await self.settle()

    async def settle(self) -> None:
        """Wait until the browser has rendered the latest state."""
        seq = self.room.seq
        await self.page.wait_for_function("(seq) => window.__p10seq >= seq", arg=seq, timeout=8000)
        if self.toasts:
            await self.fail(f"error toast: {self.toasts[0]}")

    # -------------------------------------------------------------- primitives
    async def click_card(self, cid: int) -> None:
        card = self.page.locator(f'.hand > .card[data-id="{cid}"]')
        await card.click(position={"x": 9, "y": 30})

    async def select(self, ids: list[int]) -> None:
        await self.page.keyboard.press("Escape")
        for cid in ids:
            await self.click_card(cid)
        n = await self.page.locator(".hand > .card.selected").count()
        if n != len(ids):
            await self.fail(f"selected {n} cards, wanted {len(ids)}")

    async def click(self, selector: str) -> None:
        el = self.page.locator(selector).first
        await el.click()

    # -------------------------------------------------------------- moves
    async def draw(self, action: DrawDeck | DrawDiscard) -> None:
        before = self.snap()
        if isinstance(action, DrawDeck):
            await self.click("#deck") if self.counts["draw_deck"] % 3 else await self.page.keyboard.press("d")
            self.counts["draw_deck"] += 1
        else:
            await self.click("#discard")
            self.counts["draw_discard"] += 1
        await self.changed(before, "the draw")

    async def lay_down(self, action: LayDown) -> None:
        reqs = self.game.view(self.seat).reqs
        for i, spec in enumerate(action.groups):
            if spec.kind != reqs[i].kind:
                await self.fail(f"group {i} is a {spec.kind}, phase wants {reqs[i].kind}")
            await self.select(list(spec.cards))
            twin = any(j != i and r == reqs[i] for j, r in enumerate(reqs))
            if i % 2 == 0 and not twin:
                r = reqs[i]
                label = f"{r.size} of one color" if r.kind == "color" else f"{r.kind.value.capitalize()} of {r.size}"
                await self.click(f'.acts .btn.stage:has-text("{label}")')
            else:
                await self.click(f'.slot-box[data-slot="{i}"]')
            if spec.kind.value == "run" and await self.page.locator(".popover").count():
                n = len(spec.cards)
                await self.click(f'.popover .btn:has-text("{spec.low}–{spec.low + n - 1}")')
            if not await self.page.locator(f'.slot-box.filled[data-slot="{i}"]').count():
                await self.fail(f"slot {i} did not take the cards {spec.cards}")
        before = self.snap()
        await self.click(".acts .btn.lay")
        await self.changed(before, "laying down")
        if not self.game.laid[self.seat]:
            await self.fail("the phase was not laid down")
        self.counts["lay_down"] += 1

    async def hit(self, action: Hit) -> None:
        await self.select([action.card])
        before = self.snap()
        await self.click(f'.group[data-group="{action.group}"]')
        if await self.page.locator(".popover").count():
            await self.click(f'.popover .btn:has-text("{"low end" if action.end == "low" else "high end"}")')
        await self.changed(before, "the hit")
        self.counts["hit"] += 1

    async def discard(self, action: Discard) -> None:
        await self.select([action.card])
        before = self.snap()
        via_pile = self.counts["discard"] % 2 == 1
        await self.click("#discard" if via_pile else ".acts .discard-btn")
        if action.target is not None and len(self.game.options(self.seat)["skip_targets"]) > 1:
            name = self.room.seats[action.target].name
            await self.page.locator(".popover .skip-target", has_text=name).first.click()
        if action.target is not None:
            self.counts["skip"] += 1
        await self.changed(before, "the discard")
        self.counts["discard"] += 1

    # -------------------------------------------------------------- hand order
    async def hand_ids(self) -> list[int]:
        return [
            int(x) for x in await self.page.locator(".hand > .card").evaluate_all("els => els.map(e => e.dataset.id)")
        ]

    async def drag_reorder(self) -> None:
        ids = await self.hand_ids()
        if len(ids) < 3:
            return
        await self.page.wait_for_function(
            "() => !document.getAnimations().some((a) => a.effect?.getTiming().iterations !== Infinity && a.playState === 'running')",
            timeout=8000,
        )
        src = self.page.locator(f'.hand > .card[data-id="{ids[0]}"]')
        dst = self.page.locator(f'.hand > .card[data-id="{ids[-1]}"]')
        a, b = await src.bounding_box(), await dst.bounding_box()
        assert a and b
        await self.page.mouse.move(a["x"] + 10, a["y"] + 30)
        await self.page.mouse.down()
        for k in range(1, 13):
            await self.page.mouse.move(a["x"] + 10 + (b["x"] + b["width"] - a["x"]) * k / 12, a["y"] + 30)
            await asyncio.sleep(0.015)
        await self.page.mouse.up()
        await self.until(
            lambda: [c.id for c in self.game.hands[self.seat]][-1] == ids[0],
            f"card {ids[0]} to land last in {ids}, dom now {await self.hand_ids()}",
        )
        after = await self.hand_ids()
        if after[-1] != ids[0] or sorted(after) != sorted(ids):
            await self.fail(f"drag reorder went wrong: {ids} -> {after}")
        self.counts["drag"] += 1

    async def sort(self, how: str) -> None:
        if len(self.game.hands[self.seat]) < 2:
            return
        await self.click(
            ".hand-tools .btn:has-text('1–12')" if how == "value" else ".hand-tools .btn:has-text('Colors')"
        )
        await asyncio.sleep(0.15)
        hand = self.game.hands[self.seat]
        key = [(0, c.value if how == "value" else 0) if c.natural else (1 if c.wild else 2, 0) for c in hand]
        colors = [c.color for c in hand if c.natural]
        grouped = all(colors[i] == colors[i - 1] or colors[i] not in colors[:i] for i in range(1, len(colors)))
        if key != sorted(key) or (how == "color" and not grouped):
            await self.fail(f"hand not sorted by {how}: {[c.label() for c in hand]}")
        self.counts["sort"] += 1

    # -------------------------------------------------------------- the loop
    async def play(self) -> None:
        turns = 0
        while True:
            await self.settle()
            if self.room.status == "game_over":
                await self.page.wait_for_selector(".modal.result", timeout=8000)
                return
            g = self.game
            if g.step == Step.HAND_OVER:
                print(f"hand {g.hand_no} over: phases {g.phases} scores {g.scores}; {self.counts}", flush=True)
                ready = self.page.locator('.modal .btn:has-text("Ready for hand")')
                await ready.wait_for(timeout=8000)
                before = self.snap()
                await ready.click()
                await self.changed(before, "the next deal")
                continue
            if g.current != self.seat:
                await self.changed(self.snap(), "the bots")
                continue
            view = g.view(self.seat)
            action = self.brain.act(view)
            if g.step == Step.DRAW:
                turns += 1
                if turns % 4 == 1:
                    await self.drag_reorder()
                if turns % 4 == 2:
                    await self.sort("value" if turns % 8 == 2 else "color")
                await self.draw(action)  # type: ignore[arg-type]
            elif isinstance(action, LayDown):
                await self.lay_down(action)
            elif isinstance(action, Hit):
                await self.hit(action)
            elif isinstance(action, Discard):
                await self.discard(action)
            else:
                await self.fail(f"unexpected action {action}")


async def run(args: argparse.Namespace) -> int:
    out = Path("shots")
    out.mkdir(exist_ok=True)
    room = Room("UICHK", delay_scale=args.speed, seed=args.seed)
    me = room.join(TOKEN, "Dima")
    for key in ["pro", "regular", "rookie", "pro", "regular"][: args.bots]:
        room.handle(me.id, {"type": "add_bot", "bot": key})
    room.settings.last_phase = args.phases
    w, h = (int(v) for v in args.size.split("x"))
    async with serving(game_app("phase10"), room, args.port) as url, async_playwright() as pw:
        browser = await pw.chromium.launch(executable_path=CHROME, headless=not args.headed)
        page = await browser.new_page(viewport={"width": w, "height": h})
        await page.add_init_script(
            "window.__p10seq = 0; const W = window.WebSocket; window.WebSocket = class extends W { constructor(...a) { super(...a);"
            " this.addEventListener('message', (e) => { try { const m = JSON.parse(e.data); if (m.seq != null) setTimeout(() => (window.__p10seq = m.seq), 0); } catch {} }); } };"
        )
        check = Check(page, room, 0, out)
        page.on("pageerror", lambda e: check.errors.append(str(e)))
        page.on("console", lambda m: m.type == "error" and check.errors.append(m.text))
        await page.goto(url)
        await page.wait_for_selector(".lobby-grid, .lobby", timeout=8000)
        await page.locator('.btn:has-text("Deal")').first.click()
        await page.wait_for_selector(".hand > .card", timeout=8000)
        check.seat = room.seat_of(me.id) or 0
        await page.expose_function("__p10toast", lambda text: check.toasts.append(text))
        await page.evaluate(
            "new MutationObserver((ms) => { for (const m of ms) for (const n of m.addedNodes) if (n.classList?.contains('err')) window.__p10toast(n.textContent); })"
            ".observe(document.getElementById('toasts'), { childList: true })"
        )
        started = time.monotonic()
        try:
            await check.play()
        except Failed as e:
            print(f"FAILED: {e}")
            return 1
        finally:
            await page.screenshot(path=str(out / "ui-end.png"))
            await browser.close()
    res = room.game.result if room.game else None
    print(
        f"game over after {room.game.hand_no if room.game else '?'} hands in {time.monotonic() - started:.0f}s; winners {res and res.winners}"
    )
    print("moves:", ", ".join(f"{k} {v}" for k, v in check.counts.items()))
    if check.errors:
        print("JS errors:", check.errors)
        return 1
    return 0


def main() -> None:
    faulthandler.dump_traceback_later(1500, exit=True)
    ap = argparse.ArgumentParser()
    ap.add_argument("--size", default="1280x720")
    ap.add_argument("--bots", type=int, default=2)
    ap.add_argument("--phases", type=int, default=10)
    ap.add_argument("--seed", type=int, default=1)
    ap.add_argument("--speed", type=float, default=0.03, help="bot delay scale")
    ap.add_argument("--port", type=int, default=8777)
    ap.add_argument("--headed", action="store_true")
    sys.exit(asyncio.run(run(ap.parse_args())))


if __name__ == "__main__":
    main()
