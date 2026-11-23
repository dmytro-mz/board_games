# Experiment log

Hardware: MacBook Pro M3 Pro (11 cores), torch on CPU, 8 env workers.
Win rates are full games to 100 points, 2 players, seats rotated, ±95% CI.
Independent evals use `--seed 123` (training-time evals use seed 10000).

## Heuristic baselines (2000 games per pairing)

| matchup | win rate (first agent) | round score (first vs second) |
|---|---|---|
| greedy vs random | 1.000 | 9.0 vs 82.3 |
| ev vs random | 1.000 | 13.5 vs 67.3 |
| ev vs greedy | 0.876 ± 0.014 | 17.0 vs 26.3 |

4-player `ev,greedy,ev,greedy`: EV seats 0.463 / 0.447, greedy seats 0.051 / 0.040.

## Rule-based strategy search → `expert`

Method: an EV clone with switchable features, each tested head-to-head vs `ev`
(3000–4000 games, seed 123, seats rotated; ±0.016 win rate, ±0.25 round points).
"round adv" = mean (opponent − own) round score. Features were stacked greedily.

| change (on top of the previous kept row) | vs ev win | round adv | kept |
|---|---|---|---|
| none (sanity: clone == ev) | 0.500 | −0.05 | — |
| setup: both opening flips in the **same** column | 0.474 | −0.44 | no |
| setup: opening flips in **different** columns | 0.516 | +0.25 | yes (also +0.37 adv on the final stack) |
| final turn: maximise −E[score] + P(score ≤ finisher)·finisher (doubling bonus) | 0.502 | +0.02 | no |
| reveal_bonus 0 / 0.25 / 1.5 (EV default 0.75) | 0.508 / 0.504 / 0.495 | | no (flat) |
| **discard denial** ×0.5 / ×1.0 / ×1.5 / ×2.0 | 0.569 / 0.603 / 0.634 / 0.631 | +1.24 / +1.93 / +2.32 / +2.38 | ×1.5 |
| + pair_weight 0 / 1.0 / 1.5 / 2.0 / 3.0 (EV 0.5) | 0.570 / 0.678 / 0.669 / 0.622 / 0.251 | | → replaced by ↓ |
| + probabilistic pair credit, horizon 6 / 10 / 15 / 20 / 25 cards | 0.654 / 0.680 / 0.683 / 0.672 / 0.647 | | 15, pair_cost 4 (0.685) |
| + also credit pairs whose third card is visible | 0.673 | +3.10 | no |
| + exact finishing odds (opponent score convolution) | 0.711 | +3.69 | yes |
| + opponent_turn_gain 0 / 2 / 4 (finishing) | 0.700 / 0.711 / 0.722 | +3.51 / +3.69 / +3.83 | 4 |
| + opponent final-turn gain computed from their board + my discard | 0.710 | +3.72 | no |
| + game-aware final turn (maximise P(win game), normal approx for later rounds) | 0.724 | +3.43 | no (neutral) |
| + tempo term: reveal bonus ∝ lead over opponent (0.5 / 1 / 2) | 0.720 / 0.715 / 0.688 | | no |
| + spread setup (final stack) | 0.735 | +4.20 | yes |
| + stall breaker (needed: 14% of self-play rounds hit the 400-turn cap) | 0.723 | +4.00 | yes |

