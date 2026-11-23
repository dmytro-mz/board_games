from __future__ import annotations

from phase10.game.engine import Game
from phase10.game.model import Card, Color, Kind

COLORS = {"r": Color.RED, "b": Color.BLUE, "g": Color.GREEN, "y": Color.YELLOW}


def _matches(card: Card, spec: str) -> bool:
    if spec == "w":
        return card.kind == Kind.WILD
    if spec == "s":
        return card.kind == Kind.SKIP
    return card.natural and card.color == COLORS[spec[0]] and card.value == int(spec[1:])


def rig(game: Game, seat: int, specs: str, top: str | None = None) -> list[Card]:
    """Give `seat` exactly the cards in `specs` ("r7 b7 w s"), taken from wherever they are; the cards it held go
    to the draw pile. With `top`, that card becomes the top of the discard pile. Returns the new hand."""
    wanted = specs.split()
    picked: list[Card] = []
    for spec in wanted:
        card = next(
            c
            for c in game.deck
            if _matches(c, spec) and c not in picked and (top is None or c not in game.discard[-1:])
        )
        picked.append(card)
    if top is not None:
        top_card = next(c for c in game.deck if _matches(c, top) and c not in picked)
    for pile in (*game.hands, game.draw, game.discard):
        pile[:] = [c for c in pile if c not in picked and (top is None or c != top_card)]
    game.draw.extend(game.hands[seat])
    game.hands[seat] = picked
    if top is not None:
        game.discard.append(top_card)
    assert game.card_count() == 108
    return picked


def ids(cards: list[Card], *picks: int) -> tuple[int, ...]:
    return tuple(cards[i].id for i in picks)
