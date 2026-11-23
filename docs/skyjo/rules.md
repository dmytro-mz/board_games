# Skyjo rules (as implemented)

Source: official Magilano rulebook (EN), cross-checked with skyjo.co.uk FAQ.

## Material
150 cards: `-2`×5, `-1`×10, `0`×15, `1`…`12`×10 each. 2–8 players.

## Setup (each round)
1. Deal 12 face-down cards per player as a 3-row × 4-column grid.
2. Flip the top deck card to start the discard pile.
3. Each player reveals 2 cards of their choice (`Phase.SETUP`, flip actions).
4. Round 1: the player with the highest sum of revealed cards starts
   (ties → lowest seat; unspecified by the rules). Later rounds: the previous finisher starts.

## Turn
Choose a source (`Phase.CHOOSE_SOURCE`):
- **Take the discard** → must swap it with any of your cards (face up or down);
  the replaced card goes face up onto the discard pile (`Phase.PLACE_DISCARD`).
- **Draw from the deck** → either swap it as above, or discard it and reveal one
  face-down card (`Phase.PLACE_DRAWN`).

**Column rule:** three face-up cards of equal value in one column are discarded
immediately (the swapped-out card goes to the discard pile first, the triplet on top).
Also applies to the final reveal at round end.

Empty deck: the discard pile minus its top card is shuffled into a new deck.

## End of round
When a player has no face-down cards left at the end of their turn, they become the
**finisher**; every other player gets exactly one more turn. Then all cards are revealed,
columns are cleared, and each player scores the sum of their remaining cards.

**Doubling:** if the finisher's score is positive and someone else scored *lower or equal*,
the finisher's score is doubled. Zero / negative scores are never doubled.

## End of game
After a round in which any cumulative score reaches ≥100, the lowest total wins.
Tied winners share the win (each gets 1/k in tournament win rates).

## Engine-only safety valves (not in the rulebook)
- `max_turns_per_round = 400`: round is scored without a finisher (degenerate policies).
- `max_rounds = 60` per game.

## Information structure (important for RL)
Every card becomes public the moment it is seen: drawn cards are placed or discarded
face up; face-down grid cards are unknown to *everyone, including their owner*. So Skyjo
is a perfect-information stochastic game: all unseen cards are an exchangeable random
draw from the multiset `composition − visible board cards − discard pile`.
`Observation.unknown_counts` is that multiset, which makes the observation a sufficient
statistic of the public history (no memory / RNN needed).
