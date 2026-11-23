"""JSON protocol for actions: what a browser sends <-> the engine's action tuples."""

from __future__ import annotations

from typing import Any

from avenue.game.cards import AGENT_INDEX, AGENT_LIST
from avenue.game.engine import Action


class BadAction(Exception):
    pass


def _agent(value: object) -> int:
    if not isinstance(value, str) or value not in AGENT_INDEX:
        raise BadAction(f"unknown agent {value!r}")
    return AGENT_INDEX[value]


def from_json(data: object) -> Action:
    if not isinstance(data, dict):
        raise BadAction("action must be an object")
    kind = data.get("type")
    if kind == "discard":
        return ("discard", _agent(data.get("card")))
    if kind == "play":
        up, down = data.get("up"), data.get("down")
        if up is None and down is None:
            raise BadAction("play needs a card")
        return ("play", -1 if up is None else _agent(up), -1 if down is None else _agent(down))
    if kind == "recruit":
        take = data.get("take")
        if take not in ("up", "down"):
            raise BadAction("take must be 'up' or 'down'")
        return ("recruit", 0 if take == "up" else 1)
    if kind == "market":
        index = data.get("index")
        if not isinstance(index, int) or isinstance(index, bool):
            raise BadAction("index must be a number")
        return ("market", index)
    if kind == "choose":
        option = data.get("option")
        if isinstance(option, bool):
            return ("choose", int(option))
        return ("choose", _agent(option))
    raise BadAction(f"unknown action {kind!r}")


def to_json(action: Action) -> dict[str, Any]:
    kind = action[0]
    if kind == "discard":
        return {"type": "discard", "card": AGENT_LIST[action[1]].key}
    if kind == "play":
        up, down = action[1], action[2]
        return {
            "type": "play",
            "up": AGENT_LIST[up].key if up >= 0 else None,
            "down": AGENT_LIST[down].key if down >= 0 else None,
        }
    if kind == "recruit":
        return {"type": "recruit", "take": "up" if action[1] == 0 else "down"}
    if kind == "market":
        return {"type": "market", "index": action[1]}
    if kind == "choose":
        return {"type": "choose", "option": action[1]}
    raise BadAction(f"unknown action {kind!r}")


def choice_json(stage: str, option: int) -> Any:
    """How a choice option is shown to the client: an agent key, or a yes/no flag for Spycation."""
    if stage == "spy_recruit":
        return bool(option)
    return AGENT_LIST[option].key
