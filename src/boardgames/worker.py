"""What runs inside a bot worker process (see `table.think_apart`). Kept free of imports, so a worker costs little
more than an interpreter plus the bot's own game modules (unpickling the bot imports them)."""

from __future__ import annotations

import os
import threading
import time
from typing import Any


def watch_owner(owner: int) -> None:
    """Exit when the server that started this worker is gone, even if it was killed without cleaning up."""

    def watch() -> None:
        while True:
            time.sleep(2.0)
            try:
                os.kill(owner, 0)
            except OSError:
                os._exit(0)

    threading.Thread(target=watch, daemon=True).start()


def decide(agent: Any, method: str, args: tuple[Any, ...]) -> tuple[Any, Any]:
    """The bot's decision, and the bot itself as it is afterwards (its random generator moved on)."""
    return getattr(agent, method)(*args), agent


def ready() -> None:
    """A no-op task that makes the pool start a worker ahead of the first decision."""
