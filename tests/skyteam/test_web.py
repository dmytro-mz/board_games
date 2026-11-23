import json
from pathlib import Path

from boardgames.testing import GameClient

TOKEN_A, TOKEN_B = "a" * 20, "b" * 20


def test_two_players_redaction_and_progress(tmp_path):
    with GameClient("skyteam", progress=tmp_path / "progress.json") as c:
        cfg = c.get("/api/config").json()
        assert len(cfg["scenarios"]) == 21 and cfg["progress"] == {}
        code = c.post("/api/rooms").json()["room"]
        with c.websocket_connect(f"/ws/{code}") as a, c.websocket_connect(f"/ws/{code}") as b:
            a.send_json({"token": TOKEN_A, "name": "Ann"})
            assert a.receive_json()["status"] == "lobby"
            b.send_json({"token": TOKEN_B, "name": "Bob"})
            b.receive_json()
            a.receive_json()  # Ann hears that Bob joined

            def say(sock, msg):
                sock.send_json(msg)
                return a.receive_json(), b.receive_json()

            say(a, {"type": "scenario", "id": "hnd"})
            say(a, {"type": "claim", "seat": "pilot"})
            say(b, {"type": "claim", "seat": "copilot"})
            sa, _ = say(a, {"type": "start"})
            assert sa["scenario"] == "hnd" and sa["status"] == "playing"
            say(a, {"type": "act", "seat": "pilot", "action": {"t": "ready"}})
            sa, sb = say(b, {"type": "act", "seat": "copilot", "action": {"t": "ready"}})
            assert sa["game"]["phase"] == "place"
            assert all("value" in d for d in sa["game"]["dice"]["pilot"])
            assert all("value" not in d for d in sa["game"]["dice"]["copilot"])
            assert all("value" in d for d in sb["game"]["dice"]["copilot"])
        room = c.app.state.manager.rooms[code]
        room.game.result = {"won": True, "reason": "test"}
        room.game.phase = "over"
        room.after_game_change()
    data = json.loads((tmp_path / "progress.json").read_text())
    assert data["scenarios"]["hnd"]["wins"] == 1


def test_progress_file_is_gitignored():
    assert "progress.json" in (Path(__file__).parents[2] / ".gitignore").read_text()
