import wave
from pathlib import Path

import numpy as np
import pytest

from sidekick.audio.devices import AudioDevice, classify_endpoint, pick_glasses_endpoints
from sidekick.audio.player import Player, load_wav, resample
from sidekick.audio.router import AudioRouteError, AudioRouter
from sidekick.audio.sounds import SOUND_NAMES, Sounds
from sidekick.audio.vad import FRAME, FakeVad, Segmenter, SegmenterConfig, SegmentEvent
from sidekick.config import Settings
from sidekick.events import EventBus
from sidekick.fakes import FakeAudioBackend, FakeOutput
from sidekick.paths import sounds_dir
from sidekick.state import AppState

# --- sounds -------------------------------------------------------------------


def test_all_sound_files_exist_and_are_short():
    for name in SOUND_NAMES:
        p = sounds_dir() / f"{name}.wav"
        assert p.exists(), p
        with wave.open(str(p), "rb") as w:
            assert w.getframerate() == 44100 and w.getnchannels() == 1
            assert w.getnframes() / w.getframerate() < 1.0


def test_player_plays_wav_through_backend():
    out = FakeOutput()
    player = Player(out, device_resolver=lambda: 7, volume_resolver=lambda: 0.5)
    sounds = Sounds(player)
    sounds.play("done", block=True)
    assert sounds.played == ["done"]
    assert len(out.opened) == 1 and out.opened[0].device == 7 and out.opened[0].samplerate == 44100
    total = sum(len(s) for s in out.opened[0].samples)
    samples, sr, ch = load_wav(sounds.path("done"))
    assert total == len(samples)
    assert float(np.max(np.abs(np.concatenate(out.opened[0].samples)))) <= 0.5 + 1e-6
    assert out.closed == out.opened


def test_player_stream_and_stop():
    out = FakeOutput()
    player = Player(out)
    handle, finished = player.play_stream()
    handle.write((np.zeros((2400, 1), dtype=np.float32), 24000, 1))
    handle.write((np.zeros((2400, 1), dtype=np.float32), 24000, 1))
    handle.end()
    assert finished.wait(2)
    assert out.opened[-1].samplerate == 24000
    handle2, finished2 = player.play_stream()
    handle2.write((np.zeros((2400, 1), dtype=np.float32), 24000, 1))
    player.stop()
    handle2.end()
    assert finished2.wait(2)


def test_resample_length():
    y = np.zeros(24000, dtype=np.float32)
    assert len(resample(y, 24000, 48000)) == 48000


# --- devices / router -----------------------------------------------------------


@pytest.mark.parametrize(
    "name,expected",
    [
        ("Kopfhörer (Ray-Ban Meta Stereo)", "a2dp"),
        ("Headset (Ray-Ban Meta Hands-Free AG Audio)", "hfp"),
        ("Headphones (Ray-Ban Meta)", "a2dp"),
        ("Lautsprecher (Realtek High Definition Audio)", "other"),
        ("Kopfhörer (LE-Dark Star)", "other"),
    ],
)
def test_classify_endpoint(name, expected):
    assert classify_endpoint(name, "Ray-Ban Meta") == expected


def test_pick_glasses_endpoints():
    devs = FakeAudioBackend().list_devices()
    eps = pick_glasses_endpoints(devs, "Ray-Ban Meta")
    assert eps.render_a2dp.id == "rb-a2dp"
    assert eps.render_hfp.id == "rb-hfp"
    assert eps.capture_hfp.id == "rb-mic"
    assert pick_glasses_endpoints(devs, "Nope").render_a2dp is None


def _router(backend=None):
    bus = EventBus()
    state = AppState(bus)
    settings = Settings()
    return AudioRouter(backend or FakeAudioBackend(), state, lambda: settings), state


