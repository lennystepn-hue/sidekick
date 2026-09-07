"""Bluetooth adapter health (PnP problem codes) and an elevated adapter restart."""

from __future__ import annotations

import asyncio
import json
import logging
import re
import subprocess
import sys
from dataclasses import asdict, dataclass
from typing import Any

from .state import AppState

log = logging.getLogger(__name__)

HEALTH_SCRIPT = (
    "Get-PnpDevice -Class Bluetooth -PresentOnly -ErrorAction SilentlyContinue | "
    "Where-Object { $_.InstanceId -like 'USB\\*' -or $_.InstanceId -like 'PCI\\*' } | "
    "Select-Object FriendlyName, Status, Problem, ProblemDescription, InstanceId | ConvertTo-Json -Compress"
)


@dataclass(slots=True)
class AdapterHealth:
    ok: bool
    adapter_name: str | None = None
    problem_code: int | None = None
    problem_description: str | None = None
    instance_id: str | None = None
    status: str | None = None
    message: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def parse_health(json_text: str) -> AdapterHealth:
    text = (json_text or "").strip()
    if not text:
        return AdapterHealth(ok=False, message="Kein Bluetooth-Adapter gefunden")
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        return AdapterHealth(ok=False, message="Adapterstatus nicht lesbar")
    devices = data if isinstance(data, list) else [data]
    devices = [d for d in devices if isinstance(d, dict)]
    if not devices:
        return AdapterHealth(ok=False, message="Kein Bluetooth-Adapter gefunden")
    devices.sort(key=lambda d: 0 if str(d.get("Status", "")).upper() != "OK" else 1)
    dev = devices[0]
    status = str(dev.get("Status") or "")
    name = dev.get("FriendlyName")
    desc = dev.get("ProblemDescription") or ""
    code: int | None = None
    match = re.search(r"Code (\d+)", str(desc))
    if match:
        code = int(match.group(1))
    problem = dev.get("Problem")
    if isinstance(problem, int) and problem != 0:
        code = code or problem
    ok = status.upper() == "OK"
    return AdapterHealth(
        ok=ok,
        adapter_name=name,
        problem_code=None if ok else code,
        problem_description=None if ok else (str(desc).strip() or str(problem or "")),
        instance_id=dev.get("InstanceId"),
        status=status,
        message="Adapter OK" if ok else f"{name}: {desc or problem or status}",
    )


def _run_ps(script: str, timeout: float = 30) -> str:
    if sys.platform != "win32":
        return ""
    out = subprocess.run(
        ["powershell", "-NoProfile", "-NonInteractive", "-Command", script],
        capture_output=True, text=True, timeout=timeout, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    return out.stdout


async def adapter_health() -> AdapterHealth:
    try:
        text = await asyncio.to_thread(_run_ps, HEALTH_SCRIPT)
    except Exception as exc:  # noqa: BLE001
        return AdapterHealth(ok=False, message=f"Statusabfrage fehlgeschlagen: {exc}")
    return parse_health(text)


async def reset_adapter(instance_id: str) -> tuple[bool, str]:
    """Restart the adapter with pnputil (UAC prompt). Returns (ok, message)."""
    if not instance_id:
        return False, "Keine Instanz-ID"
    safe_id = instance_id.replace("'", "")
    script = (
        f"$p = Start-Process pnputil -ArgumentList @('/restart-device', '\"{safe_id}\"') -Verb RunAs -Wait -PassThru "
        "-WindowStyle Hidden; $p.ExitCode"
    )
    try:
        out = (await asyncio.to_thread(_run_ps, script, 120)).strip()
    except Exception as exc:  # noqa: BLE001
        return False, f"Neustart fehlgeschlagen: {exc}"
    await asyncio.sleep(3)
    health = await adapter_health()
    if health.ok:
        return True, "Adapter neu gestartet und wieder in Ordnung"
    if out and out != "0":
        return False, f"pnputil Exit-Code {out}. Wenn das nicht hilft: Rechner vollständig herunterfahren, 30 Sekunden warten, einschalten."
    return False, f"Adapter meldet weiterhin: {health.message}. Rechner vollständig herunterfahren, 30 Sekunden warten, einschalten."


class BluetoothDoctor:
    def __init__(self, state: AppState, interval_s: float = 120) -> None:
        self._state = state
        self._interval = interval_s
        self._task: asyncio.Task | None = None
        self.last: AdapterHealth | None = None

    def start(self) -> None:
        if self._task is None:
            self._task = asyncio.create_task(self._run(), name="bluetooth-doctor")

    async def stop(self) -> None:
        if self._task:
            self._task.cancel()
            self._task = None

    async def check(self) -> AdapterHealth:
        health = await adapter_health()
        self.last = health
        self._state.set_adapter(
            ok=health.ok, problem_code=health.problem_code, name=health.adapter_name, instance_id=health.instance_id
        )
        return health

    async def _run(self) -> None:
        while True:
            try:
                await self.check()
            except Exception:  # noqa: BLE001
                log.exception("bluetooth health check failed")
            await asyncio.sleep(self._interval)
