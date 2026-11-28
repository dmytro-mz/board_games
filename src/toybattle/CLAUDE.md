# Toy Battle — project map

Goal: a two-player duel of toy armies in the browser that plays by the rules of the published game TOY BATTLE
(official rulebook + player aid), and one very strong bot that only knows what a player at the table would know.

## Layout and dependency direction (never import "upwards")

```
toybattle/game/       rules engine, pure Python, no I/O                          (lowest layer)
  troops.py        48 troop ids (side*24 + kind*3 + copy), KIND_INFO (names, effects, texts), beats()
  terrains.py      the 8 terrains as data: nodes (base/special/hq), paths, medal regions, objectives, palettes
  engine.py        Game state machine: step(seat, action) -> events, legal_actions, view(seat), from_view, check()
toybattle/bots/       Bot ABC · evaluate.py (static evaluation, immediate wins/threats) · general.py (search) · REGISTRY
toybattle/runner.py   play_game(bots, terrain, special, seed)
toybattle/cli.py      `bg toybattle eval` (bot vs bot per terrain: win rates, colour/starter balance, how games end)
toybattle/web/        room.py (sync table logic, bots think in a worker process) · spec.py (tile + backend) · static/ (client)
```

## Commands

- Tests: `uv run pytest tests/toybattle -n 8` (and the whole suite before you say you're done)
- Bot strength / terrain balance: `uv run bg toybattle eval -a general,g:w3:t8:b5 -n 100 [-t rug,lava]`
  (`g:w3:t8:b5-3` = a General with 3 worlds, top 8 candidates, beams 5 then 3, no clock)
- See the UI: `uv run python scripts/toybattle/demo.py --stage lobby|play|effect|over [--terrain lava] [--red]
  [--size 390x844] --out shots/toybattle/x.png` (`SHOT_CLICK=css` clicks something first)
- Click through a whole game in Chrome: `uv run python scripts/toybattle/ui_check.py [--terrain attic] [--size 390x844]
  [--red] [--motion]` (fails on JS errors, a rebuilt lobby/board, a stuck table)

## Rules engine (`game/engine.py`)

- Turn = `draw` (2 troops, rack max 8, fewer if the rack or the reserve runs short) or `place(troop, node)`, then
  effects. A slot is legal when it is connected (next to the own H.Q. or to an own top connected to it), and empty,
  own, an enemy top the troop `beats` (strictly stronger; jokers cover and are covered by anything), or the enemy
  H.Q. Kind 4 (Paper Plane) ignores the connection except for the enemy H.Q. and shielded special bases.
- Effects become decisions in `Phase.EFFECT` (`pending`), `skip` always legal; effects that can't do anything are
  skipped silently. Troop effects form a stack (a drummer's extra troop resolves its own effect first), special
  base effects a queue in placement order after all troop effects; a base effect is dropped if its troop no longer
  tops that base. Draw / magnet / sandpit effects are a single `take`.
- Regions are checked after every board change for both players; medals are kept forever. Objective reached or
  enemy H.Q. taken → game over at once. A player who at the start of their turn can neither draw nor place ends
  the game: more medals wins, a tie loses for the stuck player.
- Setup: each side removes 4 unseen troops; the starter (random) draws 3, the other 4.
- Hidden information: own rack only; `known` holds rack troops the opponent has seen (recalled / revived ones).
  `Game.view(seat)` is all a bot gets; `Game.from_view(view, rng)` deals the unseen troops at random
  (determinization). `check()` holds after every step (every troop exactly once, rack ≤ 8, medal sums…).

### Rulings (where the rulebook is silent; follow these, they are in the in-game rule book too)

Joker may cover a joker. Effects touch visible (top) troops only. Shielded bases (Station Metal-X) cancel only the
placed troop's own effect, and a Paper Plane can't airdrop onto one it isn't connected to. Restricted bases (Tropical Pool)
and both H.Q.s there take only the printed strengths; a joker always fits. Magnet: random troop of the
rack, pinned or not, to the discard. Battlefield: random unpinned rack troop is pinned until the end of its owner's
next turn, still counts towards 8. Recalled / revived troops are public. Hot floor: push an adjacent visible enemy
troop to any base next to it, ignoring placement rules, never onto an H.Q. A full rack can't recall / revive.

### Terrains

| key | name | special bases | objective |
| --- | --- | --- | --- |
| rug | Castle Field | recall: own other troop back to the rack | 7 |
| lagoon | Tropical Pool | restrict: printed strengths only (rings 1/2, 3/4/5, 6/7; the four H.Q.s 6/7); two H.Q.s per side, capturing either wins. Layout follows the published map (owner decision) | 6 |
| pillow | City of Clouds | draw 1 (4 special bases in a column, 10 outer bases); layout follows the published map (owner decision) | 8 |
| lava | Volcanic Jungle | move an adjacent enemy troop (2 bridge platforms); layout follows the published map (owner decision) | 7 |
| attic | Cursed Cemetery | revive a troop from the discard (4 pumpkins); layout follows the published map (owner decision) | 7 |
| gutter | Caribbean Sea | none; Blue has two H.Q.s; layout follows the published map (owner decision) | 5 each |
| workshop | Station Metal-X | shield: no troop effect there (3 shielded plates in the middle row); layout follows the published map (owner decision) | 7 |
| sandpit | Battlefield | pin a random rack troop of the opponent (4 bunkers); layout follows the published map (owner decision) | 8 |

`tests/toybattle/test_terrains.py` checks every board: no crossing paths, regions closed by paths with nothing inside,
symmetric boards are point-symmetric with equal objectives.

## Bot (`bots/`)

- `REGISTRY` has exactly one entry, `general` (the lobby offers only it). `ALL` adds `greedy` / `random` baselines
  for tests and `bg toybattle eval`; `make_bot("g:…")` builds experimental Generals.
- The General never sees the game, only its `View`. Per decision it deals several worlds with `Game.from_view`,
  keeps the most promising candidate actions (deduplicated by kind/node), finishes its own turn greedily, then
  searches whole turns ahead with beams (opponent's answer, then its own reply), scoring with `evaluate.Evaluator`.
  The candidate with the best average over the worlds is played. Draw / magnet / sandpit effects are always taken.
- `Evaluator`: terminal ±WIN; an immediate win for the side to move (H.Q. reachable, incl. Tin Drummer chains, or
  objective reachable with one placement) ±0.9 WIN; an immediate threat of the other side that no single placement
  (cover, block, Slingshot knock) parries −0.85 WIN; else medals, region potential, connected / reachable bases,
  H.Q. guards, path cost to the enemy H.Q., rack and reserve. Antisymmetric (tested).
- The room gives it a thinking budget (`Room.bot_budget`, 1.2 s by default) and runs it in a worker process (`boardgames.table.think_apart`: its own core, the event loop stays free).

## Web

- `Room` (sync, no I/O) follows `boardgames.table.Table`, but overrides `drive()` (bots think in a worker process while
  browsers animate; `busy_until` from the animated events) and has `step_bots()` for tests/scripts.
- Settings: `terrain` (key or "random", picked at the top of the lobby), `special` (special bases on/off),
  `turn_timer` (autopilot finishes the turn), `bot_speed`. No hints, no undo (the owner asked for no player help).
- `state_for`: own rack in full; opponent's as count + pinned count + publicly known troops; reserves as counts;
  removed troops only after the game; draw events blank the troops for everyone but the drawer; a sandpit pin event
  names the troop only for its owner (or if it was public). `tests/toybattle/test_web.py` checks it.
- Client (`static/`): `art.js` SVG toys (shaded, army colour via CSS variables) / fort / medal / bag /
  special-base icons, and the troop tile: one SVG per tile with a per-army frame (`frame-<side>`), the toy on a mesh
  screen, the strength on a tab at the top (★ for the joker) and the effect as a badge in the corner (`KIND_EFFECT`,
  badges hide below 36 px via a container query); `board.js` draws a terrain inside a raised rim: terrain
  coordinates are 100 × 160, the drawing adds `PAD` all round (`BW` × `BH`, use `pct()` to place things on it) so
  forts and edge tiles are never clipped (floor art per palette, regions with ribbon medals, paths, socket bases,
  forts), turned 180° for Red so everyone has their H.Q. at the bottom; occupied special bases keep a small pin; a tap on a special base (or a Tropical Pool ring) that isn't a move opens a bubble with its effect (`baseInfo`, `S.ui.info`); `app.js` lobby (terrain picker on top, invite link
  in the top bar, no tunnel talk), table (board + HUD; `wide` and `tall` layouts from the window size; your rack shows its 8 sockets, wide screens add a troop guide), click or
  drag a troop then a glowing slot, effect prompts, animations (troops fly in an arc and stomp, knock-offs spin to
  the discard, medals fly to the counter, the fort shakes when it falls), end-of-game results; `rules.js` the rule
  book (lobby, top bar, menu); `sound.js` synthesised sounds.
