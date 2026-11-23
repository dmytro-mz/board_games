<!-- Built from docs/phase10/rules/*.mdc (the original repo's rules), adapted to this repo. The root CLAUDE.md rules apply too. -->

# Phase 10 — project map

Goal: an online Phase 10 for friends — the complete game, a hand the player arranges and builds groups from
by themselves (the game never suggests combinations), bots good enough to fill empty seats, and a table that
works in any window size.

## Layout and dependency direction (never import "upwards")

```
phase10/game/      rules engine, pure Python, no I/O                  (lowest layer)
  model.py         Card, deck, Req, PHASES
  rules.py         group validation (set_value / run_lows / color_of) and Group (build, ends_for, add)
  actions.py       action dataclasses + JSON protocol
  engine.py        Game state machine: Game.play(seat, action) -> events, Game.view(seat), Game.arrange
phase10/bots/      Bot ABC · solver.py (deficit of a hand for a phase, lay-down plan) · planner.py · registry
phase10/runner.py  play_game(bots, seed, rules)
phase10/web/       room.py (sync table logic, no I/O) · spec.py (its tile and backend on the platform; server: boardgames)
                   static/ (vanilla ES-module client, no build step)
phase10/cli.py     typer CLI, mounted as `bg phase10 …`
scripts/           demo / shot / sizes / ui_check (visual + browser checks)
```

## Commands (always via uv, never pip; in the sandbox `export UV_CACHE_DIR=.uv-cache`)

- Tests: `uv run pytest` (must pass before you say you're done)
- Lint/format: `uv run ruff check --fix src tests scripts && uv run ruff format src tests scripts`
- Play: `uv run bg serve` (LAN) · `uv run bg serve --tunnel` (public link via cloudflared)
- Bot strength: `uv run bg phase10 eval -a pro,regular,rookie -n 300`
- See the UI: `uv run python scripts/phase10/demo.py --stage home|lobby|play|drawn|laid|handover|over --out shots/x.png`
- Click through a whole game in Chrome: `uv run python scripts/phase10/ui_check.py [--size WxH] [--phases N]`
- Every screen at phone → 1920 sizes: `uv run python scripts/phase10/sizes.py` (fails on any overflow; shots in `shots/sizes/`)

## Working agreements

- The server is authoritative; clients only send intents. Never trust client input.
- No assistance: the engine and the client never group, suggest or auto-complete combinations. The client only
  validates what the player staged (mirroring `rules.py` messages) and asks when a choice is ambiguous.
- Hands are never sorted by the game; new cards go to the end. Only the player reorders (`arrange`).
- Any rules change goes in `game/` with a test in `tests/phase10/test_engine.py`; keep `cards.js` validation in sync.
- UI changes: render with `scripts/phase10/demo.py`, look at the screenshot, run `scripts/phase10/ui_check.py` and `scripts/phase10/sizes.py`.
- `shots/` and `tmp/` are scratch output (gitignored).

# Rules engine

- `Game.play(seat, action)` validates everything and raises `IllegalMove` with a player-facing message,
  leaving the state untouched. It returns events (`deal`, `draw`, `lay_down`, `hit`, `discard`, `skipped`,
  `reshuffle`, `dry`, `out`, `hand_over`, `tiebreak`, `game_over`) that the room narrates and the client animates.
- Turn: DRAW (deck or discard, never a Skip) → PLAY (lay down the whole phase at once, then hits; discard ends
  the turn). Going out can happen by discarding, hitting or laying down the last card.
- Every group needs a natural card; groups may be longer than required. Runs store `low`; wilds take the gaps
  and a lone wild on a run asks which end (`Hit.end`).
- Skip: the discarder picks the target (`skip_targets`); not yourself, not someone with a Skip in front of
  them. The card lies in `skip_cards[target]` (not on the discard pile) until the target's turn is skipped,
  then goes onto the discard pile. House rule `RulesConfig.skip_cooldown`: also not someone who lost a turn and
  hasn't played since (`skip_spent`). One target left: automatic.
- End: fewest points among the finishers of the last phase. A tie on points sets `tied`: only those seats are
  dealt in (`active`) to replay the last phase, and the first of them to go out wins.
- `card_count()` must always be 108 (tests check it after every move of random games).
- Bots get only `Game.view(seat)`; they must never read other hands or the draw pile order.

# Web

## Server / room

- `Room` is synchronous table logic with no I/O; the platform's `boardgames/server.py` only moves JSON over WebSockets.
- Every change is broadcast as a full per-viewer snapshot (`Room.state_for`) with the engine events for
  animations. Only your own hand is sent; `_filter_event` blanks the card of other players' deck draws.
- `options` is sent only to the current, non-autoplay player. `arrange` answers only the sender (same `seq`).
- Bots, timeouts, autopilot and dealing the next hand run from `Room.plan()` → `(delay, step)`, driven by
  `Room.drive()`. Between hands the room waits for every connected human to press Ready (no forced deal, no timeout).

## Client (`static/`, no build step, no frameworks)

- `dom.js` `h()` builds DOM and skips `null` children — native `replaceChildren` / `append` don't.
- `cards.js` CSS cards sized by `--cw` (everything inside is in `em`), plus a mirror of the group rules with
  the same messages as `rules.py`.
- `hand.js` the hand: click selects, pointer drag reorders (FLIP) or drops on `[data-drop]` targets
  (`discard`, `group:ID`, `slot:I`). Move/up listeners live on `window` because reordering moves the element.
- `app.js` home, lobby, table (opponents · piles · my phase zone with staging slots · dock with status, actions,
  hand), popovers, dialogs, hand-over and game-over modals. Staged groups live only in the client until the
  phase is laid down. `sound.js` synthesised effects.
- Layout: short (≤760px high) or narrow (≤760px wide) windows put the piles beside the phase zone; ≤1100px the
  side panel becomes a slide-over; ≤520px opponents become one row each. Check with `scripts/phase10/sizes.py`.
