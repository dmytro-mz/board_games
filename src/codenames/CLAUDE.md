<!-- The root CLAUDE.md rules apply too. Background: docs/codenames/README.md. -->

# Codenames — two teams, spymasters and operatives, 4+ people, no bots

```
codenames/game/   rules engine (pure) and decks.py (words_en/words_pl, the picture deck in data/pictures;
                  picture URLs are served by the platform under /g/codenames/deck-pictures, see URL_ROOT)
codenames/web/    room.py (Table subclass; members join a team and a role instead of seats) ·
                  spec.py (tile, decks, `--codenames-pictures`, solo test mode `--codenames-test`)
                  static/ (vanilla ES modules)
```

- The server holds the key; it reaches spymasters only, operatives see it after the game. `tests/codenames/`
  checks it.
- A clue with number N allows up to N + 1 guesses (0 and ∞ allow any); a miss ends the turn; the assassin loses.
- Built for voice chat: the clue word is optional, the number is required. Clicking a card points at it, a second
  click reveals it.
- Browser checks drive Chrome (`CHROME` in `scripts/codenames/demo.py`):
  `uv run python scripts/codenames/demo.py --stage guess --as spy` · `uv run python scripts/codenames/ui_check.py`
- Word lists and card pictures are third-party, see the credits in docs/codenames/README.md.
