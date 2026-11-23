<!-- Built from docs/avenue/rules/*.mdc (the original repo's rules), adapted to this repo. The root CLAUDE.md rules apply too. -->

# Agent Avenue — project map

Goal: an online Agent Avenue (official rules: simple mode, advanced mode, team variant) for friends, with a
strong bot that only knows what a human player would know, nice SVG animal art and animations.

## Layout (never import "upwards")

```
avenue/game/     cards.py (board + card data), engine.py (Game state machine), actions.py (JSON protocol)
avenue/bots/     heuristic.py (features, evaluation, fast policy), search.py (Mastermind: determinised MC)
avenue/web/      room.py (sync table logic, no I/O), spec.py (its tile and backend on the platform; server: boardgames), static/ (vanilla JS)
avenue/cli.py    `avenue serve` / `avenue eval`
scripts/         demo.py, shot.py, ui_check.py, frames.py (browser checks), duel.py, fit_eval.py (bot work)
```

## Invariants (tested)

- The rulebook wins. Every rule lives in `game/engine.py` with a test in `tests/avenue/test_engine.py`.
- 38 agent cards and 15 black market cards are conserved at every step.
- `Game.step` raises `IllegalMove` and leaves the state untouched for illegal actions.
- Bots get `Game.redacted(player)` only (hidden cards are -1). The heuristic policy never reads other hands,
  the deck order or a face-down card it didn't play — it runs inside determinised games.
- Clients get per-viewer snapshots (`Room.state_for`); `_filter_event` hides draws, discards and face-down cards.

## Commands (always via uv)

- Tests: `uv run pytest` · Lint: `uv run ruff check --fix src tests scripts && uv run ruff format src tests scripts`
- Play: `uv run bg serve` · Bot match: `uv run bg avenue eval -n 200 [--advanced]`
- UI: `uv run python scripts/avenue/demo.py --stage play --mode advanced`, then `scripts/avenue/ui_check.py` (fails on JS errors)
- Animations: `uv run python scripts/avenue/frames.py --stage recruit` (contact sheet in shots/frames/)
