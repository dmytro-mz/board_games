"""Play whole games at real bot speed with human-like pauses and record every visual glitch.

uv run python scripts/glitch_check.py [--games 3] [--bots 1] [--size 1440x900] [--touch] [--closed] [--role R]
                                      [--snap 5] [--speed 1.0] [--think 0.35]

The other browser checks turn animations off or speed bots up, which hides this kind of bug. Here bots play at the
table's real speed and the human (the Expert planner, through ui_check.Check) waits a moment before each click.

Records, per animation frame, the state of every floating panel (feed, resolve panel, popover, modal, mode hint,
toasts) and every CSS animation start. Reports:
- entry animations that replay on an element that was already shown (a re-render blink),
- panel states that lasted less than a few frames (a flicker),
- keyboard focus dropping to the page without any input,
- JS errors and error toasts.
`--snap N` also saves a screenshot every N seconds to shots/glitch/ to look through.
"""

from __future__ import annotations

import argparse
import asyncio
import itertools
import json
import random
import sys
import time
from pathlib import Path

from playwright.async_api import async_playwright

sys.path.insert(0, str(Path(__file__).parent))
from demo import TOKEN, serving
from shot import CHROME
from ui_check import Check, Failed, instrument

from boardgames.testing import game_app
from pandemic.web.room import Room

WATCH_JS = r"""
(() => {
  const G = (window.__glitch = { anims: [], states: [], inputs: [] });
  const T = () => Math.round(performance.now());
  const txt = (el) => (el?.textContent || '').replace(/\s+/g, ' ').trim().slice(0, 90);
  document.addEventListener('animationstart', (e) => {
    const el = e.target;
    let s = null;
    if (el.closest?.('#feed')) s = 'feed|' + e.animationName + '|' + (el.dataset?.id ? el.dataset.id + '|' : '') + txt(el);
    else if (el.closest?.('#toasts')) s = 'toast|' + txt(el);
    else if (el.classList?.contains('reaction')) s = null;
    else if (el.closest?.('#resolve, #pop, #modal-root, #mode-hint, #sheet, #menu, #bubble')) s = 'panel|' + e.animationName + '|' + txt(el).slice(0, 40);
    if (s) G.anims.push([T(), e.animationName, s]);
  }, true);
  for (const ev of ['pointerdown', 'keydown']) document.addEventListener(ev, () => G.inputs.push(T()), true);
  const vis = (sel) => { const el = document.querySelector(sel); if (!el || el.classList.contains('hidden')) return null; const r = el.getBoundingClientRect(); return r.width && r.height ? el : null; };
  let last = {};
  const probe = () => {
    const now = T();
    const cur = {};
    const res = vis('#resolve');
    cur.resolve = res && !res.classList.contains('picking') ? (res.classList.contains('left') ? 'L:' : 'R:') + txt(res.querySelector('h2')) : '';
    const pop = vis('#pop');
    cur.pop = pop ? txt(pop.querySelector('.pop-head b')) : '';
    const mr = document.querySelector('#modal-root');
    cur.modal = mr && mr.innerHTML ? txt(mr.querySelector('h2')) || 'modal' : '';
    const mh = vis('#mode-hint');
    cur.hint = mh ? txt(mh).slice(0, 30) : '';
    cur.feed = [...document.querySelectorAll('#feed .f')].map(txt).join(' / ');
    cur.toast = [...document.querySelectorAll('#toasts .toast')].map(txt).join(' / ');
    const ae = document.activeElement;
    cur.focus = !ae || ae === document.body ? 'BODY' : ae.id || ae.dataset?.id || ae.dataset?.card || ae.className?.baseVal || ae.className || ae.tagName;
    cur.dock = txt(document.querySelector('#dock .wait p, #dock .act-grid')).slice(0, 40);
    for (const k in cur) if (cur[k] !== last[k]) G.states.push([now, k, cur[k]]);
    last = cur;
    requestAnimationFrame(probe);
  };
  addEventListener('DOMContentLoaded', () => requestAnimationFrame(probe));
})();
"""


class Human(Check):
    """A Check that thinks a little before each click, like a person."""

    think = 0.35

    async def press(self, loc, what):
        await asyncio.sleep(self.think * (0.6 + random.random() * 0.8))
        await super().press(loc, what)


