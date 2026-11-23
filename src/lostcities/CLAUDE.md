<!-- Built from docs/lostcities/rules/*.mdc (the original repo's rules), adapted to this repo. The root CLAUDE.md rules apply too. -->

# Lost Cities — project map

Goal: an online two-player expedition card game for friends — the complete rules, a warm table-top look with
original card art, and bots good enough to play against.

## Layout and dependency direction (never import "upwards")

```
lostcities/game/      rules engine, pure Python, no I/O                  (lowest layer)
  cards.py             Card, the 60-card DECK, colours/sites, can_extend
  scoring.py           score_expedition / score_player
  actions.py           Play / Discard / Draw + JSON protocol
  engine.py            Game state machine: step(seat, action) -> events, next_round(), view(seat), check()
lostcities/bots/      Bot ABC + heuristic player + REGISTRY (every entry appears in the lobby)
lostcities/runner.py  play_game(bots, rounds, seed)
lostcities/web/       room.py (sync table logic, no I/O) · spec.py (its tile and backend on the platform; server: boardgames)
                       static/ (vanilla ES-module client, no build step)
lostcities/cli.py     typer CLI, mounted as `bg lostcities …`
scripts/               demo / shot / ui_check (visual + browser checks)
```

## Commands (always via uv, never pip)

- Tests: `uv run pytest` (must pass before you say you're done)
- Lint/format: `uv run ruff check --fix src tests scripts && uv run ruff format src tests scripts`
- Play: `uv run bg serve` (LAN) · `uv run bg serve --tunnel` (public link via cloudflared)
- Bot strength: `uv run bg lostcities eval -a veteran,pathfinder -n 2000`
- See the UI: `uv run python scripts/lostcities/demo.py --stage home|lobby|play|draw|round|over --out shots/x.png [--size 390x844]`
- Click through a whole match in Chrome: `uv run python scripts/lostcities/ui_check.py` (fails on any JS error)

## Working agreements

- The server is authoritative; clients only send intents. Never trust client input.
- Any rules change goes in `game/` with a test in `tests/lostcities/test_engine.py`.
- UI changes: render with `scripts/lostcities/demo.py` (desktop and 390x844), look at the screenshot, run `scripts/lostcities/ui_check.py`.
- All art is original SVG in `static/art.js`; never copy the published game's artwork or rulebook text.
- `shots/` is scratch output (gitignored).

# Rules engine

- Card ids: `"red-7"` for numbers, `"red-w0".."red-w2"` for the three wagers of a colour (value 0).
- Turn = PLAY (`Play` onto your expedition or `Discard`) then DRAW (`Draw("deck")` or `Draw(color)`), never from
  `last_discard`. The round ends right after the draw that empties the deck → ROUND_OVER (`next_round()`), or
  GAME_OVER after `Game.rounds` rounds. Next round: the higher round score starts; on a tie, whoever didn't start.
- `Game.undo(seat)` takes back the turn's play/discard while still in DRAW (`can_undo`); it is not an `Action`,
  so bots and `legal_actions` never see it. The room exposes it as `{"type": "undo"}` and `game.can_undo`.
- Scoring: `(sum − 20) × (1 + wagers)`, +20 (not multiplied) for ≥ 8 cards; unstarted expedition = 0.
- `legal_actions(seat)` is the single source of truth; `step` raises `IllegalMove` and leaves state untouched.
- `Game.check()` holds after every step: all 60 cards exactly once, expeditions ascend with wagers first, hand sizes.
- `Game.view(seat)` is all a bot may see: own hand, both expeditions, full discard piles (public memory), deck size.
- Randomness only through `Game.rng` / `Bot.rng`, seeded, so games are reproducible.

# Web

## Server / room

- `Room` is synchronous table logic with no I/O; the platform's `boardgames/server.py` only moves JSON over WebSockets.
- Exactly two seats (humans or bots), extra visitors are spectators. Status: lobby → playing ⇄ round_over → game_over.
- Every change is broadcast as a full per-viewer snapshot (`Room.state_for`). Only the viewer's own `hand` is sent;
  `_filter_event` blanks the card of an opponent's deck draw. Full discard piles only with `settings.peek` or between
  rounds, when both `hands` are revealed. `tests/lostcities/test_web.py` checks all of it.
- `legal` (action JSON) is sent only to the current, non-autoplay player; the client renders from it.
- Bots, timeouts, autopilot and round transitions run from `Room.plan()` → `(delay, step)`, driven by `Room.drive()`.
  Between rounds every online human sends `ready`; with no human online the next round starts by itself.
- Players are identified by a random token in localStorage; `/r/CODE?me=TOKEN` moves a seat to another device.

## Client (`static/`, no build step, no frameworks)

- `dom.js` `h()` / `s()` build HTML / SVG and skip `null` children. Screens re-render through `morph(parent, nodes)`,
  which patches the existing DOM (matching children by `data-key` / `id`, else by order) instead of replacing it,
  so a settings switch or a card selection only touches what changed. Never `replaceChildren` a live view.
- `art.js` all artwork as `<symbol>`s in one hidden SVG: per-site landscapes and cities (the city grows with the
  value), the wager scene, emblems, the card back. `cardFace(id)` / `cardBack()` return elements.
- `app.js` home, lobby, the table (CSS grid: side column + 5 colour columns; rows: rival lanes, camp, your lanes),
  hand with click / drag / keyboard, FLIP animations keyed by `data-key` = card id, round summary overlay.
  A flight is drawn by a stand-in clone in `<body>` above everything while the real card stays invisible at its
  destination (`flyFromRect`), so moving cards never pass under lanes or the hand. Newest card is on top in both
  players' lanes; a rival's cards stack upward and show their (upright) bottom band.
  `scripts/lostcities/anim_frames.py` films a play, a draw and the bot's answer in slow motion into `shots/anim/`.
  Card sizes are CSS variables computed in `computeLayout()` from the window size only, never from the number of
  cards out: each expedition strip is a fixed `LANE` card heights tall and longer expeditions stack tighter.
  Modes: landscape (turn prompt in the side column when it fits, else above the hand), `short`, and `portrait`
  (phones: 5 columns, plates and deck as rows). `scripts/lostcities/ui_check.py --size WxH` asserts nothing gets rebuilt.
- `sound.js` synthesised effects.
