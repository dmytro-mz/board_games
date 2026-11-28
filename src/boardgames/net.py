"""Transport pieces every table shares: a queued websocket, the static client files, LAN address and tunnel."""

from __future__ import annotations

import asyncio
import gzip
import hashlib
import json
import mimetypes
import os
import re
import shutil
import socket
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from starlette._utils import get_route_path
from starlette.requests import Request
from starlette.responses import FileResponse, JSONResponse, Response
from starlette.types import Receive, Scope, Send
from starlette.websockets import WebSocket

MAX_QUEUE = 1000

IMMUTABLE = "public, max-age=31536000, immutable"
REVALIDATE = "no-cache"
COMPRESSIBLE = {".js", ".mjs", ".css", ".html", ".json", ".svg", ".txt"}
MIN_GZIP = 512  # bytes: smaller files are sent as they are
mimetypes.add_type("text/javascript", ".js")
mimetypes.add_type("text/javascript", ".mjs")


def json_bytes(data: Any) -> bytes:
    """Compact JSON, exactly as starlette's `send_json` writes it."""
    return json.dumps(data, separators=(",", ":"), ensure_ascii=False).encode()


def accepts_gzip(headers: Any) -> bool:
    return "gzip" in headers.get("accept-encoding", "")


@dataclass
class _Packed:
    """One file kept in memory: its stamp (to notice edits), ETag and the gzipped body."""

    stamp: tuple[int, int]
    etag: str
    body: bytes
    gz: bytes | None


class StaticDir:
    """A folder of client files served at `prefix`, with long-lived caching that still never serves a stale client.

    Every file is reachable two ways:
      {prefix}/{path}        revalidated on every load (ETag → 304), for links that can't carry a version
      {prefix}/~{v}/{path}   `v` is a fingerprint of the whole folder; cached for a year, never revalidated
    Pages link the versioned form (see `PageRewriter`), so a warm load costs no requests at all, and any edit of any
    file changes `v`, so the next page load fetches the new client. Text files go out gzipped from memory.
    """

    def __init__(self, directory: Path, prefix: str) -> None:
        self.directory = directory.resolve()
        self.prefix = prefix.rstrip("/")
        self._version: str | None = None
        self._stamps: tuple[tuple[str, int, int], ...] = ()
        self._packed: dict[str, _Packed] = {}

    # ------------------------------------------------------------------ version
    def _scan(self) -> tuple[tuple[str, int, int], ...]:
        out = []
        for root, dirs, files in os.walk(self.directory):
            dirs[:] = sorted(d for d in dirs if not d.startswith((".", "__")))
            for name in sorted(files):
                if name.startswith("."):
                    continue
                st = os.stat(os.path.join(root, name))
                rel = os.path.relpath(os.path.join(root, name), self.directory)
                out.append((rel, st.st_size, st.st_mtime_ns))
        return tuple(out)

    def version(self) -> str:
        """The folder's fingerprint, recomputed when any file changed (one stat per file: cheap, page loads only)."""
        stamps = self._scan()
        if stamps != self._stamps or self._version is None:
            self._stamps = stamps
            self._version = hashlib.sha1(repr(stamps).encode()).hexdigest()[:10]
        return self._version

    def url(self, path: str) -> str:
        return f"{self.prefix}/~{self.version()}/{path.lstrip('/')}"

    # ------------------------------------------------------------------ files
    def _file(self, rel: str) -> Path | None:
        path = (self.directory / rel).resolve()
        if not path.is_relative_to(self.directory) or not path.is_file():
            return None
        return path

    def _pack(self, rel: str, path: Path) -> _Packed:
        st = path.stat()
        stamp = (st.st_size, st.st_mtime_ns)
        packed = self._packed.get(rel)
        if packed is None or packed.stamp != stamp:
            body = path.read_bytes()
            gz = None
            if path.suffix in COMPRESSIBLE and len(body) >= MIN_GZIP:
                gz = gzip.compress(body, 9, mtime=0)
            etag = '"' + hashlib.sha1(body).hexdigest()[:16] + '"'
            packed = self._packed[rel] = _Packed(stamp, etag, body if gz is not None else b"", gz)
        return packed

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        request = Request(scope, receive)
        if request.method not in ("GET", "HEAD"):
            await Response(status_code=405)(scope, receive, send)
            return
        rel = get_route_path(scope).lstrip("/")
        cache = REVALIDATE
        if rel.startswith("~"):
            version, _, rel = rel.partition("/")
            if version[1:] == self.version():
                cache = IMMUTABLE
        path = self._file(rel)
        if path is None:
            await Response("Not Found", status_code=404)(scope, receive, send)
            return
        response = self.respond(request, rel, path, cache)
        await response(scope, receive, send)

    def respond(self, request: Request, rel: str, path: Path, cache: str) -> Response:
        media = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
        if path.suffix not in COMPRESSIBLE:  # images, sounds: from disk, revalidated by a stat-based ETag
            st = path.stat()
            etag = f'"{st.st_size:x}-{st.st_mtime_ns:x}"'
            headers = {"Cache-Control": cache, "ETag": etag}
            if etag in request.headers.get("if-none-match", ""):
                return Response(status_code=304, headers=headers)
            return FileResponse(path, media_type=media, headers=headers, stat_result=st)
        packed = self._pack(rel, path)
        headers = {"Cache-Control": cache, "ETag": packed.etag, "Vary": "Accept-Encoding"}
        if packed.etag in request.headers.get("if-none-match", ""):
            return Response(status_code=304, headers=headers)
        if packed.gz is None:
            return FileResponse(path, media_type=media, headers=headers)
        if accepts_gzip(request.headers):
            return Response(packed.gz, media_type=media, headers={**headers, "Content-Encoding": "gzip"})
        return Response(packed.body or path.read_bytes(), media_type=media, headers=headers)


