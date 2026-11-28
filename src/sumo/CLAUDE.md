# Marble Sumo — project map

Goal: a two-player marble-pushing duel on a 61-cell hexagon in the browser (the classic push-six-out rules), with
bots from gentle to strong. Name, art and texts are our own (the owner asked for "Abalone"; the game uses its
public rules, not its name or look). Black moves first; the first to push six rival marbles off the ring wins.

## Layout and dependency direction (never import "upwards")

```
sumo/game/       rules engine, pure Python, no I/O                               (lowest layer)
  board.py       axial cells (q, r), NEIGHBOR table, RING, names "A1".."I9" (A at Black's side), the 3 LAYOUTS
  engine.py      gen_moves / apply / undo on a plain cell list (shared with the bots), Move (public JSON),
                 Game (cells + stable marble ids + out/lost, step, resign, move limit, check), View
sumo/bots/       base.py (Bot, RandomBot) · search.py (SearchBot: alpha-beta) · REGISTRY / ALL / make_bot
sumo/runner.py   play_game(bots, layout, move_limit)
sumo/cli.py      `bg sumo eval -a yokozuna,ozeki -n 40 [-l classic,daisy] [--budget 0.5]`
sumo/web/        room.py (sync table, bots think in a worker process) · spec.py (tile + backend) · static/ (client)
```

## Commands

- Tests: `uv run pytest tests/sumo -n 8` (test_engine checks the generator against a brute-force reference)
- Bot strength: `uv run bg sumo eval -a d3,ozeki -n 16`
- See the UI: `uv run python scripts/sumo/demo.py --stage lobby|play|over [--layout daisy] [--white]
  [--size 390x844] --out shots/sumo/x.png` (`SHOT_CLICK=css` clicks something first)
- Click through a whole game in Chrome: `uv run python scripts/sumo/ui_check.py [--layout daisy] [--bot rookie]
  [--size 390x844] [--white] [--motion] [--limit 50]` (fails on JS errors, a rebuilt lobby/board, a stuck table)
- Film the push-out animation: `uv run python scripts/sumo/anim_frames.py [--white]` → `shots/sumo/anim/`

## Rules engine

- A move: 1–3 own marbles in a straight line, one step in one of 6 directions. In line (along the axis, or any
  direction for one marble): the head steps into an empty cell, or pushes rival marbles in that line when it
  outnumbers them (2 > 1, 3 > 1 or 2) and behind them is an empty cell or the edge (edge: the last one is out).
  Sideways (2–3 marbles, the other 4 directions): every target cell empty; never pushes. An own marble never
  leaves the board; a marble in front of an in-line group that is own means the group is longer (max 3).
- Internal move tuple `Mv = (tail, k, d, axis, j, cap)`; `gen_moves` returns pushes first (captures first).
- `Game.ids` gives every marble a stable id (0–13 Black, 14–27 White) so clients animate by id; `lost[side]` lists
  the ids pushed out, in order. Events: `move` (`marbles`, `dir`, `inline`, `pushed`, `out` cell, `paths`
  [[id, from, to|None]]), `resign`, `game_over` (`winner` None = draw, `reason` push | resign | limit).
- Move limit (setting, moves per player): at the limit, fewer marbles lost wins, equal is a draw.
- Layouts: `classic` (rows A–B + C3–C5), `daisy` (flowers at B2/H8 vs B5/H5), `wide` (C2/G8 vs C6/G4).

## Bots

- `SearchBot`: negamax, iterative deepening, TT (Zobrist), killers, capture-only quiescence. Incremental eval:
  1000 × marbles out, 12 × distance from the centre, 4 × touching pairs (antisymmetric, tested against a fresh count).
- Lobby: Rookie (depth 1, picks within 60 points of the best), Ozeki (depth 2), Yokozuna (time budget,
  `Room.bot_budget` 1.5 s, reaches depth 4–5). The autopilot (timer, disconnected players) is a depth-2 searcher.

## Web

- `Room` follows `boardgames.table.Table`, overrides `drive()` (bots think in a worker process (`think_apart`) while browsers animate;
  `busy_until` from the move animation) and has `step_bots()` for tests/scripts. `resign` is open to both seats.
- Settings: `layout` (or "random"), `move_limit`, `turn_timer` (autopilot moves), `bot_speed`.
- Client: `board.js` (geometry, SVG ring: earthen base, straw-rope border, clay floor, dimples; CSS marbles),
  `app.js` (lobby with opening cards, table with `wide` / `tall` layouts, board turned 180° for White),
  `rules.js` (rule book with move diagrams), `sound.js` (synthesised clacks and rolls).
- Input: tap marbles to build a line (tapping a marble two cells away in line fills the middle), then an arrow
  (red = push) or a glowing landing dimple; or drag a marble (the selection if it contains it, else the marble plus
  the own marbles right ahead of it). Esc clears.
- Animation: marbles are keyed by id; after a move each moved marble slides from its old rect (WAAPI); a pushed-out
  marble's ghost rolls onto the rope, drops and fades, then pops into the scorer's tray (6 sockets per player:
  the rival marbles they pushed out). Off with `prefers-reduced-motion`.
