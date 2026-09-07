"""Windows audio endpoints: enumeration and default-device switching.

Classification of the glasses' endpoints is pure logic (testable). Windows names its
Bluetooth endpoints like "Kopfhörer (Ray-Ban Meta Stereo)" (A2DP) and
"Headset (Ray-Ban Meta Hands-Free AG Audio)" (HFP, render + capture).
"""

from __future__ import annotations

import logging
import threading
from dataclasses import dataclass
from typing import Literal, Protocol

log = logging.getLogger(__name__)

Flow = Literal["render", "capture"]
Role = Literal["a2dp", "hfp", "other"]

HFP_MARKERS = ("hands-free", "handsfree", "freisprech", "headset")


@dataclass(slots=True)
class AudioDevice:
    id: str
    name: str
    flow: Flow
    state: str = "active"
    is_default: bool = False
    role: Role = "other"

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "name": self.name,
            "flow": self.flow,
            "state": self.state,
            "is_default": self.is_default,
            "role": self.role,
        }


@dataclass(slots=True)
class GlassesEndpoints:
    render_a2dp: AudioDevice | None = None
    render_hfp: AudioDevice | None = None
    capture_hfp: AudioDevice | None = None


def classify_endpoint(name: str, glasses_name: str) -> Role:
    if not glasses_name or glasses_name.lower() not in name.lower():
        return "other"
    lowered = name.lower()
    if any(marker in lowered for marker in HFP_MARKERS):
        return "hfp"
    return "a2dp"


def pick_glasses_endpoints(devices: list[AudioDevice], glasses_name: str) -> GlassesEndpoints:
    out = GlassesEndpoints()
    for dev in devices:
        role = classify_endpoint(dev.name, glasses_name)
        if role == "other" or dev.state not in ("active", "unplugged"):
            continue
        if dev.flow == "render" and role == "a2dp" and out.render_a2dp is None:
            out.render_a2dp = dev
        elif dev.flow == "render" and role == "hfp" and out.render_hfp is None:
            out.render_hfp = dev
        elif dev.flow == "capture" and role == "hfp" and out.capture_hfp is None:
            out.capture_hfp = dev
    return out


class AudioDeviceBackend(Protocol):
    def list_devices(self) -> list[AudioDevice]: ...
    def get_default(self, flow: Flow) -> AudioDevice | None: ...
    def set_default(self, device_id: str) -> None: ...


# --- Windows implementation ----------------------------------------------------------

STATE_NAMES = {1: "active", 2: "disabled", 4: "not_present", 8: "unplugged"}


class PycawBackend:
    """Uses the MMDevice API (through pycaw's COM definitions) plus the undocumented
    IPolicyConfig interface to change the default endpoint for all three roles."""

    def __init__(self) -> None:
        self._lock = threading.Lock()

    def _enumerator(self):
        import comtypes
        from pycaw.api.mmdeviceapi import IMMDeviceEnumerator
        from pycaw.constants import CLSID_MMDeviceEnumerator

        comtypes.CoInitialize()
        return comtypes.CoCreateInstance(CLSID_MMDeviceEnumerator, IMMDeviceEnumerator, comtypes.CLSCTX_INPROC_SERVER)

    @staticmethod
    def _friendly_name(device) -> str:
        """Read only PKEY_Device_FriendlyName instead of every property (pycaw's
        CreateDevice walks all of them and warns on the unreadable ones)."""
        from comtypes import GUID
        from pycaw.api.mmdeviceapi import PROPERTYKEY
        from pycaw.constants import STGM

        try:
            pk = PROPERTYKEY()
            pk.fmtid = GUID("{a45c254e-df1c-4efd-8020-67d146a850e0}")
            pk.pid = 14
            store = device.OpenPropertyStore(STGM.STGM_READ.value)
            value = store.GetValue(pk)
            name = value.GetValue()
            value.clear()
            return str(name) if name else "?"
        except Exception:  # noqa: BLE001
            return "?"

    def list_devices(self) -> list[AudioDevice]:
        from pycaw.constants import EDataFlow, ERole

        with self._lock:
            enum = self._enumerator()
            out: list[AudioDevice] = []
            for flow_name, flow in (("render", EDataFlow.eRender.value), ("capture", EDataFlow.eCapture.value)):
                default_id = None
                try:
                    default_id = enum.GetDefaultAudioEndpoint(flow, ERole.eMultimedia.value).GetId()
                except Exception:  # noqa: BLE001
                    pass
                collection = enum.EnumAudioEndpoints(flow, 0xF)  # DEVICE_STATEMASK_ALL
                for i in range(collection.GetCount()):
                    dev = collection.Item(i)
                    dev_id = dev.GetId()
                    state = STATE_NAMES.get(dev.GetState(), "unknown")
                    out.append(
                        AudioDevice(
                            id=dev_id,
                            name=self._friendly_name(dev),
                            flow=flow_name,  # type: ignore[arg-type]
                            state=state,
                            is_default=(dev_id == default_id),
                        )
                    )
            return out

    def get_default(self, flow: Flow) -> AudioDevice | None:
        from pycaw.constants import EDataFlow, ERole

        with self._lock:
            enum = self._enumerator()
            try:
                dev = enum.GetDefaultAudioEndpoint(
                    EDataFlow.eRender.value if flow == "render" else EDataFlow.eCapture.value,
                    ERole.eMultimedia.value,
                )
            except Exception:  # noqa: BLE001
                return None
            return AudioDevice(id=dev.GetId(), name=self._friendly_name(dev), flow=flow, is_default=True)

    def set_default(self, device_id: str) -> None:
        """Set the endpoint as default for console, multimedia and communications.

        Uses the undocumented IPolicyConfig interface (as shipped in pycaw); this is what
        the Sound control panel itself uses.
        """
        import comtypes
        from pycaw.api.policyconfig import IPolicyConfig
        from pycaw.constants import CLSID_CPolicyConfigClient

        with self._lock:
            comtypes.CoInitialize()
            policy = comtypes.CoCreateInstance(CLSID_CPolicyConfigClient, IPolicyConfig, comtypes.CLSCTX_ALL)
            for role in (0, 1, 2):  # eConsole, eMultimedia, eCommunications
                policy.SetDefaultEndpoint(device_id, role)
            log.info("default audio endpoint set to %s", device_id)


if __name__ == "__main__":
    import json

    backend = PycawBackend()
    for d in backend.list_devices():
        print(json.dumps(d.to_dict(), ensure_ascii=False))
    print("default render:", backend.get_default("render"))
    print("default capture:", backend.get_default("capture"))
