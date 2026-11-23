# Phase 10 — online

Play Phase 10, the rummy-style card game, with friends in the browser. One person runs a small Python server,
everyone else just opens a link. Collect sets, runs and colors, lay down all ten phases in order, and get rid of
your cards before anyone else; bots can fill empty seats.

![Building phase 2: a set of 12s is staged, the run of 4 is still empty](docs/screenshot.png)

## Features

- **The full game**: 108 cards (1–12 in four colors, 8 Wilds, 4 Skips), all ten phases, hitting on any group
  once your own phase is down, aimed Skips, penalty points and the "fewest points wins a tie" ending.
- **Your hand is yours to arrange**: cards arrive in the order you draw them. Drag them into any order, or sort
  by number or by color with one click. The order is kept on the server, so a reload doesn't scramble it.
- **No help from the game**: nothing is grouped or suggested. You select cards and build each group yourself
  ("＋ Set of 3", "＋ Run of 4", "＋ 7 of one color"), then lay the whole phase down. Wrong groups are
  explained ("A run can't have the same number twice (5)"), never fixed for you.
- **2–6 players**: any mix of humans and bots, with three bot levels. Shorter games (phases 1–5 or 1–3) for a
  quick round.
- **Multiplayer in the browser**: invite friends over your Wi-Fi or with a public link. Players can reconnect,
  move their seat to another device, or hand it to the autopilot if they drop out.
- **Fits any window**: the table rearranges itself from a full HD screen down to a half-width browser window or
  a phone.
- **Table extras**: chat and emoji reactions, synthesised sounds, card animations, a scoreboard with every hand,
  an optional turn timer, keyboard shortcuts.
- **Fair play**: the server holds the game state and checks every move. Nobody sees another player's hand or
  the cards they draw from the deck.

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
**Deal**.

| Command | Who can join |
| --- | --- |
| `uv run bg serve` | People on the same Wi-Fi/LAN, through the network link printed at startup |
| `uv run bg serve --tunnel` | Anyone, through a temporary public `trycloudflare.com` link |
| `uv run bg serve --public-url https://…` | Anyone, if you host the server behind your own domain or reverse proxy |

## How to play

Everyone gets 10 cards. On your turn:

1. **Draw** a card: click the deck, or the discard pile to take its top card (a Skip can't be taken).
2. **Lay down your phase** if you can. Select the cards of one group in your hand and press its button, for
   example **＋ Set of 3**. Do the same for the other group, then press **✓ Lay down**. A slot's **✕** gives
   the cards back. You can also drag cards straight onto a slot.
3. **Hit**: once your phase is down (even in the same turn), add cards to any group on the table, yours or
   anyone's. Select cards and click the group, or drag a card onto it.
4. **Discard** one card to end your turn: select it and press **Discard**, click the discard pile, or drag the
   card onto it. A Skip goes in front of the player of your choice: they lose their next turn, and the Skip
   then moves to the discard pile. A player with a Skip in front of them can't be skipped again. The lobby
   has an optional house rule (off by default): a skipped player must play a turn before the next Skip.

The hand ends when someone has no cards left. Everyone who laid down moves to the next phase, and the others
try the same phase again. Cards left in hand cost points: 1–9 are 5, 10–12 are 10, a Skip is 15, a Wild 25.
The first player to finish phase 10 ends the game. If several do it in the same hand, the one with the fewest
points wins; if they are tied, only they replay phase 10 and the first to go out wins. The **?** button in the top bar has the full rules.

| Phase | | Phase | |
| --- | --- | --- | --- |
| 1 | 2 sets of 3 | 6 | 1 run of 9 |
| 2 | 1 set of 3 + 1 run of 4 | 7 | 2 sets of 4 |
| 3 | 1 set of 4 + 1 run of 4 | 8 | 7 cards of one color |
| 4 | 1 run of 7 | 9 | 1 set of 5 + 1 set of 2 |
| 5 | 1 run of 8 | 10 | 1 set of 5 + 1 set of 3 |

**Keyboard:** `D` draws from the deck, `T` takes the discard, `S` / `C` sort by number / color, `Esc` clears
the selection.

## Bots

| Bot | Strength | Plays like |
| --- | --- | --- |
| Rookie | ★ | keeps pairs, often throws away the wrong card, skips someone at random |
| Regular | ★★★ | counts what its phase still needs and takes useful discards |
| Pro | ★★★★★ | also never feeds the next player a card they can use, and skips whoever is about to go out |

Compare bots head to head (seats rotate, games run in parallel):

```bash
uv run bg phase10 eval -a pro,regular,rookie -n 300
```

In three-player games Pro wins about 58% of the time, Regular 40% and Rookie 1%.

## Development

```bash
uv sync                                                    # install runtime + dev dependencies
uv run pytest                                              # rules, bots, room protocol, hidden information
uv run ruff check --fix src tests scripts && uv run ruff format src tests scripts
```

The browser checks drive Google Chrome through Playwright (default macOS path, set by `CHROME` in
`scripts/phase10/shot.py`):

```bash
uv run python scripts/phase10/demo.py --stage drawn --out shots/game.png   # screenshot a seeded table (home|lobby|play|drawn|laid|handover|over)
uv run python scripts/phase10/ui_check.py                                  # play a whole game through clicks and drags; fails on any glitch
uv run python scripts/phase10/sizes.py                                     # every screen at 13 window sizes; fails on any overflow
```

`ui_check.py` lets the Pro bot decide the human's moves and then performs them the way a player would:
selecting cards, staging groups with the buttons and the slots, picking a run or a Skip target in the
popovers, hitting, dragging cards to reorder the hand, sorting and pressing Ready between hands.

### Project layout

```
src/phase10/
  game/      pure rules engine (no I/O): cards and phases, group validation, actions, the Game state machine
  bots/      Bot interface, the phase solver, the planner bot and its three levels
  web/       room logic, FastAPI + WebSocket server, and the vanilla JS client in static/ (no build step)
  runner.py  play a bot-only game
  cli.py     the `phase10` command (serve, eval)
scripts/     screenshots and browser checks
tests/       pytest suite
```

Dependencies only point downwards: `game` imports nothing from the project, `bots` imports `game`, and `web`
imports both. Conventions and invariants are in [`.cursor/rules/`](.cursor/rules/).

## License and credits

The code is released under the [MIT License](LICENSE). The cards are drawn in CSS, and the sound effects are
synthesised in the browser.

This is an unofficial fan project for private games with friends. It is not affiliated with or endorsed by
Mattel, the publisher of *Phase 10*. The rules are explained in our own words. If you enjoy it, please buy the
real card game.
