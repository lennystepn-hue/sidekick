"""Settings model and TOML persistence.

`config.toml` in the app-data folder is the single source of truth. Unknown keys in the
file are preserved on save so hand edits and future versions do not fight each other.
"""

from __future__ import annotations

import tomllib
from copy import deepcopy
from pathlib import Path
from typing import Any, Literal

import tomli_w
from pydantic import BaseModel, Field

GestureAction = Literal["toggle_listen", "repeat_last", "btw", "stop_speaking", "none"]


class ServerSettings(BaseModel):
    host: str = "127.0.0.1"
    port: int = 47821


class PresenceSettings(BaseModel):
    idle_threshold_min: float = 5
    auto_connect: bool = True
    poll_interval_s: float = 2.0


class AudioSettings(BaseModel):
    glasses_device_name: str = "Ray-Ban Meta"
    restore_previous_device: bool = True
    tone_volume: float = 0.6


class SttSettings(BaseModel):
    engine: Literal["parakeet", "faster-whisper", "deepgram"] = "parakeet"
    model: str = "small"
    compute_type: str = "int8"
    # Parakeet TDT 0.6B v3 (onnx-asr): 25 European languages, ~0.08x real time on CPU.
    parakeet_model: str = "nemo-parakeet-tdt-0.6b-v3"
    parakeet_quantization: str = "int8"
    silence_timeout_s: float = 1.5
    no_speech_timeout_s: float = 8.0
    max_duration_s: float = 60.0
    languages: list[str] = Field(default_factory=lambda: ["de", "en"])
    hotwords: list[str] = Field(default_factory=lambda: ["Claude", "FastAPI", "Tauri", "Sidekick"])
    review_delay_s: float = 2.0
    cleanup_enabled: bool = True


class TtsSettings(BaseModel):
    engine: Literal["elevenlabs", "edge"] = "elevenlabs"
    voice_id: str = ""
    elevenlabs_model: str = "eleven_flash_v2_5"
    edge_voice: str = "de-DE-ConradNeural"
    language: str = "de"
    summarize_before_speaking: bool = True
    # After you sent something yourself, "done" announcements are tone-only for this long (0 = off).
    quiet_after_input_s: float = 0.0


class GestureSettings(BaseModel):
    single_tap: GestureAction = "toggle_listen"
    double_tap: GestureAction = "repeat_last"
    triple_tap: GestureAction = "btw"
    hold: GestureAction = "btw"
    capture_media_keys: bool = True
    capture_always: bool = False


class DeliverySettings(BaseModel):
    send_input: bool = False
    clipboard: bool = True


class BtwSettings(BaseModel):
    context_messages: int = 12
    file_list_limit: int = 300


class ClaudeSettings(BaseModel):
    default_mode: Literal["embedded", "external"] = "embedded"
    cleanup_model: str = "claude-haiku-4-5"
    summary_model: str = "claude-haiku-4-5"
    btw_model: str = "claude-sonnet-5"
    session_model: str = ""
    # Claude Code permission mode for the embedded session. "auto" lets Claude Code decide
    # and only asks for risky actions; "default" asks for everything; "bypassPermissions" never asks.
    permission_mode: Literal["auto", "acceptEdits", "default", "bypassPermissions"] = "auto"
    cli_path: str = ""
    last_cwd: str = ""
    # "Später": a deferred permission stays silent for this long, then asks again.
    defer_minutes: int = 10
    # When the usage limit rejects a turn, switch running sessions to this model ("" = off).
    limit_fallback_model: str = "claude-sonnet-5"
    # Offered in the model picker; the first entry means "as configured in Claude Code".
    models: list[str] = Field(
        default_factory=lambda: ["claude-opus-5", "claude-sonnet-5", "claude-haiku-4-5"]
    )


class BrainstormSettings(BaseModel):
    # Partner model for the conversation and the model that writes the project documents.
    model: str = "claude-opus-5"
    docs_model: str = "claude-opus-5"
    # Replies are spoken verbatim (the prompt keeps them short); no Haiku summary in between.
    speak_replies: bool = True
    # After a spoken reply, open the microphone again (round trip without a tap).
    auto_listen: bool = False
    # Adaptive thinking makes replies slower but more considered; off keeps the voice loop snappy.
    thinking: bool = False


class ProjectsSettings(BaseModel):
    # Folder that receives materialized brainstorms; created on first use.
    base_dir: str = "~/Projects"
    git_init: bool = True
    start_session_after_create: bool = True


class Settings(BaseModel):
    server: ServerSettings = Field(default_factory=ServerSettings)
    presence: PresenceSettings = Field(default_factory=PresenceSettings)
    audio: AudioSettings = Field(default_factory=AudioSettings)
    stt: SttSettings = Field(default_factory=SttSettings)
    tts: TtsSettings = Field(default_factory=TtsSettings)
    gestures: GestureSettings = Field(default_factory=GestureSettings)
    delivery: DeliverySettings = Field(default_factory=DeliverySettings)
    btw: BtwSettings = Field(default_factory=BtwSettings)
    claude: ClaudeSettings = Field(default_factory=ClaudeSettings)
    brainstorm: BrainstormSettings = Field(default_factory=BrainstormSettings)
    projects: ProjectsSettings = Field(default_factory=ProjectsSettings)


def _deep_merge(base: dict[str, Any], patch: dict[str, Any]) -> dict[str, Any]:
    out = deepcopy(base)
    for key, value in patch.items():
        if isinstance(value, dict) and isinstance(out.get(key), dict):
            out[key] = _deep_merge(out[key], value)
        else:
            out[key] = deepcopy(value)
    return out


def _read_toml(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    with path.open("rb") as fh:
        return tomllib.load(fh)


def load_settings(path: Path) -> Settings:
    """Load settings from TOML; missing file or keys fall back to defaults."""
    data = _read_toml(path)
    return Settings.model_validate(_deep_merge(Settings().model_dump(), data))


def save_settings(path: Path, settings: Settings) -> None:
    """Write settings to TOML, keeping unknown top-level tables and keys."""
    existing = _read_toml(path)
    merged = _deep_merge(existing, settings.model_dump(mode="json"))
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".toml.tmp")
    with tmp.open("wb") as fh:
        tomli_w.dump(merged, fh)
    tmp.replace(path)


def merge_settings(settings: Settings, patch: dict[str, Any]) -> Settings:
    """Apply a partial patch (nested dict) and re-validate."""
    return Settings.model_validate(_deep_merge(settings.model_dump(), patch))
