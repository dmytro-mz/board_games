from __future__ import annotations

from pandemic.game.engine import Game, RulesConfig
from pandemic.game.model import COLORS, CUBES_PER_COLOR, Color, Role


def new_game(*roles: Role, seed: int = 1, epidemics: int = 4, clear: bool = True) -> Game:
    """A game with these roles; `clear` removes the setup cubes so tests start from an empty board."""
    game = Game(len(roles), seed=seed, rules=RulesConfig(epidemics=epidemics, roles=tuple(roles)))
    if clear:
        for city in game.cubes:
            for color in COLORS:
                game.cubes[city][color] = 0
        game.supply = dict.fromkeys(COLORS, CUBES_PER_COLOR)
    return game


def hand(game: Game, seat: int, *cards: str) -> None:
    """Give `seat` exactly these cards, taken from wherever they are; the cards it held go under the deck."""
    for pile in (*game.hands, game.player_deck, game.player_discard):
        pile[:] = [c for c in pile if c not in cards]
    game.player_deck[:0] = game.hands[seat]
    game.hands[seat] = list(cards)


def cubes(game: Game, city: str, color: Color | str, n: int) -> None:
    color = Color(color)
    game.supply[color] += game.cubes[city][color] - n
    game.cubes[city][color] = n


def top_infection(game: Game, *cities: str) -> None:
    """Put these infection cards on top of the deck, the first one on the very top."""
    game.infection_deck = [c for c in game.infection_deck if c not in cities] + list(reversed(cities))
    game.infection_discard = [c for c in game.infection_discard if c not in cities]


def top_player(game: Game, *cards: str) -> None:
    """Put these player cards on top of the deck, the first one on the very top (repeat "epidemic" as needed)."""
    deck = list(game.player_deck)
    for c in cards:
        deck.remove(c)
    game.player_deck = deck + list(reversed(cards))