Why it works:
- **Denial** is the big one. EV never asks what its discard does for the next player; charging
  1.5 × (next player's EV gain from taking that card vs drawing blind) makes it bury useful
  cards. Own round score also drops (18.4 → 16.7), not only the opponent's rises.
- **Pair credit** `P(≥1 matching card in the next 15 seen) × (2v + mean − 4)` replaces the flat
  `0.5·v`: EV undervalued pairs and kept crediting pairs whose remaining copies were gone.
- **Finishing**: EV's logistic (temperature 2) is far too sharp — an opponent with 4 hidden
  cards has a score s.d. of ~8. The exact distribution halves own-finish doubling (0.15 → 0.08).
- **Stall breaker**: with one hidden card left, two cautious players swap a 3 for a 4 forever
  (drawing would force keeping a bad card or finishing). Non-finishing moves cost
  0.5 × (round turn − 50); 0 capped rounds in self-play afterwards, no strength change.

Rollout oracle (one-step search: every legal action × 16 determinized rollouts with `expert`
for both seats, CRN, best picked on half the rollouts and scored on the other half):
−0.23 points per decision overall, i.e. switching to rollout-best choices *loses* — no
systematic mistakes detectable at this resolution. The one positive cell (last hidden card,
after taking the discard: +2.4 ± 1.6) came from self-play standoff dynamics; acting on it
(no denial / constant waiting cost in that state) lost head-to-head vs `expert` (0.44–0.50).

Final `expert` (default params), seed 123:

| matchup | games | win rate (expert) | round score (expert vs other) |
|---|---|---|---|
| expert vs ev | 4000 | 0.722 ± 0.014 | 15.0 vs 19.0 |
| expert vs greedy | 2000 | 0.974 ± 0.007 | 11.0 vs 24.5 |
| expert vs random | 500 | 1.000 | 9.9 vs 70.7 |
| expert vs ppo_v2 `policy_latest` | 2000 | 0.643 ± 0.021 | 12.8 vs 15.0 |
| (ev vs ppo_v2 `policy_latest`, same seeds) | 2000 | 0.438 ± 0.022 | 17.3 vs 16.1 |

4-player `expert,ev,expert,ev`: expert seats 0.334 / 0.375, ev seats 0.144 / 0.146.
4-player `expert,ev,ev,ev`: expert 0.343; the ev seated right after it (the one denial targets)
0.142, the other two 0.260 / 0.256 (fair share 0.25).

## Multi-player tables (3–8 seats, for the web game)

Lineup: one candidate + (n − 1) copies of an opponent, seats rotated, full games.
"adv" = mean opponent game total − candidate game total (±95% CI); fair win share = 1/n.

Baseline (old expert, 1 + (n−1) `ev`, 2000 games, seed 123): the edge vanished at big tables.

| n | win | fair | adv | finish % | doubled % |
|---|---|---|---|---|---|
| 2 | 0.727 | 0.500 | +22.5 | 53.6 | 9.6 |
| 4 | 0.343 | 0.250 | +6.3 | 25.4 | 21.7 |
| 6 | 0.200 | 0.167 | +0.3 ± 1.2 | 24.2 | 45.4 |
| 8 | 0.154 | 0.125 | +0.3 ± 1.1 | 25.0 | 53.3 |

Cause: the **stall breaker** counted *table* turns (`stall_after` = 50 round turns ≈ 6 own
turns at 8 seats), so with one card left the expert rushed to finish and was doubled > 50% of
the time. 8 seats, 3000 games vs 7 `ev`: `stall_rate=0` 0.206 (+6.6), `stall_after=200`
0.205 (+6.4) vs default 0.154 (+0.3). Fix: count turns per player, normalised to 2 seats
(`2 · turn / n_players`) — identical at 2 seats, no capped rounds in 4/8-seat self-play.

One-factor sweep on top of the fix (vs `ev`, 3000–4000 games, seeds 123/456/789):
- `deny` 0.75 / 2.5: flat / worse (4 seats: adv +7.9 / +3.9 vs +6.9). Kept 1.5.
- `pair_horizon` 25 looked +0.025 at 8 seats (seed 123) but did not replicate (seed 456:
  15 / 20 / 25 / 35 → adv +7.0 / +6.8 / +6.2 / +5.6; vs 7 experts +0.2 / — / −0.7 / −1.3). Kept 15.
- `opponent_turn_gain` 2 / 6, `finish_bonus` 0 / 4: flat.
- **`reveal_bonus` 1.5** (2-seat default 0.75, where 1.5 was flat/slightly worse): better at
  every multi-seat size — adv +1.0 (3), +1.1 / +1.4 (4), +1.6 (6), +0.6 (8), +0.7 vs 7 experts.
  2.5 was mixed (vs 7 experts 0.115, below fair). Adopted as `multi_reveal_bonus` (3+ seats).

Final, seed 2024 (2 seats: decisions bit-identical, 0 / 24.7k action values differ, so
ppo_v3's obs-v3 prior is unchanged):

| lineup | games | old expert win / adv | new expert win / adv |
|---|---|---|---|
| 1 + 2 ev | 3000 | 0.459 / +10.0 | 0.474 / +11.7 |
| 1 + 3 ev | 3000 | 0.349 / +7.3 | 0.364 / +8.7 |
| 1 + 5 ev | 3000 | 0.209 / +1.6 | 0.239 / +5.4 |
| 1 + 7 ev | 3000 | 0.157 / −0.5 | 0.224 / +7.4 |

Head to head (new vs old): 1 new + 3 old 0.272 ± 0.014 (fair 0.25, adv +2.4); 1 new + 7 old
0.157 ± 0.011 (fair 0.125, adv +4.2); 4 new + 4 old: new seats 0.151, old 0.099 (adv +6.7 ± 0.5).

## RL runs

| run | config | steps | wall | vs greedy | vs ev | notes |
|---|---|---|---|---|---|---|
| 20261104-212642_ppo_baseline | `configs/skyjo/ppo_baseline.yaml` (obs v1, 2×256) | 30M | 28 min | 0.855 ± 0.015 | 0.368 ± 0.021 | still improving at the end; finishes only 27% of rounds vs EV |
| 20261104-215518_ppo_v2 (`policy_latest`) | `configs/skyjo/ppo_v2.yaml` (obs v2, 512+256, ev-heavy pool) | 60M | 77 min | 0.971 ± 0.007 | 0.560 ± 0.022 | first policy to beat EV; ~parity with EV by 9M steps; `policy_best` (picked on noisy 400-game eval) is 0.536 vs ev |
| 20261105-171256_ppo_v3 (`policy_latest`) | `configs/skyjo/ppo_v3.yaml` (obs v3, residual on `expert`, game episodes) | 30M | 110 min | 0.993 ± 0.005 | 0.848 ± 0.016 | **0.674 ± 0.014 vs expert** (4000 games); ≥0.60 vs expert already at ~9M steps |
| 20261106-090843_ppo_v4 (`policy_latest`) | `configs/skyjo/ppo_v4.yaml` (obs v4, any table size, warm start from v3) | +20M | 150 min | | | **0.689 ± 0.014 vs expert** 1v1; 1.30–1.64× fair share vs 2–7 experts (see below) |

### ppo_v3: residual policy on top of `expert`

Feature engineering (obs v3 = v2 + 31 features):
- **Expert prior block**: `ExpertAgent.action_values` for all 26 actions, as
  `(value − best legal value) / 10`, clipped at −3 (illegal actions = −3), plus the best value.
- Game context: total-score gaps to each opponent, distance of the leader to 100 (and a
  "≤ 25 left" flag), round turn.

Model: `logits = MLP(obs) + s · prior`, `s` learned in log space (init 20, i.e. a softmax
at 0.5 points temperature), MLP head initialised near zero. The untrained policy already
plays like `expert` (greedy: 0.522 ± 0.031 vs expert, 1000 games), so PPO only has to
learn deviations. First 20 updates train the critic only.

Training: full-game episodes, reward = relative round score / 10 per round plus ±1 for
winning the game, `gamma` 0.997, opponents 80% `expert` / 20% self-play snapshots,
batch 160 × 128, lr 2e-4 → 0, entropy 0.002 → 0.0005. ~4.6k steps/s (expert is evaluated
for both the learner's features and the opponent). `ExpertAgent` column costs are now
memoised per decision (2.1× faster, decisions verified identical on a 21k-move trace).

Final eval (seed 123):

| matchup | games | win rate (ppo_v3) | round score (ppo_v3 vs other) | finish % | doubled % |
|---|---|---|---|---|---|
| ppo_v3 `policy_latest` vs expert | 4000 | 0.674 ± 0.014 | 13.5 vs 16.5 | 54.9 vs 45.1 | 9.9 vs 18.7 |
| ppo_v3 `policy_best` (22.5M) vs expert | 4000 | 0.667 ± 0.015 | 13.8 vs 16.6 | | |
| ppo_v3 `policy_latest` vs ev | 2000 | 0.848 ± 0.016 | 12.9 vs 19.8 | | |
| ppo_v3 `policy_latest` vs greedy | 1000 | 0.993 ± 0.005 | 9.0 vs 25.3 | | |
| ppo_v3 at 9M steps vs expert | 2000 | 0.632 ± 0.021 | 14.4 vs 16.7 | | |

It is not only exploiting `expert`: vs `ev` it does better than `expert` itself (0.848 vs 0.722).
Where it overrules the prior (9M-step policy, 60 games vs expert, 29% of decisions differ,
many of them just a different choice among equivalent flips): it discards a drawn card and
flips instead of swapping much more often (more tempo), and with one hidden card left it
draws instead of taking the discard (23% of those decisions). It ends more rounds and is
doubled about half as often.

### ppo_v4: ppo_v3 for any table size

Obs v4 = v3 with every per-seat block padded to 8 seats (absent seats all zero), plus a
table-size one-hot and opponent summaries (best / mean estimated score and total gap, fewest
hidden cards, previous player's board, own turn count). At 2 seats every v3 feature sits at a
fixed v4 position (`encoding.input_feature_map`), so `init_checkpoint` from ppo_v3 copies the
first-layer rows over and zeroes the new ones: the transplanted policy is **identical to v3**
at 2 seats (0 logit difference over 2.3k decisions).

Training: 20M steps from the v3 weights, table sizes 2 (30%), 3/4 (15% each), 5–8 (10% each),
opponents 80% `expert` / 20% self-play, full games, lr 1e-4 → 0, entropy 0.001 → 0.0005,
10 critic-only updates. Win bonus is now +b on a win and −b/(n−1) otherwise (zero mean at a
fair win share; same as before at 2 seats). ~2.3k steps/s (8-seat games run 7 experts per
learner move). In-training evals (400 games at 2/4/6/8 seats) were flat within noise.

Final eval, seed 123, 1 candidate + (n − 1) `expert`, seats rotated (4000 games at 2 seats,
2000 otherwise). "×fair" = win rate × n; "adv" = mean opponent game total − candidate total.

| seats | v4 `policy_latest` win (×fair) / adv | v4 `policy_best` (9.2M) | untrained transplant |
|---|---|---|---|
| 2 | **0.689 ± 0.014** (1.38) / +19.5 | 0.678 (1.36) / +18.8 | = ppo_v3: 0.674 ± 0.014 |
| 3 | 0.493 ± 0.022 (1.48) / +13.4 | 0.476 (1.43) / +12.3 | 0.464 (1.39) / +11.2 |
| 4 | 0.389 ± 0.021 (1.55) / +10.8 | 0.390 (1.56) / +10.3 | 0.349 (1.40) / +8.8 |
| 5 | 0.303 ± 0.020 (1.52) / +9.4 | 0.321 (1.61) / +9.2 | 0.284 (1.42) / +7.3 |
| 6 | 0.273 ± 0.019 (1.64) / +7.9 | 0.242 (1.45) / +6.4 | 0.248 (1.49) / +5.7 |
| 7 | 0.217 ± 0.018 (1.52) / +5.4 | 0.208 (1.46) / +4.3 | 0.203 (1.42) / +3.6 |
| 8 | 0.163 ± 0.016 (1.30) / +4.3 | 0.179 (1.43) / +4.3 | 0.178 (1.43) / +3.1 |

- 1v1 strength is kept (0.689 vs v3's 0.674, same seeds, within CI).
- The transplant alone already beats tables of experts (the prior block is the expert's
  multi-seat action values); fine-tuning adds +1 to +2 points of game advantage at every size,
  win rate clearly up at 3–6 seats, flat at 8.
- `policy_best` and `policy_latest` are within noise of each other (mean ×fair 1.47 vs 1.48);
  latest has the higher point advantage at 6 of 7 sizes.
