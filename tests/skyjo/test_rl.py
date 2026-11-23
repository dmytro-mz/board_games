from __future__ import annotations

import numpy as np
import pytest

torch = pytest.importorskip("torch")

from skyjo.agents import make_agent
from skyjo.game import N_ACTIONS, Game, RulesConfig
from skyjo.rl.config import load_config
from skyjo.rl.encoding import ObsEncoder
from skyjo.rl.env import EnvConfig, SkyjoEnv
from skyjo.rl.network import ActorCritic
from skyjo.rl.policy_agent import PolicyAgent
from skyjo.rl.vec_env import SubprocVecEnv, SyncVecEnv
from skyjo.runner import play_game


@pytest.mark.parametrize("n_players", [2, 4])
def test_encoder_dim_matches_output(n_players: int) -> None:
    enc = ObsEncoder(n_players)
    game = Game(RulesConfig(n_players=n_players), seed=0)
    vec = enc.encode(game.observe(0))
    assert vec.shape == (enc.dim,) and vec.dtype == np.float32
    assert np.isfinite(vec).all()


def test_v2_relational_features() -> None:
    from skyjo.game.cards import HIDDEN, REMOVED
    from skyjo.rl.encoding import _relational

    own = np.array([5, 5, HIDDEN, 3, 7, 3, REMOVED, REMOVED, REMOVED, HIDDEN, HIDDEN, HIDDEN])
    feats = _relational(own, 5, mean_unknown=5.0)
    matches, delta = feats[:12], feats[12:]
    assert matches[:3].tolist() == [0.5, 0.5, 1.0]  # slot 2 would complete the 5-5 column
    assert matches[3:].sum() == 0
    assert delta[4] == pytest.approx(2 / 12) and delta[6] == 0.0
    assert ObsEncoder(2, version=1).dim + 48 == ObsEncoder(2, version=2).dim


def test_encoder_is_seat_relative() -> None:
    enc = ObsEncoder(2)
    game = Game(RulesConfig(n_players=2), seed=0)
    while game.phase.name == "SETUP":
        game.step(game.legal_actions()[0])
    a, b = enc.encode(game.observe(0)), enc.encode(game.observe(1))
    block = 12 * 17
    assert np.array_equal(a[:block], b[block : 2 * block])


@pytest.mark.parametrize("episode", ["round", "game"])
def test_env_episode_with_random_masked_actions(episode: str) -> None:
    env = SkyjoEnv(EnvConfig(episode=episode, opponents={"greedy": 1.0}), seed=1)  # type: ignore[arg-type]
    rng = np.random.default_rng(0)
    for _ in range(3):
        env.reset()
        done, total = False, 0.0
        while not done:
            mask = env.action_masks()
            assert mask.shape == (N_ACTIONS,) and mask.any()
            _obs, r, done, _, info = env.step(int(rng.choice(np.flatnonzero(mask))))
            total += r
        assert info["episode"]["return"] == pytest.approx(total, abs=1e-5)


@pytest.mark.parametrize(("version", "residual"), [(1, False), (2, False), (3, False), (3, True)])
def test_policy_agent_matches_torch_actor(tmp_path, version: int, residual: bool) -> None:  # type: ignore[no-untyped-def]
    enc = ObsEncoder(2, version)
    model = ActorCritic(enc.dim, N_ACTIONS, (64, 32), prior_offset=enc.prior_offset if residual else None)
    agent = PolicyAgent(model.actor_layers(), n_players=2, obs_version=version, prior_scale=model.prior_scale())
    obs = Game(RulesConfig(), seed=3).observe(0)
    x = torch.as_tensor(enc.encode(obs))[None]
    expected = model.logits(x).detach().numpy()[0]
    assert np.allclose(agent.logits(obs), expected, atol=1e-4)

    path = tmp_path / "p.npz"
    agent.save(path)
    loaded = make_agent(f"ppo:{path}")
    assert np.allclose(loaded.logits(obs), expected, atol=1e-5)  # type: ignore[attr-defined]
    play_game([loaded, make_agent("greedy")], seed=0)
    with pytest.raises(ValueError, match="trained for 2 players"):
        play_game([loaded, make_agent("greedy"), make_agent("greedy")], seed=0)


def test_v4_policy_plays_any_table_size(tmp_path) -> None:  # type: ignore[no-untyped-def]
    enc = ObsEncoder(None, version=4)
    model = ActorCritic(enc.dim, N_ACTIONS, (32,), prior_offset=enc.prior_offset)
    agent = PolicyAgent(model.actor_layers(), n_players=None, obs_version=4, prior_scale=model.prior_scale())
    obs = Game(RulesConfig(n_players=5), seed=3).observe(2)
    expected = model.logits(torch.as_tensor(enc.encode(obs))[None]).detach().numpy()[0]
    assert np.allclose(agent.logits(obs), expected, atol=1e-4)

    path = tmp_path / "p.npz"
    agent.save(path)
    loaded = make_agent(f"ppo:{path}")
    for n in (2, 3, 8):
        play_game([loaded] + [make_agent("greedy") for _ in range(n - 1)], seed=n)


