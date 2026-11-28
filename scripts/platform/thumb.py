"""A game tile's thumbnail: a 640 px wide screenshot of the running game, as AVIF for the game selection.

  uv run python scripts/platform/thumb.py shots/karak/play.png karak     # -> src/boardgames/static/thumbs/karak.avif

Picks the smallest quality whose SSIM against the source stays >= --ssim (0.99 is indistinguishable at tile size).
"""

from __future__ import annotations

import argparse
import io
from pathlib import Path

import numpy as np
from numpy.lib.stride_tricks import sliding_window_view
from PIL import Image

THUMBS = Path(__file__).resolve().parents[2] / "src" / "boardgames" / "static" / "thumbs"


def ssim(a: Image.Image, b: Image.Image) -> float:
    """Mean SSIM of the luma over 8x8 windows (stride 4)."""
    x = np.asarray(a.convert("L"), dtype=float)
    y = np.asarray(b.convert("L"), dtype=float)
    wx, wy = sliding_window_view(x, (8, 8))[::4, ::4], sliding_window_view(y, (8, 8))[::4, ::4]
    mx, my = wx.mean((-1, -2)), wy.mean((-1, -2))
    vx, vy = wx.var((-1, -2)), wy.var((-1, -2))
    cov = ((wx - mx[..., None, None]) * (wy - my[..., None, None])).mean((-1, -2))
    c1, c2 = 6.5025, 58.5225
    return float((((2 * mx * my + c1) * (2 * cov + c2)) / ((mx**2 + my**2 + c1) * (vx + vy + c2))).mean())


def encode(src: Image.Image, target: float) -> tuple[bytes, int, float]:
    for quality in range(50, 96, 5):
        buf = io.BytesIO()
        src.save(buf, "AVIF", quality=quality, speed=2)
        score = ssim(src, Image.open(io.BytesIO(buf.getvalue())))
        if score >= target:
            return buf.getvalue(), quality, score
    return buf.getvalue(), quality, score


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("source", type=Path)
    ap.add_argument("key")
    ap.add_argument("--ssim", type=float, default=0.99)
    args = ap.parse_args()
    img = Image.open(args.source).convert("RGB")
    if img.width != 640:
        img = img.resize((640, round(img.height * 640 / img.width)), Image.LANCZOS)
    data, quality, score = encode(img, args.ssim)
    out = THUMBS / f"{args.key}.avif"
    out.write_bytes(data)
    print(f"{out.name}: {len(data) // 1024} kB (quality {quality}, SSIM {score:.4f})")


if __name__ == "__main__":
    main()
