# Game night

Ten board games in one place, played in the browser with friends and bots. One person runs a small Python server;
everyone else opens one link, votes for a game, and plays.

| Game | Players | Bots | Kind |
| --- | --- | --- | --- |
| Ticket to Ride: Europe | 2–5 | yes | competitive |
| Pandemic | 2–4 | yes | co-op |
| Karak | 1–5 | yes | competitive |
| Codenames | 4+ | no | teams |
| Skyjo | 2–8 | yes | competitive |
| Phase 10 | 2–6 | yes | competitive |
| Lost Cities | 2 | yes | competitive |
| Toy Battle | 2 | yes | competitive |
| Agent Avenue | 2–4 | yes | competitive |
| Sky Team | 2 | no | co-op |

## Quick start

Requires [uv](https://docs.astral.sh/uv/getting-started/installation/) (it installs Python 3.12 and everything else).

```bash
uv run bg serve              # http://localhost:8000, plus a LAN link for people on your Wi-Fi
uv run bg serve --tunnel     # a public link for friends anywhere (needs `brew install cloudflared`)
```

1. **Create a room** and send the link (the 🔗 Invite chip copies it).
2. **Choose a game.** Everyone clicks the game they want to play (click again to take the vote back). The filter
   shows only games that fit your group. The room leader starts either their own pick or the most voted game.
3. **Play.** Each game has its own lobby (seats, bots, settings) and plays exactly as it always did. From a game's
   lobby the leader can ask everyone to go back to the game selection; everyone else has to agree, or the leader
   goes back anyway.

Chronicles of Avel (1–4, co-op, bots) is in the repo but not finished, so rooms don't offer it;
`uv run bg serve --unfinished` adds it to the game selection.

`uv run bg serve --help` lists all options (port, public URL, a few per-game ones). Rooms live in memory and close
a few hours after everyone has left.

## Bots and training

Each game's bot tools are under `bg <game>`, e.g. `uv run bg lostcities eval`, `uv run bg skyjo league`,
`uv run bg karak train`. Training needs the optional torch dependencies: `uv sync --group train`.

## Development

```bash
uv run pytest -n 8                                   # every game's tests + the platform (~10 s)
uv run ruff check --fix src tests scripts && uv run ruff format src tests scripts
uv run python scripts/platform/ui_check.py           # two browsers vote, launch and leave every game
```

How the repo is organised and the rules for working on it: [CLAUDE.md](CLAUDE.md). Each game's original README is
in `docs/<game>/`.