@pytest.mark.parametrize("n_players", range(2, 9))
def test_v4_layout_is_independent_of_table_size(n_players: int) -> None:
    from skyjo.rl.encoding import MAX_PLAYERS, layout

    enc = ObsEncoder(None, version=4)
    assert enc.n_players is None and enc.supports(n_players)
    game = Game(RulesConfig(n_players=n_players), seed=n_players)
    while not game.is_over and game.phase.name == "SETUP":
        game.step(game.legal_actions()[0])
    vec = enc.encode(game.observe(1))
    assert vec.shape == (enc.dim,) and np.isfinite(vec).all()
    offsets, pos = {}, 0
    for name, width in layout(4, None):
        offsets[name] = (pos, width)
        pos += width
    start, width = offsets["table"]
    assert vec[start : start + width].tolist() == [float(i == n_players - 2) for i in range(MAX_PLAYERS - 1)]
    start, width = offsets["boards"]
    seat_block = width // MAX_PLAYERS
    assert not vec[start + n_players * seat_block : start + width].any()  # absent seats are zero


@pytest.mark.parametrize("src_version", [1, 2, 3])
def test_older_weights_transplant_exactly_into_v4(src_version: int) -> None:
    from skyjo.rl.ppo import _transplant_inputs

    src_enc, dst_enc = ObsEncoder(2, src_version), ObsEncoder(None, 4)
    prior = src_enc.prior_offset is not None
    src = ActorCritic(src_enc.dim, N_ACTIONS, (64, 32), prior_offset=src_enc.prior_offset)
    dst = ActorCritic(dst_enc.dim, N_ACTIONS, (64, 32), prior_offset=dst_enc.prior_offset if prior else None)
    state = {k: v.clone() for k, v in src.state_dict().items()}
    _transplant_inputs(state, src_version, 2, 4)
    dst.load_state_dict(state)

    game, rng = Game(RulesConfig(n_players=2), seed=7), np.random.default_rng(0)
    xs_src, xs_dst = [], []
    while not game.is_over and len(xs_src) < 200:
        obs = game.observe(game.current_player)
        xs_src.append(src_enc.encode(obs))
        xs_dst.append(dst_enc.encode(obs))
        game.step(int(rng.choice(game.legal_actions())))
    a, b = torch.as_tensor(np.stack(xs_src)), torch.as_tensor(np.stack(xs_dst))
    with torch.no_grad():
        assert torch.allclose(src.logits(a), dst.logits(b), atol=1e-5)
        assert torch.allclose(src.value(a), dst.value(b), atol=1e-5)


def test_env_samples_table_sizes() -> None:
    cfg = EnvConfig(table_sizes={2: 1.0, 5: 1.0}, episode="round", opponents={"greedy": 1.0}, obs_version=4)
    env = SkyjoEnv(cfg, seed=0)
    seen = set()
    rng = np.random.default_rng(0)
    for _ in range(12):
        env.reset()
        assert env.game is not None
        seen.add(env.game.rules.n_players)
        assert len(env.opponents) == env.game.rules.n_players - 1
        done = False
        while not done:
            done = env.step(int(rng.choice(np.flatnonzero(env.action_masks()))))[2]
    assert seen == {2, 5}
    with pytest.raises(ValueError, match="fixed to 2 players"):
        EnvConfig(table_sizes={3: 1.0}, obs_version=3)


def test_v3_prior_block_ranks_actions_like_expert() -> None:
    enc = ObsEncoder(2, version=3)
    assert enc.prior_offset is not None
    expert = make_agent("expert", seed=0)
    game = Game(RulesConfig(n_players=2), seed=5)
    checked = 0
    while not game.is_over and checked < 300:
        seat = game.current_player
        obs, legal = game.observe(seat), game.legal_actions()
        action = expert.act(obs, legal)
        if obs.phase.name != "SETUP" and len(legal) > 1:
            prior = enc.encode(obs)[enc.prior_offset : enc.prior_offset + N_ACTIONS]
            assert prior[action] == 0.0 and prior.max() == 0.0
            checked += 1
        game.step(action)
    assert checked > 100


def test_self_play_snapshots_in_pool() -> None:
    enc = ObsEncoder(2)
    env = SkyjoEnv(EnvConfig(opponents={"self": 1.0}), seed=0)
    env.pool.add_snapshot(ActorCritic(enc.dim, N_ACTIONS, (32,)).actor_layers())
    env.reset()
    assert all(o.name == "self" for o in env.opponents.values())


def test_sync_and_subproc_vec_env_agree_on_shapes() -> None:
    cfg = EnvConfig(opponents={"greedy": 1.0})
    for vec in (SyncVecEnv(cfg, 4, seed=0), SubprocVecEnv(cfg, 4, num_workers=2, seed=0)):
        obs, masks = vec.reset()
        assert obs.shape == (4, vec.obs_dim) and masks.shape == (4, N_ACTIONS)
        actions = np.array([np.flatnonzero(m)[0] for m in masks])
        obs, masks, rew, done, _ = vec.step(actions)
        assert rew.shape == (4,) and done.shape == (4,)
        vec.close()


def test_load_config_overrides(tmp_path) -> None:  # type: ignore[no-untyped-def]
    path = tmp_path / "c.yaml"
    path.write_text("env:\n  opponents: {ev: 1.0}\nppo:\n  num_envs: 16\n")
    cfg = load_config(path, ["ppo.learning_rate=1e-3", "eval.games=10"])
    assert cfg.env.opponents == {"ev": 1.0}
    assert cfg.ppo.num_envs == 16 and cfg.ppo.learning_rate == 1e-3 and cfg.eval.games == 10
    assert cfg.ppo.num_steps == 128  # untouched default
    with pytest.raises(KeyError):
        load_config(None, ["ppo.nope=1"])