_IMPORT = re.compile(r"""(?:^|[;\s])(?:import|export)\s*(?:[\w*{}\s,$]+?\s*from\s*)?["']([^"']+\.m?js)["']""", re.M)


class PageRewriter:
    """A client's index.html as served: links into its own folder versioned, an import map that versions the
    shared modules it imports by absolute path, and modulepreload hints for every module the page will import (no
    import waterfall on a cold load). Re-rendered whenever a folder's version changes."""

    def __init__(
        self, page: Path, own: StaticDir, shared: StaticDir | None = None, shared_path: str = "shared/"
    ) -> None:
        self.page = page
        self.own = own
        self.shared = shared
        self.shared_path = shared_path
        self._key: tuple[str, ...] | None = None
        self._html = b""
        self._gz = b""
        self._etag = ""

    def _dirs(self) -> list[StaticDir]:
        return [self.own] if self.shared is None else [self.own, self.shared]

    def _split(self, url: str) -> tuple[StaticDir, str] | None:
        for d in self._dirs():
            if url.startswith(d.prefix + "/"):
                return d, url[len(d.prefix) + 1 :]
        return None

    def _graph(self, entries: list[str]) -> list[str]:
        """Module URLs (unversioned) reachable from the entry modules through static imports."""
        seen: list[str] = []
        todo = list(entries)
        while todo:
            url = todo.pop(0)
            found = self._split(url)
            path = found[0]._file(found[1]) if found else None
            if url in seen or path is None:
                continue
            seen.append(url)
            for spec in _IMPORT.findall(path.read_text(encoding="utf-8")):
                if spec.startswith("/"):
                    todo.append(spec)
                elif spec.startswith("."):
                    todo.append(os.path.normpath(os.path.join(os.path.dirname(url), spec)))
        return seen

    def _versioned(self, url: str) -> str:
        found = self._split(url)
        return found[0].url(found[1]) if found else url

    def _render(self) -> None:
        html = self.page.read_text(encoding="utf-8")
        entries = re.findall(r'<script[^>]*type="module"[^>]*src="([^"]+)"', html)
        modules = self._graph(entries)
        own = self.own.prefix + "/"
        html = re.sub(rf'(["(]){re.escape(own)}(?!~)', lambda m: m.group(1) + self.own.url(""), html)
        head = []
        if self.shared is not None:
            imports = {f"{self.shared.prefix}/{self.shared_path}": self.shared.url(self.shared_path)}
            head.append(f'<script type="importmap">{json.dumps({"imports": imports})}</script>')
        head += [f'<link rel="modulepreload" href="{self._versioned(u)}">' for u in modules if u not in entries]
        html = html.replace("<head>", "<head>\n" + "\n".join(head), 1)
        body = html.encode()
        self._html, self._gz = body, gzip.compress(body, 9, mtime=0)
        self._etag = '"' + hashlib.sha1(body).hexdigest()[:16] + '"'

    def response(self, request: Request) -> Response:
        key = (*(d.version() for d in self._dirs()), str(self.page.stat().st_mtime_ns))
        if key != self._key:
            self._render()
            self._key = key
        headers = {"Cache-Control": REVALIDATE, "ETag": self._etag, "Vary": "Accept-Encoding"}
        if self._etag in request.headers.get("if-none-match", ""):
            return Response(status_code=304, headers=headers)
        if accepts_gzip(request.headers):
            return Response(self._gz, media_type="text/html", headers={**headers, "Content-Encoding": "gzip"})
        return Response(self._html, media_type="text/html", headers=headers)


class CachedJSON:
    """A JSON document that never changes while the server runs (a game's config): encoded and gzipped once,
    revalidated with an ETag."""

    def __init__(self, data: Any) -> None:
        self.body = json_bytes(data)
        self.gz = gzip.compress(self.body, 9, mtime=0) if len(self.body) >= MIN_GZIP else None
        self.etag = '"' + hashlib.sha1(self.body).hexdigest()[:16] + '"'

    def response(self, request: Request) -> Response:
        headers = {"Cache-Control": REVALIDATE, "ETag": self.etag, "Vary": "Accept-Encoding"}
        if self.etag in request.headers.get("if-none-match", ""):
            return Response(status_code=304, headers=headers)
        if self.gz is not None and accepts_gzip(request.headers):
            return Response(self.gz, media_type="application/json", headers={**headers, "Content-Encoding": "gzip"})
        return Response(self.body, media_type="application/json", headers=headers)


def error(status: int, detail: str) -> JSONResponse:
    """An HTTP error as the clients read it: {"detail": message}."""
    return JSONResponse({"detail": detail}, status_code=status)


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
