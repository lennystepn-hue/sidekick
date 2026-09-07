"""Generate the Sidekick app icon and the four tray icons as PNG files.

Dependency-free (stdlib only). Everything is drawn with per-pixel signed
distance functions and 1 px analytic anti-aliasing.

Outputs (relative to the repository root, directory is created if missing):
  src-tauri/icons/app-source.png   1024x1024 app icon (feed to `pnpm tauri icon`)
  src-tauri/icons/tray-gray.png    32x32 tray icon, glasses disconnected
  src-tauri/icons/tray-green.png   32x32 tray icon, connected / idle
  src-tauri/icons/tray-blue.png    32x32 tray icon, listening
  src-tauri/icons/tray-yellow.png  32x32 tray icon, waiting for input

Usage:
  py -3 sidecar/tools/gen_icons.py [--out <dir>]
  uv run --project sidecar python sidecar/tools/gen_icons.py
"""

from __future__ import annotations

import argparse
import math
import struct
import sys
import zlib
from pathlib import Path

# Palette (see docs/superpowers/specs/2026-09-07-sidekick-design.md, section 3)
BG = (0x16, 0x1A, 0x22)
ACCENT = (0x7A, 0xA2, 0xF7)
TRAY_COLORS = {
    "gray": (0x6B, 0x72, 0x80),
    "green": (0x9E, 0xCE, 0x6A),
    "blue": (0x7A, 0xA2, 0xF7),
    "yellow": (0xE0, 0xAF, 0x68),
}

RGB = tuple[int, int, int]
RGBA = tuple[float, float, float, float]
TRANSPARENT: RGBA = (0.0, 0.0, 0.0, 0.0)


# --------------------------------------------------------------------------- PNG


def write_png(path: Path, width: int, height: int, rows: list[bytes]) -> None:
    """Write an 8-bit RGBA PNG. `rows` holds `height` byte strings of width*4 bytes."""

    def chunk(tag: bytes, data: bytes) -> bytes:
        return (
            struct.pack(">I", len(data))
            + tag
            + data
            + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)
        )

    raw = b"".join(b"\x00" + row for row in rows)  # filter type 0 per scanline
    ihdr = struct.pack(">IIBBBBB", width, height, 8, 6, 0, 0, 0)
    png = (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", ihdr)
        + chunk(b"IDAT", zlib.compress(raw, 9))
        + chunk(b"IEND", b"")
    )
    path.write_bytes(png)


# --------------------------------------------------------------------------- SDF helpers


def sd_round_rect(px: float, py: float, cx: float, cy: float, hw: float, hh: float, r: float) -> float:
    """Signed distance to a rounded rectangle centred at (cx, cy) with half extents hw/hh."""
    qx = abs(px - cx) - hw + r
    qy = abs(py - cy) - hh + r
    ox = qx if qx > 0.0 else 0.0
    oy = qy if qy > 0.0 else 0.0
    outside = math.hypot(ox, oy)
    inside = min(max(qx, qy), 0.0)
    return outside + inside - r


def sd_capsule(px: float, py: float, ax: float, ay: float, bx: float, by: float, radius: float) -> float:
    """Signed distance to the line segment a-b thickened by `radius`."""
    pax, pay = px - ax, py - ay
    bax, bay = bx - ax, by - ay
    denom = bax * bax + bay * bay
    h = (pax * bax + pay * bay) / denom if denom else 0.0
    h = 0.0 if h < 0.0 else 1.0 if h > 1.0 else h
    return math.hypot(pax - bax * h, pay - bay * h) - radius


def coverage(d: float) -> float:
    """Convert a signed distance (px) into 0..1 coverage with 1 px anti-aliasing."""
    a = 0.5 - d
    return 0.0 if a <= 0.0 else 1.0 if a >= 1.0 else a


def blend(dst: RGBA, src: RGB, a: float) -> RGBA:
    """Source-over compositing of an opaque colour with coverage `a` onto straight-alpha RGBA."""
    if a <= 0.0:
        return dst
    dr, dg, db, da = dst
    out_a = a + da * (1.0 - a)
    if out_a <= 0.0:
        return TRANSPARENT
    r = (src[0] * a + dr * da * (1.0 - a)) / out_a
    g = (src[1] * a + dg * da * (1.0 - a)) / out_a
    b = (src[2] * a + db * da * (1.0 - a)) / out_a
    return (r, g, b, out_a)


def to_bytes(px: RGBA) -> bytes:
    r, g, b, a = px
    return bytes((int(round(r)), int(round(g)), int(round(b)), int(round(a * 255.0))))


# --------------------------------------------------------------------------- app icon


