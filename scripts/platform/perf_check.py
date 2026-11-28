"""Performance regression check: the key numbers of the server and the clients against budgets. Exits non-zero
when one is over. Run it after a change to the platform or a game client (about 6 minutes for everything).

  uv run python scripts/platform/perf_check.py [--client] [--server] [--games ttr,karak]

Budgets come from measurements (docs/performance.md); each has headroom so that noise doesn't fail it.
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).parent))
import bench_client
import bench_server
from bench_games import RECIPES

from boardgames.games import GAME_KEYS

# Client: CPU while nothing happens (ms of main-thread work per second), and what a warm reload costs.
LOBBY_IDLE_MS = 2.0
# Known: Karak's SVG ring and Avenue's clipped card glow repaint every frame; their cost depends on the board
# (measured Karak 97–180, Avenue 38–90 ms/s), see docs/performance.md §5.
TABLE_IDLE_MS = {
    "default": 5.0,
    "karak": 250.0,
    "avenue": 130.0,
    "codenames": 15.0,
    "pandemic": 20.0,
}  # Pandemic: periodic timers (~1/s), as before
WARM_REQUESTS = {"default": 5, "codenames": 10}  # page, config, game page, game config (+ picture deck revalidation)
WARM_304 = {"default": 0, "codenames": 6}
# Server: the longest the event loop is blocked by one callback (stalls every room), per game.
LOOP_BLOCK_MS = 40.0
SERVER_GAMES = ("ttr", "pandemic", "karak", "skyjo", "phase10", "lostcities")  # fast, deterministic bots


def pick(table: dict[str, float], key: str) -> float:
    return table.get(key, table["default"])


async def client(games: list[str]) -> list[str]:
    args = SimpleNamespace(idle=4.0, settle=6.0, play=2.0, long=0.0, net=None, load_only=False, delay_scale=1.0)
    failures = []
    async with bench_client.serve(1.0) as (base, hub), bench_client.async_playwright() as pw:
        for key in games:
            r = await bench_client.bench_game(pw, base, hub, key, (1440, 900), args)
            for settle in (20.0, 40.0):  # the bots were still moving: wait longer for the player's turn
                if r.get("table_idle", {}).get("events", 0) == 0:
                    break
                print(f"client {key:<11} bots still moving during the idle window; again with {settle:.0f} s to settle")
                r = await bench_client.bench_game(
                    pw, base, hub, key, (1440, 900), SimpleNamespace(**{**vars(args), "settle": settle})
                )
            lobby, warm = r["lobby_idle"]["cpu_ms_per_s"], r["warm"]
            table = r.get("table_idle", {}).get("cpu_ms_per_s", 0.0)
            moving = r.get("table_idle", {}).get("events", 0)
            checks = [
                (lobby <= LOBBY_IDLE_MS, f"lobby idle {lobby:.1f} ms/s (budget {LOBBY_IDLE_MS})"),
                (table <= pick(TABLE_IDLE_MS, key), f"table idle {table:.1f} ms/s (budget {pick(TABLE_IDLE_MS, key)})"),
                (
                    warm["network_requests"] <= pick(WARM_REQUESTS, key),
                    f"warm reload {warm['network_requests']} requests (budget {pick(WARM_REQUESTS, key)})",
                ),
                (
                    warm["revalidated_304"] <= pick(WARM_304, key),
                    f"warm reload {warm['revalidated_304']} revalidations (budget {pick(WARM_304, key)})",
                ),
                (not r["errors"], f"JavaScript errors: {r['errors'][:2]}"),
                (not moving, f"the table never went idle ({moving} events in the idle window)"),
            ]
            bad = [text for ok, text in checks if not ok]
            failures += [f"{key}: {text}" for text in bad]
            print(
                f"client {key:<11} {'ok' if not bad else 'OVER'}  lobby {lobby:.1f} · table {table:.1f} ms/s · "
                f"warm {warm['network_requests']} req / {warm['revalidated_304']}×304",
                flush=True,
            )
    return failures


def server(games: list[str]) -> list[str]:
    failures = []
    for key in games:
        if key not in SERVER_GAMES:
            continue
        r = asyncio.run(bench_server.play(key, RECIPES[key], min(2, RECIPES[key].max_humans), 1, 240))
        ok = r["done"] and r["cb_max_ms"] <= LOOP_BLOCK_MS
        print(
            f"server {key:<11} {'ok' if ok else 'OVER'}  longest loop block {r['cb_max_ms']:.1f} ms, "
            f"snapshot {r['build_us_avg']:.0f} µs, {r['wire_kb_per_player']:.0f} kB/player on the wire",
            flush=True,
        )
        if not ok:
            failures.append(
                f"{key}: event loop blocked {r['cb_max_ms']:.1f} ms (budget {LOOP_BLOCK_MS}) or game unfinished"
            )
    return failures


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--client", action="store_true")
    ap.add_argument("--server", action="store_true")
    ap.add_argument("--games", default=",".join(GAME_KEYS))
    args = ap.parse_args()
    both = not args.client and not args.server
    games = args.games.split(",")
    failures = []
    if args.server or both:
        failures += server(games)
    if args.client or both:
        failures += asyncio.run(client(games))
    if failures:
        print("\nover budget:\n  " + "\n  ".join(failures))
        sys.exit(1)
    print("\nall within budget")


if __name__ == "__main__":
    main()
