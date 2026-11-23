# skyjo — engine, baselines and RL for the card game Skyjo

Goal: find a strong (ideally optimal) Skyjo strategy with reinforcement learning,
measured against hand-written strategies.

## Quickstart (macOS / Apple Silicon, uv)

```bash
uv sync                                         # python 3.12 + deps
uv run pytest                                   # engine/agents/rl tests
uv run bg skyjo league -a random,greedy,ev -n 2000 # baseline strategies
uv run bg skyjo train -c configs/skyjo/ppo_baseline.yaml # ~25 min on an M3 Pro
uv run tensorboard --logdir runs                # live curves (http://localhost:6006)
uv run bg skyjo plot runs/<run>                    # static dashboard.png
uv run bg skyjo eval -a "ppo:runs/<run>/policy_best.npz,ev" -n 2000
uv run bg skyjo eval -a "ppo:models/ppo_v4/policy_best.npz,expert" -n 2000  # shipped policy
```

## Play online with friends (web version)

```bash
uv run bg serve                 # http://localhost:8000, LAN link printed on start
uv run bg serve --tunnel        # public https link via cloudflared (brew install cloudflared)
```

Open the page, **Create a table**, and send the invite link (the server prints the LAN address;
with `--tunnel` the link works from anywhere). Friends just open it and pick a name — no
accounts. The host fills empty seats with bots: Rookie (`random`), Casual (`greedy`),
Card Counter (`ev`), Expert (`expert`) and every table-size-agnostic trained policy (obs v4+,
i.e. `ppo_v4` and later) found in `models/*/policy_best.npz` or `runs/*/policy_best.npz`.
The repo ships the trained `ppo_v4` policy in `models/ppo_v4/`, so the "AI ppo_v4" bot works
right after cloning, no training needed. Older policies (ppo_baseline, v2, v3) only play
2-player games and are ignored by the lobby.

What the table offers: 2–8 seats, live card animations, simultaneous opening flips, a game log
with chat and emoji reactions, a scoreboard with the doubling rule shown per round,
optional turn timer (the Expert autopilot moves when it runs out), 💡 hints from the Expert bot,
"let a bot play" for disconnected players, spectators, reconnect-on-refresh, rematch,
house rules (target score, column clear, double penalty), sound and mobile layout.

| option | meaning |
|---|---|
| `--port 8000` / `--host 0.0.0.0` | bind address (`127.0.0.1` hides it from your LAN) |
| `--models DIR` | directories scanned for `<run>/policy_best.npz` (default `models` and `runs`) |
| `--bot SPEC` | extra bot, any agent spec, e.g. `--bot "ev:reveal_bonus=0.5"` or `--bot ppo:path.npz` (v4+ policies only) |
| `--public-url URL` | base URL used in invite links (e.g. your own reverse proxy) |
| `--tunnel` | start a cloudflared quick tunnel and invite through it |

Rooms live in memory: restarting the server ends all tables.
New strategies added to `REGISTRY` show up in the lobby automatically.

## Commands

| command | what it does |
|---|---|
| `skyjo eval -a A,B[,C...] -n N` | N full games of one lineup, seats rotated; win rate / scores with 95% CI; JSON in `results/` |
| `skyjo league -a A,B,C -n N --players 4` | head-to-head win-rate matrix + N-player free-for-all |
| `skyjo train -c cfg.yaml -s key=value` | masked PPO; dotted overrides e.g. `-s ppo.total_timesteps=5e6` |
| `skyjo plot RUN_DIR` | dashboard PNG from `metrics.csv` |
| `skyjo watch -a ev,greedy` | print a game move by move |
| `skyjo bench` | env throughput |
| `skyjo serve [--tunnel]` | multiplayer web game (humans + bots), see above |

Agent specs: `random`, `greedy[:keep_threshold=3]`,
`ev[:reveal_bonus=..,pair_weight=..,finish_bonus=..]`, `expert[:deny=..,pair_horizon=..,pair_cost=..,multi_reveal_bonus=..]`,
`ppo:<path.npz>[,greedy=false]`.
Use `;` between specs when a spec has several params: `-a "ev:reveal_bonus=0.5,pair_weight=1;greedy"`.

## Strategies

- **random** — uniform legal move (lower bound).
- **greedy** — casual human: keep cards ≤3 or that beat your highest visible card, dump the highest card, otherwise flip. No card counting, no endgame awareness.
- **ev** — card counting + one-step expectimax: hidden cards valued at the mean of unseen cards, exact column-completion probabilities, deck draws enumerated over all values, doubling risk estimated before revealing the last card.
- **expert** — strongest rule-based player: `ev` plus discard denial (don't hand the next player useful cards), pair credit from the probability that a matching card still shows up, exact doubling odds from the opponents' score distribution, opening flips in different columns, and a stall breaker. Beats `ev` 72% and PPO v2 64% (see `docs/experiments.md`).
- **ppo** — learned policy (see `docs/rl_research.md`). The strongest, `configs/skyjo/ppo_v3.yaml`, is a
  residual policy on top of `expert`'s action values (obs v3) trained on full games against `expert`:
  beats `expert` 67% and `ev` 85% (~2 h on an M3 Pro). `configs/skyjo/ppo_v4.yaml` warm-starts it on
  the table-size-agnostic obs v4 and fine-tunes on 2–8 seat tables: 69% 1-on-1 vs `expert` and
  1.3–1.6× its fair win share against 2–7 experts. It is the one the web lobby offers.

## Layout

```
src/skyjo/game/        rules engine (pure Python)      docs/rules.md
src/skyjo/agents/      heuristic agents + registry
src/skyjo/evaluation/  parallel tournaments with CIs
src/skyjo/rl/          encoder, env, vec env, opponent pool, PPO, logger
src/skyjo/web/         multiplayer server (FastAPI + WebSocket) and static browser client
configs/skyjo/               training configs                 docs/experiments.md
models/ppo_v4/         shipped trained policy (numpy .npz, no torch needed to play)
.cursor/rules/         guidance for AI coding agents
```

## Training logs

Every run writes `runs/<timestamp>_<name>/` with `config.yaml`, `metrics.csv`,
TensorBoard events (`tb/`), `reference.json` (EV baseline numbers), `policy_best.npz`,
`policy_latest.npz` and `checkpoints/`. Key curves: `charts/learning_rate`,
`losses/*`, `rollout/*`, and `eval/<opponent>/win_rate` (ground truth).