def analyse(data: dict, frame_ms: float = 120) -> list[str]:
    out: list[str] = []
    # 1. an entry animation that starts again on the same thing within its lifetime
    seen: dict[str, int] = {}
    replays: dict[str, int] = {}
    for t, _name, s in data["anims"]:
        life = {"feed": 9500, "toast": 3700}.get(s.split("|")[0], 3000)
        if s in seen and t - seen[s] < life:
            replays[s] = replays.get(s, 0) + 1
        else:
            seen[s] = t
    for s, n in sorted(replays.items(), key=lambda x: -x[1])[:12]:
        out.append(f"replayed animation x{n}: {s}")
    if len(replays) > 12:
        out.append(f"... and {len(replays) - 12} more replayed animations")
    # 2. a panel state shown for a moment and then gone again (not caused by our own input)
    inputs = data["inputs"]
    by: dict[str, list[tuple[int, str]]] = {}
    for t, k, v in data["states"]:
        by.setdefault(k, []).append((t, v))
    focus = by.get("focus", [])
    lost = [
        (t1, v0)
        for (_, v0), (t1, v1) in itertools.pairwise(focus)
        if v1 == "BODY" and v0 != "BODY" and not any(t1 - 1500 <= ti <= t1 + 50 for ti in inputs)
    ]
    if lost:
        out.append(f"focus dropped to the page {len(lost)}x without input, e.g. from {[v for _, v in lost[:5]]}")
    for k, seq in by.items():
        if k in ("toast", "focus"):
            continue
        for (_, v0), (t1, v1), (t2, v2) in zip(seq, seq[1:], seq[2:], strict=False):
            if not v1 or t2 - t1 >= frame_ms:
                continue
            near_input = any(t1 - 400 <= ti <= t2 + 50 for ti in inputs)
            if near_input:
                continue
            out.append(f"flicker {k}: {v0!r} -> {v1!r} ({t2 - t1}ms) -> {v2!r}")
    return out


async def one_game(args, gi: int) -> tuple[bool, list[str], str]:
    room = Room("GLTCH", delay_scale=args.speed, seed=args.seed + gi)
    me = room.join(TOKEN, "Dima")
    room.handle(me.id, {"type": "sit"})
    for key in ["expert", "expert", "rookie"][: args.bots]:
        room.handle(me.id, {"type": "add_bot", "bot": key})
    room.handle(me.id, {"type": "settings", "changes": {"open_hands": not args.closed, "epidemics": args.epidemics}})
    if args.role:
        room.handle(me.id, {"type": "settings", "changes": {"roles": "choose"}})
        room.handle(me.id, {"type": "pick_role", "seat": 0, "role": args.role})
    out = Path("shots/glitch") / f"{args.tag or args.port}-g{gi}"
    out.mkdir(parents=True, exist_ok=True)
    w, h = (int(v) for v in args.size.split("x"))
    async with serving(game_app("pandemic"), room, args.port) as url, async_playwright() as pw:
        browser = await pw.chromium.launch(executable_path=CHROME, headless=not args.headed)
        ctx = await browser.new_context(viewport={"width": w, "height": h}, has_touch=args.touch, is_mobile=args.touch)
        page = await ctx.new_page()
        check = Human(page, room, out, touch=args.touch)
        check.think = args.think
        await instrument(page, check.errors, check.toasts)
        await page.add_init_script(WATCH_JS)
        await page.goto(url)
        await page.wait_for_selector("#lobby", timeout=8000)
        await page.locator("#start-btn").click()
        await page.wait_for_selector("#game #dock", timeout=8000)
        check.seat = room.seat_of(me.id) or 0
        started = time.monotonic()
        problems: list[str] = []

        async def snaps() -> None:
            k = 0
            while True:
                await asyncio.sleep(args.snap)
                k += 1
                try:
                    await page.screenshot(path=str(out / f"t{k:03d}.png"))
                except Exception:
                    return

        snapper = asyncio.create_task(snaps()) if args.snap else None
        try:
            await check.play()
            await asyncio.sleep(1.5)
        except Failed as e:
            problems.append(f"FAILED: {e}")
        if snapper:
            snapper.cancel()
        data = await page.evaluate("window.__glitch")
        Path(out / "glitch.json").write_text(json.dumps(data))
        await page.screenshot(path=str(out / "end.png"))
        await browser.close()
    problems += analyse(data)
    problems += [f"JS error: {e}" for e in check.errors]
    res = room.game.result if room.game else None
    role = room.game.roles[check.seat].value if room.game else "?"
    summary = (
        f"game {gi + 1}: {'won' if res and res.won else f'lost ({res and res.reason})'} on turn {res and res.turn} as {role}"
        f" in {time.monotonic() - started:.0f}s; moves: "
        + ", ".join(f"{k} {v}" for k, v in sorted(check.counts.items()))
    )
    return bool(res and res.won), problems, summary


async def run(args) -> int:
    bad = 0
    for gi in range(args.games):
        _, problems, summary = await one_game(args, gi)
        print(summary, flush=True)
        for p in problems:
            print("   ", p, flush=True)
        bad += bool(problems)
    print(f"{bad} of {args.games} games had problems")
    return 1 if bad else 0


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--games", type=int, default=1)
    ap.add_argument("--bots", type=int, default=1)
    ap.add_argument("--size", default="1440x900")
    ap.add_argument("--seed", type=int, default=11)
    ap.add_argument("--epidemics", type=int, default=5)
    ap.add_argument("--role", default=None)
    ap.add_argument("--closed", action="store_true")
    ap.add_argument("--touch", action="store_true")
    ap.add_argument("--speed", type=float, default=1.0, help="bot delay scale (1 = real speed)")
    ap.add_argument("--think", type=float, default=0.35, help="seconds a human waits before a click")
    ap.add_argument("--port", type=int, default=8765)
    ap.add_argument("--headed", action="store_true")
    ap.add_argument("--tag", default="")
    ap.add_argument("--snap", type=float, default=0, help="screenshot every N seconds")
    sys.exit(asyncio.run(run(ap.parse_args())))


if __name__ == "__main__":
    main()
