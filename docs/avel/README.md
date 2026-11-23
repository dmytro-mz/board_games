# Chronicles of Avel

A browser version of the cooperative board game for 1–4 heroes. You can mix humans and bots, and it works from
phone-sized screens up to large desktop windows.

Explore the land of Avel, gear up, clear the monster lairs, build walls, set traps and seal lairs before the Black
Moon rises. Then defend the castle against the march and defeat the Beast.

## Play

```sh
uv sync
uv run bg serve            # http://127.0.0.1:8000
```

Open the page, create a room, add bots or share the room link with friends, pick the crater difficulty and start.
Everyone plays in the same room from their own browser. If a player disconnects, a bot takes over their hero until
they come back.

Lobby options:

- **Bots**: `knight` is a sensible teammate; `squire` plays randomly.
- **Crater**: easy, moderate or difficult. It decides which monsters come out with the Beast.
- **Hints**: a 💡 button that asks a bot for advice.
- **Turn timer**: when a human runs out of time, a bot finishes their turn.

To play over a LAN: `uv run bg serve --host 0.0.0.0`.

## Rules notes

The game follows the rulebook: 2 actions per turn (4 in solo), the moon track, the Black Moon, the monster march,
walls, traps and seals. The Beast has 14, 14, 17 or 20 toughness for 1, 2, 3 or 4 players, and you win only once every
monster, including the Beast, is defeated.

One simplification: in the real game you pull equipment from the bag by touch, against a time limit. Here every bag
draw is random.

## Development

```sh
uv run pytest                                # engine rules, full bot games, server protocol
uv run ruff check && uv run ruff format
uv run bg avel eval --games 200 --players 2     # bot-only win rate
```

Layout:

- `src/avel/game`: the rules engine. `Game.step(seat, action)`; `legal_actions` is the source of truth.
- `src/avel/bots`: bots.
- `src/avel/web`: FastAPI and WebSocket rooms, plus the client in `static/` (plain ES modules, no build step).
