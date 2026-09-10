"""Model switching per session and usage-limit awareness."""

from __future__ import annotations

import time

from claude_agent_sdk import RateLimitEvent, RateLimitInfo, ResultMessage
from fastapi.testclient import TestClient

from sidekick.app import create_app
from sidekick.claude.embedded import is_limit_error
from sidekick.claude.summarize import model_label
from sidekick.services import build_services
from tests.test_sessions import FakeClient


def _limit_event(status: str = "rejected", resets_in: int = 3600, five_hour: float = 0.99) -> RateLimitEvent:
    resets = int(time.time()) + resets_in
    return RateLimitEvent(
        rate_limit_info=RateLimitInfo(
            status=status,
            resets_at=resets,
            rate_limit_type="five_hour",
            raw={
                "status": status,
                "resetsAt": resets,
                "unifiedWindows": {
                    "five_hour": {"utilization": five_hour, "resetsAt": resets},
                    "seven_day": {"utilization": 0.4, "resetsAt": resets + 86_400},
                },
            },
        ),
        uuid="u",
        session_id="s",
    )


def test_model_label():
    assert model_label("claude-sonnet-5") == "Sonnet 5"
    assert model_label("") == "das Standardmodell"
    assert model_label("claude-something-new") == "Something new"


def test_is_limit_error():
    assert is_limit_error("You've hit your usage limit · resets 6:20pm")
    assert is_limit_error("Nutzungslimit erreicht")
    assert not is_limit_error("Tool use failed")


def _services(tmp_path):
    services = build_services(tmp_path / "config.toml", tmp_path / "t.db", fake=True, hardware=False)
    services.sessions._client_factory = FakeClient
    spoken: list = []
    services.speaker.speak = lambda text, kind="summary": spoken.append((text, kind))
    return services, spoken


def test_switch_model_of_a_running_and_a_stopped_session(tmp_path):
    services, spoken = _services(tmp_path)
    with TestClient(create_app(services)) as c:
        s = c.post("/sessions", json={"cwd": str(tmp_path)}).json()
        assert s["model"] == ""
        client = FakeClient.instances[-1]
        r = c.post(f"/sessions/{s['id']}/model", json={"model": "claude-sonnet-5"})
        assert r.status_code == 200 and r.json()["model"] == "claude-sonnet-5"
        assert client.models == ["claude-sonnet-5"]  # switched live, no restart
        assert c.get("/state").json()["session"]["model"] == "claude-sonnet-5"
        # empty string = back to whatever Claude Code defaults to
        assert c.post(f"/sessions/{s['id']}/model", json={"model": ""}).json()["model"] == ""
        assert client.models == ["claude-sonnet-5", None]
        # a stopped session keeps the model for its next resume
        c.post(f"/sessions/{s['id']}/stop")
        assert (
            c.post(f"/sessions/{s['id']}/model", json={"model": "claude-opus-5"}).json()["model"]
            == "claude-opus-5"
        )
        assert next(x for x in c.get("/sessions").json() if x["id"] == s["id"])["model"] == "claude-opus-5"
        assert c.post("/sessions/zzz/model", json={"model": "x"}).status_code == 404


def test_usage_limit_is_announced_and_switches_to_the_fallback(tmp_path):
    services, spoken = _services(tmp_path)
    with TestClient(create_app(services)) as c:
        a = c.post("/sessions", json={"cwd": str(tmp_path)}).json()
        client_a = FakeClient.instances[-1]
        b = c.post("/sessions", json={"cwd": str(tmp_path)}).json()
        client_b = FakeClient.instances[-1]
        # a warning is spoken with the share, and does not switch anything
        client_a.queue.put_nowait(_limit_event("allowed_warning", five_hour=0.9))
        for _ in range(200):
            if spoken:
                break
            time.sleep(0.01)
        assert "knapp" in spoken[-1][0] and "90 Prozent" in spoken[-1][0] and spoken[-1][1] == "limit"
        assert client_a.models == [] and client_b.models == []
        rl = c.get("/state").json()["rate_limit"]
        assert rl["status"] == "allowed_warning" and rl["windows"]["five_hour"]["utilization"] == 0.9
        # the hard limit switches every running session to the fallback and says so
        client_a.queue.put_nowait(_limit_event("rejected"))
        for _ in range(200):
            if len(spoken) > 1:
                break
            time.sleep(0.01)
        assert "Nutzungslimit erreicht" in spoken[-1][0] and "Sonnet 5" in spoken[-1][0]
        assert "Uhr" in spoken[-1][0]  # reset time
        for _ in range(100):
            if client_a.models and client_b.models:
                break
            time.sleep(0.01)
        assert client_a.models == ["claude-sonnet-5"] and client_b.models == ["claude-sonnet-5"]
        assert c.get("/state").json()["rate_limit"]["status"] == "rejected"
        # the same status again stays quiet
        n = len(spoken)
        client_a.queue.put_nowait(_limit_event("rejected"))
        time.sleep(0.3)
        assert len(spoken) == n
        assert [x["model"] for x in c.get("/sessions").json() if x["id"] in (a["id"], b["id"])] == [
            "claude-sonnet-5",
            "claude-sonnet-5",
        ]


def test_limit_error_result_triggers_the_same_path(tmp_path):
    services, spoken = _services(tmp_path)
    services.settings.claude.limit_fallback_model = ""  # announcement only
    with TestClient(create_app(services)) as c:
        c.post("/sessions", json={"cwd": str(tmp_path)})
        client = FakeClient.instances[-1]
        client.queue.put_nowait(
            ResultMessage(
                subtype="error_during_execution",
                duration_ms=1,
                duration_api_ms=1,
                is_error=True,
                num_turns=1,
                session_id="sdk-x",
                result="You've hit your usage limit · resets 6:20pm",
            )
        )
        for _ in range(200):
            if spoken:
                break
            time.sleep(0.01)
        assert "Nutzungslimit erreicht" in spoken[-1][0] and "umgeschaltet" not in spoken[-1][0]
        assert client.models == []
