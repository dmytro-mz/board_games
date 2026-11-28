# Pandemic — online

Play Pandemic, the cooperative board game, with friends in the browser. One person runs a small Python server,
everyone else just opens a link. Travel the world as a team, keep four diseases in check and discover all four
cures before time runs out; bots can fill empty seats.

![A turn in progress: four actions left, outbreaks building up around Manila](docs/screenshot.png)

## Features

- **The classic game**: 48 cities, 7 roles with their special abilities, 5 event cards, Epidemics, chained
  outbreaks, eradication, the 7-card hand limit and all three ways to lose.
- **Lobby settings**: difficulty (4, 5 or 6 Epidemic cards: Introductory, Standard, Heroic), roles dealt at
  random or chosen by each player, and open or closed hands. Closed: only you see your cards, so you have to
  communicate and cooperate more.
- **Your call, not the game's**: the board shows what is on it (cubes, cards, decks, discard piles) but never
  computes risks or odds. Looking at the infection discard and working out what may come next is up to you.
- **Event cards any time**: everyone can play an event on anyone's turn, even in the middle of an epidemic, as
  the rules allow. The Contingency Planner stores events, the Dispatcher moves other pawns, Forecast lets you
  rearrange the top six infection cards.
- **Undo**: take back actions of your own turn as long as they didn't reveal a card.
- **2–4 players**: any mix of humans and bots, with two bot levels. Spectators can watch.
- **Multiplayer in the browser**: invite friends over your Wi-Fi or with a public link. Players can reconnect,
  move their seat to another device, or hand it to the autopilot if they drop out.
- **A map that fits any window**: zoom and pan from the whole world down to a crowded region; Pacific routes
  are drawn at the map edge. The table rearranges itself from a full HD screen down to a phone.
- **Table extras**: chat and emoji reactions, synthesised sounds, animated pawns and outbreaks, a step-by-step
  panel for draws, epidemics and infections, game statistics, keyboard shortcuts.
- **Fair play**: the server holds the game state and checks every move. With closed hands nobody sees another
  player's cards or what they draw (Epidemics are public). The order of the decks stays on the server; only
  Forecast reveals the top of the infection deck.

## Requirements

