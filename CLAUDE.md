# Board games

One server, one room for a group of friends: board games with bots, played in the browser.

## How it works

Three levels: create or join a room (`/`, one link `/r/CODE` for everyone) → choose a game as a group → the game's
own lobby and table. The platform (`src/boardgames`) hosts the rooms; every game is a self-contained package
(`src/<game>`) with a pure rules engine, bots, a web room and a vanilla-JS client. Each game has its own `CLAUDE.md`
with its invariants; read it before touching that game.

Reference for adding a game, the layout, the plug-in contract and the commands: [docs/platform.md](docs/platform.md).
**Technical rules every game follows** (engine, server, bots, client, assets, verification): [tech_rules.md](tech_rules.md).
The BGG complexity weight on a tile is looked up with the `bgg-weight` skill.

## Product rules (from the owner — keep them true)

1. **Game selection.** Every game is a tile showing its player count and whether bots are available; a player
   filter hides games that don't fit.
2. **Voting.** One vote per player; clicking a game votes for it (moving the vote), clicking it again withdraws it.
   Only online players' votes count.
3. **Launching.** Only the room leader launches: *Play selected* (their own vote) and/or *Play most voted* (strictly
   the most votes; no such game on a tie). If both are the same game there is one button; with no votes, none.
4. **Back to game selection** works only from the game's own lobby. The leader asks, every other online player
   must accept; declines are visible to all and the request stays open; the leader may force or cancel it.
5. **The leader** is whoever created the room; after 20 s offline the role passes to the next online member. The
   game table's host is always the room leader.
6. **Every game follows its original rulebook.** Change a game's rules, look or flow only when asked. A platform
   change must never change how a game plays.
7. **Efficiency, not dogma.** Share what is genuinely shared (server, room base class, JS helpers, CLI). Keep a copy
   when a game intentionally differs or sharing would make the code harder to follow.
8. **When something is unclear, a problem comes up, or a decision isn't covered here: ask the owner** instead of
   guessing.

## Values

- The server is authoritative; clients only send intents and are never trusted. Hidden information never leaves
  the server.
- Engines are pure (no I/O, no asyncio, seeded randomness). Rooms are synchronous; `server.py` only moves JSON.
- Dependencies point one way: `boardgames` never imports a game except through `games.load_games()`; inside a game
  `game/` ← `bots/` ← `web/`.
- Platform UI must not leak styles into games (they run in an iframe).
- Cheap by default: nothing blocks the event loop, an idle client draws no frames, static files are versioned and
  cached for good ([tech_rules.md](tech_rules.md); measurements in [docs/performance.md](docs/performance.md)).
- All art is original; never copy a published game's artwork or rulebook text.
- Always `uv`, never pip. `uv run pytest -n 8` must pass before you say you're done. A platform change also needs
  `scripts/platform/ui_check.py`; a game change needs that game's tests, its `ui_check.py` and a look at a screenshot.
  A change to the platform or a game's client or bots also runs `scripts/platform/perf_check.py` (budgets).
