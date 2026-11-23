"""Static game data from the official rulebook: the board, the 38 agent cards and the 15 black market cards."""

from __future__ import annotations

from dataclasses import dataclass

# ---------------------------------------------------------------- board
# 14 spaces in a loop, numbered clockwise from the green home space. Both sides of the printed board have the
# same track; the advanced side adds the 4 black market corners.
TRACK = 14
HOMES = (0, 7)  # green home, blue home (the two teams start here, 7 spaces apart)
MARKET_SPACES = frozenset({2, 5, 9, 12})  # the 4 corners
HAND_SIZE = 4
DISCARDS_SOLO = 4  # optional "discard and draw", per game
DISCARDS_TEAM = 2  # per teammate in the team variant
SUPPLY_SIZE = 3

WIN = "win"  # Codebreaker's 3rd icon (a check mark)
LOSE = "lose"  # Daredevil's 3rd icon (an X)


@dataclass(frozen=True)
class Agent:
    key: str
    name: str
    animal: str
    icons: tuple[int | str, ...]  # 1st / 2nd / 3rd+ copy in play
    copies: int


AGENT_LIST: tuple[Agent, ...] = (
    Agent("double_agent", "Double Agent", "fox", (-1, 6, -1), 6),
    Agent("enforcer", "Enforcer", "squirrel", (1, 2, 3), 6),
    Agent("codebreaker", "Codebreaker", "owl", (0, 0, WIN), 6),
    Agent("saboteur", "Saboteur", "raccoon", (-1, -1, -2), 6),
    Agent("daredevil", "Daredevil", "wolf", (2, 3, LOSE), 6),
    Agent("sentinel", "Sentinel", "pigeon", (0, 2, 6), 6),
    Agent("sidekick", "Sidekick", "otter", (4,), 1),
    Agent("mole", "Mole", "mole", (-3,), 1),
)
N_AGENTS = len(AGENT_LIST)
AGENT_INDEX = {a.key: i for i, a in enumerate(AGENT_LIST)}
DOUBLE_AGENT, ENFORCER, CODEBREAKER, SABOTEUR, DAREDEVIL, SENTINEL, SIDEKICK, MOLE = range(N_AGENTS)
DECK_COUNTS = tuple(a.copies for a in AGENT_LIST)  # 38 cards
TOTAL_AGENTS = sum(DECK_COUNTS)


def _base_move(agent: int, count: int) -> int:
    icons = AGENT_LIST[agent].icons
    icon = icons[min(count, 3, len(icons)) - 1]
    return icon if isinstance(icon, int) else 0


# BASE_MOVES[agent][count] for count 0..3 (the 4th, 5th, ... copy counts as the 3rd)
BASE_MOVES = tuple(tuple(0 if n == 0 else _base_move(a, n) for n in range(4)) for a in range(N_AGENTS))


def base_move(agent: int, count: int) -> int:
    """Spaces moved for recruiting `agent` when `count` copies are in play (including the new one)."""
    return BASE_MOVES[agent][count if count < 3 else 3]


@dataclass(frozen=True)
class MarketCard:
    key: str
    name: str
    ongoing: bool  # ∞ ongoing ability (stays in front of you) vs ⚡ instant ability (resolved, then discarded)
    text: str


MARKET_LIST: tuple[MarketCard, ...] = (
    # ongoing abilities
    MarketCard(
        "distraction_device",
        "Distraction Device",
        True,
        "When you recruit a Saboteur, move forward instead of backward.",
    ),
    MarketCard(
        "watchtower_hq", "Watchtower HQ", True, "When you recruit an Enforcer, move 2 additional spaces forward."
    ),
    MarketCard("sinister_twin", "Sinister Twin", True, "When you recruit a Double Agent, move twice as far."),
    MarketCard("supercomputer", "Supercomputer", True, "When you recruit a Codebreaker, move 3 spaces forward."),
    MarketCard(
        "leader_of_the_pack",
        "Leader of the Pack",
        True,
        "During the End step, if you have 3 Daredevils in play, you win the game instead of losing it.",
    ),
    MarketCard(
        "getaway_car", "Getaway Car", True, "When you land exactly on either home space, move 3 spaces forward."
    ),
    MarketCard(
        "masterplan",
        "Masterplan",
        True,
        "During the End step, if you have 7 different agents in play, you win the game.",
    ),
    MarketCard(
        "security_system",
        "Security System",
        True,
        "During the End step, if the opponent is on your home space, you win the game.",
    ),
    # instant abilities
    MarketCard("outpost", "Outpost", False, "Recruit a Sentinel from your hand."),
    MarketCard("smoke_screen", "Smoke Screen", False, "Recruit the top card of the agent deck."),
    MarketCard(
        "brainwashing_device", "Brainwashing Device", False, "Put 1 agent the opponent has in play into your hand."
    ),
    MarketCard(
        "double_trouble", "Double Trouble", False, "Reveal 2 of the same agent from your hand. Recruit 1 of them."
    ),
    MarketCard("surveillance_truck", "Surveillance Truck", False, "Move 1 space forward."),
    MarketCard(
        "secret_recruit",
        "Secret Recruit",
        False,
        "Recruit 1 agent from your hand that is different from the ones you have in play.",
    ),
    MarketCard(
        "spycation", "Spycation", False, "Put 1 agent you have in play into your hand. You may recruit it immediately."
    ),
)
N_MARKET = len(MARKET_LIST)
MARKET_INDEX = {m.key: i for i, m in enumerate(MARKET_LIST)}
(
    DISTRACTION,
    WATCHTOWER,
    SINISTER_TWIN,
    SUPERCOMPUTER,
    LEADER,
    GETAWAY,
    MASTERPLAN,
    SECURITY,
    OUTPOST,
    SMOKE_SCREEN,
    BRAINWASHING,
    DOUBLE_TROUBLE,
    TRUCK,
    SECRET_RECRUIT,
    SPYCATION,
) = range(N_MARKET)