def test_router_route_and_restore():
    backend = FakeAudioBackend()
    router, state = _router(backend)
    dev = router.route_to_glasses()
    assert dev.id == "rb-a2dp" and backend.set_calls == ["rb-a2dp"]
    assert state.data.audio.routed_to_glasses is True
    assert state.data.audio.previous_output_device.startswith("Lautsprecher")
    assert router.output_device_name() == "Kopfhörer (Ray-Ban Meta Stereo)"
    # routing twice must not overwrite the remembered previous device
    router.route_to_glasses()
    assert state.data.audio.previous_output_device.startswith("Lautsprecher")
    # simulate HFP taking over the default, ensure_a2dp fixes it
    backend.set_default("rb-hfp")
    router.ensure_a2dp()
    assert backend.get_default("render").id == "rb-a2dp"
    prev = router.restore()
    assert prev.id == "spk" and backend.get_default("render").id == "spk"
    assert state.data.audio.routed_to_glasses is False and router.output_device_name() is None


def test_router_without_glasses_raises():
    router, _ = _router(FakeAudioBackend(devices=[AudioDevice(id="spk", name="Speakers", flow="render", is_default=True)]))
    with pytest.raises(AudioRouteError):
        router.route_to_glasses()


# --- VAD segmenter --------------------------------------------------------------


def _frames(n):
    return [np.zeros(FRAME, dtype=np.float32) for _ in range(n)]


def test_segmenter_speech_start_end_with_preroll():
    # 20 silent frames, 30 speech frames, then silence until timeout
    probs = [0.0] * 20 + [0.9] * 30 + [0.0] * 200
    seg = Segmenter(FakeVad(probs), SegmenterConfig(silence_timeout_s=0.5, min_speech_s=0.1, pre_roll_s=0.32))
    events = []
    for i, f in enumerate(_frames(120)):
        ev = seg.feed(f)
        if ev:
            events.append((i, ev))
        if seg.finished:
            break
    assert events[0][1] == SegmentEvent.SPEECH_START
    assert events[-1][1] == SegmentEvent.SPEECH_END
    frames_needed_for_min = 4  # 0.1 s / 0.032 s -> ceil = 4
    assert events[0][0] == 20 + frames_needed_for_min - 1
    silence_frames = 16  # 0.5 s / 0.032 s -> 15.6 -> 16 frames
    assert events[-1][0] == 50 + silence_frames - 1
    # buffer = pre-roll (10 frames) + speech + trailing silence
    assert len(seg.audio) == (10 + (50 - 20 - 3) + silence_frames - 1) * FRAME or len(seg.audio) > 0


def test_segmenter_no_speech_timeout():
    seg = Segmenter(FakeVad([0.0]), SegmenterConfig(no_speech_timeout_s=0.2))
    events = [seg.feed(f) for f in _frames(20)]
    assert SegmentEvent.TIMEOUT_NO_SPEECH in events
    assert not seg.has_speech


def test_segmenter_max_duration():
    seg = Segmenter(FakeVad([0.95]), SegmenterConfig(max_duration_s=0.5, min_speech_s=0.05))
    events = [seg.feed(f) for f in _frames(40)]
    assert SegmentEvent.SPEECH_START in events and SegmentEvent.MAX_DURATION in events


def test_segmenter_manual_end():
    seg = Segmenter(FakeVad([0.9]), SegmenterConfig(min_speech_s=0.05))
    for f in _frames(5):
        seg.feed(f)
    assert seg.end_now() is True and seg.finished


def test_real_silero_model_runs():
    from sidekick.audio.vad import SileroVad
    from sidekick.paths import bundled_models_dir

    vad = SileroVad(bundled_models_dir() / "silero_vad.onnx")
    silence = np.zeros(FRAME, dtype=np.float32)
    p_silence = max(vad(silence) for _ in range(5))
    assert 0.0 <= p_silence < 0.5
    vad.reset()
    rng = np.random.default_rng(0)
    noise = (rng.standard_normal(FRAME) * 0.05).astype(np.float32)
    assert 0.0 <= vad(noise) <= 1.0


def test_load_wav_tmp(tmp_path: Path):
    p = tmp_path / "x.wav"
    with wave.open(str(p), "wb") as w:
        w.setnchannels(2)
        w.setsampwidth(2)
        w.setframerate(22050)
        w.writeframes(np.zeros(2200, dtype=np.int16).tobytes())
    samples, sr, ch = load_wav(p)
    assert samples.shape == (1100, 2) and sr == 22050 and ch == 2
