"""Smoke test of the fully wired app with fake hardware."""

from fastapi.testclient import TestClient

from sidekick.app import create_app
from sidekick.services import build_services


def test_full_app_smoke(tmp_path):
    services = build_services(tmp_path / "config.toml", tmp_path / "t.db", fake=True, hardware=False)
    with TestClient(create_app(services)) as c:
        assert c.get("/health").json()["ok"] is True
        state = c.get("/state").json()
        assert state["mode"] == "idle"
        devices = c.get("/audio/devices").json()
        assert any(d["role"] == "a2dp" for d in devices)
        r = c.post("/audio/route", json={"target": "glasses"})
        assert r.status_code == 200 and "Ray-Ban" in r.json()["output_device"]
        assert c.get("/state").json()["audio"]["routed_to_glasses"] is True
        assert c.post("/audio/route", json={"target": "restore"}).status_code == 200
        assert c.post("/audio/play", json={"sound": "done"}).status_code == 200
        assert c.post("/audio/play", json={"sound": "nope"}).status_code == 404
        g = c.get("/glasses").json()
        assert g["device_name"] == "Ray-Ban Meta"
        assert c.post("/glasses/connect").json()["ok"] is True
        assert c.post("/glasses/disconnect").json()["ok"] is True
        assert c.get("/session").json()["session"] is None
        assert c.get("/sessions").json() == []
        assert c.post("/sessions", json={"cwd": str(tmp_path / "nope")}).status_code == 422
        assert c.get("/sessions/zzz/messages").status_code == 404
        assert c.post("/sessions/zzz/activate").status_code == 404
        assert c.patch("/sessions/zzz", json={"title": "x"}).status_code == 404
        assert c.post("/sessions/zzz/send", json={"text": "hi"}).status_code == 409
        assert c.get("/state").json()["sessions"] == []
        assert c.get("/session/messages").json() == []
        assert c.post("/session/send", json={"text": "hi"}).status_code == 409
        assert c.get("/sessions/external").json() == []
        assert c.get("/transcripts").json() == []
        assert c.get("/btw").json() == []
        assert c.get("/gestures/log").json() == []
        assert (
            c.get("/hooks/snippet")
            .json()["hooks"]["Stop"][0]["hooks"][0]["url"]
            .startswith("http://127.0.0.1:")
        )
        assert (
            c.get("/hooks/status", params={"path": str(tmp_path), "scope": "project"}).json()["installed"]
            is False
        )
        assert (
            c.post("/hooks/install", json={"path": str(tmp_path), "scope": "local"}).json()["installed"]
            is True
        )
        assert (
            c.post("/hooks/uninstall", json={"path": str(tmp_path), "scope": "local"}).json()["installed"]
            is False
        )
        assert c.post("/hook/SessionStart", json={"session_id": "x", "cwd": str(tmp_path)}).status_code == 200
        assert c.post("/hook", content=b"not json").status_code == 200
        assert c.post("/tts/speak", json={"text": ""}).status_code == 422
        assert c.post("/tts/stop").status_code == 200
        assert c.post("/listen/stop").status_code == 200
        assert c.post("/transcript/zzz/cancel").status_code == 404
        assert c.get("/secrets").json() == {"elevenlabs": False, "deepgram": False}
        # settings hot-reload reaches the gesture mapping
        c.put("/settings", json={"gestures": {"single_tap": "none"}})
        assert services.settings.gestures.single_tap == "none"
