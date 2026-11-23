<!-- The root CLAUDE.md rules apply too. Background: docs/avel/README.md. -->

# Chronicles of Avel — cooperative, 1–4 heroes, humans and bots mixed

```
avel/game/      rules engine: Game.step(seat, action) -> events; legal_actions is the source of truth
                model.py (tiles, monsters, equipment, craters), backpack.py (tetris backpack), actions.py
avel/bots/      HeroBot ("knight", sensible) and "squire" (random); BOT_TYPES
avel/web/       room.py (Table subclass: seats, settings, turn timer, hints) · spec.py (tile, catalogue for the client)
                static/ (vanilla ES modules: board, tiles, monsters, items, scenery art)
avel/cli.py     `bg avel eval --games 200 --players 2` (bot-only win rate)
```

- Rules follow the rulebook (2 actions per turn, 4 solo; moon track, Black Moon, march, walls, traps, seals; Beast
  toughness 14/14/17/20 by player count). One simplification: bag draws are random (no blind pulling).
- A disconnected player's hero is played by a bot until they return; the turn timer hands the turn to a bot.
- Tests: `tests/avel/` (engine rules, full bot games, server protocol).
