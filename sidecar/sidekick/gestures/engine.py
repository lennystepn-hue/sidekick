"""Pure mapping: virtual key -> media event -> gesture -> action."""

from __future__ import annotations

from ..config import GestureSettings

VK_MEDIA_NEXT_TRACK = 0xB0
VK_MEDIA_PREV_TRACK = 0xB1
VK_MEDIA_STOP = 0xB2
VK_MEDIA_PLAY_PAUSE = 0xB3

MEDIA_KEYS: dict[int, str] = {
    VK_MEDIA_PLAY_PAUSE: "play_pause",
    VK_MEDIA_NEXT_TRACK: "next",
    VK_MEDIA_PREV_TRACK: "prev",
    VK_MEDIA_STOP: "stop",
}

# What the Ray-Ban Meta touchpad sends: tap = play/pause, double tap = next,
# triple tap = previous, tap-and-hold = (if Windows gets anything at all) stop.
GESTURE_FOR_KEY: dict[str, str] = {
    "play_pause": "single_tap",
    "next": "double_tap",
    "prev": "triple_tap",
    "stop": "hold",
}

ACTIONS = ("toggle_listen", "repeat_last", "btw", "stop_speaking", "none")


def resolve_action(key: str, gestures: GestureSettings) -> tuple[str, str]:
    """Return (gesture, action) for a media key name; unknown keys map to ("unknown", "none")."""
    gesture = GESTURE_FOR_KEY.get(key)
    if gesture is None:
        return "unknown", "none"
    action = getattr(gestures, gesture, "none")
    return gesture, action if action in ACTIONS else "none"


def should_swallow(gestures: GestureSettings, glasses_connected: bool) -> bool:
    """Swallow media keys (keep them away from Spotify & Co.) while the app owns them."""
    if not gestures.capture_media_keys:
        return False
    return glasses_connected or gestures.capture_always
