"""Masked actor-critic MLP (separate actor / critic towers).

With `prior_offset` set, the actor is residual: logits = MLP(obs) + scale * obs[prior block],
where the prior block holds a heuristic's per-action values (see `encoding.expert_prior`)
and `scale` is learned (in log space). The MLP head starts near zero, so the initial
policy is a softmax over the heuristic's action values.
"""

from __future__ import annotations

import math
from collections.abc import Sequence

import numpy as np
import torch
from torch import nn
from torch.distributions import Categorical

from skyjo.rl.policy_agent import Layers

MASK_VALUE = -1e9


def _mlp(in_dim: int, hidden: Sequence[int], out_dim: int, out_gain: float) -> nn.Sequential:
    layers: list[nn.Module] = []
    dim = in_dim
    for h in hidden:
        lin = nn.Linear(dim, h)
        nn.init.orthogonal_(lin.weight, gain=np.sqrt(2))
        nn.init.zeros_(lin.bias)
        layers += [lin, nn.ReLU()]
        dim = h
    head = nn.Linear(dim, out_dim)
    nn.init.orthogonal_(head.weight, gain=out_gain)
    nn.init.zeros_(head.bias)
    layers.append(head)
    return nn.Sequential(*layers)


class ActorCritic(nn.Module):
    def __init__(
        self,
        obs_dim: int,
        n_actions: int,
        hidden: Sequence[int] = (256, 256),
        prior_offset: int | None = None,
        prior_scale: float = 20.0,
    ) -> None:
        super().__init__()
        self.actor = _mlp(obs_dim, hidden, n_actions, out_gain=0.01)
        self.critic = _mlp(obs_dim, hidden, 1, out_gain=1.0)
        self.n_actions = n_actions
        self.prior_offset = prior_offset
        if prior_offset is not None:
            self.prior_log_scale = nn.Parameter(torch.tensor(math.log(prior_scale)))

    def value(self, obs: torch.Tensor) -> torch.Tensor:
        return self.critic(obs).squeeze(-1)

    def logits(self, obs: torch.Tensor) -> torch.Tensor:
        logits = self.actor(obs)
        if self.prior_offset is not None:
            prior = obs[:, self.prior_offset : self.prior_offset + self.n_actions]
            logits = logits + self.prior_log_scale.exp() * prior
        return logits

    def act(
        self, obs: torch.Tensor, mask: torch.Tensor, action: torch.Tensor | None = None
    ) -> tuple[torch.Tensor, torch.Tensor, torch.Tensor, torch.Tensor]:
        logits = self.logits(obs).masked_fill(~mask, MASK_VALUE)
        dist = Categorical(logits=logits)
        if action is None:
            action = dist.sample()
        return action, dist.log_prob(action), dist.entropy(), self.value(obs)

    def actor_layers(self) -> Layers:
        """Actor weights as numpy (W[in, out], b) pairs for `PolicyAgent`."""
        linears = [m for m in self.actor if isinstance(m, nn.Linear)]
        return [(m.weight.detach().cpu().numpy().T.copy(), m.bias.detach().cpu().numpy().copy()) for m in linears]

    def prior_scale(self) -> float | None:
        """Current multiplier of the prior block (None for a plain MLP actor)."""
        if self.prior_offset is None:
            return None
        return float(self.prior_log_scale.detach().exp().item())
