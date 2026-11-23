"""A heuristic hero: gears up, explores, clears lairs, buys walls, traps and seals, then hunts the Beast."""

from __future__ import annotations

import random
from collections import deque

from avel.bots.base import Bot
from avel.bots.tactics import Estimate, clash_choice, item_value, keep_fighting, reward_value, simulate
from avel.game import actions as A
from avel.game.actions import Action
from avel.game.engine import Hero, Item, Monster, Phase, View, distances, hero_pool, monster_pool
from avel.game.model import (
    MAX_TOUGHNESS,
    MOON_TRACK,
    PRICE,
    SLOTS,
    Hex,
    Kind,
    Size,
    neighbours,
)
from avel.game.model import (
    Action as TileAction,
)


class HeroBot(Bot):
    def __init__(
        self,
        seed: int | None = None,
        runs: int = 80,
        careful: float = 0.2,
        seal_value: float = 3,
        explore_seal: float = 0,
        near_threat: float = 0,
    ) -> None:
        super().__init__(seed)
        self.rng = random.Random(seed)
        self.runs = runs
        self.careful = careful
        self.seal_value = seal_value
        self.explore_seal = explore_seal
        self.near_threat = near_threat
        self._cache: dict[tuple, Estimate] = {}

    # ------------------------------------------------------------------ entry
    def act(self, view: View) -> Action:
        legal = view.legal
        assert legal, "asked to act without legal actions"
        if len(legal) == 1:
            return legal[0]
        me = view.hero()
        match view.phase:
            case Phase.TURN:
                action = self._turn(view, me)
            case Phase.PREPARE:
                action = self._prepare(view, me)
            case Phase.CLASH:
                action = self._clash(view, me)
            case Phase.AFTER_CLASH:
                action = self._after_clash(view, me)
            case Phase.CHOOSE_UPGRADE:
                action = self._choose_upgrade(view, me)
            case Phase.OVERFLOW:
                action = self._overflow(view, me)
            case Phase.STUN_LOSS:
                action = self._stun_loss(view, me)
            case Phase.STEER:
                action = self._steer(view)
            case _:
                action = legal[0]
        if action not in legal:  # never stall a game on a planning slip
            action = next((a for a in legal if isinstance(a, A.EndTurn | A.Done | A.Resolve | A.Fight)), legal[0])
        return action

    # ------------------------------------------------------------------ helpers
    def items_of(self, view: View, hero: Hero) -> list[Item]:
        return [view.items[i] for i in hero.equipped]

    def estimate(self, view: View, hero: Hero, monster: Monster, potions=(), toughness: int | None = None) -> Estimate:
        items = self.items_of(view, hero)
        hp = hero.toughness if toughness is None else toughness
        desperate = view.beast_out
        key = (
            tuple((i.key, i.upgraded) for i in items),
            tuple(potions),
            hp,
            monster.key,
            monster.left,
            desperate,
        )
        if key not in self._cache:
            self._cache[key] = simulate(
                items, list(potions), hp, monster.type, monster.left, self.rng, self.runs, desperate
            )
        return self._cache[key]

    def battle_potions(self, view: View, hero: Hero, monster: Monster) -> list:
        from avel.game.model import Attribute

        if monster.type.attribute == Attribute.NO_ELIXIR:
            return []
        out = []
        for i in hero.pack:
            p = view.items[i].type.potion
            if p is not None:
                out.append(p)
        return out

    def worth_fighting(self, view: View, hero: Hero, monster: Monster) -> float:
        """Score of battling this monster now (<= 0: don't)."""
        potions = self.battle_potions(view, hero, monster) if monster.type.size != Size.SMALL else []
        est = self.estimate(view, hero, monster, tuple(sorted(potions)))
        castle_dist = distances(view.tiles).get(monster.at, 9)
        threat = self.threat(view, monster, castle_dist)
        if monster.type.size == Size.BEAST:
            if est.stun > 0.45 and hero.toughness < MAX_TOUGHNESS:
                return 0
            return 4 + est.dealt * 3 + threat - est.stun * 6
        risk = self.careful + (0.25 if view.beast_out else 0) + (0.15 if threat > 3 else 0)
        # once the march is on a stun only sends the hero back to the castle, right next to this monster
        last_stand = view.beast_out and castle_dist <= 1
        if not last_stand and (est.stun > risk + 0.15 or (est.stun > risk and est.kill < 0.5)):
            return 0
        if est.kill < 0.2 and est.dealt < 0.8 and threat < 3:
            return 0
        stun_cost = 3 + 0.6 * hero.coins + 1.5 * len(hero.owned)
        return est.kill * (reward_value(monster.type) + threat) + est.dealt * (0.8 + threat / 4) - est.stun * stun_cost

    def threat(self, view: View, monster: Monster, castle_dist: int) -> float:
        """How urgently this monster has to go (it marches on the castle once the Beast is out)."""
        if view.beast_out:
            # a monster next to the castle breaks a wall (or gets in) at the end of this round
            urgency = {1: 18 + 6 * (view.walls <= 1), 2: 9, 3: 5}.get(castle_dist, 2)
            return urgency + (4 if monster.type.size == Size.BEAST else 0)
        rounds_left = len(MOON_TRACK) - 1 - view.moon
        steady = {1: self.near_threat, 2: self.near_threat / 3}.get(castle_dist, 0.0)
        if rounds_left <= 4 and castle_dist <= 2:
            return steady + (3 - castle_dist) * (5 - rounds_left) * 1.5
        return steady

    # ------------------------------------------------------------------ the turn
    def _turn(self, view: View, me: Hero) -> Action:
        legal = view.legal
        free = self._free_move(view, me)
        if free is not None:
            return free
        if view.actions_left <= 0:
            return A.EndTurn()
        here = me.at
        # battle a monster on this tile
        best_battle: tuple[float, Action] | None = None
        for m in view.monsters_at(here):
            score = self.worth_fighting(view, me, m)
            if score > 0 and (best_battle is None or score > best_battle[0]):
                best_battle = (score, A.Battle(m.id))
        # a more urgent monster that can still be reached and fought this turn wins over the one here
        if view.actions_left >= 2 and view.beast_out:
            reach = self._hero_dist(view, me.at)
            for m in view.monsters.values():
                if m.at == here or reach.get(m.at, (9, None))[0] != 1:
                    continue
                score = self.worth_fighting(view, me, m) / 1.9
                if score > 0 and (best_battle is None or score > best_battle[0]):
                    best_battle = (score, A.Move(m.at))
        if best_battle and best_battle[1] in legal:
            return best_battle[1]
        if me.toughness <= 2 and A.Rest() in legal:
            return A.Rest()
        tile_action = self._tile_action(view, me)
        if tile_action is not None and tile_action in legal:
            return tile_action
        target = self._goal(view, me)
        if target is not None and target != here:
            step = self._step_towards(view, me, target)
            if step is not None and A.Move(step) in legal:
                return A.Move(step)
        if me.toughness < MAX_TOUGHNESS and A.Rest() in legal:
            return A.Rest()
        return A.EndTurn()

    def _free_move(self, view: View, me: Hero) -> Action | None:
        legal = view.legal
        for a in legal:
            if isinstance(a, A.Drink) and me.toughness <= 2 and view.items[a.item].type.heals:
                return a
        for a in legal:
            if isinstance(a, A.Equip):
                new = view.items[a.item]
                old_id = me.slots[new.kind]
                if old_id is None:
                    return a
                old = view.items[old_id]
                if new.upgraded and not old.upgraded:
                    return a
        for a in legal:
            if isinstance(a, A.Give) and a.item is not None and a.item in me.pack:
                mate = view.heroes[a.to]
                kind = view.items[a.item].kind
                if kind in SLOTS and mate.slots[kind] is None:
                    return a
        return None

    def _tile_action(self, view: View, me: Hero) -> Action | None:
        legal = view.legal
        tile = view.tiles[me.at]
        if not tile.face_up or not tile.key:
            return None
        action = tile.type.action
        if action == TileAction.MARKET:
            return self._market(view, me)
        if action == TileAction.UPGRADE:
            ups = [a for a in legal if isinstance(a, A.Upgrade)]
            if ups and me.coins - PRICE >= self._wall_budget(view):
                return max(ups, key=lambda a: (a.item in me.equipped, view.items[a.item].kind == Kind.WEAPON))
        if action == TileAction.WALL and self._want_wall(view, me):
            return A.Wall()
        if action == TileAction.TRAP:
            return self._trap(view, me)
        if action == TileAction.SEAL:
            return self._seal(view, me)
        if view.beast_out:
            return None
        if action == TileAction.WORK and A.Work() in legal and self._room(view, me) >= 2:
            return A.Work()
        if action == TileAction.WISH and A.Wish() in legal and me.coins <= 4 and self._room(view, me) >= 4:
            return A.Wish()
        return None

    def _room(self, view: View, me: Hero) -> int:
        from avel.game import backpack

        return backpack.free_cells([view.items[i].kind for i in me.pack]) - me.coins

    def _empty_slots(self, me: Hero) -> int:
        return sum(1 for k in SLOTS if me.slots[k] is None)

    def _market(self, view: View, me: Hero) -> Action | None:
        options = [a for a in view.legal if isinstance(a, A.Market)]
        best: tuple[float, Action] | None = None
        spare = [i for i in me.pack if view.items[i].kind in SLOTS]
        for a in options:
            if any(i in me.equipped for i in a.sell):
                continue
            if any(view.items[i].type.potion is None and view.items[i].kind == Kind.ELIXIR for i in a.sell):
                continue
            coins_after = me.coins + 2 * len(a.sell) - PRICE * a.buy
            if a.buy == 0 and not all(i in spare for i in a.sell):
                continue
            if a.buy and coins_after < self._wall_budget(view):
                continue
            score = a.buy * (3 + 2 * (self._empty_slots(me) > 0)) + sum(2.0 for i in a.sell if i in spare)
            if best is None or score > best[0]:
                best = (score, a)
        if best is not None and (self._empty_slots(me) > 0 or me.coins >= 6 or spare):
            return best[1]
        return None

    def _wall_budget(self, view: View) -> int:
        """Coins this hero keeps for walls (the castle's only real defence once the Beast is out).

        The team saves for the missing walls together: the richest heroes keep 3 coins per wall each.
        """
        if not view.walls_left or (view.beast_out and view.march_rounds > 0):
            return 0
        if view.moon < 8 and not view.beast_out:
            return 0
        me = view.hero()
        richer = sorted(view.heroes, key=lambda h: (-h.coins, h.seat))
        rank = next(i for i, h in enumerate(richer) if h.seat == me.seat)
        walls = view.walls_left
        share = walls // view.n + (1 if rank < walls % view.n else 0)
        return PRICE * share

    def _want_wall(self, view: View, me: Hero, ignore_coins: bool = False) -> bool:
        if not view.walls_left or not (not view.beast_out or view.march_rounds == 0):
            return False
        if not ignore_coins and me.coins < PRICE:
            return False
        return view.moon >= 8 or view.beast_out

    def _beast_path(self, view: View) -> list[Hex]:
        crater = next((t.hex for t in view.tiles.values() if t.crater), None)
        beast = view.monsters.get("beast")
        start = beast.at if beast else crater
        if start is None:
            return []
        dist = distances(view.tiles)
        path, h = [], start
        while dist.get(h, 0) > 1:
            h = min((n for n in neighbours(h) if dist.get(n) == dist[h] - 1), key=lambda x: x)
            path.append(h)
        return path

    def _trap(self, view: View, me: Hero) -> Action | None:
        traps = [a for a in view.legal if isinstance(a, A.Trap)]
        if not traps:
            return None
        path = [h for h in self._beast_path(view) if view.tiles[h].face_up and view.tiles[h].trap is None]
        if not path:
            return None
        budget = self._wall_budget(view)
        traps = [a for a in traps if me.coins - a.level >= budget]
        if not traps:
            return None
        best_level = max(a.level for a in traps)
        for h in path:
            a = A.Trap(best_level, h)
            if a in traps:
                return a
        return None

    def _seal(self, view: View, me: Hero) -> Action | None:
        seals = [a for a in view.legal if isinstance(a, A.Seal)]
        dist = distances(view.tiles)
        if not seals:
            return None
        if me.coins - PRICE < self._wall_budget(view) and min(dist.get(a.at, 9) for a in seals) > 1:
            return None

        def size(a: A.Seal) -> int:
            return 1 if view.tiles[a.at].type.lairs[a.lair] == Size.BIG else 0

        return max(seals, key=lambda a: (-dist.get(a.at, 0), size(a)))

    def _open_lairs(self, view: View, near: int) -> list[tuple[Hex, int]]:
        """Empty, unsealed lairs on face-up tiles within `near` steps of the castle."""
        dist = distances(view.tiles)
        out = []
        for t in view.tiles.values():
            if not t.face_up or dist.get(t.hex, 9) > near:
                continue
            for i, sealed in enumerate(t.seals):
                if not sealed and not any(m.at == t.hex and m.lair == i for m in view.monsters.values()):
                    out.append((t.hex, i))
        return out

    # ------------------------------------------------------------------ navigation
    def _hero_dist(self, view: View, start: Hex) -> dict[Hex, tuple[int, Hex | None]]:
        """BFS over the hero's moves: distance and the first step."""
        out: dict[Hex, tuple[int, Hex | None]] = {start: (0, None)}
        q = deque([start])
        while q:
            h = q.popleft()
            d, first = out[h]
            nxt = [n for n in neighbours(h) if n in view.tiles]
            tile = view.tiles[h]
            if tile.face_up and tile.key and tile.type.shortcut:
                nxt += [t.hex for t in view.tiles.values() if t.face_up and t.key and t.type.shortcut and t.hex != h]
            for n in nxt:
                if n not in out:
                    out[n] = (d + 1, n if first is None else first)
                    if view.tiles[n].face_up:
                        q.append(n)
        return out

    def _step_towards(self, view: View, me: Hero, target: Hex) -> Hex | None:
        reach = self._hero_dist(view, me.at)
        return reach[target][1] if target in reach else None

    def _goal(self, view: View, me: Hero) -> Hex | None:
        reach = self._hero_dist(view, me.at)
        others = [h.at for h in view.heroes if h.seat != me.seat]
        best: tuple[float, Hex] | None = None

        def consider(h: Hex, value: float) -> None:
            nonlocal best
            # the turn already tried everything worth doing here
            if h not in reach or value <= 0 or h == me.at:
                return
            d = reach[h][0]
            score = value / (1 + d * 0.9)
            if best is None or score > best[0]:
                best = (score, h)

        for m in view.monsters.values():
            score = self.worth_fighting(view, me, m)
            if m.at in others and not view.beast_out:
                score *= 0.5
            consider(m.at, score)
        coins = me.coins
        known = {t.key for t in view.tiles.values() if t.face_up}
        explore = 3.5 + 0.4 * view.moon
        if "quarry" not in known and view.moon >= 4:
            explore += 4
        if "alchemist" not in known:
            explore += 1.5
        if "stone_circles" not in known and view.moon <= 8:
            explore += self.explore_seal
        spare_coins = coins - self._wall_budget(view)
        for t in view.tiles.values():
            if not t.face_up:
                if not view.beast_out:
                    consider(t.hex, explore if t.hex not in others else 1)
                continue
            action = t.type.action
            spares = sum(1 for i in me.pack if view.items[i].kind in SLOTS)
            if action == TileAction.MARKET and (spare_coins >= PRICE or spares):
                consider(t.hex, 2 + 3 * self._empty_slots(me) * (spare_coins >= PRICE) + 2.5 * spares)
            elif action == TileAction.UPGRADE and spare_coins >= PRICE:
                if any(view.items[i].type.upgradable and not view.items[i].upgraded for i in me.equipped):
                    consider(t.hex, 7 + 2 * min(spare_coins // PRICE, 3))
            elif action == TileAction.WORK and not view.monsters_at(t.hex) and not view.beast_out:
                consider(t.hex, 1.5 if coins < 6 else 0.5)
            elif action == TileAction.WALL and self._want_wall(view, me):
                consider(t.hex, 9 + 3 * min(coins // PRICE, view.walls_left) + (4 if view.beast_out else 0))
            elif action == TileAction.TRAP and view.moon <= 11 and not view.beast_out and view.moon >= 4:
                affordable = [lvl for lvl, at in view.traps.items() if at is None and spare_coins >= lvl]
                if affordable:
                    consider(t.hex, 4 + 0.8 * max(affordable))
            elif action == TileAction.SEAL and coins >= PRICE and view.seals_left:
                if not view.beast_out and view.moon <= 10:
                    close = bool(self._open_lairs(view, near=1))
                    if close or spare_coins >= PRICE:
                        far = bool(self._open_lairs(view, near=9))
                        consider(t.hex, self.seal_value * far + 4 * bool(self._open_lairs(view, near=2)) + 8 * close)
            elif action == TileAction.WISH and 1 <= coins <= 3 and not view.beast_out:
                consider(t.hex, 1.2)
        if me.toughness <= 2:
            return None
        return best[1] if best else None

    # ------------------------------------------------------------------ battle
    def _prepare(self, view: View, me: Hero) -> Action:
        battle = view.battle
        assert battle is not None
        monster = view.monsters[battle.monster]
        drinks = [a for a in view.legal if isinstance(a, A.Drink)]
        if drinks and monster.type.size != Size.SMALL:
            return drinks[0]
        if drinks and monster.type.size == Size.SMALL:
            base = self.estimate(view, me, monster, tuple(sorted(battle.potions)))
            if base.kill < 0.5 and view.beast_out:
                return drinks[0]
        return A.Fight()

    def _clash(self, view: View, me: Hero) -> Action:
        battle = view.battle
        assert battle is not None
        monster = view.monsters[battle.monster]
        return clash_choice(
            battle.dice,
            battle.bonus,
            self.items_of(view, me),
            battle.used,
            monster.type,
            me.toughness,
            monster.left,
        )

    def _after_clash(self, view: View, me: Hero) -> Action:
        battle = view.battle
        assert battle is not None
        monster = view.monsters[battle.monster]
        pool = hero_pool(self.items_of(view, me), battle.potions, monster.type) + monster_pool(monster.type)
        if keep_fighting(pool, me.toughness, monster.left, battle.clash, view.beast_out):
            return A.Fight()
        return A.Retreat()

    # ------------------------------------------------------------------ bookkeeping
    def _choose_upgrade(self, view: View, me: Hero) -> Action:
        options = [a for a in view.legal if isinstance(a, A.ChooseUpgrade)]
        order = {Kind.WEAPON: 3, Kind.HELMET: 2, Kind.SHIELD: 1}
        return max(options, key=lambda a: (a.item in me.equipped, order.get(view.items[a.item].kind, 0)))

    def _overflow(self, view: View, me: Hero) -> Action:
        legal = view.legal
        if A.Done() in legal:
            return A.Done()
        for a in legal:
            if isinstance(a, A.Equip):
                new = view.items[a.item]
                old_id = me.slots[new.kind]
                if old_id is None or (new.upgraded and not view.items[old_id].upgraded):
                    return a
        drops = [a for a in legal if isinstance(a, A.Discard)]
        from avel.game import backpack

        kinds = [view.items[i].kind for i in me.pack]
        excess = me.coins - backpack.free_cells(kinds)  # coins that don't fit next to the items
        coin_value = 1.6 if self._wall_budget(view) else 1.0

        def cost(a: A.Discard) -> float:
            if a.item is None:
                return coin_value * max(1, excess)
            value = item_value(view.items[a.item], a.item in me.equipped)
            if a.item in me.pack:
                value -= 1.5
                if view.items[a.item].kind in SLOTS:
                    value -= 1.0  # a spare weapon / shield / helmet that nobody wields
            return value

        return min(drops, key=cost)

    def _stun_loss(self, view: View, me: Hero) -> Action:
        options = [a for a in view.legal if isinstance(a, A.Lose)]
        return min(options, key=lambda a: item_value(view.items[a.item], a.item in me.equipped))

    def _steer(self, view: View) -> Action:
        options = [a for a in view.legal if isinstance(a, A.Steer)]
        march = view.march
        assert march is not None and march.monster is not None
        monster = view.monsters[march.monster]
        heroes = [h.at for h in view.heroes]

        def score(a: A.Steer) -> tuple:
            tile = view.tiles[a.to]
            trap = tile.trap is not None and monster.type.size == Size.BEAST
            near = -min((abs(a.to[0] - h[0]) + abs(a.to[1] - h[1]) for h in heroes), default=0)
            return (trap, a.to in heroes, near)

        return max(options, key=score)
