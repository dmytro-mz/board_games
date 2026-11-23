<!-- The root CLAUDE.md rules apply too. Background: docs/skyteam/README.md. -->

# Sky Team — cooperative landing, exactly 2 players (Pilot, Co-Pilot), no bots

```
skyteam/game/      engine.py (Game.apply(seat, action), view(seat): each pilot sees only their own dice)
                   scenarios.py (all 21 scenarios, modules, special abilities)
skyteam/progress.py  finished scenarios in ./progress.json (gitignored; `bg serve --skyteam-progress FILE`)
skyteam/web/       room.py — its own small Room (it never had the shared Table skeleton): members keyed by token,
                   `status` derived from the game, `drive()` ticks the real-time module's clock
                   spec.py (tile, scenarios, progress) · static/ (vanilla ES modules, SVG cockpit)
```

- Communication rules are part of the game: no chat; a speech-bubble symbol says when talking is allowed.
- The in-game Leave menu takes both pilots back to the game's lobby; from there the room leader can go back to the
  game selection.
- Dev helpers in `scripts/skyteam/` expect a running server: `uv run bg serve --port 8765`, then e.g.
  `uv run python scripts/skyteam/two_players.py`. Balance check: `uv run python scripts/skyteam/solve.py 5`.
