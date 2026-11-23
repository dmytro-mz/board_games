<!-- Built from docs/ttr/rules/*.mdc (the original repo's rules), adapted to this repo. The root CLAUDE.md rules apply too. -->

# Ticket to Ride: Europe — project map

Goal: an online Ticket to Ride: Europe for friends — complete official rules, a board that looks and feels
like the real one, and bots good enough to fill empty seats.

## Layout and dependency direction (never import "upwards")

```
ttr/game/          rules engine, pure Python, no I/O                  (lowest layer)
  model.py         City / Route / Ticket / MapData, card constants, route points
  europe.py        the Europe map: cities (measured on the board photo), routes, tickets
  rules.py         pure helpers: payments, tunnels, doubles, stations, longest path
  actions.py       action dataclasses + JSON protocol
  engine.py        Game state machine: Game.step(seat, action) -> events, Game.view(seat)
ttr/bots/          Bot ABC + planner (Rookie / Conductor / Expert) + registry
ttr/runner.py      play_game(bots, seed)
ttr/web/           room.py (sync table logic, no I/O) · spec.py (its tile and backend on the platform; server: boardgames)
                   static/ (vanilla ES-module client, no build step)
ttr/cli.py         typer CLI, mounted as `bg ttr …`
scripts/           map tracing from the board photo (assets/): find_cities,
                   trace_land -> land.json, build_land (borders), overlay/crop/city_sheet (checks)
                   demo/ui_check/shot/board_shot (visual + browser checks)
```

## Commands (always via uv, never pip)

- Tests: `uv run pytest` (must pass before you say you're done)
- Lint/format: `uv run ruff check --fix src tests scripts && uv run ruff format src tests scripts`
- Play: `uv run bg serve` (LAN) · `uv run bg serve --tunnel` (public link via cloudflared)
- Bot strength: `uv run bg ttr eval -a expert,conductor -n 400`
- See the UI: `uv run python scripts/ttr/demo.py --stage play|tickets|over|lobby --out shots/x.png`
- Click through a whole game in Chrome: `uv run python scripts/ttr/ui_check.py` (fails on any JS error)

## Working agreements

- The server is authoritative; clients only send intents. Never trust client input.
- Any rules change goes in `game/` with a test in `tests/ttr/test_engine.py` or `tests/ttr/test_rules.py`.
- UI changes: render with `scripts/ttr/demo.py`, look at the screenshot, run `scripts/ttr/ui_check.py`.
- `shots/` is scratch output (gitignored).

# Rules engine

Implements the official Ticket to Ride: Europe rules. When in doubt, the rulebook wins; house rules
are opt-in `RulesConfig` flags (e.g. `double_min_players=2` lets 2–3 players use both tracks).

## Rules that are easy to get wrong

- Setup: 45 trains, 3 stations, 4 cards; offer 1 long + 3 short tickets, keep ≥ 2 (simultaneous).
  Returned long tickets leave the game; returned short tickets go under the pile.
- Drawing: 2 cards; a face-up locomotive taken first is the whole turn and can't be the second card.
  3 face-up locomotives wipe the market (guarded so it can't loop). Empty deck → reshuffle discards.
- Grey routes: any one colour. Ferries: at least `route.ferry` locomotives.
- Tunnels: payment is held aside, 3 cards revealed; each matching colour or locomotive costs one more
  card (only locomotives match an all-locomotive payment). Pay or decline — declined cards go back.
- Double routes: with < 4 players only one track may be used; nobody ever owns both tracks.
- Stations cost 1/2/3 cards of one colour, one per city; each borrows one opponent route into its city
  for tickets (`rules.best_station_use` tries every choice). Unused stations: 4 points each.
- End: a turn ending with ≤ 2 trains starts the last round — everyone, the trigger player included,
  gets exactly one more turn. European Express (+10) to every player tied for longest path.
- Tie-break: most completed tickets, then the Express.

## Invariants (tested)

- Card conservation: deck + discard + face-up + hands (+ tunnel held/revealed) == 110 at every step.
- `Game.view(seat)` is all a bot may see; it never contains other hands or tickets.
- `Game.step` raises `IllegalMove` and leaves state untouched for illegal actions.
- Map: 47 cities, 46 tickets, ticket values within 1 of the shortest path, twins are symmetric.

## Map data

Everything is traced from the board photo `scripts/assets/board_photo.jpg`; never invent geometry.

- City positions in `europe.py` are photo pixels (template-matched with `scripts/ttr/find_cities.py`),
  mapped by `_board()`; `label` (n/s/e/w/ne/nw/se/sw) is where the name sits on the photo.
- Route shapes are hand-kept polylines in `europe_paths.py` (`Route.path` = bend points between the two
  cities, `Route.side` = track of a double): a few straight pieces with clean bends like the printed board, no
  wobble, no two routes running side by side. After moving a city or adding a route, edit them there and check
  with `uv run python scripts/ttr/board_shot.py out.png --view x,y,width`.
- Coastlines: `scripts/ttr/trace_land.py` segments land/sea from the photo into `land.json`
  (`build_land.py` only supplies the Natural Earth borders).
- Check with `scripts/ttr/overlay.py OUT.png --routes --land --tiles` and `scripts/ttr/board_shot.py`.

# Web

## Server / room

- `Room` is synchronous table logic with no I/O; the platform's `boardgames/server.py` only moves JSON over WebSockets.
- Every change is broadcast as a full per-viewer snapshot (`Room.state_for`). Hidden information —
  other hands, other tickets and offers, blind-drawn cards — must never reach another client until
  the game is over (`_filter_event`, `_my_state`). `tests/ttr/test_web.py` checks this; keep it passing.
- Bots, timeouts and autopilot run from `Room.plan()` → `(delay, step)`, driven by `Room.drive()`.
- Players are identified by a random token in localStorage; `/r/CODE?me=TOKEN` moves a player to another
  device (that's how `scripts/ttr/demo.py` opens a seeded table).

## Client (`static/`, no build step, no frameworks)

- `dom.js` `h()` / `s()` build HTML / SVG and skip `null` children — but native `replaceChildren` /
  `append` do NOT (they print "null"): filter first.
- `board.js` draws the map: score track frame, the printed map art (painted once into one canvas
  bitmap — no tiled patterns, they show seams), routes as car rectangles along each route's traced
  `path` (offset by `side` for doubles), cities, labels, trains (raised pieces; the spaces underneath
  are hidden), stations, score markers.
- Pan/zoom/pinch only change a CSS transform while the gesture runs; the viewBox is committed after
  a short idle. Keep SVG filters, image patterns and infinite animations off the board — every
  re-raster pays for them and the map flashes.
- `cards.js` train cards, ticket cards (mini map uses `<use href="#land-sym">`), colour chips.
- `app.js` home, lobby, game layout (board · market · dock · side panel), popovers and dialogs.
- Avoid generic class names that collide with layout classes (`.game`, `.board`, `.panel`...).
- After UI changes: `uv run python scripts/ttr/demo.py ...` and look at the PNG; then `scripts/ttr/ui_check.py`.
