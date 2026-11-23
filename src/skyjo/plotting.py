"""Render a training dashboard PNG from a run's metrics.csv."""

from __future__ import annotations

import csv
import json
from collections import defaultdict
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt


def load_metrics(run_dir: Path) -> dict[str, tuple[list[int], list[float]]]:
    series: dict[str, tuple[list[int], list[float]]] = defaultdict(lambda: ([], []))
    with (run_dir / "metrics.csv").open() as f:
        for row in csv.DictReader(f):
            xs, ys = series[row["tag"]]
            xs.append(int(row["step"]))
            ys.append(float(row["value"]))
    return dict(series)


def _smooth(ys: list[float], k: int = 10) -> list[float]:
    out, acc = [], 0.0
    alpha = 2 / (k + 1)
    for i, y in enumerate(ys):
        acc = y if i == 0 else alpha * y + (1 - alpha) * acc
        out.append(acc)
    return out


PANELS: list[tuple[str, list[str]]] = [
    ("learning rate", ["charts/learning_rate"]),
    ("entropy / ent coef", ["losses/entropy", "charts/ent_coef"]),
    ("losses", ["losses/policy", "losses/value"]),
    ("approx KL / clipfrac", ["losses/approx_kl", "losses/clipfrac"]),
    ("explained variance", ["losses/explained_variance"]),
    ("rollout return (vs pool)", ["rollout/return"]),
    ("rollout round score", ["rollout/score", "rollout/opp_score"]),
    ("steps / second", ["charts/sps"]),
]


def plot_run(run_dir: Path, out: Path | None = None) -> Path:
    metrics = load_metrics(run_dir)
    ref_path = run_dir / "reference.json"
    reference = json.loads(ref_path.read_text())["vs"] if ref_path.exists() else {}
    opponents = sorted({t.split("/")[1] for t in metrics if t.startswith("eval/")})

    n_panels = len(PANELS) + 2
    cols = 3
    rows = (n_panels + cols - 1) // cols
    fig, axes = plt.subplots(rows, cols, figsize=(6 * cols, 3.6 * rows), squeeze=False)
    flat = axes.flatten()

    for ax, (title, tags) in zip(flat, PANELS, strict=False):
        for tag in tags:
            if tag in metrics:
                xs, ys = metrics[tag]
                smooth = tag.startswith(("rollout/", "losses/"))
                ax.plot(xs, _smooth(ys) if smooth else ys, label=tag.split("/")[-1])
        ax.set_title(title)
        ax.grid(alpha=0.3)
        if len(tags) > 1:
            ax.legend(fontsize=8)

    ax_win, ax_score = flat[len(PANELS)], flat[len(PANELS) + 1]
    for i, opp in enumerate(opponents):
        color = f"C{i}"
        if f"eval/{opp}/win_rate" in metrics:
            ax_win.plot(*metrics[f"eval/{opp}/win_rate"], marker="o", ms=3, color=color, label=f"vs {opp}")
        if f"eval/{opp}/round_score" in metrics:
            ax_score.plot(*metrics[f"eval/{opp}/round_score"], marker="o", ms=3, color=color, label=f"vs {opp}")
        if opp in reference:
            ax_win.axhline(reference[opp]["win_rate"], color=color, ls="--", alpha=0.5)
            ax_score.axhline(reference[opp]["round_score"], color=color, ls="--", alpha=0.5)
    ax_win.set_title("eval: game win rate (dashed = EV heuristic)")
    ax_win.set_ylim(0, 1)
    ax_score.set_title("eval: mean round score, lower is better (dashed = EV)")
    for ax in (ax_win, ax_score):
        ax.grid(alpha=0.3)
        ax.legend(fontsize=8)
    for ax in flat[n_panels:]:
        ax.axis("off")
    for ax in flat:
        ax.set_xlabel("env steps")

    fig.suptitle(run_dir.name)
    fig.tight_layout()
    out = out or run_dir / "dashboard.png"
    fig.savefig(out, dpi=110)
    plt.close(fig)
    return out
