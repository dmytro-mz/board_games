"""Masked PPO with an opponent pool (heuristics + frozen self-play snapshots).

CleanRL-style single-file trainer: rollouts from a batched env, GAE, clipped
surrogate objective. Periodic full-game tournaments against fixed baselines are
the ground-truth progress signal; everything goes to TensorBoard + metrics.csv.
"""

from __future__ import annotations

import json
import re
import time
from concurrent.futures import ProcessPoolExecutor
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

import numpy as np
import torch
import yaml
from rich.console import Console

from skyjo.agents import make_agent
from skyjo.evaluation.tournament import TournamentResult, run_tournament
from skyjo.game.actions import N_ACTIONS
from skyjo.rl.config import TrainConfig
from skyjo.rl.encoding import ObsEncoder, input_feature_map
from skyjo.rl.logger import MetricsLogger
from skyjo.rl.network import ActorCritic
from skyjo.rl.policy_agent import PolicyAgent
from skyjo.rl.vec_env import make_vec_env

console = Console()


def resolve_device(name: str) -> torch.device:
    if name == "auto":
        return torch.device("mps" if torch.backends.mps.is_available() else "cpu")
    return torch.device(name)


def make_run_dir(cfg: TrainConfig) -> Path:
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    run_dir = Path(cfg.run_root) / f"{stamp}_{cfg.name}"
    (run_dir / "checkpoints").mkdir(parents=True, exist_ok=False)
    return run_dir


_SIZED_LABEL = re.compile(r"_\dp$")


def evaluate_policy(
    policy: PolicyAgent, cfg: TrainConfig, pool: ProcessPoolExecutor | None, seed: int
) -> dict[str, TournamentResult]:
    """Results keyed by `<opponent>` (env.n_players table) or `<opponent>_<n>p`."""
    results = {}
    sizes = cfg.eval.table_sizes or [cfg.env.n_players]
    for spec in cfg.eval.opponents:
        for n in sizes:
            lineup = [policy] + [make_agent(spec) for _ in range(n - 1)]
            label = spec if n == cfg.env.n_players else f"{spec}_{n}p"
            results[label] = run_tournament(
                lineup, cfg.eval.games, cfg.env.rules(n), seed=seed, workers=cfg.eval.workers, executor=pool
            )
    return results


def _eval_scalars(results: dict[str, TournamentResult]) -> dict[str, float]:
    out: dict[str, float] = {}
    vs_fair: dict[str, list[float]] = {}
    for label, res in results.items():
        me, *others = res.summaries
        out[f"eval/{label}/win_rate"] = me.win_rate
        out[f"eval/{label}/game_score"] = me.game_score
        out[f"eval/{label}/round_score"] = me.round_score
        out[f"eval/{label}/opp_round_score"] = sum(o.round_score for o in others) / len(others)
        out[f"eval/{label}/finish_rate"] = me.finish_rate
        out[f"eval/{label}/doubled_rate"] = me.doubled_rate
        spec = _SIZED_LABEL.sub("", label)
        vs_fair.setdefault(spec, []).append(me.win_rate * res.n_players)
    for spec, ratios in vs_fair.items():
        if len(ratios) > 1:
            out[f"eval/{spec}/mean_win_vs_fair"] = sum(ratios) / len(ratios)
    return out


def _transplant_inputs(state: dict[str, torch.Tensor], src_version: int, src_n: int, dst_version: int) -> None:
    """Re-index the first actor/critic layer from a `src_version` layout to `dst_version`."""
    idx = torch.as_tensor(input_feature_map(src_version, src_n, dst_version))
    dst_dim = ObsEncoder(src_n, dst_version).dim
    for key in ("actor.0.weight", "critic.0.weight"):
        w = state[key]
        new = torch.zeros(w.shape[0], dst_dim, dtype=w.dtype)
        new[:, idx] = w
        state[key] = new


@dataclass
class TrainState:
    update: int = 0
    global_step: int = 0
    best_score: float = -float("inf")


