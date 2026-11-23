<!-- Built from docs/skyjo/rules/*.mdc (the original repo's rules), adapted to this repo. The root CLAUDE.md rules apply too. -->

# Skyjo RL — project map

Goal: a correct Skyjo engine, strong heuristic baselines, and RL agents that beat them.

## Layout and dependency direction (never import "upwards")

```
skyjo/game/        rules engine, pure Python, no numpy/torch      (lowest layer)
skyjo/agents/      Agent ABC + heuristics (random, greedy, ev) + registry
skyjo/runner.py    play_game(agents, rules, seed)
skyjo/evaluation/  tournaments: seat rotation, seeds, CIs, multiprocessing
skyjo/rl/          encoding/env/vec_env/opponents/policy_agent = numpy only
                   network/ppo/logger = the ONLY torch importers
skyjo/web/         multiplayer: bots.py (lobby catalog) · room.py (sync table logic, no I/O)
                   spec.py (its tile and backend on the platform; server: boardgames) · static/ (vanilla JS client, no build step)
skyjo/cli.py       typer CLI, mounted as `bg skyjo …`
configs/skyjo/*.yaml     training configs  ·  docs/  rules + research + experiments
```

## Commands (always via uv)

- Tests: `uv run pytest` (must pass before you say you're done)
- Lint/format: `uv run ruff check --fix src tests && uv run ruff format src tests`
- Evaluate: `uv run bg skyjo eval -a ev,greedy -n 2000` · `uv run bg skyjo league -a random,greedy,ev`
- Debug a game: `uv run bg skyjo watch -a ev,greedy`
- Web game: `uv run bg serve` (LAN) · `uv run bg serve --tunnel` (public link, needs cloudflared)
- Train: `uv run bg skyjo train -c configs/skyjo/ppo_baseline.yaml -s ppo.total_timesteps=1e6`
- Smoke train (~1 min): `uv run bg skyjo train -c configs/skyjo/smoke.yaml -s run_root=runs_smoke`
- Curves: `uv run tensorboard --logdir runs` or `uv run bg skyjo plot runs/<run>`

## Working agreements

- New strategy = new `Agent` subclass + `REGISTRY` entry + a test in `tests/skyjo/test_agents.py`.
- Claims about strength need a tournament with CIs (≥1000 games), never single games.
- Don't commit `runs/`, `runs_smoke/`, `results/`, `logs/` (gitignored).
- Record experiment outcomes in `docs/experiments.md` (config, steps, eval vs ev).
- Web lobby offers only obs v4+ policies (any table size, `bots.MIN_WEB_OBS_VERSION`).
- Web: the server is authoritative; clients only get `Room.state_for` snapshots, which must never
  contain face-down values (`tests/skyjo/test_web.py` checks this). Game rules stay in `skyjo/game/`.

# Game engine invariants (see docs/rules.md for the full rules)

- Deck: 150 cards (-2×5, -1×10, 0×15, 1..12×10). Card conservation:
  `non-removed board cards + deck + discard + hand == 150` (removed columns go to discard).
- Grid positions are column-major: column c = slots `3c, 3c+1, 3c+2`.
- Board views use sentinels `HIDDEN = 13`, `REMOVED = 14`; `value - MIN_VALUE` is a dense
  code 0..16. Use `is_visible()`, never compare against literals.
- Action ids (26): `0..11` replace slot, `12..23` flip slot, `24` draw deck, `25` take discard.
  Changing this breaks every trained policy (their output layer is indexed by action id).
- Phases: SETUP → CHOOSE_SOURCE → (PLACE_DRAWN | PLACE_DISCARD) → next player.
  Taking the discard forces a replace; a drawn card may be discarded + one flip.
- Column clear happens after every placement/flip AND at the final reveal; the swapped
  card is discarded before the triplet.
- Finisher's positive score doubles unless strictly lowest (ties double, `double_on_tie`).
- `Observation` is the only thing agents see — never leak hidden values into it.
- Every rules change needs a deterministic test (rig `Board`s, call `Round._finish()`)
  plus the random-game fuzz test must still pass.

# RL conventions

- Algorithm: masked PPO (`rl/ppo.py`, CleanRL style). Illegal actions are masked with
  logits = -1e9; never let the env silently "fix" an illegal action.
- torch only in `network.py`, `ppo.py`, `logger.py`. Workers use `PolicyAgent`
  (numpy forward) — keep `network.ActorCritic.actor_layers()` and `mlp_forward` in sync
  (`tests/skyjo/test_rl.py::test_policy_agent_matches_torch_actor`). Residual actors
  (`ppo.residual_prior`, obs v3+) add `prior_scale * obs[prior block]` to the logits in both;
  the scale travels with snapshots (`add_snapshot(layers, prior_scale)`) and the `.npz` meta.
- Obs v3+ calls `ExpertAgent.action_values` on every encode, so expert speed is training speed.
- Observation layouts are versioned (`rl/encoding.py`). Never edit an existing version:
  add version N+1 behind `if self.version >= N+1`, add it to `SUPPORTED_VERSIONS`, bump
  `OBS_VERSION`. Policies store their version in the `.npz`, so old runs stay loadable.
  Configs pin `env.obs_version` for reproducibility. Layouts are declared once in
  `encoding.layout()` (dims, prior offset, `input_feature_map` all derive from it).
- Obs v4 is table-size agnostic (per-seat blocks padded to 8, `ObsEncoder.n_players` is None).
  Train it on mixed tables with `env.table_sizes` and evaluate with `eval.table_sizes`
  (`eval/<opp>_<n>p/*`, plus `eval/<opp>/mean_win_vs_fair`). `init_checkpoint` from an older
  layout transplants the first-layer weights via `input_feature_map` (exact at the old size).
- Device: default `cpu`. On the M3 the MLP is tiny; MPS is ~6× slower for per-step
  inference (batch 128) and only wins on the optimiser step. Re-measure before switching.
- Hardware budget (M3 Pro, 11 cores): eval is synchronous (training pauses), so
  `ppo.num_workers` and `eval.workers` can each be ~10; `torch_threads` 4.

## Logging contract (TensorBoard + `runs/<run>/metrics.csv`)

- `charts/*` lr, ent_coef, sps · `losses/*` policy, value, entropy, approx_kl, clipfrac,
  explained_variance · `rollout/*` episode stats vs the training pool ·
  `eval/<opponent>/*` win_rate, round_score, game_score from full-game tournaments.
- `eval/*` is the ground truth; `rollout/*` mixes opponents and is noisy.
- New metrics: add to the right namespace and, if important, a panel in `plotting.py`.

## Experiment workflow

1. Smoke run first: `uv run bg skyjo train -c configs/skyjo/smoke.yaml -s run_root=runs_smoke`.
2. New idea = new YAML in `configs/skyjo/` (don't mutate a config referenced in experiments.md).
3. Evaluate the best policy: `uv run bg skyjo eval -a "ppo:runs/<run>/policy_best.npz,ev" -n 2000`.
4. Append the result row to `docs/experiments.md`.
