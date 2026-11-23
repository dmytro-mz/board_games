"""Metrics sink: TensorBoard for live curves, CSV for plotting / agents to parse."""

from __future__ import annotations

import csv
import time
from pathlib import Path

from torch.utils.tensorboard import SummaryWriter


class MetricsLogger:
    def __init__(self, run_dir: Path) -> None:
        self.run_dir = run_dir
        self.writer = SummaryWriter(log_dir=str(run_dir / "tb"))
        self._csv_file = (run_dir / "metrics.csv").open("a", newline="")
        self._csv = csv.writer(self._csv_file)
        if self._csv_file.tell() == 0:
            self._csv.writerow(["step", "tag", "value", "wall_time"])
        self._t0 = time.time()

    def log(self, step: int, scalars: dict[str, float]) -> None:
        now = time.time() - self._t0
        for tag, value in scalars.items():
            self.writer.add_scalar(tag, value, step)
            self._csv.writerow([step, tag, f"{value:.6g}", f"{now:.1f}"])
        self._csv_file.flush()

    def text(self, tag: str, text: str) -> None:
        self.writer.add_text(tag, text)

    def close(self) -> None:
        self.writer.close()
        self._csv_file.close()