def train(cfg: TrainConfig, resume: Path | None = None) -> Path:
    p = cfg.ppo
    torch.manual_seed(cfg.seed)
    np.random.seed(cfg.seed)
    torch.set_num_threads(cfg.torch_threads)
    device = resolve_device(cfg.device)

    run_dir = make_run_dir(cfg)
    (run_dir / "config.yaml").write_text(yaml.safe_dump(cfg.to_dict(), sort_keys=False))
    logger = MetricsLogger(run_dir)
    logger.text("config", f"```yaml\n{yaml.safe_dump(cfg.to_dict(), sort_keys=False)}\n```")

    envs = make_vec_env(cfg.env, p.num_envs, p.num_workers, seed=cfg.seed)
    prior_offset = None
    if p.residual_prior:
        prior_offset = ObsEncoder(cfg.env.n_players, cfg.env.obs_version).prior_offset
        if prior_offset is None:
            raise ValueError(f"ppo.residual_prior needs an obs version with a prior block, got {cfg.env.obs_version}")
    model = ActorCritic(envs.obs_dim, N_ACTIONS, p.hidden, prior_offset=prior_offset, prior_scale=p.prior_scale)
    model = model.to(device)
    if cfg.init_checkpoint is not None:
        init = torch.load(cfg.init_checkpoint, map_location="cpu", weights_only=False)
        src_env = init["config"]["env"]
        weights = init["model"]
        if src_env["obs_version"] != cfg.env.obs_version:
            _transplant_inputs(weights, src_env["obs_version"], src_env["n_players"], cfg.env.obs_version)
        model.load_state_dict(weights)
        console.print(f"[yellow]initialised weights from {cfg.init_checkpoint} (obs v{src_env['obs_version']})")
    optimizer = torch.optim.Adam(model.parameters(), lr=p.learning_rate, eps=1e-5)
    state = TrainState()
    if resume is not None:
        ckpt = torch.load(resume, map_location=device, weights_only=False)
        model.load_state_dict(ckpt["model"])
        optimizer.load_state_dict(ckpt["optimizer"])
        state = TrainState(**ckpt["state"])
        console.print(f"[yellow]resumed from {resume} at update {state.update}")

    eval_pool = ProcessPoolExecutor(max_workers=cfg.eval.workers) if cfg.eval.workers > 1 else None
    num_updates = p.total_timesteps // p.batch_size
    console.print(
        f"[bold]run[/] {run_dir}  device={device}  obs_dim={envs.obs_dim}  batch={p.batch_size}  updates={num_updates}"
    )

    _write_reference(cfg, eval_pool, run_dir)

    def snapshot_policy() -> PolicyAgent:
        policy = PolicyAgent(
            model.actor_layers(),
            cfg.env.n_players,
            greedy=True,
            obs_version=cfg.env.obs_version,
            prior_scale=model.prior_scale(),
        )
        policy.name = "ppo"
        return policy

    def run_eval() -> None:
        t0 = time.time()
        results = evaluate_policy(snapshot_policy(), cfg, eval_pool, seed=10_000)
        scalars = _eval_scalars(results)
        logger.log(state.global_step, scalars)
        key = cfg.eval.best_metric or f"eval/{cfg.eval.best_metric_opponent}/win_rate"
        line = "  ".join(f"{s}: win {r.summaries[0].win_rate:.3f}" for s, r in results.items())
        console.print(f"[cyan]eval @ {state.global_step:,}[/]  {line}  ({time.time() - t0:.1f}s)")
        policy = snapshot_policy()
        policy.save(run_dir / "policy_latest.npz")
        if key in scalars and scalars[key] > state.best_score:
            state.best_score = scalars[key]
            policy.save(run_dir / "policy_best.npz")
            (run_dir / "best.json").write_text(json.dumps({"global_step": state.global_step, **scalars}, indent=2))

    def save_checkpoint() -> None:
        torch.save(
            {
                "model": model.state_dict(),
                "optimizer": optimizer.state_dict(),
                "state": vars(state),
                "config": cfg.to_dict(),
            },
            run_dir / "checkpoints" / "latest.pt",
        )
        snapshot_policy().save(run_dir / "checkpoints" / f"policy_{state.update:05d}.npz")

    t_obs = torch.zeros((p.num_steps, p.num_envs, envs.obs_dim), device=device)
    t_masks = torch.zeros((p.num_steps, p.num_envs, N_ACTIONS), dtype=torch.bool, device=device)
    t_actions = torch.zeros((p.num_steps, p.num_envs), dtype=torch.long, device=device)
    t_logprobs = torch.zeros((p.num_steps, p.num_envs), device=device)
    t_rewards = torch.zeros((p.num_steps, p.num_envs), device=device)
    t_dones = torch.zeros((p.num_steps, p.num_envs), device=device)
    t_values = torch.zeros((p.num_steps, p.num_envs), device=device)

    obs_np, mask_np = envs.reset()
    next_obs = torch.as_tensor(obs_np, device=device)
    next_mask = torch.as_tensor(mask_np, device=device)
    next_done = torch.zeros(p.num_envs, device=device)
    envs.add_snapshot(model.actor_layers(), model.prior_scale())

    if state.update == 0:
        run_eval()

    try:
        start_update = state.update
        t_start = time.time()
        while state.update < num_updates:
            state.update += 1
            frac = 1.0 - (state.update - 1) / num_updates
            lr = p.learning_rate * frac if p.anneal_lr else p.learning_rate
            optimizer.param_groups[0]["lr"] = lr
            ent_coef = (
                p.ent_coef if p.ent_coef_final is None else p.ent_coef_final + (p.ent_coef - p.ent_coef_final) * frac
            )

            # ---------------------------------------------------------- rollout
            episodes: list[dict[str, float]] = []
            t_roll = time.time()
            for step in range(p.num_steps):
                state.global_step += p.num_envs
                t_obs[step], t_masks[step], t_dones[step] = next_obs, next_mask, next_done
                with torch.no_grad():
                    action, logprob, _, value = model.act(next_obs, next_mask)
                t_actions[step], t_logprobs[step], t_values[step] = action, logprob, value
                obs_np, mask_np, reward_np, done_np, eps = envs.step(action.cpu().numpy())
                episodes.extend(eps)
                t_rewards[step] = torch.as_tensor(reward_np, device=device)
                next_obs = torch.as_tensor(obs_np, device=device)
                next_mask = torch.as_tensor(mask_np, device=device)
                next_done = torch.as_tensor(done_np, dtype=torch.float32, device=device)
            rollout_time = time.time() - t_roll

            # ---------------------------------------------------------- GAE
            with torch.no_grad():
                next_value = model.value(next_obs)
                advantages = torch.zeros_like(t_rewards)
                lastgaelam = torch.zeros(p.num_envs, device=device)
                for t in reversed(range(p.num_steps)):
                    if t == p.num_steps - 1:
                        nonterminal, nextvalues = 1.0 - next_done, next_value
                    else:
                        nonterminal, nextvalues = 1.0 - t_dones[t + 1], t_values[t + 1]
                    delta = t_rewards[t] + p.gamma * nextvalues * nonterminal - t_values[t]
                    lastgaelam = delta + p.gamma * p.gae_lambda * nonterminal * lastgaelam
                    advantages[t] = lastgaelam
                returns = advantages + t_values

            # ---------------------------------------------------------- optimise
            b_obs = t_obs.reshape(-1, envs.obs_dim)
            b_masks = t_masks.reshape(-1, N_ACTIONS)
            b_actions = t_actions.reshape(-1)
            b_logprobs = t_logprobs.reshape(-1)
            b_adv = advantages.reshape(-1)
            b_returns = returns.reshape(-1)
            b_values = t_values.reshape(-1)

            t_opt = time.time()
            clipfracs, approx_kl = [], torch.tensor(0.0)
            pg_loss = v_loss = entropy_loss = grad_norm = torch.tensor(0.0)
            for _ in range(p.update_epochs):
                perm = torch.randperm(p.batch_size, device=device)
                for start in range(0, p.batch_size, p.minibatch_size):
                    mb = perm[start : start + p.minibatch_size]
                    _, newlogprob, entropy, newvalue = model.act(b_obs[mb], b_masks[mb], b_actions[mb])
                    logratio = newlogprob - b_logprobs[mb]
                    ratio = logratio.exp()
                    with torch.no_grad():
                        approx_kl = ((ratio - 1) - logratio).mean()
                        clipfracs.append(((ratio - 1.0).abs() > p.clip_coef).float().mean().item())

                    mb_adv = b_adv[mb]
                    mb_adv = (mb_adv - mb_adv.mean()) / (mb_adv.std() + 1e-8)
                    pg_loss = torch.max(
                        -mb_adv * ratio, -mb_adv * torch.clamp(ratio, 1 - p.clip_coef, 1 + p.clip_coef)
                    ).mean()

                    if p.clip_vloss:
                        v_unclipped = (newvalue - b_returns[mb]) ** 2
                        v_clipped = b_values[mb] + torch.clamp(newvalue - b_values[mb], -p.clip_coef, p.clip_coef)
                        v_loss = 0.5 * torch.max(v_unclipped, (v_clipped - b_returns[mb]) ** 2).mean()
                    else:
                        v_loss = 0.5 * ((newvalue - b_returns[mb]) ** 2).mean()

                    entropy_loss = entropy.mean()
                    if state.update <= p.critic_warmup_updates:
                        loss = p.vf_coef * v_loss
                    else:
                        loss = pg_loss - ent_coef * entropy_loss + p.vf_coef * v_loss
                    optimizer.zero_grad()
                    loss.backward()
                    grad_norm = torch.nn.utils.clip_grad_norm_(model.parameters(), p.max_grad_norm)
                    optimizer.step()
                if p.target_kl is not None and approx_kl > p.target_kl:
                    break
            opt_time = time.time() - t_opt

            y_pred, y_true = b_values.cpu().numpy(), b_returns.cpu().numpy()
            var_y = np.var(y_true)
            explained_var = float("nan") if var_y == 0 else 1 - np.var(y_true - y_pred) / var_y
            sps = (state.update - start_update) * p.batch_size / (time.time() - t_start)

            scalars = {
                "charts/learning_rate": lr,
                "charts/ent_coef": ent_coef,
                "charts/sps": sps,
                "charts/rollout_seconds": rollout_time,
                "charts/optimize_seconds": opt_time,
                "losses/policy": pg_loss.item(),
                "losses/value": v_loss.item(),
                "losses/entropy": entropy_loss.item(),
                "losses/approx_kl": approx_kl.item(),
                "losses/clipfrac": float(np.mean(clipfracs)),
                "losses/grad_norm": float(grad_norm),
                "losses/explained_variance": explained_var,
            }
            if model.prior_offset is not None:
                scalars["charts/prior_scale"] = model.prior_scale()
            if episodes:
                for key in sorted({k for e in episodes for k in e}):
                    vals = [e[key] for e in episodes if key in e]
                    scalars[f"rollout/{key}"] = float(np.mean(vals))
                scalars["rollout/episodes"] = float(len(episodes))
            logger.log(state.global_step, scalars)

            if state.update % 5 == 0 or state.update == 1:
                console.print(
                    f"upd {state.update:>5}/{num_updates}  step {state.global_step:>11,}  sps {sps:>7,.0f}  "
                    f"lr {lr:.2e}  ret {scalars.get('rollout/return', float('nan')):+.3f}  "
                    f"score {scalars.get('rollout/score', float('nan')):5.1f}  "
                    f"ent {entropy_loss.item():.3f}  kl {approx_kl.item():.4f}  ev {explained_var:.2f}"
                )

            if state.update % cfg.snapshot_every_updates == 0:
                envs.add_snapshot(model.actor_layers(), model.prior_scale())
            if state.update % cfg.eval.every_updates == 0 or state.update == num_updates:
                run_eval()
            if state.update % cfg.save_every_updates == 0 or state.update == num_updates:
                save_checkpoint()
    except KeyboardInterrupt:
        console.print("[yellow]interrupted - saving checkpoint")
        save_checkpoint()
    finally:
        envs.close()
        if eval_pool is not None:
            eval_pool.shutdown()
        logger.close()
    best_key = cfg.eval.best_metric or f"eval/{cfg.eval.best_metric_opponent}/win_rate"
    console.print(f"[green]done[/] best {best_key} {state.best_score:.3f} -> {run_dir}")
    return run_dir


def _write_reference(cfg: TrainConfig, pool: ProcessPoolExecutor | None, run_dir: Path) -> None:
    """Baseline numbers (EV heuristic vs each eval opponent) for plot reference lines."""
    reference = {}
    n = cfg.env.n_players
    for spec in cfg.eval.opponents:
        lineup = [make_agent("ev")] + [make_agent(spec) for _ in range(n - 1)]
        res = run_tournament(
            lineup, cfg.eval.games, cfg.env.rules(), seed=10_000, workers=cfg.eval.workers, executor=pool
        )
        reference[spec] = {"win_rate": res.summaries[0].win_rate, "round_score": res.summaries[0].round_score}
    (run_dir / "reference.json").write_text(json.dumps({"agent": "ev", "vs": reference}, indent=2))
