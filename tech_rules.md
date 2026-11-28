# Technical rules for every game

Every game on this platform follows these rules. They are general on purpose: a game may add its own rules in its
`CLAUDE.md`, but never break these. The how-to (layout, plug-in contract, commands) is in
[docs/platform.md](docs/platform.md); the measurements behind the performance rules are in
[docs/performance.md](docs/performance.md).

## 1. Structure

1. A game is one self-contained package `src/<game>/`: `game/` (rules engine), `bots/`, `web/` (room, spec,
   static client), plus its own `CLAUDE.md`, tests in `tests/<game>/` and scripts in `scripts/<game>/`.
2. Dependencies point one way: `game/` ← `bots/` ← `web/`. A game imports from the platform only what the plug-in
   contract offers (`boardgames.games`, `boardgames.table`); the platform reaches a game only through its spec.
3. Share what is genuinely shared (platform helpers, shared client modules); keep a copy only when the game
   intentionally differs.

## 2. Rules engine

1. Pure: no I/O, no asyncio, no clocks, no global state. All randomness comes from a seeded generator owned by the
   game, so any game can be replayed from its seed.
2. One source of truth for legality (`legal_actions` or equivalent). An illegal move raises and leaves the state
   untouched.
3. Invariants (cards conserved, counts in range…) are checked by a function and exercised by tests over many random
   games. Every rule has a test.

## 3. Server and room

1. The server is authoritative. Clients send intents only; every input is validated, nothing from a client is
   trusted.
2. Hidden information never leaves the server. Each viewer gets their own snapshot (`state_for`), and events sent
   for animation are filtered per viewer too. Tests assert that no snapshot or event leaks what a viewer may not see.
3. The room is synchronous, does no I/O, and builds on the shared table base (members, host, chat, log, driver).
   The host is always the room leader; the room never decides that itself.
4. Snapshots carry state, not catalogues. Data that never changes while the server runs (maps, card lists, rules
   text, bot lists) is served once from the game's config endpoint, not repeated in every message.
5. Everything automatic (bot moves, timeouts, round transitions) is planned by `plan()` and run by the table's
   driver; timers are computed from deadlines, never polled.

## 4. Bots

1. A bot sees only what a human in its seat would see: the engine's per-seat view, which is a copy, never a live
   reference into the game.
2. Nothing may block the event loop. A bot decision that can take more than a few milliseconds goes through
   `Table.think(key, compute)`: the key identifies the position and seat, the view is built before, and code before
   `think` in a step has no side effects.
3. A search with a time budget (it uses a full core for its whole budget) runs in a worker process via
   `think_apart`, and calls `prewarm_bots()` when such a bot takes a seat. Its bot object must be picklable and keep
   all its state (random generator included) on itself.
4. Bots draw randomness only from their own seeded generator. A bot's strength is part of the game: changing its
   budget, depth or speed is a game change.

## 5. Client

1. Vanilla ES modules, no build step, no frameworks. The client works inside the room page's iframe and on its own
   at `/g/<key>/r/CODE`. Its styles never leak out, and it uses the shared identity (token, name).
2. URLs: server routes come from `gameBase(import.meta.url)`; the game's own files are referenced relative to the
   module (`new URL("file", import.meta.url)`, relative imports, relative CSS `url()`); shared modules are imported
   from `/static/shared/`. Never hard-code `/g/<key>/static/...`: those links are not versioned and get revalidated
   on every load.
3. Render by patching, not rebuilding: update the existing DOM (`morph` or keyed updates); never re-create a whole
   view on each state.
4. An idle table draws no frames:
   - no permanent `requestAnimationFrame` or `setInterval` loops; per-frame drawing (a countdown) uses
     `frameLoop(draw, running)` and is kicked after every render;
   - animations that run while waiting for a player (pulses, glows, bobbing) animate only `transform` and
     `opacity` on HTML elements, which the compositor runs off the main thread. To pulse a shadow, put the shadow on
     a pseudo-element and animate its opacity. Animating `box-shadow`, `filter`, `fill`, `stroke`, sizes, or any
     property of an SVG child repaints the page every frame;
   - one-off animations (moves, flights, reveals) may use anything, as long as they end.
5. No long tasks: a state update renders well within one frame. Heavy work is spread or precomputed.
6. Clean up what you start: timers, listeners outside the game's own DOM, audio nodes. Closing the iframe must free
   everything.

## 6. Assets

1. All art is original. Prefer SVG and synthesised sound; they cost no requests.
2. Raster images are AVIF (or WebP), sized for how they are displayed (2× for high-density screens), at a quality
   indistinguishable from the source (SSIM ≥ 0.99; `scripts/platform/thumb.py` does this for tile thumbnails).
3. A game's tile thumbnail is `src/boardgames/static/thumbs/<key>.avif`, a 640 px wide screenshot of the running game.

## 7. Verification

A change is done when all of these pass:

1. `uv run pytest -n 8`: rules, hidden information, permissions, the web protocol.
2. `uv run python scripts/platform/ui_check.py` and the game's own `scripts/<game>/ui_check.py` (no JavaScript
   errors), plus a look at the screenshots.
3. `uv run python scripts/platform/perf_check.py`: event-loop blocking, idle CPU, warm reloads within budget.

A new game also registers itself in the shared tooling, so the checks cover it: a recipe in
`scripts/platform/bench_games.py` (which bot fills the seats), its demo stages in
`scripts/platform/compare_shots.py`, and, if its bots finish games quickly, in `perf_check.py`'s server games.
