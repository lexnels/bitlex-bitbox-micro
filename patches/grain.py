"""Granular controls (see src/grain.c): Shape, Grain Sync / Sync Rate, Position. Apply with `mod`, `looper` and `cave`."""
import struct

from thumb import hooker, symbols

hook = hooker(symbols())
IDS = struct.pack("<4H", 0x17D, 0x17E, 0x17F, 0x180)       # Shape, Grain Sync, Sync Rate, Position

PATCHES = [
    hook(0x080AFAC8, 0x080AF5A0, "grain_spawn"),           # grain render: a finished grain spawns the next
    (0x080AFAE8, struct.pack("<I", 0x080CAC00), struct.pack("<I", 0x38008000)),   # grain window table -> MOD_RAM
    # granular pad page (Density, Grain Size, Window, Scatter, Pan Rnd, Speed): + the four after Speed, both variants
    (0x080C7054 + 12, bytes(8), IDS),
    (0x080C7270 + 12, bytes(8), IDS),
]
