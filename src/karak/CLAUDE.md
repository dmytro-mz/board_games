<!-- Built from docs/karak/rules/*.mdc (the original repo's rules), adapted to this repo. The root CLAUDE.md rules apply too. -->

# Karak — project map

Goal: an online Karak for friends — the complete game, a look that is unmistakably Karak (stone dungeon
tiles, round monster tokens, parchment hero sheet), and bots good enough to fill empty seats.

## Layout and dependency direction (never import "upwards")

```
karak/game/        rules engine, pure Python, no I/O                  (lowest layer)
  model.py         Pos/directions/exit masks, tile pile, items, monsters, bag, heroes
  rules.py         pure helpers: exact win odds, connectivity, neighbours
  actions.py       action dataclasses + JSON protocol
  engine.py        Game state machine: Game.step(seat, action) -> events, Game.view(seat)
karak/bots/        Bot ABC + planner (Squire / Adventurer / Champion) + registry
                   neural.py + models/*.npz (each model auto-registers as a bot)
karak/nn/          encoding.py (board -> planes/vector/action mask, VERSION) · forward.py (numpy inference)
karak/rl/          training only (torch): env, vec_env (worker processes), network, config, train (BC + PPO)
karak/runner.py    play_game(bots, heroes, seed)
karak/web/         room.py (sync table logic, no I/O) · spec.py (its tile and backend on the platform; server: boardgames)
                   static/ (vanilla ES-module client, no build step)
karak/cli.py       typer CLI, mounted as `bg karak …`
scripts/           demo / shot / ui_check (visual + browser checks), tune.py (bot configs)
configs/karak/           training YAMLs (bc, bc_finetune, ppo_champion, selfplay, smoke)
```

## Commands (always via uv, never pip; in the sandbox `export UV_CACHE_DIR=.uv-cache`)

- Tests: `uv run pytest` (must pass before you say you're done)
- Lint/format: `uv run ruff check --fix src tests scripts && uv run ruff format src tests scripts`
- Play: `uv run bg serve` (LAN) · `uv run bg serve --tunnel` (public link via cloudflared)
- Bot strength: `uv run bg karak eval -a champion,adventurer,squire -n 300`
- See the UI: `uv run python scripts/karak/demo.py --stage home|lobby|play|combat|over --out shots/x.png`
- Train / evaluate the AI: `uv run bg karak train -c configs/karak/<x>.yaml -s init=<policy.npz>` (runs in `runs/`, MPS,
  run outside the sandbox) · `uv run bg karak eval-ai <policy.npz> -n 500 [--opponent ai:<other.npz>]`
- Click through a whole game in Chrome: `uv run python scripts/karak/ui_check.py` (fails on any JS error)
- Every screen at phone → 1920 widths: `uv run python scripts/karak/sizes.py` (fails on any overflow; shots in `shots/sizes/`)

## Working agreements

- The server is authoritative; clients only send intents. Never trust client input.
- Any rules change goes in `game/` with a test in `tests/karak/test_engine.py`.
- UI changes: render with `scripts/karak/demo.py`, look at the screenshot, run `scripts/karak/ui_check.py` and `scripts/karak/sizes.py`.
- All art is original SVG in `static/art.js`; never copy the published game's artwork or rulebook text.
- `shots/` is scratch output (gitignored); so are `runs/` and `logs/`.
- `nn/` and `bots/` must not import torch (playing needs only numpy). Changing the encoding means bumping
  `encoding.VERSION` and retraining: old models are refused.

# Rules engine

## Model

- `Pos(x, y)` with y pointing down; directions N=0 E=1 S=2 W=3; exits are a 4-bit mask, `rotate` is clockwise.
- Points are stored in halves: treasure = 2, the Dragon's ruby = 3 (shown as 1½).
- Box: 79 tiles + the start tile, 53 tokens (incl. 10 chests and 1 dragon). Slots: 2 weapons, 3 spells, 1 key.

## Turn flow (phases)

TURN → (explore) PLACE → (room) CHOOSE_TOKEN for the Oracle → COMBAT → ROLLED → LOOT / CURSE → back to TURN or the
next player. REINCARNATE for the Warrior at 0 HP with several fountains. GAME_OVER when the Dragon falls.

- 4 moves per turn; exploring places a tile whose exit points back at the hero; one fitting rotation auto-places.
- Win: total > strength (Thief: ≥). Tie: retreat. Loss: retreat and −1 HP; 0 HP = unconscious (skip a turn,
  recover), the Warrior instead rises at a fountain. A fight ends the turn unless the Swordsman rolled a 6.
- Retreat goes to the last tile of the turn without a monster. The Thief may slip past a monster only with a move
  left and can't end her turn on its tile, so no hero ever stands on a monster between turns.
- Ending a turn on a healing tile (start or fountain) heals fully and lifts the Curse.
- House rule: if the labyrinth can't grow and the Dragon is still in the bag, it wakes in the farthest empty room.

## Karak: Regent (`RulesConfig(expansion=True, lord=True)`, tests in `tests/karak/test_regent.py`)

- Off by default: base games keep the exact 79-tile pile, 53-token bag and the 6 `BASE_HEROES` (the trained network
  and `nn/encoding.py` only know those; `Hero` also holds the Regent heroes and `Hero.LORD`).
- `Game.actor` is who must act: the current hero, except the summoned hero in the second half of an arena duel and
  the duel winner choosing spoils. `legal_actions` / `step` / `Room` all go through `actor`, not `current`.
- Skills are a set per player (`Player.skills`); the Lord of Karak holds several. Always ask `has_skill`, never `hero ==`.
- Arena: `Tile.spent` once fought in. Cursed chamber rolls a die on entry and on being thrown back onto it.
  Berserk heal choice is `EndTurn(heal_to)`; the acrobat's spare daggers live in spell slots (`carry_slot`).
- Strengths of the bat (6) and ice mage (11) are our own choice: the rules text doesn't print them.

## Invariants (tested)

- `legal_actions(seat)` is the single source of truth; `Game.step` raises `IllegalMove` and leaves state
  untouched for anything else.
- Tiles + pile + pending == 80 (98 with the expansion); slot limits and HP bounds hold at every step.
- `Game.view(seat)` is all a bot may see; the pile and bag order are hidden.
- Every hero skill has a test; keep them when changing combat.

# Web

## Server / room

- `Room` is synchronous table logic with no I/O; the platform's `boardgames/server.py` only moves JSON over WebSockets.
- Every change is broadcast as a full per-viewer snapshot (`Room.state_for`). The Oracle's offer goes only to
  her (`offer`), and `_filter_event` hides offered / returned tokens from others. `tests/karak/test_web.py` checks it.
- `legal` (action JSON) is sent only to the current, non-autoplay player; the client renders from it.
- Bots, timeouts and autopilot run from `Room.plan()` → `(delay, step)`, driven by `Room.drive()`.
- Players are identified by a random token in localStorage; `/r/CODE?me=TOKEN` moves a seat to another device.

## Client (`static/`, no build step, no frameworks)

- `dom.js` `h()` / `s()` build HTML / SVG and skip `null` children — native `replaceChildren` / `append` don't.
- `art.js` all artwork as `<symbol>`s in one hidden SVG, drawn with `<use>`; heroes, monsters, items, dice.
- `board.js` the labyrinth: cached tile symbols per (kind, mask, variant), tokens, floor items, clickable
  spots (`data-act` = action JSON), the ghost tile with ⟲ ⟳ ✓, hero pawns moved by CSS transforms.
  ViewBox pan/zoom; it auto-fits until the user pans.
- `app.js` home, lobby, game layout (board · dock with hero sheet and action bar · side panel), combat and
  other float panels, popovers, dialogs, keyboard controls. `sound.js` synthesised effects.
- After UI changes: `uv run python scripts/karak/demo.py ...` and look at the PNG; then `scripts/karak/ui_check.py`.