- [uv](https://docs.astral.sh/uv/getting-started/installation/). It installs Python 3.12 and all
  dependencies for you.
- Optional: [cloudflared](https://developers.cloudflare.com/cloudflare-one/connections/connect-networks/downloads/),
  to invite friends from outside your network (`brew install cloudflared` on macOS).

## Quick start

```bash
uv run bg serve
```

Open <http://localhost:8000>, click **Create a table**, add bots or send the invite link to friends, and click
**Start game**.

| Command | Who can join |
| --- | --- |
| `uv run bg serve` | People on the same Wi-Fi/LAN, through the network link printed at startup |
| `uv run bg serve --tunnel` | Anyone, through a temporary public `trycloudflare.com` link |
| `uv run bg serve --public-url https://…` | Anyone, if you host the server behind your own domain or reverse proxy |

## How to play

The team wins together by discovering all four cures. Everyone loses together after the 8th outbreak, when a
disease runs out of cubes, or when a player has to draw from an empty player deck. On your turn:

1. **Four actions.** Click a city on the map to see how you can get there and what it costs, or use the action
   buttons: drive or ferry along a route, fly with your city cards (direct, charter, shuttle between research
   stations), build a research station, treat disease, share knowledge with a player in the same city, or
   discover a cure with 5 cards of one colour at a research station. **End actions** finishes early.
2. **Draw 2 player cards.** An Epidemic raises the infection rate, puts 3 cubes on the city at the bottom of the
   infection deck, and shuffles the infection discard back on top of the deck. Hand limit: 7 cards.
3. **Infect cities.** Flip as many infection cards as the infection rate; each city gets one cube. A 4th cube
   causes an outbreak: every connected city gets a cube instead, and outbreaks can chain.

Click any player to read their role. The **Help** button in the top bar has the full rules, the map symbols and
the shortcuts.

**Keyboard:** `D` `F` `C` `S` drive, direct flight, charter flight, shuttle flight · `B` `T` `K` `U` build,
treat, share knowledge, discover cure · `Z` undo · `P` end actions (press twice) · `N` draw · `Space` continue ·
`+` `−` `0` zoom · arrow keys jump between cities · `Esc` cancels.

## Bots

| Bot | Strength | Plays like |
| --- | --- | --- |
| Rookie | ★ | treats what's in front of it, sometimes wanders off, forgets its event cards |
| Expert | ★★★ | plans the whole turn, collects cure sets, guards cities about to outbreak and times its events |

Measure how often all-bot teams win, per team size and difficulty (games run in parallel):

```bash
uv run bg pandemic eval -a expert,rookie -n 150
```

Win rate of Expert teams over 150 games each (Rookie teams practically never win):

| Players | Introductory (4) | Standard (5) | Heroic (6) |
| --- | --- | --- | --- |
| 2 | 58% | 29% | 15% |
| 3 | 33% | 24% | 6% |
| 4 | 22% | 12% | 3% |

## Development

```bash
uv sync                                                    # install runtime + dev dependencies
uv run pytest                                              # rules, bots, room protocol, hidden information
uv run ruff check --fix . && uv run ruff format .
```

The browser checks drive Google Chrome through Playwright (default macOS path, set by `CHROME` in
`scripts/pandemic/shot.py`):

```bash
uv run python scripts/pandemic/demo.py --stage epidemic --out shots/game.png  # screenshot a seeded table (home|lobby|play|draw|epidemic|infect|discard|over)
uv run python scripts/pandemic/ui_check.py --role dispatcher --closed       # play whole games through clicks; fails on any JS error or error toast
uv run python scripts/pandemic/sizes.py --stage play                        # one stage at phone → full HD sizes, with a city popover open
uv run python scripts/pandemic/flow_check.py --closed                      # a whole table as three real people: host, phone, spectator
```

`ui_check.py` lets the Expert bot decide the human's moves and then performs them the way a player would: through
the map popover or an action button and a highlighted city, the share and cure dialogs, event cards with their
map modes, the hand-limit dialog, Forecast arranging, Continue after epidemics, plus occasional undo.

`flow_check.py` opens three browsers like three friends would: the host on a laptop types a name and creates
the table, a second player on a touch phone joins by code, a third opens the invite link and watches. It covers
the lobby (chat, rename, settings, roles, bots), chat and shortcuts in game, map pinch/tap/drag/wheel, both
players playing to the end with taps and clicks, reloads mid-game, and play again / back to the lobby.

### Project layout

```
src/pandemic/
  game/      pure rules engine (no I/O): map, cards and roles, actions, the Game state machine
  bots/      Bot interface and the planner bot with its two levels
  web/       room logic, Starlette + WebSocket server, and the vanilla JS client in static/ (no build step)
  runner.py  play a bot-only game
  cli.py     the `pandemic` command (serve, eval)
scripts/     map builder, screenshots and browser checks
tests/       pytest suite
```

Dependencies only point downwards: `game` imports nothing from the project, `bots` imports `game`, and `web`
imports both. Conventions and invariants are in [`.cursor/rules/`](.cursor/rules/).

## License and credits

The code is released under the [MIT License](LICENSE). The world map is built from
[Natural Earth](https://www.naturalearthdata.com/) data (public domain) by `scripts/pandemic/build_map.py`. The cards are
drawn in CSS, and the sound effects are synthesised in the browser.

This is an unofficial fan project for private games with friends. It is not affiliated with or endorsed by
Z-Man Games, the publisher of *Pandemic*, or its designer Matt Leacock. The rules are explained in our own
words. If you enjoy it, please buy the real board game.
