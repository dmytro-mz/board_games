# Choosing the first RL candidate

## The problem, from an RL point of view

| property | Skyjo | consequence |
|---|---|---|
| information | effectively perfect-information + chance (see `rules.md`) | no CFR-style machinery needed; observation with card counts is Markov → feed-forward MLP |
| players | 2–8, general-sum ranking (zero-sum for 2p relative reward) | needs self-play / opponent pool to avoid overfitting to one heuristic |
| actions | 26 discrete ids, legality depends on phase | invalid-action masking |
| horizon | ~20–40 learner decisions per round, ~4–6 rounds per game | short; terminal reward per round is fine with GAE |
| reward | sparse (end of round), high variance from deck luck | large batches, advantage normalisation, many episodes |
| simulator | pure Python, ~24k learner steps/s/process, ~65k with 8 workers | cheap samples → on-policy model-free is affordable |
| hardware | MacBook Pro M3 Pro, 11 CPU cores, unified memory | CPU-bound env; tiny MLP; MPS not worth it (measured) |

## Candidates considered

1. **Masked PPO + self-play opponent pool** — on-policy actor-critic, robust to
   hyper-parameters, trivial action masking, scales with parallel CPU envs, the standard
   choice for card games and what prior Skyjo projects converged on
   ([skyjoai](https://github.com/faguodev/skyjoai) via RLlib,
   [skynet-skyjo](https://github.com/AZERDSQ131/skynet-skyjo) self-play PPO).
   Weakness: sample-hungry (we have cheap samples) and no explicit lookahead.
2. **DQN / Rainbow** — more sample-efficient but replay buffers go stale under a moving
   self-play opponent distribution; masking in the target max is fiddly; more brittle.
3. **AlphaZero / Stochastic MuZero (MCTS with chance nodes)** — very strong for
   perfect-information stochastic games, and Skyjo qualifies. But needs a fast batched
   simulator + search per move (Python engine would bottleneck), and a lot more code.
   Best as phase 2, bootstrapped from the PPO policy/value networks.
4. **CFR / Deep CFR / ReBeL / NFSP** — built for private information and bluffing,
   which Skyjo barely has; the chance-heavy tree makes them expensive for little gain.
5. **Evolution strategies / CMA-ES over heuristic parameters** — great cheap baseline
   tuner for `ExpectedValueAgent` (5 parameters), not a general policy learner.

## Decision: masked PPO, CleanRL-style, own implementation

Why own implementation instead of sb3-contrib `MaskablePPO`: we need control over
self-play snapshot distribution into worker processes, torch-free opponent inference,
and logging; ~300 lines is cheap. `SkyjoEnv` still implements `action_masks()`, so
`MaskablePPO` can be dropped in for comparison.

Design:
- Episode = one round (default) with reward `(mean opponent score − own score) / 10`;
  `episode: game` + `win_bonus` available to learn end-of-game tactics later.
- Learner sits at a random seat; opponents sampled per episode from
  `{random, greedy, ev, self}` where `self` = one of the last 20 frozen snapshots.
- Separate actor and critic MLPs (2×256, ReLU), orthogonal init, logits masked to −1e9.
- 128 envs × 128 steps = 16k samples/update, 8 minibatches × 4 epochs, linear LR anneal
  2.5e-4 → 0, entropy 0.01 → 0.002.
- Ground-truth metric: greedy-policy win rate in full games (to 100 points) vs each
  baseline, every 20 updates, 400 games, logged as `eval/<opp>/*`.

## Roadmap after the first candidate

1. Tune PPO (network width, `gamma`, reward mode, opponent mix, longer runs).
2. Game-level episodes so the agent learns to manage the doubling risk vs cumulative totals.
3. Inference-time search: 1-ply expectimax over the exact chance distribution using the
   learned value net (cheap, typically a large gain in stochastic card games).
4. Stochastic-MuZero/AlphaZero-with-chance-nodes if (3) shows search pays off; would
   justify porting the engine to numba/Rust for batched simulation.
5. Tune the EV heuristic with CMA-ES as a stronger fixed opponent/benchmark.
