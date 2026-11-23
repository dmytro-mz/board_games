# Board games — repo rules

One server, one room for a group of friends, nine board games with bots (plus unfinished ones), played in the browser. The games were
separate repos (`../agent_avenue`, `../karak`, `../skyjo`, …) and were combined here; those folders are the old
originals and are not touched from this repo.

## Product rules (from the owner — keep them true)

1. **Three levels.**
   1. *Create a room* (`/`): name + "Create a room", or join with a code. One link (`/r/CODE`) for everyone.
   2. *Choose the game* (`/r/CODE`, phase `select`): every game is a tile (4 columns on wide screens, 3, 2, 1 on
      narrower ones). Each tile shows for how many players the game is and whether bots are available. A player
      filter ("Fits us (N)", Any, 1…6+, "No bots") hides games that don't fit.
   3. *The game's own lobby, then the game* (phase `game`): exactly the lobby and table the game always had.
2. **Voting.** Every player has one vote. Clicking a game votes for it (moving the vote from another game);
   clicking the same game again takes the vote back. Only votes of players who are online count.
3. **Launching.** Only the room leader launches. The leader sees *Play selected* (the leader's own vote) and
   *Play most voted* (the game with strictly the most votes). If both are the same game, there is only one
   button. On a tie there is no "most voted" game. With no votes there is no button.
4. **Back to game selection** works only while the game sits in its own lobby (mid-game the host first ends the
   game with the game's own "back to lobby"). The leader asks; every *other online* player must accept. Declines
   are shown to everyone and the request stays open. While waiting, the leader can **force** it ("Go back now")
   or cancel it. Offline players don't block it. Accepted → the game table is closed for everyone.
5. **The leader** is whoever created the room; if they are gone for 20 s the role moves to the next online
   member. The game table's host is *always* the room leader (`GameRoom.set_host`).
6. **All games play exactly as they did in their original repos.** Change a game's rules, look or flow only
   when asked. A platform change must not change how a game plays.
7. **Efficiency, not dogma.** Reuse what is genuinely shared (the server, the room base class, the shared JS
   helpers, the CLI). Keep a copy when a game intentionally differs or when sharing would make the code harder
   to follow. "Not DRY for its own sake."
8. **Unfinished games** (`games.UNFINISHED_KEYS`, currently Chronicles of Avel) stay in the repo with their tests
   and `bg <game>` tools but are not offered in rooms; `bg serve --unfinished` shows them. Moving a game to
   `GAME_KEYS` is the owner's call.
9. **When something is unclear, a problem comes up, or a decision isn't covered by these rules: ask the owner**
   instead of guessing.

## Layout

```
src/boardgames/          the platform (one package)
  cli.py                 `bg serve` (all games) and `bg <game> …` (each game's bot/training tools)
  server.py              FastAPI app: platform routes + every game mounted under /g/<game>/ (one websocket loop)
  party.py               the room: members, leader, votes, launch, back-to-selection (sync, no I/O)
  games.py               GameSpec / Backend / GameRoom protocols, GAME_KEYS (tile order), UNFINISHED_KEYS
  table.py               Table: base class of game rooms (members, host, chat, reactions, log, bot driver loop)
  net.py                 queued websocket Connection, cache-safe static files, LAN IP, cloudflared tunnel
  testing.py             game_app / GameClient: one game "as if served alone" for its tests and scripts
  static/                the room page (index.html, app.js, style.css, thumbs/<game>.jpg)
  static/shared/         modules games import: platform.js (identity, URLs, leaveRoom), dom.js (h/s/morph/toast/dialog)
src/<game>/              one top-level package per game: avel avenue codenames karak lostcities pandemic phase10
                         skyjo skyteam ttr. Inside: game/ (pure rules engine), bots/, web/room.py, web/spec.py,
                         web/static/ (vanilla JS client), cli.py (bot tools), plus game-specific bits (rl/, nn/…).
                         Each has its own CLAUDE.md with the game's invariants.
tests/platform/          party + server tests     tests/<game>/   each game's tests (unchanged from its repo)
scripts/platform/        ui_check.py: two players click through all games in Chrome
scripts/<game>/          each game's dev scripts (demo, ui_check, sizes…), now started via boardgames.testing
docs/<game>/             each game's original README, rules notes and screenshots; docs/<game>/rules/*.mdc are
                         the original cursor rules (the per-game CLAUDE.md files are built from them)
configs/<game>/          training configs (karak, skyjo)
```

Dependency direction: `boardgames` never imports a game except through `games.load_games()` (`<game>.web.spec`).
A game imports from `boardgames` only `games.GameSpec` (in `web/spec.py`) and `table` (in `web/room.py`).
Inside a game the old layering holds: `game/` ← `bots/` ← `web/`; never import upwards.

## How a game plugs in

- `src/<game>/web/spec.py` defines `GAME = GameSpec(key, title, tagline, min_players, max_players, bots, kind,
  minutes, static, backend, error, accent)` and a `Backend` class (`new_room(code)`, `config()`; optional
  `mounts()`, `routes(router)`, `on_connect`, `on_message`). Add the key to `games.GAME_KEYS` and a thumbnail at
  `src/boardgames/static/thumbs/<key>.jpg` (640 px wide screenshot of a running game).
- The game's `Room` follows `games.GameRoom`: `join/connect/disconnect/handle/set_host/describe/drive/close`,
  `status` ("lobby" while in its own lobby), `host_id`, `members` (with `.token`). Nine rooms get most of that
  from `boardgames.table.Table`; Sky Team implements it directly (it never had the shared skeleton).
- The game's client lives at `/g/<key>/`: `index.html` loads `/g/<key>/static/…`; `app.js` computes
  `BASE = gameBase(import.meta.url)` and uses it for `api/…` and `ws/…`; identity comes from
  `TOKEN_KEY`/`NAME_KEY` (`bg.token`, `bg.name`, shared with the room page); "leave table" calls `leaveRoom()`.
  Invite links stay `/r/CODE` (the room link). The client runs inside the room page's iframe, but must also work
  opened directly at `/g/<key>/r/CODE` (scripts do that).
- `POST /g/<key>/api/rooms` opens a table of that game without voting (tests, browser checks).

## Commands (always via uv, never pip)

- Play: `uv run bg serve` (LAN) · `uv run bg serve --tunnel` (public link via cloudflared) · `uv run bg serve --help`
- Game tools: `uv run bg <game> --help`, e.g. `uv run bg lostcities eval -a veteran,pathfinder -n 2000`
- Tests: `uv run pytest -n 8` (must pass before you say you're done; ~10 s). Torch tests run only with
  `uv sync --group train`.
- Lint/format: `uv run ruff check --fix src tests scripts && uv run ruff format src tests scripts`
- Room page in Chrome, all games: `uv run python scripts/platform/ui_check.py` (fails on any JS error;
  screenshots in `shots/platform/`)
- A game's own browser checks: `uv run python scripts/<game>/ui_check.py` (see the game's CLAUDE.md)

## Working agreements

- The server is authoritative; clients only send intents. Never trust client input. Hidden information never
  leaves the server (each game's `state_for` / `_filter_event` and its tests guard that).
- Python 3.12, `from __future__ import annotations`, full type hints, ruff line length 120. Engines stay pure
  (no I/O, no asyncio, randomness only through seeded `rng`s).
- Rooms (party and tables) are synchronous and do no I/O; `server.py` only moves JSON over websockets.
- Clients: vanilla ES modules, no build step, no frameworks. Re-render with `morph` where a game already does.
  Platform UI must not leak styles into games (they run in an iframe — keep it that way).
- Any platform change: run `tests/platform`, the whole suite, and `scripts/platform/ui_check.py`. Any game change:
  that game's tests and its `scripts/<game>/ui_check.py`, and look at a screenshot.
- All art is original; never copy a published game's artwork or rulebook text.
- Training (torch, tensorboard…) stays in the optional `train` dependency group; playing needs only numpy.
- Scratch output (`shots/`, `runs/`, `logs/`, `tmp/`, `progress.json`) is gitignored.
