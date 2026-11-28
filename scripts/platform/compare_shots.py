"""Before/after screenshots: each game's demo stages rendered by two checkouts at the same sizes, compared pixel by
pixel. A difference image (changed pixels in magenta over a dimmed copy) is saved for every pair that differs.

  git worktree add --detach tmp/base <commit>; (cd tmp/base && uv sync)
  uv run python scripts/platform/compare_shots.py --base tmp/base [--games ttr,karak] [--sizes 1440x900,390x844]

Prints the share of changed pixels per shot; continuous animations (pulses, idle bobbing) make small differences
even between two runs of the same checkout, so --noise renders the current checkout twice to show that floor.
"""

from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
from pathlib import Path

import numpy as np
from PIL import Image

STAGES = {
    "avenue": ["lobby", "play", "recruit", "over"],
    "codenames": ["lobby", "clue", "guess", "over"],
    "karak": ["lobby", "play"],
    "lostcities": ["lobby", "play", "draw", "round", "over"],
    "pandemic": ["lobby", "play", "draw", "over"],
    "phase10": ["lobby", "play"],
    "sumo": ["lobby", "play", "over"],
    "toybattle": ["lobby", "play", "effect", "over"],
    "ttr": ["lobby", "play", "tickets", "over"],
}


def shoot(root: Path, game: str, stage: str, size: str, out: Path) -> bool:
    out.parent.mkdir(parents=True, exist_ok=True)
    folder = game == "codenames"  # its demo writes <stage>-<deck>-<who>-<size>.png into a folder
    target = out.with_suffix("") if folder else out
    cmd = ["uv", "run", "-q", "--project", str(root), "python", f"scripts/{game}/demo.py"]
    cmd += ["--stage", stage, "--size", size, "--out", str(target.resolve())]
    proc = subprocess.run(cmd, cwd=root, capture_output=True, text=True, timeout=180)
    if folder and proc.returncode == 0:
        (target / f"{stage}-en-op-{size}.png").replace(out)
        shutil.rmtree(target, ignore_errors=True)
    if proc.returncode != 0 or not out.exists():
        print(f"  {game} {stage} {size}: demo failed in {root}: {proc.stderr.strip()[-300:]}", file=sys.stderr)
        return False
    return True


def compare(a: Path, b: Path, diff: Path) -> float:
    x = np.asarray(Image.open(a).convert("RGB"), dtype=np.int16)
    y = np.asarray(Image.open(b).convert("RGB"), dtype=np.int16)
    if x.shape != y.shape:
        return 1.0
    changed = np.abs(x - y).max(axis=2) > 24
    share = float(changed.mean())
    if share > 0:
        img = (x * 0.35).astype(np.uint8)
        img[changed] = (255, 0, 255)
        Image.fromarray(img).save(diff)
    return share


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", type=Path, required=True)
    ap.add_argument("--games", default=",".join(STAGES))
    ap.add_argument("--sizes", default="1440x900,390x844")
    ap.add_argument("--out", type=Path, default=Path("shots/compare"))
    ap.add_argument("--noise", action="store_true", help="also render the current checkout twice (run-to-run floor)")
    args = ap.parse_args()
    here = Path.cwd()
    print(f"{'game':<11}{'stage':<9}{'size':<10}{'changed':>9}" + (f"{'noise':>9}" if args.noise else ""))
    for game in args.games.split(","):
        for stage in STAGES[game]:
            for size in args.sizes.split(","):
                name = f"{game}-{stage}-{size}"
                before, after = args.out / f"{name}-before.png", args.out / f"{name}-after.png"
                if not (
                    shoot(args.base.resolve(), game, stage, size, before) and shoot(here, game, stage, size, after)
                ):
                    continue
                share = compare(before, after, args.out / f"{name}-diff.png")
                line = f"{game:<11}{stage:<9}{size:<10}{share * 100:>8.2f}%"
                if args.noise:
                    again = args.out / f"{name}-again.png"
                    if shoot(here, game, stage, size, again):
                        line += f"{compare(after, again, args.out / f'{name}-noise.png') * 100:>8.2f}%"
                print(line, flush=True)


if __name__ == "__main__":
    main()
