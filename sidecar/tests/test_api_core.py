from fastapi.testclient import TestClient

from sidekick.app import create_app


def test_health_and_state(core_services):
    with TestClient(create_app(core_services)) as c:
        r = c.get("/health")
        assert r.status_code == 200 and r.json()["ok"] is True
        s = c.get("/state").json()
        assert s["mode"] == "idle" and s["glasses"] == "unknown"


def test_settings_put_persists(core_services):
    with TestClient(create_app(core_services)) as c:
        assert c.get("/settings").json()["stt"]["model"] == "small"
        r = c.put("/settings", json={"stt": {"model": "medium"}})
        assert r.status_code == 200 and r.json()["stt"]["model"] == "medium"
        assert core_services.settings.stt.model == "medium"
        assert 'model = "medium"' in core_services.settings_path.read_text(encoding="utf-8")
        bad = c.put("/settings", json={"gestures": {"hold": "nope"}})
        assert bad.status_code == 422


def test_secrets(core_services):
    with TestClient(create_app(core_services)) as c:
        assert c.get("/secrets").json() == {"elevenlabs": False, "deepgram": False}
        assert c.put("/secrets/elevenlabs", json={"value": "abc"}).status_code == 200
        assert c.get("/secrets").json()["elevenlabs"] is True
        assert c.put("/secrets/unknown", json={"value": "x"}).status_code == 404
        assert c.delete("/secrets/elevenlabs").status_code == 200
        assert c.get("/secrets").json()["elevenlabs"] is False


def test_websocket_sends_state_then_events(core_services):
    with TestClient(create_app(core_services)) as c:
        with c.websocket_connect("/ws") as ws:
            first = ws.receive_json()
            assert first["type"] == "state" and first["data"]["mode"] == "idle"
            core_services.state.update(mode="listening")
            ev = ws.receive_json()
            assert ev["type"] == "state" and ev["data"]["mode"] == "listening"
            ws.send_json({"type": "ping"})
            assert ws.receive_json()["type"] == "pong"
