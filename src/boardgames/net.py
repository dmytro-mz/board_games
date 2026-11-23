"""Transport pieces every table shares: a queued websocket, cache-safe static files, LAN address and tunnel."""

from __future__ import annotations

import asyncio
import re
import shutil
import socket
import subprocess
import time
from typing import Any

from fastapi import WebSocket
from fastapi.staticfiles import StaticFiles

MAX_QUEUE = 1000


class RevalidatedStatic(StaticFiles):
    """Browsers must revalidate (cheap 304 via ETag), so a restarted server never runs a stale client."""

    def file_response(self, *args: Any, **kwargs: Any) -> Any:
        response = super().file_response(*args, **kwargs)
        response.headers["Cache-Control"] = "no-cache"
        return response


class Connection:
    """One websocket. Sends go through a queue so a slow client never blocks the room.

    Rooms only see `member_id` and `send()` (their `Listener` protocol)."""

    def __init__(self, ws: WebSocket, member_id: str) -> None:
        self.ws = ws
        self.member_id = member_id
        self.queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue()

    def send(self, message: dict[str, Any]) -> None:
        if self.queue.qsize() < MAX_QUEUE:
            self.queue.put_nowait(message)

    async def pump(self) -> None:
        while True:
            message = await self.queue.get()
            await self.ws.send_json(message)


def client_origin(ws: WebSocket) -> str:
    """The visitor's address for the server log (behind cloudflared, the real one is in a header)."""
    return ws.headers.get("cf-connecting-ip") or (ws.client.host if ws.client else "")


def lan_ip() -> str | None:
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
        try:
            s.connect(("10.255.255.255", 1))  # no packet is sent; picks the outbound interface
            ip = s.getsockname()[0]
        except OSError:
            return None
    return None if ip.startswith("127.") else ip


class TunnelError(RuntimeError):
    pass


def start_tunnel(port: int) -> tuple[subprocess.Popen[str], str]:
    """A cloudflared quick tunnel to the local server: (process, public https URL)."""
    exe = shutil.which("cloudflared")
    if exe is None:
        raise TunnelError("--tunnel needs cloudflared: `brew install cloudflared`")
    proc = subprocess.Popen(
        [exe, "tunnel", "--no-autoupdate", "--url", f"http://127.0.0.1:{port}"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
        text=True,
    )
    assert proc.stderr is not None
    pattern = re.compile(r"https://[a-z0-9-]+\.trycloudflare\.com")
    deadline = time.time() + 30
    for line in proc.stderr:
        if match := pattern.search(line):
            return proc, match.group(0)
        if time.time() > deadline:
            break
    proc.terminate()
    raise TunnelError("cloudflared did not report a public URL")
