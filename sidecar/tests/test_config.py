from pathlib import Path

from sidekick.config import Settings, load_settings, merge_settings, save_settings


def test_defaults_match_spec():
    s = Settings()
    assert s.server.port == 47821
    assert s.presence.idle_threshold_min == 5
    assert s.audio.glasses_device_name == "Ray-Ban Meta"
    assert s.stt.silence_timeout_s == 1.5
    assert s.stt.model == "small"
    assert s.gestures.single_tap == "toggle_listen"
    assert s.gestures.double_tap == "repeat_last"
    assert s.gestures.hold == "btw"
    assert s.claude.cleanup_model == "claude-haiku-4-5"
    assert s.claude.btw_model == "claude-sonnet-5"


def test_load_missing_file_gives_defaults(tmp_path: Path):
    assert load_settings(tmp_path / "nope.toml") == Settings()


def test_roundtrip_preserves_unknown_keys(tmp_path: Path):
    p = tmp_path / "config.toml"
    p.write_text('[stt]\nmodel = "medium"\n[custom]\nfoo = 1\n', encoding="utf-8")
    s = load_settings(p)
    assert s.stt.model == "medium"
    s.stt.model = "small"
    save_settings(p, s)
    text = p.read_text(encoding="utf-8")
    assert 'model = "small"' in text
    assert "[custom]" in text and "foo = 1" in text
    assert load_settings(p).stt.model == "small"


def test_merge_partial():
    s = Settings()
    merged = merge_settings(s, {"tts": {"engine": "edge"}, "gestures": {"hold": "none"}})
    assert merged.tts.engine == "edge"
    assert merged.gestures.hold == "none"
    assert merged.stt.model == "small"
    # original untouched
    assert s.tts.engine == "elevenlabs"


def test_merge_rejects_invalid_action():
    import pytest

    with pytest.raises(Exception):
        merge_settings(Settings(), {"gestures": {"single_tap": "launch_rockets"}})
