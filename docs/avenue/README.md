# Agent Avenue — online

Play Agent Avenue, the two-spy bluffing game, with friends in the browser or against a strong bot. One person
runs a small Python server, everyone else just opens a link.

![A game in progress](docs/screenshot.png)

## Features

- **The official rules**: simple mode, advanced mode with all 15 black market cards, and the team variant for
  3–4 players (2 vs 2 or 2 vs 1). Every rule and clarification of the rulebook is implemented and tested.
- **A strong bot, Mastermind**: it only sees what a human player would see (your hand, the deck and your face-down
  cards stay hidden from it), counts cards, reads bluffs and bluffs back. It plays out hundreds of sampled games
  per decision, and wins about 95–97% of games against a solid rule-of-thumb player.
- **Hand-drawn animal agents**: the fox Double Agent, squirrel Enforcer, owl Codebreaker, raccoon Saboteur, wolf
  Daredevil, pigeon Sentinel, otter Sidekick and the Mole, all drawn in SVG, on a neighbourhood board with
  hopping spy meeples.
- **Animations and sound**: cards fly, face-down cards flip, meeples hop space by space, black market cards
  pop up, and every sound is synthesised in the browser.
- **Multiplayer in the browser**: share the invite link, pick or shuffle teams in the lobby, reconnect any time,
  continue on another device, or hand an absent player's seat to the autopilot. An optional turn timer lets the
  autopilot move for players who take too long. Chat and emoji reactions included.
- **Rule book** in the lobby and during the game, with a reference of every card.
- **Fair play**: the server holds the game state and checks every move. Clients only send what a player wants to
  do and never receive other players' hidden cards.
- Works on phones, tablets and desktops.

## Requirements

- [uv](https://docs.astral.sh/uv/getting-started/installation/). It installs Python 3.12 and all dependencies
  for you.
- Optional: [cloudflared](https://developers.cloudflare.com/cloudflare-one/connections/connect-networks/downloads/)
  to invite friends from outside your network (`brew install cloudflared` on macOS).

## Quick start

```bash
uv run bg serve
```

Open <http://localhost:8000>, click **Create a table**, choose **Simple** or **Advanced** at the top of the
lobby, add the bot or send the invite link to a friend, and click **Start**.

| Command | Who can join |
| --- | --- |
| `uv run bg serve` | People on the same Wi-Fi/LAN, through the network link printed at startup |
| `uv run bg serve --tunnel` | Anyone, through a temporary public `trycloudflare.com` link |
| `uv run bg serve --public-url https://…` | Anyone, if you host the server behind your own domain |

`--think` caps how long the bot may think per decision (default 1 second; on a normal laptop it needs only a
fraction of that). Run `uv run bg serve --help` for all options.

## How to play

On your turn, click a card in your hand to play it **face up**, then a second card with a different name to play
it **face down**, and press **Play cards**. **Discard & draw** swaps a card (4 times per game). When the other
team has played, click the face-up or the face-down card in the middle of the board to recruit it. In advanced
mode, click a black market card when your spy lands on a corner space.

The full rules are in the **Rule book** (top right).

## The bot

Mastermind is a determinised Monte Carlo search (`src/avenue/bots/search.py`). For every decision it samples
complete games that are consistent with what it has seen (it receives `Game.redacted(player)`, where every
hidden card is replaced by `-1`), tries each legal move in the same samples, plays three turns on with a fast
rule-of-thumb policy that never peeks either, and scores the result. When it plays its two cards it simulates
both of the opponent's answers and blends a model of the opponent's choice with the worst case, so it doesn't
count on a careless opponent.

```bash
uv run bg avenue eval -a mastermind -b heuristic -n 200            # simple mode
uv run bg avenue eval -a mastermind -b heuristic -n 200 --advanced
```

## Development

```bash
uv sync                                                    # install runtime + dev dependencies
uv run pytest                                              # rules, bots, room protocol, hidden information
uv run ruff check --fix src tests scripts && uv run ruff format src tests scripts
```

Browser checks drive Google Chrome through Playwright (Chrome at the default macOS path):

```bash
uv run python scripts/avenue/demo.py --stage play --mode advanced --out shots/game.png  # screenshot a seeded table
uv run python scripts/avenue/ui_check.py --mode advanced --players 4                    # click through a whole game
uv run python scripts/avenue/frames.py --stage recruit                                   # contact sheet of an animation
uv run python scripts/avenue/duel.py mastermind heuristic 200 advanced a.budget=0.3      # bot vs bot
```

### Project layout

```
src/avenue/
  game/      rules engine (no I/O): cards and board data, the Game state machine, JSON actions
  bots/      heuristic policy and evaluation, the Mastermind search bot
  web/       room logic, Starlette + WebSocket server, and the vanilla JS client in static/ (no build step)
  runner.py  bot-only games
  cli.py     the `avenue` command (serve, eval)
scripts/     screenshots, browser click-through, animation frames, bot duels
tests/       pytest suite
```

Dependencies only point downwards: `game` imports nothing from the project, `bots` imports `game`, and `web`
imports both.

## Rules notes

The rules follow the official English rulebook. Two details:

- The printed component list shows **Outpost** with the ∞ (ongoing) symbol, but its text, "Recruit a Sentinel
  from your hand", can only be carried out once. It is resolved as an instant ability and then discarded. The
  rulebook's clarification ("If your hand size is decreased by an ability such as Outpost, draw back up to 4")
  also treats it that way.
- The rulebook's clarifications call **Brainwashing Device** "Mind Control" in places. It is the same card.

In the team variant, "agree with your teammate" decisions (who plays face up, which card to recruit, who takes a
black market card) are made by whichever teammate acts first. A bot teammate always lets a human decide; press
**Let teammate lead** to have the bot play the face-up card.

## License and credits

The code is released under the [MIT License](LICENSE). All artwork is original SVG drawn for this project.

This is an unofficial fan project for private games with friends. It is not affiliated with or endorsed by
Nerdlab Games. *Agent Avenue* is designed by Christian and Laura Kudahl and published by Nerdlab Games. If you
enjoy the game, please buy the real one.
