"""Render the main screens at several resolutions; screenshot each and fail on any overflow.

uv run python scripts/sizes.py [--sizes 1920x1080,1280x720] [--stages lobby,play] [--bots 3] [--out shots/sizes]

Checks: no element listed in WATCH is wider than its box or sticks out of the window, the hand's cards stay inside
the window, and the buttons the player needs right now are visible without scrolling the page.
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

from playwright.async_api import async_playwright

sys.path.insert(0, str(Path(__file__).parent))
from demo import prepare, serving
from shot import CHROME

from boardgames.testing import game_app

SIZES = "1920x1080,1600x900,1440x900,1366x768,1280x720,1180x820,1024x768,900x600,820x1180,700x650,768x1024,600x900,390x844,360x640"
STAGES = "home,lobby,play,drawn,laid,handover,over"
WATCH = (
    ".topbar, .panel, .seat-row, .lobby-grid, .invite, .opp, .opps, .center, .mine, .mine-head, .dock, .dock-top, .status,"
    " .acts, .hand-row, .modal, .home-card, .group, .slot-box, .track, .banner, .mini-bar"
)

# Elements whose content is wider than their box, or that stick out of the window.
OVERFLOW_JS = """(sel) => {
  const out = [];
  const cls = (el) => (typeof el.className === "string" ? el.className.trim().split(/\\s+/) : []);
  const name = (el) => [el.tagName.toLowerCase(), ...cls(el)].join(".");
  for (const el of document.querySelectorAll(sel)) {
    const r = el.getBoundingClientRect();
    if (!r.width || getComputedStyle(el).visibility === "hidden") continue;
    if (el.closest("aside.side") && !el.closest("aside.side.open") && innerWidth <= 1100) continue;
    const [sw, cw] = [el.scrollWidth, el.clientWidth];
    if (sw > cw + 2 && !el.matches(".table-scroll")) out.push(`${name(el)} content ${sw}px > box ${cw}px`);
    const [left, right] = [Math.round(r.left), Math.round(r.right)];
    if (right > innerWidth + 1 || left < -1) out.push(`${name(el)} sticks out (${left}..${right} of ${innerWidth})`);
  }
  for (const c of document.querySelectorAll(".hand > .card")) {
    const r = c.getBoundingClientRect();
    if (r.right > innerWidth + 1 || r.left < -1 || r.bottom > innerHeight + 1) out.push(`hand card ${c.dataset.id} outside the window`);
  }
  for (const b of document.querySelectorAll(".dock .btn, .modal .actions .btn")) {
    const r = b.getBoundingClientRect();
    if (r.width && (r.bottom > innerHeight + 1 || r.top < 0)) out.push(`button "${b.textContent.trim()}" off screen`);
  }
  if (document.documentElement.scrollWidth > innerWidth + 1) out.push(`page scrolls sideways (${document.documentElement.scrollWidth}px)`);
  return out;
}"""


async def check(stage: str, sizes: list[tuple[int, int]], out: Path, port: int, bots: int) -> list[str]:
    room = prepare("play" if stage == "home" else stage, bots, 3)
    room.delay_scale = 1000.0  # freeze the bots while we look
    problems: list[str] = []
    async with serving(game_app("phase10"), room, port) as url, async_playwright() as pw:
        browser = await pw.chromium.launch(executable_path=CHROME)
        target = url.split("/g/")[0] + "/" if stage == "home" else url
        for w, h in sizes:
            page = await browser.new_page(viewport={"width": w, "height": h}, reduced_motion="reduce")
            errors: list[str] = []
            page.on("pageerror", lambda e, errors=errors: errors.append(str(e)))
            await page.goto(target)
            await page.wait_for_load_state("networkidle")
            await page.wait_for_timeout(900 if stage not in ("handover", "over") else 2200)
            await page.screenshot(path=str(out / f"{stage}-b{bots}-{w}x{h}.png"))
            found = errors + await page.evaluate(OVERFLOW_JS, WATCH)
            problems += [f"{stage} b{bots} {w}x{h}: {p}" for p in dict.fromkeys(found)]
            await page.close()
        await browser.close()
    return problems


async def run(args: argparse.Namespace) -> int:
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    sizes = [tuple(int(v) for v in s.split("x")) for s in args.sizes.split(",")]
    problems: list[str] = []
    port = args.port
    for bots in [int(b) for b in args.bots.split(",")]:
        for stage in args.stages.split(","):
            problems += await check(stage, sizes, out, port, bots)  # type: ignore[arg-type]
            port += 1
    for p in problems:
        print(p)
    print(f"{len(problems)} problem(s); screenshots in {out}")
    return 1 if problems else 0


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--sizes", default=SIZES)
    ap.add_argument("--stages", default=STAGES)
    ap.add_argument("--bots", default="3", help="comma-separated opponent counts, e.g. 1,3,5")
    ap.add_argument("--out", default="shots/sizes")
    ap.add_argument("--port", type=int, default=8790)
    sys.exit(asyncio.run(run(ap.parse_args())))


if __name__ == "__main__":
    main()
