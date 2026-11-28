"""Markdown tables comparing two sets of benchmark results (the JSON files the bench_* scripts write).

uv run python scripts/platform/bench_report.py --dir tmp/bench --before base --after final
  reads server_<before>.json / server_<after>.json, client_<..>.json, load_<..>_tunnel.json, load_<..>_mix.json
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


def load(path: Path) -> list[dict[str, Any]] | None:
    return json.loads(path.read_text()) if path.exists() else None


def by(rows: list[dict[str, Any]], key: str) -> dict[Any, dict[str, Any]]:
    return {r[key]: r for r in rows}


def arrow(a: float, b: float, fmt: str = "{:.0f}") -> str:
    return f"{fmt.format(a)} → **{fmt.format(b)}**"


def server(before: list[dict[str, Any]], after: list[dict[str, Any]]) -> str:
    a, b = by(before, "game"), by(after, "game")
    out = [
        "| Game | Longest loop block (ms) | Blocks > 20 ms | Loop CPU per game (ms) | Snapshot build (µs) | Wire kB / player |",
        "|---|---|---|---|---|---|",
    ]
    for g in a:
        if g not in b:
            continue
        x, y = a[g], b[g]
        out.append(
            f"| {g} | {arrow(x['cb_max_ms'], y['cb_max_ms'], '{:.1f}')} | {x['cb_over_20ms']} → **{y['cb_over_20ms']}** "
            f"| {arrow(x['loop_cpu_ms'], y['loop_cpu_ms'])} | {x['build_us_avg']:.0f} / {y['build_us_avg']:.0f} "
            f"| {x['wire_kb_per_player']:.0f} / {y['wire_kb_per_player']:.0f} |"
        )
    return "\n".join(out)


def client(before: list[dict[str, Any]], after: list[dict[str, Any]]) -> str:
    a, b = by(before, "game"), by(after, "game")
    out = [
        "| Game | Idle lobby (ms CPU/s) | Idle table (ms CPU/s) | Play (ms CPU/s) | Frame avg / p95 (ms) | Warm reload: requests (304s) |",
        "|---|---|---|---|---|---|",
    ]
    for g in a:
        if g not in b:
            continue
        x, y = a[g], b[g]
        ti = lambda r: r.get("table_idle", {}).get("cpu_ms_per_s", 0.0)  # noqa: E731
        pl = lambda r: r.get("play", {})  # noqa: E731
        out.append(
            f"| {g} | {arrow(x['lobby_idle']['cpu_ms_per_s'], y['lobby_idle']['cpu_ms_per_s'], '{:.1f}')} "
            f"| {arrow(ti(x), ti(y), '{:.1f}')} | {arrow(pl(x).get('cpu_ms_per_s', 0), pl(y).get('cpu_ms_per_s', 0))} "
            f"| {pl(x).get('frame_avg_ms', 0):.1f}/{pl(x).get('frame_p95_ms', 0):.1f} → "
            f"{pl(y).get('frame_avg_ms', 0):.1f}/{pl(y).get('frame_p95_ms', 0):.1f} "
            f"| {x['warm']['network_requests']} ({x['warm']['revalidated_304']}) → "
            f"**{y['warm']['network_requests']} ({y['warm']['revalidated_304']})** |"
        )
    return "\n".join(out)


def leaks(after: list[dict[str, Any]]) -> str:
    out = [
        "| Game | JS heap after GC, start → end of 60 s fast play (MB) | DOM nodes start → end | After back to selection |",
        "|---|---|---|---|",
    ]
    for r in after:
        long, back = r.get("long"), r["after_back"]
        if not long:
            continue
        out.append(
            f"| {r['game']} | {long['heap_mb_start']:.1f} → {long['heap_mb_end']:.1f} | {long['nodes_start']:.0f} → "
            f"{long['nodes_end']:.0f} | {back['documents']:.0f} document, {back['nodes']:.0f} nodes, {back['heap_mb']:.1f} MB |"
        )
    return "\n".join(out)


def loads(before: list[dict[str, Any]], after: list[dict[str, Any]]) -> str:
    a, b = by(before, "game"), by(after, "game")
    out = [
        "| Game | Cold: game kB | Cold: shell + thumbnails kB | Cold load (ms) | Warm: requests (304s) | Warm load (ms) |",
        "|---|---|---|---|---|---|",
    ]
    for g in a:
        if g not in b:
            continue
        x, y = a[g], b[g]
        cx, cy, wx, wy = x["cold"], y["cold"], x["warm"], y["warm"]
        out.append(
            f"| {g} | {arrow(cx['kb_game'], cy['kb_game'])} | {arrow(cx['kb_shell'] + cx['kb_thumbs'], cy['kb_shell'] + cy['kb_thumbs'])} "
            f"| {arrow(x['room_load_ms'] + x['game_load_ms'], y['room_load_ms'] + y['game_load_ms'])} "
            f"| {wx['network_requests']} ({wx['revalidated_304']}) → **{wy['network_requests']} ({wy['revalidated_304']})** "
            f"| {arrow(x['warm_load_ms'], y['warm_load_ms'])} |"
        )
    return "\n".join(out)


def capacity(before: list[dict[str, Any]], after: list[dict[str, Any]]) -> str:
    a, b = by(before, "rooms"), by(after, "rooms")
    out = [
        "| Rooms (×4 clients) | Message RTT p50 / p99 / max (ms) | Server CPU (% of a core) | Memory (MB) | Messages/s |",
        "|---|---|---|---|---|",
    ]
    for n in a:
        if n not in b:
            continue
        x, y = a[n], b[n]
        out.append(
            f"| {n} | {x['rtt_p50_ms']:.1f} / {x['rtt_p99_ms']:.1f} / {x['rtt_max_ms']:.0f} → "
            f"**{y['rtt_p50_ms']:.1f} / {y['rtt_p99_ms']:.1f} / {y['rtt_max_ms']:.0f}** | {x['cpu_pct']:.0f} → {y['cpu_pct']:.0f} "
            f"| {x['rss_mb']:.0f} → {y['rss_mb']:.0f} | {x['msgs_per_s']:.0f} → {y['msgs_per_s']:.0f} |"
        )
    return "\n".join(out)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dir", type=Path, default=Path("tmp/bench"))
    ap.add_argument("--before", default="base")
    ap.add_argument("--after", default="final")
    args = ap.parse_args()
    d, x, y = args.dir, args.before, args.after
    sections = [
        ("Server: headless bot games", server, f"server_{x}.json", f"server_{y}.json"),
        ("Server: capacity", capacity, f"load_{x}_mix.json", f"load_{y}_mix.json"),
        ("Client: CPU and frames", client, f"client_{x}.json", f"client_{y}.json"),
        (
            "Client: loading over a tunnel (60 ms RTT, 9 Mbit/s)",
            loads,
            f"load_{x}_tunnel.json",
            f"load_{y}_tunnel.json",
        ),
    ]
    for title, fn, fa, fb in sections:
        a, b = load(d / fa), load(d / fb)
        if a and b:
            print(f"### {title}\n\n{fn(a, b)}\n")
    after = load(d / f"client_{y}.json")
    if after:
        print(f"### Client: long sessions\n\n{leaks(after)}\n")


if __name__ == "__main__":
    main()
