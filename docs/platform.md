# Platform reference

Read this when you add a game or change the platform. The product rules and values are in `/CLAUDE.md`.
The technical rules every game must follow are in [`/tech_rules.md`](../tech_rules.md).

## Layout

```
src/boardgames/          the platform (one package)
  cli.py                 `bg serve` (all games) and `bg <game> …` (each game's bot/training tools)
  server.py              Starlette app: platform routes + every game mounted under /g/<game>/ (one websocket loop)
  party.py               the room: members, leader, votes, launch, back-to-selection (sync, no I/O)
  games.py               GameSpec / Backend / GameRoom protocols, GAME_KEYS (tile order)
  table.py               Table: base class of game rooms (members, host, chat, reactions, log, bot driver loop),
                         think() (bot work off the event loop), think_apart() (search bots in worker processes)
  worker.py              what runs inside a bot worker process (import-free on purpose)
  net.py                 queued websocket Connection, static files (StaticDir, PageRewriter), LAN IP, tunnel
  testing.py             game_app / GameClient: one game "as if served alone" for its tests and scripts
  static/                the room page (index.html, app.js, style.css, thumbs/<game>.avif)
  static/shared/         modules games import: platform.js (identity, URLs, leaveRoom, frameLoop),
                         dom.js (h/s/morph/toast/dialog)
src/<game>/              one top-level package per game: avenue codenames karak lostcities pandemic phase10
                         skyjo skyteam sumo toybattle ttr. Inside: game/ (pure rules engine), bots/, web/room.py, web/spec.py,
                         web/static/ (vanilla JS client), cli.py (bot tools), plus game-specific bits (rl/, nn/…).
                         Each has its own CLAUDE.md with the game's invariants.
tests/platform/          party + server tests     tests/<game>/   each game's tests
scripts/platform/        ui_check.py: two players click through all games in Chrome · perf_check.py: performance
                         budgets · bench_*.py: benchmarks · compare_shots.py: before/after screenshots ·
                         thumb.py: a tile thumbnail (AVIF)
scripts/<game>/          each game's dev scripts (demo, ui_check, sizes…), started via boardgames.testing
docs/<game>/             each game's README, rules notes and screenshots
configs/<game>/          training configs (karak, skyjo)
```

Dependency direction: `boardgames` never imports a game except through `games.load_games()` (`<game>.web.spec`).
A game imports from `boardgames` only `games.GameSpec` (in `web/spec.py`) and `table` (in `web/room.py`).
Inside a game: `game/` ← `bots/` ← `web/`; never import upwards.

## How a game plugs in

- `src/<game>/web/spec.py` defines `GAME = GameSpec(key, title, tagline, min_players, max_players, bots, kind,
  minutes, static, backend, error, accent)` and a `Backend` class (`new_room(code)`, `config()`; optional
  `mounts()`, `routes(router)`, `on_connect`, `on_message`). Add the key to `games.GAME_KEYS` and a thumbnail at
  `src/boardgames/static/thumbs/<key>.avif` (a 640 px wide screenshot of a running game, converted with
  `uv run python scripts/platform/thumb.py shot.png <key>`).
- The game's `Room` follows `games.GameRoom`: `join/connect/disconnect/handle/set_host/describe/drive/close`,
  `status` ("lobby" while in its own lobby), `host_id`, `members` (with `.token`). Ten rooms get most of that
  from `boardgames.table.Table`; Sky Team implements it directly (it never had the shared skeleton).
- The game's client lives at `/g/<key>/`: `index.html` loads `/g/<key>/static/…`; `app.js` computes
  `BASE = gameBase(import.meta.url)` and uses it for `api/…` and `ws/…`; identity comes from
  `TOKEN_KEY`/`NAME_KEY` (`bg.token`, `bg.name`, shared with the room page); "leave table" calls `leaveRoom()`.
  Invite links stay `/r/CODE` (the room link). The client runs inside the room page's iframe, but must also work
  opened directly at `/g/<key>/r/CODE` (scripts do that).
- `POST /g/<key>/api/rooms` opens a table of that game without voting (tests, browser checks).

## Commands (always via uv, never pip)

- Play: `uv run bg serve` (LAN) · `uv run bg serve --tunnel` (public link via cloudflared)
- Game tools: `uv run bg <game> --help`, e.g. `uv run bg lostcities eval -a veteran,pathfinder -n 2000`
- Tests: `uv run pytest -n 8` (~10 s). Torch tests run only with `uv sync --group train`.
- Lint/format: `uv run ruff check --fix src tests scripts && uv run ruff format src tests scripts`
- Room page in Chrome, all games: `uv run python scripts/platform/ui_check.py` (fails on any JS error; screenshots in `shots/platform/`)
- Performance budgets (server loop blocking, client idle CPU, warm reloads): `uv run python scripts/platform/perf_check.py`
- Benchmarks (numbers in `docs/performance.md`): `scripts/platform/bench_server.py` (headless bot games),
  `bench_load.py` (rooms × websocket clients), `bench_client.py` (Chrome + CDP), `bench_trace.py` (where frames go)
- Before/after screenshots of every demo stage: `uv run python scripts/platform/compare_shots.py --base <worktree>`
- A game's own browser checks: `uv run python scripts/<game>/ui_check.py`

## Conventions

- Python 3.12, `from __future__ import annotations`, full type hints, ruff line length 120.
- Clients: vanilla ES modules, no build step, no frameworks. Re-render with `morph` where a game already does.
- A client idles at zero frames: no permanent `requestAnimationFrame` or `setInterval` loops. Per-frame drawing (a turn
  timer counting down) goes through `frameLoop(draw, running)` from `platform.js`, kicked after every render.
  Pulses that run while the table waits for a player animate `transform`/`opacity` (the compositor runs those);
  animating `box-shadow`, `filter`, `fill` etc. repaints the whole page every frame (measured 30–150 ms of CPU/s).
- Static files: a page links its folder at `/…/static/~<version>/…` (cached for a year; the version is a fingerprint
  of the folder, so any edit reaches the next page load), `PageRewriter` adds the import map and modulepreload
  hints. Reference files relative to the module (`new URL("x.json", import.meta.url)`), never as `/g/<key>/static/x`
  (that path still works but is revalidated on every load). Browser scripts that `import()` a page's module must
  import the page's own URL (`new URL("board.js", document.querySelector("script[type=module]").src)`): the
  unversioned URL is a separate module instance.
- Bots: a decision that takes more than a few ms goes through `Table.think(key, compute)` (inside `plan()` or a step;
  runs in a thread under `drive()`). Search bots with a time budget use `think_apart` (a worker process, so they
  neither hold the GIL against the event loop nor share a core); call `prewarm_bots()` when one sits down.
- Training (torch, tensorboard…) stays in the optional `train` dependency group; playing needs only numpy.
- Scratch output (`shots/`, `runs/`, `logs/`, `tmp/`, `progress.json`) is gitignored.
