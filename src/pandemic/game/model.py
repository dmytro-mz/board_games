"""Static game data: the 48 cities and their connections, diseases, roles, events and the infection rate track."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Any


class Color(StrEnum):
    BLUE = "blue"
    YELLOW = "yellow"
    BLACK = "black"
    RED = "red"


COLORS: tuple[Color, ...] = (Color.BLUE, Color.YELLOW, Color.BLACK, Color.RED)


@dataclass(frozen=True)
class City:
    id: str
    name: str
    color: Color
    population: int  # only used to pick the first player, as in the rulebook


_CITY_ROWS = [
    ("sf", "San Francisco", "blue", 5_864_000),
    ("chi", "Chicago", "blue", 9_121_000),
    ("mon", "Montréal", "blue", 3_429_000),
    ("ny", "New York", "blue", 20_464_000),
    ("was", "Washington", "blue", 4_679_000),
    ("atl", "Atlanta", "blue", 4_715_000),
    ("lon", "London", "blue", 8_586_000),
    ("mad", "Madrid", "blue", 5_427_000),
    ("par", "Paris", "blue", 10_755_000),
    ("ess", "Essen", "blue", 575_000),
    ("mil", "Milan", "blue", 5_232_000),
    ("stp", "St. Petersburg", "blue", 4_879_000),
    ("la", "Los Angeles", "yellow", 14_900_000),
    ("mex", "Mexico City", "yellow", 19_463_000),
    ("mia", "Miami", "yellow", 5_582_000),
    ("bog", "Bogotá", "yellow", 8_702_000),
    ("lim", "Lima", "yellow", 9_121_000),
    ("san", "Santiago", "yellow", 6_015_000),
    ("bue", "Buenos Aires", "yellow", 13_639_000),
    ("sao", "São Paulo", "yellow", 20_186_000),
    ("lag", "Lagos", "yellow", 11_547_000),
    ("kin", "Kinshasa", "yellow", 9_046_000),
    ("joh", "Johannesburg", "yellow", 3_888_000),
    ("kha", "Khartoum", "yellow", 4_887_000),
    ("alg", "Algiers", "black", 2_946_000),
    ("cai", "Cairo", "black", 14_718_000),
    ("ist", "Istanbul", "black", 13_576_000),
    ("mos", "Moscow", "black", 15_512_000),
    ("bag", "Baghdad", "black", 6_204_000),
    ("riy", "Riyadh", "black", 5_037_000),
    ("teh", "Tehran", "black", 7_419_000),
    ("kar", "Karachi", "black", 20_711_000),
    ("del", "Delhi", "black", 22_242_000),
    ("mum", "Mumbai", "black", 16_910_000),
    ("che", "Chennai", "black", 8_865_000),
    ("kol", "Kolkata", "black", 14_374_000),
    ("bei", "Beijing", "red", 17_311_000),
    ("seo", "Seoul", "red", 22_547_000),
    ("tok", "Tokyo", "red", 13_189_000),
    ("sha", "Shanghai", "red", 13_482_000),
    ("osa", "Osaka", "red", 2_871_000),
    ("tai", "Taipei", "red", 8_338_000),
    ("hk", "Hong Kong", "red", 7_106_000),
    ("bkk", "Bangkok", "red", 7_151_000),
    ("man", "Manila", "red", 20_767_000),
    ("hcm", "Ho Chi Minh City", "red", 8_314_000),
    ("jak", "Jakarta", "red", 26_063_000),
    ("syd", "Sydney", "red", 3_785_000),
]

_EDGES = (
    "sf-tok sf-man sf-la sf-chi chi-la chi-mex chi-atl chi-mon mon-ny mon-was ny-was ny-lon ny-mad was-atl was-mia "
    "atl-mia lon-mad lon-par lon-ess mad-par mad-alg mad-sao par-ess par-mil par-alg ess-mil ess-stp mil-ist stp-ist "
    "stp-mos la-mex la-syd mex-mia mex-bog mex-lim mia-bog bog-lim bog-bue bog-sao lim-san bue-sao sao-lag lag-kha "
    "lag-kin kin-kha kin-joh joh-kha kha-cai alg-ist alg-cai cai-ist cai-bag cai-riy ist-mos ist-bag mos-teh bag-riy "
    "bag-kar bag-teh riy-kar teh-kar teh-del kar-mum kar-del del-mum del-che del-kol mum-che che-kol che-bkk che-jak "
    "kol-bkk kol-hk bei-sha bei-seo seo-sha seo-tok tok-sha tok-osa sha-tai sha-hk osa-tai tai-hk tai-man hk-man "
    "hk-hcm hk-bkk bkk-hcm bkk-jak man-hcm man-syd hcm-jak jak-syd"
)

CITIES: dict[str, City] = {cid: City(cid, name, Color(color), pop) for cid, name, color, pop in _CITY_ROWS}
EDGES: list[tuple[str, str]] = [tuple(e.split("-")) for e in _EDGES.split()]  # type: ignore[misc]
ADJ: dict[str, tuple[str, ...]] = {
    cid: tuple(b if a == cid else a for a, b in EDGES if cid in (a, b)) for cid in CITIES
}
START_CITY = "atl"


def distances(start: str) -> dict[str, int]:
    """Driving distance (number of Drive/Ferry actions) from `start` to every city."""
    dist = {start: 0}
    frontier = [start]
    while frontier:
        nxt = []
        for a in frontier:
            for b in ADJ[a]:
                if b not in dist:
                    dist[b] = dist[a] + 1
                    nxt.append(b)
        frontier = nxt
    return dist


DIST: dict[str, dict[str, int]] = {c: distances(c) for c in CITIES}


def path(start: str, goal: str) -> list[str]:
    """A shortest driving route, both ends included."""
    route = [goal]
    while route[-1] != start:
        here = route[-1]
        route.append(min(ADJ[here], key=lambda c: (DIST[start][c], c)))
    return route[::-1]


class Role(StrEnum):
    CONTINGENCY_PLANNER = "planner"
    DISPATCHER = "dispatcher"
    MEDIC = "medic"
    OPERATIONS_EXPERT = "ops"
    QUARANTINE_SPECIALIST = "quarantine"
    RESEARCHER = "researcher"
    SCIENTIST = "scientist"


ROLE_NAMES: dict[Role, str] = {
    Role.CONTINGENCY_PLANNER: "Contingency Planner",
    Role.DISPATCHER: "Dispatcher",
    Role.MEDIC: "Medic",
    Role.OPERATIONS_EXPERT: "Operations Expert",
    Role.QUARANTINE_SPECIALIST: "Quarantine Specialist",
    Role.RESEARCHER: "Researcher",
    Role.SCIENTIST: "Scientist",
}


class EventCard(StrEnum):
    AIRLIFT = "airlift"
    FORECAST = "forecast"
    GOVERNMENT_GRANT = "grant"
    ONE_QUIET_NIGHT = "quiet"
    RESILIENT_POPULATION = "resilient"


EVENT_NAMES: dict[EventCard, str] = {
    EventCard.AIRLIFT: "Airlift",
    EventCard.FORECAST: "Forecast",
    EventCard.GOVERNMENT_GRANT: "Government Grant",
    EventCard.ONE_QUIET_NIGHT: "One Quiet Night",
    EventCard.RESILIENT_POPULATION: "Resilient Population",
}
EVENT_TEXT: dict[EventCard, str] = {
    EventCard.AIRLIFT: "Move any pawn to any city.",
    EventCard.FORECAST: "Look at the top 6 infection cards and put them back in any order.",
    EventCard.GOVERNMENT_GRANT: "Build a research station in any city, no card needed.",
    EventCard.ONE_QUIET_NIGHT: "Skip the next Infect Cities step.",
    EventCard.RESILIENT_POPULATION: "Remove one card from the infection discard pile from the game.",
}
EVENTS: tuple[str, ...] = tuple(e.value for e in EventCard)
EPIDEMIC = "epidemic"

INFECTION_RATE = (2, 2, 2, 3, 3, 4, 4)  # indexed by the number of epidemics drawn
CUBES_PER_COLOR = 24
MAX_STATIONS = 6
MAX_OUTBREAKS = 8
HAND_LIMIT = 7
ACTIONS_PER_TURN = 4
FORECAST_CARDS = 6
STARTING_HAND = {2: 4, 3: 3, 4: 2}
DIFFICULTIES = {4: "Introductory", 5: "Standard", 6: "Heroic"}


def is_city(card: str) -> bool:
    return card in CITIES


def is_event(card: str) -> bool:
    return card in EVENTS


def card_color(card: str) -> Color | None:
    city = CITIES.get(card)
    return city.color if city else None


def catalogue() -> dict[str, Any]:
    """Static data for the web client."""
    return {
        "cities": [
            {"id": c.id, "name": c.name, "color": c.color.value, "adj": list(ADJ[c.id])} for c in CITIES.values()
        ],
        "roles": [{"key": r.value, "name": ROLE_NAMES[r]} for r in Role],
        "events": [{"key": e.value, "name": EVENT_NAMES[e], "text": EVENT_TEXT[e]} for e in EventCard],
        "infection_rate": list(INFECTION_RATE),
        "difficulties": [{"epidemics": n, "name": name} for n, name in DIFFICULTIES.items()],
        "limits": {
            "cubes": CUBES_PER_COLOR,
            "stations": MAX_STATIONS,
            "outbreaks": MAX_OUTBREAKS,
            "hand": HAND_LIMIT,
            "actions": ACTIONS_PER_TURN,
        },
        "starting_hand": STARTING_HAND,
    }


__all__ = [
    "ACTIONS_PER_TURN",
    "ADJ",
    "CITIES",
    "COLORS",
    "CUBES_PER_COLOR",
    "DIFFICULTIES",
    "DIST",
    "EDGES",
    "EPIDEMIC",
    "EVENTS",
    "EVENT_NAMES",
    "FORECAST_CARDS",
    "HAND_LIMIT",
    "INFECTION_RATE",
    "MAX_OUTBREAKS",
    "MAX_STATIONS",
    "ROLE_NAMES",
    "STARTING_HAND",
    "START_CITY",
    "City",
    "Color",
    "EventCard",
    "Role",
    "card_color",
    "catalogue",
    "is_city",
    "is_event",
    "path",
]
