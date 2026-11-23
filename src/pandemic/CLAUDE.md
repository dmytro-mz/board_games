<!-- Built from docs/pandemic/rules/*.mdc (the original repo's rules), adapted to this repo. The root CLAUDE.md rules apply too. -->

# Pandemic — project map

Goal: an online Pandemic (classic edition) for friends — the complete game, a readable world map that zooms
from the whole world to a crowded region, bots good enough to fill empty seats, and a table that works from a
phone to full HD.

## Layout and dependency direction (never import "upwards")

```
pandemic/game/      rules engine, pure Python, no I/O                  (lowest layer)
  model.py          48 cities + routes, roles, event cards, distances/path, catalogue() for the client
  actions.py        action dataclasses + JSON protocol (to_json / from_json)
  engine.py         Game state machine: Game.play(seat, action) -> events, undo, view(seat) -> View, sandbox
pandemic/bots/      Bot ABC (act / react) · planner.py (beam-search turn planner) · registry (rookie, expert)
pandemic/runner.py  play_game(bots, seed, rules)
pandemic/web/       room.py (sync table logic, no I/O) · server.py (FastAPI + WebSocket, /api/config)
                    static/ (vanilla ES-module client, no build step)
pandemic/cli.py     typer CLI (entry point `pandemic`: serve, eval)
scripts/            build_map (map-data.js from Natural Earth) · demo / shot / sizes / ui_check / flow_check / glitch_check (browser checks)
```

## Commands (always via uv, never pip; in the sandbox `export UV_CACHE_DIR=.uv-cache`)

- Tests: `uv run pytest` (must pass before you say you're done)
- Lint/format: `uv run ruff check --fix . && uv run ruff format .`
- Play: `uv run bg serve` (LAN) · `uv run bg serve --tunnel` (public link via cloudflared)
- Bot strength: `uv run bg pandemic eval -a expert,rookie -n 150` (win rate per team size and difficulty)
- See the UI: `uv run python scripts/pandemic/demo.py --stage home|lobby|play|draw|epidemic|infect|discard|over --out shots/x.png`
- Click through whole games in Chrome: `uv run python scripts/pandemic/ui_check.py [--role R] [--closed] [--size WxH] [--bots N]`
- A whole table as real people (typing, a touch phone, a spectator, reloads): `uv run python scripts/pandemic/flow_check.py [--closed]`
- One stage at phone → full HD sizes (plus a city popover): `uv run python scripts/pandemic/sizes.py --stage play`
- Visual glitches at real bot speed (replayed animations, flicker, lost focus; `--snap 5` saves frames to look at):
 `uv run python scripts/pandemic/glitch_check.py [--bots N] [--size WxH] [--touch] [--closed] [--role R]`
- The browser scripts share port 8765: run them one after another, not in parallel.

## Working agreements

- The server is authoritative; clients only send intents. Never trust client input.
- The UI never computes risks, odds or "danger" for players (no outbreak warnings, no known infection-deck top).
  It shows what is on the table and explains why an action isn't possible; judging the board is the players' job.
- Hidden information: with closed hands only your own cards (and Epidemics) reach your browser; the order of
  the decks is never sent. Bots see open hands (they can't chat).
- Any rules change goes in `game/` with a test in `tests/pandemic/test_engine.py`; keep `static/rules.js` in sync (it
  mirrors legality only to enable buttons and explain; the server re-checks everything).
- UI changes: render with `scripts/pandemic/demo.py`, look at the screenshot, run `scripts/pandemic/ui_check.py`, `scripts/pandemic/flow_check.py`, `scripts/pandemic/sizes.py` and `scripts/pandemic/glitch_check.py`.
- `shots/` and `tmp/` are scratch output (gitignored).

# Rules engine

- `Game.play(seat, action)` validates everything and raises `IllegalMove` with a player-facing message,
  leaving the state untouched. It returns events (`turn`, `move`, `treat`, `build`, `share`, `cure`, `draw`,
  `epidemic`, `infect`, `outbreak`, `prevented`, `intensify`, `event`, `forecast`, `discard`, `game_over`, …)
  that the room narrates and the client animates.
- Steps: ACTIONS (4, or `Pass`) → DRAW (`DrawCards`, 2 cards) → EPIDEMIC (one per Epidemic drawn: increase and
  infect happen on draw, `Continue` intensifies) → INFECT (`Continue` infects) → next player's ACTIONS.
  `waiting_for()` is the Forecast seat, else the seat over the hand limit, else the current seat.
- Hand limit 7: the seat over it must `Discard` (or play an event) before anything else; it can be any seat
  (Share Knowledge).
- Events are allowed for any seat at any time except while a Forecast is being arranged, while someone else is
  over the hand limit, and during an epidemic only Resilient Population. Events never use an action.
- Treat removes 1 cube, or all cubes of a cured disease; the Medic always all (and clears cured cubes for free).
  Eradication happens when a cured disease has no cubes left.
- Undo (`Game.undo`) only covers turn actions of the current turn and is cleared by anything that reveals
  information or is out of turn (draws, events, discards).
- Invariants (checked over random games in `test_random_games_keep_the_invariants`): player cards always add up
  to 53 + epidemics, infection cards to 48, cubes on the board + supply to 24 per colour, max 3 per city,
  max 6 stations. `Game.clone()` must play identically.
- Bots get only `Game.view(seat)` → `View`, and try moves on `view.sandbox()` (hidden cards are placeholders).
  `act` answers when the game waits for the bot; `react` may return an event to play out of turn.
- `Planner(beam, noise, events)` searches a whole turn with `evaluate()`; Rookie is `beam=1, noise=0.25,
  events=False`. Tune with `uv run bg pandemic eval`.

# Web

## Server / room

- `Room` is synchronous table logic with no I/O; the platform's `boardgames/server.py` only moves JSON over WebSockets and serves
  `/api/config` (map, roles, events, bots) and the static client.
- Every change is broadcast as a full per-viewer snapshot (`Room.state_for`) with the engine events for
  animations. `_sees(viewer, seat)` decides hands; `_filter_event` blanks other players' drawn cards and Forecast
  cards when hands are closed. `turn_end` (events since the current draw) lets a reload rebuild the resolve panel.
- Bots, the autopilot and out-of-turn bot events run from `Room.plan()` → `(delay, step)`, driven by
  `Room.drive()`. Pauses before Continue are longer while a human holds a playable event (those don't follow
  `bot_speed`, which scales the rest). A `hold` request (sent when a player opens an event card) pauses all bots
  for up to `HOLD_MAX` seconds, once per seat per game step, only for seats that hold an event; it ends when the
  game moves on or the card is put back.
- Host-only requests: settings, add_bot, remove_seat, shuffle, start, play_again, to_lobby, autoplay.

## Client (`static/`, no build step, no frameworks)

- Template strings + `innerHTML`; every user-provided text (names, chat) goes through `esc()`. Parts redrawn on
  every state (status, dock, side, popover, resolve, log, mode hint) go through `setHtml`, which skips identical
  markup so focus, hover, scroll, open `<details>` and CSS animations survive bot moves. The event feed is keyed
  (one element per line); a move's log lines join it together when its state arrives, so none flashes by.
- `store.js` the shared state `S` and accessors (`players()`, `me()`, `myTurn()`…); `net.js` `send` / `act`.
- `data.js` map/roles/events filled from `/api/config` (`initData`); `map-data.js` is generated by
  `scripts/pandemic/build_map.py` — don't edit it by hand.
- `rules.js` what you can do now and why not (move options, dock buttons, share/cure/events). Mirrors the
  engine only to enable buttons and explain; never adds advice or risk.
- `board.js` the SVG map: zoom/pan, labels in tiers by zoom, Pacific wrap labels, cubes, stations, pawns,
  highlights for map modes. `game.js` status bar, dock (actions + hand), side panel (team, discards, log, chat),
  city popover, resolve panel (draw → epidemic → infection), dialogs, forced dialogs (`syncForced`: hand limit,
  Forecast), menu, help. `app.js` home, lobby, connection, routing. `sound.js` synthesised effects.
- Action buttons show no keyboard letters; shortcuts are listed only in Help.
- Layout: ≤1279px the side panel becomes a slide-over; portrait or ≤760px wide stacks the dock; ≤600px is the
  phone layout (compact status, scrollable dock capped at 42dvh, popover/resolve as bottom sheets); a short
  landscape screen (≤520px tall) puts the dock beside the map. Check with `scripts/pandemic/sizes.py`.
- Map input: only a city's dot and visible label take pointer events (rings, cubes, stations overlap neighbours);
  a tap elsewhere goes to the nearest city within 22px (`nearestCity`). Drag pans, two fingers pinch-zoom, and
  the click that ends a drag or pinch is swallowed. Floating things on the map (event feed, mode hint) let taps
  through except for their buttons; the resolve panel hides while a map pick (move mode, Airlift, Grant) is on.
  The feed moves beside the resolve panel when the panel reaches the top of the map (`placeFeed`).
  The view can pan past the right edge by the map-button column and past the bottom edge by the mode hint, so
  no city stays stuck under them; the home view leaves room for the buttons.
- Handlers: never `el.onkeydown = (e) => cond && fn()` — a handler returning `false` cancels the event (that's
  how typing in the name field broke).
- Browser checks type with `keyboard.type`, tap on touch contexts and pinch through CDP: `scripts/pandemic/flow_check.py`
  plays a whole table with three people (desktop host, phone player, spectator who reloads); `ui_check.py` plays
  single-human games at any size.
