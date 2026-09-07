# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec for the Sidekick sidecar (onedir build).

Build from sidecar/:  uv run pyinstaller tools/sidecar.spec --noconfirm
Output: dist/sidekick-sidecar/sidekick-sidecar.exe (+ _internal/)
"""

from pathlib import Path

from PyInstaller.utils.hooks import collect_all, collect_submodules

ROOT = Path(SPECPATH).resolve().parent
PKG = ROOT / "sidekick"

datas = [
    (str(PKG / "sounds"), "sidekick/sounds"),
    (str(PKG / "models"), "sidekick/models"),
    (str(PKG / "prompts"), "sidekick/prompts"),
]
binaries = []
hiddenimports = [
    *collect_submodules("sidekick"),
    "uvicorn.logging",
    "uvicorn.loops.auto",
    "uvicorn.loops.asyncio",
    "uvicorn.protocols.http.auto",
    "uvicorn.protocols.http.h11_impl",
    "uvicorn.protocols.http.httptools_impl",
    "uvicorn.protocols.websockets.auto",
    "uvicorn.protocols.websockets.websockets_impl",
    "uvicorn.lifespan.on",
    "keyring.backends.Windows",
    "keyring.backends.null",
    "comtypes.gen",
]

for package in (
    "faster_whisper",
    "ctranslate2",
    "onnxruntime",
    "claude_agent_sdk",
    "miniaudio",
    "sounddevice",
    "_sounddevice_data",
    "pycaw",
    "comtypes",
    "edge_tts",
    "elevenlabs",
    "keyring",
    "tokenizers",
    "huggingface_hub",
    "psutil",
    "platformdirs",
):
    try:
        d, b, h = collect_all(package)
    except Exception:  # package without data or not installed
        continue
    datas += d
    binaries += b
    hiddenimports += h

a = Analysis(
    [str(ROOT / "tools" / "sidecar_entry.py")],
    pathex=[str(ROOT)],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    runtime_hooks=[],
    excludes=["tkinter", "matplotlib", "IPython", "pytest", "torch", "torchaudio", "PIL"],
    noarchive=False,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="sidekick-sidecar",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=True,
    disable_windowed_traceback=False,
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    name="sidekick-sidecar",
)