def render_app_icon(size: int = 1024) -> list[bytes]:
    """Dark rounded square with a stylised pair of glasses in the accent colour."""
    s = size / 1024.0
    centre = size / 2.0
    # background rounded square: full bleed, corner radius ~22 %
    bg_r = 225.0 * s
    bg_half = size / 2.0

    # glyph geometry (defined in 1024 space, scaled by s)
    cy = 532.0 * s  # slightly below centre so the raised temples sit visually centred
    lens_hw, lens_hh, lens_r = 165.0 * s, 120.0 * s, 88.0 * s
    lens_dx = 215.0 * s
    stroke = 22.0 * s  # half stroke width -> 44 px outline at 1024
    bridge_y = cy - 62.0 * s
    bridge_half = 52.0 * s
    temple_len_x = 92.0 * s
    temple_rise = 34.0 * s
    temple_r = 20.0 * s

    lens_lx = centre - lens_dx
    lens_rx = centre + lens_dx
    outer_lx = lens_lx - lens_hw + 6.0 * s
    outer_rx = lens_rx + lens_hw - 6.0 * s
    temple_y0 = cy - lens_hh + 44.0 * s

    # bounding box for the glyph so background-only pixels stay cheap
    gy0 = int(cy - lens_hh - stroke - temple_rise - 8)
    gy1 = int(cy + lens_hh + stroke + 8)
    gx0 = int(outer_lx - temple_len_x - temple_r - 8)
    gx1 = int(outer_rx + temple_len_x + temple_r + 8)

    rows: list[bytes] = []
    for y in range(size):
        py = y + 0.5
        row = bytearray()
        in_glyph_row = gy0 <= y <= gy1
        for x in range(size):
            px = x + 0.5
            bg_cov = coverage(sd_round_rect(px, py, centre, centre, bg_half, bg_half, bg_r))
            pixel = blend(TRANSPARENT, BG, bg_cov)
            if in_glyph_row and gx0 <= x <= gx1:
                d_l = abs(sd_round_rect(px, py, lens_lx, cy, lens_hw, lens_hh, lens_r)) - stroke
                d_r = abs(sd_round_rect(px, py, lens_rx, cy, lens_hw, lens_hh, lens_r)) - stroke
                d = d_l if d_l < d_r else d_r
                d_b = sd_capsule(px, py, centre - bridge_half, bridge_y, centre + bridge_half, bridge_y, stroke)
                if d_b < d:
                    d = d_b
                d_tl = sd_capsule(
                    px, py, outer_lx, temple_y0, outer_lx - temple_len_x, temple_y0 - temple_rise, temple_r
                )
                if d_tl < d:
                    d = d_tl
                d_tr = sd_capsule(
                    px, py, outer_rx, temple_y0, outer_rx + temple_len_x, temple_y0 - temple_rise, temple_r
                )
                if d_tr < d:
                    d = d_tr
                pixel = blend(pixel, ACCENT, coverage(d))
            row += to_bytes(pixel)
        rows.append(bytes(row))
    return rows


# --------------------------------------------------------------------------- tray icons


def darken(rgb: RGB, factor: float = 0.55) -> RGB:
    return (int(round(rgb[0] * factor)), int(round(rgb[1] * factor)), int(round(rgb[2] * factor)))


def render_tray_icon(color: RGB, size: int = 32) -> list[bytes]:
    """Filled circle with a 2 px darker ring on a transparent background."""
    centre = size / 2.0
    outer_r = 13.0 * size / 32.0
    ring_w = 2.0 * size / 32.0
    ring = darken(color)
    rows: list[bytes] = []
    for y in range(size):
        py = y + 0.5
        row = bytearray()
        for x in range(size):
            px = x + 0.5
            d = math.hypot(px - centre, py - centre)
            pixel = blend(TRANSPARENT, ring, coverage(d - outer_r))
            pixel = blend(pixel, color, coverage(d - (outer_r - ring_w)))
            row += to_bytes(pixel)
        rows.append(bytes(row))
    return rows


# --------------------------------------------------------------------------- main


def main(argv: list[str] | None = None) -> int:
    repo_root = Path(__file__).resolve().parents[2]
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument(
        "--out",
        type=Path,
        default=repo_root / "src-tauri" / "icons",
        help="output directory (default: <repo>/src-tauri/icons)",
    )
    parser.add_argument("--app-size", type=int, default=1024, help="app icon edge length (default 1024)")
    args = parser.parse_args(argv)

    out: Path = args.out
    out.mkdir(parents=True, exist_ok=True)

    app_path = out / "app-source.png"
    print(f"rendering {app_path.name} ({args.app_size}x{args.app_size}) ...", flush=True)
    write_png(app_path, args.app_size, args.app_size, render_app_icon(args.app_size))

    for name, rgb in TRAY_COLORS.items():
        tray_path = out / f"tray-{name}.png"
        print(f"rendering {tray_path.name} (32x32) ...", flush=True)
        write_png(tray_path, 32, 32, render_tray_icon(rgb, 32))

    print(f"done -> {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
